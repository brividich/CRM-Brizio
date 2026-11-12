"""Lettura di una pagina di planimetria: testi, simboli colorati e legenda.

Le piante di servizio (condizionatori, differenziali, telecamere...) sono lo
stesso disegno CAD con sopra simboli colorati e sigle, più un riquadro con la
**legenda** e il cartiglio. Qui si estrae dalla pagina:

* le parole con la posizione in percentuale, già raddrizzate se la pagina è
  ruotata (le piante orizzontali spesso sono pagine verticali ruotate di 90°);
* i **simboli** pieni colorati (quadratini, cerchi) con il loro colore;
* i **riquadri** di legenda/cartiglio: le parole lì dentro non sono posizioni;
* la **legenda** interpretata in tre forme:
    - colore → tipo («rosso = differenziali di servizio»);
    - sigle → costruttore («AERMEC: C1, C2, C3»);
    - sigla → descrizione («T1 PIAZZALE UFFICI»).

Se il PDF non ha testo (scritte convertite in linee) si usa il riconoscimento
del testo sulla pagina disegnata, in tre rotazioni, e sulle sigle dentro i simboli.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# parole che identificano la legenda e il cartiglio
_PAROLE_TITOLO = {"LEGENDA", "LEGEND", "PLANIMETRIA", "DATA", "FIRMA", "AGGIORNATA", "AGGIORNATO", "TIPOLOGIA",
                  "COSTRUTTORE", "REVISIONE", "SCALA", "DISEGNATO"}
# intestazioni delle colonne della legenda: non sono costruttori né descrizioni
_INTESTAZIONI = {"LEGENDA", "TIPOLOGIA", "COSTRUTTORE", "NUMERO", "INTERNO", "N", "DATA", "FIRMA", "SIGLA",
                 "DESCRIZIONE", "MARCA", "POSIZIONE", "NOTE"}
_SIGLA = re.compile(r"^[A-Z]{1,3}\d{1,4}(?:/?[A-Z])?$")  # C5, D95/A, T12, C3A
_RIQUADRO_MAX = 0.40  # un riquadro di legenda non supera il 40% della pagina
_RIQUADRO_MIN = 0.004
_CONTORNO_MIN, _CONTORNO_MAX = 0.002, 0.25  # zone disegnate: fra lo 0,2% e il 25% della pagina
_SIMBOLO_MIN, _SIMBOLO_MAX = 0.25, 3.5  # lato dei simboli in % del lato corto della pagina


class ErrorePagina(Exception):
    """La pagina non si può leggere."""


@dataclass
class ParolaPagina:
    testo: str
    x: float
    y: float
    riga: tuple = ()


@dataclass
class Riga:
    testo: str
    x: float
    y: float
    verticale: bool = False
    parole: list = field(default_factory=list)


@dataclass
class Simbolo:
    colore: str  # «#rrggbb»
    x: float
    y: float
    w: float
    h: float
    testo: str = ""  # sigla letta dentro il simbolo (riconoscimento del testo)


@dataclass
class Riquadro:
    x0: float
    y0: float
    x1: float
    y1: float

    def contiene(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


@dataclass
class Legenda:
    tipi: list[tuple[str, str]] = field(default_factory=list)  # (colore, testo)
    costruttori: dict[str, str] = field(default_factory=dict)  # sigla normalizzata → costruttore
    descrizioni: dict[str, str] = field(default_factory=dict)  # sigla normalizzata → descrizione
    sigle: set[str] = field(default_factory=set)  # tutte le sigle citate in legenda
    titolo: str = ""  # «PLANIMETRIA TELECAMERE aggiornata al ...»
    servizio: str = ""  # «TELECAMERE»: cosa rappresenta la pianta, dal titolo

    @property
    def vuota(self) -> bool:
        return not (self.tipi or self.costruttori or self.descrizioni)

    def tipo_di_colore(self, colore: str) -> str:
        for c, testo in self.tipi:
            if _colori_vicini(c, colore):
                return testo
        return ""


@dataclass
class Pagina:
    parole: list[ParolaPagina]  # fuori dalla legenda: posizioni sulla pianta
    parole_legenda: list[ParolaPagina]
    simboli: list[Simbolo]
    riquadri: list[Riquadro]
    legenda: Legenda
    larghezza: float
    altezza: float
    ocr: bool = False
    contorni: list[Riquadro] = field(default_factory=list)  # rettangoli disegnati sulla pianta (zone, locali)

    def contorno_di(self, x: float, y: float) -> Riquadro | None:
        """Il rettangolo disegnato più piccolo che racchiude il punto (es. il locale col nome del reparto)."""
        dentro = [r for r in self.contorni if r.contiene(x, y) and (r.x1 - r.x0) * (r.y1 - r.y0) >= _CONTORNO_MIN * 10000]
        return min(dentro, key=lambda r: (r.x1 - r.x0) * (r.y1 - r.y0)) if dentro else None

    def simbolo_vicino(self, x: float, y: float, raggio: float = 2.2) -> Simbolo | None:
        migliore, dist = None, raggio
        for s in self.simboli:
            d = max(abs(s.x - x) - s.w / 2, abs(s.y - y) - s.h / 2, 0) if s.w else max(abs(s.x - x), abs(s.y - y))
            if d <= dist:
                migliore, dist = s, d
        return migliore


# --- colori ------------------------------------------------------------------

def _hex(rgb) -> str:
    r, g, b = (max(0, min(255, round(float(v) * 255))) for v in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb(colore: str) -> tuple[int, int, int]:
    c = colore.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _colori_vicini(a: str, b: str, soglia: int = 60) -> bool:
    try:
        return sum(abs(x - y) for x, y in zip(_rgb(a), _rgb(b))) <= soglia
    except (ValueError, IndexError):
        return False


def _colorato(rgb) -> bool:
    """Né bianco, né nero, né grigio: i simboli dei servizi sono colori pieni."""
    r, g, b = (float(v) for v in rgb[:3])
    return max(r, g, b) - min(r, g, b) > 0.25


def normalizza_sigla(testo: str) -> str:
    t = re.sub(r"[^0-9A-Z]", "", str(testo or "").upper())
    return t


# --- PDF ---------------------------------------------------------------------

def leggi_pdf(contenuto: bytes, pagina: int = 0, *, ocr_se_vuoto: bool = True) -> Pagina:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=contenuto, filetype="pdf")
    except Exception as exc:
        raise ErrorePagina("Il file non è un PDF leggibile.") from exc
    try:
        if pagina >= doc.page_count:
            raise ErrorePagina(f"Il PDF ha solo {doc.page_count} pagine.")
        page = doc[pagina]
        rot = page.rotation_matrix
        w, h = page.rect.width, page.rect.height

        def pct(x, y):
            p = fitz.Point(x, y) * rot
            return round(p.x / w * 100, 2), round(p.y / h * 100, 2)

        def rect_pct(r):
            rr = fitz.Rect(r) * rot
            rr.normalize()
            return rr.x0 / w * 100, rr.y0 / h * 100, rr.x1 / w * 100, rr.y1 / h * 100

        parole: list[ParolaPagina] = []
        for x0, y0, x1, y1, testo, blocco, riga, _n in page.get_text("words"):
            testo = str(testo).strip()
            if testo:
                px, py = pct((x0 + x1) / 2, (y0 + y1) / 2)
                parole.append(ParolaPagina(testo, px, py, (blocco, riga)))
        righe = _righe_da_dict(page, pct, rot)

        simboli, rettangoli = [], []
        lato = min(w, h)
        visti = set()
        for dr in page.get_drawings():
            r = dr.get("rect")
            if r is None or r.is_empty:
                continue
            x0, y0, x1, y1 = rect_pct(r)
            fill = dr.get("fill")
            lw, lh = r.width / lato * 100, r.height / lato * 100
            if fill and _colorato(fill) and _SIMBOLO_MIN <= lw <= _SIMBOLO_MAX and _SIMBOLO_MIN <= lh <= _SIMBOLO_MAX:
                chiave = (round(x0, 1), round(y0, 1), _hex(fill))
                if chiave not in visti:  # i CAD disegnano spesso due volte lo stesso simbolo
                    visti.add(chiave)
                    simboli.append(Simbolo(_hex(fill), round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2),
                                           round(x1 - x0, 2), round(y1 - y0, 2)))
            area = (x1 - x0) * (y1 - y0) / 10000
            if _CONTORNO_MIN <= area <= _RIQUADRO_MAX and not (fill and _colorato(fill)):
                rettangoli.append((Riquadro(x0, y0, x1, y1), r))

        ocr = False
        if not parole and ocr_se_vuoto:
            ocr = True
            parole, righe = _ocr_pagina(page)
            _ocr_simboli(page, simboli, rot, w, h)
        candidati = [x[0] for x in rettangoli if (x[0].x1 - x[0].x0) * (x[0].y1 - x[0].y0) >= _RIQUADRO_MIN * 10000]
        riquadri = _riquadri_legenda(parole, righe, candidati)
        pag = _componi(parole, righe, simboli, riquadri, w, h, ocr)
        pag.contorni = [
            x[0] for x in rettangoli
            if (x[0].x1 - x[0].x0) * (x[0].y1 - x[0].y0) <= _CONTORNO_MAX * 10000
            and not any(q.contiene((x[0].x0 + x[0].x1) / 2, (x[0].y0 + x[0].y1) / 2) for q in riquadri)
        ]
        return pag
    finally:
        doc.close()


def _righe_da_dict(page, pct, rot) -> list[Riga]:
    righe = []
    try:
        dati = page.get_text("dict")
    except Exception:
        return righe
    for blocco in dati.get("blocks", []):
        for linea in blocco.get("lines", []):
            testo = " ".join(s.get("text", "") for s in linea.get("spans", [])).strip()
            testo = re.sub(r"\s+", " ", testo)
            if not testo:
                continue
            x0, y0, x1, y1 = linea["bbox"]
            cx, cy = pct((x0 + x1) / 2, (y0 + y1) / 2)
            dx, dy = linea.get("dir", (1, 0))
            # direzione del testo dopo la rotazione della pagina
            vx = dx * rot.a + dy * rot.c
            verticale = abs(vx) < 0.5
            righe.append(Riga(testo, cx, cy, verticale))
    return righe


def _componi(parole, righe, simboli, riquadri, w, h, ocr) -> Pagina:
    def dentro(x, y):
        return any(r.contiene(x, y) for r in riquadri)

    fuori = [p for p in parole if not dentro(p.x, p.y)]
    leg = [p for p in parole if dentro(p.x, p.y)]
    righe_leg = [r for r in righe if dentro(r.x, r.y)]
    simboli_leg = [s for s in simboli if dentro(s.x, s.y)]
    simboli_pianta = [s for s in simboli if not dentro(s.x, s.y)]
    legenda = interpreta_legenda(righe_leg, simboli_leg)
    _allinea_sigle_simboli(simboli_pianta, legenda)
    return Pagina(fuori, leg, simboli_pianta, riquadri, legenda, w, h, ocr)


def _allinea_sigle_simboli(simboli: list[Simbolo], legenda: Legenda) -> None:
    """Le sigle lette nei simboli si confrontano con quelle della legenda: «T1E» non c'è, «T18» sì."""
    note = legenda.sigle
    if not note:
        return
    prefissi = {re.match(r"[A-Z]*", s).group(0) for s in note}
    for s in simboli:
        if not s.testo or normalizza_sigla(s.testo) in note:
            continue
        corretta = correggi_sigla_ocr(s.testo)
        if normalizza_sigla(corretta) in note:
            s.testo = corretta
        else:
            prefisso = re.match(r"[A-Z]*", s.testo).group(0)
            numeri = [int(m.group(1)) for n in note if (m := re.match(rf"^{prefisso}(\d+)", n))]
            mio = re.match(r"[A-Z]*(\d+)", s.testo)
            # prefisso sconosciuto, o numero oltre l'elenco completo della legenda (T28 con T1..T26): lettura sbagliata
            if prefisso not in prefissi or (len(numeri) >= 5 and mio and int(mio.group(1)) > max(numeri)):
                s.testo = ""  # meglio niente che una sigla inventata


