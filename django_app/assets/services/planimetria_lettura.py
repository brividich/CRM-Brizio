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

La pagina PDF passa da ``planimetria_pagina``: lì si separano legenda e
cartiglio (le loro parole non sono posizioni), si leggono i simboli colorati e
la legenda (colore → tipo, sigle → costruttore, sigla → descrizione). Qui la
legenda serve a controllare gli abbinamenti, a limitare le categorie cercate e
a proporre gli asset **da creare** e i **reparti** scritti sulla pianta.
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

from ..models import IT_DEVICE_TYPES, Asset, AssetCategory, PlantLayout
from . import planimetria_pagina as pagina_pdf
from .planimetria_pagina import Pagina

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


Parola = pagina_pdf.ParolaPagina  # testo, x, y (centro in % della pagina), riga


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
    tipo: str = ""  # dalla legenda, per il colore del simbolo accanto alla sigla
    costruttore_legenda: str = ""
    descrizione: str = ""
    avvisi: list[str] = field(default_factory=list)

    @property
    def spostamento_grande(self) -> bool:
        if self.stato != "sposta" or self.x_attuale is None:
            return False
        return max(abs(self.x - self.x_attuale), abs(self.y - self.y_attuale)) > _SPOSTAMENTO_GRANDE

    @property
    def preselezionata(self) -> bool:
        return (self.fonte != FONTE_AI and self.stato != "invariato" and not self.altri_punti
                and not self.spostamento_grande and not self.avvisi)


@dataclass
class DaCreare:
    """Sigla sulla pianta senza un asset in anagrafica: si può creare da qui."""

    sigla: str
    x: float
    y: float
    tipo: str = ""
    descrizione: str = ""
    costruttore: str = ""
    categoria_id: int | None = None
    nome: str = ""
    altri_punti: int = 0

    @property
    def preselezionata(self) -> bool:
        return bool(self.categoria_id) and not self.altri_punti and bool(self.tipo or self.descrizione or self.costruttore)


@dataclass
class DaAssociare:
    """Sigla letta sulla pianta che non è diventata una proposta: si associa a mano a un asset."""

    sigla: str
    x: float
    y: float
    motivo: str
    candidati: list[dict] = field(default_factory=list)  # id, nome, sotto (n. interno, categoria, reparto)
    altri_punti: int = 0


@dataclass
class ArePropostaReparto:
    nome: str
    x: float
    y: float
    w: float
    h: float
    contorno: bool  # True se il riquadro viene da un contorno disegnato, False se è un riquadro di partenza
    condiviso: bool = False  # lo stesso contorno racchiude più nomi: va scelto a mano

    @property
    def preselezionata(self) -> bool:
        return self.contorno and not self.condiviso


@dataclass
class Risultato:
    fonte_testo: str
    parole_lette: int
    proposte: list[Proposta] = field(default_factory=list)
    non_riconosciute: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)
    da_creare: list[DaCreare] = field(default_factory=list)
    reparti: list[ArePropostaReparto] = field(default_factory=list)
    da_associare: list[DaAssociare] = field(default_factory=list)
    legenda: pagina_pdf.Legenda | None = None
    categorie_note: str = ""  # perché la ricerca è limitata ad alcune categorie
    categorie_nomi: list[str] = field(default_factory=list)


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

def leggi_pagina_pdf(contenuto: bytes, pagina: int = 0, *, ocr_se_vuoto: bool = True) -> Pagina:
    """Pagina PDF con parole fuori dalla legenda, simboli e legenda interpretata."""
    try:
        return pagina_pdf.leggi_pdf(contenuto, pagina, ocr_se_vuoto=ocr_se_vuoto)
    except pagina_pdf.ErrorePagina as exc:
        raise ErroreLettura(str(exc)) from exc


def leggi_pagina_immagine(percorso: str) -> Pagina:
    try:
        return pagina_pdf.leggi_immagine(percorso)
    except pagina_pdf.ErrorePagina as exc:
        raise ErroreLettura(str(exc)) from exc


