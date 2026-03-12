from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LegacyAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Email o username", max_length=254)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "autocomplete": "username",
                "placeholder": "Email o nome utente",
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "autocomplete": "current-password",
                "placeholder": "Password",
            }
        )


class LegacyChangePasswordForm(forms.Form):
    nuova_password = forms.CharField(
        label="Nuova password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Nuova password"}),
        min_length=6,
    )
    conferma_password = forms.CharField(
        label="Conferma password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Conferma password"}),
        min_length=6,
    )

    def clean(self):
        cleaned = super().clean()
        nuova = cleaned.get("nuova_password")
        conferma = cleaned.get("conferma_password")
        if nuova and conferma and nuova != conferma:
            raise forms.ValidationError("Le password non coincidono.")
        return cleaned

