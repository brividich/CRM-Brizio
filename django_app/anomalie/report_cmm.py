"""Lettura delle righe di un protocollo ZEISS (PiWeb / CALYPSO) da uno screenshot.

Il controllore cattura con lo strumento di cattura le righe del report che gli
interessano e le incolla nella scheda dell'anomalia: qui l'immagine passa da
Tesseract (OCR, nessun salvataggio) e ogni riga diventa una *proposta* di misura
(caratteristica, limiti, rilevato, dove) che il controllore conferma o scarta.

Riga tipica del protocollo::

    ■ 178,00   Length   4,0539   4,0000   0,1000   0,0000   0,0539   [eccedenza]
      nome     tipo     misurato nominale toll.+   toll.-   scostam.

Il nome della caratteristica puo' essere numerico («178,00», «180,00 - 148,00») o
con testo («163,01 Dia G»): per non confonderlo con i valori si cerca la sequenza di
cinque numeri in cui ``misurato - nominale = scostamento``; cio' che sta prima e' il
nome, cio' che segue (l'eccedenza sopra la barra) si ignora.
"""
from __future__ import annotations

import csv
import io
import re
import subprocess
import tempfile
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_RIGHE = 60

# Tipo del protocollo (etichetta sopra il simbolo) -> caratteristica della scheda.
TIPI_ZEISS = {
    "length": "lunghezza", "distance": "quota", "width": "quota", "diameter": "diametro", "radius": "raggio",
    "angle": "angolo", "position": "posizione", "parallelism": "parallelismo", "perpendicularity": "perpendicolarita",
    "angularity": "perpendicolarita", "concentricity": "concentricita", "coaxiality": "concentricita",
    "symmetry": "simmetria", "flatness": "planarita", "straightness": "planarita", "roundness": "circolarita",
    "circularity": "circolarita", "cylindricity": "circolarita", "runout": "oscillazione",
    "totalrunout": "oscillazione", "profile": "profilo", "lineprofile": "profilo", "surfaceprofile": "profilo",
}
# I valori del protocollo hanno sempre 4 decimali (4,0539 · 0,1000 · -0,0090): cosi' non si
# confondono con il nome della caratteristica (178,00). L'OCR a volte perde la virgola
# («01000», «12519842»): una cifra pura di almeno 4 caratteri vale /10000.
_VAL = re.compile(r"^[-−–]?\d+[.,]\d{3,4}$")  # 3 decimali: una cifra persa dall'OCR
_CIFRE = re.compile(r"^[-−–]?\d{4,9}$")
_NOME = re.compile(r"^\d{2,4}[A-Z]?[.,]\d{2}$|^\d{5,6}$")  # «175,03» o «17503» senza virgola
_PAROLA_NOME = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$|^[-–]$|^\d{2,4}[A-Z]?[.,]\d{2}$")


class ErroreReport(Exception):
    """Messaggio leggibile per il controllore."""


def _num(token: str) -> float:
    return float(token.replace("−", "-").replace("–", "-").replace(",", "."))


def _valore(token: str) -> float | None:
    """Valore a 4 decimali del protocollo, anche senza virgola; None se non lo e'."""
    t = token.replace("−", "-").replace("–", "-").replace(":", ",").strip(".;")
    if _VAL.match(t):
        return _num(t)
    if _CIFRE.match(t):
        segno = -1 if t.startswith("-") else 1
        return segno * int(t.lstrip("-")) / 10000
    return None


def _unisci_spezzati(token: list[str]) -> list[str]:
    """«4 0539» (virgola letta come spazio) -> «4,0539»."""
    out: list[str] = []
    for t in token:
        if out and re.fullmatch(r"\d{4}", t) and re.fullmatch(r"-?\d{1,4}", out[-1]):
            out[-1] = f"{out[-1]},{t}"
        else:
            out.append(t)
    return out


def _fmt(valore: float) -> str:
    testo = f"{valore:.4f}".rstrip("0").rstrip(".")
    return "0" if testo in ("-0", "") else testo


