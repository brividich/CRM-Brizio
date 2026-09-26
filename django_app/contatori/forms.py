import re

from django import forms

from .models import (
    ColonnaProfiloSNMP,
    DispositivoSNMP,
    ImpostazioniSNMP,
    LetturaContatori,
    Macchina,
    ProfiloSNMP,
    SondaSNMP,
)


class LetturaForm(forms.ModelForm):
    class Meta:
        model = LetturaContatori
        fields = [
            "macchina", "trimestre", "data", "a4_bn", "a3_bn",
            "a4_col", "a3_col", "fonte", "note",
        ]
        widgets = {"data": forms.DateInput(attrs={"type": "date"})}


class MacchinaForm(forms.ModelForm):
    class Meta:
        model = Macchina
        fields = [
            "reparto", "matricola", "modello", "contratto", "fornitore",
            "host", "profilo_snmp", "snmp_community", "snmp_porta", "snmp_versione",
            "snmp_timeout", "asset", "attiva",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].label = "Asset collegato (registro HUB)"
        self.fields["asset"].required = False
        self.fields["asset"].empty_label = "— nessun asset collegato —"
        try:
            from assets.models import Asset
            self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")
        except Exception:  # pragma: no cover
            pass

    def clean(self):
        cleaned = super().clean()
        modello = (cleaned.get("modello") or "").strip()
        if modello and modello not in Macchina.Modello.values and not cleaned.get("profilo_snmp"):
            self.add_error(
                "modello",
                "Per un modello non Canon seleziona un profilo SNMP dal catalogo.",
            )
        return cleaned


class ImpostazioniSNMPForm(forms.ModelForm):
    class Meta:
        model = ImpostazioniSNMP
        fields = ["community", "port", "timeout", "version"]


class DispositivoSNMPForm(forms.ModelForm):
    class Meta:
        model = DispositivoSNMP
        fields = [
            "nome", "categoria", "host", "profilo_snmp", "community", "porta", "versione",
            "timeout", "posizione", "produttore", "modello", "matricola",
            "asset", "note", "attivo",
        ]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].required = False
        self.fields["asset"].empty_label = "— nessun asset collegato —"
        try:
            from assets.models import Asset
            self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")
        except Exception:  # pragma: no cover
            pass

    def clean_porta(self):
        porta = self.cleaned_data.get("porta")
        if porta is not None and porta > 65535:
            raise forms.ValidationError("La porta deve essere compresa tra 1 e 65535.")
        return porta


class SondaSNMPForm(forms.ModelForm):
    class Meta:
        model = SondaSNMP
        fields = [
            "nome", "oid", "tipo_valore", "modalita", "aggregazione",
            "unita", "fattore", "soglia_warning_min", "soglia_warning_max",
            "soglia_critica_min", "soglia_critica_max", "ordine", "attiva",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["modalita"].required = False
        self.fields["aggregazione"].required = False

    def clean(self):
        cleaned = super().clean()
        cleaned["modalita"] = cleaned.get("modalita") or SondaSNMP.Modalita.GET
        cleaned["aggregazione"] = (
            cleaned.get("aggregazione") or SondaSNMP.Aggregazione.PRIMO
        )
        oid = cleaned.get("oid")
        if oid and self.instance.dispositivo_id:
            duplicati = SondaSNMP.objects.filter(
                dispositivo_id=self.instance.dispositivo_id, oid=oid,
            ).exclude(pk=self.instance.pk)
            if duplicati.exists():
                self.add_error("oid", "Questo OID è già configurato per il dispositivo.")
        for campo_min, campo_max, etichetta in (
            ("soglia_warning_min", "soglia_warning_max", "warning"),
            ("soglia_critica_min", "soglia_critica_max", "critica"),
        ):
            minimo, massimo = cleaned.get(campo_min), cleaned.get(campo_max)
            if minimo is not None and massimo is not None and minimo > massimo:
                self.add_error(
                    campo_max,
                    f"La soglia massima {etichetta} deve essere ≥ della minima.",
                )
        return cleaned


class ProfiloSNMPForm(forms.ModelForm):
    class Meta:
        model = ProfiloSNMP
        fields = [
            "slug", "nome", "produttore", "categoria", "famiglia_modelli",
            "descrizione", "sys_object_id_prefix", "sys_descr_pattern",
            "versione", "porta", "timeout", "attivo", "note",
        ]
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_sys_descr_pattern(self):
        pattern = self.cleaned_data.get("sys_descr_pattern", "")
        if pattern:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise forms.ValidationError(f"Espressione regolare non valida: {exc}")
        return pattern


class ColonnaProfiloSNMPForm(forms.ModelForm):
    class Meta:
        model = ColonnaProfiloSNMP
        fields = [
            "nome", "oid", "tipo_valore", "modalita", "aggregazione",
            "unita", "fattore", "contatore_mfc", "ordine", "attiva",
        ]
