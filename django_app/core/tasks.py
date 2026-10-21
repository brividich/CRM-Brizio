"""Task periodici django-q2 trasversali (modulo core).

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_caporeparto_morning_digest() -> dict:
    """Digest mattutino per caporeparto (DPI in attesa + incidenti aperti del reparto).

    Wrappa ``send_caporeparto_morning_digest``. **Fail-safe**: no-op se non ci sono
    caporeparto assegnati o voci in sospeso; salta i capi senza ``email_notifica``.
    """
    from django.core.management import call_command

    try:
        call_command("send_caporeparto_morning_digest", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_caporeparto_morning_digest: eccezione inattesa")
        raise


def run_audit_sigilli() -> dict:
    """Sigillo mensile dell'audit: sigilla i mesi conclusi, verifica la catena,
    esporta su SharePoint (``core.audit_sigilli.ciclo_mensile``)."""
    from core.audit_sigilli import ciclo_mensile

    try:
        return {"ok": True, **ciclo_mensile()}
    except Exception:
        logger.exception("run_audit_sigilli: eccezione inattesa")
        raise


def run_report_pianificati() -> dict:
    """Genera e invia per mail i report pianificati arrivati a scadenza (Centro report)."""
    from core.report_centro.pianificazione import esegui_scadute

    try:
        return {"ok": True, **esegui_scadute()}
    except Exception:
        logger.exception("run_report_pianificati: eccezione inattesa")
        raise


def run_report_emissioni_pulizia() -> dict:
    """Elimina dal registro emissioni report le righe oltre la conservazione.

    Soglia in SiteConfig (Admin portale → Centro report → Registro); 0 = mai."""
    from core.report_centro.registro import giorni_conservazione, pulisci_scadute

    try:
        giorni = giorni_conservazione()
        return {"ok": True, "giorni": giorni, "eliminate": pulisci_scadute(giorni)}
    except Exception:
        logger.exception("run_report_emissioni_pulizia: eccezione inattesa")
        raise


def run_gdpr_retention() -> dict:
    """Conservazione GDPR degli archivi tecnici (``core/gdpr_retention.py``), applicata."""
    from core.gdpr_retention import esegui

    try:
        esiti = esegui(apply=True)
        return {"ok": not any(e["errore"] for e in esiti),
                "righe": {e["codice"]: e["righe"] for e in esiti}}
    except Exception:
        logger.exception("run_gdpr_retention: eccezione inattesa")
        raise


def run_notifiche_archivio() -> dict:
    """Archivia le notifiche in-app scadute ed elimina le archiviate oltre soglia.

    Soglie da ``core.notifiche_archivio.get_politica`` (SiteConfig)."""
    from core.notifiche_archivio import archivia_scadute

    try:
        return {"ok": True, **archivia_scadute()}
    except Exception:
        logger.exception("run_notifiche_archivio: eccezione inattesa")
        raise