def _tipo(parola: str) -> str:
    """Etichetta del tipo anche se l'OCR la storpia («Lorgth» -> length, «Daymater» -> diameter)."""
    import difflib

    chiave = re.sub(r"[^a-z]", "", parola.lower())
    if len(chiave) < 4:
        return ""
    if chiave in TIPI_ZEISS:
        return chiave
    simili = difflib.get_close_matches(chiave, list(TIPI_ZEISS), n=1, cutoff=0.6)
    return simili[0] if simili else ""


def leggi_riga(testo: str) -> dict | None:
    """Una riga di testo del protocollo -> dati grezzi, None se non e' una riga di misura."""
    token = _unisci_spezzati([t.strip(";") for t in testo.replace("\t", " ").split() if t.strip(";")])
    numeri = [(i, v) for i, v in ((i, _valore(t)) for i, t in enumerate(token)) if v is not None]
    # Cinque valori consecutivi con misurato - nominale = scostamento.
    for k in range(len(numeri) - 4):
        (ia, a), (_in, n), (_ip, p), (_im, m), (_id, d) = numeri[k:k + 5]
        if abs((a - n) - d) <= max(0.0011, abs(d) * 0.002):
            return {"nome": _nome(token[:ia]), "tipo": _tipo_in_riga(token[:ia]), "simbolo": _simbolo_in_riga(token[:ia]),
                    "misurato": a, "nominale": n, "tol_sup": p, "tol_inf": m, "scostamento": d, "da_verificare": False}
    # Scostamento letto male: con il nome della caratteristica davanti si prendono i primi
    # quattro valori dopo il nome e lo scostamento si ricalcola (riga da controllare).
    inizio = next((i for i, t in enumerate(token) if _NOME.match(t)), None)
    if inizio is not None:
        dopo = [(i, v) for i, v in numeri if i > inizio]
        if len(dopo) >= 4:
            (ia, a), (_in, n), (_ip, p), (_im, m) = dopo[:4]
            return {"nome": _nome(token[:ia]), "tipo": _tipo_in_riga(token[:ia]), "simbolo": _simbolo_in_riga(token[:ia]),
                    "misurato": a, "nominale": n, "tol_sup": p, "tol_inf": m, "scostamento": round(a - n, 4),
                    "da_verificare": True}
    return None


def _tipo_in_riga(prima: list[str]) -> str:
    """Etichetta del tipo finita sulla riga dei valori (es. «Length» accanto al nome)."""
    for t in prima:
        if not _NOME.match(t) and len(t) >= 4 and _tipo(t):
            return _tipo(t)
    return ""


def _simbolo_in_riga(prima: list[str]) -> str:
    """Tipo dal simbolo letto come testo subito prima dei valori («Y» = ⊕ posizione…)."""
    return _tipo_da_simbolo(prima[-1]) if prima and not _NOME.match(prima[-1]) else ""


# Abbreviazioni nel nome della caratteristica («163,01 Dia G», «172,00 Pos C»).
_ABBREVIAZIONI = (("dia", "diameter"), ("pos", "position"), ("perp", "perpendicularity"), ("conc", "concentricity"),
                  ("dist", "distance"), ("par", "parallelism"), ("run", "runout"), ("flat", "flatness"),
                  ("rad", "radius"), ("ang", "angle"), ("sym", "symmetry"), ("round", "roundness"))


def _tipo_da_nome(nome: str) -> str:
    for parola in nome.split()[1:]:
        p = parola.lower()
        for abbr, tipo in _ABBREVIAZIONI:
            if p.startswith(abbr):
                return tipo
    return ""


