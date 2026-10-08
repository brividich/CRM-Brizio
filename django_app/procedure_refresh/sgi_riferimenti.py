"""Grafo dei riferimenti incrociati tra documenti SGI (fase A2, deterministico, zero AI).

Trova nel testo estratto di una revisione i codici di altri documenti SGI citati
(«vedi MOD.093», «secondo MT CN 06», «IDOR CN 01 Allegato A») e li collega al
catalogo ``ProcedureDocument``:

- riconoscimento con lo **stesso** ``_CODE_RE`` dell'import dalla share (importato,
  non copiato), usato in qualunque punto del testo con confini di parola e maiuscole
  esatte: in un testo libero «mq 50», «pg. 3» o «io 2» non sono codici;
- normalizzazione con ``_safe_code`` («MOD. 093» → «MOD.093»; un codice spezzato a
  fine riga torna su una riga);
- esclusi l'autocitazione e le righe ripetute del cartiglio (stessa riga ≥ 3 volte);
- risoluzione per codice esatto, poi per forma normalizzata (spazi, punti, zeri
  iniziali), poi per codice disambiguato dall'import (``dedup_candidates``);
  un allegato senza documento proprio si risolve sul documento base;
- le norme esterne (ISO, EN, AS, UNI, ASTM, ...) non sono riferimenti SGI: vengono
  solo contate, per il report.

Ricostruzione per revisione in transazione (delete + insert) a ogni nuova estrazione.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

from django.db import transaction

from procedure_refresh.management.commands.import_sgi_da_share import _CODE_RE, _norm_spaces, _safe_code

logger = logging.getLogger(__name__)

# _CODE_RE è ancorato a inizio nome file (^): qui serve in qualunque punto del testo.
_CITAZIONE_RE = re.compile(r"(?<![A-Za-z0-9.])" + _CODE_RE.pattern.removeprefix("^") + r"(?![A-Za-z0-9_])")
_ALLEGATO_RE = re.compile(r"\s+Allegato\s+[A-Za-z0-9]+$")
_NORMA_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(UNI\s+EN\s+ISO|UNI\s+CEI\s+EN|UNI\s+EN|UNI\s+ISO|CEI\s+EN|EN\s+ISO|ISO\s*/\s*IEC|ISO|EN|AS|UNI|ASTM|IEC)"
    r"\s*(?:-\s*)?(?:[A-Z]\s?)?(\d{2,5})(?:[-:.]\d{1,4})*(?![A-Za-z0-9])"
)
# «MT CN» a fine riga e numero a capo: _CODE_RE ammette un solo spazio dopo CN.
_CN_A_CAPO_RE = re.compile(r"(?<=CN)[ \t]*\r?\n[ \t]*(?=\d)")
RIPETIZIONI_CARTIGLIO = 3


def _ricuci(testo: str) -> str:
    """Rimette su una riga i codici spezzati a fine riga dopo «CN»."""
    return _CN_A_CAPO_RE.sub(" ", testo or "")


@dataclass(frozen=True)
class Citazione:
    codice: str
    sezione: str
    occorrenze: int


def chiave(codice: str) -> str:
    """Forma di confronto: maiuscolo, senza spazi né punti, senza zeri iniziali."""
    compatto = re.sub(r"[\s.]+", "", (codice or "").upper())
    return re.sub(r"(?<!\d)0+(?=\d)", "", compatto)


def codici_citati(testo: str) -> list[str]:
    """Codici SGI citati in un testo libero, normalizzati, in ordine di comparsa."""
    return [_safe_code(_norm_spaces(m.group("code"))) for m in _CITAZIONE_RE.finditer(_ricuci(testo))]


def norme_citate(testo: str) -> Counter:
    """Norme esterne citate (es. «ISO 9001», «UNI EN 1090») → occorrenze. Non sono riferimenti SGI."""
    out: Counter = Counter()
    for m in _NORMA_RE.finditer(testo or ""):
        out[f"{_norm_spaces(m.group(1)).replace(' / ', '/')} {m.group(2)}"] += 1
    return out


def _righe_cartiglio(testo: str) -> set[str]:
    conta = Counter(r.strip() for r in testo.splitlines() if r.strip())
    return {r for r, n in conta.items() if n >= RIPETIZIONI_CARTIGLIO}


def _sezioni(testo: str) -> list[tuple[int, str]]:
    """(offset di inizio, etichetta «§n Titolo») delle sezioni, con la stessa regola di
    heading del chunker RAG (``_sgi_sections``). Le citazioni si cercano sul testo intero,
    così un codice spezzato a fine riga non viene tagliato da un falso heading («06 e…»)."""
    from ai_assistant.services import _SGI_HEADING_RE

    out: list[tuple[int, str]] = [(0, "")]
    offset = 0
    for riga in testo.splitlines(keepends=True):
        m = _SGI_HEADING_RE.match(riga.rstrip("\r\n"))
        if m and len(riga.strip()) <= 90 and any(ch.isalpha() for ch in m.group(2)):
            out.append((offset, f"§{m.group(1)} {m.group(2).strip()}"[:160]))
        offset += len(riga)
    return out


def estrai_citazioni(testo: str, codice_proprio: str = "") -> list[Citazione]:
    """Citazioni per (codice, sezione) con il numero di occorrenze. Pura, niente DB."""
    if not testo:
        return []
    testo = _ricuci(testo)
    proprio = chiave(codice_proprio)
    cartiglio = _righe_cartiglio(testo)
    sezioni = _sezioni(testo)
    conteggi: Counter = Counter()
    for m in _CITAZIONE_RE.finditer(testo):
        inizio_riga = testo.rfind("\n", 0, m.start()) + 1
        fine_riga = testo.find("\n", m.start())
        if testo[inizio_riga: fine_riga if fine_riga >= 0 else None].strip() in cartiglio:
            continue
        codice = _safe_code(_norm_spaces(m.group("code")))
        if proprio and chiave(codice) == proprio:
            continue
        sezione = next(label for off, label in reversed(sezioni) if off <= m.start())
        conteggi[(codice, sezione)] += 1
    return [Citazione(codice=c, sezione=s, occorrenze=n) for (c, s), n in conteggi.items()]


class Catalogo:
    """Risolve un codice citato su ``ProcedureDocument`` (una query, poi in memoria)."""

    def __init__(self, documenti=None):
        if documenti is None:
            from procedure_refresh.models import ProcedureDocument

            documenti = list(ProcedureDocument.objects.order_by("-is_active", "code").only("id", "code", "is_active"))
        self.esatti: dict[str, object] = {}
        self.normalizzati: dict[str, object] = {}
        for doc in documenti:
            self.esatti.setdefault(doc.code.upper(), doc)
            self.normalizzati.setdefault(chiave(doc.code), doc)
        self.documenti = documenti

    def risolvi(self, codice: str):
        doc = self.esatti.get(codice.upper()) or self.normalizzati.get(chiave(codice))
        if doc is not None:
            return doc
        # Codice disambiguato dall'import: «IDOR CN 02» → «IDOR CN 02 ISMS» se il nudo non c'è.
        prefisso = codice.upper() + " "
        for d in self.documenti:
            if d.code.upper().startswith(prefisso):
                return d
        base = _ALLEGATO_RE.sub("", codice)
        if base != codice:
            return self.risolvi(base)
        return None


def ricostruisci(rev, testo: str, *, catalogo: Catalogo | None = None) -> int:
    """Sostituisce i riferimenti uscenti della revisione (transazione). Ritorna quanti."""
    from procedure_refresh.models import SgiRiferimento

    catalogo = catalogo or Catalogo()
    righe = []
    for c in estrai_citazioni(testo, rev.document.code):
        doc = catalogo.risolvi(c.codice)
        if doc is not None and doc.pk == rev.document_id:
            continue  # autocitazione con un'altra grafia
        righe.append(SgiRiferimento(da_revisione=rev, codice_citato=c.codice[:60], a_documento=doc,
                                    sezione=c.sezione, occorrenze=c.occorrenze, risolto=doc is not None))
    with transaction.atomic():
        SgiRiferimento.objects.filter(da_revisione=rev).delete()
        SgiRiferimento.objects.bulk_create(righe)
    return len(righe)


def ricostruisci_sicuro(rev, testo: str) -> None:
    """Variante per la catena di estrazione: un errore qui non blocca il testo persistito."""
    try:
        ricostruisci(rev, testo)
    except Exception:
        logger.exception("sgi_riferimenti: ricostruzione fallita per revisione %s", rev.pk)
