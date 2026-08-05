"""Lettura della scansione del foglio firme (catena dell'evidenza, anello 6).

Il punto di tutto: **non serve leggere le firme, serve vedere se ci sono.**

Il foglio l'ha generato il portale, quindi l'elenco e l'ordine delle righe sono
congelati nel foglio emesso e la posizione di ogni cella è registrata in
millimetri. Riconoscere *chi* ha firmato sarebbe un problema difficile e
inutile: quello che conta è se il rettangolo della riga 7 contiene inchiostro.
Diventa una misura su rettangoli di posizione nota — geometria e una soglia.

Il procedimento:

1. la scansione viene rasterizzata (PDF) o aperta (immagine) in scala di grigi;
2. si cercano i **quattro marcatori d'angolo**, che dicono dove sta il foglio
   dentro l'immagine anche se è storto o di scala diversa;
3. se il foglio è ruotato lo si raddrizza e si ricercano i marcatori;
4. dai marcatori si costruisce la corrispondenza millimetri → pixel;
5. per ogni cella si misura quanto inchiostro contiene.

Il risultato è una **proposta**, mai una registrazione: la presenza a un corso è
un atto con valore legale e la conferma resta di una persona. Le celle dubbie
sono marcate come tali proprio perché qualcuno le guardi.

Nessuna dipendenza esterna: pymupdf e pillow sono già nel progetto.
"""
from __future__ import annotations

from io import BytesIO

__all__ = [
    "SOGLIA_FIRMATO",
    "SOGLIA_DUBBIA",
    "ErroreLettura",
    "analizza_scansione",
    "apri_scansione",
    "trova_marcatori",
]

# Frazione di pixel scuri dentro la cella, al netto del bordo stampato.
# Una cella bianca sta a zero; una firma copre qualche punto percentuale.
SOGLIA_FIRMATO = 0.010
SOGLIA_DUBBIA = 0.004

# Quanto si rientra dal bordo della cella prima di misurare: il rettangolo
# stampato è nero e falserebbe ogni conteggio.
INSET_MM = 1.4

# Lato della finestra d'angolo in cui cercare il marcatore. Deve contenerlo con
# margine e non arrivare all'intestazione, che parte a 20 mm.
FINESTRA_MARCATORE_MM = 18.0

DPI_RASTER = 200


class ErroreLettura(Exception):
    """La scansione non è utilizzabile: il chiamante deve dirlo all'utente."""


def apri_scansione(contenuto: bytes, nome_file: str = ""):
    """Prima pagina della scansione come immagine in scala di grigi.

    Accetta un PDF (rasterizzato) o un'immagine. Solo la prima pagina: un
    foglio firme è una pagina, e leggere le altre confonderebbe soltanto.
    """
    from PIL import Image

    pare_pdf = contenuto[:5] == b"%PDF" or nome_file.lower().endswith(".pdf")
    if pare_pdf:
        import fitz

        try:
            doc = fitz.open(stream=contenuto, filetype="pdf")
        except Exception as exc:  # pragma: no cover - file corrotto
            raise ErroreLettura("Il PDF non è leggibile.") from exc
        try:
            if not doc.page_count:
                raise ErroreLettura("Il PDF non ha pagine.")
            pix = doc[0].get_pixmap(dpi=DPI_RASTER)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            doc.close()
    else:
        try:
            img = Image.open(BytesIO(contenuto))
            img.load()
        except Exception as exc:
            raise ErroreLettura("Il file non è un'immagine né un PDF leggibile.") from exc

    return img.convert("L")


def _soglia_scuro(img) -> int:
    """Soglia di «pixel scuro» adattata alla scansione.

    Un valore fisso non regge: una fotocopia grigia e una scansione brillante
    hanno fondi lontanissimi. Si parte dal fondo effettivo e si scende.
    """
    istogramma = img.histogram()
    totale = sum(istogramma) or 1
    # Livello sotto cui sta il 90% dei pixel più scuri esclusi: approssima il fondo.
    cumulato = 0
    fondo = 255
    for livello, quanti in enumerate(istogramma):
        cumulato += quanti
        if cumulato >= totale * 0.5:
            fondo = livello
            break
    return max(40, min(200, fondo - 60))


