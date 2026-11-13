"""MOD.128 MPQ — form di gestione (CRUD) processi/clienti/abilitazioni/certificati.

Form additivi (come ``models_mpq``/``views_mpq``) per la gestione in-app dei
processi qualificati. Riusano le classi CSS ``fm-*`` del design HR. La gestione
delle **persone** distingue dipendenti interni (``legacy_anagrafica_id`` da
picker) dai **qualificatori esterni** (``nominativo_esterno``).
"""
from __future__ import annotations

from django import forms

from .models_mpq import (
    AbilitazioneProcesso,
    CertificazioneIndividuale,
    ClienteQualificante,
    EvidenzaRequisitoPersona,
    ProcessoQualificato,
    QualificaMacchina,
    RequisitoMacchina,
    RequisitoPersona,
    RequisitoQualifica,
    RiferimentoProcesso,
)

_FM = {"class": "fm-input"}
_FM_SELECT = {"class": "fm-input fm-select"}
_FM_TEXTAREA = {"class": "fm-input", "rows": 3}
_FM_DATE = {"class": "fm-input", "type": "date"}
_FM_NUM = {"class": "fm-input", "min": "0"}
_FM_CHECK = {"class": "fm-check"}


class ClienteQualificanteForm(forms.ModelForm):
    class Meta:
        model = ClienteQualificante
        fields = ["nome", "tipo", "codice", "certificatore", "is_active", "note"]
        widgets = {
            "nome": forms.TextInput(attrs=_FM),
            "tipo": forms.Select(attrs=_FM_SELECT),
            "codice": forms.TextInput(attrs=_FM),
            "certificatore": forms.Select(attrs=_FM_SELECT),
            "is_active": forms.CheckboxInput(attrs=_FM_CHECK),
            "note": forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = ClienteQualificante.objects.all().order_by("nome")
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["certificatore"].queryset = qs
        self.fields["certificatore"].required = False


class ProcessoQualificatoForm(forms.ModelForm):
    class Meta:
        model = ProcessoQualificato
        fields = [
            "cliente", "nome", "regime", "perimetro_part145", "livello",
            "ente_certificatore", "tipo_qualifica",
            "tipo_validita", "data_conseguimento", "durata_mesi", "data_scadenza",
            "frequenza_macchine_mesi",
            "personale_modalita", "riferimento_dichiarazione",
            "stato", "motivo_stato", "riferimento_stato",
            "numero_revisione", "responsabile_qualita", "data_revisione",
            "reparti", "clienti_addizionali", "note",
        ]
        widgets = {
            "cliente": forms.Select(attrs=_FM_SELECT),
            "nome": forms.TextInput(attrs=_FM),
            "regime": forms.Select(attrs=_FM_SELECT),
            "livello": forms.TextInput(attrs=_FM),
            "ente_certificatore": forms.Select(attrs=_FM_SELECT),
            "tipo_qualifica": forms.Select(attrs=_FM_SELECT),
            "tipo_validita": forms.Select(attrs=_FM_SELECT),
            "data_conseguimento": forms.DateInput(attrs=_FM_DATE),
            "durata_mesi": forms.NumberInput(attrs=_FM_NUM),
            "data_scadenza": forms.DateInput(attrs=_FM_DATE),
            "frequenza_macchine_mesi": forms.NumberInput(attrs=_FM_NUM),
            "personale_modalita": forms.Select(attrs=_FM_SELECT),
            "riferimento_dichiarazione": forms.TextInput(attrs=_FM),
            "stato": forms.Select(attrs=_FM_SELECT),
            "motivo_stato": forms.TextInput(attrs=_FM),
            "riferimento_stato": forms.TextInput(attrs=_FM),
            "numero_revisione": forms.TextInput(attrs=_FM),
            "responsabile_qualita": forms.TextInput(attrs=_FM),
            "data_revisione": forms.DateInput(attrs=_FM_DATE),
            "reparti": forms.SelectMultiple(attrs={
                "class": "fm-input fm-select", "size": "6",
                "data-picker": "", "data-picker-placeholder": "Cerca reparto…"}),
            "clienti_addizionali": forms.SelectMultiple(attrs={
                "class": "fm-input fm-select", "size": "4",
                "data-picker": "", "data-picker-placeholder": "Cerca cliente/ente…"}),
            "note": forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("ente_certificatore", "tipo_qualifica", "reparti",
                  "clienti_addizionali", "durata_mesi", "data_conseguimento",
                  "data_scadenza", "data_revisione", "frequenza_macchine_mesi"):
            self.fields[f].required = False
        cli_qs = ClienteQualificante.objects.all().order_by("nome")
        self.fields["cliente"].queryset = cli_qs
        add_qs = cli_qs
        if self.instance and self.instance.pk:
            add_qs = cli_qs.exclude(pk=self.instance.cliente_id)
        self.fields["clienti_addizionali"].queryset = add_qs


class RiferimentoProcessoForm(forms.ModelForm):
    class Meta:
        model = RiferimentoProcesso
        fields = ["codice", "tipo", "note"]
        widgets = {
            "codice": forms.TextInput(attrs=_FM),
            "tipo": forms.Select(attrs=_FM_SELECT),
            "note": forms.TextInput(attrs=_FM),
        }


class RequisitoQualificaForm(forms.ModelForm):
    """Requisito del processo **uguale per tutti** (contratto, audit, certificato del processo…).

    Ciò che serve alla singola persona (corso, esame, test visivo, esperienza, DPI)
    va in «Cosa serve a una persona»: quei tipi restano scelti solo sui requisiti
    già registrati, per non perderli.
    """

    TIPI_PROCESSO = tuple(k for k, _v in RequisitoQualifica.TIPO_CHOICES
                          if k not in RequisitoQualifica.TIPI_PER_PERSONA)

    class Meta:
        model = RequisitoQualifica
        fields = [
            "tipo", "descrizione", "obbligatorio", "rif_normativo",
            "stato", "data_conseguimento", "periodicita_mesi", "data_scadenza",
            "evidenza_url", "note",
        ]
        widgets = {
            "tipo": forms.Select(attrs=_FM_SELECT),
            "descrizione": forms.TextInput(attrs=_FM),
            "obbligatorio": forms.CheckboxInput(attrs=_FM_CHECK),
            "rif_normativo": forms.TextInput(attrs=_FM),
            "stato": forms.Select(attrs=_FM_SELECT),
            "data_conseguimento": forms.DateInput(attrs=_FM_DATE),
            "periodicita_mesi": forms.NumberInput(attrs=_FM_NUM),
            "data_scadenza": forms.DateInput(attrs=_FM_DATE),
            "evidenza_url": forms.TextInput(attrs=_FM),
            "note": forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("rif_normativo", "data_conseguimento", "periodicita_mesi",
                  "data_scadenza", "evidenza_url", "note"):
            self.fields[f].required = False
        attuale = getattr(self.instance, "tipo", None) if self.instance.pk else None
        self.fields["tipo"].choices = [
            (k, v) for k, v in RequisitoQualifica.TIPO_CHOICES if k in self.TIPI_PROCESSO or k == attuale
        ]


class CertificazioneIndividualeForm(forms.ModelForm):
    class Meta:
        model = CertificazioneIndividuale
        fields = ["schema", "numero", "livello", "data_scadenza",
                  "ente_certificatore", "stato", "documento", "note"]
        widgets = {
            "schema": forms.TextInput(attrs=_FM),
            "numero": forms.TextInput(attrs=_FM),
            "livello": forms.TextInput(attrs=_FM),
            "data_scadenza": forms.DateInput(attrs=_FM_DATE),
            "ente_certificatore": forms.Select(attrs=_FM_SELECT),
            "stato": forms.Select(attrs=_FM_SELECT),
            "note": forms.TextInput(attrs=_FM),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("numero", "livello", "data_scadenza", "ente_certificatore",
                  "documento", "note"):
            self.fields[f].required = False
        self.fields["ente_certificatore"].queryset = (
            ClienteQualificante.objects.all().order_by("nome"))


class AbilitazioneProcessoForm(forms.Form):
    """Abilitazione persona×processo: dipendente interno (picker) o esterno."""

    TIPO_INTERNO = "interno"
    TIPO_ESTERNO = "esterno"

    tipo_persona = forms.ChoiceField(
        choices=[(TIPO_INTERNO, "Dipendente interno"), (TIPO_ESTERNO, "Qualificatore esterno")],
        widget=forms.RadioSelect, initial=TIPO_INTERNO,
    )
    # Il <select> dei dipendenti è reso dal template (popolato dalla view); qui
    # il campo cattura solo il legacy_id scelto (nessuna validazione su choices).
    dipendente = forms.CharField(required=False)
    nominativo_esterno = forms.CharField(
        required=False, max_length=200, widget=forms.TextInput(attrs=_FM))
    is_qualificato = forms.BooleanField(required=False, initial=True, widget=forms.CheckboxInput(attrs=_FM_CHECK))
    is_addetto = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs=_FM_CHECK))
    is_controllore = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs=_FM_CHECK))
    is_part145 = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs=_FM_CHECK))
    stato = forms.ChoiceField(
        choices=AbilitazioneProcesso.STATO_CHOICES,
        initial=AbilitazioneProcesso.STATO_ATTIVA, widget=forms.Select(attrs=_FM_SELECT))
    data_ingresso = forms.DateField(required=False, widget=forms.DateInput(attrs=_FM_DATE))
    note = forms.CharField(required=False, max_length=255, widget=forms.TextInput(attrs=_FM))

    def clean(self):
        cd = super().clean()
        tipo = cd.get("tipo_persona")
        if tipo == self.TIPO_ESTERNO:
            if not (cd.get("nominativo_esterno") or "").strip():
                self.add_error("nominativo_esterno", "Indicare il nominativo del qualificatore esterno.")
            cd["legacy_anagrafica_id"] = 0
        else:
            dip = (cd.get("dipendente") or "").strip()
            if not dip:
                self.add_error("dipendente", "Selezionare un dipendente.")
            else:
                try:
                    cd["legacy_anagrafica_id"] = int(dip)
                except ValueError:
                    self.add_error("dipendente", "Dipendente non valido.")
            cd["nominativo_esterno"] = ""
        return cd