def parole_da_pdf(contenuto: bytes, pagina: int = 0) -> tuple[list[Parola], tuple[float, float]]:
    """Parole del testo vettoriale di una pagina PDF fuori da legenda e cartiglio (niente OCR)."""
    pag = leggi_pagina_pdf(contenuto, pagina, ocr_se_vuoto=False)
    return pag.parole, (pag.larghezza, pag.altezza)


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
        it = a.asset_type in IT_DEVICE_TYPES
        valori = [(a.internal_number, FONTE_NUMERO_INTERNO), (a.asset_tag, FONTE_TAG),
                  (a.serial_number, FONTE_MATRICOLA), (a.name, FONTE_NOME)]
        valori += [(s, FONTE_SIGLA) for s in sigle_in(a.name) + sigle_in(a.asset_tag)]
        for valore, fonte in valori:
            chiave = normalizza(valore)
            # sigle di una cifra o due lettere abbinerebbero quote e numeri di stanza;
            # i numeri interni di due caratteri sì («Int.033» → 33, «Int.C1» → C1), perché sulle piante ci sono
            if len(chiave) < 2 or (len(chiave) == 2 and not (fonte == FONTE_NUMERO_INTERNO and any(c.isdigit() for c in chiave))):
                continue
            # «CN5» nel nome dell'Access Point è il reparto, non la macchina
            if fonte in (FONTE_SIGLA, FONTE_NOME) and chiave in escluse:
                continue
            # dispositivi IT (PC, telecamere...): solo sigle con lettere, mai numeri nudi o nomi interi
            if it and (chiave.isdigit() or fonte in (FONTE_NOME, FONTE_MATRICOLA)):
                continue
            voci = indice.setdefault(chiave, [])
            if all(x[0].pk != a.pk for x in voci):
                voci.append((a, fonte))
        # «T1 CAM - Piazzale»: una sigla breve all'inizio del nome è la sigla scritta sulla pianta
        iniziale = re.match(r"^\s*([A-Za-z]{1,2}\d{1,2})(?:\s|-|$)", a.name or "")
        if iniziale:
            chiave = normalizza(iniziale.group(1))
            if len(chiave) == 2:
                voci = indice.setdefault(chiave, [])
                if all(x[0].pk != a.pk for x in voci):
                    voci.append((a, FONTE_SIGLA))
    return indice


def assets_candidati(categorie: set[int] | None = None):
    """Asset che possono stare su una planimetria: non dismessi (per gli IT valgono solo le sigle, vedi indice)."""
    qs = Asset.objects.exclude(status=Asset.STATUS_RETIRED).select_related("asset_category")
    if categorie is None:
        return qs
    return qs.filter(asset_category_id__in=categorie)


_PAROLE_VUOTE = {"di", "da", "del", "della", "e", "ed", "per", "con", "in", "a", "al", "il", "la", "le", "lo", "gli", "i"}


def _parole_testo(testo: str, minimo: int = 3) -> list[str]:
    return [w for w in re.split(r"[^0-9a-zà-ù]+", str(testo or "").casefold())
            if len(w) >= minimo and w not in _PAROLE_VUOTE]


def _radice(parola: str) -> str:
    # «bruciatori» / «bruciatore», «differenziali» / «differenziale»
    return parola[:-1] if len(parola) > 4 and parola[-1] in "aeio" else parola


_CACHE_CATEGORIE: list = []


def _categorie_attive():
    # una lettura confronta decine di sigle con le categorie: si caricano una volta per lettura
    if not _CACHE_CATEGORIE:
        _CACHE_CATEGORIE.extend(AssetCategory.objects.filter(is_active=True))
    return _CACHE_CATEGORIE


def categorie_per_testo(testo: str, categorie=None) -> list[AssetCategory]:
    """Categorie il cui nome (o un sinonimo) compare nel testo, es. «CHILLER» → Chiller.

    Tutte le parole del nome della categoria devono esserci e il testo deve parlare
    di quella cosa: «Differenziali macchine» non è la categoria «Macchine NO CE».
    """
    parole_testo = _parole_testo(testo, 2)
    if not parole_testo:
        return []
    radici = {_radice(w) for w in parole_testo}
    principale = _radice(parole_testo[0])
    out = []
    for cat in (categorie if categorie is not None else _categorie_attive()):
        nomi = [cat.label, *[x for x in re.split(r"[,;]", getattr(cat, "sinonimi", "") or "") if x.strip()]]
        for nome in nomi:
            parole = {_radice(w) for w in _parole_testo(nome, 2)}
            if parole and parole <= radici and principale in parole:
                out.append(cat)
                break
    return out


