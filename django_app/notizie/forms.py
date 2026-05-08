from __future__ import annotations

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_extension_and_mime,
)

from .models import Notizia, NotiziaAllegato, NotiziaAudience


# Allegati notizie: documenti, immagini, e file Office. 25 MB.
NOTIZIE_ALLEGATO_MAX_BYTES = 25 * 1024 * 1024
NOTIZIE_ALLEGATO_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".zip",
}
NOTIZIE_ALLEGATO_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}


class NotiziaForm(forms.ModelForm):
    class Meta:
        model = Notizia
        fields = ("titolo", "corpo", "obbligatoria")
        widgets = {
            "titolo": forms.TextInput(
                attrs={
                    "maxlength": "300",
                    "placeholder": "Titolo comunicazione",
                }
            ),
            "corpo": forms.Textarea(
                attrs={
                    "rows": 10,
                    "placeholder": "Testo della comunicazione",
                }
            ),
        }


class NotiziaAudienceForm(forms.ModelForm):
    class Meta:
        model = NotiziaAudience
        fields = ("legacy_role_id",)
        widgets = {
            "legacy_role_id": forms.NumberInput(
                attrs={"min": "1", "placeholder": "ID ruolo legacy"}
            )
        }


class AudienceInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        seen_roles: set[int] = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            cleaned = form.cleaned_data
            if not cleaned or cleaned.get("DELETE"):
                continue

            role_id = cleaned.get("legacy_role_id")
            if role_id is None:
                continue
            if role_id in seen_roles:
                raise forms.ValidationError("Ruolo duplicato nella audience.")
            seen_roles.add(role_id)


class NotiziaAllegatoForm(forms.ModelForm):
    class Meta:
        model = NotiziaAllegato
        fields = ("nome_file", "file", "url_esterno")
        widgets = {
            "nome_file": forms.TextInput(attrs={"placeholder": "Nome allegato"}),
            "url_esterno": forms.URLInput(attrs={"placeholder": "https://..."}),
        }

    def clean(self):
        cleaned = super().clean()
        nome_file = str(cleaned.get("nome_file") or "").strip()
        file_obj = cleaned.get("file")
        url_esterno = str(cleaned.get("url_esterno") or "").strip()

        if not nome_file and not file_obj and not url_esterno:
            return cleaned

        if file_obj and url_esterno:
            raise forms.ValidationError("Specifica un file o un URL esterno, non entrambi.")

        if not file_obj and not url_esterno:
            raise forms.ValidationError("Inserisci un file o un URL esterno.")

        if file_obj:
            try:
                validate_extension_and_mime(
                    file_obj,
                    allowed_extensions=NOTIZIE_ALLEGATO_EXTENSIONS,
                    allowed_mimes=NOTIZIE_ALLEGATO_MIMES,
                    max_bytes=NOTIZIE_ALLEGATO_MAX_BYTES,
                    label=safe_filename(getattr(file_obj, "name", "")) or "Allegato",
                    allow_empty=False,
                )
            except UploadMimeValidationError as exc:
                raise forms.ValidationError(str(exc))

        if not nome_file and file_obj:
            safe_name = safe_filename(getattr(file_obj, "name", ""))
            cleaned["nome_file"] = (safe_name or "allegato")[:300]

        if not cleaned.get("nome_file"):
            raise forms.ValidationError("Inserisci un nome allegato.")

        return cleaned


NotiziaAudienceFormSet = inlineformset_factory(
    Notizia,
    NotiziaAudience,
    form=NotiziaAudienceForm,
    formset=AudienceInlineFormSet,
    extra=1,
    can_delete=True,
)

NotiziaAllegatoFormSet = inlineformset_factory(
    Notizia,
    NotiziaAllegato,
    form=NotiziaAllegatoForm,
    extra=1,
    can_delete=True,
)
