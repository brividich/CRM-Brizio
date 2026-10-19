"""Viste del modulo Automazioni — Impostazioni del modulo e notifiche di sistema.

Spacchettamento di ``automazioni/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations


from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from admin_portale.decorators import legacy_admin_or_acl_required

from ..models import (
    AutomationRunLog,
)
from ..approval_mailbox_runtime import (
    get_approval_graph_form_defaults,
    get_approval_graph_status,
    get_approval_imap_form_defaults,
    get_approval_imap_status,
    get_approval_mailbox_backend,
    get_default_approval_mailbox_details,
    run_approval_poll_now,
    run_approval_imap_poll_now,
    save_approval_graph_settings,
    save_approval_imap_settings,
    MAILBOX_BACKEND_GRAPH,
    MAILBOX_BACKEND_IMAP,
)



from . import _helpers  # noqa: E402


def _safe_runlog_count() -> int | None:
    """Numero totale di RunLog in tabella (per contesto in UI). None se non leggibile."""
    try:
        return AutomationRunLog.objects.count()
    except Exception:
        return None


def _build_automation_settings_context(
    *,
    poll_result=None,
    approval_imap_form=None,
    approval_graph_form=None,
) -> dict[str, object]:
    from ..approval_email_templates import APPROVAL_MAILBOX_SITE_CONFIG_KEY
    from ..scadenze_config import get_scadenze_config
    from ..runlog_retention import (
        get_retention_days,
        DEFAULT_RETENTION_DAYS,
        RETENTION_MIN,
        RETENTION_MAX,
    )

    mailbox_details = get_default_approval_mailbox_details()
    active_backend = get_approval_mailbox_backend()
    return {
        **_helpers._base_context(),
        # ── Retention RunLog (GDPR) ────────────────────────────────────────
        "runlog_retention_days": get_retention_days(),
        "runlog_retention_default": DEFAULT_RETENTION_DAYS,
        "runlog_retention_min": RETENTION_MIN,
        "runlog_retention_max": RETENTION_MAX,
        "runlog_total_count": _safe_runlog_count(),
        # ── Report scadenze (visite mediche / contratti) ──────────────────
        "scadenze_config": get_scadenze_config(),
        # ── Graph (nuovo backend) ──────────────────────────────────────────
        "approval_graph_status": get_approval_graph_status(),
        "approval_graph_form": approval_graph_form or get_approval_graph_form_defaults(),
        # ── IMAP (retrocompat) ────────────────────────────────────────────
        "approval_imap_status": get_approval_imap_status(),
        "approval_imap_form": approval_imap_form or get_approval_imap_form_defaults(),
        # ── Backend attivo ────────────────────────────────────────────────
        "approval_mailbox_backend": active_backend,
        "approval_mailbox_backend_is_graph": active_backend == MAILBOX_BACKEND_GRAPH,
        "approval_mailbox_backend_is_imap": active_backend == MAILBOX_BACKEND_IMAP,
        # ── Risultato ultimo poll ─────────────────────────────────────────
        # Separati per evitare che il risultato di un backend appaia nel pannello dell'altro.
        "approval_graph_result": poll_result if active_backend == MAILBOX_BACKEND_GRAPH else None,
        "approval_imap_result": poll_result if active_backend == MAILBOX_BACKEND_IMAP else None,
        "approval_mailbox_site_config_key": APPROVAL_MAILBOX_SITE_CONFIG_KEY,
        "approval_mailbox_site_config_value": (
            str(mailbox_details["value"] or "") if mailbox_details.get("source") == "site_config" else ""
        ),
    }


@legacy_admin_or_acl_required("automazioni", "event_notifications_page")
@require_GET
def event_notifications_page(request):
    """Flussi su evento con collegamento al designer e stato corrente."""
    from ..event_notifications import get_event_notifications

    rows = get_event_notifications()
    context = {
        **_helpers._base_context(),
        "rows": rows,
        "totale": len(rows),
    }
    # Mail del modulo anomalie: stesso pannello di Configurazione → Notifiche,
    # stessi dati (nessuna copia). Un errore qui non deve rompere la pagina.
    try:
        from anomalie.notifiche import stato_pannello
        from anomalie.views import _can_manage_anomalie_config

        context["notifiche"] = stato_pannello()
        context["notifiche_modificabile"] = _can_manage_anomalie_config(request)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Pannello notifiche anomalie non disponibile", exc_info=True)
    return render(request, "automazioni/pages/notifiche_sistema.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Canali Teams — gestione TeamsWebhookPreset
# ─────────────────────────────────────────────────────────────────────────────

@legacy_admin_or_acl_required("automazioni", "settings_page")
def settings_page(request):
    from core.models import SiteConfig

    poll_result = None
    approval_imap_form = get_approval_imap_form_defaults()
    approval_graph_form = get_approval_graph_form_defaults()

    if request.method == "POST":
        action = _helpers._string_value(request.POST.get("action"))

        if action == "save_scadenze_config":
            from ..scadenze_config import save_scadenze_config

            try:
                posted_giorni = int(_helpers._string_value(request.POST.get("scadenze_giorni")) or "30")
            except (TypeError, ValueError):
                posted_giorni = 30
            saved = save_scadenze_config(
                attivo=_helpers._bool_value(request.POST.get("scadenze_attivo")),
                giorni=posted_giorni,
                email_visite=_helpers._string_value(request.POST.get("scadenze_email_visite")),
                email_contratti=_helpers._string_value(request.POST.get("scadenze_email_contratti")),
                email_qualifiche=_helpers._string_value(request.POST.get("scadenze_email_qualifiche")),
                includi_visite=_helpers._bool_value(request.POST.get("scadenze_includi_visite")),
                includi_contratti=_helpers._bool_value(request.POST.get("scadenze_includi_contratti")),
                includi_qualifiche=_helpers._bool_value(request.POST.get("scadenze_includi_qualifiche")),
            )
            if saved:
                messages.success(request, "Configurazione report scadenze salvata.")
            else:
                messages.error(request, "Impossibile salvare la configurazione report scadenze.")
            return redirect("admin_portale:automazioni_settings")

        if action == "save_runlog_retention":
            from ..runlog_retention import set_retention_days

            try:
                saved_days = set_retention_days(_helpers._string_value(request.POST.get("runlog_retention_days")))
                messages.success(
                    request,
                    f"Retention RunLog impostata a {saved_days} giorni.",
                )
            except Exception:
                messages.error(request, "Impossibile salvare la retention RunLog.")
            return redirect("admin_portale:automazioni_settings")

        if action == "run_runlog_cleanup":
            from django.core.management import call_command
            from io import StringIO

            try:
                buf = StringIO()
                call_command("cleanup_run_logs", apply=True, stdout=buf, verbosity=1)
                messages.success(request, "Pulizia RunLog eseguita. " + buf.getvalue().strip().splitlines()[-1])
            except Exception as exc:
                messages.error(request, f"Pulizia RunLog fallita: {exc}")
            return redirect("admin_portale:automazioni_settings")

        if action == "save_default_approval_mailbox":
            from ..approval_email_templates import APPROVAL_MAILBOX_SITE_CONFIG_KEY

            mailbox_value = _helpers._string_value(request.POST.get("approval_mailbox"))
            saved = SiteConfig.set(
                APPROVAL_MAILBOX_SITE_CONFIG_KEY,
                mailbox_value,
                "Mailbox tecnica globale usata dai template approvazione mail_reply/hybrid.",
            )
            if saved:
                messages.success(request, "Mailbox tecnica predefinita aggiornata.")
            else:
                messages.error(request, "Impossibile salvare la mailbox tecnica in SiteConfig.")
            return redirect("admin_portale:automazioni_settings")

        # ── Azioni Graph backend ──────────────────────────────────────────────
        if action == "save_approval_graph_config":
            try:
                posted_page_size = max(1, min(int(_helpers._string_value(request.POST.get("approval_graph_page_size")) or "25"), 50))
            except (TypeError, ValueError):
                posted_page_size = 25

            approval_graph_form = {
                "mailbox": _helpers._string_value(request.POST.get("approval_graph_mailbox")),
                "folder": _helpers._string_value(request.POST.get("approval_graph_folder")) or "Inbox",
                "only_unread": _helpers._bool_value(request.POST.get("approval_graph_only_unread")),
                "page_size": posted_page_size,
                "mark_read": _helpers._bool_value(request.POST.get("approval_graph_mark_read")),
            }
            ok, message = save_approval_graph_settings(
                mailbox=str(approval_graph_form["mailbox"]),
                folder=str(approval_graph_form["folder"]),
                only_unread=bool(approval_graph_form["only_unread"]),
                page_size=int(approval_graph_form["page_size"]),
                mark_read=bool(approval_graph_form["mark_read"]),
            )
            poll_result = {"ok": ok, "message": message, "output": "", "stats": {}}
            if ok:
                approval_graph_form = get_approval_graph_form_defaults()
                messages.success(request, message)
            else:
                messages.error(request, message)

        if action == "run_approval_graph_poll":
            poll_result = run_approval_poll_now(limit=25)
            if poll_result.get("ok"):
                messages.success(request, str(poll_result.get("message") or "Polling Graph completato."))
            else:
                messages.error(request, str(poll_result.get("message") or "Polling Graph fallito."))

        # ── Azioni IMAP backend (retrocompat) ────────────────────────────────
        if action == "save_approval_imap_config":
            posted_port = _helpers._string_value(request.POST.get("approval_imap_port"))
            try:
                parsed_port = max(int(posted_port or approval_imap_form["port"]), 1)
            except (TypeError, ValueError):
                parsed_port = int(approval_imap_form["port"])

            approval_imap_form = {
                "host": _helpers._string_value(request.POST.get("approval_imap_host")),
                "port": parsed_port,
                "user": _helpers._string_value(request.POST.get("approval_imap_user")),
                "password": "",
                "folder": _helpers._string_value(request.POST.get("approval_imap_folder")) or "INBOX",
                "use_ssl": _helpers._bool_value(request.POST.get("approval_imap_use_ssl")),
                "password_configured": bool(_helpers._string_value(request.POST.get("approval_imap_password")))
                or bool(approval_imap_form.get("password_configured")),
            }
            ok, message = save_approval_imap_settings(
                host=str(approval_imap_form["host"]),
                port=int(approval_imap_form["port"]),
                user=str(approval_imap_form["user"]),
                password=_helpers._string_value(request.POST.get("approval_imap_password")),
                use_ssl=bool(approval_imap_form["use_ssl"]),
                folder=str(approval_imap_form["folder"]),
            )
            poll_result = {"ok": ok, "message": message, "output": "", "stats": {}}
            if ok:
                approval_imap_form = get_approval_imap_form_defaults()
                messages.success(request, message)
            else:
                messages.error(request, message)

        if action == "run_approval_imap_poll":
            poll_result = run_approval_imap_poll_now()
            if poll_result.get("ok"):
                messages.success(request, str(poll_result.get("message") or "Polling IMAP completato."))
            else:
                messages.error(request, str(poll_result.get("message") or "Polling IMAP fallito."))

    return render(
        request,
        "automazioni/pages/impostazioni.html",
        _build_automation_settings_context(
            poll_result=poll_result,
            approval_imap_form=approval_imap_form,
            approval_graph_form=approval_graph_form,
        ),
    )
