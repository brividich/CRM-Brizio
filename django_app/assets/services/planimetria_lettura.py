"""Leggere una planimetria e proporre dove stanno gli asset.

Sulle piante dell'officina accanto alle macchine c'è quasi sempre una sigla già
presente nella scheda asset: il numero interno, il tag, la matricola o il nome.
Qui si leggono i testi della planimetria con la loro posizione e li si abbina
agli asset; il risultato è solo una **proposta** che una persona conferma
nell'editor della mappa (niente viene scritto da questo modulo).

Fonti del testo, in ordine di affidabilità:

1. **PDF vettoriale** (es. stampato su PDF dal DWG): i testi sono veri e la
   posizione è esatta. La pagina può diventare anche l'immagine della pianta,
   così i punti combaciano per costruzione.
2. **OCR dell'immagine** già caricata (Tesseract, lo stesso dei referti).

Le etichette che non si abbinano da sole possono passare all'AI locale
(Ollama), che sceglie fra gli asset candidati: quelle proposte restano
marcate «AI» e non sono preselezionate.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..models import IT_DEVICE_TYPES, Asset, PlantLayout

logger = logging.getLogger(__name__)

# Etichette per la pagina: da dove viene l'abbinamento.
FONTE_NUMERO_INTERNO = "N. interno"
FONTE_TAG = "Tag"
FONTE_MATRICOLA = "Matricola"
FONTE_NOME = "Nome"
FONTE_SIGLA = "Sigla"
FONTE_AI = "AI locale"

_PESO = {FONTE_NUMERO_INTERNO: 100, FONTE_TAG: 95, FONTE_MATRICOLA: 90, FONTE_SIGLA: 85, FONTE_NOME: 70}
# «Int.233», «N. INT 045», «Nr. 12»: il prefisso non fa parte della sigla
_PREFISSI = re.compile(r"^(N\.?\s*INT\.?|NINT|INT\.?|N\.|NR\.?|NUM\.?|#)\s*", re.IGNORECASE)
_STESSO_PUNTO = 6.0  # letture dello stesso asset più vicine di così (in %) sono un punto solo
_GIA_QUI = 3.0  # entro questa distanza dal marker attuale l'asset è «già qui» (l'etichetta sta accanto al simbolo)
_SPOSTAMENTO_GRANDE = 10.0  # oltre, la proposta non è preselezionata: può essere una legenda o un'altra sigla
_MAX_PAROLE_GRUPPO = 3


class ErroreLettura(Exception):
    """La planimetria non si può leggere (file non valido, OCR assente...)."""


@dataclass
class Parola:
    testo: str
    x: float  # centro, in percentuale della pagina/immagine
    y: float
    riga: tuple = ()  # chiave di riga per unire parole vicine


@dataclass
class Proposta:
    asset_id: int
    nome: str
    numero_interno: str
    tag: str
    categoria: str
    reparto: str
    testo_letto: str
    x: float
    y: float
    fonte: str
    stato: str = "nuovo"  # nuovo | sposta | invariato
    x_attuale: float | None = None
    y_attuale: float | None = None
    altri_punti: int = 0  # stessa sigla letta in altri punti della pianta

    @property
    def spostamento_grande(self) -> bool:
        if self.stato != "sposta" or self.x_attuale is None:
            return False
        return max(abs(self.x - self.x_attuale), abs(self.y - self.y_attuale)) > _SPOSTAMENTO_GRANDE

    @property
    def preselezionata(self) -> bool:
        return (self.fonte != FONTE_AI and self.stato != "invariato" and not self.altri_punti
                and not self.spostamento_grande)


@dataclass
class Risultato:
    fonte_testo: str
    parole_lette: int
    proposte: list[Proposta] = field(default_factory=list)
    non_riconosciute: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)


def normalizza(testo) -> str:
    """Sigla confrontabile: maiuscola, senza prefissi «Int.», spazi, trattini, punti e zeri iniziali.

    Nelle sigle con cifre le lettere che l'OCR confonde con i numeri (I/L → 1,
    O → 0) diventano cifre, sia sulla pianta sia nella scheda asset: «DMI2» = «DM12».
    """
    t = _PREFISSI.sub("", str(testo or "").strip())
    t = re.sub(r"[^0-9A-Z]", "", t.upper())
    if t.isdigit():
        return t.lstrip("0") or "0"
    if any(c.isdigit() for c in t):
        t = t.translate(str.maketrans({"I": "1", "L": "1", "O": "0"}))
    return t


def sigle_in(testo) -> list[str]:
    """Le sigle alfanumeriche dentro un nome o un tag («DM7 - DMG Mori» → DM7, «CNC-DM7-0006» → DM7)."""
    out = []
    for pezzo in re.split(r"[\s\-_/,.;:()]+", str(testo or "")):
        if len(pezzo) >= 3 and any(c.isdigit() for c in pezzo) and any(c.isalpha() for c in pezzo):
            out.append(pezzo)
    return out


# --- lettura -----------------------------------------------------------------

def parole_da_pdf(contenuto: bytes, pagina: int = 0) -> tuple[list[Parola], tuple[float, float]]:
    """Parole del testo vettoriale di una pagina PDF, con il centro in percentuale."""
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=contenuto, filetype="pdf")
    except Exception as exc:
        raise ErroreLettura("Il file non è un PDF leggibile.") from exc
    try:
        if pagina >= doc.page_count:
            raise ErroreLettura(f"Il PDF ha solo {doc.page_count} pagine.")
        page = doc[pagina]
        w, h = page.rect.width, page.rect.height
        parole = []
        for x0, y0, x1, y1, testo, blocco, riga, _n in page.get_text("words"):
            testo = str(testo).strip()
            if testo:
                parole.append(Parola(testo, round((x0 + x1) / 2 / w * 100, 2), round((y0 + y1) / 2 / h * 100, 2),
                                     (blocco, riga)))
        return parole, (w, h)
    finally:
        doc.close()


def pagina_pdf_png(contenuto: bytes, pagina: int = 0, lato_max: int = 4000) -> bytes:
    """La pagina del PDF come PNG, da usare come immagine della planimetria."""
    import fitz

    doc = fitz.open(stream=contenuto, filetype="pdf")
    try:
        page = doc[pagina]
        zoom = min(4.0, lato_max / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
    finally:
        doc.close()


def parole_da_immagine(percorso_immagine: str, timeout: int = 120) -> list[Parola]:
    """OCR dell'immagine con le posizioni delle parole (Tesseract, uscita TSV)."""
    from anagrafica.services.referti_ocr import _ambiente, percorso_tesseract
    from PIL import Image

    exe = percorso_tesseract()
    if not exe:
        raise ErroreLettura("Il riconoscimento del testo (Tesseract) non è installato su questo server.")
    with Image.open(percorso_immagine) as img:
        larghezza, altezza = img.size
        # le sigle sulle piante sono piccole: un'immagine piccola si ingrandisce
        fattore = 2 if max(larghezza, altezza) < 2500 else 1
        lavoro = img.convert("L")
        if fattore > 1:
            lavoro = lavoro.resize((larghezza * fattore, altezza * fattore))
        with tempfile.TemporaryDirectory(prefix="planimetria-ocr-") as tmp:
            ingresso = Path(tmp) / "pianta.png"
            lavoro.save(ingresso)
            uscita = Path(tmp) / "testo"
            try:
                subprocess.run(
                    [exe, str(ingresso), str(uscita), "-l", "ita+eng", "--psm", "11", "tsv"],
                    check=True, capture_output=True, timeout=timeout, env=_ambiente(),
                )
            except subprocess.TimeoutExpired:
                raise ErroreLettura(f"La lettura ha superato {timeout} secondi ed è stata interrotta.") from None
            except subprocess.CalledProcessError:
                # senza i dati della lingua inglese si riprova con il solo italiano
                try:
                    subprocess.run(
                        [exe, str(ingresso), str(uscita), "-l", "ita", "--psm", "11", "tsv"],
                        check=True, capture_output=True, timeout=timeout, env=_ambiente(),
                    )
                except Exception as exc:
                    raise ErroreLettura("Il riconoscimento del testo è fallito su questa immagine.") from exc
            tsv = uscita.with_suffix(".tsv").read_text(encoding="utf-8", errors="replace")
    larghezza_l, altezza_l = larghezza * fattore, altezza * fattore
    parole = []
    for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        testo = (r.get("text") or "").strip()
        try:
            conf = float(r.get("conf") or -1)
        except ValueError:
            conf = -1
        if not testo or conf < 40:
            continue
        x = (int(r["left"]) + int(r["width"]) / 2) / larghezza_l * 100
        y = (int(r["top"]) + int(r["height"]) / 2) / altezza_l * 100
        parole.append(Parola(testo, round(x, 2), round(y, 2), (r.get("block_num"), r.get("par_num"), r.get("line_num"))))
    return parole


