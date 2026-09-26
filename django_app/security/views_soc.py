"""Viste aggiuntive dell'innesto SOC IT - CN (non presenti nell'app SC-AI originale).

Tenute separate dal grande `views.py` di SC-AI per isolamento dell'innesto.
"""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from security.models import SecurityAsset, SecurityMailboxSource


def assets_list(request):
    """Elenco dei SecurityAsset con l'eventuale Asset HUB collegato (fase D2)."""
    assets = (
        SecurityAsset.objects.select_related("source", "hub_asset").order_by("hostname")
    )
    n_tot = assets.count()
    n_linked = assets.exclude(hub_asset__isnull=True).count()
    return render(
        request,
        "security/soc_assets.html",
        {"assets": assets, "n_tot": n_tot, "n_linked": n_linked},
    )


@require_POST
def run_mailbox_ingestion_view(request):
    """Esegue (sincrono) l'ingestione delle sorgenti mailbox graph/imap abilitate.

    Le credenziali (Graph/IMAP) vanno configurate nella Configuration Studio
    (`/soc/admin/config/general/`) come SecurityCenterSetting: qui non si toccano.
    Per esecuzioni pianificate usare il task django-q2 `ingest_security_mailboxes_task`.
    """
    from security.services.configuration import can_manage_security_config

    if not can_manage_security_config(request.user):
        messages.error(request, "Serve il permesso di configurazione del Security Center.")
        return redirect("security:admin_mailbox_sources_list")
    from security.services.mailbox_ingestion import run_mailbox_ingestion

    sources = list(
        SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual")
    )
    if not sources:
        messages.info(
            request,
            "Nessuna sorgente mailbox Graph/IMAP abilitata. Creane una e imposta le "
            "credenziali nella Configurazione (config generale).",
        )
        return redirect("security:admin_mailbox_sources_list")

    from security.services.mailbox_setup import run_summary

    # run_mailbox_ingestion NON solleva: l'esito sta nel run. Prima il try/except qui
    # non scattava mai e un errore di credenziali veniva riportato come «ok».
    ok = err = 0
    for src in sources:
        level, text = run_summary(run_mailbox_ingestion(src))
        if level == "error":
            err += 1
            messages.warning(request, f"«{src.name}»: {text}")
        else:
            ok += 1
    messages.success(request, f"Lettura caselle eseguita: {ok} ok, {err} in errore.")
    return redirect("security:admin_mailbox_sources_list")
