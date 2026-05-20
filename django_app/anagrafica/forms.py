from __future__ import annotations

from django import forms
from django.utils import timezone

from assets.models import Asset
from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_extension_and_mime,
)

from .models import (
    AreaAziendale,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    Fornitore,
    FornitoreAsset,
    FornitoreDocumento,
    FornitoreOrdine,
    FornitoreValutazione,
    RuoloAziendale,
)


# Documenti fornitore: PDF, immagini, Office. 15 MB.
FORNITORE_DOC_MAX_BYTES = 15 * 1024 * 1024
FORNITORE_DOC_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
}
FORNITORE_DOC_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "application/octet-stream",
}


class DipendenteLegacyForm(forms.Form):
    nome = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Nome"}))
    cognome = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Cognome"}))
    aliasusername = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Alias login"}))
    matricola = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Matricola"}))
    reparto = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Reparto"}))
    mansione = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Mansione"}))
    ruolo = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "ana-input", "placeholder": "Ruolo"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "ana-input", "placeholder": "login@dominio"}))
    email_notifica = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "ana-input", "placeholder": "nome@example.com"}))
    attivo = forms.BooleanField(required=False, initial=True)


class FornitoreForm(forms.ModelForm):
    class Meta:
        model = Fornitore
        fields = [
            "ragione_sociale", "piva", "codice_fiscale", "categoria",
            "telefono", "email", "pec", "website",
            "indirizzo", "citta", "cap", "provincia",
            "is_active", "note",
        ]
        widgets = {
            "ragione_sociale": forms.TextInput(attrs={"class": "ana-input", "placeholder": "Ragione sociale *"}),
            "piva": forms.TextInput(attrs={"class": "ana-input", "maxlength": 11, "placeholder": "12345678901"}),
            "codice_fiscale": forms.TextInput(attrs={"class": "ana-input", "maxlength": 16}),
            "categoria": forms.Select(attrs={"class": "ana-input"}),
            "telefono": forms.TextInput(attrs={"class": "ana-input", "placeholder": "+39 ..."}),
            "email": forms.EmailInput(attrs={"class": "ana-input"}),
            "pec": forms.EmailInput(attrs={"class": "ana-input"}),
            "website": forms.URLInput(attrs={"class": "ana-input", "placeholder": "https://..."}),
            "indirizzo": forms.TextInput(attrs={"class": "ana-input"}),
            "citta": forms.TextInput(attrs={"class": "ana-input"}),
            "cap": forms.TextInput(attrs={"class": "ana-input", "maxlength": 5}),
            "provincia": forms.TextInput(attrs={"class": "ana-input", "maxlength": 2, "style": "text-transform:uppercase"}),
            "note": forms.Textarea(attrs={"class": "ana-input", "rows": 3}),
        }


class FornitoreDocumentoForm(forms.ModelForm):
    class Meta:
        model = FornitoreDocumento
        fields = ["nome", "tipo", "file", "note"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "ana-input", "placeholder": "Nome documento"}),
            "tipo": forms.Select(attrs={"class": "ana-input"}),
            "note": forms.TextInput(attrs={"class": "ana-input", "placeholder": "Note opzionali"}),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if not uploaded_file:
            return uploaded_file
        try:
            validate_extension_and_mime(
                uploaded_file,
                allowed_extensions=FORNITORE_DOC_EXTENSIONS,
                allowed_mimes=FORNITORE_DOC_MIMES,
                max_bytes=FORNITORE_DOC_MAX_BYTES,
                label=safe_filename(getattr(uploaded_file, "name", "")) or "Documento",
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc))
        return uploaded_file


