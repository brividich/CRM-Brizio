"""Riferimenti dei processi qualificati (MOD.128) ↔ registro SGI (Procedure).

- :func:`cerca`: documenti del registro per il campo «Nuovo codice» (suggerimenti mentre si scrive);
- :func:`documento`: il documento del registro per un codice (esatto, poi stessa forma senza spazi,
  punti e zeri iniziali, poi codice che comincia così, es. «MOD.161» → «MOD.161 Rev…»);
- :func:`stato_riferimenti`: per ogni riferimento, il documento, la revisione in vigore e se è
  cambiata da quella verificata (``RiferimentoProcesso.revisione_vista``);
- :func:`suggeriti`: i documenti citati nel testo dei riferimenti (grafo ``SgiRiferimento``)
  che non sono ancora fra i riferimenti del processo.

I documenti riservati (con una regola di visibilità) non si propongono e non si cercano.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _chiave(codice: str) -> str:
    from procedure_refresh.sgi_riferimenti import chiave

    return chiave(codice)


def _riservati() -> set[str]:
    try:
        from procedure_refresh.libreria import codici_riservati

        return codici_riservati()
    except Exception:
        logger.exception("MOD.128: documenti riservati non leggibili")
        return set()


def _corrente(doc):
    return next((r for r in doc.revisions.all() if r.is_current), None)


def documento(codice: str, *, catalogo=None):
    """``(documento, revisione corrente)`` per un codice, oppure ``(None, None)``."""
    from procedure_refresh.models import ProcedureDocument

    codice = (codice or "").strip()
    if not codice:
        return None, None
    docs = catalogo
    if docs is None:
        docs = list(ProcedureDocument.objects.filter(is_active=True).prefetch_related("revisions"))
    k = _chiave(codice)
    esatto = [d for d in docs if d.code.upper() == codice.upper()]
    stessa = esatto or [d for d in docs if _chiave(d.code) == k]
    inizio = stessa or sorted((d for d in docs if _chiave(d.code).startswith(k) and len(k) >= 3),
                              key=lambda d: len(d.code))
    doc = (inizio or [None])[0]
    return doc, (_corrente(doc) if doc else None)


def stato_riferimenti(processo, *, catalogo=None) -> list[dict]:
    """Una riga per riferimento: documento, revisione, «nuova revisione da verificare»."""
    from procedure_refresh.models import ProcedureDocument

    if catalogo is None:
        catalogo = list(ProcedureDocument.objects.filter(is_active=True).prefetch_related("revisions"))
    out = []
    for rif in processo.riferimenti.all():
        doc, rev = documento(rif.codice, catalogo=catalogo)
        corrente = (rev.revision_code or "") if rev else ""
        out.append({
            "rif": rif, "doc": doc, "rev": rev, "corrente": corrente,
            "nel_registro": doc is not None,
            "nuova_revisione": bool(rev and rif.revisione_vista and corrente != rif.revisione_vista),
        })
    return out


def revisione_corrente(codice: str) -> str:
    """Il codice di revisione in vigore (vuoto se il documento non è nel registro)."""
    _doc, rev = documento(codice)
    return (rev.revision_code or "") if rev else ""


def suggeriti(processo, *, stato=None) -> list[dict]:
    """Documenti citati dai riferimenti (revisione in vigore) e non ancora fra i riferimenti."""
    from procedure_refresh.models import SgiRiferimento

    stato = stato if stato is not None else stato_riferimenti(processo)
    presenti = {_chiave(r["rif"].codice) for r in stato} | {_chiave(r["doc"].code) for r in stato if r["doc"]}
    revisioni = {r["rev"].pk: r["doc"].code for r in stato if r["rev"]}
    if not revisioni:
        return []
    riservati = _riservati()
    out, visti = [], set()
    for cit in (SgiRiferimento.objects.filter(da_revisione_id__in=list(revisioni), a_documento__isnull=False,
                                              a_documento__is_active=True)
                .select_related("a_documento").order_by("a_documento__code")):
        d = cit.a_documento
        k = _chiave(d.code)
        if k in presenti or k in visti or d.code in riservati:
            continue
        visti.add(k)
        out.append({"codice": d.code, "titolo": d.title, "citato_da": revisioni[cit.da_revisione_id]})
    return out


def cerca(testo: str, *, limite: int = 10) -> list[dict]:
    """Documenti del registro (in vigore, non riservati) per codice o titolo."""
    from django.db.models import Q

    from procedure_refresh.models import ProcedureDocument

    testo = (testo or "").strip()
    if len(testo) < 2:
        return []
    riservati = _riservati()
    out = []
    for d in (ProcedureDocument.objects.filter(is_active=True)
              .filter(Q(code__icontains=testo) | Q(title__icontains=testo))
              .prefetch_related("revisions").order_by("code")[: limite * 3]):
        if d.code in riservati:
            continue
        rev = _corrente(d)
        out.append({"codice": d.code, "titolo": d.title, "rev": (rev.revision_code or "") if rev else ""})
        if len(out) >= limite:
            break
    return out
