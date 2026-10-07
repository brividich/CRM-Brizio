from django import forms
from django.utils import timezone
from core.upload_mime import validate_extension_and_mime, UploadMimeValidationError
from .models import ChecklistProcesso, AuditVerificaEfficacia
from core.upload_limits import DOCUMENT_MAX_BYTES, DOCUMENT_MAX_MB


class ChecklistProcessoForm(forms.ModelForm):
    versione = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    motivo = forms.CharField(max_length=400, label="Motivo della revisione")

    class Meta:
        model = ChecklistProcesso
        fields = ["codice", "norma", "punti", "domanda", "criterio", "suggerimento", "ordine", "attiva"]
        widgets = {n: forms.Textarea(attrs={"rows": 3}) for n in ["domanda", "criterio", "suggerimento"]}
        labels = {"attiva": "Domanda verificata e utilizzabile nei nuovi piani"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["versione"] = self.instance.revisione if self.instance.pk else 0

    def clean(self):
        dati = super().clean()
        if self.instance.pk and dati.get("versione") != self.instance.revisione:
            raise forms.ValidationError("La domanda e stata modificata altrove. Ricarica la scheda.")
        codice = (dati.get("codice") or "").strip().upper()
        if ChecklistProcesso.objects.filter(processo=self.instance.processo, codice__iexact=codice).exclude(pk=self.instance.pk).exists():
            self.add_error("codice", "Codice gia presente per questo processo.")
        dati["codice"] = codice
        return dati


class AllegatoEvidenzaForm(forms.Form):
    file = forms.FileField(label=f"Evidenza (PDF, PNG o JPEG, massimo {DOCUMENT_MAX_MB} MB)")

    def clean_file(self):
        file = self.cleaned_data["file"]
        try:
            validate_extension_and_mime(file, allowed_extensions={".pdf", ".png", ".jpg", ".jpeg"},
                allowed_mimes={"application/pdf", "image/png", "image/jpeg"}, max_bytes=DOCUMENT_MAX_BYTES,
                allow_empty=False, label="Evidenza")
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return file


class VerificaEfficaciaForm(forms.ModelForm):
    class Meta:
        model = AuditVerificaEfficacia
        fields = ["risultato", "metodo", "evidenza", "data_verifica", "prossima_verifica"]
        widgets = {"metodo": forms.Textarea(attrs={"rows": 3}), "evidenza": forms.Textarea(attrs={"rows": 4}),
                   "data_verifica": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "prossima_verifica": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean(self):
        dati = super().clean()
        data = dati.get("data_verifica")
        prossima = dati.get("prossima_verifica")
        if data and data > timezone.localdate():
            self.add_error("data_verifica", "La verifica non puo essere nel futuro.")
        if dati.get("risultato") != "EFFICACE" and not prossima:
            self.add_error("prossima_verifica", "Pianifica una nuova verifica.")
        if prossima and prossima <= timezone.localdate():
            self.add_error("prossima_verifica", "La prossima verifica deve essere futura.")
        return dati
