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
    ProcessoQualificato,
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
            "cliente", "nome", "regime", "livello",
            "ente_certificatore", "tipo_qualifica",
            "tipo_validita", "data_conseguimento", "durata_mesi", "data_scadenza",
            "personale_modalita", "riferimento_dichiarazione",
            "stato", "motivo_stato", "riferimento_stato",
            "numero_revisione", "responsabile_qualita", "data_revisione",
            "reparti", "clienti_addizionali",
            "corsi_richiesti", "dpi_richiesti", "visite_richieste", "note",
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
            # corsi/DPI/visite: select nativi con filtro + crea-al-volo (_mpq_quickadd),
            # niente data-picker (gestiti dall'enhancer MOD.128, non dal msp-picker).
            "corsi_richiesti": forms.SelectMultiple(attrs={"class": "fm-input fm-select", "size": "6"}),
            "dpi_richiesti": forms.SelectMultiple(attrs={"class": "fm-input fm-select", "size": "6"}),
            "visite_richieste": forms.SelectMultiple(attrs={"class": "fm-input fm-select", "size": "6"}),
            "note": forms.Textarea(attrs=_FM_TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("ente_certificatore", "tipo_qualifica", "reparti",
                  "clienti_addizionali", "durata_mesi", "data_conseguimento",
                  "data_scadenza", "data_revisione",
                  "corsi_richiesti", "dpi_richiesti", "visite_richieste"):
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
    """Requisito generico tipizzato di un processo (1.14): audit/certificato/…"""

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