def trova_marcatori(img) -> dict[str, tuple[float, float]]:
    """Centro dei quattro quadrati d'angolo, in pixel.

    Si cerca il baricentro dei pixel scuri dentro una finestra d'angolo stretta:
    lì il marcatore è l'unica cosa nera, quindi non serve isolare forme.
    """
    larghezza, altezza = img.size
    if larghezza < 200 or altezza < 200:
        raise ErroreLettura("La scansione è troppo piccola per essere letta.")

    # La finestra è espressa in mm sul foglio: si converte usando la dimensione
    # dell'immagine, assumendo che la pagina occupi la scansione (vero per una
    # scansione di un A4).
    fin_x = int(larghezza * FINESTRA_MARCATORE_MM / 210.0)
    fin_y = int(altezza * FINESTRA_MARCATORE_MM / 297.0)
    soglia = _soglia_scuro(img)
    px = img.load()

    def baricentro(x0: int, y0: int, x1: int, y1: int) -> tuple[float, float] | None:
        somma_x = somma_y = quanti = 0
        for y in range(y0, y1):
            for x in range(x0, x1):
                if px[x, y] < soglia:
                    somma_x += x
                    somma_y += y
                    quanti += 1
        if quanti < 20:
            return None
        return somma_x / quanti, somma_y / quanti

    angoli = {
        "alto_sx": (0, 0, fin_x, fin_y),
        "alto_dx": (larghezza - fin_x, 0, larghezza, fin_y),
        "basso_sx": (0, altezza - fin_y, fin_x, altezza),
        "basso_dx": (larghezza - fin_x, altezza - fin_y, larghezza, altezza),
    }
    trovati: dict[str, tuple[float, float]] = {}
    for nome, box in angoli.items():
        centro = baricentro(*box)
        if centro is None:
            raise ErroreLettura(
                f"Non trovo il riferimento d'angolo «{nome.replace('_', ' ')}». "
                "Rifai la scansione inquadrando il foglio per intero."
            )
        trovati[nome] = centro
    return trovati


def _angolo_gradi(marcatori: dict) -> float:
    """Inclinazione del foglio, dai due marcatori in alto."""
    import math

    (x1, y1), (x2, y2) = marcatori["alto_sx"], marcatori["alto_dx"]
    return math.degrees(math.atan2(y2 - y1, x2 - x1))


def _mappa_mm_px(marcatori: dict, geometria: dict):
    """Funzione che porta millimetri sul foglio in pixel sull'immagine."""
    larghezza_mm, altezza_mm = geometria.get("pagina_mm", [210.0, 297.0])
    lato = float(geometria.get("marcatore_mm", 6.0))
    margine = float(geometria.get("margine_marcatore_mm", 8.0))
    centro = margine + lato / 2.0

    x_sx = (marcatori["alto_sx"][0] + marcatori["basso_sx"][0]) / 2
    x_dx = (marcatori["alto_dx"][0] + marcatori["basso_dx"][0]) / 2
    y_alto = (marcatori["alto_sx"][1] + marcatori["alto_dx"][1]) / 2
    y_basso = (marcatori["basso_sx"][1] + marcatori["basso_dx"][1]) / 2

    span_mm_x = larghezza_mm - 2 * centro
    span_mm_y = altezza_mm - 2 * centro
    if span_mm_x <= 0 or span_mm_y <= 0 or x_dx <= x_sx or y_basso <= y_alto:
        raise ErroreLettura("I riferimenti d'angolo non sono coerenti: scansione inutilizzabile.")

    scala_x = (x_dx - x_sx) / span_mm_x
    scala_y = (y_basso - y_alto) / span_mm_y

    def in_pixel(x_mm: float, y_mm: float) -> tuple[float, float]:
        return (x_sx + (x_mm - centro) * scala_x,
                y_alto + (y_mm - centro) * scala_y)

    return in_pixel, scala_x, scala_y


