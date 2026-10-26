"""Form di certificazioni e audit esterni."""
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from core.upload_limits import DOCUMENT_MAX_BYTES
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from .models import AuditEsterno, Certificazione
from .services.audit_esterni import CLASSIFICAZIONI

_DATA = {"type": "date"}


class CertificazioneForm(forms.ModelForm):
    class Meta:
        model = Certificazione
        fields = ["norma", "descrizione", "ente", "numero", "campo_applicazione", "emesso_il", "scade_il",
                  "prossima_sorveglianza", "attiva", "note"]
        widgets = {
            "emesso_il": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "scade_il": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "prossima_sorveglianza": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "campo_applicazione": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"attiva": "Certificato in vigore"}

    def clean(self):
        dati = super().clean()
        if dati.get("norma") == "ALTRO" and not (dati.get("descrizione") or "").strip():
            self.add_error("descrizione", "Indica di quale certificazione o qualifica si tratta.")
        emesso, scade = dati.get("emesso_il"), dati.get("scade_il")
        if emesso and scade and scade <= emesso:
            self.add_error("scade_il", "La scadenza deve seguire l'emissione.")
        return dati


class AuditEsternoForm(forms.ModelForm):
    class Meta:
        model = AuditEsterno
        fields = ["tipo", "certificazione", "ente", "data_inizio", "data_fine", "en9100", "iso45001", "iso14001",
                  "iso27001", "pdr125", "altre_norme", "auditor", "ambito", "stato", "esito", "risposta_entro",
                  "sintesi"]
        widgets = {
            "data_inizio": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "data_fine": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "risposta_entro": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "ambito": forms.Textarea(attrs={"rows": 3}),
            "sintesi": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {"certificazione": "Certificato interessato", "stato": "Stato", "esito": "Esito dell'ente"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["certificazione"].queryset = Certificazione.objects.order_by("-attiva", "norma")
        self.fields["certificazione"].required = False
        # La chiusura passa dal pulsante «Chiudi l'audit», che controlla esito, rapporto e NC aperte.
        self.fields["stato"].choices = [c for c in AuditEsterno.STATO_CHOICES if c[0] != AuditEsterno.STATO_CHIUSO]
        if self.instance.pk and self.instance.stato == AuditEsterno.STATO_CHIUSO:
            self.fields["stato"].choices = AuditEsterno.STATO_CHOICES
            self.fields["stato"].disabled = True

    def clean(self):
        dati = super().clean()
        inizio, fine = dati.get("data_inizio"), dati.get("data_fine")
        if inizio and fine and fine < inizio:
            self.add_error("data_fine", "La fine non può precedere l'inizio.")
        if not any(dati.get(c) for c in ("en9100", "iso45001", "iso14001", "iso27001", "pdr125")) \
                and not (dati.get("altre_norme") or "").strip():
            self.add_error("altre_norme", "Indica almeno una norma o un requisito verificato.")
        return dati


class RilievoEsternoForm(forms.Form):
    classificazione = forms.ChoiceField(label="Classificazione", choices=CLASSIFICAZIONI)
    descrizione = forms.CharField(label="Rilievo come scritto dall'ente", widget=forms.Textarea(attrs={"rows": 3}))
    rif_norma = forms.CharField(label="Requisito / paragrafo", max_length=200, required=False)
    processo = forms.CharField(label="Processo / area", max_length=200, required=False)
    data_richiesta = forms.DateField(label="Chiusura richiesta entro", required=False,
                                     widget=forms.DateInput(attrs=_DATA, format="%Y-%m-%d"))
    responsabile = forms.ModelChoiceField(label="Responsabile", queryset=None, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["responsabile"]
        campo.queryset = get_user_model().objects.filter(is_active=True).order_by("last_name", "first_name", "username")
        campo.label_from_instance = lambda u: (u.get_full_name() or u.get_username())


class RapportoEsternoForm(forms.Form):
    file = forms.FileField(label="Rapporto dell'ente (PDF)")

    def clean_file(self):
        caricato = self.cleaned_data["file"]
        try:
            validate_extension_and_mime(caricato, allowed_extensions={".pdf"}, allowed_mimes={"application/pdf"},
                                        max_bytes=DOCUMENT_MAX_BYTES, label="Rapporto", allow_empty=False)
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return caricato
