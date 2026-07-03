"""#6 — Sezione «Amministrazione Specifiche» del modulo (gated ACL ``PERM_ADMIN``).

Pagina principale con le aree gestibili + gestione della mappatura Cliente→cartella.
Le aree Timbri (#2), Auto-approvazione (#3) e Notifiche (#5) sono placeholder finché
i rispettivi interventi non le riempiono.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .acl_bootstrap import PERM_ADMIN
from .cartelle_cliente import cartelle_disponibili
from .models import AutoApprovazioneConfig, ClienteCartellaShare, NotificaConfig


def utente_puo_admin(request) -> bool:
    """True se l'utente ha il permesso ACL della sezione admin (per il link condizionato in UI)."""
    from core.acl_v2 import evaluate_permission_code_access
    from core.legacy_utils import get_legacy_user

    try:
        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        res = evaluate_permission_code_access(
            permission_code=PERM_ADMIN,
            django_user=getattr(request, "user", None),
            legacy_user=legacy_user,
        )
        return bool(res.get("allowed"))
    except Exception:  # noqa: BLE001
        return False


_AREE_PLACEHOLDER = [
    {"titolo": "Timbri per capocommessa", "icon": "user",
     "desc": "Timbro ricevuto + firma da sovrapporre al MOD.133 (arriva col MOD.133 reale)."},
]


@login_required
def admin_home(request):
    """Landing della sezione Amministrazione: card per ogni area gestibile."""
    cfg = AutoApprovazioneConfig.get_config()
    ncfg = NotificaConfig.get_config()
    return render(request, "gestione_specifiche/admin/home.html", {
        "n_mappature": ClienteCartellaShare.objects.count(),
        "auto_attiva": cfg.attiva,
        "reparto_in1": ncfg.reparto_in1,
        "aree_placeholder": _AREE_PLACEHOLDER,
    })


@login_required
def admin_notifiche(request):
    """#5 — Config notifiche/assegnazione: reparto IN1 + nomi aggiuntivi + email on/off."""
    from django.contrib.auth import get_user_model

    cfg = NotificaConfig.get_config()
    if request.method == "POST":
        cfg.reparto_in1 = ((request.POST.get("reparto_in1") or "").strip()[:100]) or "IN1"
        cfg.email_attiva = request.POST.get("email_attiva") == "1"
        cfg.save()
        ids = [int(x) for x in request.POST.getlist("utenti_aggiuntivi") if x.isdigit()]
        cfg.utenti_aggiuntivi.set(ids)
        messages.success(request, "Configurazione notifiche salvata.")
        return redirect("gestione_specifiche:admin_notifiche")

    User = get_user_model()
    utenti = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
    selezionati = set(cfg.utenti_aggiuntivi.values_list("pk", flat=True))
    return render(request, "gestione_specifiche/admin/notifiche.html",
                  {"cfg": cfg, "utenti": utenti, "selezionati": selezionati})


@login_required
def admin_cartelle(request):
    """Gestione mappatura Cliente → cartella share: lista + aggiungi (POST)."""
    if request.method == "POST":
        cliente = (request.POST.get("cliente") or "").strip()
        cartella = (request.POST.get("cartella") or "").strip()
        if not cliente or not cartella:
            messages.error(request, "Cliente e cartella sono obbligatori.")
        else:
            ClienteCartellaShare.objects.update_or_create(
                cliente=cliente, defaults={"cartella": cartella, "attivo": True, "note": "admin"})
            messages.success(request, f"Mappatura salvata: {cliente} → {cartella}.")
        return redirect("gestione_specifiche:admin_cartelle")

    return render(request, "gestione_specifiche/admin/cartelle.html", {
        "mappature": ClienteCartellaShare.objects.all(),
        "cartelle": cartelle_disponibili(),
    })


@login_required
@require_POST
def admin_cartella_edit(request, pk: int):
    """Modifica cartella / attiva-disattiva una mappatura."""
    m = get_object_or_404(ClienteCartellaShare, pk=pk)
    cartella = (request.POST.get("cartella") or "").strip()
    if cartella:
        m.cartella = cartella
    m.attivo = request.POST.get("attivo") == "1"
    m.save(update_fields=["cartella", "attivo", "updated_at"])
    messages.success(request, f"Mappatura aggiornata: {m.cliente}.")
    return redirect("gestione_specifiche:admin_cartelle")


@login_required
@require_POST
def admin_cartella_delete(request, pk: int):
    """Elimina una mappatura cliente→cartella."""
    m = get_object_or_404(ClienteCartellaShare, pk=pk)
    cliente = m.cliente
    m.delete()
    messages.success(request, f"Mappatura eliminata: {cliente}.")
    return redirect("gestione_specifiche:admin_cartelle")


@login_required
def admin_auto_approva(request):
    """#3 — Config auto-approvazione MOD.133: attiva + approvatore MSO."""
    from django.contrib.auth import get_user_model

    cfg = AutoApprovazioneConfig.get_config()
    if request.method == "POST":
        cfg.attiva = request.POST.get("attiva") == "1"
        appr = (request.POST.get("approvatore") or "").strip()
        cfg.approvatore_id = int(appr) if appr.isdigit() else None
        cfg.nota = (request.POST.get("nota") or "").strip()[:300]
        if cfg.attiva and not cfg.approvatore_id:
            messages.error(request, "Per attivare l'auto-approvazione serve un approvatore di riferimento (MSO).")
            cfg.attiva = False
        cfg.save()
        messages.success(request, "Configurazione auto-approvazione salvata.")
        return redirect("gestione_specifiche:admin_auto_approva")

    User = get_user_model()
    utenti = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
    return render(request, "gestione_specifiche/admin/auto_approva.html", {"cfg": cfg, "utenti": utenti})
