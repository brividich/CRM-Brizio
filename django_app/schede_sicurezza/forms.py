"""Form condivisi del modulo Schede di sicurezza.

``ProdottoChimicoForm`` e' l'unico posto in cui si dichiara *cosa* si chiede
quando si censisce un prodotto chimico: lo usano sia la schermata di
schede_sicurezza sia il form dell'asset "Prodotto chimico" (con prefisso), che
prima chiedevano due sottoinsiemi diversi degli stessi dati.
"""
from __future__ import annotations

from django import forms

from . import pittogrammi as ghs
from .models import ProdottoChimico

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
            "nome", "reparto", "fornitore", "produttore",
            "famiglia", "sottocategoria",
            "numero_interno", "codice_prodotto", "ubicazione", "quantita_presente",
            "pittogrammi", "dpi_obbligatori", "attivo",
        ]
        labels = {
            "nome": "Nome prodotto",
            "reparto": "Reparto",
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
            "reparto": forms.Select(attrs=_TESTO_ATTRS),
            "dpi_obbligatori": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Import in-funzione: le due app restano agganciate solo a runtime.
        from anagrafica.models import Reparto
        from dpi.models import CategoriaDPI

        self.fields["reparto"].queryset = Reparto.objects.filter(is_active=True).order_by("nome")
        self.fields["reparto"].empty_label = "Seleziona…"
        self.fields["nome"].required = True
        self.fields["reparto"].required = True

        dpi_field = self.fields["dpi_obbligatori"]
        dpi_field.queryset = CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome")
        dpi_field.label_from_instance = lambda cat: f"{cat.icona_emoji} {cat.nome}".strip()

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
        prodotto = super().save(commit=commit)
        if commit:
            self._propaga_pittogrammi(prodotto)
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
