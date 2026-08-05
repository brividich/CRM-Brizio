from __future__ import annotations

import logging

from django import forms

from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_extension_and_mime,
)

from .models import PNG_MAX_SIZE, RegistroTimbro, RegistroTimbroImmagine

logger = logging.getLogger(__name__)


class RegistroTimbroForm(forms.ModelForm):
    image_timbro = forms.ImageField(required=False)
    image_firma = forms.ImageField(required=False)
    image_sigla = forms.ImageField(required=False)
    data_consegna = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "tim-input", "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
    )
    data_ritiro = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "tim-input", "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
    )

    class Meta:
        model = RegistroTimbro
        fields = [
            "codice_timbro",
            "qualifica",
            "tipo_timbro",
            "abilitazione_processo",
            "data_consegna",
            "data_ritiro",
            "note",
            "firma_testo",
            "is_attivo",
        ]
        widgets = {
            "codice_timbro": forms.TextInput(attrs={"class": "tim-input", "placeholder": "Codice timbro"}),
            "qualifica": forms.TextInput(attrs={"class": "tim-input", "placeholder": "Qualifica"}),
            "tipo_timbro": forms.Select(attrs={"class": "tim-input"}),
            "abilitazione_processo": forms.Select(attrs={"class": "tim-input"}),
            "note": forms.Textarea(attrs={"class": "tim-input", "rows": 4, "placeholder": "Note operative"}),
            "firma_testo": forms.Textarea(attrs={"class": "tim-input", "rows": 3, "placeholder": "Testo o note firma"}),
            "is_attivo": forms.CheckboxInput(attrs={"class": "tim-checkbox"}),
        }

    def __init__(self, *args, operatore=None, **kwargs):
        super().__init__(*args, **kwargs)
        fld = self.fields.get("abilitazione_processo")
        if fld is None:
            return
        # Aggancio MOD.128: offre SOLO le abilitazioni della persona del timbro
        # (match per legacy_anagrafica_id dell'operatore). Import locale (cross-app).
        from anagrafica.models_mpq import AbilitazioneProcesso
        lid = getattr(operatore, "legacy_anagrafica_id", None)
        if lid is None and getattr(self.instance, "operatore_id", None):
            lid = getattr(self.instance.operatore, "legacy_anagrafica_id", None)
        if lid:
            fld.queryset = (AbilitazioneProcesso.objects
                            .filter(legacy_anagrafica_id=lid)
                            .select_related("processo", "processo__cliente"))
        else:
            fld.queryset = AbilitazioneProcesso.objects.none()
        fld.required = False
        fld.label = "Abilitazione MOD.128 collegata"
        fld.empty_label = "— Nessuna —"
        fld.label_from_instance = (
            lambda ab: f"{ab.processo.nome} ({ab.processo.cliente.nome})")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_attivo") and cleaned.get("data_ritiro"):
            self.add_error("data_ritiro", "Un record attivo non puo avere una data ritiro.")
        return cleaned

    def _clean_png(self, field_name: str):
        file_obj = self.cleaned_data.get(field_name)
        if not file_obj:
            return
        try:
            validate_extension_and_mime(
                file_obj,
                allowed_extensions={".png"},
                allowed_mimes={"image/png"},
                max_bytes=PNG_MAX_SIZE,
                label=safe_filename(getattr(file_obj, "name", "")) or "Immagine",
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc))
        return file_obj

    def clean_image_timbro(self):
        return self._clean_png("image_timbro")

    def clean_image_firma(self):
        return self._clean_png("image_firma")

    def clean_image_sigla(self):
        return self._clean_png("image_sigla")


class RegistroArchiveForm(forms.Form):
    confirm = forms.BooleanField(required=True)


def save_variant_image(*, registro: RegistroTimbro, variante: str, uploaded_file) -> RegistroTimbroImmagine:
    image_obj = RegistroTimbroImmagine.objects.filter(registro=registro, variante=variante).first()
    if image_obj is None:
        image_obj = RegistroTimbroImmagine(registro=registro, variante=variante)
    elif image_obj.image:
        try:
            image_obj.image.delete(save=False)
        except Exception:
            # File vecchio non rimosso: resta orfano sul disco, non blocca il salvataggio.
            logger.exception("Timbri: rimozione dell'immagine precedente fallita")
    image_obj.image = uploaded_file
    image_obj.source_url = ""
    image_obj.original_filename = str(getattr(uploaded_file, "name", "") or "")[:255]
    image_obj.save()
    return image_obj
