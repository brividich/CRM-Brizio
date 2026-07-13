from django import forms
from .models import LetturaContatori, Macchina, ImpostazioniSNMP


class LetturaForm(forms.ModelForm):
    class Meta:
        model = LetturaContatori
        fields = ["macchina", "trimestre", "data", "a4_bn", "a3_bn",
                  "a4_col", "a3_col", "fonte", "note"]
        widgets = {"data": forms.DateInput(attrs={"type": "date"})}


class MacchinaForm(forms.ModelForm):
    class Meta:
        model = Macchina
        fields = ["reparto", "matricola", "modello", "contratto",
                  "fornitore", "host", "attiva"]


class ImpostazioniSNMPForm(forms.ModelForm):
    class Meta:
        model = ImpostazioniSNMP
        fields = ["community", "port", "timeout", "version"]
