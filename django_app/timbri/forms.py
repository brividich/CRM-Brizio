from __future__ import annotations

from django import forms

from .models import PNG_MAX_SIZE, RegistroTimbro, RegistroTimbroImmagine


class RegistroTimbroForm(forms.ModelForm):
    image_timbro = forms.ImageField(required=False)
    image_firma = forms.ImageField(required=False)
    image_sigla = forms.ImageField(required=False)

    class Meta:
        model = RegistroTimbro
        fields = [
            "codice_timbro",
            "qualifica",
            "tipo_timbro",
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
            "data_consegna": forms.DateInput(attrs={"class": "tim-input", "type": "date"}),
            "data_ritiro": forms.DateInput(attrs={"class": "tim-input", "type": "date"}),
            "note": forms.Textarea(attrs={"class": "tim-input", "rows": 4, "placeholder": "Note operative"}),
            "firma_testo": forms.Textarea(attrs={"class": "tim-input", "rows": 3, "placeholder": "Testo o note firma"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_attivo") and cleaned.get("data_ritiro"):
            self.add_error("data_ritiro", "Un record attivo non puo avere una data ritiro.")
        return cleaned

    def _clean_png(self, field_name: str):
        file_obj = self.cleaned_data.get(field_name)
        if not file_obj:
            return
        if str(getattr(file_obj, "name", "") or "").lower().endswith(".png") is False:
            raise forms.ValidationError("Sono consentiti solo file PNG.")
        if int(getattr(file_obj, "size", 0) or 0) > PNG_MAX_SIZE:
            raise forms.ValidationError("Dimensione massima 20 MB.")
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
            pass
    image_obj.image = uploaded_file
    image_obj.source_url = ""
    image_obj.original_filename = str(getattr(uploaded_file, "name", "") or "")[:255]
    image_obj.save()
    return image_obj
