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
from .models import ClienteCartellaShare


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
    {"titolo": "Auto-approvazione MOD.133", "icon": "shield",
     "desc": "Delega di approvazione automatica (registrata a nome MSO)."},
    {"titolo": "Notifiche / assegnazione", "icon": "share",
     "desc": "Incaricato o gruppo IN1 a cui notificare le nuove specifiche."},
]


@login_required
def admin_home(request):
    """Landing della sezione Amministrazione: card per ogni area gestibile."""
    return render(request, "gestione_specifiche/admin/home.html", {
        "n_mappature": ClienteCartellaShare.objects.count(),
        "aree_placeholder": _AREE_PLACEHOLDER,
    })


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
