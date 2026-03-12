from __future__ import annotations

from collections import defaultdict
import json
import re
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from django import forms
from django.db import transaction
from django.db.models import Q

from anagrafica.models import Fornitore

from .models import (
    Asset,
    AssetCategory,
    AssetCategoryField,
    AssetCustomField,
    AssetLabelTemplate,
    PeriodicVerification,
    PlantLayout,
    PlantLayoutArea,
    PlantLayoutMarker,
    WorkMachine,
    WorkOrder,
)


def _attach_input_css(form: forms.Form | forms.ModelForm) -> None:
    for field in form.fields.values():
        widget = field.widget
        css = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{css} input".strip()


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class AssetCategoryFieldMixin:
    CATEGORY_STORAGE_KEY = "_category_fields"

    def _category_field_form_name(self, code: str) -> str:
        return f"category__{code}"

    def _category_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "si", "s", "on"}
        return bool(value)

    def _category_date(self, value) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            row = value.strip()
            if not row:
                return None
            for parser in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    return datetime.strptime(row, parser).date()
                except ValueError:
                    continue
        return None

    def _category_value_from_extra(self, field_def: AssetCategoryField):
        raw = self._original_category_values.get(field_def.code, None)
        if field_def.field_type == AssetCategoryField.TYPE_BOOL:
            return self._category_bool(raw)
        if field_def.field_type == AssetCategoryField.TYPE_DATE:
            return self._category_date(raw)
        if field_def.field_type == AssetCategoryField.TYPE_NUMBER:
            return "" if raw in (None, "") else str(raw)
        return "" if raw is None else str(raw)

    def _normalize_category_value(self, field_def: AssetCategoryField, value):
        if field_def.field_type == AssetCategoryField.TYPE_BOOL:
            return bool(value)
        if field_def.field_type == AssetCategoryField.TYPE_DATE:
            if isinstance(value, datetime):
                return value.date().isoformat()
            if isinstance(value, date):
                return value.isoformat()
            return str(value or "").strip()
        if field_def.field_type == AssetCategoryField.TYPE_NUMBER:
            if value in (None, ""):
                return ""
            return str(value).strip()
        return str(value or "").strip()[:4000]

    def _build_category_form_field(self, field_def: AssetCategoryField):
        if field_def.field_type == AssetCategoryField.TYPE_NUMBER:
            field = forms.DecimalField(
                required=False,
                label=field_def.label,
                max_digits=16,
                decimal_places=2,
            )
        elif field_def.field_type == AssetCategoryField.TYPE_DATE:
            field = forms.DateField(
                required=False,
                label=field_def.label,
                input_formats=["%Y-%m-%d", "%d/%m/%Y"],
                widget=forms.DateInput(attrs={"type": "date"}),
            )
        elif field_def.field_type == AssetCategoryField.TYPE_BOOL:
            field = forms.BooleanField(required=False, label=field_def.label)
        elif field_def.field_type == AssetCategoryField.TYPE_TEXTAREA:
            field = forms.CharField(
                required=False,
                label=field_def.label,
                max_length=4000,
                widget=forms.Textarea(attrs={"rows": 3}),
            )
        else:
            field = forms.CharField(required=False, label=field_def.label, max_length=500)

        field.help_text = field_def.help_text
        field.widget.attrs["data-category-field"] = "1"
        field.widget.attrs["data-category-id"] = str(field_def.category_id)
        if field_def.placeholder:
            field.widget.attrs["placeholder"] = field_def.placeholder
        return field

    def _setup_category_fields(self, *, work_machine_only: bool) -> None:
        current_category_id = getattr(self.instance, "asset_category_id", None) or 0
        category_qs = AssetCategory.objects.filter(is_active=True)
        if work_machine_only:
            category_qs = category_qs.filter(base_asset_type=Asset.TYPE_WORK_MACHINE)
        else:
            category_qs = category_qs.exclude(base_asset_type=Asset.TYPE_WORK_MACHINE)

        category_ids = list(category_qs.values_list("id", flat=True))
        if current_category_id and current_category_id not in category_ids:
            category_ids.append(current_category_id)
        self.category_queryset = AssetCategory.objects.filter(pk__in=category_ids).order_by("sort_order", "label", "id")
        if "asset_category" in self.fields:
            self.fields["asset_category"].queryset = self.category_queryset
            self.fields["asset_category"].help_text = "Se selezioni una categoria, vengono caricati i campi dedicati."
        if "asset_type" in self.fields:
            self.fields["asset_type"].help_text = (
                "Famiglia tecnica usata dal sistema. Se scegli una categoria asset, questo valore viene allineato automaticamente."
            )

        raw_category_values = self._original_extra_columns.get(self.CATEGORY_STORAGE_KEY, {})
        self._original_category_values = dict(raw_category_values) if isinstance(raw_category_values, dict) else {}
        self.category_fields = list(
            AssetCategoryField.objects.select_related("category")
            .filter(
                Q(category_id__in=category_ids),
                Q(is_active=True),
                Q(show_in_form=True),
            )
            .order_by("category__sort_order", "category__label", "sort_order", "label", "id")
        )

        grouped_field_names: dict[int, list[str]] = defaultdict(list)
        self.category_dynamic_field_names: list[str] = []
        self.category_field_groups: list[dict[str, object]] = []

        for field_def in self.category_fields:
            field_name = self._category_field_form_name(field_def.code)
            self.fields[field_name] = self._build_category_form_field(field_def)
            self.initial[field_name] = self._category_value_from_extra(field_def)
            self.category_dynamic_field_names.append(field_name)
            grouped_field_names[field_def.category_id].append(field_name)

        for category in self.category_queryset:
            field_names = grouped_field_names.get(category.id, [])
            if not field_names:
                continue
            self.category_field_groups.append(
                {
                    "category": category,
                    "field_names": field_names,
                }
            )

    def _validate_category_fields(self, cleaned_data: dict) -> dict:
        selected_category = cleaned_data.get("asset_category")
        if not selected_category:
            return cleaned_data
        for field_def in self.category_fields:
            if field_def.category_id != selected_category.id:
                continue
            if not field_def.is_required or field_def.field_type == AssetCategoryField.TYPE_BOOL:
                continue
            value = cleaned_data.get(self._category_field_form_name(field_def.code))
            if value in (None, ""):
                self.add_error(
                    self._category_field_form_name(field_def.code),
                    "Compila questo campo per la categoria selezionata.",
                )
        return cleaned_data

    def _apply_category_values(self, next_extra: dict[str, object], cleaned_data: dict) -> dict[str, object]:
        category_values = dict(self._original_category_values)
        selected_category = cleaned_data.get("asset_category")
        if selected_category:
            for field_def in self.category_fields:
                if field_def.category_id != selected_category.id:
                    continue
                field_name = self._category_field_form_name(field_def.code)
                value = self._normalize_category_value(field_def, cleaned_data.get(field_name))
                if field_def.field_type == AssetCategoryField.TYPE_BOOL:
                    category_values[field_def.code] = bool(value)
                elif value not in ("", None):
                    category_values[field_def.code] = value
                else:
                    category_values.pop(field_def.code, None)
        if category_values:
            next_extra[self.CATEGORY_STORAGE_KEY] = category_values
        else:
            next_extra.pop(self.CATEGORY_STORAGE_KEY, None)
        return next_extra