# --- abbinamento ---------------------------------------------------------------

def _candidati(parole: list[Parola]) -> list[tuple[str, str, float, float]]:
    """(chiave normalizzata, testo, x, y) per parole singole e gruppi di parole vicine sulla stessa riga."""
    righe: dict[tuple, list[Parola]] = {}
    for p in parole:
        righe.setdefault(p.riga or (id(p),), []).append(p)
    out = []
    for gruppo in righe.values():
        gruppo.sort(key=lambda p: p.x)
        for i in range(len(gruppo)):
            for n in range(1, _MAX_PAROLE_GRUPPO + 1):
                pezzo = gruppo[i:i + n]
                if len(pezzo) < n:
                    break
                testo = " ".join(p.testo for p in pezzo)
                chiave = normalizza(testo)
                if len(chiave) >= 2:
                    out.append((chiave, testo, sum(p.x for p in pezzo) / n, sum(p.y for p in pezzo) / n))
    return out


def nomi_reparti() -> set[str]:
    """Nomi di reparti e aree (e testi collegati) normalizzati: sulla pianta sono etichette di zona, non asset."""
    nomi: set[str] = set()
    try:
        from anagrafica.models import AreaAziendale, Reparto

        from ..models import RepartoAssetCollegato

        for valore in [*Reparto.objects.values_list("nome", flat=True),
                       *AreaAziendale.objects.values_list("nome", flat=True),
                       *RepartoAssetCollegato.objects.values_list("testo", flat=True),
                       *Asset.objects.exclude(reparto="").values_list("reparto", flat=True).distinct()]:
            chiave = normalizza(valore)
            if chiave:
                nomi.add(chiave)
    except Exception:
        logger.debug("Nomi dei reparti non disponibili", exc_info=True)
    return nomi


