"""Rack di rete (``/assets/rete/rack/``): armadi, switch che contengono e dispositivi collegati.

Lettura con il binding ACL v2 di ``/assets/rete/`` (lo stesso di «Indirizzi IP»). Creare,
modificare o eliminare un rack richiede il permesso di modificare gli asset (come
collegare un indirizzo): il server ricontrolla nel POST. Lo switch si mette nel rack
dalla sua scheda (``views_asset_rete.asset_rete_prefisso``), qui si vede il risultato.
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.audit import log_action

from .models import RackRete
from .services import rete_switch
from .views_rete import _puo_collegare

GUIDA_ANCORA = "#rete-rack"


class RackForm(forms.ModelForm):
    class Meta:
        model = RackRete
        fields = ["codice", "nome", "ubicazione", "prefisso_porte", "prefisso_patch", "note"]
        labels = {
            "codice": "Codice",
            "nome": "Nome",
            "ubicazione": "Ubicazione",
            "prefisso_porte": "Prefisso porte switch",
            "prefisso_patch": "Prefisso patch panel",
            "note": "Note",
        }
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["codice"].widget.attrs["placeholder"] = "Es. R0"
        self.fields["nome"].widget.attrs["placeholder"] = "Es. Armadio CED"
        self.fields["ubicazione"].widget.attrs["placeholder"] = "Es. CED piano terra"
        self.fields["prefisso_porte"].widget.attrs["placeholder"] = "Es. A0"
        self.fields["prefisso_patch"].widget.attrs["placeholder"] = "Es. Q0"

    def clean_codice(self):
        return (self.cleaned_data.get("codice") or "").strip().upper()

    def _prefisso(self, campo: str) -> str:
        grezzo = (self.cleaned_data.get(campo) or "").strip()
        valore = rete_switch.prefisso_valido(grezzo)
        if grezzo and not valore:
            raise forms.ValidationError("Solo lettere e cifre, es. A0.")
        altri = RackRete.objects.filter(**{campo: valore}).exclude(pk=self.instance.pk) if valore else None
        if altri is not None and (altro := altri.first()):
            raise forms.ValidationError(f"Già usato dal rack {altro.codice}.")
        return valore

    def clean_prefisso_porte(self):
        return self._prefisso("prefisso_porte")

    def clean_prefisso_patch(self):
        return self._prefisso("prefisso_patch")


def _shell(request: HttpRequest) -> dict:
    from .views import _assets_shell_context

    return _assets_shell_context(request, search_placeholder="Cerca asset, seriali o utenti")


def _salva(request: HttpRequest) -> tuple[bool, RackForm | None]:
    """POST di creazione, modifica o eliminazione. ``(fatto, form con errori)``."""
    azione = request.POST.get("azione") or ""
    rack_id = request.POST.get("rack") or ""
    rack = RackRete.objects.filter(pk=int(rack_id)).first() if rack_id.isdigit() else None
    if azione == "elimina":
        if rack is None:
            messages.error(request, "Rack non trovato: ricarica la pagina.")
            return True, None
        switch = rack.switch.count()
        log_action(request, "rete_rack_eliminato", "assets", {"codice": rack.codice, "switch": switch})
        rack.delete()
        messages.success(request, f"Rack {rack.codice} eliminato." + (f" I suoi {switch} switch restano senza rack." if switch else ""))
        return True, None
    form = RackForm(request.POST, instance=rack)
    if not form.is_valid():
        return False, form
    nuovo = rack is None
    rack = form.save()
    log_action(request, "rete_rack_creato" if nuovo else "rete_rack_modificato", "assets",
               {"codice": rack.codice, "prefisso_porte": rack.prefisso_porte, "prefisso_patch": rack.prefisso_patch})
    messages.success(request, f"Rack {rack.codice} {'creato' if nuovo else 'salvato'}.")
    return True, None


@login_required
def rete_rack(request: HttpRequest) -> HttpResponse:
    puo_modificare = _puo_collegare(request)
    form_errori = None
    if request.method == "POST":
        if not puo_modificare:
            messages.error(request, "Per gestire i rack serve il permesso di modificare gli asset.")
            return redirect("assets:rete_rack")
        fatto, form_errori = _salva(request)
        if fatto:
            destinazione = request.POST.get("torna") or ""
            if destinazione.isdigit() and RackRete.objects.filter(pk=int(destinazione)).exists():
                return redirect("assets:rete_rack_detail", id=int(destinazione))
            return redirect("assets:rete_rack")
        messages.error(request, "Rack non salvato: correggi i campi segnalati.")
    data = rete_switch.panoramica_rack()
    return render(request, "assets/pages/rete_rack.html", {
        **_shell(request),
        "page_title": "Rack e switch",
        **data,
        "puo_modificare": puo_modificare,
        "form": form_errori or RackForm(),
        "form_aperto": form_errori is not None,
        "guida_url": reverse("assets:guida") + GUIDA_ANCORA,
    })


@login_required
def rete_rack_detail(request: HttpRequest, id: int) -> HttpResponse:
    rack = get_object_or_404(RackRete, pk=id)
    puo_modificare = _puo_collegare(request)
    data = rete_switch.dettaglio_rack(rack)
    return render(request, "assets/pages/rete_rack_detail.html", {
        **_shell(request),
        "page_title": f"Rack {rack.codice}",
        "rack": rack,
        **data,
        "puo_modificare": puo_modificare,
        "form": RackForm(instance=rack),
        "guida_url": reverse("assets:guida") + GUIDA_ANCORA,
    })
