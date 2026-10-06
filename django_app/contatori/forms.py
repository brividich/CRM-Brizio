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


_PASSWORD = {"autocomplete": "new-password"}
CAMPI_V3 = ("v3_utente", "v3_auth", "v3_auth_key", "v3_priv", "v3_priv_key")


class CredenzialiV3Form(forms.Form):
    """Campi SNMPv3 comuni ai form; il JS `snmp_v3.js` li mostra solo con versione v3.

    `campo_versione` indica il campo che seleziona la versione SNMP.
    """
    campo_versione = "versione"

    v3_utente = forms.CharField(label="SNMPv3 - utente", max_length=64, required=False)
    v3_auth = forms.ChoiceField(label="SNMPv3 - autenticazione", required=False,
                                choices=[("", "Nessuna"), ("sha1", "SHA"), ("md5", "MD5")])
    v3_auth_key = forms.CharField(label="SNMPv3 - chiave di autenticazione", max_length=128,
                                  required=False, strip=False,
                                  widget=forms.PasswordInput(attrs=_PASSWORD))
    v3_priv = forms.ChoiceField(label="SNMPv3 - cifratura", required=False,
                                choices=[("", "Nessuna"), ("aes", "AES"), ("des", "DES")])
    v3_priv_key = forms.CharField(label="SNMPv3 - chiave di cifratura", max_length=128,
                                  required=False, strip=False,
                                  widget=forms.PasswordInput(attrs=_PASSWORD),
                                  help_text="Per sostituire le credenziali reinseriscile tutte: "
                                            "il segreto viene riscritto per intero.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[self.campo_versione].widget.attrs["data-snmp-versione"] = ""
        for nome in CAMPI_V3:
            self.fields[nome].widget.attrs["data-snmp-v3"] = ""
        # Campi v3 subito dopo il selettore di versione.
        ordine = [n for n in self.fields if n not in CAMPI_V3]
        pos = ordine.index(self.campo_versione) + 1
        self.order_fields(ordine[:pos] + list(CAMPI_V3) + ordine[pos:])

    def _v3_richiesta(self):
        return self.cleaned_data.get(self.campo_versione) == "v3"

    def _v3_compilata(self):
        return any(self.cleaned_data.get(k) for k in ("v3_utente", "v3_auth_key", "v3_priv_key"))

    def _segreto_v3(self):
        """Segreto serializzato oppure "" con errore sul form."""
        from .snmp import SNMPError, segreto_v3
        try:
            return segreto_v3(*(self.cleaned_data.get(k, "") for k in CAMPI_V3))
        except SNMPError as e:
            self.add_error("v3_utente", str(e))
            return ""


class CommunitySNMPForm(CredenzialiV3Form, forms.ModelForm):
    valore = forms.CharField(label="Community read-only", max_length=60, required=False,
                             strip=False, widget=forms.PasswordInput(attrs=_PASSWORD),
                             help_text="In modifica lascia vuoto per mantenere il valore salvato. "
                                       "Non usata con SNMPv3.")

    class Meta:
        model = CommunitySNMP
        fields = ["nome", "valore", "versione", "porta", "ordine", "attiva"]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "community_%s")
        super().__init__(*args, **kwargs)
        self.fields["valore"].widget.attrs["data-snmp-non-v3"] = ""

    def clean_porta(self):
        value = self.cleaned_data.get("porta")
        if value is not None and not 1 <= value <= 65535:
            raise forms.ValidationError("La porta deve essere compresa tra 1 e 65535.")
        return value

    def clean(self):
        data = super().clean()
        self._segreto = ""
        era_v3 = self.instance.pk and self.instance.versione == "v3"
        if self._v3_richiesta():
            # In modifica di una credenziale già v3 i campi vuoti la lasciano invariata.
            if self._v3_compilata() or not era_v3:
                self._segreto = self._segreto_v3()
        elif data.get("valore"):
            self._segreto = data["valore"]
        elif not self.instance.pk or era_v3:
            self.add_error("valore", "Inserisci la community.")
        return data

    def save(self, commit=True):
        from .credential_crypto import cifra
        instance = super().save(commit=False)
        if self._segreto:
            instance.segreto_cifrato = cifra(self._segreto)
        if commit:
            instance.save()
        return instance