# Simboli del protocollo letti dall'OCR come testo -> tipo (ultima risorsa, dopo etichetta e nome).
_SIMBOLI_TIPO = (
    # ricavate da letture vere di Tesseract sui protocolli (⊕ -> «Q», «Q}»; lunghezza -> «?», «L:%»…)
    (re.compile(r"^[QO][}\])]?[.,]?$|^(Y|\+|®|@|\$|&|©|⊕|\(\+\))$"), "position"),
    (re.compile(r"^\?$|^L[:;]|^9\?$|^(of|ol|o\]|q)$"), "length"),
    (re.compile(r"//|/'|^(J/|/l|ll|II|f/|1/)$"), "parallelism"),
    (re.compile(r"^(1|L|_L|⊥|J_|_l_)$"), "perpendicularity"),
    (re.compile(r"^(%\)|\(%\)\}?|\(%\)|%|Ø|ø|0\)|\(\)|\(o\))$"), "diameter"),
    (re.compile(r"^(/|7|f)$"), "runout"),
    (re.compile(r"^(\[|\(@\)|@\)|◎)$"), "concentricity"),
)


def _tipo_da_simbolo(token: str) -> str:
    for regex, tipo in _SIMBOLI_TIPO:
        if regex.match(token or ""):
            return tipo
    return ""


def _nome(prima: list[str]) -> str:
    """Nome della caratteristica dai token prima dei valori: dal primo «178,00» in poi,
    senza il pallino iniziale e senza il simbolo letto come testo subito prima dei valori."""
    inizio = next((i for i, t in enumerate(prima) if _NOME.match(t)), None)
    if inizio is None:
        return ""
    parti = prima[inizio:]
    if len(parti) > 1 and not _NOME.match(parti[-1]) and (len(parti[-1]) <= 2 or not _PAROLA_NOME.match(parti[-1])):
        parti = parti[:-1]  # simbolo del tipo (⊕ ∅ // …) letto come «Y», «of», «%)»
    parti = [t for t in parti if _PAROLA_NOME.match(t) or re.fullmatch(r"\d{5,6}", t)]
    if parti and re.fullmatch(r"\d{5,6}", parti[0]):
        parti[0] = f"{parti[0][:-2]},{parti[0][-2:]}"  # 17503 -> 175,03
    return " ".join(parti).strip(" -")


def righe_da_testo(linee: list[str]) -> list[dict]:
    """Righe del protocollo da righe di testo (OCR o testo incollato), con sezione e tipo.

    Il tipo («Length», «Position»…) nel protocollo e' scritto piccolo sopra il simbolo:
    l'OCR lo restituisce spesso su una riga a parte, che vale per la riga di misura dopo.
    """
    out: list[dict] = []
    sezione = ""
    tipo_sospeso = ""
    for linea in linee:
        testo = " ".join(str(linea or "").split())
        if not testo:
            continue
        riga = leggi_riga(testo)
        if riga is None and any(_NOME.match(t) for t in testo.split()[:3]):
            tipo_sospeso = ""  # riga di misura illeggibile: il tipo in sospeso era suo
            continue
        if riga is None:
            parole = testo.split()
            # etichetta del tipo, anche spezzata dall'OCR («T engh e» -> length)
            tipo = (_tipo(parole[0]) or _tipo("".join(parole))) if parole and len(parole) <= 4 else ""
            lettere = [c for c in testo if c.isalpha()]
            maiuscole = sum(1 for c in lettere if c.isupper())
            if tipo and len(parole) <= 4:
                tipo_sospeso = tipo
            elif (len(lettere) >= 5 and maiuscole / len(lettere) >= 0.85 and re.search(r"[A-Z]{3}", testo)
                  and not re.search(r"\b(NAME|ACTUAL|NOMINAL)\b", testo.upper())):
                sezione = testo.title()
            continue
        # Priorità: abbreviazione nel nome («Dia», «Pos»), etichetta sulla riga o sopra, simbolo letto come testo.
        riga["tipo"] = _tipo_da_nome(riga["nome"]) or riga.get("tipo") or tipo_sospeso or riga.get("simbolo") or ""
        tipo_sospeso = ""
        riga["sezione"] = sezione
        out.append(riga)
        if len(out) >= MAX_RIGHE:
            break
    return out