# --- riquadri di legenda -----------------------------------------------------

def _riquadri_legenda(parole, righe, rettangoli: list[Riquadro]) -> list[Riquadro]:
    """Riquadri con un titolo di legenda/cartiglio, più gli elenchi «sigla descrizione» incolonnati."""
    titoli = [(p.x, p.y) for p in parole if normalizza_sigla(p.testo) in _PAROLE_TITOLO]
    scelti: list[Riquadro] = []
    for tx, ty in titoli:
        dentro = [r for r in rettangoli if r.contiene(tx, ty)]
        if dentro:
            scelti.append(max(dentro, key=lambda r: (r.x1 - r.x0) * (r.y1 - r.y0)))
    elenco = _riquadro_elenco(righe)
    if elenco:
        scelti.append(elenco)
    # riquadri annidati: tiene i più esterni
    out = []
    for r in sorted(scelti, key=lambda r: -(r.x1 - r.x0) * (r.y1 - r.y0)):
        if not any(o.x0 <= r.x0 and o.y0 <= r.y0 and o.x1 >= r.x1 and o.y1 >= r.y1 for o in out):
            out.append(r)
    return out


def _riquadro_elenco(righe: list[Riga]) -> Riquadro | None:
    """Almeno 4 righe «sigla + testo» incolonnate: è un elenco di legenda (es. telecamere)."""
    voci = [r for r in righe if _voce_descrizione(r.testo)]
    if len(voci) < 4:
        return None
    gruppi: dict[int, list[Riga]] = {}
    for r in voci:
        asse = r.x if r.verticale else r.y  # le righe di un elenco cambiano lungo l'asse perpendicolare
        colonna = round((r.y if r.verticale else r.x) / 6)
        gruppi.setdefault(colonna, []).append(r)
    migliore = max(gruppi.values(), key=len)
    if len(migliore) < 4:
        return None
    margine = 2.5
    return Riquadro(min(r.x for r in migliore) - margine, min(r.y for r in migliore) - margine,
                    max(r.x for r in migliore) + margine, max(r.y for r in migliore) + margine)


