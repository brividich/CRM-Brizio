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

from anagrafica.models import Fornitore, FornitoreDocumento

from .maintenance import build_workorder_prefill_payload, get_applicable_assistance_contracts, resolve_asset_maintenance_rules
from .models import (
    Asset,
    AssetAdministrativeDeadline,
    AssetCategory,
    AssetCategoryField,
    AssetComponent,
    AssetCustomField,
    AssetLabelTemplate,
    AssistanceContract,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
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


class AssetComponentForm(forms.ModelForm):
    class Meta:
        model = AssetComponent
        fields = [
            "asset",
            "code",
            "name",
            "component_type",
            "serial_number",
            "manufacturer",
            "model",
            "installed_on",
            "notes",
            "is_active",
        ]
        labels = {
            "asset": "Asset",
            "code": "Codice componente",
            "name": "Nome componente",
            "component_type": "Tipo componente",
            "serial_number": "Numero seriale",
            "manufacturer": "Produttore",
            "model": "Modello",
            "installed_on": "Installato il",
            "notes": "Note",
            "is_active": "Attivo",
        }
        widgets = {
            "installed_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        locked_asset = kwargs.pop("locked_asset", None)
        asset_queryset = kwargs.pop("asset_queryset", None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and locked_asset is None:
            locked_asset = self.instance.asset
        self.locked_asset = locked_asset
        self.fields["asset"].queryset = asset_queryset or Asset.objects.order_by("name", "asset_tag", "id")
        self.fields["asset"].help_text = "Asset proprietario del componente."
        if self.locked_asset is not None:
            self.fields["asset"].queryset = Asset.objects.filter(pk=self.locked_asset.pk)
            self.fields["asset"].required = False
            self.initial["asset"] = self.locked_asset.pk
            self.fields["asset"].widget = forms.HiddenInput()
        _attach_input_css(self)
        if isinstance(self.fields["asset"].widget, forms.HiddenInput):
            self.fields["asset"].widget.attrs.pop("class", None)

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip()

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip()

    def clean_component_type(self):
        return (self.cleaned_data.get("component_type") or "").strip()

    def clean_serial_number(self):
        return (self.cleaned_data.get("serial_number") or "").strip()

    def clean_manufacturer(self):
        return (self.cleaned_data.get("manufacturer") or "").strip()

    def clean_model(self):
        return (self.cleaned_data.get("model") or "").strip()

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        asset = self.locked_asset or cleaned_data.get("asset")
        code = (cleaned_data.get("code") or "").strip()
        if self.locked_asset is not None:
            cleaned_data["asset"] = self.locked_asset
        if asset and code:
            duplicate_qs = AssetComponent.objects.filter(asset=asset, code__iexact=code)
            if self.instance.pk:
                duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
            if duplicate_qs.exists():
                self.add_error("code", "Esiste gia un componente con questo codice per l'asset selezionato.")
        return cleaned_data


class AssetAdministrativeDeadlineForm(forms.ModelForm):
    class Meta:
        model = AssetAdministrativeDeadline
        fields = [
            "asset",
            "component",
            "deadline_type",
            "title",
            "reference_code",
            "issuer",
            "issued_on",
            "due_date",
            "warning_days",
            "notes",
            "is_active",
        ]
        labels = {
            "asset": "Asset",
            "component": "Componente",
            "deadline_type": "Tipo scadenza",
            "title": "Titolo",
            "reference_code": "Riferimento",
            "issuer": "Ente / Emittente",
            "issued_on": "Data emissione",
            "due_date": "Data scadenza",
            "warning_days": "Preavviso (giorni)",
            "notes": "Note",
            "is_active": "Attiva",
        }
        widgets = {
            "issued_on": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        locked_asset = kwargs.pop("locked_asset", None)
        asset_queryset = kwargs.pop("asset_queryset", None)
        preselected_component = kwargs.pop("preselected_component", None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and locked_asset is None:
            locked_asset = self.instance.asset
        self.locked_asset = locked_asset
        self.preselected_component = preselected_component

        self.fields["asset"].queryset = asset_queryset or Asset.objects.order_by("name", "asset_tag", "id")
        self.fields["asset"].help_text = "L'asset a cui appartiene la scadenza."
        self.fields["component"].required = False
        self.fields["component"].help_text = "Opzionale: collega la scadenza a un componente dello stesso asset."
        self.fields["warning_days"].help_text = "Numero di giorni usato per evidenziare le scadenze imminenti."

        selected_asset_id = None
        selected_component_id = None
        if self.locked_asset is not None:
            selected_asset_id = self.locked_asset.pk
            self.fields["asset"].queryset = Asset.objects.filter(pk=self.locked_asset.pk)
            self.fields["asset"].required = False
            self.initial["asset"] = self.locked_asset.pk
            self.fields["asset"].widget = forms.HiddenInput()
        elif self.is_bound:
            selected_asset_id = self.data.get(self.add_prefix("asset")) or self.data.get("asset")
        elif self.instance and self.instance.pk:
            selected_asset_id = self.instance.asset_id
        else:
            selected_asset_id = self.initial.get("asset") or getattr(preselected_component, "asset_id", None)

        if self.is_bound:
            selected_component_id = self.data.get(self.add_prefix("component")) or self.data.get("component")
        elif self.instance and self.instance.pk:
            selected_component_id = self.instance.component_id
        elif preselected_component is not None:
            selected_component_id = preselected_component.pk

        component_qs = AssetComponent.objects.none()
        if selected_asset_id:
            component_filter = Q(asset_id=selected_asset_id)
            if selected_component_id:
                component_filter |= Q(pk=selected_component_id)
            component_qs = AssetComponent.objects.filter(component_filter).order_by("-is_active", "name", "code", "id")
        elif selected_component_id:
            component_qs = AssetComponent.objects.filter(pk=selected_component_id).order_by("-is_active", "name", "code", "id")
        self.fields["component"].queryset = component_qs

        if preselected_component is not None and not self.is_bound and not self.instance.pk:
            self.initial.setdefault("component", preselected_component.pk)
            self.initial.setdefault("asset", preselected_component.asset_id)

        _attach_input_css(self)
        if isinstance(self.fields["asset"].widget, forms.HiddenInput):
            self.fields["asset"].widget.attrs.pop("class", None)

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()

    def clean_reference_code(self):
        return (self.cleaned_data.get("reference_code") or "").strip()

    def clean_issuer(self):
        return (self.cleaned_data.get("issuer") or "").strip()

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean_warning_days(self):
        value = self.cleaned_data.get("warning_days")
        if value in (None, ""):
            return 30
        return int(value)

    def clean(self):
        cleaned_data = super().clean()
        asset = self.locked_asset or cleaned_data.get("asset")
        component = cleaned_data.get("component")
        if self.locked_asset is not None:
            cleaned_data["asset"] = self.locked_asset
        if asset is not None and component is not None and component.asset_id != asset.id:
            self.add_error("component", "Il componente selezionato non appartiene all'asset indicato.")
        return cleaned_data


class MaintenanceInterventionTemplateForm(forms.ModelForm):
    class Meta:
        model = MaintenanceInterventionTemplate
        fields = [
            "code",
            "label",
            "description",
            "asset_category",
            "sort_order",
            "is_active",
        ]
        labels = {
            "code": "Codice",
            "label": "Nome template",
            "description": "Descrizione",
            "asset_category": "Categoria asset",
            "sort_order": "Ordine",
            "is_active": "Attivo",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_category_id = getattr(self.instance, "asset_category_id", None)
        category_qs = AssetCategory.objects.filter(Q(is_active=True) | Q(pk=current_category_id)).order_by(
            "sort_order",
            "label",
            "id",
        )
        self.fields["asset_category"].required = False
        self.fields["asset_category"].queryset = category_qs
        self.fields["asset_category"].help_text = "Lascia vuoto per un template generale riutilizzabile su piu categorie."
        self.fields["description"].help_text = "Descrizione standard del tipo di intervento manutentivo."
        _attach_input_css(self)

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip()

    def clean_label(self):
        return (self.cleaned_data.get("label") or "").strip()

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()


class MaintenanceRuleForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRule
        fields = [
            "intervention_template",
            "asset_category",
            "threshold_type",
            "threshold_value",
            "warning_days",
            "sort_order",
            "is_active",
            "notes",
        ]
        labels = {
            "intervention_template": "Template intervento",
            "asset_category": "Categoria asset",
            "threshold_type": "Tipo soglia",
            "threshold_value": "Valore soglia",
            "warning_days": "Warning (giorni)",
            "sort_order": "Ordine",
            "is_active": "Attiva",
            "notes": "Note",
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_category_id = getattr(self.instance, "asset_category_id", None)
        selected_category_id = None
        if self.is_bound:
            selected_category_id = self.data.get(self.add_prefix("asset_category")) or self.data.get("asset_category")
        elif current_category_id:
            selected_category_id = current_category_id
        else:
            selected_category_id = self.initial.get("asset_category")

        current_template_id = getattr(self.instance, "intervention_template_id", None)

        category_qs = AssetCategory.objects.filter(Q(is_active=True) | Q(pk=current_category_id)).order_by(
            "sort_order",
            "label",
            "id",
        )
        template_filter = Q(is_active=True)
        if selected_category_id:
            template_filter &= Q(asset_category__isnull=True) | Q(asset_category_id=selected_category_id)
        if current_template_id:
            template_filter |= Q(pk=current_template_id)
        template_qs = MaintenanceInterventionTemplate.objects.filter(template_filter).order_by(
            "sort_order",
            "label",
            "id",
        )

        self.fields["asset_category"].queryset = category_qs
        self.fields["intervention_template"].queryset = template_qs
        self.fields["warning_days"].required = False
        self.fields["intervention_template"].help_text = (
            "Sono disponibili i template generali e quelli della categoria selezionata."
        )
        self.fields["threshold_value"].help_text = (
            "Giorni pronti subito; ore, km e cicli sono modellati ora per usi successivi."
        )
        self.fields["warning_days"].help_text = "Giorni di preallerta prima della scadenza operativa."
        self.fields["notes"].help_text = "Note operative o eccezioni della policy standard."
        _attach_input_css(self)

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean_warning_days(self):
        value = self.cleaned_data.get("warning_days")
        if value in (None, ""):
            return 15
        return int(value)

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("asset_category")
        template = cleaned_data.get("intervention_template")
        if category is not None and template is not None:
            if template.asset_category_id and template.asset_category_id != category.id:
                self.add_error(
                    "intervention_template",
                    "Il template selezionato appartiene a una categoria diversa dalla regola.",
                )
        return cleaned_data


class MaintenanceRuleAssetOverrideForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRuleAssetOverride
        fields = [
            "asset",
            "base_rule",
            "override_threshold_type",
            "override_threshold_value",
            "override_intervention_template",
            "is_disabled",
            "notes",
        ]
        labels = {
            "asset": "Asset",
            "base_rule": "Regola base",
            "override_threshold_type": "Tipo soglia override",
            "override_threshold_value": "Valore soglia override",
            "override_intervention_template": "Template intervento override",
            "is_disabled": "Disabilita per questo asset",
            "notes": "Note override",
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        locked_asset = kwargs.pop("locked_asset", None)
        locked_base_rule = kwargs.pop("locked_base_rule", None)
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and locked_asset is None:
            locked_asset = self.instance.asset
        if self.instance and self.instance.pk and locked_base_rule is None:
            locked_base_rule = self.instance.base_rule

        self.locked_asset = locked_asset
        self.locked_base_rule = locked_base_rule

        current_asset_id = getattr(self.instance, "asset_id", None)
        current_rule_id = getattr(self.instance, "base_rule_id", None)
        current_template_id = getattr(self.instance, "override_intervention_template_id", None)

        selected_asset_id = None
        if locked_asset is not None:
            selected_asset_id = locked_asset.id
        elif self.is_bound:
            selected_asset_id = self.data.get(self.add_prefix("asset")) or self.data.get("asset")
        elif current_asset_id:
            selected_asset_id = current_asset_id
        else:
            selected_asset_id = self.initial.get("asset")

        selected_rule_id = None
        if locked_base_rule is not None:
            selected_rule_id = locked_base_rule.id
        elif self.is_bound:
            selected_rule_id = self.data.get(self.add_prefix("base_rule")) or self.data.get("base_rule")
        elif current_rule_id:
            selected_rule_id = current_rule_id
        else:
            selected_rule_id = self.initial.get("base_rule")

        asset_qs = Asset.objects.select_related("asset_category").order_by("name", "asset_tag", "id")
        if current_asset_id:
            asset_qs = asset_qs.filter(Q(pk=current_asset_id) | Q(asset_category__isnull=False))
        self.fields["asset"].queryset = asset_qs

        if locked_asset is not None:
            self.fields["asset"].queryset = Asset.objects.filter(pk=locked_asset.pk)
            self.fields["asset"].required = False
            self.initial["asset"] = locked_asset.pk
            self.fields["asset"].widget = forms.HiddenInput()

        rule_qs = MaintenanceRule.objects.select_related("asset_category", "intervention_template").order_by(
            "asset_category__sort_order",
            "asset_category__label",
            "sort_order",
            "id",
        )
        if selected_asset_id:
            asset_for_rules = Asset.objects.filter(pk=selected_asset_id).only("asset_category_id").first()
            if asset_for_rules and asset_for_rules.asset_category_id:
                rule_qs = rule_qs.filter(asset_category_id=asset_for_rules.asset_category_id)
            elif locked_base_rule is None and current_rule_id is None:
                rule_qs = rule_qs.none()
        if current_rule_id:
            rule_qs = MaintenanceRule.objects.select_related("asset_category", "intervention_template").filter(
                Q(pk=current_rule_id) | Q(pk__in=rule_qs.values("pk"))
            )
        self.fields["base_rule"].queryset = rule_qs

        if locked_base_rule is not None:
            self.fields["base_rule"].queryset = MaintenanceRule.objects.filter(pk=locked_base_rule.pk)
            self.fields["base_rule"].required = False
            self.initial["base_rule"] = locked_base_rule.pk
            self.fields["base_rule"].widget = forms.HiddenInput()

        template_qs = MaintenanceInterventionTemplate.objects.order_by("sort_order", "label", "id")
        category_id = None
        if locked_base_rule is not None:
            category_id = locked_base_rule.asset_category_id
        elif selected_rule_id:
            base_rule = MaintenanceRule.objects.filter(pk=selected_rule_id).only("asset_category_id").first()
            category_id = getattr(base_rule, "asset_category_id", None)
        if category_id:
            template_qs = template_qs.filter(Q(is_active=True), Q(asset_category__isnull=True) | Q(asset_category_id=category_id))
        else:
            template_qs = template_qs.filter(is_active=True, asset_category__isnull=True)
        if current_template_id:
            template_qs = MaintenanceInterventionTemplate.objects.filter(Q(pk=current_template_id) | Q(pk__in=template_qs.values("pk")))
        self.fields["override_intervention_template"].required = False
        self.fields["override_intervention_template"].queryset = template_qs.order_by("sort_order", "label", "id")

        self.fields["override_threshold_type"].required = False
        self.fields["override_threshold_value"].required = False
        self.fields["asset"].help_text = "Asset su cui applicare la personalizzazione."
        self.fields["base_rule"].help_text = "Regola standard ereditata dalla categoria dell'asset."
        self.fields["override_threshold_type"].help_text = (
            "Lascia vuoto per mantenere il tipo soglia standard; se lo cambi, indica anche il nuovo valore."
        )
        self.fields["override_threshold_value"].help_text = "Lascia vuoto per mantenere il valore soglia standard."
        self.fields["override_intervention_template"].help_text = (
            "Disponibili template generali o della stessa categoria della regola base."
        )
        self.fields["notes"].help_text = "Note specifiche dell'override per questo asset."
        _attach_input_css(self)
        for field_name in ("asset", "base_rule"):
            if isinstance(self.fields[field_name].widget, forms.HiddenInput):
                self.fields[field_name].widget.attrs.pop("class", None)

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        asset = self.locked_asset or cleaned_data.get("asset")
        base_rule = self.locked_base_rule or cleaned_data.get("base_rule")
        override_type = cleaned_data.get("override_threshold_type")
        override_value = cleaned_data.get("override_threshold_value")
        override_template = cleaned_data.get("override_intervention_template")

        if self.locked_asset is not None:
            cleaned_data["asset"] = self.locked_asset
        if self.locked_base_rule is not None:
            cleaned_data["base_rule"] = self.locked_base_rule

        if asset is not None and base_rule is not None:
            asset_category_id = getattr(asset, "asset_category_id", None)
            if not asset_category_id or asset_category_id != base_rule.asset_category_id:
                self.add_error("base_rule", "La regola selezionata non appartiene alla categoria dell'asset.")

        if override_type and override_value in (None, ""):
            self.add_error(
                "override_threshold_value",
                "Quando imposti un tipo soglia override devi indicare anche il valore soglia override.",
            )

        if override_template is not None and base_rule is not None:
            if override_template.asset_category_id and override_template.asset_category_id != base_rule.asset_category_id:
                self.add_error(
                    "override_intervention_template",
                    "Il template override deve essere generale oppure della stessa categoria della regola base.",
                )

        return cleaned_data


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


class AssistanceContractForm(forms.ModelForm):
    class Meta:
        model = AssistanceContract
        fields = [
            "supplier",
            "code",
            "title",
            "contract_type",
            "asset",
            "asset_category",
            "document",
            "start_date",
            "end_date",
            "is_active",
            "periodic_cost_eur",
            "sla_description",
            "coverage_summary",
            "notes",
        ]
        labels = {
            "supplier": "Fornitore",
            "code": "Codice contratto",
            "title": "Titolo",
            "contract_type": "Tipo contratto",
            "asset": "Asset",
            "asset_category": "Categoria asset",
            "document": "Documento",
            "start_date": "Data inizio",
            "end_date": "Data fine",
            "is_active": "Contratto attivo",
            "periodic_cost_eur": "Costo periodico (EUR)",
            "sla_description": "SLA base",
            "coverage_summary": "Copertura",
            "notes": "Note",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "coverage_summary": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        locked_asset = kwargs.pop("locked_asset", None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and locked_asset is None:
            locked_asset = self.instance.asset
        self.locked_asset = locked_asset

        current_supplier_id = getattr(self.instance, "supplier_id", None)
        current_document_id = getattr(self.instance, "document_id", None)
        current_category_id = getattr(self.instance, "asset_category_id", None)

        selected_supplier_id = None
        if self.is_bound:
            selected_supplier_id = self.data.get(self.add_prefix("supplier")) or self.data.get("supplier")
        elif current_supplier_id:
            selected_supplier_id = current_supplier_id
        else:
            selected_supplier_id = self.initial.get("supplier")

        self.fields["supplier"].queryset = Fornitore.objects.filter(Q(is_active=True) | Q(pk=current_supplier_id)).order_by(
            "ragione_sociale",
            "id",
        )
        self.fields["asset"].required = False
        self.fields["asset"].queryset = Asset.objects.order_by("name", "asset_tag", "id")
        self.fields["asset_category"].required = False
        self.fields["asset_category"].queryset = AssetCategory.objects.filter(
            Q(is_active=True) | Q(pk=current_category_id)
        ).order_by("sort_order", "label", "id")

        if self.locked_asset is not None:
            self.fields["asset"].queryset = Asset.objects.filter(pk=self.locked_asset.pk)
            self.fields["asset"].required = False
            self.initial["asset"] = self.locked_asset.pk
            self.fields["asset"].widget = forms.HiddenInput()

        document_qs = FornitoreDocumento.objects.none()
        if selected_supplier_id:
            document_qs = FornitoreDocumento.objects.filter(fornitore_id=selected_supplier_id).order_by(
                "-uploaded_at",
                "nome",
                "id",
            )
        if current_document_id:
            document_qs = FornitoreDocumento.objects.filter(Q(pk=current_document_id) | Q(pk__in=document_qs.values("pk")))
        self.fields["document"].required = False
        self.fields["document"].queryset = document_qs

        self.fields["supplier"].help_text = "Usa il fornitore reale gia presente in anagrafica."
        self.fields["asset"].help_text = "Opzionale: collega il contratto a un singolo asset."
        self.fields["asset_category"].help_text = "Opzionale: alternativa al singolo asset per contratti di categoria."
        self.fields["document"].help_text = "Opzionale: collega un documento gia caricato sul fornitore."
        self.fields["coverage_summary"].help_text = "Descrizione sintetica di cosa e incluso."
        self.fields["sla_description"].help_text = "Esempio: presa in carico 8h, onsite 24h."
        _attach_input_css(self)
        self.fields["is_active"].widget.attrs["class"] = ""
        if isinstance(self.fields["asset"].widget, forms.HiddenInput):
            self.fields["asset"].widget.attrs.pop("class", None)

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip()

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()

    def clean_sla_description(self):
        return (self.cleaned_data.get("sla_description") or "").strip()

    def clean_coverage_summary(self):
        return (self.cleaned_data.get("coverage_summary") or "").strip()

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        asset = self.locked_asset or cleaned_data.get("asset")
        asset_category = cleaned_data.get("asset_category")
        supplier = cleaned_data.get("supplier")
        document = cleaned_data.get("document")

        if self.locked_asset is not None:
            cleaned_data["asset"] = self.locked_asset
        if asset is not None and asset_category is not None:
            self.add_error("asset_category", "Scegli un contratto per asset oppure per categoria, non entrambi.")
        if document is not None and supplier is not None and document.fornitore_id != supplier.id:
            self.add_error("document", "Il documento selezionato appartiene a un fornitore diverso.")
        return cleaned_data


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


def _validate_workorder_relations(
    *,
    asset: Asset | None,
    verification: PeriodicVerification | None,
    maintenance_rule: MaintenanceRule | None,
    supplier: Fornitore | None,
    assistance_contract: AssistanceContract | None,
    add_error,
    keep_existing_coverage: bool = False,
) -> tuple[Fornitore | None, bool]:
    resolved_supplier = supplier
    covered_by_contract = bool(keep_existing_coverage)

    if verification is not None and asset is not None:
        if not verification.assets.filter(pk=asset.pk).exists():
            add_error("periodic_verification", "La verifica selezionata non appartiene a questo asset.")
        elif resolved_supplier is None and verification.supplier_id:
            resolved_supplier = verification.supplier

    if maintenance_rule is not None and asset is not None:
        if maintenance_rule.asset_category_id != getattr(asset, "asset_category_id", None):
            add_error("maintenance_rule", "La regola selezionata non appartiene alla categoria dell'asset.")

    if assistance_contract is not None:
        if asset is not None and not assistance_contract.applies_to_asset(asset):
            add_error("assistance_contract", "Il contratto selezionato non copre questo asset.")
        if verification is not None and verification.supplier_id and verification.supplier_id != assistance_contract.supplier_id:
            add_error("assistance_contract", "Il contratto selezionato usa un fornitore diverso dalla verifica.")
        if resolved_supplier is not None and resolved_supplier.id != assistance_contract.supplier_id:
            add_error("assistance_contract", "Il contratto selezionato appartiene a un fornitore diverso.")
        resolved_supplier = assistance_contract.supplier
        covered_by_contract = True

    return resolved_supplier, covered_by_contract


class WorkOrderForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = [
            "periodic_verification",
            "maintenance_rule",
            "supplier",
            "assistance_contract",
            "covered_by_contract",
            "kind",
            "status",
            "title",
            "description",
            "resolution",
            "downtime_minutes",
            "cost_eur",
        ]
        labels = {
            "periodic_verification": "Verifica periodica collegata",
            "maintenance_rule": "Regola manutenzione",
            "supplier": "Fornitore",
            "assistance_contract": "Contratto assistenza",
            "covered_by_contract": "Copertura da contratto",
            "kind": "Tipo intervento",
            "status": "Stato",
            "title": "Titolo",
            "description": "Descrizione",
            "resolution": "Risoluzione",
            "downtime_minutes": "Fermo impianto (minuti)",
            "cost_eur": "Costo totale (EUR)",
        }
        widgets = {
            "periodic_verification": forms.Select(),
            "maintenance_rule": forms.Select(),
            "supplier": forms.Select(),
            "assistance_contract": forms.Select(),
            "description": forms.Textarea(attrs={"rows": 4}),
            "resolution": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.asset = kwargs.pop("asset", None)
        self.prefill_payload = kwargs.pop("prefill_payload", None)
        super().__init__(*args, **kwargs)
        if self.prefill_payload is None:
            base_rule_id = 0
            raw_rule_value = self.initial.get("maintenance_rule") or getattr(self.instance, "maintenance_rule_id", None)
            try:
                base_rule_id = int(raw_rule_value or 0)
            except (TypeError, ValueError):
                base_rule_id = 0
            self.prefill_payload = build_workorder_prefill_payload(asset=self.asset, base_rule_id=base_rule_id)
        current_supplier_id = getattr(self.instance, "supplier_id", None)
        current_contract_id = getattr(self.instance, "assistance_contract_id", None)
        current_rule_id = getattr(self.instance, "maintenance_rule_id", None)

        self.fields["supplier"].queryset = Fornitore.objects.filter(Q(is_active=True) | Q(pk=current_supplier_id)).order_by(
            "ragione_sociale",
            "id",
        )
        self.fields["supplier"].required = False
        self.fields["supplier"].help_text = "Se colleghi una verifica periodica il fornitore viene proposto automaticamente."
        self.fields["status"].required = False
        self.fields["status"].widget = forms.HiddenInput()
        self.fields["status"].initial = WorkOrder.STATUS_OPEN
        self.initial["status"] = WorkOrder.STATUS_OPEN
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
        rule_rows = []
        if self.asset is not None and getattr(self.asset, "asset_category_id", None):
            rule_rows = [
                row
                for row in resolve_asset_maintenance_rules(self.asset)
                if row["base_rule"].is_active and not row["is_disabled"]
            ]
        self.effective_rule_map = {row["base_rule"].id: row for row in rule_rows}
        rule_ids = list(self.effective_rule_map.keys())
        rule_qs = MaintenanceRule.objects.none()
        if rule_ids:
            rule_qs = MaintenanceRule.objects.select_related("intervention_template", "asset_category").filter(pk__in=rule_ids)
        if current_rule_id:
            rule_qs = MaintenanceRule.objects.select_related("intervention_template", "asset_category").filter(
                Q(pk=current_rule_id) | Q(pk__in=rule_qs.values("pk"))
            )
        self.fields["maintenance_rule"].required = False
        self.fields["maintenance_rule"].queryset = rule_qs.order_by("sort_order", "id")
        self.fields["maintenance_rule"].help_text = "Opzionale: collega il work order a una regola manutentiva effettiva dell'asset."
        self.fields["maintenance_rule"].label_from_instance = lambda rule: self._maintenance_rule_label(
            rule,
            self.effective_rule_map,
        )

        self.contract_rows = get_applicable_assistance_contracts(self.asset) if self.asset is not None else []
        contract_ids = [contract.id for contract in self.contract_rows]
        contract_qs = AssistanceContract.objects.none()
        if contract_ids:
            contract_qs = AssistanceContract.objects.select_related("supplier", "asset", "asset_category").filter(
                pk__in=contract_ids
            )
        if current_contract_id:
            contract_qs = AssistanceContract.objects.select_related("supplier", "asset", "asset_category").filter(
                Q(pk=current_contract_id) | Q(pk__in=contract_qs.values("pk"))
            )
        self.fields["assistance_contract"].required = False
        self.fields["assistance_contract"].queryset = contract_qs.order_by("supplier__ragione_sociale", "title", "id")
        self.fields["assistance_contract"].help_text = "Se presente, il contratto valorizza copertura e fornitore."
        self.fields["covered_by_contract"].required = False
        self.fields["covered_by_contract"].help_text = "Disponibile solo con un contratto selezionato."
        if self.asset is not None and not self.is_bound:
            verifications = list(verification_qs)
            if len(verifications) == 1:
                verification = verifications[0]
                self.initial.setdefault("periodic_verification", verification.pk)
                if verification.supplier_id:
                    self.initial.setdefault("supplier", verification.supplier_id)
            self._apply_prefill_defaults()
        _attach_input_css(self)
        self.fields["covered_by_contract"].widget.attrs["class"] = ""

    def _apply_prefill_defaults(self) -> None:
        payload = self.prefill_payload or {}
        preferred_rule = payload.get("maintenance_rule")
        preferred_contract = payload.get("contract") or (self.contract_rows[0] if self.contract_rows else None)
        preferred_supplier = payload.get("supplier")

        if preferred_rule is not None:
            self.initial.setdefault("maintenance_rule", preferred_rule.id)
            self.initial.setdefault("kind", payload.get("kind") or WorkOrder.KIND_PREVENTIVE)
        if payload.get("title"):
            self.initial.setdefault("title", payload["title"])
        if payload.get("description"):
            self.initial.setdefault("description", payload["description"])
        if preferred_contract is not None:
            self.initial.setdefault("assistance_contract", preferred_contract.id)
            self.initial.setdefault("covered_by_contract", True)
            preferred_supplier = preferred_contract.supplier
        if preferred_supplier is not None:
            self.initial.setdefault("supplier", preferred_supplier.id)

    def _maintenance_rule_label(self, rule: MaintenanceRule, effective_rule_map: dict[int, dict]) -> str:
        row = effective_rule_map.get(rule.id)
        if row is None:
            return str(rule)
        template = row["effective_intervention_template"]
        threshold_label = row.get("effective_threshold_label") or rule.get_threshold_type_display()
        warning_days = int(row.get("effective_warning_days") or 0)
        return (
            f"{template.label} - {row['effective_threshold_value']} {threshold_label.lower()} "
            f"(warning {warning_days} gg)"
        )

    def build_rule_suggestion_map(self) -> dict[str, dict[str, str]]:
        payload: dict[str, dict[str, str]] = {}
        for rule in self.fields["maintenance_rule"].queryset:
            row = self.effective_rule_map.get(rule.id)
            template = row["effective_intervention_template"] if row is not None else rule.intervention_template
            template_description = (getattr(template, "description", "") or "").strip()
            effective_notes = (str(row.get("effective_notes") or "").strip() if row is not None else "")
            description_parts: list[str] = []
            if template_description:
                description_parts.append(template_description)
            if effective_notes and effective_notes not in description_parts:
                description_parts.append(effective_notes)
            payload[str(rule.id)] = {
                "title": (getattr(template, "label", "") or "").strip(),
                "description": "\n\n".join(description_parts).strip(),
                "template_label": (getattr(template, "label", "") or "").strip(),
            }
        return payload

    def build_contract_suggestion_map(self) -> dict[str, dict[str, str]]:
        return {
            str(contract.id): {
                "supplier_id": str(contract.supplier_id or ""),
                "supplier_label": str(contract.supplier) if contract.supplier_id else "",
                "contract_label": (contract.title or contract.code or "").strip(),
            }
            for contract in self.fields["assistance_contract"].queryset
        }

    def clean(self):
        cleaned_data = super().clean()
        verification = cleaned_data.get("periodic_verification")
        maintenance_rule = cleaned_data.get("maintenance_rule")
        supplier = cleaned_data.get("supplier")
        assistance_contract = cleaned_data.get("assistance_contract")
        if cleaned_data.get("covered_by_contract") and assistance_contract is None:
            self.add_error("covered_by_contract", "Seleziona un contratto per indicare la copertura.")
        supplier, covered_by_contract = _validate_workorder_relations(
            asset=self.asset,
            verification=verification,
            maintenance_rule=maintenance_rule,
            supplier=supplier,
            assistance_contract=assistance_contract,
            add_error=self.add_error,
            keep_existing_coverage=bool(cleaned_data.get("covered_by_contract")),
        )
        cleaned_data["supplier"] = supplier
        cleaned_data["covered_by_contract"] = covered_by_contract
        # In creazione il workorder parte sempre aperto, anche se il client
        # prova a forzare uno stato finale via POST.
        cleaned_data["status"] = WorkOrder.STATUS_OPEN
        return cleaned_data


class WorkOrderCloseForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            (WorkOrder.STATUS_DONE, "Chiusa"),
            (WorkOrder.STATUS_CANCELED, "Annullata"),
        ],
        initial=WorkOrder.STATUS_DONE,
        label="Esito finale",
    )
    resolution = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}), label="Risoluzione")
    intervention_duration_minutes = forms.IntegerField(required=False, min_value=0, label="Durata intervento (minuti)")
    downtime_minutes = forms.IntegerField(required=False, min_value=0, label="Fermo impianto (minuti)")
    labor_cost_eur = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label="Manodopera (EUR)")
    materials_cost_eur = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label="Ricambi / materiali (EUR)")
    cost_eur = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label="Costo totale (EUR)")
    assistance_contract = forms.ModelChoiceField(required=False, queryset=AssistanceContract.objects.none(), label="Contratto assistenza")
    covered_by_contract = forms.BooleanField(required=False, label="Coperto da contratto")
    log_note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Nota di chiusura")

    def __init__(self, *args, **kwargs):
        self.asset = kwargs.pop("asset", None)
        self.workorder = kwargs.pop("workorder", None)
        super().__init__(*args, **kwargs)
        current_contract_id = getattr(self.workorder, "assistance_contract_id", None)
        contract_rows = get_applicable_assistance_contracts(self.asset) if self.asset is not None else []
        contract_ids = [contract.id for contract in contract_rows]
        contract_qs = AssistanceContract.objects.none()
        if contract_ids:
            contract_qs = AssistanceContract.objects.select_related("supplier", "asset", "asset_category").filter(
                pk__in=contract_ids
            )
        if current_contract_id:
            contract_qs = AssistanceContract.objects.select_related("supplier", "asset", "asset_category").filter(
                Q(pk=current_contract_id) | Q(pk__in=contract_qs.values("pk"))
            )
        self.fields["assistance_contract"].queryset = contract_qs.order_by("supplier__ragione_sociale", "title", "id")
        self.fields["assistance_contract"].help_text = "Opzionale: collega la chiusura a un contratto assistenza."
        self.fields["covered_by_contract"].help_text = "Disponibile solo con un contratto selezionato."
        self.fields["cost_eur"].help_text = "Il costo totale viene calcolato automaticamente se non inserito."
        _attach_input_css(self)
        self.fields["covered_by_contract"].widget.attrs["class"] = ""

    def clean(self):
        cleaned_data = super().clean()
        labor_cost = cleaned_data.get("labor_cost_eur")
        materials_cost = cleaned_data.get("materials_cost_eur")
        total_cost = cleaned_data.get("cost_eur")
        assistance_contract = cleaned_data.get("assistance_contract")
        if cleaned_data.get("covered_by_contract") and assistance_contract is None:
            self.add_error("covered_by_contract", "Seleziona un contratto per indicare la copertura.")
        if total_cost in (None, "") and (labor_cost is not None or materials_cost is not None):
            cleaned_data["cost_eur"] = (labor_cost or 0) + (materials_cost or 0)
        supplier, covered_by_contract = _validate_workorder_relations(
            asset=self.asset,
            verification=getattr(self.workorder, "periodic_verification", None),
            maintenance_rule=getattr(self.workorder, "maintenance_rule", None),
            supplier=getattr(self.workorder, "supplier", None),
            assistance_contract=assistance_contract,
            add_error=self.add_error,
            keep_existing_coverage=bool(cleaned_data.get("covered_by_contract")),
        )
        if supplier is not None and getattr(self.workorder, "supplier_id", None) is None:
            cleaned_data["resolved_supplier"] = supplier
        cleaned_data["covered_by_contract"] = covered_by_contract
        return cleaned_data