def proposta_misura(riga: dict) -> dict:
    """Riga del protocollo -> misura della scheda (stessi campi di dettaglio_controllo)."""
    car = TIPI_ZEISS.get(riga.get("tipo") or "", "altro")
    n, p, m, a = riga["nominale"], riga["tol_sup"], riga["tol_inf"], riga["misurato"]
    # Toll. negativa nel protocollo: con segno (-0,2500) o 0. Limiti = nominale + tolleranze.
    inf = m if m <= 0 else -m
    if n == 0 and inf == 0:
        misura = {"modo": "max", "nom": "", "a": _fmt(p), "b": ""}
    else:
        misura = {"modo": "minmax", "nom": _fmt(n), "a": _fmt(n + inf), "b": _fmt(n + p)}
    d = riga["scostamento"]
    fuori = d > p + 1e-9 or d < inf - 1e-9
    dove = " · ".join(x for x in (f"car. {riga['nome']}" if riga.get("nome") else "", riga.get("sezione") or "") if x)
    return {
        "car": car, "nome": "" if car != "altro" else (riga.get("tipo") or "Misura"),
        **misura, "ril": _fmt(a), "dove": dove[:120],
        "fuori": fuori, "scostamento": d, "tipo_zeiss": riga.get("tipo") or "",
        "da_verificare": bool(riga.get("da_verificare")), "caratteristica": riga.get("nome") or "",
    }


def _ocr_linee(contenuto: bytes, timeout: int = 60, *, netto: bool = False) -> list[str]:
    """OCR dello screenshot: righe di testo ricostruite dalle posizioni delle parole.

    ``netto`` passa l'immagine a bianco/nero: aiuta sulle catture piu' grandi, peggiora
    su quelle piccole. ``leggi_screenshot`` le prova entrambe e tiene la riga coerente.
    """
    from PIL import Image

    from anagrafica.services.referti_ocr import _ambiente, percorso_tesseract

    exe = percorso_tesseract()
    if not exe:
        raise ErroreReport("Il riconoscimento del testo (Tesseract) non è installato su questo server.")
    try:
        img = Image.open(io.BytesIO(contenuto))
        img.load()
    except Exception as exc:
        raise ErroreReport("L'immagine incollata non si riesce ad aprire.") from exc
    larghezza, altezza = img.size
    # Le catture dello schermo hanno testo piccolo: si ingrandisce per Tesseract.
    # Un «1» sottile dopo la virgola sparisce a bassa risoluzione: ingrandire, rendere
    # nitido e passare a bianco/nero aiuta Tesseract sulle cifre.
    from PIL import ImageFilter, ImageOps

    lato = max(larghezza, altezza)
    fattore = 4 if lato < 1400 else 3 if lato < 2200 else 2 if lato < 3200 else 1
    lavoro = ImageOps.autocontrast(img.convert("L"))
    if fattore > 1:
        lavoro = lavoro.resize((larghezza * fattore, altezza * fattore), Image.LANCZOS)
    lavoro = lavoro.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=2))
    if netto:
        lavoro = lavoro.point(lambda v: 255 if v > 165 else 0)
    with tempfile.TemporaryDirectory(prefix="report-cmm-") as tmp:
        ingresso = Path(tmp) / "report.png"
        lavoro.save(ingresso)
        uscita = Path(tmp) / "testo"
        try:
            subprocess.run([exe, str(ingresso), str(uscita), "-l", "eng", "--psm", "6", "tsv"],
                           check=True, capture_output=True, timeout=timeout, env=_ambiente())
        except subprocess.TimeoutExpired:
            raise ErroreReport("La lettura dell'immagine ha impiegato troppo ed è stata interrotta.") from None
        except subprocess.CalledProcessError:
            try:
                subprocess.run([exe, str(ingresso), str(uscita), "--psm", "6", "tsv"],
                               check=True, capture_output=True, timeout=timeout, env=_ambiente())
            except Exception as exc:
                raise ErroreReport("Il riconoscimento del testo è fallito su questa immagine.") from exc
        tsv = uscita.with_suffix(".tsv").read_text(encoding="utf-8", errors="replace")
    parole = []
    for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        testo = (r.get("text") or "").strip()
        if not testo:
            continue
        try:
            sx, top, alt = int(r.get("left") or 0), int(r.get("top") or 0), int(r.get("height") or 0)
        except ValueError:
            continue
        parole.append((top + alt / 2, alt, sx, testo))
    return righe_da_parole(parole)