class SezioniFormMixin:
    """Raggruppa i campi in sezioni per `_form_sezioni.html`.

    `sezioni_def`: tuple (titolo, descrizione, campi). I campi v3 finiscono nel
    riquadro dedicato della loro sezione; quelli non elencati nell'ultima.
    """
    sezioni_def = ()
    campi_full = frozenset({"note", "asset"})

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        if "profilo_snmp" in self.fields:
            self.fields["profilo_snmp"].label = "Profilo SNMP"

    def sezioni(self):
        usati, out = set(), []
        for titolo, descrizione, campi in self.sezioni_def:
            nomi = [n for n in campi if n in self.fields]
            usati.update(nomi)
            out.append({"titolo": titolo, "descrizione": descrizione,
                        "campi": [self[n] for n in nomi if n not in CAMPI_V3],
                        "v3": [self[n] for n in nomi if n in CAMPI_V3]})
        out[-1]["campi"] += [self[n] for n in self.fields if n not in usati]
        return out


_DESCR_SNMP = ("Indirizzo e parametri di lettura. I campi vuoti usano il profilo "
               "o la configurazione globale.")


class CredenzialeV3InlineMixin(CredenzialiV3Form):
    """Credenziali v3 inserite sull'apparato: salvate cifrate nel catalogo community.

    I campi compilati prevalgono sulla credenziale selezionata; se non compilati
    serve una credenziale salvata.
    """

    campo_community = "community"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[self.campo_community].widget.attrs["data-snmp-non-v3"] = ""

    def nome_credenziale_v3(self, instance):
        raise NotImplementedError

    def clean(self):
        data = super().clean()
        self._segreto_v3_inline = ""
        if self._v3_richiesta():
            if self._v3_compilata():
                self._segreto_v3_inline = self._segreto_v3()
            elif not data.get("community_salvata"):
                self.add_error("v3_utente", "SNMPv3: inserisci le credenziali "
                                            "o seleziona una community salvata.")
        return data

    def save(self, commit=True):
        from .credential_crypto import cifra
        instance = super().save(commit=False)
        if self._segreto_v3_inline:
            community, _ = CommunitySNMP.objects.update_or_create(
                nome=self.nome_credenziale_v3(instance)[:80],
                defaults={"versione": "v3", "segreto_cifrato": cifra(self._segreto_v3_inline)})
            instance.community_salvata = community
        if commit:
            instance.save()
            self.save_m2m()
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


def _imposta_campo_asset(field):
    field.required = False
    field.empty_label = "— nessun asset collegato —"
    try:
        from assets.models import Asset
        field.queryset = Asset.objects.order_by("asset_tag", "name")
    except Exception:  # pragma: no cover
        pass


class MacchinaForm(SezioniFormMixin, CredenzialeV3InlineMixin, forms.ModelForm):
    campo_versione = "snmp_versione"
    campo_community = "snmp_community"
    sezioni_def = (
        ("Macchina", "Dati di contratto e fatturazione.",
         ("reparto", "matricola", "modello", "contratto", "fornitore")),
        ("Connessione SNMP", _DESCR_SNMP,
         ("host", "profilo_snmp", "snmp_versione", "snmp_porta", "snmp_timeout",
          "community_salvata", "snmp_community", *CAMPI_V3)),
        ("Collegamenti", "", ("asset", "attiva")),
    )

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
        _imposta_campo_asset(self.fields["asset"])

    def nome_credenziale_v3(self, instance):
        return f"SNMPv3 stampante {instance.matricola}"

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


class DispositivoSNMPForm(SezioniFormMixin, CredenzialeV3InlineMixin, forms.ModelForm):
    sezioni_def = (
        ("Identità", "Come riconoscere l'apparato nella centrale.",
         ("nome", "categoria", "posizione", "produttore", "modello", "matricola")),
        ("Connessione SNMP", _DESCR_SNMP,
         ("host", "profilo_snmp", "versione", "porta", "timeout",
          "community_salvata", "community", *CAMPI_V3)),
        ("Collegamenti e note", "", ("asset", "note", "attivo")),
    )

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
        _imposta_campo_asset(self.fields["asset"])

    def nome_credenziale_v3(self, instance):
        return f"SNMPv3 dispositivo {instance.host}"

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
            "soglia_critica_min", "soglia_critica_max", "etichette", "ordine", "attiva",
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
            "soglia_critica_min", "soglia_critica_max", "etichette", "verificata", "fonte", "ordine", "attiva",
        ]
