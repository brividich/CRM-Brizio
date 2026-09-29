from django import forms
from django.utils import timezone
from .models import AuditPreparazione, AzioneCorrettivaAudit, RilevazioneKpi
from .services.procedure import risultato_kpi


class PreparazioneForm(forms.ModelForm):
    class Meta:
        model = AuditPreparazione
        fields = ["audit_precedenti", "car_cliente", "documenti_registrazioni", "obiettivi_carenze"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in fields}


class CarForm(forms.ModelForm):
    versione = forms.IntegerField(widget=forms.HiddenInput)

    class Meta:
        model = AzioneCorrettivaAudit
        fields = ["data_richiesta", "responsabile", "origine_esterna", "approvazione_esterna", "causa", "contenimento", "azione", "analizzata_il", "evidenza_attuazione", "evidenza_efficacia"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in ["causa", "contenimento", "azione", "evidenza_attuazione", "evidenza_efficacia"]}
        widgets.update({f: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for f in ["data_richiesta", "analizzata_il"]})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["versione"].initial = self.instance.versione
        if self.instance.pk:
            self.fields["data_richiesta"].disabled = True

    def clean(self):
        dati = super().clean()
        if dati.get("versione") != self.instance.versione:
            self.add_error(None, "La CAR e stata aggiornata da un altro utente. Ricarica prima di salvare.")
        for campo in ["data_richiesta", "analizzata_il"]:
            if dati.get(campo) and dati[campo] > timezone.localdate():
                self.add_error(campo, "La data non puo essere futura.")
        if dati.get("analizzata_il") and dati.get("data_richiesta") and dati["analizzata_il"] < dati["data_richiesta"]:
            self.add_error("analizzata_il", "La valutazione non puo precedere la richiesta.")
        return dati


    @property
    def sezioni(self):
        return sezioni_form(self, [
            ("1. Richiesta e responsabilita", "data_richiesta responsabile origine_esterna approvazione_esterna"),
            ("2. Cause e azioni", "causa contenimento azione analizzata_il"),
            ("3. Prove di attuazione ed efficacia", "evidenza_attuazione evidenza_efficacia"),
        ])


class ProrogaForm(forms.Form):
    proroga_al = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    motivo = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))


class KpiForm(forms.ModelForm):
    class Meta:
        model = RilevazioneKpi
        exclude = ["autore", "registrata_il"]
        widgets = {f: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for f in ["periodo_da", "periodo_a"]}
        widgets.update({f: forms.Textarea(attrs={"rows": 2}) for f in ["fonte_filtri", "commento", "motivo_non_confrontabilita"]})

    def clean(self):
        dati = super().clean()
        if dati.get("periodo_da") and dati.get("periodo_a") and (dati["periodo_a"] < dati["periodo_da"] or dati["periodo_a"] > timezone.localdate()):
            self.add_error("periodo_a", "Indica un periodo concluso, con fine non precedente all'inizio.")
        if not dati.get("confrontabile") and not dati.get("motivo_non_confrontabilita", "").strip():
            self.add_error("motivo_non_confrontabilita", "Indica cosa cambia e la decorrenza della nuova serie.")
        if all(dati.get(f) is not None for f in ["numeratore", "denominatore", "target", "verso", "formula"]):
            from types import SimpleNamespace
            risultato_kpi(SimpleNamespace(**dati))
        return dati


    @property
    def sezioni(self):
        return sezioni_form(self, [
            ("1. Indicatore e periodo", "processo codice periodo_da periodo_a riferimento_riesame"),
            ("2. Dati e calcolo", "formula numeratore denominatore pezzi_nc pezzi_totali fonte_filtri target verso"),
            ("3. Confronto e decisioni", "valore_precedente confrontabile motivo_non_confrontabilita commento"),
        ])


def sezioni_form(form, gruppi):
    return [{"titolo": titolo, "campi": [form[n] for n in nomi.split()]} for titolo,nomi in gruppi]