def singolare(testo: str) -> str:
    """«DIFFERENZIALI DI SERVIZIO» → «Differenziale di servizio»: i tipi in legenda sono al plurale."""
    parole = str(testo or "").strip().split()
    if not parole:
        return ""
    prima = parole[0].lower()
    if len(prima) > 4 and prima.isalpha():
        if prima.endswith("i"):
            prima = prima[:-1] + "e"
        elif prima.endswith("e"):
            prima = prima[:-1] + "a"
    return " ".join([prima.capitalize(), *[w.lower() for w in parole[1:]]])


def _con_figlie(ids: set[int]) -> set[int]:
    tutte = set(ids)
    nuove = set(ids)
    for _ in range(4):
        nuove = set(AssetCategory.objects.filter(parent_id__in=nuove).values_list("id", flat=True)) - tutte
        if not nuove:
            break
        tutte |= nuove
    return tutte


def categorie_ammesse(layout: PlantLayout, legenda=None) -> tuple[set[int] | None, str]:
    """Categorie da cercare su questa pianta e perché. ``None`` = tutte (salvo IT)."""
    scelte = set(layout.asset_categories.values_list("id", flat=True)) if layout.pk else set()
    if scelte:
        return _con_figlie(scelte), "scelte nelle impostazioni della planimetria"
    testi_tipo = [t for _c, t in legenda.tipi] if legenda is not None else []
    if legenda is not None and not testi_tipo and legenda.servizio:
        testi_tipo = [legenda.servizio] if categorie_per_testo(legenda.servizio) else []
    if testi_tipo:
        trovate = set()
        for testo in testi_tipo:
            trovate |= {c.id for c in categorie_per_testo(testo)}
        # una legenda con tipi che non corrispondono a nessuna categoria (es. «Differenziali di servizio»)
        # esclude tutto: le sigle diventano asset da creare, non abbinamenti sbagliati
        return _con_figlie(trovate), "dalla legenda della pianta"
    if layout.pk:
        dai_marker = set(
            layout.markers.exclude(asset__asset_category_id=None).values_list("asset__asset_category_id", flat=True)
        )
        if len(dai_marker) and layout.markers.count() >= 3:
            return _con_figlie(dai_marker), "delle macchine già su questa planimetria"
    return None, ""


def _sembra_sigla(testo: str) -> bool:
    chiave = normalizza(testo)
    return 2 <= len(chiave) <= 20 and any(c.isdigit() for c in chiave)


def abbina(layout: PlantLayout, parole: list[Parola] | None = None, *, usa_ai: bool = False, fonte_testo: str = "",
           pagina: Pagina | None = None) -> Risultato:
    """Proposte di posizione per gli asset riconosciuti fra le parole della pianta."""
    from .plant_layout_image import marker_is_unplaced

    _CACHE_CATEGORIE.clear()
    legenda = pagina.legenda if pagina is not None else None
    if parole is None:
        parole = list(pagina.parole) if pagina is not None else []
    if pagina is not None:
        # le sigle lette dentro i simboli (testo convertito in linee) valgono come parole
        parole = parole + [Parola(s.testo, s.x, s.y, ("simbolo", i)) for i, s in enumerate(pagina.simboli) if s.testo]
    risultato = Risultato(fonte_testo=fonte_testo, parole_lette=len(parole), legenda=legenda)
    categorie, perche = categorie_ammesse(layout, legenda)
    if categorie is not None:
        risultato.categorie_note = perche
        risultato.categorie_nomi = list(
            AssetCategory.objects.filter(id__in=categorie, parent_id__isnull=True).values_list("label", flat=True)
        ) or list(AssetCategory.objects.filter(id__in=categorie).values_list("label", flat=True)[:12])
    assets = list(assets_candidati(categorie))
    reparti = nomi_reparti()
    indice = _indice_asset(assets, reparti)
    # le sigle nascoste dalla categoria (es. «10» di un differenziale = Int.10 di una macchina) non si propongono
    indice_tutti = _indice_asset(list(assets_candidati()), reparti) if categorie is not None else indice
    trovati: dict[int, list[tuple[Asset, str, str, float, float]]] = {}
    usate: set[str] = set()
    ambigue: dict[str, tuple[str, float, float, list]] = {}
    for chiave, testo, x, y in _candidati(parole):
        voci = indice.get(chiave)
        if not voci:
            continue
        if len(voci) > 1:  # sigla di più asset: ambigua, non si propone ma si sceglie a mano
            if _sembra_sigla(testo):
                ambigue.setdefault(chiave, (testo, x, y, voci))
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
        proposta = _proposta(asset, fonte, testo, x, y, attuali.get(asset_id), altri=len(lontane))
        _controlla_con_legenda(proposta, asset, pagina, normalizza(testo))
        if pagina is not None and pagina.ocr and normalizza(testo).isdigit():
            proposta.avvisi.append("Numero letto dal riconoscimento del testo: controlla che sia proprio questo asset")
        risultato.proposte.append(proposta)

    da_ai = sorted({
        p.testo for p in parole
        if _sembra_sigla(p.testo) and normalizza(p.testo) not in usate
    })
    if pagina is not None:
        risultato.da_creare = _da_creare(parole, usate, pagina, layout, categorie, indice_tutti, reparti)
        # su un livello i reparti non si disegnano: stanno sulla pianta base
        risultato.reparti = [] if layout.base_id else _reparti_proposti(layout, pagina)
        gia = {normalizza(d.sigla) for d in risultato.da_creare}
        da_ai = [t for t in da_ai if normalizza(t) not in gia]
    if usa_ai and da_ai:
        gia = set(trovati)
        # all'AI niente dispositivi IT, salvo categorie scelte apposta: abbinerebbe sigle a caso ai PC
        per_ai = [a for a in assets if a.pk not in gia and (categorie is not None or a.asset_type not in IT_DEVICE_TYPES)]
        for proposta in _abbina_con_ai(da_ai, parole, per_ai, attuali):
            risultato.proposte.append(proposta)
            da_ai = [t for t in da_ai if t != proposta.testo_letto]
    risultato.non_riconosciute = da_ai[:200]
    risultato.da_associare = _da_associare(
        parole, usate | {normalizza(p.testo_letto) for p in risultato.proposte},
        {normalizza(d.sigla) for d in risultato.da_creare}, ambigue, indice_tutti, reparti,
        filtrate=categorie is not None, macchine_ammesse=_macchine_ammesse(categorie),
    )
    ordine = {"sposta": 0, "nuovo": 1, "invariato": 2}
    risultato.proposte.sort(key=lambda p: (p.fonte == FONTE_AI, ordine[p.stato], p.nome.casefold()))
    return risultato