class AssetForm(AssetCategoryFieldMixin, forms.ModelForm):
    asset_tag = forms.CharField(required=False)
    periodic_verification_ids = forms.ModelMultipleChoiceField(
        required=False,
        queryset=PeriodicVerification.objects.none(),
        label="Verifiche periodiche",
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )

    class Meta:
        model = Asset
        fields = [
            "asset_tag",
            "name",
            "asset_category",
            "asset_type",
            "reparto",
            "manufacturer",
            "model",
            "serial_number",
            "status",
            "sharepoint_folder_url",
            "sharepoint_folder_path",
            "assignment_to",
            "assignment_reparto",
            "assignment_location",
            "notes",
        ]
        labels = {
            "asset_tag": "Tag bene",
            "name": "Nome bene",
            "asset_category": "Categoria asset",
            "asset_type": "Tipo bene",
            "reparto": "Reparto",
            "manufacturer": "Produttore",
            "model": "Modello",
            "serial_number": "Numero seriale",
            "status": "Stato",
            "sharepoint_folder_url": "URL cartella SharePoint",
            "sharepoint_folder_path": "Percorso cartella SharePoint",
            "assignment_to": "Assegnato a",
            "assignment_reparto": "Reparto assegnazione",
            "assignment_location": "Posizione assegnazione",
            "notes": "Note",
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_asset_tag(self):
        return (self.cleaned_data.get("asset_tag") or "").strip()

    def clean_sharepoint_folder_url(self):
        value = (self.cleaned_data.get("sharepoint_folder_url") or "").strip()
        if value and "://" not in value and "sharepoint" in value.lower():
            value = f"https://{value.lstrip('/')}"
        return value[:1000]

    def clean_sharepoint_folder_path(self):
        value = (self.cleaned_data.get("sharepoint_folder_path") or "").strip().replace("\\", "/")
        while "//" in value:
            value = value.replace("//", "/")
        return value.strip("/")[:500]

    def _custom_field_form_name(self, code: str) -> str:
        return f"extra__{code}"

    def _custom_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "si", "s", "on"}
        return bool(value)

    def _custom_date(self, value) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            row = value.strip()
            if not row:
                return None
            for parser in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    return datetime.strptime(row, parser).date()
                except ValueError:
                    continue
        return None

    def _custom_value_from_extra(self, field_def: AssetCustomField):
        raw = self._original_extra_columns.get(field_def.code, None)
        if raw is None:
            raw = self._original_extra_columns.get(field_def.label, None)
        if field_def.field_type == AssetCustomField.TYPE_BOOL:
            return self._custom_bool(raw)
        if field_def.field_type == AssetCustomField.TYPE_DATE:
            return self._custom_date(raw)
        if field_def.field_type == AssetCustomField.TYPE_NUMBER:
            return "" if raw in (None, "") else str(raw)
        return "" if raw is None else str(raw)

    def _normalize_custom_value(self, field_def: AssetCustomField, value):
        if field_def.field_type == AssetCustomField.TYPE_BOOL:
            return bool(value)
        if field_def.field_type == AssetCustomField.TYPE_DATE:
            if isinstance(value, datetime):
                return value.date().isoformat()
            if isinstance(value, date):
                return value.isoformat()
            row = str(value or "").strip()
            return row
        if field_def.field_type == AssetCustomField.TYPE_NUMBER:
            if value in (None, ""):
                return ""
            return str(value).strip()
        return str(value or "").strip()[:500]

    def save(self, commit=True):
        instance: Asset = super().save(commit=False)
        next_extra: dict[str, object] = {}
        for key, value in self._original_extra_columns.items():
            keep_key = True
            for field_def in self.custom_fields:
                if key == field_def.code or key == field_def.label:
                    keep_key = False
                    break
            if keep_key:
                next_extra[key] = value

        for field_def in self.custom_fields:
            field_name = self._custom_field_form_name(field_def.code)
            value = self._normalize_custom_value(field_def, self.cleaned_data.get(field_name))
            if field_def.field_type == AssetCustomField.TYPE_BOOL:
                next_extra[field_def.code] = bool(value)
            elif value not in ("", None):
                next_extra[field_def.code] = value

        next_extra = self._apply_category_values(next_extra, self.cleaned_data)
        instance.extra_columns = next_extra
        if commit:
            instance.save()
            self.save_m2m()
            instance.periodic_verifications.set(self.cleaned_data.get("periodic_verification_ids") or [])
        return instance

    def __init__(self, *args, **kwargs):
        custom_fields = kwargs.pop("custom_fields", None)
        list_suggestions = kwargs.pop("list_suggestions", None) or {}
        super().__init__(*args, **kwargs)
        self.custom_fields = list(
            custom_fields
            if custom_fields is not None
            else AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id")
        )
        self.base_field_names = list(self.Meta.fields)
        self.dynamic_field_names: list[str] = []
        self.verification_field_names = ["periodic_verification_ids"]
        self._original_extra_columns = (
            dict(self.instance.extra_columns)
            if self.instance and self.instance.pk and isinstance(self.instance.extra_columns, dict)
            else {}
        )
        self._setup_category_fields(work_machine_only=False)
        self.fields["periodic_verification_ids"].queryset = PeriodicVerification.objects.order_by("name", "id")
        self.fields["periodic_verification_ids"].help_text = "Ogni asset puo appartenere a piu verifiche periodiche."
        if self.instance and self.instance.pk:
            self.initial["periodic_verification_ids"] = list(
                self.instance.periodic_verifications.order_by("name", "id").values_list("id", flat=True)
            )

        for field_def in self.custom_fields:
            field_name = self._custom_field_form_name(field_def.code)
            initial_value = self._custom_value_from_extra(field_def)
            if field_def.field_type == AssetCustomField.TYPE_NUMBER:
                self.fields[field_name] = forms.DecimalField(
                    required=False,
                    label=field_def.label,
                    max_digits=16,
                    decimal_places=2,
                )
            elif field_def.field_type == AssetCustomField.TYPE_DATE:
                self.fields[field_name] = forms.DateField(
                    required=False,
                    label=field_def.label,
                    input_formats=["%Y-%m-%d", "%d/%m/%Y"],
                    widget=forms.DateInput(attrs={"type": "date"}),
                )
            elif field_def.field_type == AssetCustomField.TYPE_BOOL:
                self.fields[field_name] = forms.BooleanField(required=False, label=field_def.label)
            else:
                self.fields[field_name] = forms.CharField(required=False, label=field_def.label, max_length=500)
            self.initial[field_name] = initial_value
            self.dynamic_field_names.append(field_name)

        self.list_suggestions = list_suggestions
        for field_name in [
            "reparto",
            "manufacturer",
            "model",
            "assignment_to",
            "assignment_reparto",
            "assignment_location",
        ]:
            suggestions = list_suggestions.get(field_name, [])
            if field_name in self.fields and suggestions:
                self.fields[field_name].widget.attrs["list"] = f"list_{field_name}"

        if "sharepoint_folder_url" in self.fields:
            self.fields["sharepoint_folder_url"].help_text = "Link completo alla cartella asset su SharePoint."
        if "sharepoint_folder_path" in self.fields:
            self.fields["sharepoint_folder_path"].help_text = "Percorso relativo usato per l'eventuale sync file."

        _attach_input_css(self)

    def clean(self):
        cleaned_data = super().clean()
        selected_category = cleaned_data.get("asset_category")
        if selected_category:
            if selected_category.base_asset_type == Asset.TYPE_WORK_MACHINE:
                self.add_error("asset_category", "Per questa categoria usa il form Macchine di lavoro.")
            else:
                cleaned_data["asset_type"] = selected_category.base_asset_type
        return self._validate_category_fields(cleaned_data)