def _voce_descrizione(testo: str) -> tuple[str, str] | None:
    pezzi = testo.split(None, 1)
    if len(pezzi) != 2:
        return None
    sigla, resto = pezzi[0].rstrip(".:-"), pezzi[1].strip(" -:")
    if _SIGLA.match(sigla.upper()) and re.search(r"[A-Za-zÀ-ù]{3,}", resto) and not _solo_sigle(resto):
        return sigla.upper(), resto
    return None


def _token_sigle(testo: str) -> list[str]:
    return [t for t in re.split(r"[\s,;+]+", testo.upper()) if t]


def _solo_sigle(testo: str) -> bool:
    toks = _token_sigle(testo)
    return bool(toks) and all(_SIGLA.match(t) for t in toks)


# --- interpretazione della legenda --------------------------------------------

def interpreta_legenda(righe: list[Riga], simboli: list[Simbolo]) -> Legenda:
    leg = Legenda()
    testuali = [r for r in righe if not _solo_sigle(r.testo)]
    # un colore ripetuto decine di volte in legenda è il testo convertito in linee, non un simbolo
    conta: dict[str, int] = {}
    for s in simboli:
        conta[s.colore] = conta.get(s.colore, 0) + 1
    campioni = [s for s in simboli if conta[s.colore] <= 6]
    # colore → tipo: la riga di testo più vicina a ogni simbolo della legenda
    for s in campioni:
        vicine = sorted(
            (r for r in testuali if not (set(normalizza_sigla(x) for x in r.testo.split()) & (_PAROLE_TITOLO | _INTESTAZIONI))),
            key=lambda r: abs(r.x - s.x) + abs(r.y - s.y),
        )
        if vicine and abs(vicine[0].x - s.x) + abs(vicine[0].y - s.y) <= 12:
            testo = vicine[0].testo.strip(" :-")
            if testo and all(not _colori_vicini(c, s.colore) for c, _t in leg.tipi):
                leg.tipi.append((s.colore, testo))
    tipi_testo = {normalizza_sigla(t) for _c, t in leg.tipi}
    for r in righe:
        parole = r.testo.split()
        if parole and normalizza_sigla(parole[0]) == "PLANIMETRIA":
            leg.titolo = r.testo
            servizio = []
            for w in parole[1:]:
                # il servizio è in maiuscolo; «aggiornata al», le date e «Imm.1» chiudono
                if not w.isupper() or any(c.isdigit() for c in w):
                    break
                servizio.append(w)
            leg.servizio = " ".join(servizio)
            break
    # sigla → descrizione: «T1 PIAZZALE UFFICI»
    for r in righe:
        voce = _voce_descrizione(r.testo)
        if voce:
            leg.descrizioni[normalizza_sigla(voce[0])] = _pulisci(voce[1])
            leg.sigle.add(normalizza_sigla(voce[0]))
    # sigle → costruttore: celle di sole sigle e la cella di testo sulla stessa riga della tabella.
    # Senza la colonna «Costruttore/Marca» una sigla sola con un testo accanto è una descrizione.
    con_costruttore = any(set(normalizza_sigla(x) for x in r.testo.split()) & {"COSTRUTTORE", "MARCA", "FORNITORE"}
                          for r in righe)
    for r in righe:
        if not _solo_sigle(r.testo):
            continue
        sigle = [normalizza_sigla(t) for t in _token_sigle(r.testo)]
        leg.sigle.update(sigle)
        compagne = [
            c for c in testuali
            if c is not r and normalizza_sigla(c.testo) not in tipi_testo
            and not (set(normalizza_sigla(x) for x in c.testo.split()) & _INTESTAZIONI)
            and _stessa_riga(r, c)
        ]
        if not compagne:
            continue
        testo = _pulisci(min(compagne, key=lambda c: abs(c.y - r.y) if r.verticale else abs(c.x - r.x)).testo)
        if not re.search(r"[A-Za-zÀ-ù]{2,}", testo):
            continue
        if con_costruttore:
            for s in sigle:
                leg.costruttori.setdefault(s, testo)
        elif len(sigle) == 1:
            leg.descrizioni.setdefault(sigle[0], testo)
    return leg