def _frazione_scura(img, box: tuple[int, int, int, int], soglia: int) -> float:
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return 0.0
    ritaglio = img.crop((x0, y0, x1, y1))
    istogramma = ritaglio.histogram()
    totale = sum(istogramma) or 1
    scuri = sum(istogramma[: soglia + 1])
    return scuri / totale


def analizza_scansione(foglio, contenuto: bytes, nome_file: str = "") -> dict:
    """Legge la scansione e propone chi ha firmato.

    Ritorna un dizionario con l'esito per riga. **È una proposta**: la scrittura
    delle presenze resta un gesto umano, perché la presenza a un corso è un atto
    con valore legale e non si autocertifica da una misura di pixel.
    """
    geometria = foglio.geometria or {}
    celle = geometria.get("celle") or []
    if not celle:
        raise ErroreLettura(
            "Questo foglio non ha una geometria registrata: è stato emesso prima "
            "della lettura automatica, oppure non aveva iscritti."
        )

    img = apri_scansione(contenuto, nome_file)
    marcatori = trova_marcatori(img)

    # Raddrizzamento: sotto il quarto di grado non vale la pena, la cella ha
    # margine a sufficienza.
    inclinazione = _angolo_gradi(marcatori)
    if abs(inclinazione) > 0.25:
        img = img.rotate(inclinazione, resample=2, fillcolor=255, expand=False)
        marcatori = trova_marcatori(img)
        inclinazione_residua = _angolo_gradi(marcatori)
    else:
        inclinazione_residua = inclinazione

    in_pixel, scala_x, scala_y = _mappa_mm_px(marcatori, geometria)
    soglia = _soglia_scuro(img)
    larghezza, altezza = img.size

    per_riga: dict[int, dict] = {}
    for cella in celle:
        x0, y0 = in_pixel(cella["x_mm"] + INSET_MM, cella["y_mm"] + INSET_MM)
        x1, y1 = in_pixel(cella["x_mm"] + cella["w_mm"] - INSET_MM,
                          cella["y_mm"] + cella["h_mm"] - INSET_MM)
        box = (max(0, int(x0)), max(0, int(y0)),
               min(larghezza, int(x1)), min(altezza, int(y1)))
        frazione = _frazione_scura(img, box, soglia)

        riga = per_riga.setdefault(cella["riga"], {
            "riga": cella["riga"],
            "legacy_id": cella["legacy_id"],
            "nome": "",
            "ingresso": False, "uscita": False,
            "frazione_ingresso": 0.0, "frazione_uscita": 0.0,
            "dubbia": False,
        })
        riga[f"frazione_{cella['campo']}"] = round(frazione, 5)
        riga[cella["campo"]] = frazione >= SOGLIA_FIRMATO
        if SOGLIA_DUBBIA <= frazione < SOGLIA_FIRMATO:
            riga["dubbia"] = True

    nomi = {r.get("n"): r.get("nome", "") for r in (foglio.righe or [])}
    for numero, riga in per_riga.items():
        riga["nome"] = nomi.get(numero, f"#{riga['legacy_id']}")

    righe = [per_riga[k] for k in sorted(per_riga)]
    return {
        "foglio": foglio,
        "righe": righe,
        "n_firmati": sum(1 for r in righe if r["ingresso"] or r["uscita"]),
        "n_dubbie": sum(1 for r in righe if r["dubbia"]),
        "inclinazione": round(inclinazione, 2),
        "inclinazione_residua": round(inclinazione_residua, 2),
        "soglia_scuro": soglia,
        "dimensione_px": [larghezza, altezza],
    }
