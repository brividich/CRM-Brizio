from __future__ import annotations

from django import forms

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from .models import SoaVoce, ThreatIntelligence

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class _OfiChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        testo = " ".join(str(obj.opportunita or "").split())
        return f"OFI n. {obj.numero} · {obj.get_tipo_display()} · {testo[:70]}"


def _ofi_queryset():
    from gestione_specifiche.models import RegistroOFI

    return RegistroOFI.objects.order_by("-numero")


class SoaVoceForm(forms.ModelForm):
    ofi = _OfiChoiceField(queryset=None, required=False, label="Voce del Registro OFI collegata")

    class Meta:
        model = SoaVoce
        fields = [
            "livello", "vulnerabilita", "riferimenti", "giustificazione",
            "obbligo_legislativo", "obbligo_normativo", "obbligo_regolatorio", "obbligo_cliente", "buona_pratica",
            "azione", "responsabile", "scadenza", "livello_atteso", "ofi",
        ]
        labels = {
            "livello": "Applicazione del controllo (0-4)",
            "vulnerabilita": "Vulnerabilità",
            "riferimenti": "Riferimenti (procedure, moduli, evidenze)",
            "giustificazione": "Giustificazione dell'inclusione o dell'esclusione",
            "obbligo_legislativo": "Legislativo",
            "obbligo_normativo": "Normativo",
            "obbligo_regolatorio": "Regolatorio",
            "obbligo_cliente": "Cliente",
            "buona_pratica": "Buona pratica",
            "azione": "Azione del piano di trattamento",
            "responsabile": "Responsabile dell'azione",
            "scadenza": "Scadenza",
            "livello_atteso": "Livello atteso dopo l'azione",
        }
        widgets = {
            "riferimenti": forms.Textarea(attrs={"rows": 3}),
            "giustificazione": forms.Textarea(attrs={"rows": 4}),
            "azione": forms.Textarea(attrs={"rows": 3}),
            "scadenza": _DATE,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ofi"].queryset = _ofi_queryset()

    def clean(self):
        dati = super().clean()
        livello = dati.get("livello")
        if livello == 0 and not (dati.get("giustificazione") or "").strip():
            self.add_error("giustificazione", "Un controllo escluso richiede la giustificazione dell'esclusione.")
        if (dati.get("azione") or "").strip() and not dati.get("scadenza"):
            self.add_error("scadenza", "Indica la scadenza dell'azione.")
        return dati


class ThreatIntelligenceForm(forms.ModelForm):
    ofi = _OfiChoiceField(queryset=None, required=False, label="Voce del Registro OFI collegata")

    class Meta:
        model = ThreatIntelligence
        fields = ["data", "fonte", "informazione", "esito", "azione", "note", "ofi"]
        labels = {"informazione": "Informazione / minaccia", "esito": "Esito della valutazione", "azione": "Azione intrapresa"}
        widgets = {
            "data": _DATE,
            "informazione": forms.Textarea(attrs={"rows": 3}),
            "azione": forms.Textarea(attrs={"rows": 2}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ofi"].queryset = _ofi_queryset()

    def clean(self):
        dati = super().clean()
        if dati.get("esito") == ThreatIntelligence.ESITO_AZIONE and not (dati.get("azione") or "").strip():
            self.add_error("azione", "Descrivi l'azione richiesta.")
        return dati


class CopiaFirmataForm(forms.Form):
    file = forms.FileField(label="Copia firmata (PDF)")

    def clean_file(self):
        caricato = self.cleaned_data["file"]
        try:
            validate_extension_and_mime(
                caricato,
                allowed_extensions={".pdf"},
                allowed_mimes={"application/pdf"},
                max_bytes=20 * 1024 * 1024,
                label="Copia firmata",
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return caricato