def _indice_asset(assets, escluse: set[str] = frozenset()) -> dict[str, list[tuple[Asset, str]]]:
    indice: dict[str, list[tuple[Asset, str]]] = {}
    for a in assets:
        valori = [(a.internal_number, FONTE_NUMERO_INTERNO), (a.asset_tag, FONTE_TAG),
                  (a.serial_number, FONTE_MATRICOLA), (a.name, FONTE_NOME)]
        valori += [(s, FONTE_SIGLA) for s in sigle_in(a.name) + sigle_in(a.asset_tag)]
        for valore, fonte in valori:
            chiave = normalizza(valore)
            # sigle di una cifra o due lettere abbinerebbero quote e numeri di stanza;
            # i numeri interni di due cifre («Int.033» → 33) sì, perché sulle piante ci sono
            if len(chiave) < 2 or (len(chiave) == 2 and not (fonte == FONTE_NUMERO_INTERNO and chiave.isdigit())):
                continue
            # «CN5» nel nome dell'Access Point è il reparto, non la macchina
            if fonte in (FONTE_SIGLA, FONTE_NOME) and chiave in escluse:
                continue
            voci = indice.setdefault(chiave, [])
            if all(x[0].pk != a.pk for x in voci):
                voci.append((a, fonte))
    return indice


def assets_candidati():
    """Asset che possono stare su una planimetria: non IT e non dismessi."""
    return (
        Asset.objects.exclude(asset_type__in=IT_DEVICE_TYPES)
        .exclude(status=Asset.STATUS_RETIRED)
        .select_related("asset_category")
    )


def _sembra_sigla(testo: str) -> bool:
    chiave = normalizza(testo)
    return 2 <= len(chiave) <= 20 and any(c.isdigit() for c in chiave)


