"""Impostazioni › Viste elenco dipendenti (prompt 03): viste configurabili da admin, senza codice."""
from __future__ import annotations

import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models_elenco import VistaElenco
from .services import colonne_elenco
from .services import viste_elenco as viste_svc


def _admin(request) -> bool:
    from .views import _is_anagrafica_admin

    return _is_anagrafica_admin(request)


def _nega(request):
    messages.error(request, "Le viste dell'elenco si gestiscono dall'amministrazione anagrafica.")
    return redirect("anagrafica:dipendenti_list")


def _ruoli():
    try:
        from core.legacy_models import Ruolo

        return [(r.id, r.nome) for r in Ruolo.objects.order_by("nome")]
    except Exception:  # noqa: BLE001 - senza tabella ruoli si usano solo viste globali
        return []


class VistaElencoForm(forms.ModelForm):
    colonne_json = forms.CharField(widget=forms.HiddenInput, required=False)
    ruolo_legacy_id = forms.TypedChoiceField(label="Ruolo", required=False, coerce=int, empty_value=None)
    filtro_reparto = forms.CharField(label="Filtro reparto all'apertura", required=False, max_length=100)

    class Meta:
        model = VistaElenco
        fields = ["nome", "descrizione", "ambito", "ruolo_legacy_id", "predefinita", "blocca_personalizzazione", "ordinamento", "ordine", "attiva"]

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields["ruolo_legacy_id"].choices = [("", "—")] + _ruoli()
        chiavi = [("", "Nominativo")] + [(c.chiave, c.etichetta) for c in colonne_elenco.colonne_disponibili(request)]
        self.fields["ordinamento"] = forms.ChoiceField(label="Ordina all'apertura per", choices=chiavi, required=False)
        self.fields["filtro_reparto"].initial = (self.instance.filtri or {}).get("reparto", "")
        self.fields["colonne_json"].initial = json.dumps(self.instance.colonne or viste_svc.specifica(colonne_elenco.DEFAULT_COLONNE))

    def clean(self):
        dati = super().clean()
        if dati.get("ambito") == VistaElenco.AMBITO_RUOLO and not dati.get("ruolo_legacy_id"):
            self.add_error("ruolo_legacy_id", "Scegli il ruolo per cui vale la vista.")
        try:
            voci = json.loads(dati.get("colonne_json") or "[]")
        except ValueError:
            raise forms.ValidationError("Colonne non valide: ricarica la pagina.")
        permessi = colonne_elenco.permessi_utente(self.request)
        visibili_admin = {c.chiave for c in colonne_elenco.REGISTRO.values() if colonne_elenco.colonna_permessa(c, permessi)}
        pulite, viste_chiavi = [], set()
        for voce in voci if isinstance(voci, list) else []:
            chiave = str((voce or {}).get("chiave") or "")
            if chiave not in visibili_admin or chiave in viste_chiavi:
                continue  # solo chiavi del registro che l'admin può vedere, una volta sola
            viste_chiavi.add(chiave)
            try:
                larghezza = max(0, min(int(voce.get("larghezza") or 0), 600))
            except (TypeError, ValueError):
                larghezza = 0
            pulite.append({"chiave": chiave, "visibile": bool(voce.get("visibile", True)), "larghezza": larghezza})
        # Colonne della vista che questo admin non può vedere: restano (in coda), non si perdono.
        for voce in self.instance.colonne or []:
            if isinstance(voce, dict) and voce.get("chiave") in colonne_elenco.REGISTRO and voce["chiave"] not in visibili_admin:
                pulite.append(voce)
        if not any(v["visibile"] for v in pulite):
            raise forms.ValidationError("Lascia visibile almeno una colonna oltre al nominativo.")
        dati["colonne_pulite"] = pulite
        return dati

    def save(self, commit=True):
        vista = super().save(commit=False)
        vista.colonne = self.cleaned_data["colonne_pulite"]
        vista.filtri = {**(vista.filtri or {}), "reparto": self.cleaned_data.get("filtro_reparto", "").strip()}
        if not vista.codice:
            base = slugify(vista.nome)[:50] or "vista"
            codice, n = base, 2
            while VistaElenco.objects.filter(codice=codice).exists():
                codice, n = f"{base}-{n}", n + 1
            vista.codice = codice
        if commit:
            with transaction.atomic():
                vista.save()
                if vista.predefinita:
                    altre = VistaElenco.objects.filter(predefinita=True, ambito=vista.ambito).exclude(pk=vista.pk)
                    if vista.ambito == VistaElenco.AMBITO_RUOLO:
                        altre = altre.filter(ruolo_legacy_id=vista.ruolo_legacy_id)
                    altre.update(predefinita=False)
        return vista


