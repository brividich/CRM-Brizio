from django import forms
from .models import (
    DispositivoSNMP,
    ImpostazioniSNMP,
    LetturaContatori,
    Macchina,
    SondaSNMP,
)


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


class DispositivoSNMPForm(forms.ModelForm):
    def clean_porta(self):
        porta = self.cleaned_data.get("porta")
        if porta is not None and porta > 65535:
            raise forms.ValidationError("La porta deve essere compresa tra 1 e 65535.")
        return porta

    class Meta:
        model = DispositivoSNMP
        fields = [
            "nome", "categoria", "host", "porta", "versione", "posizione",
            "produttore", "modello", "matricola", "asset", "note", "attivo",
        ]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].required = False
        self.fields["asset"].empty_label = "— nessun asset collegato —"
        try:
            from assets.models import Asset
            self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")
        except Exception:  # pragma: no cover - assets sempre presente nell'HUB
            pass


class SondaSNMPForm(forms.ModelForm):
    class Meta:
        model = SondaSNMP
        fields = [
            "nome", "oid", "tipo_valore", "unita", "fattore",
            "soglia_warning_min", "soglia_warning_max",
            "soglia_critica_min", "soglia_critica_max", "ordine", "attiva",
        ]

    def clean(self):
        cleaned = super().clean()
        oid = cleaned.get("oid")
        if oid and self.instance.dispositivo_id:
            duplicati = SondaSNMP.objects.filter(
                dispositivo_id=self.instance.dispositivo_id, oid=oid,
            ).exclude(pk=self.instance.pk)
            if duplicati.exists():
                self.add_error("oid", "Questo OID è già configurato per il dispositivo.")
        coppie = (
            ("soglia_warning_min", "soglia_warning_max", "warning"),
            ("soglia_critica_min", "soglia_critica_max", "critica"),
        )
        for campo_min, campo_max, etichetta in coppie:
            minimo, massimo = cleaned.get(campo_min), cleaned.get(campo_max)
            if minimo is not None and massimo is not None and minimo > massimo:
                self.add_error(campo_max, f"La soglia massima {etichetta} deve essere ≥ della minima.")
        return cleaned
