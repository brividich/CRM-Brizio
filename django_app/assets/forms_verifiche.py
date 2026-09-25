"""Form della sezione Manutenzione > Verifiche periodiche (impianti)."""
from __future__ import annotations

from django import forms
from django.utils import timezone

from anagrafica.models import Fornitore

from .models import (
    PERIODIC_FREQUENCY_LABELS,
    Asset,
    PeriodicCheckCategory,
    PeriodicCheckIntakeConfig,
    PeriodicCheckItem,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)

_DATE = {"type": "date"}


def _supplier_queryset():
    return Fornitore.objects.filter(is_active=True).order_by("ragione_sociale")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


class PeriodicCheckSystemForm(forms.ModelForm):
    class Meta:
        model = PeriodicCheckSystem
        fields = ["name", "description", "asset", "sort_order", "is_active"]
        labels = {
            "name": "Impianto",
            "description": "Descrizione",
            "asset": "Asset per gli ordini di lavoro",
            "sort_order": "Ordine",
            "is_active": "Attivo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")
        self.fields["asset"].required = False


class PeriodicCheckCategoryForm(forms.ModelForm):
    class Meta:
        model = PeriodicCheckCategory
        fields = ["name", "description", "color", "sort_order", "is_active"]
        labels = {
            "name": "Categoria",
            "description": "Descrizione",
            "color": "Colore",
            "sort_order": "Ordine",
            "is_active": "Attiva",
        }
        widgets = {"color": forms.RadioSelect}


class PeriodicCheckTypeForm(forms.ModelForm):
    frequency_months = forms.TypedChoiceField(
        label="Frequenza",
        coerce=int,
        choices=[(months, label) for months, label in PERIODIC_FREQUENCY_LABELS.items()],
    )
    items_text = forms.CharField(
        label="Voci di checklist",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Una voce per riga (solo per il metodo «Checklist a voci»).",
    )

    class Meta:
        model = PeriodicCheckType
        fields = [
            "system", "category", "name", "reference_code", "method", "frequency_months", "warning_days",
            "supplier", "executor_label", "legal_reference", "next_due_date", "archive_folder",
            "instructions", "point_categories", "sort_order", "is_active",
        ]
        labels = {
            "system": "Impianto",
            "category": "Categoria",
            "name": "Verifica",
            "reference_code": "Codice",
            "method": "Come si registra",
            "warning_days": "Preavviso (giorni)",
            "supplier": "Fornitore",
            "executor_label": "Esecutore (se non in anagrafica)",
            "legal_reference": "Riferimento normativo",
            "next_due_date": "Prossima scadenza",
            "archive_folder": "Cartella d'archivio",
            "instructions": "Istruzioni",
            "point_categories": "Tipi di segnalazione sui punti",
            "sort_order": "Ordine",
            "is_active": "Attiva",
        }
        help_texts = {
            "next_due_date": "Si ricalcola da sola a ogni verifica registrata; qui si imposta la prima.",
            "archive_folder": "Solo riferimento: dove stavano i documenti prima del portale.",
            "category": "Per filtrare e raggruppare l'elenco (es. Antincendio, Elettrico).",
            "point_categories": "Uno per riga. Sul foglio il primo si segna con l'evidenziatore, il secondo con un cerchio a penna.",
        }
        widgets = {
            "next_due_date": forms.DateInput(attrs=_DATE, format="%Y-%m-%d"),
            "instructions": forms.Textarea(attrs={"rows": 3}),
            "point_categories": forms.Textarea(attrs={"rows": 2}),
            "method": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["system"].queryset = PeriodicCheckSystem.objects.filter(is_active=True)
        self.fields["category"].queryset = PeriodicCheckCategory.objects.filter(is_active=True)
        self.fields["category"].required = False
        self.fields["category"].empty_label = "Nessuna categoria"
        self.fields["supplier"].queryset = _supplier_queryset()
        self.fields["supplier"].required = False
        if self.instance.pk:
            self.fields["items_text"].initial = "\n".join(
                self.instance.items.filter(is_active=True).values_list("label", flat=True)
            )

    def save_items(self, check_type: PeriodicCheckType) -> None:
        """Allinea le voci al testo: le voci tolte si spengono (gli esiti passati restano)."""
        wanted = _lines(self.cleaned_data.get("items_text", ""))
        existing = {item.label: item for item in check_type.items.all()}
        for index, label in enumerate(wanted):
            item = existing.pop(label, None)
            if item is None:
                PeriodicCheckItem.objects.create(check_type=check_type, label=label[:200], sort_order=(index + 1) * 10)
            else:
                item.sort_order = (index + 1) * 10
                item.is_active = True
                item.save(update_fields=["sort_order", "is_active"])
        for item in existing.values():
            if item.is_active:
                item.is_active = False
                item.save(update_fields=["is_active"])


class PeriodicCheckRegisterForm(forms.Form):
    performed_on = forms.DateField(label="Data della verifica", widget=forms.DateInput(attrs=_DATE, format="%Y-%m-%d"))
    outcome = forms.ChoiceField(
        label="Esito",
        choices=[c for c in PeriodicCheckSession.OUTCOME_CHOICES if c[0] != PeriodicCheckSession.OUTCOME_ARCHIVE],
        widget=forms.RadioSelect,
        initial=PeriodicCheckSession.OUTCOME_OK,
    )
    technician = forms.CharField(label="Tecnico", max_length=120, required=False)
    supplier = forms.ModelChoiceField(label="Fornitore", queryset=Fornitore.objects.none(), required=False)
    remarks_text = forms.CharField(
        label="Rilievi / prescrizioni",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Uno per riga. Ogni rilievo potra' diventare un ordine di lavoro.",
    )
    notes = forms.CharField(label="Note", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    next_due_date = forms.DateField(
        label="Prossima scadenza",
        required=False,
        widget=forms.DateInput(attrs=_DATE, format="%Y-%m-%d"),
        help_text="Vuota = calcolata dalla frequenza. Compilala se il verbale indica una data diversa.",
    )

    def __init__(self, *args, check_type: PeriodicCheckType, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_type = check_type
        self.fields["supplier"].queryset = _supplier_queryset()
        if not self.is_bound:
            self.fields["performed_on"].initial = timezone.localdate()
            if check_type.supplier_id:
                self.fields["supplier"].initial = check_type.supplier_id

    def clean(self):
        cleaned = super().clean()
        performed_on = cleaned.get("performed_on")
        next_due = cleaned.get("next_due_date")
        if performed_on and next_due and next_due <= performed_on:
            self.add_error("next_due_date", "La prossima scadenza deve essere dopo la data della verifica.")
        return cleaned

    @property
    def remarks(self) -> list[str]:
        return _lines(self.cleaned_data.get("remarks_text", ""))


class WorkOrderFromResultForm(forms.Form):
    asset = forms.ModelChoiceField(label="Asset", queryset=Asset.objects.none())
    title = forms.CharField(label="Titolo", max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = Asset.objects.order_by("asset_tag", "name")


class PeriodicCheckIntakeConfigForm(forms.ModelForm):
    class Meta:
        model = PeriodicCheckIntakeConfig
        fields = ["attiva", "cartella", "sposta_elaborati", "max_file_per_giro"]
        labels = {
            "attiva": "Leggi la cartella in automatico (ogni 2 minuti)",
            "cartella": "Cartella di rete dello scanner",
            "sposta_elaborati": "Sposta i file letti in «elaborati» e gli altri in «errori»",
            "max_file_per_giro": "File al massimo per passaggio",
        }
