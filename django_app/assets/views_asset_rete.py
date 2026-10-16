"""Interfacce di rete dalla scheda «Tecnica e rete» e mappa porte dello switch.

Le route stanno sotto ``/assets/edit/<id>/rete/``: ricadono nel binding ACL v2 di
``assets_edit`` (prefisso), quindi chi modifica l'asset modifica anche la sua rete.
Ogni salvataggio passa da ``storico_asset.traccia`` ("Cosa è cambiato nella rete").
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.forms import modelformset_factory
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .models import Asset, AssetEndpoint, AssetFieldHistory
from .services import rete_switch, storico_asset
from .services.mac import normalizza_mac


class InterfacciaReteForm(forms.ModelForm):
    class Meta:
        model = AssetEndpoint
        fields = ["endpoint_name", "ip", "mac", "vlan", "switch_name", "switch_port", "punto"]
        labels = {
            "endpoint_name": "Nome interfaccia",
            "ip": "IP",
            "mac": "MAC",
            "vlan": "VLAN",
            "switch_name": "Switch",
            "switch_port": "Porta SW",
            "punto": "Porta patch panel",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mac"].max_length = 32
        self.fields["mac"].widget.attrs.update({"maxlength": 32, "placeholder": "aa:bb:cc:dd:ee:ff"})
        self.fields["switch_name"].widget.attrs.update({"list": "asset-rete-switch-list", "placeholder": "Matricola dello switch"})
        self.fields["switch_port"].widget.attrs["placeholder"] = "Es. A0.1.37"
        self.fields["punto"].widget.attrs["placeholder"] = "Es. Q0.89"
        self.fields["vlan"].widget.attrs["min"] = 0

    def clean_mac(self):
        valore = (self.cleaned_data.get("mac") or "").strip()
        if not valore:
            return ""
        mac = normalizza_mac(valore)
        if not mac:
            raise forms.ValidationError("MAC non valido: usa 12 cifre esadecimali (es. aa:bb:cc:dd:ee:ff).")
        return mac

    def clean_ip(self):
        return (self.cleaned_data.get("ip") or "").strip() or None

    def clean(self):
        cleaned = super().clean()
        for campo in ("endpoint_name", "switch_name", "switch_port", "punto"):
            if campo in cleaned:
                cleaned[campo] = (cleaned.get(campo) or "").strip()
        return cleaned


# Una riga vuota in fondo per aggiungere un'interfaccia: se resta vuota non si salva.
InterfacceFormSet = modelformset_factory(
    AssetEndpoint, form=InterfacciaReteForm, extra=1, can_delete=True,
)


def _can_edit(request: HttpRequest, asset: Asset) -> bool:
    from .views import _can_edit_asset

    return _can_edit_asset(request, asset.id)


def rete_context(request: HttpRequest, asset: Asset, *, can_edit: bool | None = None) -> dict:
    """Contesto del blocco «Interfacce e collegamenti di rete» (scheda e risposta HTMX)."""
    endpoints = list(asset.endpoints.all())
    switch_per_nome = rete_switch.risolvi_switch(endpoints)
    righe = [
        {"endpoint": ep, "switch": switch_per_nome.get((ep.switch_name or "").strip().casefold())}
        for ep in endpoints
    ]
    return {
        "asset": asset,
        "rete_righe": righe,
        "rete_can_edit": _can_edit(request, asset) if can_edit is None else can_edit,
    }


def switch_context(request: HttpRequest, asset: Asset, *, can_edit: bool | None = None) -> dict | None:
    """Mappa porte, solo per apparati di rete o asset a cui qualcosa e' gia' collegato."""
    mappa = rete_switch.mappa_switch(asset)
    if not mappa["totale"] and not rete_switch.is_switch(asset):
        return None
    mappa["can_edit"] = _can_edit(request, asset) if can_edit is None else can_edit
    return mappa


def _render_blocco(request: HttpRequest, asset: Asset) -> HttpResponse:
    return render(request, "assets/partials/rete_interfacce.html", rete_context(request, asset))


@login_required
@require_http_methods(["GET", "POST"])
def asset_rete_edit(request: HttpRequest, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset, pk=id)
    if not _can_edit(request, asset):
        return HttpResponseForbidden("Non hai il permesso di modificare questo asset.")
    queryset = asset.endpoints.order_by("id")
    if request.GET.get("annulla") == "1":
        return _render_blocco(request, asset)
    if request.method == "POST":
        formset = InterfacceFormSet(request.POST, queryset=queryset, prefix="rete")
        if formset.is_valid():
            with storico_asset.traccia([asset.id], fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Modifica rete dalla scheda"):
                for form in formset.deleted_forms:
                    if form.instance.pk:
                        form.instance.delete()
                for form in formset.forms:
                    if form in formset.deleted_forms or not form.has_changed():
                        continue
                    endpoint = form.save(commit=False)
                    endpoint.asset = asset
                    if not endpoint.pk and not endpoint.endpoint_name:
                        endpoint.endpoint_name = (
                            "Collegamento principale" if not asset.endpoints.exists()
                            else f"Interfaccia {asset.endpoints.count() + 1}"
                        )
                    endpoint.save()
            if not request.headers.get("HX-Request"):
                messages.success(request, "Interfacce di rete aggiornate.")
                return redirect("assets:asset_view", id=asset.id)
            return _render_blocco(request, asset)
    else:
        formset = InterfacceFormSet(queryset=queryset, prefix="rete")
    return render(request, "assets/partials/rete_interfacce_form.html", {
        "asset": asset,
        "formset": formset,
        "switch_disponibili": rete_switch.switch_disponibili(),
    })


@login_required
@require_POST
def asset_rete_collega_porte(request: HttpRequest, id: int) -> HttpResponse:
    """Collega a questo switch le porte censite con un prefisso e senza switch indicato."""
    asset = get_object_or_404(Asset, pk=id)
    if not _can_edit(request, asset):
        return HttpResponseForbidden("Non hai il permesso di modificare questo asset.")
    prefisso = rete_switch.prefisso_valido(request.POST.get("prefisso"))
    if not prefisso:
        messages.error(request, "Indica il prefisso delle porte (es. A0).")
        return redirect("assets:asset_view", id=asset.id)
    endpoints = rete_switch.endpoint_con_prefisso(prefisso)
    if endpoints:
        with storico_asset.traccia({ep.asset_id for ep in endpoints}, fonte=AssetFieldHistory.FONTE_FORM,
                                   utente=request.user, dettaglio=f"Porte {prefisso}.* collegate a {asset.asset_tag}"):
            for ep in endpoints:
                ep.switch_name = asset.asset_tag
                ep.save(update_fields=["switch_name"])
        messages.success(request, f"{len(endpoints)} porte con prefisso {prefisso} collegate a {asset.asset_tag}.")
    else:
        messages.info(request, f"Nessuna porta senza switch con prefisso {prefisso}.")
    return redirect("assets:asset_view", id=asset.id)
