"""Analisi del rischio del MOD.165 (registro delle minacce, monitoraggio dei controlli, piano OT). Viste fail-closed."""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_SOA_EDIT, PERM_SOA_VIEW
from .models import ControlloIso27002, RischioMinaccia, ScenarioRischioOT, SoaRevisione
from .services.rischio import analizza, fascia
from .views import MODULE, _has_perm, _nega

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class _ControlliField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.codice} {obj.titolo}"


class RischioMinacciaForm(forms.ModelForm):
    controlli = _ControlliField(queryset=ControlloIso27002.objects.all(), required=False,
                                widget=forms.SelectMultiple(attrs={"size": 12}),
                                label="Controlli che mitigano la minaccia",
                                help_text="Ctrl (⌘ su Mac) + clic per sceglierne più di uno.")

    class Meta:
        model = RischioMinaccia
        fields = ["gruppo", "agente", "minaccia", "rischio_inerente", "controlli", "note", "ordine"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}
        help_texts = {"rischio_inerente": "Probabilità × impatto sugli asset, come nel MOD.165 (fino a 64)."}

    def clean_rischio_inerente(self):
        valore = self.cleaned_data.get("rischio_inerente")
        if valore is not None and valore > 64:
            raise forms.ValidationError("Il rischio inerente del MOD.165 va da 0 a 64.")
        return valore


class ScenarioOTForm(forms.ModelForm):
    controlli = _ControlliField(queryset=ControlloIso27002.objects.all(), required=False,
                                widget=forms.SelectMultiple(attrs={"size": 10}), label="Controlli ISO/IEC 27002",
                                help_text="Ctrl (⌘ su Mac) + clic per sceglierne più di uno.")

    class Meta:
        model = ScenarioRischioOT
        fields = ["codice", "scenario", "minacce", "controlli", "misure", "rischio_inerente", "vulnerabilita_attesa",
                  "azioni", "opzione", "responsabile", "scadenza", "stato", "riferimenti"]
        widgets = {"scenario": forms.Textarea(attrs={"rows": 2}), "minacce": forms.Textarea(attrs={"rows": 2}),
                   "misure": forms.Textarea(attrs={"rows": 3}), "azioni": forms.Textarea(attrs={"rows": 3}),
                   "riferimenti": forms.Textarea(attrs={"rows": 2}), "scadenza": _DATE}


class SogliaForm(forms.ModelForm):
    class Meta:
        model = SoaRevisione
        fields = ["soglia_rischio"]

    def clean_soglia_rischio(self):
        valore = self.cleaned_data["soglia_rischio"]
        if valore > 64:
            raise forms.ValidationError("La soglia va da 0 a 64.")
        return valore


def _url(revisione: SoaRevisione, anchor: str = "") -> str:
    url = reverse("sistema_gestione:soa_rischi", kwargs={"numero": revisione.numero})
    return f"{url}#{anchor}" if anchor else url


@login_required
def soa_rischi(request, numero: int):
    if not _has_perm(request, PERM_SOA_VIEW):
        return _nega(request)
    revisione = get_object_or_404(SoaRevisione, numero=numero)
    analisi = analizza(revisione)
    if request.GET.get("formato") == "xlsx":
        return _excel(request, analisi)
    filtro = request.GET.get("filtro", "")
    minacce = analisi.non_accettabili if filtro == "oltre" else analisi.minacce
    for r in analisi.minacce:
        r.fascia = fascia(r.residuo)
    for r in analisi.controlli:
        r.fascia, r.fascia_futuro = fascia(r.residuo), fascia(r.futuro)
    for r in analisi.scenari:
        r.fascia, r.fascia_atteso = fascia(r.residuo), fascia(r.atteso)
    puo_modificare = _has_perm(request, PERM_SOA_EDIT) and revisione.modificabile
    return render(request, "sistema_gestione/pages/soa_rischi.html", {
        "page_title": f"Analisi del rischio - SoA Rev.{revisione.numero}",
        "revisione": revisione, "analisi": analisi, "minacce": minacce, "filtro": filtro,
        "controlli_collegati": [r for r in analisi.controlli if r.minacce],
        "revisioni": SoaRevisione.objects.order_by("-numero"),
        "puo_modificare": puo_modificare,
        "form_soglia": SogliaForm(instance=revisione) if puo_modificare else None,
    })


