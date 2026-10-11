from django import forms
from django.utils import timezone
from .models import AuditPreparazione, AzioneCorrettivaAudit, RilevazioneKpi
from .services.procedure import risultato_kpi


class PreparazioneForm(forms.ModelForm):
    class Meta:
        model = AuditPreparazione
        fields = ["audit_precedenti", "car_cliente", "documenti_registrazioni", "obiettivi_carenze", "origine_ai"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in fields[:4]}
        # Valorizzato da «Copia nei campi vuoti»: resta la traccia che il testo è partito da una bozza AI.
        widgets["origine_ai"] = forms.HiddenInput

    def clean_origine_ai(self):
        # Una volta partita da una bozza AI la preparazione resta marcata anche se poi riscritta.
        return bool(self.cleaned_data.get("origine_ai") or self.instance.origine_ai)


_PERCHE = [f"perche_{n}" for n in range(1, 6)]
_ISHIKAWA = [f"ishikawa_{k}" for k in AzioneCorrettivaAudit.ISHIKAWA]


class CarForm(forms.ModelForm):
    versione = forms.IntegerField(widget=forms.HiddenInput)

    class Meta:
        model = AzioneCorrettivaAudit
        fields = ["data_richiesta", "responsabile", "origine_esterna", "approvazione_esterna", "analisi_metodo", "causa", "contenimento", "azione", "analizzata_il", "evidenza_attuazione", "evidenza_efficacia"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in ["causa", "contenimento", "azione", "evidenza_attuazione", "evidenza_efficacia"]}
        widgets.update({f: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for f in ["data_richiesta", "analizzata_il"]})
        labels = {"causa": "Causa radice (sintesi o riferimento al documento esterno)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["versione"].initial = self.instance.versione
        if self.instance.pk:
            self.fields["data_richiesta"].disabled = True
        perche = list(self.instance.analisi_perche or []) + [""] * 5
        for n, nome in enumerate(_PERCHE):
            self.fields[nome] = forms.CharField(label=f"Perché {n + 1}", required=False, max_length=500, initial=perche[n])
        for nome in _ISHIKAWA:
            chiave = nome.removeprefix("ishikawa_")
            self.fields[nome] = forms.CharField(
                label=AzioneCorrettivaAudit.ISHIKAWA[chiave], required=False, max_length=1000,
                widget=forms.Textarea(attrs={"rows": 2}), initial=(self.instance.analisi_ishikawa or {}).get(chiave, ""),
            )

    def save(self, commit=True):
        car = super().save(commit=False)
        car.analisi_perche = [self.cleaned_data.get(n, "").strip() for n in _PERCHE]
        if not any(car.analisi_perche):
            car.analisi_perche = []
        car.analisi_ishikawa = {
            n.removeprefix("ishikawa_"): self.cleaned_data.get(n, "").strip()
            for n in _ISHIKAWA if self.cleaned_data.get(n, "").strip()
        }
        if commit:
            car.save()
        return car

    @property
    def campi_analisi_cambiati(self) -> bool:
        return bool(set(self.changed_data) & set(_PERCHE + _ISHIKAWA + ["analisi_metodo"]))

    def clean(self):
        dati = super().clean()
        if dati.get("versione") != self.instance.versione:
            self.add_error(None, "La CAR e stata aggiornata da un altro utente. Ricarica prima di salvare.")
        for campo in ["data_richiesta", "analizzata_il"]:
            if dati.get(campo) and dati[campo] > timezone.localdate():
                self.add_error(campo, "La data non puo essere futura.")
        if dati.get("analizzata_il") and dati.get("data_richiesta") and dati["analizzata_il"] < dati["data_richiesta"]:
            self.add_error("analizzata_il", "La valutazione non puo precedere la richiesta.")
        metodo = dati.get("analisi_metodo")
        if metodo == AzioneCorrettivaAudit.METODO_CINQUE_PERCHE and not any((dati.get(n) or "").strip() for n in _PERCHE):
            self.add_error("perche_1", "Con il metodo 5 perché compila almeno il primo perché.")
        if metodo == AzioneCorrettivaAudit.METODO_ISHIKAWA and not any((dati.get(n) or "").strip() for n in _ISHIKAWA):
            self.add_error("analisi_metodo", "Con Ishikawa compila almeno una categoria 6M.")
        if metodo == AzioneCorrettivaAudit.METODO_ESTERNA and not (dati.get("causa") or "").strip():
            self.add_error("causa", "Indica il documento esterno che contiene l'analisi e la causa radice.")
        return dati


    @property
    def sezioni(self):
        return sezioni_form(self, [
            ("1. Richiesta e responsabilita", "data_richiesta responsabile origine_esterna approvazione_esterna"),
            ("2. Analisi delle cause", "analisi_metodo " + " ".join(_PERCHE) + " " + " ".join(_ISHIKAWA) + " causa"),
            ("3. Contenimento e azione correttiva", "contenimento azione analizzata_il"),
            ("4. Prove di attuazione ed efficacia", "evidenza_attuazione evidenza_efficacia"),
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
