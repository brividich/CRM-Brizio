"""Form dei passi del wizard «Nuovo apparato» (MFC e dispositivi SNMP). Ogni passo si valida lato server."""
from django import forms

from .forms import CAMPI_V3, CredenzialiV3Form, SezioniFormMixin, _imposta_campo_asset
from .models import CommunitySNMP, DispositivoSNMP, Macchina, ProfiloSNMP

# Valore del tipo che crea una Macchina (MFC a contratto) invece di un DispositivoSNMP.
TIPO_MFC = "MFC"
TIPI_APPARATO = [(TIPO_MFC, "Stampante MFC a contratto (contatori e fattura)")] + [
    (valore, "Stampante senza contratto MFC" if valore == DispositivoSNMP.Categoria.STAMPANTE else etichetta)
    for valore, etichetta in DispositivoSNMP.Categoria.choices
]

# Tipo d'apparato proposto in base al tipo dell'asset scelto.
TIPO_DA_ASSET = {"STAMPANTE": TIPO_MFC, "FIREWALL": "FIREWALL", "SERVER": "SERVER", "CCTV": "TVCC_NVR"}


def valori_asset(asset):
    """Dati dell'asset usati per i campi lasciati vuoti (mai sovrascritti se compilati)."""
    if asset is None:
        return {}
    ip = next((e.ip for e in asset.endpoints.all() if e.ip), "")
    return {"nome": asset.name or "", "matricola": asset.serial_number or "", "modello": asset.model or "",
            "produttore": asset.manufacturer or "", "posizione": asset.reparto or "", "host": ip}


class PassoApparatoForm(SezioniFormMixin, forms.Form):
    """Asset di partenza, tipo d'apparato e identità; i campi solo-MFC sono marcati per il JS."""
    sezioni_def = (
        ("Asset del registro", "Se l'apparato è già nel registro Asset, sceglilo: i campi lasciati vuoti "
                               "prendono nome, matricola, modello, reparto e IP dall'asset.",
         ("asset",)),
        ("Che apparato è", "", ("tipo_apparato", "nome", "matricola", "modello", "posizione",
                                "contratto", "fornitore", "note")),
    )
    campi_full = frozenset({"asset", "note"})

    asset = forms.ModelChoiceField(queryset=None, required=False, label="Asset collegato (registro HUB)")
    tipo_apparato = forms.ChoiceField(choices=TIPI_APPARATO, label="Tipo di apparato",
                                      help_text="Le MFC a contratto hanno i quattro contatori e la "
                                                "riconciliazione con la fattura; gli altri apparati "
                                                "vanno nel Monitor SNMP.")
    nome = forms.CharField(max_length=100, required=False, label="Nome",
                           help_text="Come comparirà nel portale. Per le MFC è il reparto, es. «CQF - 2».")
    matricola = forms.CharField(max_length=40, required=False, label="Matricola / seriale")
    modello = forms.CharField(max_length=120, required=False, label="Modello",
                              help_text="Es. «iR-ADV C5535i»: i Canon iR-ADV noti hanno i contatori già mappati.")
    posizione = forms.CharField(max_length=120, required=False, label="Reparto / posizione",
                                help_text="Es. «Officina - piano terra».")
    contratto = forms.CharField(max_length=20, required=False, label="Contratto",
                                help_text="Stesso contratto = fatturazione in pool.")
    fornitore = forms.ChoiceField(choices=Macchina.Fornitore.choices, initial=Macchina.Fornitore.BASE,
                                  required=False, label="Fornitore")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _imposta_campo_asset(self.fields["asset"])
        self.fields["asset"].widget.attrs.update({"class": "js-searchable",
                                                  "data-placeholder": "Cerca per tag, nome o seriale…"})
        self.fields["asset"].label_from_instance = (
            lambda a: f"{a.asset_tag} · {a.name}" + (f" · {a.serial_number}" if a.serial_number else ""))
        self.fields["tipo_apparato"].widget.attrs["data-tipo-apparato"] = ""
        for nome in ("contratto", "fornitore"):
            self.fields[nome].widget.attrs["data-solo-mfc"] = ""
        for nome in ("posizione", "note"):
            self.fields[nome].widget.attrs["data-solo-altri"] = ""

    def clean(self):
        data = super().clean()
        asset = data.get("asset")
        dall_asset = valori_asset(asset)
        for campo in ("nome", "matricola", "modello", "posizione"):
            if not data.get(campo) and dall_asset.get(campo):
                data[campo] = dall_asset[campo][:self.fields[campo].max_length]
        mfc = data.get("tipo_apparato") == TIPO_MFC
        if not data.get("nome"):
            self.add_error("nome", "Inserisci il nome (per le MFC il reparto) o scegli un asset.")
        if mfc:
            if data.get("nome") and len(data["nome"]) > 60:
                self.add_error("nome", "Per le MFC il reparto ha al massimo 60 caratteri.")
            if not data.get("matricola"):
                self.add_error("matricola", "Per una MFC la matricola è obbligatoria.")
            elif Macchina.objects.filter(matricola=data["matricola"]).exists():
                self.add_error("matricola", f"Esiste già una stampante con matricola {data['matricola']}.")
            data["fornitore"] = data.get("fornitore") or Macchina.Fornitore.BASE
        return data


