"""Form del verbale di riesame (MOD.062)."""
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from .models import Processo, Riesame, RiesameObiettivo, RiesamePartecipante

_DATA = {"type": "date"}


def _utenti():
    return get_user_model().objects.filter(is_active=True).order_by("last_name", "first_name", "username")


def _etichetta_utente(u) -> str:
    return u.get_full_name() or u.get_username()


class RiesameForm(forms.ModelForm):
    class Meta:
        model = Riesame
        fields = ["anno", "data", "data_intermedio", "data_pianificazione", "periodo_dal", "periodo_al",
                  "documenti_esaminati"]
        widgets = {
            "data": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "data_intermedio": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "data_pianificazione": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "periodo_dal": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "periodo_al": forms.DateInput(attrs=_DATA, format="%Y-%m-%d"),
            "documenti_esaminati": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        dati = super().clean()
        dal, al = dati.get("periodo_dal"), dati.get("periodo_al")
        if dal and al and al < dal:
            self.add_error("periodo_al", "La fine del periodo non può precedere l'inizio.")
        return dati


class PartecipanteForm(forms.ModelForm):
    class Meta:
        model = RiesamePartecipante
        fields = ["funzione", "utente", "nome"]
        labels = {"utente": "Persona", "nome": "Oppure nome (esterni)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["utente"].queryset = _utenti()
        self.fields["utente"].label_from_instance = _etichetta_utente

    def clean(self):
        dati = super().clean()
        if not dati.get("utente") and not (dati.get("nome") or "").strip():
            raise forms.ValidationError("Scegli una persona o scrivi il nome.")
        return dati


class ObiettivoForm(forms.ModelForm):
    class Meta:
        model = RiesameObiettivo
        fields = ["descrizione", "processo", "indicatore", "risultato_atteso", "responsabile", "risorse", "scadenza"]
        widgets = {"descrizione": forms.Textarea(attrs={"rows": 2}), "risorse": forms.Textarea(attrs={"rows": 2}),
                   "scadenza": forms.DateInput(attrs=_DATA, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["processo"].queryset = Processo.objects.filter(attivo=True).order_by("codice")
        self.fields["responsabile"].queryset = _utenti()
        self.fields["responsabile"].label_from_instance = _etichetta_utente


class ObiettivoAndamentoForm(forms.ModelForm):
    """In un verbale approvato si aggiorna solo l'andamento: il testo dell'obiettivo resta quello deciso."""

    class Meta:
        model = RiesameObiettivo
        fields = ["nota"]
        widgets = {"nota": forms.Textarea(attrs={"rows": 3})}
        labels = {"nota": "Andamento"}