def _excel(request, analisi):
    from core.excel_export import build_xlsx_bytes

    rev = analisi.revisione
    righe = [[r.minaccia.gruppo, r.minaccia.agente, r.minaccia.minaccia, r.minaccia.rischio_inerente,
              ", ".join(c.codice for c in r.controlli), r.vulnerabilita, r.residuo,
              "Sì" if r.accettabile else "No", ", ".join(c.codice for c in r.critici)] for r in analisi.minacce]
    corpo = build_xlsx_bytes(
        columns=["Gruppo", "Agente", "Minaccia", "Rischio inerente", "Controlli", "Vulnerabilità max",
                 "Rischio residuo", "Accettabile", "Controlli che determinano la vulnerabilità"],
        rows=righe, sheet_title="Rischio per minaccia",
        title=f"Analisi del rischio - MOD.165 Rev.{rev.numero}",
        subtitle=f"Soglia di accettabilità {analisi.soglia} · residuo = inerente × vulnerabilità / 4",
    )
    log_action(request, "soa_rischi_download", MODULE, {"revisione": rev.numero}, oggetto=rev)
    response = HttpResponse(corpo, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="Rischi_MOD165_Rev{rev.numero}.xlsx"'
    return response


def _revisione_modificabile(request, numero: int):
    revisione = get_object_or_404(SoaRevisione, numero=numero)
    if not revisione.modificabile:
        messages.error(request, "La revisione non è in bozza: apri una nuova revisione della SoA per modificare l'analisi.")
        return revisione, False
    return revisione, True


@login_required
def soa_rischio_minaccia(request, numero: int, pk: int | None = None):
    if not _has_perm(request, PERM_SOA_EDIT):
        return _nega(request)
    revisione, ok = _revisione_modificabile(request, numero)
    if not ok:
        return redirect(_url(revisione, "minacce"))
    minaccia = get_object_or_404(RischioMinaccia, pk=pk, revisione=revisione) if pk else RischioMinaccia(revisione=revisione)
    if request.method == "POST" and request.POST.get("azione") == "rimuovi" and pk:
        log_action(request, "soa_rischio_minaccia_rimossa", MODULE, {"minaccia": minaccia.minaccia}, oggetto=revisione)
        minaccia.delete()
        messages.success(request, "Minaccia rimossa dall'analisi.")
        return redirect(_url(revisione, "minacce"))
    form = RischioMinacciaForm(request.POST or None, instance=minaccia)
    if request.method == "POST" and form.is_valid():
        minaccia = form.save(commit=False)
        minaccia.aggiornata_da = request.user
        minaccia.save()
        form.save_m2m()
        log_action(request, "soa_rischio_minaccia_salvata", MODULE,
                   {"minaccia": minaccia.minaccia, "campi": sorted(form.changed_data)}, oggetto=revisione)
        messages.success(request, "Minaccia salvata: il rischio residuo è ricalcolato.")
        return redirect(_url(revisione, f"m-{minaccia.pk}"))
    return render(request, "sistema_gestione/pages/soa_rischio_form.html", {
        "page_title": "Minaccia" if pk else "Nuova minaccia", "revisione": revisione, "form": form,
        "puo_rimuovere": bool(pk), "indietro": _url(revisione, "minacce"),
    })


@login_required
def soa_rischio_ot(request, numero: int, pk: int | None = None):
    if not _has_perm(request, PERM_SOA_EDIT):
        return _nega(request)
    revisione, ok = _revisione_modificabile(request, numero)
    if not ok:
        return redirect(_url(revisione, "ot"))
    scenario = get_object_or_404(ScenarioRischioOT, pk=pk, revisione=revisione) if pk else ScenarioRischioOT(revisione=revisione)
    if request.method == "POST" and request.POST.get("azione") == "rimuovi" and pk:
        log_action(request, "soa_rischio_ot_rimosso", MODULE, {"codice": scenario.codice}, oggetto=revisione)
        scenario.delete()
        messages.success(request, "Scenario OT rimosso.")
        return redirect(_url(revisione, "ot"))
    form = ScenarioOTForm(request.POST or None, instance=scenario)
    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.aggiornato_da = request.user
        scenario.save()
        form.save_m2m()
        log_action(request, "soa_rischio_ot_salvato", MODULE,
                   {"codice": scenario.codice, "campi": sorted(form.changed_data)}, oggetto=revisione)
        messages.success(request, f"Scenario {scenario.codice} salvato.")
        return redirect(_url(revisione, f"ot-{scenario.pk}"))
    return render(request, "sistema_gestione/pages/soa_rischio_form.html", {
        "page_title": f"Scenario OT {scenario.codice}" if pk else "Nuovo scenario OT", "revisione": revisione,
        "form": form, "puo_rimuovere": bool(pk), "indietro": _url(revisione, "ot"),
    })


@login_required
@require_POST
def soa_rischio_soglia(request, numero: int):
    if not _has_perm(request, PERM_SOA_EDIT):
        return _nega(request)
    revisione, ok = _revisione_modificabile(request, numero)
    if ok:
        precedente = revisione.soglia_rischio
        form = SogliaForm(request.POST, instance=revisione)
        if form.is_valid():
            form.save()
            log_action(request, "soa_rischio_soglia", MODULE, {"da": precedente, "a": revisione.soglia_rischio}, oggetto=revisione)
            messages.success(request, "Soglia di accettabilità aggiornata.")
        else:
            messages.error(request, " ".join(sum(form.errors.values(), [])))
    return redirect(_url(revisione))
