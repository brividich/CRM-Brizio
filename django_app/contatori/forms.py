import re
import uuid

from django import forms

from .models import (
    ColonnaProfiloSNMP,
    CommunitySNMP,
    DispositivoSNMP,
    ImpostazioniSNMP,
    LetturaContatori,
    Macchina,
    ProfiloSNMP,
    SondaSNMP,
)


class CommunitySNMPForm(forms.ModelForm):
    valore = forms.CharField(label="Community read-only", max_length=60, required=False,
                             strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                             help_text="In modifica lascia vuoto per mantenere il valore salvato.")

    class Meta:
        model = CommunitySNMP
        fields = ["nome", "valore", "versione", "porta", "ordine", "attiva"]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "community_%s")
        super().__init__(*args, **kwargs)

    def clean_valore(self):
        value = self.cleaned_data.get("valore", "")
        if not value and not self.instance.pk:
            raise forms.ValidationError("Inserisci la community.")
        return value

    def clean_porta(self):
        value = self.cleaned_data.get("porta")
        if value is not None and not 1 <= value <= 65535:
            raise forms.ValidationError("La porta deve essere compresa tra 1 e 65535.")
        return value

    def save(self, commit=True):
        from .credential_crypto import cifra
        instance = super().save(commit=False)
        if self.cleaned_data.get("valore"):
            instance.segreto_cifrato = cifra(self.cleaned_data["valore"])
        if commit:
            instance.save()
        return instance


class DiscoveryBackgroundForm(forms.Form):
    richiesta = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    rete = forms.CharField(max_length=64, initial="10.0.0.0/24", label="Rete CIDR")
    communities = forms.MultipleChoiceField(label="Community da provare", initial=["0"],
                                            widget=forms.CheckboxSelectMultiple)
    versione = forms.ChoiceField(choices=ImpostazioniSNMP.Versione.choices)
    timeout = forms.IntegerField(min_value=1, max_value=10, initial=2,
                                 label="Attesa per richiesta (secondi)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["communities"].choices = [("0", "Globale")] + [
            (str(c.pk), c.nome) for c in CommunitySNMP.objects.filter(attiva=True)]

    def clean_rete(self):
        from .snmp import SNMPError, hosts_rete
        try:
            self.hosts = hosts_rete(self.cleaned_data["rete"])
        except SNMPError as e:
            raise forms.ValidationError(str(e)) from e
        return self.cleaned_data["rete"]

    def clean_communities(self):
        values = self.cleaned_data["communities"]
        if len(values) > 8:
            raise forms.ValidationError("Seleziona al massimo otto community.")
        # Ordine stabile del catalogo; non dipende dall'ordine delle checkbox nel POST.
        return [int(key) for key, _ in self.fields["communities"].choices if key in values]


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
            "host", "profilo_snmp", "community_salvata", "snmp_community", "snmp_porta", "snmp_versione",
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
            "nome", "categoria", "host", "profilo_snmp", "community_salvata", "community", "porta", "versione",
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
            "descrizione", "sys_object_id_prefix", "sys_descr_pattern", "oid_riconoscimento",
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
            "unita", "fattore", "contatore_mfc", "soglia_warning_min", "soglia_warning_max",
            "soglia_critica_min", "soglia_critica_max", "verificata", "fonte", "ordine", "attiva",
        ]