def _pulisci(testo: str) -> str:
    return re.sub(r"^[^0-9A-Za-zÀ-ù]+|[^0-9A-Za-zÀ-ù)]+$", "", testo.strip())


def _stessa_riga(a: Riga, b: Riga, tolleranza: float = 1.4) -> bool:
    # testo verticale: le righe della tabella si susseguono lungo x
    return abs(a.x - b.x) <= tolleranza if a.verticale else abs(a.y - b.y) <= tolleranza


# --- riconoscimento del testo --------------------------------------------------

def _tesseract() -> tuple[str, dict]:
    from anagrafica.services.referti_ocr import _ambiente, percorso_tesseract

    exe = percorso_tesseract()
    if not exe:
        raise ErrorePagina("Il PDF non contiene testo e il riconoscimento del testo (Tesseract) non è installato.")
    return exe, _ambiente()


def ocr_immagine(img, *, rotazioni=(0, 90, 270), timeout: int = 120) -> tuple[list[ParolaPagina], list[Riga]]:
    """Parole e righe di un'immagine PIL in più rotazioni, con le coordinate riportate sull'originale."""
    exe, env = _tesseract()
    larghezza, altezza = img.size
    grigio = img.convert("L")
    passate: dict[int, tuple[list, list, int]] = {}
    with tempfile.TemporaryDirectory(prefix="planimetria-ocr-") as tmp:
        for ang in rotazioni:
            parole, righe = [], []
            lavoro = grigio.rotate(ang, expand=True, fillcolor=255) if ang else grigio
            ingresso = Path(tmp) / f"r{ang}.png"
            lavoro.save(ingresso)
            uscita = Path(tmp) / f"r{ang}"
            try:
                subprocess.run([exe, str(ingresso), str(uscita), "-l", "ita+eng", "--psm", "11", "tsv"],
                               check=True, capture_output=True, timeout=timeout, env=env)
            except subprocess.TimeoutExpired:
                raise ErrorePagina(f"La lettura ha superato {timeout} secondi ed è stata interrotta.") from None
            except subprocess.CalledProcessError:
                try:
                    subprocess.run([exe, str(ingresso), str(uscita), "-l", "ita", "--psm", "11", "tsv"],
                                   check=True, capture_output=True, timeout=timeout, env=env)
                except Exception as exc:
                    raise ErrorePagina("Il riconoscimento del testo è fallito su questa immagine.") from exc
            tsv = uscita.with_suffix(".tsv").read_text(encoding="utf-8", errors="replace")
            lw, lh = lavoro.size
            buone = 0
            per_riga: dict[tuple, list[ParolaPagina]] = {}
            for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
                testo = (r.get("text") or "").strip()
                try:
                    conf = float(r.get("conf") or -1)
                except ValueError:
                    conf = -1
                if not testo or conf < (40 if ang == 0 else 60):
                    continue
                cx = int(r["left"]) + int(r["width"]) / 2
                cy = int(r["top"]) + int(r["height"]) / 2
                x, y = _ruota_indietro(cx, cy, ang, larghezza, altezza, lw, lh)
                chiave = (ang, r.get("block_num"), r.get("par_num"), r.get("line_num"))
                p = ParolaPagina(testo, round(x / larghezza * 100, 2), round(y / altezza * 100, 2), chiave)
                parole.append(p)
                per_riga.setdefault(chiave, []).append(p)
                if conf >= 80 and re.search(r"[A-Za-z]{3,}", testo):
                    buone += 1
            for chiave, gruppo in per_riga.items():
                righe.append(Riga(" ".join(p.testo for p in gruppo), sum(p.x for p in gruppo) / len(gruppo),
                                  sum(p.y for p in gruppo) / len(gruppo), verticale=ang in (90, 270), parole=gruppo))
            passate[ang] = (parole, righe, buone)
    # il testo capovolto letto nella rotazione sbagliata dà parole senza senso: si tiene la rotazione migliore
    ruotate = sorted((a for a in passate if a), key=lambda a: -passate[a][2])
    tenute = [a for a in passate if not a]
    if ruotate:
        tenute.append(ruotate[0])
        tenute += [a for a in ruotate[1:] if passate[a][2] > passate[ruotate[0]][2] * 0.5]
    parole_tot: list[ParolaPagina] = []
    righe_tot: list[Riga] = []
    for a in sorted(tenute, key=lambda a: -passate[a][2]):
        for p in passate[a][0]:
            if not any(q.testo == p.testo and abs(q.x - p.x) < 1 and abs(q.y - p.y) < 1 for q in parole_tot):
                parole_tot.append(p)
        righe_tot += passate[a][1]
    return parole_tot, righe_tot


