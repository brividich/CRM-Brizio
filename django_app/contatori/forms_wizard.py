"""Form dei passi del wizard «Nuovo dispositivo SNMP». Ogni passo si valida lato server."""
from django import forms

from .forms import CAMPI_V3, CredenzialiV3Form, _imposta_campo_asset
from .models import CommunitySNMP, DispositivoSNMP, ProfiloSNMP


class PassoTipoForm(forms.Form):
    nome = forms.CharField(max_length=100, label="Nome del dispositivo",
                           help_text="Come comparirà nella Centrale, es. «UPS sala server».")
    categoria = forms.ChoiceField(choices=DispositivoSNMP.Categoria.choices, label="Tipo di apparato")
    profilo = forms.ModelChoiceField(
        queryset=ProfiloSNMP.objects.none(), required=False, label="Modello (profilo SNMP)",
        empty_label="Generico: riconosci il modello durante il test",
        help_text="Un preset noto porta con sé gli OID dei contatori; con «Generico» il portale "
                  "prova a riconoscerlo dal sysObjectID.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profilo"].queryset = ProfiloSNMP.objects.filter(attivo=True).order_by("produttore", "nome")
        self.fields["profilo"].label_from_instance = lambda p: f"{p.produttore} · {p.nome}"
        self.fields["profilo"].widget.attrs["class"] = "js-searchable"


class PassoReteForm(forms.Form):
    host = forms.CharField(max_length=253, label="Indirizzo IP o nome host",
                           help_text="Un nome viene risolto subito nel suo IP.")
    porta = forms.IntegerField(min_value=1, max_value=65535, initial=161, label="Porta UDP")
    versione = forms.ChoiceField(label="Versione SNMP", initial="v2c", choices=[
        ("v2c", "SNMPv2c (consigliata)"), ("v3", "SNMPv3 (utente e chiavi)"),
        ("v1", "SNMPv1 (solo apparati datati)")])

    def __init__(self, *args, escludi_pk=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.escludi_pk = escludi_pk

    def clean_host(self):
        from .errori_snmp import ErroreSNMPCatalogato, valida_host
        try:
            ip = valida_host(self.cleaned_data["host"])
        except ErroreSNMPCatalogato as e:
            raise forms.ValidationError(f"[{e.codice}] {e}") from e
        esistente = DispositivoSNMP.objects.filter(host=ip).exclude(pk=self.escludi_pk).first()
        if esistente:
            raise forms.ValidationError(
                f"L'indirizzo {ip} è già usato dal dispositivo «{esistente.nome}»: aprilo dal "
                "Monitor SNMP invece di crearne un altro.")
        return ip


class PassoCredenzialiForm(CredenzialiV3Form):
    """Community dal catalogo cifrato, community nuova (salvata cifrata) o utente v3."""
    campo_versione = "versione"

    versione = forms.CharField(widget=forms.HiddenInput)  # dal passo «Rete», non modificabile qui
    community_salvata = forms.ModelChoiceField(
        queryset=CommunitySNMP.objects.none(), required=False, label="Credenziale dal catalogo",
        empty_label="— nessuna: ne inserisco una nuova —")
    community = forms.CharField(
        max_length=60, required=False, strip=False, label="Nuova community (sola lettura)",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Viene salvata cifrata nel catalogo, mai in chiaro. Se l'hai già inserita, "
                  "lascia vuoto per mantenerla.")
    usa_globale = forms.BooleanField(required=False, label="Usa la community della configurazione globale")

    def __init__(self, *args, globale_disponibile=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.globale_disponibile = globale_disponibile
        if not globale_disponibile:
            del self.fields["usa_globale"]
        self.fields["community_salvata"].queryset = CommunitySNMP.objects.filter(attiva=True).order_by("ordine", "nome")
        self.fields["community_salvata"].label_from_instance = (
            lambda c: f"{c.nome} ({c.get_versione_display() or 'qualsiasi versione'})")

    def campi_visibili(self):
        """La versione e' nota dal passo «Rete»: si mostrano solo i campi pertinenti."""
        v3 = self["versione"].value() == "v3"
        nascosti = {"community", "usa_globale"} if v3 else set(CAMPI_V3)
        return [self[n] for n in self.fields if n not in nascosti and n != "versione"]

    def clean(self):
        data = super().clean()
        versione = data.get("versione")
        salvata = data.get("community_salvata")
        if salvata and salvata.versione and (salvata.versione == "v3") != (versione == "v3"):
            self.add_error("community_salvata", f"Questa credenziale è per {salvata.get_versione_display()}, "
                                                f"ma al passo precedente hai scelto {versione}.")
        self._segreto_inline = ""
        # Una scelta esplicita (catalogo o globale) vince sui campi digitati: niente
        # segreto «vecchio» che resta attivo dopo aver cambiato idea.
        if salvata or (versione != "v3" and data.get("usa_globale")):
            return data
        if versione == "v3":
            if self._v3_compilata():
                self._segreto_inline = self._segreto_v3()
            else:
                self.add_error("v3_utente", "SNMPv3: inserisci utente e chiavi o scegli una credenziale v3 dal catalogo.")
        else:
            self._segreto_inline = data.get("community") or ""
            if not self._segreto_inline:
                self.add_error("community", "Scegli una credenziale dal catalogo o inserisci la community.")
        return data


class PassoAssociazioneForm(forms.Form):
    asset = forms.ModelChoiceField(queryset=None, required=False,  # impostato in __init__
                                   label="Asset collegato (registro HUB)")
    posizione = forms.CharField(max_length=120, required=False, label="Reparto / posizione",
                                help_text="Es. «Officina - piano terra».")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _imposta_campo_asset(self.fields["asset"])
        self.fields["asset"].widget.attrs.update({"class": "js-searchable",
                                                  "data-placeholder": "Cerca per tag, nome o seriale…"})
        self.fields["asset"].label_from_instance = (
            lambda a: f"{a.asset_tag} · {a.name}" + (f" · {a.serial_number}" if a.serial_number else ""))


CAMPI_SEGRETI = ("community", "v3_auth_key", "v3_priv_key")
__all__ = ["PassoTipoForm", "PassoReteForm", "PassoCredenzialiForm", "PassoAssociazioneForm",
           "CAMPI_SEGRETI", "CAMPI_V3"]