_MAX_DA_ASSOCIARE = 300
_MISURA = re.compile(r"^\d+([.,]\d+)?\s?(mm|cm|m|mq|m2|kg|t|kw|kva|v|a|bar|l)$", re.I)  # quote e targhe: «1400mm»


def _candidato(asset: Asset) -> dict:
    sotto = " · ".join(x for x in (
        asset.internal_number or asset.asset_tag or "",
        asset.asset_category.label if asset.asset_category_id and asset.asset_category else "",
        asset.reparto or "",
    ) if x)
    return {"id": asset.pk, "nome": asset.name or asset.asset_tag or f"Asset {asset.pk}", "sotto": sotto}


def _macchine_ammesse(categorie) -> bool:
    if not categorie:
        return True
    return AssetCategory.objects.filter(id__in=categorie, base_asset_type=Asset.TYPE_WORK_MACHINE).exists()


def _da_associare(parole, usate, da_creare, ambigue, indice_tutti, reparti, *, filtrate: bool,
                  macchine_ammesse: bool = True) -> list[DaAssociare]:
    """Sigle lette e non usate, con la posizione e gli asset che potrebbero essere (se ce ne sono)."""
    per_chiave: dict[str, DaAssociare] = {}

    def aggiungi(chiave, testo, x, y):
        if chiave in per_chiave:
            per_chiave[chiave].altri_punti += 1
            return
        voci = ambigue[chiave][3] if chiave in ambigue else []
        if voci:
            motivo = f"Corrisponde a {len(voci)} asset: scegli quale"
        elif filtrate and indice_tutti.get(chiave):
            voci = indice_tutti[chiave]
            motivo = "C'è un asset con questa sigla, ma di un'altra categoria"
        else:
            motivo = "Nessun asset con questa sigla: cercalo per nome"
        per_chiave[chiave] = DaAssociare(
            sigla=testo.strip(" ,;:.()[]"), x=x, y=y, motivo=motivo,
            candidati=[_candidato(a) for a, _fonte in voci[:12]],
        )

    for p in parole:
        chiave = normalizza(p.testo)
        if (not _sembra_sigla(p.testo) or chiave in usate or chiave in da_creare or chiave in reparti
                or _NON_CODICE.match(p.testo.strip(" ,;:.()[]")) or _MISURA.match(p.testo.strip())):
            continue
        if not macchine_ammesse and chiave not in ambigue and re.match(r"^-\d{1,4}[A-Za-z]?-?$", p.testo.strip()):
            continue  # «-233-»: numero di una macchina del disegno di fondo, non di questo servizio
        aggiungi(chiave, p.testo, p.x, p.y)
    for chiave, (testo, x, y, _voci) in ambigue.items():  # sigle ambigue scritte su più parole («T 12»)
        if chiave not in per_chiave and chiave not in usate:
            aggiungi(chiave, testo, x, y)
    righe = sorted(per_chiave.values(), key=lambda d: (not d.candidati, _ordine_sigla(d.sigla)))
    return righe[:_MAX_DA_ASSOCIARE]


