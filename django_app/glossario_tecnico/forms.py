from __future__ import annotations

from django import forms

from .models import Termine, Variante


class TermineForm(forms.ModelForm):
    class Meta:
        model = Termine
        fields = [
            "termine", "termine_en", "categoria", "definizione", "simbolo",
            "esempio_disegno", "norma_rif", "usa_nel_rag", "note_interne",
        ]
        widgets = {
            "definizione": forms.Textarea(attrs={"rows": 4, "maxlength": 600}),
            "note_interne": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "definizione": "Con parole nostre, al massimo ~600 caratteri. Niente testo di norme né valori di tabelle.",
            "norma_rif": "Solo il codice, es. «ISO 1101».",
            "note_interne": "Non vengono mai mostrate all'assistente.",
        }


class VarianteForm(forms.ModelForm):
    class Meta:
        model = Variante
        fields = ["testo", "tipo", "lingua"]
        widgets = {"lingua": forms.TextInput(attrs={"size": 3, "maxlength": 2})}


class PropostaForm(forms.Form):
    """Correzione di una proposta AI prima di accettarla."""

    termine = forms.CharField(max_length=150)
    categoria = forms.ChoiceField(choices=Termine.CATEGORIE)
    definizione = forms.CharField(widget=forms.Textarea(attrs={"rows": 4, "maxlength": 600}), max_length=600)
    varianti = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Una per riga, nel formato tipo:testo (es. traduzione:spot face).",
    )

    def clean_varianti(self):
        righe = [r.strip() for r in (self.cleaned_data.get("varianti") or "").splitlines() if r.strip()]
        tipi = {t for t, _ in Variante.TIPI}
        for riga in righe:
            tipo, sep, testo = riga.partition(":")
            if not sep or tipo.strip() not in tipi or not testo.strip():
                raise forms.ValidationError(f"Riga non valida: «{riga}» (tipo:testo, tipi: {', '.join(sorted(tipi))}).")
        return [f"{r.partition(':')[0].strip()}:{r.partition(':')[2].strip()}" for r in righe]
