"""Form condivisi del modulo Schede di sicurezza.

``ProdottoChimicoForm`` e' l'unico posto in cui si dichiara *cosa* si chiede
quando si censisce un prodotto chimico: lo usano sia la schermata di
schede_sicurezza sia il form dell'asset "Prodotto chimico" (con prefisso), che
prima chiedevano due sottoinsiemi diversi degli stessi dati.
"""
from __future__ import annotations

from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db.models import Q

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from . import pittogrammi as ghs
from .models import ImpostazioniEtichetta, ProdottoChimico

_TESTO_ATTRS = {"class": "pc-input"}


class ProdottoChimicoForm(forms.ModelForm):
    """Anagrafica completa del prodotto chimico (identita', logistica, pericolosita')."""

    pittogrammi = forms.MultipleChoiceField(
        choices=ghs.PITTOGRAMMI_GHS,
        required=False,
        label="Pittogrammi di pericolo",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ProdottoChimico
        fields = [
            "nome", "mansioni", "fornitore", "produttore",
            "famiglia", "sottocategoria",
            "numero_interno", "codice_prodotto", "ubicazione", "quantita_presente",
            "pittogrammi", "dpi_obbligatori", "attivo",
        ]
        labels = {
            "nome": "Nome prodotto",
            "mansioni": "Mansioni di rischio",
            "quantita_presente": "Quantità presente",
        }
        widgets = {
            "nome": forms.TextInput(attrs=_TESTO_ATTRS),
            "fornitore": forms.TextInput(attrs=_TESTO_ATTRS),
            "produttore": forms.TextInput(attrs=_TESTO_ATTRS),
            "famiglia": forms.TextInput(attrs=_TESTO_ATTRS),
            "sottocategoria": forms.TextInput(attrs=_TESTO_ATTRS),
            "numero_interno": forms.TextInput(attrs=_TESTO_ATTRS),
            "codice_prodotto": forms.TextInput(attrs=_TESTO_ATTRS),
            "ubicazione": forms.TextInput(attrs=_TESTO_ATTRS),
            "quantita_presente": forms.TextInput(attrs=_TESTO_ATTRS),
            "mansioni": forms.CheckboxSelectMultiple,
            "dpi_obbligatori": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Import in-funzione: le due app restano agganciate solo a runtime.
        from anagrafica.models import Mansione
        from dpi.models import CategoriaDPI

        mansioni_qs = Mansione.objects.filter(is_active=True)
        if self.instance and self.instance.pk:
            mansioni_qs = Mansione.objects.filter(
                Q(is_active=True) | Q(prodotti_chimici=self.instance)
            )
        self.fields["mansioni"].queryset = mansioni_qs.distinct().order_by("nome")
        self.fields["mansioni"].help_text = (
            "Ogni dipendente che ricopre una di queste mansioni dovra' prendere "
            "visione della versione corrente della SDS."
        )
        self.fields["nome"].required = True
        self.fields["mansioni"].required = True

        dpi_field = self.fields["dpi_obbligatori"]
        dpi_field.queryset = CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome")
        dpi_field.label_from_instance = lambda cat: cat.nome

        if self.instance and self.instance.pk:
            # La scheda corrente ha la precedenza (vedi `pittogrammi_effettivi`):
            # il selettore deve partire da cio' che l'utente vede sul prodotto.
            self.initial["pittogrammi"] = ghs.normalizza(self.instance.pittogrammi_effettivi())

    def clean_pittogrammi(self):
        return ghs.normalizza(self.cleaned_data.get("pittogrammi"))

    def catalogo_pittogrammi(self) -> list[dict]:
        """Il catalogo CLP con lo stato di selezione corrente, per il selettore."""
        if self.is_bound:
            chiave = self.add_prefix("pittogrammi")
            getlist = getattr(self.data, "getlist", None)
            selezionati = getlist(chiave) if getlist else (self.data.get(chiave) or [])
        else:
            selezionati = self.initial.get("pittogrammi") or []
        return ghs.catalogo(selezionati=selezionati)

    def save(self, commit=True):
        vecchie_mansioni = set()
        if self.instance and self.instance.pk:
            vecchie_mansioni = set(self.instance.mansioni.values_list("pk", flat=True))
        prodotto = super().save(commit=commit)
        if commit:
            self._propaga_pittogrammi(prodotto)
            nuove_mansioni = set(prodotto.mansioni.values_list("pk", flat=True))
            aggiunte = nuove_mansioni - vecchie_mansioni
            if aggiunte:
                from .services.assegnazioni import notifica_mansioni_aggiunte
                notifica_mansioni_aggiunte(prodotto, aggiunte)
        return prodotto

    def _propaga_pittogrammi(self, prodotto) -> None:
        """Allinea la scheda corrente alla scelta fatta qui.

        Senza questo passaggio il prodotto e la sua SDS potrebbero mostrare due
        set diversi di simboli: `pittogrammi_effettivi` da' la precedenza alla
        scheda, quindi la modifica sul prodotto sembrerebbe non aver preso.
        """
        scheda = prodotto.scheda_corrente()
        codici = self.cleaned_data.get("pittogrammi") or []
        if scheda is not None and list(scheda.pittogrammi or []) != list(codici):
            scheda.pittogrammi = list(codici)
            scheda.save(update_fields=["pittogrammi"])


LOGO_ESTENSIONI = {".png", ".jpg", ".jpeg", ".webp"}
LOGO_MIME = {"image/png", "image/jpeg", "image/webp"}
LOGO_MAX_BYTES = 2 * 1024 * 1024

# Limiti dei campi numerici: (minimo, massimo). Fuori da qui l'etichetta non sta
# in piedi (QR illeggibile, testo che esce dal bordo).
LIMITI_ETICHETTA = {
    "larghezza_mm": (40, 150),
    "altezza_mm": (25, 150),
    "logo_altezza_mm": (4, 20),
    "nome_dimensione_pt": (7, 24),
}


class ImpostazioniEtichettaForm(forms.ModelForm):
    rimuovi_logo = forms.BooleanField(required=False, label="Togli il logo caricato (torna al logo del portale)")

    class Meta:
        model = ImpostazioniEtichetta
        fields = [
            "larghezza_mm", "altezza_mm", "posizione_qr", "testo_qr",
            "mostra_logo", "logo", "logo_altezza_mm",
            "nome_dimensione_pt", "nome_maiuscolo", "riga_extra", "mostra_pittogrammi", "mostra_dpi",
            "testo_emergenza", "colore_fascia", "mostra_bordo",
        ]
        widgets = {
            "larghezza_mm": forms.NumberInput(attrs=_TESTO_ATTRS),
            "altezza_mm": forms.NumberInput(attrs=_TESTO_ATTRS),
            "logo_altezza_mm": forms.NumberInput(attrs=_TESTO_ATTRS),
            "nome_dimensione_pt": forms.NumberInput(attrs=_TESTO_ATTRS),
            "testo_qr": forms.TextInput(attrs=_TESTO_ATTRS),
            "testo_emergenza": forms.TextInput(attrs=_TESTO_ATTRS),
            "colore_fascia": forms.TextInput(attrs={**_TESTO_ATTRS, "placeholder": "#B91C1C"}),
            "logo": forms.ClearableFileInput(attrs={"accept": ".png,.jpg,.jpeg,.webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, (minimo, massimo) in LIMITI_ETICHETTA.items():
            campo = self.fields[nome]
            campo.validators += [MinValueValidator(minimo), MaxValueValidator(massimo)]
            campo.widget.attrs.update({"min": minimo, "max": massimo})
            campo.help_text = f"Da {minimo} a {massimo}."
        self.fields["colore_fascia"].validators.append(
            RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Usa un colore esadecimale, es. #B91C1C.")
        )
        # Il logo si toglie con la spunta dedicata, non con quella del widget.
        self.fields["logo"].widget = forms.FileInput(attrs={"accept": ".png,.jpg,.jpeg,.webp"})
        self.fields["logo"].help_text = "PNG, JPG o WEBP, massimo 2 MB. Senza logo caricato si usa quello del portale."

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and logo is not getattr(self.instance, "logo", None) and hasattr(logo, "content_type"):
            try:
                validate_extension_and_mime(
                    logo,
                    allowed_extensions=LOGO_ESTENSIONI,
                    allowed_mimes=LOGO_MIME,
                    max_bytes=LOGO_MAX_BYTES,
                    label="Logo",
                    allow_empty=False,
                )
            except UploadMimeValidationError as exc:
                raise forms.ValidationError(str(exc))
        return logo

    def clean_colore_fascia(self):
        return (self.cleaned_data.get("colore_fascia") or "").upper()

    def save(self, commit=True):
        impostazioni = super().save(commit=False)
        if self.cleaned_data.get("rimuovi_logo") and not self.files.get("logo"):
            impostazioni.logo = ""
        if commit:
            impostazioni.save()
        return impostazioni
