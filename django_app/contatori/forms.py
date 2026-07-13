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
                  "fornitore", "host", "asset", "attiva"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Aggancio manuale all'Asset del registro HUB (in alternativa al match
        # automatico del comando `collega_asset`).
        self.fields["asset"].label = "Asset collegato (registro HUB)"
        self.fields["asset"].required = False
        self.fields["asset"].empty_label = "— nessun asset collegato —"
        try:
            from assets.models import Asset
            self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")
        except Exception:  # pragma: no cover - assets sempre presente nell'HUB
            pass


class ImpostazioniSNMPForm(forms.ModelForm):
    class Meta:
        model = ImpostazioniSNMP
        fields = ["community", "port", "timeout", "version"]
