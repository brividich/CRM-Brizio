"""Estrazione testo dei documenti SGI (fase A1 del database SGI).

Funzioni pure e fail-safe: mai un'eccezione verso il chiamante (errore -> testo
vuoto + avviso). Sulla share ci sono solo PDF (STOP 0), quindi l'unico estrattore
è pymupdf; gli altri formati ritornano un avviso «formato non supportato».

Rispetto all'estrazione "piatta" del RAG (``page.get_text()``):
- **ordine di lettura**: blocchi ordinati (``get_text("blocks", sort=True)``);
- **tabelle** ricostruite in pipe-table Markdown (``page.find_tables()``) e non
  duplicate nel testo dei blocchi; le "tabelle" che sono solo una cornice o un
  riquadro (meno di 2 righe/colonne, o più del 70% della pagina) restano testo;
- **intestazioni e piè di pagina ripetuti** (righe nella fascia alta/bassa presenti
  in almeno il 60% delle pagine, numeri normalizzati: «pag. 3 di 12») tenuti solo
  alla prima occorrenza: il cartiglio resta una volta, non a ogni pagina;
- normalizzazione: NFC, spazi collassati, sillabazioni a fine riga ricomposte.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Sotto questa media di caratteri/pagina il PDF è considerato una scansione.
SOGLIA_SCANSIONE_CHARS = 50
# Righe ripetute in almeno questa quota di pagine = intestazione/piè di pagina.
SOGLIA_RIPETIZIONE = 0.6
# Fascia alta/bassa della pagina dove cercare intestazioni e piè di pagina.
FASCIA_BORDO = 0.15
# Una "tabella" più grande di questa quota della pagina è una cornice, non una tabella.
SOGLIA_CORNICE = 0.7

METODO_PDF = "pymupdf_layout"


@dataclass
class EstrazioneResult:
    testo: str = ""
    formato: str = ""
    metodo: str = ""
    n_pagine: int | None = None
    n_caratteri: int = 0
    n_sezioni: int = 0
    ha_testo_nativo: bool = True
    ocr_usato: bool = False
    avvisi: list[str] = field(default_factory=list)


def normalizza(testo: str) -> str:
    """NFC, sillabazioni a fine riga ricomposte, spazi collassati, righe vuote al massimo doppie."""
    testo = unicodedata.normalize("NFC", testo or "")
    testo = testo.replace("\r\n", "\n").replace("\r", "\n")
    testo = re.sub(r"(\w)-\n([a-zà-ÿ])", r"\1\2", testo)
    testo = re.sub(r"[ \t   ]+", " ", testo)
    testo = re.sub(r" *\n *", "\n", testo)
    testo = re.sub(r"\n{3,}", "\n\n", testo)
    return testo.strip()


def _chiave_ripetizione(riga: str) -> str:
    """Chiave di confronto tra pagine: minuscolo, numeri normalizzati, spazi singoli."""
    riga = re.sub(r"\d+", "#", riga.lower())
    return re.sub(r"\s+", " ", riga).strip()


def _cella(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("|", "/")


def tabella_markdown(righe: list[list]) -> str:
    """Righe di celle -> pipe-table Markdown (prima riga = intestazione). Vuota se nessun dato."""
    pulite = [[_cella(c) for c in riga] for riga in righe if riga is not None]
    pulite = [r for r in pulite if any(r)]
    if not pulite:
        return ""
    n_col = max(len(r) for r in pulite)
    pulite = [r + [""] * (n_col - len(r)) for r in pulite]
    out = ["| " + " | ".join(pulite[0]) + " |", "|" + "---|" * n_col]
    out += ["| " + " | ".join(r) + " |" for r in pulite[1:]]
    return "\n".join(out)


def _tabella_vera(tab, area_pagina: float) -> bool:
    try:
        x0, y0, x1, y1 = tab.bbox
        if (x1 - x0) * (y1 - y0) > SOGLIA_CORNICE * area_pagina:
            return False
        return tab.row_count >= 2 and tab.col_count >= 2
    except Exception:
        return False


def _dentro(bbox, contenitore) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return contenitore[0] <= cx <= contenitore[2] and contenitore[1] <= cy <= contenitore[3]


def _unita_pagina(page, avvisi_pagina: list[str]) -> list[dict]:
    """Unità ordinate di una pagina: blocchi di testo e tabelle, con posizione verticale."""
    altezza = page.rect.height or 1.0
    area = (page.rect.width or 1.0) * altezza
    tabelle = []
    try:
        tabelle = [t for t in page.find_tables().tables if _tabella_vera(t, area)]
    except Exception:
        avvisi_pagina.append("tabelle non ricostruite")
    unita: list[dict] = []
    for tab in tabelle:
        try:
            md = tabella_markdown(tab.extract())
        except Exception:
            md = ""
            avvisi_pagina.append("tabella non leggibile")
        if md:
            unita.append({"y": tab.bbox[1], "y1": tab.bbox[3], "tipo": "tabella", "testo": md})
    bbox_tabelle = [t.bbox for t in tabelle]
    for blocco in page.get_text("blocks", sort=True):
        x0, y0, x1, y1, testo, _n, tipo = blocco[:7]
        if tipo != 0 or not str(testo).strip():
            continue  # immagini o blocchi vuoti
        if any(_dentro((x0, y0, x1, y1), tb) for tb in bbox_tabelle):
            continue  # già nella pipe-table
        unita.append({"y": y0, "y1": y1, "tipo": "testo", "testo": str(testo)})
    unita.sort(key=lambda u: u["y"])
    for u in unita:
        u["bordo"] = u["y1"] <= FASCIA_BORDO * altezza or u["y"] >= (1 - FASCIA_BORDO) * altezza
    return unita


def _estrai_pdf(path: Path) -> EstrazioneResult:
    res = EstrazioneResult(formato="pdf", metodo=METODO_PDF)
    try:
        import fitz  # pymupdf
    except Exception:
        res.avvisi.append("pymupdf non disponibile")
        return res
    try:
        with fitz.open(str(path)) as doc:
            res.n_pagine = doc.page_count
            pagine: list[list[dict]] = []
            caratteri_grezzi = 0
            avvisi_tabelle = 0
            for page in doc:
                caratteri_grezzi += len(page.get_text().strip())
                avvisi_pagina: list[str] = []
                pagine.append(_unita_pagina(page, avvisi_pagina))
                avvisi_tabelle += len(avvisi_pagina)
    except Exception as exc:
        res.avvisi.append(f"PDF illeggibile: {type(exc).__name__}")
        return res

    n = len(pagine)
    res.ha_testo_nativo = bool(n) and (caratteri_grezzi / n) >= SOGLIA_SCANSIONE_CHARS
    if avvisi_tabelle:
        res.avvisi.append(f"{avvisi_tabelle} tabelle non ricostruite")

    # Intestazioni/piè di pagina: righe di bordo ripetute in >= 60% delle pagine.
    ripetute: set[str] = set()
    if n >= 2:
        conteggio: dict[str, int] = {}
        for unita in pagine:
            chiavi = set()
            for u in unita:
                if not u["bordo"]:
                    continue
                if u["tipo"] == "tabella":
                    chiavi.add(_chiave_ripetizione(u["testo"]))
                else:
                    chiavi.update(_chiave_ripetizione(r) for r in u["testo"].splitlines() if r.strip())
            for k in chiavi:
                conteggio[k] = conteggio.get(k, 0) + 1
        minimo = max(2, math.ceil(SOGLIA_RIPETIZIONE * n))
        ripetute = {k for k, c in conteggio.items() if c >= minimo and k}

    gia_visti: set[str] = set()
    rimosse = 0
    parti: list[str] = []
    for unita in pagine:
        for u in unita:
            if u["tipo"] == "tabella":
                k = _chiave_ripetizione(u["testo"])
                if u["bordo"] and k in ripetute:
                    if k in gia_visti:
                        rimosse += 1
                        continue
                    gia_visti.add(k)
                parti.append(u["testo"])
                continue
            righe = []
            for riga in u["testo"].splitlines():
                k = _chiave_ripetizione(riga)
                if u["bordo"] and k in ripetute:
                    if k in gia_visti:
                        rimosse += 1
                        continue
                    gia_visti.add(k)
                righe.append(riga)
            if any(r.strip() for r in righe):
                parti.append(normalizza("\n".join(righe)))
    if rimosse:
        res.avvisi.append(f"{rimosse} righe di intestazione/piè di pagina ripetute rimosse")

    res.testo = normalizza("\n\n".join(p for p in parti if p.strip())) if parti else ""
    res.n_caratteri = len(res.testo)
    res.n_sezioni = conta_sezioni(res.testo)
    if not res.ha_testo_nativo:
        res.avvisi.append("probabile scansione: testo nativo assente o scarso")
    return res


def conta_sezioni(testo: str) -> int:
    """Sezioni ``§`` riconosciute dal chunker del RAG (stessa regola, import lazy)."""
    if not testo:
        return 0
    try:
        from ai_assistant.services import _sgi_sections

        return sum(1 for label, _body in _sgi_sections(testo) if label)
    except Exception:
        return 0


def estrai(path: Path | str) -> EstrazioneResult:
    """Estrae il testo di un documento SGI con dispatch per estensione. Mai eccezioni."""
    try:
        path = Path(path)
        ext = path.suffix.lower()
        if ext == ".pdf":
            return _estrai_pdf(path)
        return EstrazioneResult(formato=ext.lstrip("."), metodo="", avvisi=[f"formato non supportato: {ext or '?'}"])
    except Exception as exc:  # fail-safe assoluto
        logger.debug("sgi_testo.estrai fallita: %s", exc)
        return EstrazioneResult(avvisi=[f"errore estrazione: {type(exc).__name__}"])


# ── Persistenza ──────────────────────────────────────────────────────────────


def revisioni_da_estrarre(*, forza: bool = False, solo: str = ""):
    """Revisioni correnti da file server di documenti attivi e indicizzabili, con il
    loro eventuale testo persistito. Esclusi i documenti fuori dal RAG (flag o
    deny-list roster): il loro testo non deve essere persistito per l'assistente."""
    from procedure_refresh.models import ProcedureRevision, SourceType

    qs = (
        ProcedureRevision.objects.filter(
            is_current=True, document__is_active=True, document__escludi_dal_rag=False,
            source_type=SourceType.FILESERVER,
        )
        .select_related("document", "testo_estratto")
        .order_by("document__code")
    )
    if solo:
        qs = qs.filter(document__code__iexact=solo.strip())
    try:
        from ai_assistant.services import _sgi_excluded_by_keyword
    except Exception:  # pragma: no cover
        _sgi_excluded_by_keyword = None
    out = []
    for rev in qs:
        if _sgi_excluded_by_keyword and _sgi_excluded_by_keyword(rev.document.code, rev.document.title):
            continue
        if not forza and _testo_aggiornato(rev):
            continue
        out.append(rev)
    return out