class FornitoreOrdineForm(forms.ModelForm):
    class Meta:
        model = FornitoreOrdine
        fields = ["numero_ordine", "data_ordine", "importo", "stato", "descrizione", "note"]
        widgets = {
            "numero_ordine": forms.TextInput(attrs={"class": "ana-input", "placeholder": "N. ordine (opzionale)"}),
            "data_ordine": forms.DateInput(attrs={"class": "ana-input", "type": "date"}),
            "importo": forms.NumberInput(attrs={"class": "ana-input", "step": "0.01", "placeholder": "0.00"}),
            "stato": forms.Select(attrs={"class": "ana-input"}),
            "descrizione": forms.Textarea(attrs={"class": "ana-input", "rows": 2, "placeholder": "Descrizione..."}),
            "note": forms.TextInput(attrs={"class": "ana-input", "placeholder": "Note"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial.setdefault("data_ordine", timezone.localdate())


STAR_CHOICES = [(i, f"{'★' * i}{'☆' * (5 - i)}  ({i}/5)") for i in range(1, 6)]


class FornitoreValutazioneForm(forms.ModelForm):
    class Meta:
        model = FornitoreValutazione
        fields = ["data", "qualita", "puntualita", "comunicazione", "note"]
        widgets = {
            "data": forms.DateInput(attrs={"class": "ana-input", "type": "date"}),
            "qualita": forms.Select(choices=STAR_CHOICES, attrs={"class": "ana-input"}),
            "puntualita": forms.Select(choices=STAR_CHOICES, attrs={"class": "ana-input"}),
            "comunicazione": forms.Select(choices=STAR_CHOICES, attrs={"class": "ana-input"}),
            "note": forms.Textarea(attrs={"class": "ana-input", "rows": 2, "placeholder": "Note opzionali..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial.setdefault("data", timezone.localdate())


class AnagraficaCivileForm(forms.ModelForm):
    class Meta:
        model = DipendenteAnagraficaCivile
        exclude = ["legacy_anagrafica_id", "updated_by", "updated_at"]
        widgets = {
            "data_nascita": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "luogo_nascita": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Comune di nascita"}),
            "genere": forms.Select(attrs={"class": "dp-input"}),
            "indirizzo_residenza": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Via/Piazza..."}),
            "citta_residenza": forms.TextInput(attrs={"class": "dp-input"}),
            "provincia_residenza": forms.TextInput(attrs={"class": "dp-input", "maxlength": 5, "style": "text-transform:uppercase"}),
            "nazione_residenza": forms.TextInput(attrs={"class": "dp-input"}),
            "cap_residenza": forms.TextInput(attrs={"class": "dp-input", "maxlength": 10}),
            "indirizzo_domicilio": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Se diverso dalla residenza"}),
            "citta_domicilio": forms.TextInput(attrs={"class": "dp-input"}),
            "nazione_domicilio": forms.TextInput(attrs={"class": "dp-input"}),
            "cap_domicilio": forms.TextInput(attrs={"class": "dp-input", "maxlength": 10}),
            "codice_fiscale": forms.TextInput(attrs={"class": "dp-input", "maxlength": 16, "style": "text-transform:uppercase"}),
            "titolo_studio": forms.Select(attrs={"class": "dp-input"}),
            "email_privata": forms.EmailInput(attrs={"class": "dp-input"}),
            "telefono_privato": forms.TextInput(attrs={"class": "dp-input", "placeholder": "+39 ..."}),
            "nome_banca": forms.TextInput(attrs={"class": "dp-input"}),
            "iban": forms.TextInput(attrs={"class": "dp-input", "maxlength": 34, "style": "text-transform:uppercase", "placeholder": "IT..."}),
            "intestatario_conto": forms.TextInput(attrs={"class": "dp-input"}),
            "percentuale_disabilita": forms.NumberInput(attrs={"class": "dp-input", "step": "0.01", "min": "0", "max": "100", "placeholder": "es. 46.00"}),
        }

    def clean_codice_fiscale(self):
        return self.cleaned_data.get("codice_fiscale", "").upper().strip()

    def clean_iban(self):
        return self.cleaned_data.get("iban", "").replace(" ", "").upper()


class AnagraficaAziendaleForm(forms.ModelForm):
    class Meta:
        model = DipendenteAnagraficaAziendale
        exclude = ["legacy_anagrafica_id", "updated_by", "updated_at"]
        widgets = {
            "taglia_scarpe": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. 42"}),
            "taglia_pantalone": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. 48 oppure 50/34"}),
            "taglia_maglia": forms.Select(attrs={"class": "dp-input"}),
            "data_consenso_privacy": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "data_prima_assunzione": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "prova_data_inizio": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "prova_data_fine": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "tipologia_contratto": forms.Select(attrs={"class": "dp-input"}),
            "livello_inquadramento": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. 3° livello CCNL Metalmeccanici"}),
            "email_aziendale": forms.EmailInput(attrs={"class": "dp-input"}),
            "telefono_aziendale": forms.TextInput(attrs={"class": "dp-input", "placeholder": "+39 ..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Area: dropdown da catalogo AreaAziendale; include il valore corrente anche se non nel catalogo
        active_aree = list(AreaAziendale.objects.filter(is_active=True).values_list("nome", flat=True).order_by("nome"))
        current_area = self.instance.area if self.instance.pk else ""
        if current_area and current_area not in active_aree:
            active_aree = [current_area] + active_aree
        area_choices = [("", "— Nessuna —")] + [(n, n) for n in active_aree]
        self.fields["area"].widget = forms.Select(attrs={"class": "dp-input"})
        self.fields["area"].widget.choices = area_choices

        # Ruolo aziendale: dropdown da catalogo RuoloAziendale
        active_ruoli = list(RuoloAziendale.objects.filter(is_active=True).values_list("nome", flat=True).order_by("nome"))
        current_ruolo = self.instance.ruolo_aziendale if self.instance.pk else ""
        if current_ruolo and current_ruolo not in active_ruoli:
            active_ruoli = [current_ruolo] + active_ruoli
        ruolo_choices = [("", "— Nessuno —")] + [(n, n) for n in active_ruoli]
        self.fields["ruolo_aziendale"].widget = forms.Select(attrs={"class": "dp-input"})
        self.fields["ruolo_aziendale"].widget.choices = ruolo_choices


class FornitoreAssetForm(forms.ModelForm):
    class Meta:
        model = FornitoreAsset
        fields = ["asset", "tipo", "data_inizio", "data_fine", "note"]
        widgets = {
            "asset": forms.Select(attrs={"class": "ana-input"}),
            "tipo": forms.Select(attrs={"class": "ana-input"}),
            "data_inizio": forms.DateInput(attrs={"class": "ana-input", "type": "date"}),
            "data_fine": forms.DateInput(attrs={"class": "ana-input", "type": "date"}),
            "note": forms.TextInput(attrs={"class": "ana-input", "placeholder": "Note"}),
        }

    def __init__(self, *args, fornitore=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("data_inizio", timezone.localdate())
        if fornitore:
            already = FornitoreAsset.objects.filter(fornitore=fornitore).values_list("asset_id", flat=True)
            qs = Asset.objects.exclude(pk__in=already).order_by("name")
        else:
            qs = Asset.objects.order_by("name")
        self.fields["asset"].queryset = qs
        self.fields["asset"].label_from_instance = lambda obj: f"{obj.asset_tag} — {obj.name}"
