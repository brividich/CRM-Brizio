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

    ok = err = 0
    for src in sources:
        try:
            run_mailbox_ingestion(src)
            ok += 1
        except Exception as exc:  # errore connessione/credenziali → segnalato all'utente
            err += 1
            messages.warning(request, f"«{src.name}»: {exc}")
    messages.success(request, f"Ingestione mailbox eseguita: {ok} sorgenti ok, {err} in errore.")
    return redirect("security:admin_mailbox_sources_list")