def _testo_aggiornato(rev) -> bool:
    try:
        esistente = rev.testo_estratto
    except Exception:
        return False
    return bool(rev.file_hash) and esistente.file_hash == rev.file_hash


def persisti_estrazione(rev, *, forza: bool = False) -> str:
    """Estrae e salva il testo di una revisione. Idempotente su ``file_hash``.

    Ritorna lo stato: ``estratto`` | ``invariato`` | ``saltato: <motivo>``.
    """
    from procedure_refresh.models import SgiTestoEstratto

    if not rev.file_hash:
        return "saltato: hash file mancante (rilanciare import_sgi_da_share)"
    if not forza and _testo_aggiornato(rev):
        return "invariato"
    path = Path(rev.source_path or "")
    try:
        if not path.is_file():
            return "saltato: file non raggiungibile"
    except OSError:
        return "saltato: file non raggiungibile"
    res = estrai(path)
    SgiTestoEstratto.objects.update_or_create(
        revision=rev,
        defaults={
            "file_hash": rev.file_hash,
            "formato": res.formato[:10],
            "metodo": res.metodo[:30],
            "testo": res.testo,
            "n_pagine": res.n_pagine,
            "n_caratteri": res.n_caratteri,
            "n_sezioni": res.n_sezioni,
            "ha_testo_nativo": res.ha_testo_nativo,
            "ocr_usato": res.ocr_usato,
            "avvisi": "\n".join(res.avvisi),
        },
    )
    return "estratto"

