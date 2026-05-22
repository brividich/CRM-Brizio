from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import (
    AreaAziendale,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    RuoloAziendale,
    TipoVisitaMedica,
    VisitaMedica,
)


# NOTE: i form Fornitore* sono stati spostati nel modulo `fornitori.forms`
# insieme alle view dei fornitori. Vedere `fornitori/forms.py`.


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


class AnagraficaCivileForm(forms.ModelForm):
    class Meta:
        model = DipendenteAnagraficaCivile
        exclude = ["legacy_anagrafica_id", "updated_by", "updated_at"]
        widgets = {
            "foto": forms.ClearableFileInput(attrs={"class": "dp-input", "accept": "image/*"}),
            "data_nascita": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "luogo_nascita": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Comune di nascita"}),
            "provincia_nascita": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. PI oppure PISA", "style": "text-transform:uppercase"}),
            "nazionalita": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. Italiana"}),
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
        exclude = [
            "legacy_anagrafica_id", "updated_by", "updated_at",
            "tipologia_contratto", "livello_inquadramento",
        ]
        widgets = {
            "badge": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Codice badge fisico"}),
            "taglia_scarpe": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. 42"}),
            "taglia_pantalone": forms.TextInput(attrs={"class": "dp-input", "placeholder": "Es. 48 oppure 50/34"}),
            "taglia_maglia": forms.Select(attrs={"class": "dp-input"}),
            "data_consenso_privacy": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "data_prima_assunzione": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "data_assunzione_ultima": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "data_cessazione": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "prova_data_inizio": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "prova_data_fine": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
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

    def clean_badge(self):
        val = self.cleaned_data.get("badge", "").strip()
        if val:
            stripped = val.lstrip("0")
            return stripped if stripped else "0"
        return val


# ---------------------------------------------------------------------------
# Visite mediche
# ---------------------------------------------------------------------------

class VisitaMedicaForm(forms.ModelForm):
    """Form di registrazione/modifica visita medica.

    Il referto è gestito come FileField separato: la view crea un
    ``DocumentoDipendente`` di tipo VISITA_MEDICA_REFERTO e lo aggancia
    a ``visita.referto_documento``.
    """

    referto_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "dp-input", "accept": ".pdf,image/*"}),
        help_text="Referto/documento allegato (opzionale). Storage privato.",
    )

    class Meta:
        model = VisitaMedica
        fields = [
            "tipo", "data_svolgimento", "esito",
            "prescrizioni", "medico_competente", "note",
        ]
        widgets = {
            "tipo": forms.Select(attrs={"class": "dp-input"}),
            "data_svolgimento": forms.DateInput(attrs={"class": "dp-input", "type": "date"}),
            "esito": forms.Select(attrs={"class": "dp-input"}),
            "prescrizioni": forms.Textarea(attrs={"class": "dp-input", "rows": 2}),
            "medico_competente": forms.TextInput(attrs={"class": "dp-input"}),
            "note": forms.Textarea(attrs={"class": "dp-input", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoVisitaMedica.objects.filter(is_active=True).order_by("nome")

    def clean_data_svolgimento(self):
        data = self.cleaned_data.get("data_svolgimento")
        if data and data > timezone.localdate():
            raise forms.ValidationError("La data di svolgimento non può essere nel futuro.")
        return data
