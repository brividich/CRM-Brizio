"""Form delle azioni FSM (sessione 3b) del modulo Suggestion Corner.

Un form per transizione che richiede input dall'utente. Le transizioni senza
input (avvia_do, avvia_check, inserisci_act, chiudi) non hanno form.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django import forms

from .models import SuggestionCorner

User = get_user_model()


class ClassificaForm(forms.Form):
    stato_sms = forms.ChoiceField(
        choices=[
            (SuggestionCorner.StatoSMS.SMS_SI, "SMS Sì"),
            (SuggestionCorner.StatoSMS.SMS_NO, "SMS No"),
        ],
        label="Esito classificazione",
    )


class PlanForm(forms.Form):
    incaricato = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("username"),
        label="Incaricato (DO)",
    )
    controllore = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("username"),
        label="Controllore (CHECK)",
    )
    data_limite_esecuzione = forms.DateField(
        label="Scadenza esecuzione (DO)", widget=forms.DateInput(attrs={"type": "date"}),
    )
    data_limite_controllo = forms.DateField(
        label="Scadenza controllo (CHECK)", widget=forms.DateInput(attrs={"type": "date"}),
    )
    plan_testo = forms.CharField(label="Piano", widget=forms.Textarea, required=False)

    def clean(self):
        cleaned = super().clean()
        inc = cleaned.get("incaricato")
        ctrl = cleaned.get("controllore")
        if inc and ctrl and inc == ctrl:
            raise forms.ValidationError("Il controllore deve essere diverso dall'incaricato.")
        return cleaned


class CompletaDoForm(forms.Form):
    esito_do = forms.ChoiceField(
        choices=[
            (SuggestionCorner.EsitoAttivita.SI, "Sì"),
            (SuggestionCorner.EsitoAttivita.NO, "No"),
        ],
        label="Esito esecuzione",
    )
    do_testo = forms.CharField(label="Descrizione esecuzione", widget=forms.Textarea, required=False)


class DoRifareForm(forms.Form):
    nuova_data_limite_esecuzione = forms.DateField(
        label="Nuova scadenza esecuzione", widget=forms.DateInput(attrs={"type": "date"}),
    )


class CheckForm(forms.Form):
    check_testo = forms.CharField(label="Note controllo", widget=forms.Textarea, required=False)


class CheckRinviatoForm(forms.Form):
    nuova_data_limite_controllo = forms.DateField(
        label="Nuova scadenza controllo", widget=forms.DateInput(attrs={"type": "date"}),
    )
