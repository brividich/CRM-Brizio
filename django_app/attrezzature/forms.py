from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_extension_and_mime,
)

from .models import Attrezzatura, AttrezzaturaNota, AttrezzaturaTask

User = get_user_model()


class AttrezzaturaForm(forms.ModelForm):
    class Meta:
        model = Attrezzatura
        fields = [
            "codice",
            "descrizione",
            "part_number",
            "numero_pezzi",
            "avanzamento_percentuale",
            "stato",
            "disponibilita_stato",
            "ordine_visuale",
            "data_consegna_prevista",
            "note_consegna",
            "note_rocco",
            "blocked_reason",
        ]
        widgets = {
            "codice": forms.TextInput(attrs={"class": "input"}),
            "descrizione": forms.TextInput(attrs={"class": "input"}),
            "part_number": forms.TextInput(attrs={"class": "input"}),
            "numero_pezzi": forms.NumberInput(attrs={"class": "input", "min": 0}),
            "avanzamento_percentuale": forms.NumberInput(attrs={"class": "input", "min": 0, "max": 100}),
            "stato": forms.Select(attrs={"class": "input"}),
            "disponibilita_stato": forms.Select(attrs={"class": "input"}),
            "ordine_visuale": forms.NumberInput(attrs={"class": "input"}),
            "data_consegna_prevista": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "note_consegna": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "note_rocco": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "blocked_reason": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }


class AttrezzaturaTaskForm(forms.ModelForm):
    class Meta:
        model = AttrezzaturaTask
        fields = [
            "attrezzatura",
            "part_number",
            "codice_attrezzo",
            "tipo",
            "titolo",
            "descrizione",
            "stato",
            "priorita",
            "assegnato_a",
            "scadenza",
            "origine",
            "external_kickoff_id",
            "external_kickoff_activity_id",
            "blocked_reason",
        ]
        widgets = {
            "attrezzatura": forms.Select(attrs={"class": "input"}),
            "part_number": forms.TextInput(attrs={"class": "input"}),
            "codice_attrezzo": forms.TextInput(attrs={"class": "input"}),
            "tipo": forms.Select(attrs={"class": "input"}),
            "titolo": forms.TextInput(attrs={"class": "input"}),
            "descrizione": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "stato": forms.Select(attrs={"class": "input"}),
            "priorita": forms.Select(attrs={"class": "input"}),
            "assegnato_a": forms.Select(attrs={"class": "input"}),
            "scadenza": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "origine": forms.Select(attrs={"class": "input"}),
            "external_kickoff_id": forms.TextInput(attrs={"class": "input"}),
            "external_kickoff_activity_id": forms.TextInput(attrs={"class": "input"}),
            "blocked_reason": forms.Textarea(attrs={"class": "input", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attrezzatura"].required = False
        self.fields["assegnato_a"].required = False
        self.fields["assegnato_a"].queryset = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        self.fields["attrezzatura"].queryset = Attrezzatura.objects.order_by("codice", "part_number", "id")


class ProgressUpdateForm(forms.Form):
    avanzamento_percentuale = forms.IntegerField(required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "input"}))
    stato = forms.ChoiceField(required=False, choices=[("", "Mantieni stato")] + list(Attrezzatura._meta.get_field("stato").choices), widget=forms.Select(attrs={"class": "input"}))
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": "input", "rows": 3}))


class TaskCompleteForm(forms.Form):
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": "input", "rows": 3}))


class TaskBlockForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"class": "input", "rows": 3}))


class AttrezzaturaBlockForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Motivo blocco"}))


class NotaForm(forms.ModelForm):
    class Meta:
        model = AttrezzaturaNota
        fields = ["testo"]
        widgets = {"testo": forms.Textarea(attrs={"class": "input", "rows": 3})}


class ImportUploadForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input", "accept": ".xls,.xlsx"}))

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if not uploaded_file:
            return uploaded_file
        try:
            validate_extension_and_mime(
                uploaded_file,
                allowed_extensions={".xls", ".xlsx"},
                allowed_mimes={
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.ms-excel",
                    "application/octet-stream",
                    "application/zip",
                    "application/x-zip-compressed",
                },
                max_bytes=15 * 1024 * 1024,
                label=safe_filename(getattr(uploaded_file, "name", "")) or "Import",
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc))
        return uploaded_file


class EmbeddedPreviewForm(forms.Form):
    part_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "P/N", "list": "attrezzature-part-number-list"}),
    )
