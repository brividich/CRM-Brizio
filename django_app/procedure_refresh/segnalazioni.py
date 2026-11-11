"""CN-SGI: segnalazioni di modifica e riletture.

- :func:`avvisa_nuova`: notifica nel portale a chi gestisce CN-SGI per ogni nuova segnalazione
  (destinatari del riepilogo settimanale e chi ha già gestito segnalazioni);
- :func:`avvisa_autore`: notifica a chi ha segnalato quando la segnalazione cambia stato;
- :func:`mie`: le segnalazioni dell'utente per «Le mie letture»;
- :func:`da_rileggere` / :func:`crea_rilettura`: dopo una nuova revisione, la richiesta di presa
  visione per chi aveva letto (o doveva leggere) le revisioni precedenti.

Fail-safe: un errore nelle notifiche non blocca mai il salvataggio della segnalazione.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

URL_SEGNALAZIONI = "/procedure-refresh/admin/segnalazioni/"
URL_LETTURE = "/procedure-refresh/letture/"
GIORNI_RILETTURA = 14


def _stato_txt(cr) -> str:
    if cr.status == "recepita" and getattr(cr, "recepita_in_revisione", None):
        return f"recepita nella Rev.{cr.recepita_in_revisione.revision_code}"
    return cr.get_status_display().lower()


def destinatari_gestori() -> set[int]:
    """Legacy id di chi riceve gli avvisi delle segnalazioni."""
    from core.notifiche import legacy_user_ids_for_email
    from procedure_refresh.models import ProcedureChangeRequest
    from procedure_refresh.reminder_config import get_reminder_config
    from procedure_refresh.tasks import _legacy_id_map

    ids: set[int] = set()
    try:
        for email in get_reminder_config().get("digest_destinatari") or []:
            ids.update(legacy_user_ids_for_email(email))
    except Exception:
        logger.exception("CN-SGI: destinatari del riepilogo non leggibili")
    try:
        gestori = list(
            ProcedureChangeRequest.objects.exclude(gestita_da=None).values_list("gestita_da_id", flat=True).distinct()[:20]
        )
        ids.update(v for v in _legacy_id_map(gestori).values() if v)
    except Exception:
        logger.exception("CN-SGI: gestori delle segnalazioni non leggibili")
    return ids


def avvisa_nuova(cr, *, escludi_user_id=None) -> int:
    """Avvisa chi gestisce di una nuova segnalazione. Ritorna quante notifiche ha creato."""
    try:
        from core.notifiche import invia_notifica
        from procedure_refresh.tasks import _legacy_id_map

        escluso = _legacy_id_map([escludi_user_id]).get(escludi_user_id) if escludi_user_id else None
        n = 0
        for legacy_id in destinatari_gestori():
            if legacy_id == escluso:
                continue
            invia_notifica(
                legacy_id, "presa_visione",
                f"Nuova segnalazione di modifica su {cr.document.code}: «{(cr.testo or '')[:90]}»",
                url_azione=f"{URL_SEGNALAZIONI}?doc={cr.document_id}",
            )
            n += 1
        return n
    except Exception:
        logger.exception("CN-SGI: avviso nuova segnalazione fallito")
        return 0


def avvisa_autore(cr) -> bool:
    """Avvisa chi ha segnalato del nuovo stato, con la risposta di chi gestisce."""
    try:
        if not cr.created_by_id:
            return False
        from core.notifiche import invia_notifica
        from procedure_refresh.tasks import _legacy_id_map

        legacy_id = _legacy_id_map([cr.created_by_id]).get(cr.created_by_id)
        if not legacy_id:
            return False
        risposta = f" Risposta: «{cr.risposta_gestore[:120]}»" if cr.risposta_gestore else ""
        invia_notifica(
            legacy_id, "presa_visione",
            f"La tua segnalazione su {cr.document.code} è {_stato_txt(cr)}.{risposta}",
            url_azione=f"{URL_LETTURE}#segnalazioni",
        )
        return True
    except Exception:
        logger.exception("CN-SGI: avviso all'autore della segnalazione fallito")
        return False


def aperte() -> int:
    from procedure_refresh.models import ChangeRequestStatus, ProcedureChangeRequest

    try:
        return ProcedureChangeRequest.objects.filter(
            status__in=[ChangeRequestStatus.APERTA, ChangeRequestStatus.IN_CARICO]
        ).count()
    except Exception:
        return 0


def mie(user, limite: int = 50) -> list:
    from procedure_refresh.models import ProcedureChangeRequest

    if not getattr(user, "is_authenticated", False):
        return []
    return list(
        ProcedureChangeRequest.objects.filter(created_by=user)
        .select_related("document", "recepita_in_revisione")
        .order_by("-created_at")[:limite]
    )


def recepite_in(rev) -> list:
    from procedure_refresh.models import ChangeRequestStatus, ProcedureChangeRequest

    return list(
        ProcedureChangeRequest.objects.filter(recepita_in_revisione=rev, status=ChangeRequestStatus.RECEPITA)
        .select_related("created_by")
        .order_by("created_at")
    )


# ---------------------------------------------------------------------------
# Rilettura dopo una nuova revisione
# ---------------------------------------------------------------------------


def da_rileggere(doc, rev) -> list[int]:
    """Utenti che avevano una presa visione su una revisione precedente e non ce l'hanno su quella in vigore."""
    from procedure_refresh.models import AssignmentStatus, ProcedureAssignment

    precedenti = set(
        ProcedureAssignment.objects.filter(revision__document=doc)
        .exclude(revision=rev)
        .exclude(status=AssignmentStatus.CANCELLED)
        .values_list("user_id", flat=True)
    )
    gia = set(
        ProcedureAssignment.objects.filter(revision=rev).exclude(status=AssignmentStatus.CANCELLED).values_list("user_id", flat=True)
    )
    return sorted(precedenti - gia)