def _controlla_con_legenda(proposta: Proposta, asset: Asset, pagina: Pagina | None, chiave: str) -> None:
    """Tipo (colore del simbolo) e costruttore della legenda confrontati con la scheda asset."""
    if pagina is None:
        return
    leg = pagina.legenda
    simbolo = pagina.simbolo_vicino(proposta.x, proposta.y)
    if simbolo is not None:
        proposta.tipo = leg.tipo_di_colore(simbolo.colore)
    proposta.costruttore_legenda = leg.costruttori.get(chiave, "")
    proposta.descrizione = leg.descrizioni.get(chiave, "")
    categoria = asset.asset_category
    if proposta.tipo and categoria is not None:
        if not any(c.id == categoria.id or c.id == categoria.parent_id for c in categorie_per_testo(proposta.tipo)):
            proposta.avvisi.append(f"In legenda è «{proposta.tipo}», nella scheda «{categoria.label}»")
    if proposta.costruttore_legenda and asset.manufacturer:
        a = normalizza(proposta.costruttore_legenda)
        b = normalizza(asset.manufacturer)
        if a and b and a not in b and b not in a:
            proposta.avvisi.append(
                f"In legenda il costruttore è «{proposta.costruttore_legenda}», nella scheda «{asset.manufacturer}»"
            )


_NON_CODICE = re.compile(r"^\d+[.,]\d+|^\d{1,2}/\d{1,2}(/\d{2,4})?$|^\d{4,}$")


def _sembra_codice(testo: str, tipo: str) -> bool:
    """Sigla di un oggetto da inventariare: lettere+cifre («D95/A», «T12») o numero accanto a un simbolo."""
    t = testo.strip(" ,;:.()[]")
    if not t or _NON_CODICE.match(t):
        return False
    chiave = normalizza(t)
    if not 2 <= len(chiave) <= 12:
        return False
    if re.match(r"^[A-Z]{1,3}\d{1,4}[A-Z]?$", chiave):
        return True
    if re.match(r"^-\d{1,4}-?$", t):  # «-233-»: numero interno delle macchine sulla pianta generale
        return True
    return chiave.isdigit() and bool(tipo)


_SERVIZI_GENERICI = {"", "GENERALE", "AZIENDA", "AZIENDALE", "STABILIMENTO", "EDIFICIO", "PIANO", "EMERGENZA"}


