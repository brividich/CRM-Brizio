"""Catalogo corsi: azioni in blocco dall'elenco Corsi (tipo, validità) e corsi una tantum da rivedere.

Analisi del 26/11/2026: nessun corso aveva un tipo (quindi nessuna valutazione di efficacia) e
molti corsi di «aggiornamento» o con rinnovo di legge erano una tantum (nessuna scadenza).
"""
from __future__ import annotations

import re

from django.db import transaction


class CatalogoError(Exception):
    pass


# Parole che fanno pensare a un corso con rinnovo periodico (da confermare con RSPP/Qualità).
_PAROLE_RINNOVO = re.compile(
    r"aggiornament|antincendio|primo\s+soccorso|carrell|muletti?\b|preposti?\b|\bple\b|piattaform"
    r"|\bgru\b|carroponte|\brls\b|\brspp\b|\baspp\b|spazi\s+confinati|lavori\s+in\s+quota|ponteggi"
    r"|\bdpi\b.*terza|blsd?\b|defibrillat",
    re.IGNORECASE,
)


def ids_una_tantum_da_rivedere() -> list[int]:
    """Corsi senza validità (una tantum) il cui titolo fa pensare a un rinnovo."""
    from django.db.models import Q

    from ..models_formazione import TrainingCourse

    out = []
    for pk, titolo in (TrainingCourse.objects.filter(Q(validita_mesi__isnull=True) | Q(validita_mesi=0))
                       .exclude(stato="ARCHIVIATO").values_list("pk", "titolo")):
        if _PAROLE_RINNOVO.search(titolo or ""):
            out.append(pk)
    return out


def assegna_tipo(ids: list[int], tipo_id: str) -> tuple[int, str]:
    from ..models_formazione import TrainingCourse, TrainingCourseType

    if tipo_id == "nessuno":
        n = TrainingCourse.objects.filter(pk__in=ids).update(tipo=None)
        return n, "nessuno"
    tipo = TrainingCourseType.objects.filter(pk=int(tipo_id) if str(tipo_id).isdigit() else 0).first()
    if tipo is None:
        raise CatalogoError("Scegli il tipo da assegnare.")
    n = TrainingCourse.objects.filter(pk__in=ids).update(tipo=tipo)
    return n, tipo.nome


def imposta_validita(ids: list[int], mesi: str, *, riempi_scadenze: bool = False, user=None) -> dict:
    """Cambia la validità dei corsi. Con ``riempi_scadenze`` i completamenti validi senza data di
    scadenza ricevono completamento + validità; le scadenze già scritte (attestato) non cambiano.
    Le scadenze del cruscotto si ricalcolano per i corsi toccati."""
    from ..models_formazione import TrainingCourse, TrainingDeadline, TrainingEmployeeRecord
    from ..views._helpers import _add_months

    if not str(mesi).strip().isdigit():
        raise CatalogoError("Scrivi la validità in mesi (0 = una tantum).")
    mesi = min(int(mesi), 240)
    n_scadenze = 0
    with transaction.atomic():
        n = TrainingCourse.objects.filter(pk__in=ids).update(validita_mesi=mesi)
        if riempi_scadenze and mesi:
            for r in TrainingEmployeeRecord.objects.filter(corso_id__in=ids, data_scadenza__isnull=True,
                                                           idoneo=True).only("pk", "data_completamento"):
                TrainingEmployeeRecord.objects.filter(pk=r.pk).update(
                    data_scadenza=_add_months(r.data_completamento, mesi))
                n_scadenze += 1
        TrainingDeadline.objects.filter(corso_id__in=ids).update(needs_refresh=True)
    try:
        from .training_deadline_service import refresh_deadlines
        for cid in ids:
            refresh_deadlines(corso_id=cid)
    except Exception:  # noqa: BLE001 - il ricalcolo riparte comunque al prossimo giro pianificato
        import logging
        logging.getLogger(__name__).exception("Ricalcolo scadenze dopo la validità non riuscito")
    return {"corsi": n, "mesi": mesi, "scadenze": n_scadenze}
