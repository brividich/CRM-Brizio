"""Aggregazione dati per il digest mattutino del caporeparto (AU51).

Ambito **verificato e schedulabile offline**: per ogni caporeparto (fonte
autorevole ``Reparto.caporeparto_legacy_id``) raccoglie
  - **DPI in attesa**: ``RichiestaDPI`` in stato ``INVIATA`` richieste dai
    dipendenti del suo reparto (legame pulito via ``richiedente_legacy_id``);
  - **incidenti aperti**: ``RilevazioneIncidente`` con ``chiusura_rspp=False`` nel
    reparto (legame via nome reparto).

**Volutamente esclusi** (non c'è un legame reparto pulito/offline):
  - *assenze da approvare*: il flusso è SharePoint e quel collegamento non è più
    in uso → nessun conteggio ORM affidabile;
  - *ticket del reparto*: il modello ``tickets`` non ha un legame reparto/dipendente.

L'aggregazione è isolata qui (testabile senza email); il management command
``send_caporeparto_morning_digest`` si limita a formattare e inviare.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def capi_legacy_ids() -> list[int]:
    """ID legacy dei caporeparto (reparti attivi con caporeparto assegnato)."""
    from anagrafica.models import Reparto

    return sorted({
        int(v)
        for v in Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=False)
        .values_list("caporeparto_legacy_id", flat=True)
        if v is not None
    })


def reparto_names_for_capo(capo_legacy_id: int) -> list[str]:
    """Nomi dei reparti attivi guidati da questo caporeparto."""
    from anagrafica.models import Reparto

    return [
        str(nome).strip()
        for nome in Reparto.objects.filter(
            is_active=True, caporeparto_legacy_id=int(capo_legacy_id)
        ).values_list("nome", flat=True)
        if str(nome or "").strip()
    ]


def employee_legacy_ids_for_capo(capo_legacy_id: int) -> set[int]:
    """ID legacy dei dipendenti assegnati al caporeparto.

    Legame primario autorevole: ``DipendenteAnagraficaAziendale.caporeparto_legacy_id``
    (coerente con ``assenze._anagrafica_employee_ids_for_capo``, senza il fallback
    fuzzy per nome-area, ambiguo dopo l'inversione gerarchia Reparto↔Area).
    """
    from anagrafica.models import DipendenteAnagraficaAziendale

    return {
        int(v)
        for v in DipendenteAnagraficaAziendale.objects.filter(
            caporeparto_legacy_id=int(capo_legacy_id)
        ).values_list("legacy_anagrafica_id", flat=True)
        if v is not None
    }


def capo_notification_email(capo_legacy_id: int) -> str:
    """Email di notifica del caporeparto (mai il campo ``email`` = login legacy)."""
    try:
        from core.legacy_models import AnagraficaDipendente

        email = (
            AnagraficaDipendente.objects.filter(id=int(capo_legacy_id))
            .values_list("email_notifica", flat=True)
            .first()
        ) or ""
        return str(email).strip()
    except Exception:
        logger.debug("capo_notification_email fallita per capo=%s", capo_legacy_id, exc_info=True)
        return ""


def build_caporeparto_digest(capo_legacy_id: int) -> dict:
    """Raccoglie DPI in attesa + incidenti aperti per un caporeparto.

    Ritorna un dict serializzabile: ``{capo_legacy_id, email, reparti, dpi[], incidenti[], totale}``.
    Le liste contengono gli oggetti ORM (il command li formatta). Fail-safe per modulo.
    """
    reparti = reparto_names_for_capo(capo_legacy_id)
    emp_ids = employee_legacy_ids_for_capo(capo_legacy_id)

    dpi_in_attesa = []
    try:
        from dpi.models import RichiestaDPI, StatoRichiesta

        if emp_ids:
            dpi_in_attesa = list(
                RichiestaDPI.objects.filter(
                    stato=StatoRichiesta.INVIATA, richiedente_legacy_id__in=emp_ids
                ).order_by("-id")
            )
    except Exception:
        logger.debug("build_caporeparto_digest: DPI fallito per capo=%s", capo_legacy_id, exc_info=True)

    incidenti_aperti = []
    try:
        from rilevazione_incidenti.models import RilevazioneIncidente

        if reparti:
            incidenti_aperti = list(
                RilevazioneIncidente.objects.filter(
                    chiusura_rspp=False, reparto__in=reparti
                ).order_by("-id")
            )
    except Exception:
        logger.debug("build_caporeparto_digest: incidenti fallito per capo=%s", capo_legacy_id, exc_info=True)

    return {
        "capo_legacy_id": int(capo_legacy_id),
        "email": capo_notification_email(capo_legacy_id),
        "reparti": reparti,
        "dpi": dpi_in_attesa,
        "incidenti": incidenti_aperti,
        "totale": len(dpi_in_attesa) + len(incidenti_aperti),
    }
