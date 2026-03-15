from django import forms

from .models import SegnalazionePreposto


class SegnalazioneForm(forms.ModelForm):
    data_segnalazione = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"],
        label="Data segnalazione",
    )

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
