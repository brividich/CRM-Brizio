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
    # SEC (CWE-620): richiede la password attuale per il cambio self-service, così
    # una sessione temporaneamente dirottata non può reimpostare la password senza
    # conoscere quella corrente. Verificata nella view contro l'hash legacy.
    password_attuale = forms.CharField(
        label="Password attuale",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Password attuale"}),
    )
    nuova_password = forms.CharField(
        label="Nuova password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Nuova password"}),
        min_length=12,
    )
    conferma_password = forms.CharField(
        label="Conferma password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Conferma password"}),
        min_length=12,
    )

    def clean(self):
        cleaned = super().clean()
        nuova = cleaned.get("nuova_password")
        conferma = cleaned.get("conferma_password")
        if nuova and conferma and nuova != conferma:
            raise forms.ValidationError("Le password non coincidono.")
        if nuova:
            # SEC (audit B2): stessi validatori di Django (password comuni, solo numeri...).
            from django.contrib.auth import password_validation
            from django.core.exceptions import ValidationError

            try:
                password_validation.validate_password(nuova, user=self.user)
            except ValidationError as exc:
                self.add_error("nuova_password", exc)
        return cleaned

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