def abbina(layout: PlantLayout, parole: list[Parola], *, usa_ai: bool = False, fonte_testo: str = "") -> Risultato:
    """Proposte di posizione per gli asset riconosciuti fra le parole della pianta."""
    from .plant_layout_image import marker_is_unplaced

    risultato = Risultato(fonte_testo=fonte_testo, parole_lette=len(parole))
    assets = list(assets_candidati())
    indice = _indice_asset(assets, nomi_reparti())
    trovati: dict[int, list[tuple[Asset, str, str, float, float]]] = {}
    usate: set[str] = set()
    for chiave, testo, x, y in _candidati(parole):
        voci = indice.get(chiave)
        if not voci or len(voci) > 1:  # sigla di più asset: ambigua, meglio non proporla
            continue
        asset, fonte = voci[0]
        trovati.setdefault(asset.pk, []).append((asset, fonte, testo, x, y))
        usate.add(normalizza(testo))

    attuali = {
        m.asset_id: m for m in layout.markers.all() if not marker_is_unplaced(m)
    }
    for asset_id, letture in trovati.items():
        letture.sort(key=lambda r: -_PESO[r[1]])
        asset, fonte, testo, x, y = letture[0]
        # sigla e numero interno scritti uno accanto all'altro sono lo stesso punto
        lontane = [r for r in letture if abs(r[3] - x) > _STESSO_PUNTO or abs(r[4] - y) > _STESSO_PUNTO]
        risultato.proposte.append(_proposta(asset, fonte, testo, x, y, attuali.get(asset_id), altri=len(lontane)))

    da_ai = sorted({
        p.testo for p in parole
        if _sembra_sigla(p.testo) and normalizza(p.testo) not in usate
    })
    if usa_ai and da_ai:
        gia = set(trovati)
        for proposta in _abbina_con_ai(da_ai, parole, [a for a in assets if a.pk not in gia], attuali):
            risultato.proposte.append(proposta)
            da_ai = [t for t in da_ai if t != proposta.testo_letto]
    risultato.non_riconosciute = da_ai[:200]
    ordine = {"sposta": 0, "nuovo": 1, "invariato": 2}
    risultato.proposte.sort(key=lambda p: (p.fonte == FONTE_AI, ordine[p.stato], p.nome.casefold()))
    return risultato


def _proposta(asset: Asset, fonte: str, testo: str, x: float, y: float, marker, altri: int = 0) -> Proposta:
    stato, xa, ya = "nuovo", None, None
    if marker is not None:
        xa, ya = float(marker.x_percent), float(marker.y_percent)
        stato = "invariato" if abs(xa - x) <= _GIA_QUI and abs(ya - y) <= _GIA_QUI else "sposta"
    return Proposta(
        asset_id=asset.pk, nome=asset.name, numero_interno=asset.internal_number or "", tag=asset.asset_tag or "",
        categoria=asset.asset_category.label if asset.asset_category_id else asset.get_asset_type_display(),
        reparto=asset.reparto or "", testo_letto=testo, x=round(x, 2), y=round(y, 2), fonte=fonte,
        stato=stato, x_attuale=xa, y_attuale=ya, altri_punti=altri,
    )


def _abbina_con_ai(etichette: list[str], parole: list[Parola], assets: list[Asset], attuali) -> list[Proposta]:
    """Chiede all'AI locale di abbinare le etichette rimaste agli asset (JSON, poi verificato)."""
    if not assets:
        return []
    etichette = etichette[:60]
    elenco = [
        {"id": a.pk, "nome": a.name, "n_int": a.internal_number or "", "tag": a.asset_tag or "",
         "matricola": a.serial_number or "", "categoria": a.asset_category.label if a.asset_category_id else ""}
        for a in assets[:400]
    ]
    prompt = (
        "Sei un assistente che abbina le sigle lette su una planimetria industriale agli asset del registro.\n"
        "Per ogni sigla scegli l'asset solo se sei sicuro (stesso numero interno, tag o matricola scritto in modo "
        "diverso, abbreviazioni evidenti). Se non sei sicuro non includerla.\n"
        "Rispondi SOLO con JSON: {\"abbinamenti\": [{\"sigla\": \"...\", \"asset_id\": 123}]}\n\n"
        f"Sigle: {json.dumps(etichette, ensure_ascii=False)}\n\n"
        f"Asset: {json.dumps(elenco, ensure_ascii=False)}"
    )
    try:
        from ai_assistant.services import chat_with_ollama

        risposta = getattr(chat_with_ollama(prompt), "content", "") or ""
    except Exception:
        logger.warning("Planimetria: AI locale non disponibile", exc_info=True)
        return []
    m = re.search(r"\{.*\}", risposta, re.DOTALL)
    try:
        dati = json.loads(m.group(0) if m else risposta)
    except (ValueError, TypeError):
        logger.info("Planimetria: risposta AI non in JSON")
        return []
    per_id = {a.pk: a for a in assets}
    posizioni = {}
    for p in parole:
        posizioni.setdefault(p.testo, (p.x, p.y))
    out, usati = [], set()
    for voce in (dati.get("abbinamenti") or []) if isinstance(dati, dict) else []:
        try:
            sigla, asset_id = str(voce.get("sigla") or ""), int(voce.get("asset_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        asset = per_id.get(asset_id)
        # solo sigle che c'erano davvero e asset dell'elenco: l'AI non inventa posizioni
        if asset is None or sigla not in posizioni or asset_id in usati:
            continue
        usati.add(asset_id)
        x, y = posizioni[sigla]
        out.append(_proposta(asset, FONTE_AI, sigla, x, y, attuali.get(asset_id)))
    return out
