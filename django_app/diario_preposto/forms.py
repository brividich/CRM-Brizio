from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import SegnalazionePreposto

# Margine per l'orologio del PC di chi compila: oltre, la data è nel futuro.
TOLLERANZA_DATA_FUTURA = timedelta(minutes=10)


class SegnalazioneForm(forms.ModelForm):
    MSG_CONFLITTO = (
        "Nel frattempo qualcun altro ha modificato questa segnalazione: le tue modifiche "
        "non sono state salvate. Riapri la segnalazione per vedere la versione attuale."
    )

    data_segnalazione = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"],
        label="Data segnalazione",
    )
    # Versione letta all'apertura della modifica (updated_at): se al salvataggio
    # non coincide più, un altro utente ha salvato nel frattempo.
    versione = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = SegnalazionePreposto
        fields = ["data_segnalazione", "titolo", "descrizione"]
        labels = {
            "titolo": "Titolo",
            "descrizione": "Descrizione della segnalazione",
        }
        widgets = {
            "titolo": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Titolo segnalazione"}
            ),
            "descrizione": forms.Textarea(
                attrs={"class": "form-control", "rows": 7, "placeholder": "Descrizione..."}
            ),
        }

    def clean_data_segnalazione(self):
        value = self.cleaned_data["data_segnalazione"]
        if value and value > timezone.now() + TOLLERANZA_DATA_FUTURA:
            raise forms.ValidationError("La data della segnalazione non può essere nel futuro.")
        return value

    def clean_titolo(self):
        value = (self.cleaned_data.get("titolo") or "").strip()
        if not value:
            raise forms.ValidationError("Il titolo è obbligatorio.")
        return value

    def clean_descrizione(self):
        value = (self.cleaned_data.get("descrizione") or "").strip()
        if not value:
            raise forms.ValidationError("La descrizione è obbligatoria.")
        return value


class EliminaSegnalazioneForm(forms.Form):
    motivo = forms.CharField(min_length=5, max_length=500, strip=True)
