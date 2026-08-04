from __future__ import annotations

from django import forms

from core.legacy_models import AnagraficaDipendente

from .models import ChecklistTaskTemplate, ChiusuraEvento, ChiusuraProposta, ChiusuraVoce


def _responsabili_queryset():
    # Solo dipendenti collegati a un account utente: sono gli unici che possono
    # accedere alla pagina "Gestione" e confermare i propri task.
    return (
        AnagraficaDipendente.objects.filter(utente_id__isnull=False)
        .order_by("cognome", "nome")
    )


class ChecklistTaskTemplateForm(forms.ModelForm):
    class Meta:
        model = ChecklistTaskTemplate
        fields = ["descrizione", "responsabile", "reparto", "ordine", "attivo", "note"]
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 2, "class": "hub-input"}),
            "reparto": forms.TextInput(attrs={"class": "hub-input"}),
            "ordine": forms.NumberInput(attrs={"class": "hub-input"}),
            "note": forms.Textarea(attrs={"rows": 2, "class": "hub-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsabile"].queryset = _responsabili_queryset()
        self.fields["responsabile"].required = False
        self.fields["responsabile"].widget.attrs["class"] = "hub-select"
        self.fields["attivo"].widget.attrs["class"] = "hub-checkbox"


class ChiusuraEventoForm(forms.ModelForm):
    class Meta:
        model = ChiusuraEvento
        fields = ["nome", "data_inizio", "data_fine", "note"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "hub-input", "placeholder": "Es. Ferie estive 2026"}),
            "data_inizio": forms.DateInput(attrs={"class": "hub-input", "type": "date"}, format="%Y-%m-%d"),
            "data_fine": forms.DateInput(attrs={"class": "hub-input", "type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 2, "class": "hub-input"}),
        }

    def clean(self):
        cd = super().clean()
        data_inizio, data_fine = cd.get("data_inizio"), cd.get("data_fine")
        if data_inizio and data_fine and data_fine < data_inizio:
            self.add_error("data_fine", "La data di fine non può precedere la data di inizio.")
        return cd


class ChiusuraVoceForm(forms.ModelForm):
    class Meta:
        model = ChiusuraVoce
        fields = ["descrizione", "responsabile", "ordine", "note"]
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 2, "class": "hub-input"}),
            "ordine": forms.NumberInput(attrs={"class": "hub-input"}),
            "note": forms.Textarea(attrs={"rows": 2, "class": "hub-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsabile"].queryset = _responsabili_queryset()
        self.fields["responsabile"].required = False
        self.fields["responsabile"].widget.attrs["class"] = "hub-select"


class ChiusuraPropostaForm(forms.ModelForm):
    class Meta:
        model = ChiusuraProposta
        fields = ["descrizione", "responsabile_suggerito"]
        widgets = {
            "descrizione": forms.Textarea(attrs={
                "rows": 2, "class": "hub-input",
                "placeholder": "Cosa proponi di aggiungere alla checklist?",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsabile_suggerito"].queryset = _responsabili_queryset()
        self.fields["responsabile_suggerito"].required = False
        self.fields["responsabile_suggerito"].widget.attrs["class"] = "hub-select"
        self.fields["responsabile_suggerito"].label = "Responsabile suggerito (opzionale)"


class ChiusuraPropostaDecisioneForm(forms.Form):
    DECISIONE_CHOICES = [("approva", "Approva"), ("rifiuta", "Rifiuta")]

    decisione = forms.ChoiceField(choices=DECISIONE_CHOICES, widget=forms.RadioSelect)
    aggiungi_al_template = forms.BooleanField(
        required=False, label="Aggiungi anche come mansione permanente in configurazione",
    )
    note_admin = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2, "class": "hub-input"}),
    )
