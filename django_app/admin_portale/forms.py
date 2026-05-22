from __future__ import annotations

from django import forms


class UtenteUpdateForm(forms.Form):
    # Lo username non è modificabile da qui: la fonte di verità è
    # `anagrafica_dipendenti.aliasusername` (scheda dipendente). Vedi
    # `anagrafica.views.dipendente_username_set`, che lo propaga all'account.
    nome = forms.CharField(max_length=200)
    email = forms.EmailField(required=False)
    attivo = forms.BooleanField(required=False)
    ruolo_id = forms.IntegerField(required=False)
    deve_cambiare_password = forms.BooleanField(required=False)
    force_password_reset = forms.BooleanField(required=False)


class UtenteCreateForm(forms.Form):
    nome = forms.CharField(max_length=200)
    email = forms.EmailField(required=False)
    ruolo_id = forms.IntegerField(required=False)
    attivo = forms.BooleanField(required=False, initial=True)
    deve_cambiare_password = forms.BooleanField(required=False, initial=True)
    ad_managed = forms.BooleanField(required=False)
    password_iniziale = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True))

    def clean(self):
        cleaned = super().clean()
        ad_managed = bool(cleaned.get("ad_managed"))
        password_iniziale = (cleaned.get("password_iniziale") or "").strip()
        if not ad_managed and not password_iniziale:
            self.add_error("password_iniziale", "Password iniziale obbligatoria se non AD managed.")
        elif not ad_managed and len(password_iniziale) < 8:
            self.add_error("password_iniziale", "La password deve essere di almeno 8 caratteri.")
        return cleaned


class BulkRoleForm(forms.Form):
    ruolo_id = forms.IntegerField()
    user_ids = forms.CharField(required=False)

    def cleaned_user_ids(self) -> list[int]:
        raw = self.cleaned_data.get("user_ids", "")
        items = []
        for token in str(raw).replace(";", ",").split(","):
            token = token.strip()
            if token.isdigit():
                items.append(int(token))
        return items


class PulsanteForm(forms.Form):
    id = forms.IntegerField(required=False)
    codice = forms.CharField(max_length=100)
    nome_visibile = forms.CharField(max_length=200, required=False)
    modulo = forms.CharField(max_length=100)
    url = forms.CharField(max_length=500)
    icona = forms.CharField(max_length=50, required=False)
    ordine = forms.IntegerField(required=False)
    descrizione = forms.CharField(required=False)

    def clean_codice(self):
        value = (self.cleaned_data.get("codice") or "").strip()
        if not value:
            raise forms.ValidationError("Codice obbligatorio.")
        return value

    def clean_modulo(self):
        value = (self.cleaned_data.get("modulo") or "").strip()
        if not value:
            raise forms.ValidationError("Modulo obbligatorio.")
        return value

    def clean_url(self):
        value = (self.cleaned_data.get("url") or "").strip()
        if not value:
            raise forms.ValidationError("URL obbligatorio.")
        lower = value.lower()
        # Blocca schemi pericolosi che potrebbero eseguire codice nel browser
        if lower.startswith(("javascript:", "data:", "vbscript:")):
            raise forms.ValidationError("Schema URL non consentito.")
        if lower.startswith(("route:", "django:", "http://", "https://")):
            return value
        if not value.startswith("/"):
            value = "/" + value
        return value