def _da_creare(parole, usate, pagina: Pagina, layout, categorie, indice_tutti, reparti=frozenset()) -> list[DaCreare]:
    leg = pagina.legenda
    categoria_pianta = None
    macchine_ammesse = True
    if categorie:
        cats = list(AssetCategory.objects.filter(id__in=categorie).only("id", "label", "parent_id", "base_asset_type"))
        if len(cats) == 1:
            categoria_pianta = cats[0]
        macchine_ammesse = any(c.base_asset_type == Asset.TYPE_WORK_MACHINE for c in cats)
    servizio_cat = None
    if leg.servizio:
        trovate = categorie_per_testo(leg.servizio)
        servizio_cat = trovate[0] if len(trovate) == 1 else None
    per_chiave: dict[str, DaCreare] = {}
    esplose = []
    for p in parole:
        pezzi = p.testo.split("-")
        # «D148-D149/A»: due sigle scritte attaccate sullo stesso simbolo
        if len(pezzi) == 2 and all(re.match(r"^[A-Za-z]{1,3}\d{1,4}(/?[A-Za-z])?$", x) for x in pezzi):
            esplose += [Parola(x, p.x, p.y, p.riga) for x in pezzi]
        else:
            esplose.append(p)
    for p in esplose:
        chiave = normalizza(p.testo)
        if not chiave or chiave in usate or normalizza(p.testo.strip(" ,;")) in usate:
            continue
        simbolo = pagina.simbolo_vicino(p.x, p.y)
        tipo = leg.tipo_di_colore(simbolo.colore) if simbolo is not None else ""
        if not _sembra_codice(p.testo, tipo):
            continue
        if chiave in reparti:
            continue  # «CN5»: nome di reparto, non un oggetto
        numero_macchina = bool(re.match(r"^-\d{1,4}-?$", p.testo.strip()))
        if categorie is not None and numero_macchina and not macchine_ammesse:
            continue  # «-233-»: numero di una macchina del disegno di fondo, non di questo servizio
        if categorie is not None and not tipo and chiave not in leg.sigle and not numero_macchina:
            continue  # pianta di un servizio: solo sigle col simbolo colorato o citate in legenda («AGV1», «P145» no)
        if chiave in indice_tutti and not tipo:
            continue  # è un asset di un'altra categoria: non lo si crea due volte
        if chiave in per_chiave:
            per_chiave[chiave].altri_punti += 1
            continue
        sigla = p.testo.strip(" ,;:.()[]")
        sigla = sigla.strip("-") if re.match(r"^-\d+-?$", sigla) else sigla
        descrizione = leg.descrizioni.get(chiave, "")
        costruttore = leg.costruttori.get(chiave, "")
        cat = None
        if tipo:
            trovate = categorie_per_testo(tipo)
            cat = trovate[0] if len(trovate) == 1 else None
        cat = cat or categoria_pianta or servizio_cat
        servizio = leg.servizio if normalizza(leg.servizio) not in _SERVIZI_GENERICI else ""
        base = singolare(tipo) if tipo else (cat.label if cat else (singolare(servizio) if servizio else "Asset"))
        nome = f"{base} {sigla}" + (f" - {descrizione.capitalize()}" if descrizione else "")
        per_chiave[chiave] = DaCreare(sigla=sigla, x=p.x, y=p.y, tipo=tipo, descrizione=descrizione,
                                      costruttore=costruttore, categoria_id=cat.id if cat else None,
                                      nome=nome[:255])
    return sorted(per_chiave.values(), key=lambda d: _ordine_sigla(d.sigla))[:400]


def _ordine_sigla(sigla: str):
    m = re.match(r"^([A-Za-z]*)(\d*)(.*)$", sigla)
    return (m.group(1).upper(), int(m.group(2) or 0), m.group(3)) if m else (sigla, 0, "")


def _reparti_proposti(layout: PlantLayout, pagina: Pagina) -> list[ArePropostaReparto]:
    """Nomi di reparto scritti sulla pianta → aree da confermare, sul contorno disegnato che li racchiude."""
    try:
        from anagrafica.models import Reparto

        from ..models import RepartoAssetCollegato

        nomi = {normalizza(n): n for n in Reparto.objects.values_list("nome", flat=True) if n}
        for testo in RepartoAssetCollegato.objects.values_list("testo", flat=True):
            nomi.setdefault(normalizza(testo), testo)
        for testo in Asset.objects.exclude(reparto="").values_list("reparto", flat=True).distinct():
            nomi.setdefault(normalizza(testo), testo)
    except Exception:
        return []
    esistenti = {normalizza(n) for n in layout.areas.values_list("name", flat=True)} if layout.pk else set()
    esistenti |= {normalizza(n) for n in layout.areas.values_list("reparto_code", flat=True)} if layout.pk else set()
    out: dict[str, ArePropostaReparto] = {}
    for chiave, testo, x, y in _candidati(pagina.parole):
        if len(chiave) < 2 or chiave not in nomi or chiave in esistenti or chiave in out:
            continue
        contorno = pagina.contorno_di(x, y)
        if contorno is not None:
            out[chiave] = ArePropostaReparto(nomi[chiave], round(contorno.x0, 2), round(contorno.y0, 2),
                                             round(contorno.x1 - contorno.x0, 2), round(contorno.y1 - contorno.y0, 2), True)
        else:
            out[chiave] = ArePropostaReparto(nomi[chiave], round(max(0, x - 4), 2), round(max(0, y - 3), 2), 8, 6, False)
    uso: dict[tuple, int] = {}
    for a in out.values():
        if a.contorno:
            uso[(a.x, a.y, a.w, a.h)] = uso.get((a.x, a.y, a.w, a.h), 0) + 1
    for a in out.values():
        if a.contorno and uso[(a.x, a.y, a.w, a.h)] > 1:
            a.condiviso = True
    return sorted(out.values(), key=lambda a: a.nome.casefold())


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