def _ruota_indietro(x, y, ang, w0, h0, lw, lh):
    """Punto sull'immagine ruotata (PIL, antiorario, expand) → punto sull'originale."""
    if ang == 90:
        return w0 - y, x
    if ang == 270:
        return y, h0 - x
    return x, y


def _ocr_pagina(page) -> tuple[list[ParolaPagina], list[Riga]]:
    import fitz
    from PIL import Image

    zoom = min(5.0, 4000 / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return ocr_immagine(img)


_CONFUSIONI = str.maketrans({"Z": "2", "S": "5", "B": "8", "E": "8", "G": "6", "O": "0", "I": "1", "L": "1"})


def correggi_sigla_ocr(testo: str) -> str:
    """«T1Z» → «T12»: dopo le lettere iniziali, le lettere simili a cifre diventano cifre."""
    m = re.match(r"^([A-Z]{1,3}?)(\d[0-9A-Z/]*)$", testo)
    if not m:
        return testo
    prefisso, corpo = m.group(1), m.group(2)
    tradotto = corpo.translate(_CONFUSIONI)
    if tradotto.isdigit():
        return prefisso + tradotto
    if tradotto[:-1].rstrip("/").isdigit():  # D95/A: l'ultima lettera è un suffisso vero
        return prefisso + corpo[:-1].translate(_CONFUSIONI) + corpo[-1]
    return testo


def _ocr_simboli(page, simboli: list[Simbolo], rot, w, h) -> None:
    """Sigla scritta dentro ogni simbolo (testo chiaro su fondo colorato), letta ritaglio per ritaglio."""
    import fitz
    from PIL import Image, ImageOps

    try:
        exe, env = _tesseract()
    except ErrorePagina:
        return
    inv = ~rot
    lato = min(w, h)
    angoli = [90, 270, 0]
    with tempfile.TemporaryDirectory(prefix="planimetria-sim-") as tmp:
        for s in simboli:
            if s.w / 100 * w < lato * 0.012:  # troppo piccolo per contenere una sigla
                continue
            r = fitz.Rect((s.x - s.w / 2) / 100 * w, (s.y - s.h / 2) / 100 * h,
                          (s.x + s.w / 2) / 100 * w, (s.y + s.h / 2) / 100 * h) * inv
            r.normalize()
            r = r + (0.8, 0.8, -0.8, -0.8)
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(8, 8), clip=r, alpha=False)
            except Exception:
                continue
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            # testo bianco su fondo colorato: il canale più scuro del fondo separa bene le lettere
            canale = min(range(3), key=lambda i: _rgb(s.colore)[i])
            maschera = ImageOps.expand(img.split()[canale].point(lambda v: 0 if v > 150 else 255), 20, fill=255)
            for ang in list(angoli):
                file = Path(tmp) / "s.png"
                maschera.rotate(ang, expand=True, fillcolor=255).save(file)
                try:
                    out = subprocess.run([exe, str(file), "stdout", "--psm", "7"], capture_output=True, text=True,
                                         timeout=20, env=env).stdout
                except Exception:
                    break
                testo = correggi_sigla_ocr(re.sub(r"[^0-9A-Z/]", "", out.upper()))
                if _SIGLA.match(testo):
                    s.testo = testo
                    angoli.remove(ang)
                    angoli.insert(0, ang)  # le sigle di una pianta hanno quasi sempre la stessa rotazione
                    break


def leggi_immagine(percorso_immagine: str) -> Pagina:
    """Pagina da un'immagine già caricata: solo riconoscimento del testo (niente simboli vettoriali)."""
    from PIL import Image

    with Image.open(percorso_immagine) as img:
        lavoro = img.convert("RGB")
        if max(lavoro.size) < 2500:
            lavoro = lavoro.resize((lavoro.size[0] * 2, lavoro.size[1] * 2))
        parole, righe = ocr_immagine(lavoro)
        w, h = lavoro.size
    riquadri = _riquadri_legenda(parole, righe, [])
    return _componi(parole, righe, [], riquadri, w, h, True)
