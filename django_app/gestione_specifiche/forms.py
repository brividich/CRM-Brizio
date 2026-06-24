"""Form e formset per il flusso MOD.133 (F3)."""
from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory

from . import constants as C
from .models import MOD133, RigaMOD133, Specifica

_TXT = {"class": "gs-input"}
_AREA = {"class": "gs-input", "rows": 2}


class SpecificaForm(forms.ModelForm):
    class Meta:
        model = Specifica
        fields = [
            "codice", "revisione", "titolo", "tipo", "fonte", "cliente",
            "tag", "note", "allegato", "commessa_ref", "famiglia_ref",
        ]
        widgets = {
            "codice": forms.TextInput(attrs=_TXT),
            "revisione": forms.TextInput(attrs=_TXT),
            "titolo": forms.TextInput(attrs=_TXT),
            "tipo": forms.Select(attrs=_TXT),
            "fonte": forms.Select(attrs=_TXT),
            "cliente": forms.TextInput(attrs=_TXT),
            "tag": forms.TextInput(attrs=_TXT),
            "note": forms.Textarea(attrs=_AREA),
            "commessa_ref": forms.TextInput(attrs=_TXT),
            "famiglia_ref": forms.TextInput(attrs=_TXT),
        }


class RigaMOD133Form(forms.ModelForm):
    class Meta:
        model = RigaMOD133
        fields = [
            "ordine", "rif_paragrafo", "argomento", "descrizione_modifiche",
            "descrizione_impatto", "rif_doc_cn", "rif_paragrafo_cn", "tag_processo",
            "impatto_documenti", "impatto_operativo", "genera_ofi",
        ]
        widgets = {
            "ordine": forms.NumberInput(attrs={"class": "gs-input gs-input--num"}),
            "rif_paragrafo": forms.TextInput(attrs=_TXT),
            "argomento": forms.TextInput(attrs=_TXT),
            "descrizione_modifiche": forms.Textarea(attrs=_AREA),
            "descrizione_impatto": forms.Textarea(attrs=_AREA),
            "rif_doc_cn": forms.TextInput(attrs=_TXT),
            "rif_paragrafo_cn": forms.TextInput(attrs=_TXT),
            "tag_processo": forms.TextInput(attrs=_TXT),
        }

    def clean(self):
        cleaned = super().clean()
        # Griglia documenti obbligatoria solo se impatto_documenti=Y.
        if cleaned.get("impatto_documenti") and not (cleaned.get("rif_doc_cn") or "").strip():
            self.add_error("rif_doc_cn", "Obbligatorio quando l'impatto sui documenti è attivo.")
        return cleaned


RigaMOD133FormSet = inlineformset_factory(
    MOD133, RigaMOD133, form=RigaMOD133Form, extra=1, can_delete=True,
)


class ChiusuraCompilazioneForm(forms.Form):
    """Firma compilatore + assegnazione approvatore alla chiusura compilazione."""
    approvatore = forms.ModelChoiceField(
        queryset=None, label="Approvatore", widget=forms.Select(attrs=_TXT),
    )

    def __init__(self, *args, **kwargs):
        from django.contrib.auth import get_user_model
        super().__init__(*args, **kwargs)
        self.fields["approvatore"].queryset = get_user_model().objects.filter(is_active=True)


class ApprovazioneForm(forms.Form):
    esito = forms.ChoiceField(choices=C.ESITO_CHOICES, widget=forms.Select(attrs=_TXT))
    note = forms.CharField(required=False, widget=forms.Textarea(attrs=_AREA))


class DistribuzioneForm(forms.Form):
    canale = forms.ChoiceField(choices=C.CANALE_CHOICES, widget=forms.Select(attrs=_TXT))
    destinatari = forms.ModelMultipleChoiceField(
        queryset=None, required=False, widget=forms.CheckboxSelectMultiple,
        label="Reparti destinatari",
    )
    cartacea = forms.BooleanField(required=False, label="Copia cartacea")
    n_copie_distribuite = forms.IntegerField(min_value=0, initial=0, required=False,
                                             widget=forms.NumberInput(attrs={"class": "gs-input gs-input--num"}))
    n_copie_ritirate = forms.IntegerField(min_value=0, initial=0, required=False,
                                          widget=forms.NumberInput(attrs={"class": "gs-input gs-input--num"}))
    deroga_giustificazione = forms.CharField(required=False, widget=forms.Textarea(attrs=_AREA),
                                             label="Giustificazione deroga copie")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from anagrafica.models import Reparto
        self.fields["destinatari"].queryset = Reparto.objects.filter(is_active=True).order_by("nome")
