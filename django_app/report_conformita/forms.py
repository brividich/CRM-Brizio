from django import forms
from django.core.validators import RegexValidator

SAFE_TEXT = RegexValidator(r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
                           "Il testo contiene caratteri non validi.", inverse_match=True)


class CorrectionForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput)
    action = forms.ChoiceField(label="Operazione", choices=(
        ("correct", "Rettifica soltanto il report"), ("restore", "Ripristina il dato sorgente"),
    ))
    value = forms.CharField(label="Valore da mostrare nel report", required=False, max_length=250,
                            validators=[SAFE_TEXT],
                            strip=False, widget=forms.Textarea(attrs={"rows": 3}))
    reason = forms.CharField(label="Motivazione", max_length=1000, validators=[SAFE_TEXT],
                             widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, kpi=False, **kwargs):
        super().__init__(*args, **kwargs)
        if kpi:
            self.fields["value"] = forms.CharField(label="Valore indicatore nel report", required=False,
                                                  max_length=80, strip=False, validators=[SAFE_TEXT])

    def clean_value(self):
        return self.cleaned_data["value"].replace("\r", " ").replace("\n", " ")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") == "restore":
            # Restoration does not use the replacement, including stale/oversized source values.
            self._errors.pop("value", None)
            cleaned["value"] = ""
        return cleaned
