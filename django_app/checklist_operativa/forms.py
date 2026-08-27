from __future__ import annotations

from django import forms
from django.db.models import Q

from anagrafica.models import Reparto
from core.legacy_models import AnagraficaDipendente

from .models import ChecklistTaskTemplate, ChiusuraEvento, ChiusuraProposta, ChiusuraVoce


def _responsabili_queryset():
    # Solo dipendenti collegati a un account utente: sono gli unici che possono
    # accedere alla pagina "Gestione" e confermare i propri task.
    return (
        AnagraficaDipendente.objects.filter(utente_id__isnull=False)
        .order_by("cognome", "nome")
    )


def _prepara_vice(form) -> None:
    """Configura il campo ``vice_responsabili``, uguale su template e voce."""
    campo = form.fields["vice_responsabili"]
    campo.queryset = _responsabili_queryset()
    campo.required = False
    campo.widget.attrs.update({"class": "hub-select co-multi", "size": "6"})
    campo.help_text = (
        "Chi può confermare al posto del responsabile se è assente. "
        "Tieni premuto CTRL per sceglierne più di uno."
    )


def _valida_vice(form):
    """Il responsabile non è vice di se stesso: sarebbe una delega che non delega."""
    responsabile = form.cleaned_data.get("responsabile")
    vice = form.cleaned_data.get("vice_responsabili")
    if responsabile and vice and responsabile in vice:
        form.add_error(
            "vice_responsabili",
            "Il responsabile non può essere anche vice di se stesso: "
            "scegli un collega diverso.",
        )


class ChecklistTaskTemplateForm(forms.ModelForm):
    class Meta:
        model = ChecklistTaskTemplate
        fields = [
            "descrizione", "responsabile", "vice_responsabili",
            "reparto", "ordine", "attivo", "note",
        ]
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
        self.fields["attivo"].widget.attrs["class"] = "hub-checkbox"
        _prepara_vice(self)
        # Reparti dal catalogo di anagrafica: i disattivati restano fuori, ma se
        # una mansione ne ha già uno disattivato lo si continua a vedere invece
        # di azzerarlo alla prima modifica.
        reparti = Reparto.objects.filter(is_active=True)
        corrente = getattr(self.instance, "reparto_id", None)
        if corrente:
            reparti = Reparto.objects.filter(Q(is_active=True) | Q(pk=corrente))
        self.fields["reparto"].queryset = reparti.order_by("nome")
        self.fields["reparto"].required = False
        self.fields["reparto"].empty_label = "— nessun reparto —"
        self.fields["reparto"].widget.attrs["class"] = "hub-select"

    def clean(self):
        cd = super().clean()
        _valida_vice(self)
        return cd


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
        fields = ["descrizione", "responsabile", "vice_responsabili", "ordine", "note"]
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
        _prepara_vice(self)

    def clean(self):
        cd = super().clean()
        _valida_vice(self)
        return cd


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