class PassoConnessioneForm(SezioniFormMixin, CredenzialiV3Form):
    """Indirizzo, versione e credenziali in una pagina. Con v3 la community non si usa."""
    campo_versione = "versione"
    testo_v3 = "Le chiavi sono salvate cifrate e non vengono mai mostrate. La community non serve."
    sezioni_def = (
        ("Indirizzo", "Dove si trova in rete e quale versione SNMP usa.", ("host", "porta", "versione")),
        ("Credenziali", "Con cosa il portale si presenta all'apparato (sola lettura).",
         ("community_salvata", "community", "usa_globale", *CAMPI_V3)),
    )

    host = forms.CharField(max_length=253, label="Indirizzo IP o nome host",
                           help_text="Un nome viene risolto subito nel suo IP.")
    porta = forms.IntegerField(min_value=1, max_value=65535, initial=161, label="Porta UDP")
    versione = forms.ChoiceField(label="Versione SNMP", initial="v2c", choices=[
        ("v2c", "SNMPv2c (consigliata)"), ("v3", "SNMPv3 (utente e chiavi)"),
        ("v1", "SNMPv1 (solo apparati datati)")])
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
        if not globale_disponibile:
            del self.fields["usa_globale"]
        else:
            self.fields["usa_globale"].widget.attrs["data-snmp-non-v3"] = ""
        self.fields["community"].widget.attrs["data-snmp-non-v3"] = ""
        self.fields["community_salvata"].queryset = CommunitySNMP.objects.filter(attiva=True).order_by("ordine", "nome")
        self.fields["community_salvata"].label_from_instance = (
            lambda c: f"{c.nome} ({c.get_versione_display() or 'qualsiasi versione'})")

    def v3(self):
        return self["versione"].value() == "v3"

    def clean_host(self):
        from .errori_snmp import ErroreSNMPCatalogato, valida_host
        try:
            ip = valida_host(self.cleaned_data["host"])
        except ErroreSNMPCatalogato as e:
            raise forms.ValidationError(f"[{e.codice}] {e}") from e
        esistente = DispositivoSNMP.objects.filter(host=ip).first()
        if esistente:
            raise forms.ValidationError(
                f"L'indirizzo {ip} è già usato dal dispositivo «{esistente.nome}»: aprilo dal "
                "Monitor SNMP invece di crearne un altro.")
        mfc = Macchina.objects.filter(host=ip).first()
        if mfc:
            raise forms.ValidationError(
                f"L'indirizzo {ip} è già usato dalla stampante «{mfc.reparto}» ({mfc.matricola}).")
        return ip

    def clean(self):
        data = super().clean()
        versione = data.get("versione")
        salvata = data.get("community_salvata")
        if salvata and salvata.versione and (salvata.versione == "v3") != (versione == "v3"):
            self.add_error("community_salvata", f"Questa credenziale è per {salvata.get_versione_display()}, "
                                                f"ma la versione scelta è {versione}.")
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


class PassoVerificaForm(forms.Form):
    """Modello (profilo) da usare: vuoto = quello riconosciuto dalla verifica."""
    profilo = forms.ModelChoiceField(
        queryset=ProfiloSNMP.objects.none(), required=False, label="Modello (profilo SNMP)",
        empty_label="Riconosci automaticamente dalla verifica")

    def __init__(self, *args, solo_stampanti=False, **kwargs):
        super().__init__(*args, **kwargs)
        profili = ProfiloSNMP.objects.filter(attivo=True)
        if solo_stampanti:
            profili = profili.filter(categoria=ProfiloSNMP.Categoria.STAMPANTE)
        self.fields["profilo"].queryset = profili.order_by("produttore", "nome")
        self.fields["profilo"].label_from_instance = lambda p: f"{p.produttore} · {p.nome}"
        self.fields["profilo"].widget.attrs["class"] = "js-searchable"


CAMPI_SEGRETI = ("community", "v3_auth_key", "v3_priv_key")
__all__ = ["PassoApparatoForm", "PassoConnessioneForm", "PassoVerificaForm", "CAMPI_SEGRETI", "CAMPI_V3",
           "TIPO_MFC", "valori_asset"]