@login_required
def viste_elenco(request):
    if not _admin(request):
        return _nega(request)
    viste = list(VistaElenco.objects.all())
    for v in viste:
        v.n_colonne = len(v.chiavi)
        v.n_sensibili = sum(1 for k in v.chiavi if k in colonne_elenco.REGISTRO and colonne_elenco.REGISTRO[k].sensibile)
    return render(request, "anagrafica/pages/viste_elenco.html", {"viste": viste, "ruoli": dict(_ruoli())})


@login_required
def vista_elenco_modifica(request, pk: int | None = None):
    if not _admin(request):
        return _nega(request)
    vista = get_object_or_404(VistaElenco, pk=pk) if pk else VistaElenco()
    form = VistaElencoForm(request.POST or None, instance=vista, request=request)
    if request.method == "POST" and form.is_valid():
        vista = form.save()
        log_action(request, "vista_elenco_salvata", "anagrafica", {"vista": vista.codice, "colonne": vista.chiavi}, oggetto=vista)
        messages.success(request, f"Vista «{vista.nome}» salvata.")
        return redirect("anagrafica:viste_elenco")
    disponibili = colonne_elenco.colonne_disponibili(request)
    attuali = {v["chiave"]: v for v in json.loads(form["colonne_json"].value() or "[]")} if form["colonne_json"].value() else {}
    ordinate = [c for c in disponibili if c.chiave in attuali]
    ordinate.sort(key=lambda c: list(attuali).index(c.chiave))
    ordinate += [c for c in disponibili if c.chiave not in attuali]
    righe = [{"colonna": c, "visibile": attuali.get(c.chiave, {}).get("visibile", False) if c.chiave in attuali else False,
              "larghezza": attuali.get(c.chiave, {}).get("larghezza", 0)} for c in ordinate]
    return render(request, "anagrafica/pages/vista_elenco_form.html", {"form": form, "vista": vista, "righe": righe})


@login_required
@require_POST
def vista_elenco_azione(request, pk: int):
    if not _admin(request):
        return _nega(request)
    vista = get_object_or_404(VistaElenco, pk=pk)
    azione = request.POST.get("azione")
    if azione == "duplica":
        copia = VistaElenco(nome=f"{vista.nome} (copia)"[:120], descrizione=vista.descrizione, colonne=vista.colonne,
                            ordinamento=vista.ordinamento, filtri=vista.filtri, ordine=vista.ordine + 1)
        base = slugify(copia.nome)[:50] or "vista"
        codice, n = base, 2
        while VistaElenco.objects.filter(codice=codice).exists():
            codice, n = f"{base}-{n}", n + 1
        copia.codice = codice
        copia.save()
        log_action(request, "vista_elenco_duplicata", "anagrafica", {"da": vista.codice, "a": copia.codice}, oggetto=copia)
        messages.success(request, f"Creata la copia «{copia.nome}».")
        return redirect("anagrafica:vista_elenco_modifica", pk=copia.pk)
    if azione == "ripristina":
        if vista.codice not in viste_svc.PRESET:
            messages.error(request, "Solo le viste di sistema hanno un'impostazione di partenza.")
        else:
            _nome, _descr, chiavi = viste_svc.PRESET[vista.codice]
            vista.colonne = viste_svc.specifica(chiavi)
            vista.ordinamento, vista.filtri, vista.blocca_personalizzazione = "", {}, False
            vista.save()
            log_action(request, "vista_elenco_ripristinata", "anagrafica", {"vista": vista.codice}, oggetto=vista)
            messages.success(request, f"Vista «{vista.nome}» riportata alle colonne di partenza.")
        return redirect("anagrafica:vista_elenco_modifica", pk=vista.pk)
    if azione == "elimina":
        if request.POST.get("conferma") != vista.codice:
            messages.error(request, "Per eliminare scrivi il codice della vista nel campo di conferma.")
            return redirect("anagrafica:vista_elenco_modifica", pk=vista.pk)
        log_action(request, "vista_elenco_eliminata", "anagrafica", {"vista": vista.codice, "colonne": vista.chiavi})
        vista.delete()
        messages.success(request, "Vista eliminata: chi la usava torna alla vista predefinita.")
        return redirect("anagrafica:viste_elenco")
    messages.error(request, "Azione non riconosciuta.")
    return redirect("anagrafica:viste_elenco")


@login_required
def vista_elenco_anteprima(request):
    """Anteprima live (HTMX/fetch): prime righe vere con le colonne scelte, filtrate dai permessi dell'admin."""
    if not _admin(request):
        return HttpResponse(status=403)
    try:
        voci = json.loads(request.POST.get("colonne_json") or request.GET.get("colonne_json") or "[]")
    except ValueError:
        voci = []
    colonne = colonne_elenco.colonne_da_specifica(voci, request)
    from .views import build_dipendenti_rows

    righe = build_dipendenti_rows(request, apply_filters=False)[:8]
    colonne_elenco.arricchisci(righe, [c["colonna"] for c in colonne])
    return render(request, "anagrafica/partials/_vista_elenco_anteprima.html", {"righe": righe, "colonne": colonne})