def crea_rilettura(doc, rev, *, da_utente, giorni: int = GIORNI_RILETTURA):
    """Richiesta di presa visione pubblicata della revisione in vigore per chi aveva letto le precedenti.

    Ritorna ``(campagna, n_persone)``; ``(None, 0)`` se non c'è nessuno da avvisare.
    """
    from core.notifiche import invia_notifica
    from procedure_refresh.models import (
        AssignmentStatus,
        CampaignStatus,
        ProcedureAssignment,
        ProcedureCampaign,
        ProcedureCampaignDocument,
    )
    from procedure_refresh.tasks import _legacy_id_map

    utenti = da_rileggere(doc, rev)
    if not utenti:
        return None, 0
    oggi = timezone.localdate()
    scadenza = oggi + timedelta(days=max(1, min(int(giorni or GIORNI_RILETTURA), 120)))
    etichetta = f"Rev.{rev.revision_code}" if rev.revision_code else "nuova revisione"
    campagna = ProcedureCampaign.objects.create(
        name=f"Rilettura {doc.code} {etichetta}"[:200],
        description=f"Nuova revisione di {doc.code} · {doc.title}: rilettura per chi aveva preso visione delle revisioni precedenti.",
        status=CampaignStatus.PUBLISHED,
        start_date=oggi,
        due_date=scadenza,
        created_by=da_utente,
        published_at=timezone.now(),
    )
    ProcedureCampaignDocument.objects.create(campaign=campagna, revision=rev, is_mandatory=True, display_order=0)
    for uid in utenti:
        ProcedureAssignment.objects.get_or_create(
            campaign=campagna, revision=rev, user_id=uid,
            defaults={"assigned_by": da_utente, "due_date": scadenza, "status": AssignmentStatus.ASSIGNED},
        )
    mappa = _legacy_id_map(utenti)
    for uid in utenti:
        invia_notifica(
            mappa.get(uid), "presa_visione",
            f"{doc.code} è cambiato ({etichetta}): rileggilo entro il {scadenza:%d/%m/%Y}.",
            url_azione=URL_LETTURE,
        )
    return campagna, len(utenti)
