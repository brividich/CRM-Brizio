from __future__ import annotations

from django import forms
from django.utils import timezone

from assets.models import Asset

from .models import Fornitore, FornitoreAsset, FornitoreDocumento, FornitoreOrdine, FornitoreValutazione


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