class AssetAssignmentForm(forms.ModelForm):
    assigned_user_id = forms.ChoiceField(required=False, label="Dipendente")

    class Meta:
        model = Asset
        fields = ["assignment_to", "assignment_reparto", "assignment_location", "notes"]
        labels = {
            "assignment_to": "Assegnato a",
            "assignment_reparto": "Reparto assegnazione",
            "assignment_location": "Posizione assegnazione",
            "notes": "Note assegnazione",
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        user_choices = kwargs.pop("user_choices", None)
        selected_user_id = kwargs.pop("selected_user_id", None)
        list_suggestions = kwargs.pop("list_suggestions", None) or {}
        super().__init__(*args, **kwargs)
        choices = [("", "-- Nessun dipendente --")]
        if user_choices:
            choices.extend(user_choices)
        self.fields["assigned_user_id"].choices = choices
        if selected_user_id is not None:
            self.initial["assigned_user_id"] = str(selected_user_id or "")

        self.list_suggestions = list_suggestions
        for field_name in ["assignment_to", "assignment_reparto", "assignment_location"]:
            suggestions = list_suggestions.get(field_name, [])
            if field_name in self.fields and suggestions:
                self.fields[field_name].widget.attrs["list"] = f"list_{field_name}"
        _attach_input_css(self)


class AssetFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Ricerca")
    asset_type = forms.ChoiceField(
        required=False,
        label="Tipo",
        choices=[("", "Tutti i tipi"), *Asset.TYPE_CHOICES],
    )
    reparto = forms.CharField(required=False, label="Reparto")
    vlan = forms.IntegerField(required=False, label="VLAN", min_value=1)
    ip = forms.CharField(required=False, label="IP")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _attach_input_css(self)


class WorkMachineFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Ricerca")
    reparto = forms.CharField(required=False, label="Reparto")
    status = forms.ChoiceField(
        required=False,
        label="Stato",
        choices=[("", "Tutti gli stati"), *Asset.STATUS_CHOICES],
    )
    cnc_only = forms.BooleanField(required=False, label="Solo CNC")
    five_axes_only = forms.BooleanField(required=False, label="Solo 5 assi")
    tcr_only = forms.BooleanField(required=False, label="Solo TCR")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _attach_input_css(self)
        for field_name in ["cnc_only", "five_axes_only", "tcr_only"]:
            self.fields[field_name].widget.attrs["class"] = ""


class WorkMachineAssetForm(AssetCategoryFieldMixin, forms.ModelForm):
    asset_tag = forms.CharField(required=False, label="Tag bene")
    sharepoint_folder_url = forms.CharField(required=False, label="URL cartella SharePoint", max_length=1000)
    sharepoint_folder_path = forms.CharField(required=False, label="Percorso cartella SharePoint", max_length=500)
    x_mm = forms.IntegerField(required=False, min_value=0, label="Corsa X (mm)")
    y_mm = forms.IntegerField(required=False, min_value=0, label="Corsa Y (mm)")
    z_mm = forms.IntegerField(required=False, min_value=0, label="Corsa Z (mm)")
    diameter_mm = forms.IntegerField(required=False, min_value=0, label="Diametro (mm)")
    spindle_mm = forms.IntegerField(required=False, min_value=0, label="Mandrino (mm)")
    year = forms.IntegerField(required=False, min_value=1900, max_value=9999, label="Anno macchina")
    tmc = forms.IntegerField(required=False, min_value=0, label="TMC")
    tcr_enabled = forms.BooleanField(required=False, label="TCR attivo")
    pressure_bar = forms.DecimalField(required=False, min_value=0, max_digits=8, decimal_places=2, label="Pressione (bar)")
    cnc_controlled = forms.BooleanField(required=False, label="Controllo CNC")
    five_axes = forms.BooleanField(required=False, label="5 assi")
    accuracy_from = forms.CharField(required=False, max_length=120, label="Accuracy from")
    next_maintenance_date = forms.DateField(
        required=False,
        label="Prossima manutenzione",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    maintenance_reminder_days = forms.IntegerField(required=False, min_value=0, label="Soglia reminder (giorni)")
    documents_specs_payload = forms.CharField(required=False, widget=forms.HiddenInput())
    documents_manuals_payload = forms.CharField(required=False, widget=forms.HiddenInput())
    documents_interventions_payload = forms.CharField(required=False, widget=forms.HiddenInput())
    periodic_verification_ids = forms.ModelMultipleChoiceField(
        required=False,
        queryset=PeriodicVerification.objects.none(),
        label="Verifiche periodiche",
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )

    class Meta:
        model = Asset
        fields = [
            "asset_tag",
            "name",
            "asset_category",
            "reparto",
            "manufacturer",
            "model",
            "serial_number",
            "status",
            "sharepoint_folder_url",
            "sharepoint_folder_path",
            "assignment_to",
            "assignment_reparto",
            "assignment_location",
            "notes",
        ]
        labels = {
            "name": "Nome macchina",
            "asset_category": "Categoria macchina",
            "reparto": "Reparto",
            "manufacturer": "Produttore",
            "model": "Modello",
            "serial_number": "Numero seriale",
            "status": "Stato",
            "sharepoint_folder_url": "URL cartella SharePoint",
            "sharepoint_folder_path": "Percorso cartella SharePoint",
            "assignment_to": "Responsabile",
            "assignment_reparto": "Reparto assegnazione",
            "assignment_location": "Posizione",
            "notes": "Note",
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    asset_field_names = [
        "asset_tag",
        "name",
        "asset_category",
        "reparto",
        "manufacturer",
        "model",
        "serial_number",
        "status",
    ]
    sharepoint_field_names = [
        "sharepoint_folder_url",
        "sharepoint_folder_path",
    ]
    machine_field_names = [
        "x_mm",
        "y_mm",
        "z_mm",
        "diameter_mm",
        "spindle_mm",
        "year",
        "tmc",
        "pressure_bar",
        "accuracy_from",
        "next_maintenance_date",
        "maintenance_reminder_days",
        "tcr_enabled",
        "cnc_controlled",
        "five_axes",
    ]
    assignment_field_names = [
        "assignment_to",
        "assignment_reparto",
        "assignment_location",
        "notes",
    ]
    verification_field_names = [
        "periodic_verification_ids",
    ]
    document_field_names = [
        "documents_specs_payload",
        "documents_manuals_payload",
        "documents_interventions_payload",
    ]
    document_field_map = {
        "documents_specs_payload": ("SPECIFICHE", "Specifiche"),
        "documents_manuals_payload": ("MANUALI", "Manuali"),
        "documents_interventions_payload": ("INTERVENTI", "Interventi"),
    }

    def clean_asset_tag(self):
        return (self.cleaned_data.get("asset_tag") or "").strip()

    def clean_sharepoint_folder_url(self):
        value = (self.cleaned_data.get("sharepoint_folder_url") or "").strip()
        if value and "://" not in value and "sharepoint" in value.lower():
            value = f"https://{value.lstrip('/')}"
        return value[:1000]

    def clean_sharepoint_folder_path(self):
        value = (self.cleaned_data.get("sharepoint_folder_path") or "").strip().replace("\\", "/")
        while "//" in value:
            value = value.replace("//", "/")
        return value.strip("/")[:500]

    def _ensure_manual_source_key(self) -> str:
        if self.instance and self.instance.pk:
            related = getattr(self.instance, "work_machine", None)
            source_key = (self.instance.source_key or getattr(related, "source_key", "")).strip()
            if source_key:
                return source_key
        return f"manual-wm-{uuid4().hex[:24]}"

    def _documents_from_extra(self, category: str) -> str:
        raw_docs = self._original_extra_columns.get("documents")
        if not isinstance(raw_docs, list):
            return "[]"
        rows = []
        for row in raw_docs:
            if not isinstance(row, dict):
                continue
            if (row.get("category") or "SPECIFICHE").upper() != category:
                continue
            rows.append(
                {
                    "name": str(row.get("name") or row.get("filename") or "").strip(),
                    "url": str(row.get("url") or "").strip(),
                    "date": str(row.get("date") or "").strip(),
                    "size": str(row.get("size") or "").strip(),
                }
            )
        return json.dumps(rows, ensure_ascii=False)

    def _parse_document_payload(self, value, category: str) -> list[dict[str, str]]:
        if not value:
            return []
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise forms.ValidationError("Formato documenti non valido.")
        if not isinstance(payload, list):
            raise forms.ValidationError("Formato documenti non valido.")

        documents = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            url = str(row.get("url") or "").strip()
            date_value = str(row.get("date") or "").strip()
            size_value = str(row.get("size") or "").strip()
            if not any([name, url, date_value, size_value]):
                continue
            documents.append(
                {
                    "name": name or url or "Documento",
                    "url": url,
                    "date": date_value,
                    "size": size_value,
                    "category": category,
                }
            )
        return documents

    def __init__(self, *args, **kwargs):
        list_suggestions = kwargs.pop("list_suggestions", None) or {}
        work_machine = kwargs.pop("work_machine", None)
        super().__init__(*args, **kwargs)
        self.list_suggestions = list_suggestions
        self.work_machine = work_machine or getattr(self.instance, "work_machine", None)
        self._original_extra_columns = (
            dict(self.instance.extra_columns)
            if self.instance and self.instance.pk and isinstance(self.instance.extra_columns, dict)
            else {}
        )
        self._setup_category_fields(work_machine_only=True)

        if self.work_machine:
            for field_name in self.machine_field_names:
                self.initial.setdefault(field_name, getattr(self.work_machine, field_name, None))
        else:
            self.initial.setdefault("maintenance_reminder_days", 30)
        for field_name, meta in self.document_field_map.items():
            self.initial.setdefault(field_name, self._documents_from_extra(meta[0]))

        for field_name in [
            "reparto",
            "manufacturer",
            "model",
            "assignment_to",
            "assignment_reparto",
            "assignment_location",
        ]:
            suggestions = list_suggestions.get(field_name, [])
            if field_name in self.fields and suggestions:
                self.fields[field_name].widget.attrs["list"] = f"list_{field_name}"

        self.fields["sharepoint_folder_url"].help_text = "Link completo alla cartella macchina su SharePoint."
        self.fields["sharepoint_folder_path"].help_text = "Percorso relativo per sync file, es. Macchine/CN5/ML-000001."
        self.fields["periodic_verification_ids"].queryset = PeriodicVerification.objects.order_by("name", "id")
        self.fields["periodic_verification_ids"].help_text = "Collega la macchina a una o piu verifiche periodiche."
        if self.instance and self.instance.pk:
            self.initial["periodic_verification_ids"] = list(
                self.instance.periodic_verifications.order_by("name", "id").values_list("id", flat=True)
            )

        _attach_input_css(self)
        for field_name in ["tcr_enabled", "cnc_controlled", "five_axes"]:
            self.fields[field_name].widget.attrs["class"] = ""

    def clean_maintenance_reminder_days(self):
        value = self.cleaned_data.get("maintenance_reminder_days")
        if value in (None, ""):
            return 30
        return int(value)

    def clean(self):
        cleaned_data = super().clean()
        selected_category = cleaned_data.get("asset_category")
        if selected_category and selected_category.base_asset_type != Asset.TYPE_WORK_MACHINE:
            self.add_error("asset_category", "Questa categoria non appartiene alle macchine di lavoro.")
        for field_name, meta in self.document_field_map.items():
            category = meta[0]
            cleaned_data[field_name] = json.dumps(
                self._parse_document_payload(cleaned_data.get(field_name), category),
                ensure_ascii=False,
            )
        return self._validate_category_fields(cleaned_data)

    @transaction.atomic
    def save(self, commit: bool = True):
        asset: Asset = super().save(commit=False)
        asset.asset_type = Asset.TYPE_WORK_MACHINE

        source_key = (asset.source_key or getattr(self.work_machine, "source_key", "")).strip()
        if not source_key:
            source_key = self._ensure_manual_source_key()
        asset.source_key = source_key
        next_extra = dict(self._original_extra_columns)
        documents = []
        for field_name, meta in self.document_field_map.items():
            documents.extend(self._parse_document_payload(self.cleaned_data.get(field_name), meta[0]))
        if documents:
            next_extra["documents"] = documents
        else:
            next_extra.pop("documents", None)
        next_extra = self._apply_category_values(next_extra, self.cleaned_data)
        asset.extra_columns = next_extra

        if not commit:
            return asset

        asset.save()

        machine = self.work_machine or getattr(asset, "work_machine", None)
        if machine is None:
            machine = WorkMachine(asset=asset)
        machine.source_key = source_key
        for field_name in self.machine_field_names:
            setattr(machine, field_name, self.cleaned_data.get(field_name))
        machine.save()
        asset.periodic_verifications.set(self.cleaned_data.get("periodic_verification_ids") or [])

        self.instance = asset
        self.work_machine = machine
        return asset


class PeriodicVerificationForm(forms.ModelForm):
    asset_ids = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Asset.objects.none(),
        label="Asset coinvolti",
        widget=forms.SelectMultiple(attrs={"size": 7, "data-pv-asset-select": "1"}),
    )

    class Meta:
        model = PeriodicVerification
        fields = [
            "name",
            "supplier",
            "frequency_months",
            "last_verification_date",
            "next_verification_date",
            "is_active",
            "notes",
        ]
        labels = {
            "name": "Nome verifica",
            "supplier": "Azienda fornitore",
            "frequency_months": "Cadenza (mesi)",
            "last_verification_date": "Ultima verifica",
            "next_verification_date": "Prossima verifica",
            "is_active": "Verifica attiva",
            "notes": "Note",
        }
        widgets = {
            "last_verification_date": forms.DateInput(attrs={"type": "date"}),
            "next_verification_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        actor = kwargs.pop("actor", None)
        preselected_asset_id = kwargs.pop("preselected_asset_id", 0)
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields["asset_ids"].queryset = Asset.objects.order_by("reparto", "name", "asset_tag")
        self.fields["frequency_months"].help_text = "Esempi: 1, 2, 3, 6, 12."
        self.fields["asset_ids"].help_text = "Puoi collegare piu asset alla stessa verifica."
        self.fields["asset_ids"].widget.attrs["data-pv-asset-select"] = "1"
        if self.instance and self.instance.pk:
            self.initial["asset_ids"] = list(self.instance.assets.order_by("reparto", "name", "asset_tag").values_list("id", flat=True))
        elif preselected_asset_id:
            self.initial["asset_ids"] = [int(preselected_asset_id)]
        _attach_input_css(self)
        self.fields["is_active"].widget.attrs["class"] = ""

    def clean_frequency_months(self):
        value = int(self.cleaned_data.get("frequency_months") or 0)
        if value <= 0:
            raise forms.ValidationError("Inserisci una cadenza in mesi maggiore di zero.")
        return value

    @transaction.atomic
    def save(self, commit=True):
        instance: PeriodicVerification = super().save(commit=False)
        if not instance.pk and getattr(self.actor, "is_authenticated", False):
            instance.created_by = self.actor
        if not instance.next_verification_date and instance.last_verification_date and instance.frequency_months:
            from .models import _add_months

            instance.next_verification_date = _add_months(instance.last_verification_date, instance.frequency_months)
        if commit:
            instance.save()
            instance.assets.set(self.cleaned_data.get("asset_ids") or [])
        return instance


class PlantLayoutForm(forms.ModelForm):
    areas_payload = forms.CharField(required=False, widget=forms.HiddenInput())
    markers_payload = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = PlantLayout
        fields = ["category", "name", "description", "image", "is_active"]
        labels = {
            "category": "Categoria mappa",
            "name": "Nome planimetria",
            "description": "Descrizione",
            "image": "Immagine PNG/JPG",
            "is_active": "Usa come mappa attiva",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].help_text = "Esempi: Officina, TVCC, Sistema allarme."
        self.fields["image"].widget.attrs["accept"] = ".png,.jpg,.jpeg"
        self.fields["image"].help_text = "Carica una planimetria in PNG o JPG."
        self.fields["description"].help_text = "Nota interna facoltativa per capire versione o piano."
        self.fields["is_active"].widget.attrs["class"] = ""
        _attach_input_css(self)
        self.area_rows_input: list[dict[str, object]] = []
        self.marker_rows_input: list[dict[str, object]] = []

    def _normalize_hex(self, value: str | None, *, fallback: str = "#2563EB") -> str:
        row = str(value or "").strip().upper()
        if HEX_COLOR_RE.match(row):
            return row
        return fallback

    def _parse_json_list(self, raw_value, *, label: str) -> list[dict]:
        if not raw_value:
            return []
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise forms.ValidationError(f"{label}: formato non valido.")
        if not isinstance(payload, list):
            raise forms.ValidationError(f"{label}: formato non valido.")
        rows: list[dict] = []
        for row in payload:
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _to_int(self, value, *, default: int = 0) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError, AttributeError):
            return default

    def _to_percent(self, value, *, label: str, minimum: float = 0.0, maximum: float = 100.0) -> float:
        try:
            number = round(float(value), 2)
        except (TypeError, ValueError):
            raise forms.ValidationError(f"{label}: coordinata non valida.")
        if number < minimum or number > maximum:
            raise forms.ValidationError(f"{label}: il valore deve essere compreso tra {minimum:g} e {maximum:g}.")
        return number

    def clean_image(self):
        upload = self.cleaned_data.get("image")
        if upload:
            ext = Path(getattr(upload, "name", "") or "").suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg"}:
                raise forms.ValidationError("Carica una planimetria PNG o JPG.")
            size = int(getattr(upload, "size", 0) or 0)
            if size > 10 * 1024 * 1024:
                raise forms.ValidationError("La planimetria non puo superare 10 MB.")
            return upload
        if self.instance and self.instance.pk and self.instance.image:
            return self.instance.image
        raise forms.ValidationError("Carica una planimetria PNG o JPG.")

    def clean(self):
        cleaned_data = super().clean()
        area_rows = []
        marker_rows = []
        raw_area_rows = self._parse_json_list(cleaned_data.get("areas_payload"), label="Reparti")
        raw_marker_rows = self._parse_json_list(cleaned_data.get("markers_payload"), label="Marker")

        existing_area_ids = set()
        existing_marker_ids = set()
        machine_assets = {
            asset.id: asset
            for asset in Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE).only(
                "id",
                "name",
                "asset_tag",
                "reparto",
                "status",
            )
        }
        placed_asset_ids = set()

        for index, row in enumerate(raw_area_rows, start=1):
            area_id = self._to_int(row.get("id"))
            if area_id:
                if area_id in existing_area_ids:
                    raise forms.ValidationError("Reparti duplicati nel payload editor.")
                existing_area_ids.add(area_id)
            x = self._to_percent(row.get("x_percent"), label=f"Reparto {index} - X")
            y = self._to_percent(row.get("y_percent"), label=f"Reparto {index} - Y")
            width = self._to_percent(row.get("width_percent"), label=f"Reparto {index} - larghezza", minimum=0.5)
            height = self._to_percent(row.get("height_percent"), label=f"Reparto {index} - altezza", minimum=0.5)
            if x + width > 100.0:
                width = round(100.0 - x, 2)
            if y + height > 100.0:
                height = round(100.0 - y, 2)
            if width <= 0 or height <= 0:
                raise forms.ValidationError(f"Reparto {index}: area fuori dai limiti della planimetria.")
            area_rows.append(
                {
                    "id": area_id or None,
                    "name": str(row.get("name") or "").strip()[:120] or f"Reparto {index}",
                    "reparto_code": str(row.get("reparto_code") or "").strip()[:120],
                    "color": self._normalize_hex(row.get("color")),
                    "notes": str(row.get("notes") or "").strip()[:255],
                    "x_percent": x,
                    "y_percent": y,
                    "width_percent": width,
                    "height_percent": height,
                    "sort_order": self._to_int(row.get("sort_order"), default=index * 10),
                }
            )

        for index, row in enumerate(raw_marker_rows, start=1):
            marker_id = self._to_int(row.get("id"))
            if marker_id:
                if marker_id in existing_marker_ids:
                    raise forms.ValidationError("Marker duplicati nel payload editor.")
                existing_marker_ids.add(marker_id)
            asset_id = self._to_int(row.get("asset_id"))
            if asset_id not in machine_assets:
                raise forms.ValidationError(f"Marker {index}: macchina non valida.")
            if asset_id in placed_asset_ids:
                raise forms.ValidationError("Ogni macchina puo comparire una sola volta sulla planimetria.")
            placed_asset_ids.add(asset_id)
            marker_rows.append(
                {
                    "id": marker_id or None,
                    "asset_id": asset_id,
                    "label": str(row.get("label") or "").strip()[:120],
                    "x_percent": self._to_percent(row.get("x_percent"), label=f"Marker {index} - X"),
                    "y_percent": self._to_percent(row.get("y_percent"), label=f"Marker {index} - Y"),
                    "sort_order": self._to_int(row.get("sort_order"), default=index * 10),
                }
            )

        cleaned_data["area_rows"] = area_rows
        cleaned_data["marker_rows"] = marker_rows
        self.area_rows_input = area_rows
        self.marker_rows_input = marker_rows
        return cleaned_data

    @transaction.atomic
    def save(self, commit: bool = True):
        layout: PlantLayout = super().save(commit=commit)
        if not commit:
            return layout

        existing_areas = {row.id: row for row in PlantLayoutArea.objects.filter(layout=layout)}
        keep_area_ids: list[int] = []
        for index, row in enumerate(self.cleaned_data.get("area_rows", []), start=1):
            area = existing_areas.get(row["id"]) if row.get("id") else PlantLayoutArea(layout=layout)
            area.name = row["name"]
            area.reparto_code = row["reparto_code"]
            area.color = row["color"]
            area.notes = row["notes"]
            area.x_percent = row["x_percent"]
            area.y_percent = row["y_percent"]
            area.width_percent = row["width_percent"]
            area.height_percent = row["height_percent"]
            area.sort_order = row["sort_order"] or index * 10
            area.save()
            keep_area_ids.append(area.id)
        area_qs = PlantLayoutArea.objects.filter(layout=layout)
        if keep_area_ids:
            area_qs.exclude(id__in=keep_area_ids).delete()
        else:
            area_qs.delete()

        existing_markers = {row.id: row for row in PlantLayoutMarker.objects.filter(layout=layout)}
        keep_marker_ids: list[int] = []
        for index, row in enumerate(self.cleaned_data.get("marker_rows", []), start=1):
            marker = existing_markers.get(row["id"]) if row.get("id") else PlantLayoutMarker(layout=layout)
            marker.asset_id = row["asset_id"]
            marker.label = row["label"]
            marker.x_percent = row["x_percent"]
            marker.y_percent = row["y_percent"]
            marker.sort_order = row["sort_order"] or index * 10
            marker.is_visible = True
            marker.save()
            keep_marker_ids.append(marker.id)
        marker_qs = PlantLayoutMarker.objects.filter(layout=layout)
        if keep_marker_ids:
            marker_qs.exclude(id__in=keep_marker_ids).delete()
        else:
            marker_qs.delete()

        return layout


class AssetLabelTemplateForm(forms.ModelForm):
    body_fields_payload = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = AssetLabelTemplate
        fields = [
            "name",
            "page_width_mm",
            "page_height_mm",
            "qr_size_mm",
            "qr_position",
            "show_logo",
            "logo_file",
            "logo_height_mm",
            "logo_alignment",
            "title_font_size_pt",
            "body_font_size_pt",
            "show_border",
            "border_radius_mm",
            "show_field_labels",
            "show_target_label",
            "show_help_text",
            "show_target_url",
            "background_color",
            "border_color",
            "text_color",
            "accent_color",
            "title_primary_field",
            "title_secondary_field",
        ]
        labels = {
            "name": "Nome template",
            "page_width_mm": "Larghezza etichetta (mm)",
            "page_height_mm": "Altezza etichetta (mm)",
            "qr_size_mm": "Dimensione QR (mm)",
            "qr_position": "Posizione QR",
            "show_logo": "Mostra logo",
            "logo_file": "Logo personalizzato",
            "logo_height_mm": "Altezza logo (mm)",
            "logo_alignment": "Allineamento logo",
            "title_font_size_pt": "Font titolo (pt)",
            "body_font_size_pt": "Font contenuto (pt)",
            "show_border": "Mostra bordo",
            "border_radius_mm": "Raggio bordo (mm)",
            "show_field_labels": "Mostra etichette campo",
            "show_target_label": "Mostra target QR",
            "show_help_text": "Mostra testo guida",
            "show_target_url": "Mostra URL/Percorso target",
            "background_color": "Sfondo",
            "border_color": "Colore bordo",
            "text_color": "Colore testo",
            "accent_color": "Colore evidenza",
            "title_primary_field": "Titolo principale",
            "title_secondary_field": "Titolo secondario",
        }

    def __init__(self, *args, **kwargs):
        field_choices = kwargs.pop("field_choices", None) or []
        super().__init__(*args, **kwargs)
        self.field_choices = [choice for choice in field_choices if choice and choice[0]]
        title_choices = [("", "-- Nessuno --"), *self.field_choices]
        self.fields["title_primary_field"].choices = self.field_choices
        self.fields["title_secondary_field"].choices = title_choices
        selected_body_fields = list(getattr(self.instance, "body_fields", None) or [])
        if not selected_body_fields:
            selected_body_fields = ["asset_type", "reparto", "serial_number"]
        self.initial.setdefault("body_fields_payload", json.dumps(selected_body_fields, ensure_ascii=False))

        for field_name in ["background_color", "border_color", "text_color", "accent_color"]:
            self.fields[field_name].widget = forms.TextInput(attrs={"type": "color"})
        for field_name in [
            "show_logo",
            "show_border",
            "show_field_labels",
            "show_target_label",
            "show_help_text",
            "show_target_url",
        ]:
            self.fields[field_name].widget.attrs["class"] = ""
        self.fields["logo_file"].widget.attrs["accept"] = ".png,.jpg,.jpeg"
        self.fields["name"].help_text = "Template usato per il PDF QR stampabile."
        self.fields["title_secondary_field"].help_text = "Puoi lasciarlo vuoto per avere un solo titolo."
        self.fields["logo_file"].help_text = "Se non carichi nulla viene usato il logo aziendale predefinito."
        _attach_input_css(self)

    def _valid_field_keys(self) -> set[str]:
        return {key for key, _label in self.field_choices}

    def _clean_hex(self, value: str, *, fallback: str) -> str:
        row = (value or "").strip()
        if len(row) == 7 and row.startswith("#"):
            digits = row[1:]
            if all(ch in "0123456789abcdefABCDEF" for ch in digits):
                return row.upper()
        return fallback

    def clean_title_primary_field(self):
        value = (self.cleaned_data.get("title_primary_field") or "").strip()
        if value not in self._valid_field_keys():
            raise forms.ValidationError("Seleziona un campo valido per il titolo principale.")
        return value

    def clean_title_secondary_field(self):
        value = (self.cleaned_data.get("title_secondary_field") or "").strip()
        if value and value not in self._valid_field_keys():
            raise forms.ValidationError("Seleziona un campo valido per il titolo secondario.")
        return value

    def clean_background_color(self):
        return self._clean_hex(self.cleaned_data.get("background_color"), fallback="#FFFFFF")

    def clean_border_color(self):
        return self._clean_hex(self.cleaned_data.get("border_color"), fallback="#111827")

    def clean_text_color(self):
        return self._clean_hex(self.cleaned_data.get("text_color"), fallback="#0F172A")

    def clean_accent_color(self):
        return self._clean_hex(self.cleaned_data.get("accent_color"), fallback="#1D4ED8")

    def clean_logo_file(self):
        upload = self.cleaned_data.get("logo_file")
        if not upload:
            return upload
        ext = Path(getattr(upload, "name", "") or "").suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg"}:
            raise forms.ValidationError("Carica un file PNG o JPG.")
        size = int(getattr(upload, "size", 0) or 0)
        if size > 2 * 1024 * 1024:
            raise forms.ValidationError("Il logo non puo superare 2 MB.")
        return upload

    def clean(self):
        cleaned_data = super().clean()
        raw_payload = cleaned_data.get("body_fields_payload")
        body_fields: list[str] = []
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                raise forms.ValidationError("Selezione campi etichetta non valida.")
            if not isinstance(payload, list):
                raise forms.ValidationError("Selezione campi etichetta non valida.")
            valid_keys = self._valid_field_keys()
            for row in payload:
                key = str(row or "").strip()
                if key and key in valid_keys and key not in body_fields:
                    body_fields.append(key)
        cleaned_data["body_fields"] = body_fields
        return cleaned_data

    def save(self, commit=True):
        instance: AssetLabelTemplate = super().save(commit=False)
        instance.body_fields = self.cleaned_data.get("body_fields", [])
        if commit:
            instance.save()
        return instance


class WorkOrderForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = [
            "periodic_verification",
            "supplier",
            "kind",
            "status",
            "title",
            "description",
            "resolution",
            "downtime_minutes",
            "cost_eur",
        ]
        labels = {
            "periodic_verification": "Intervento programmato",
            "supplier": "Fornitore",
            "kind": "Tipo intervento",
            "status": "Stato",
            "title": "Titolo",
            "description": "Descrizione",
            "resolution": "Risoluzione",
            "downtime_minutes": "Fermo impianto (minuti)",
            "cost_eur": "Costo (EUR)",
        }
        widgets = {
            "periodic_verification": forms.Select(),
            "supplier": forms.Select(),
            "description": forms.Textarea(attrs={"rows": 4}),
            "resolution": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.asset = kwargs.pop("asset", None)
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Fornitore.objects.filter(is_active=True).order_by("ragione_sociale", "id")
        self.fields["supplier"].required = False
        self.fields["supplier"].help_text = "Se l'intervento e programmato il fornitore viene proposto automaticamente."
        verification_field = self.fields["periodic_verification"]
        verification_field.required = False
        verification_field.help_text = "Seleziona la verifica periodica collegata per proporre il fornitore."
        verification_qs = PeriodicVerification.objects.none()
        if self.asset is not None:
            verification_qs = (
                self.asset.periodic_verifications.filter(is_active=True)
                .select_related("supplier")
                .order_by("name", "id")
            )
        verification_field.queryset = verification_qs
        if self.asset is not None and not self.is_bound:
            verifications = list(verification_qs)
            if len(verifications) == 1:
                verification = verifications[0]
                self.initial.setdefault("periodic_verification", verification.pk)
                if verification.supplier_id:
                    self.initial.setdefault("supplier", verification.supplier_id)
        _attach_input_css(self)

    def clean(self):
        cleaned_data = super().clean()
        verification = cleaned_data.get("periodic_verification")
        supplier = cleaned_data.get("supplier")
        if verification is not None and self.asset is not None:
            if not verification.assets.filter(pk=self.asset.pk).exists():
                self.add_error("periodic_verification", "La verifica selezionata non appartiene a questo asset.")
            if supplier is None and verification.supplier_id:
                cleaned_data["supplier"] = verification.supplier
        return cleaned_data


class WorkOrderCloseForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            (WorkOrder.STATUS_DONE, "Chiusa"),
            (WorkOrder.STATUS_CANCELED, "Annullata"),
        ],
        initial=WorkOrder.STATUS_DONE,
        label="Stato finale",
    )
    resolution = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}), label="Risoluzione")
    downtime_minutes = forms.IntegerField(required=False, min_value=0, label="Fermo impianto (minuti)")
    cost_eur = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label="Costo (EUR)")
    log_note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Nota di chiusura")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _attach_input_css(self)
