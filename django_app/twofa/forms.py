from django import forms


class VerifyOTPForm(forms.Form):
    code = forms.CharField(
        label="Codice di verifica",
        min_length=6,
        max_length=8,
        widget=forms.TextInput(attrs={
            "class": "input",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "placeholder": "000000",
            "autofocus": True,
        }),
    )

    def clean_code(self):
        return self.cleaned_data["code"].strip().replace(" ", "")


class SetupTOTPConfirmForm(forms.Form):
    code = forms.CharField(
        label="Codice dall'app",
        min_length=6,
        max_length=8,
        widget=forms.TextInput(attrs={
            "class": "input",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "placeholder": "000000",
            "autofocus": True,
        }),
    )

    def clean_code(self):
        return self.cleaned_data["code"].strip().replace(" ", "")