# ── Persone qualificate e macchine qualificate (13/11/2026) ──────────────────

class RequisitoPersonaForm(forms.ModelForm):
    """Cosa serve a una persona sul processo: per ruolo, una tantum o ricorrente."""

    class Meta:
        model = RequisitoPersona
        fields = [
            "tipo", "corso", "tipo_visita", "tipo_qualifica", "categoria_dpi", "descrizione", "ruoli",
            "ricorrenza", "frequenza_mesi", "scadenza_fine_mese", "ore_minime",
            "bloccante", "attivo", "note",
        ]
        labels = {
            "corso": "Corso (per «Corso di formazione»)",
            "tipo_visita": "Visita (per «Visita medica»)",
            "tipo_qualifica": "Qualifica (per «Qualifica del catalogo»)",
            "categoria_dpi": "Categoria DPI (per «DPI consegnato»)",
            "descrizione": "Descrizione",
            "ruoli": "Vale per i ruoli (vuoto = tutti)",
        }
        widgets = {
            "tipo": forms.Select(attrs=_FM_SELECT),
            "corso": forms.Select(attrs=_FM_SELECT),
            "tipo_visita": forms.Select(attrs=_FM_SELECT),
            "tipo_qualifica": forms.Select(attrs=_FM_SELECT),
            "categoria_dpi": forms.Select(attrs=_FM_SELECT),
            "descrizione": forms.TextInput(attrs=_FM),
            "ruoli": forms.SelectMultiple(attrs={"class": "fm-input fm-select", "size": "6",
                                                 "data-picker": "",
                                                 "data-picker-placeholder": "Cerca ruolo…"}),
            "ricorrenza": forms.Select(attrs=_FM_SELECT),
            "frequenza_mesi": forms.NumberInput(attrs=_FM_NUM),
            "scadenza_fine_mese": forms.CheckboxInput(attrs=_FM_CHECK),
            "ore_minime": forms.NumberInput(attrs={**_FM_NUM, "step": "0.5"}),
            "bloccante": forms.CheckboxInput(attrs=_FM_CHECK),
            "attivo": forms.CheckboxInput(attrs=_FM_CHECK),
            "note": forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, processo=None, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("corso", "tipo_visita", "tipo_qualifica", "categoria_dpi", "descrizione", "ruoli",
                  "frequenza_mesi", "ore_minime", "note"):
            self.fields[f].required = False
        self.fields["frequenza_mesi"].help_text = (
            "Per corsi, visite e qualifiche vuoto = segue la loro scadenza; se la scrivi vale la più "
            "vicina fra le due (anche nello scadenzario della Formazione).")
        self.fields["tipo_qualifica"].queryset = (
            self.fields["tipo_qualifica"].queryset.filter(is_active=True).order_by("nome"))
        processo = processo or getattr(self.instance, "processo", None)
        self.fields["ruoli"].queryset = (processo.ruoli.all() if processo is not None
                                         else self.fields["ruoli"].queryset.none())
        self.fields["corso"].queryset = self.fields["corso"].queryset.order_by("titolo")

    def clean(self):
        cd = super().clean()
        tipo = cd.get("tipo")
        if tipo == RequisitoPersona.TIPO_CORSO and not cd.get("corso"):
            self.add_error("corso", "Scegli il corso.")
        if tipo == RequisitoPersona.TIPO_VISITA and not cd.get("tipo_visita"):
            self.add_error("tipo_visita", "Scegli la visita.")
        if tipo == RequisitoPersona.TIPO_QUALIFICA and not cd.get("tipo_qualifica"):
            self.add_error("tipo_qualifica", "Scegli la qualifica.")
        if tipo == RequisitoPersona.TIPO_DPI and not cd.get("categoria_dpi"):
            self.add_error("categoria_dpi", "Scegli la categoria DPI.")
        if tipo not in RequisitoPersona.TIPI_DA_ALTRI_MODULI and not (cd.get("descrizione") or "").strip():
            self.add_error("descrizione", "Scrivi cosa serve (es. «Test visivo Jaeger»).")
        if (cd.get("ricorrenza") == RequisitoPersona.RICORRENZA_RICORRENTE and not cd.get("frequenza_mesi")
                and tipo not in RequisitoPersona.TIPI_DA_ALTRI_MODULI):
            self.add_error("frequenza_mesi", "Indica ogni quanti mesi va ripetuto.")
        if tipo == RequisitoPersona.TIPO_ESPERIENZA and not cd.get("ore_minime"):
            self.add_error("ore_minime", "Indica le ore da raggiungere.")
        return cd


class EvidenzaRequisitoPersonaForm(forms.ModelForm):
    class Meta:
        model = EvidenzaRequisitoPersona
        fields = ["data_esecuzione", "esito", "ore", "data_scadenza", "documento", "note"]
        labels = {"data_esecuzione": "Eseguito il", "data_scadenza": "Scade il (vuoto = dalla ricorrenza)"}
        widgets = {
            "data_esecuzione": forms.DateInput(attrs=_FM_DATE),
            "esito": forms.Select(attrs=_FM_SELECT),
            "ore": forms.NumberInput(attrs={**_FM_NUM, "step": "0.5"}),
            "data_scadenza": forms.DateInput(attrs=_FM_DATE),
            "note": forms.TextInput(attrs=_FM),
        }

    def __init__(self, *args, requisito=None, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("ore", "data_scadenza", "documento", "note"):
            self.fields[f].required = False
        if requisito is not None and requisito.tipo != RequisitoPersona.TIPO_ESPERIENZA:
            del self.fields["ore"]


class RequisitoMacchinaForm(forms.ModelForm):
    class Meta:
        model = RequisitoMacchina
        fields = ["tipo", "descrizione", "piano", "ricorrenza", "bloccante", "attivo"]
        widgets = {
            "tipo": forms.Select(attrs=_FM_SELECT),
            "descrizione": forms.TextInput(attrs=_FM),
            "piano": forms.Select(attrs=_FM_SELECT),
            "ricorrenza": forms.TextInput(attrs=_FM),
            "bloccante": forms.CheckboxInput(attrs=_FM_CHECK),
            "attivo": forms.CheckboxInput(attrs=_FM_CHECK),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["piano"].required = False
        self.fields["ricorrenza"].required = False
        self.fields["piano"].queryset = self.fields["piano"].queryset.order_by("label")


class QualificaMacchinaForm(forms.ModelForm):
    class Meta:
        model = QualificaMacchina
        fields = ["data_qualifica", "frequenza_mesi", "data_scadenza", "limitazioni", "note"]
        labels = {"data_qualifica": "Qualificata il", "data_scadenza": "Scade il (vuoto = dalla frequenza)"}
        widgets = {
            "data_qualifica": forms.DateInput(attrs=_FM_DATE),
            "frequenza_mesi": forms.NumberInput(attrs=_FM_NUM),
            "data_scadenza": forms.DateInput(attrs=_FM_DATE),
            "limitazioni": forms.Textarea(attrs=_FM_TEXTAREA),
            "note": forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields:
            self.fields[f].required = False