def righe_da_parole(parole: list[tuple[float, int, int, str]]) -> list[str]:
    """Righe di testo dalle parole ``(centro_y, altezza, x, testo)``.

    Non ci si fida delle righe di Tesseract: con righe del protocollo fitte ne unisce
    due in una (e si leggeva solo la prima). Le parole con il centro alla stessa
    altezza (entro mezza altezza tipica) formano una riga, ordinata da sinistra.
    """
    if not parole:
        return []
    altezze = sorted(a for _c, a, _x, _t in parole if a > 0)
    tipica = altezze[len(altezze) // 2] if altezze else 10
    soglia = max(3.0, tipica * 0.5)
    linee: list[list[tuple[float, int, int, str]]] = []
    for p in sorted(parole):
        if linee:
            centro = sum(q[0] for q in linee[-1]) / len(linee[-1])
            if abs(p[0] - centro) <= soglia:
                linee[-1].append(p)
                continue
        linee.append([p])
    return [" ".join(t for _c, _a, _x, t in sorted(linea, key=lambda q: q[2])) for linea in linee]


def leggi_screenshot(contenuto: bytes) -> dict:
    """Screenshot -> ``{"righe": [misure proposte], "testo": [righe OCR]}``."""
    if not contenuto:
        raise ErroreReport("Nessuna immagine ricevuta.")
    if len(contenuto) > MAX_BYTES:
        raise ErroreReport("L'immagine è troppo grande: cattura solo le righe che servono.")
    linee = _ocr_linee(contenuto)
    righe = unisci_letture(righe_da_testo(linee), righe_da_testo(_ocr_linee(contenuto, netto=True)))
    return {"righe": [proposta_misura(r) for r in righe], "testo": linee[:80]}


def _affidabilita(riga: dict) -> int:
    """Quanto e' credibile una riga letta: coerente con lo scostamento, banda di tolleranza non nulla, tipo noto."""
    punti = 0 if riga.get("da_verificare") else 4
    if not (riga["tol_sup"] == 0 and riga["tol_inf"] == 0):
        punti += 2
    if riga.get("tipo"):
        punti += 1
    return punti


def unisci_letture(*letture: list[dict]) -> list[dict]:
    """Piu' letture OCR della stessa immagine: per ogni caratteristica la riga piu' credibile,
    nell'ordine in cui compaiono; le righe senza nome restano dalla prima lettura."""
    scelte: dict[str, dict] = {}
    ordine: list[str] = []
    anonime: list[dict] = []
    for lettura in letture:
        for riga in lettura:
            chiave = (riga.get("nome") or "").split(" ")[0]
            # stessa riga letta con un nome diverso (178,00 / 176,00): stessi valori = stessa riga
            gemella = next((k for k, v in scelte.items() if k != chiave and v["misurato"] == riga["misurato"]
                            and v["nominale"] == riga["nominale"] and v["tol_sup"] == riga["tol_sup"]), None)
            if gemella:
                chiave = gemella
            if not chiave:
                if lettura is letture[0]:
                    anonime.append(riga)
                continue
            if chiave not in scelte:
                scelte[chiave] = riga
                ordine.append(chiave)
            elif not scelte[chiave].get("tipo") and riga.get("tipo") and _affidabilita(riga) >= _affidabilita(scelte[chiave]) - 1:
                scelte[chiave] = {**scelte[chiave], "tipo": riga["tipo"]}
            elif _affidabilita(riga) > _affidabilita(scelte[chiave]):
                if gemella:
                    riga = {**riga, "nome": scelte[chiave]["nome"]}
                if not riga.get("tipo") and scelte[chiave].get("tipo"):
                    riga = {**riga, "tipo": scelte[chiave]["tipo"]}
                if not riga.get("sezione"):
                    riga = {**riga, "sezione": scelte[chiave].get("sezione", "")}
                scelte[chiave] = riga
    return [scelte[k] for k in ordine] + anonime
