"""Form e formset per il flusso MOD.133 (F3)."""
from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory

from . import constants as C
from .models import MOD133, RegistroOFI, RigaMOD133, Specifica

_TXT = {"class": "gs-input"}
_AREA = {"class": "gs-input", "rows": 2}


class PrivateClearableFileInput(forms.ClearableFileInput):
    """ClearableFileInput per allegati su storage privato (senza URL pubblico).

    Il widget standard, in rendering, chiama ``value.url`` per costruire il link
    "Attualmente: ...". Con ``PrivateSpecificaStorage`` quell'accesso solleva
    ``NotImplementedError`` (gli allegati non sono esposti su /media/). Qui
    sopprimiamo il link: mostriamo solo lo stato "file presente" + checkbox di
    rimozione, senza mai accedere a ``.url``. Stesso pattern di
    ``anagrafica.forms.PrivateClearableFileInput``.
    """

    template_name = "gestione_specifiche/widgets/private_clearable_file_input.html"

    def is_initial(self, value):
        # Lo standard fa `bool(value and getattr(value, "url", False))`, che
        # innesca l'accesso a .url. Qui basta che esista un file salvato.
        return bool(value and getattr(value, "name", None))

    def format_value(self, value):
        # Non restituiamo un oggetto con .url: evita che il template provi a
        # leggerlo. Il nome file basta per mostrare "file presente".
        if self.is_initial(value):
            return getattr(value, "name", "")
        return None


class SpecificaForm(forms.ModelForm):
    class Meta:
        model = Specifica
        fields = [
            "codice", "revisione", "titolo", "tipo", "fonte", "cliente",
            "tag", "note", "allegato", "commessa_ref", "famiglia_ref",
        ]
        widgets = {
            "codice": forms.TextInput(attrs=_TXT),
            "revisione": forms.TextInput(attrs=_TXT),
            "titolo": forms.TextInput(attrs=_TXT),
            "tipo": forms.Select(attrs=_TXT),
            "fonte": forms.Select(attrs=_TXT),
            "cliente": forms.TextInput(attrs=_TXT),
            "tag": forms.TextInput(attrs=_TXT),
            "note": forms.Textarea(attrs=_AREA),
            "allegato": PrivateClearableFileInput(attrs=_TXT),
            "commessa_ref": forms.TextInput(attrs=_TXT),
            "famiglia_ref": forms.TextInput(attrs=_TXT),
        }

    def clean(self):
        cleaned = super().clean()
        # M1: unicita' applicativa (codice, revisione) — blocca nuovi duplicati da UI. Il vincolo
        # DB (UniqueConstraint) sara' aggiunto dopo la deduplica del pregresso (comando
        # `specifiche_duplicati`).
        codice = (cleaned.get("codice") or "").strip()
        revisione = (cleaned.get("revisione") or "").strip()
        if codice:
            qs = Specifica.objects.filter(codice=codice, revisione=revisione)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "Esiste gia' una specifica con questo codice e questa revisione."
                )
        return cleaned


class RigaMOD133Form(forms.ModelForm):
    # Ordine non è più un campo visibile (la UI mostra un badge numerico): è
    # facoltativo e coerciato a 0 in clean, l'ordinamento riga rompe i pari per id.
    ordine = forms.IntegerField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = RigaMOD133
        fields = [
            "ordine", "rif_paragrafo", "argomento", "descrizione_modifiche",
            "descrizione_impatto", "rif_doc_cn", "rif_paragrafo_cn", "tag_processo",
            "impatto_documenti", "impatto_operativo", "genera_ofi",
        ]
        widgets = {
            "rif_paragrafo": forms.TextInput(attrs=_TXT),
            "argomento": forms.TextInput(attrs=_TXT),
            "descrizione_modifiche": forms.Textarea(attrs=_AREA),
            "descrizione_impatto": forms.Textarea(attrs=_AREA),
            "rif_doc_cn": forms.TextInput(attrs=_TXT),
            "rif_paragrafo_cn": forms.TextInput(attrs=_TXT),
            "tag_processo": forms.TextInput(attrs=_TXT),
        }

    def clean(self):
        cleaned = super().clean()
        # ordine facoltativo dalla UI → default 0 (l'ordinamento rompe i pari per id).
        if cleaned.get("ordine") in (None, ""):
            cleaned["ordine"] = 0
        # Griglia documenti obbligatoria solo se impatto_documenti=Y.
        if cleaned.get("impatto_documenti") and not (cleaned.get("rif_doc_cn") or "").strip():
            self.add_error("rif_doc_cn", "Obbligatorio quando l'impatto sui documenti è attivo.")
        return cleaned


RigaMOD133FormSet = inlineformset_factory(
    MOD133, RigaMOD133, form=RigaMOD133Form, extra=1, can_delete=True,
)


class ChiusuraCompilazioneForm(forms.Form):
    """Firma compilatore + assegnazione approvatore alla chiusura compilazione."""
    approvatore = forms.ModelChoiceField(
        queryset=None, label="Approvatore", widget=forms.Select(attrs=_TXT),
    )

    def __init__(self, *args, **kwargs):
        from django.contrib.auth import get_user_model
        super().__init__(*args, **kwargs)
        self.fields["approvatore"].queryset = get_user_model().objects.filter(is_active=True)


class ApprovazioneForm(forms.Form):
    esito = forms.ChoiceField(choices=C.ESITO_CHOICES, widget=forms.Select(attrs=_TXT))
    note = forms.CharField(required=False, widget=forms.Textarea(attrs=_AREA))


class DistribuzioneForm(forms.Form):
    canale = forms.ChoiceField(choices=C.CANALE_CHOICES, widget=forms.Select(attrs=_TXT))
    destinatari = forms.ModelMultipleChoiceField(
        queryset=None, required=False, widget=forms.CheckboxSelectMultiple,
        label="Reparti destinatari",
    )
    cartacea = forms.BooleanField(required=False, label="Copia cartacea")
    n_copie_distribuite = forms.IntegerField(min_value=0, initial=0, required=False,
                                             widget=forms.NumberInput(attrs={"class": "gs-input gs-input--num"}))
    n_copie_ritirate = forms.IntegerField(min_value=0, initial=0, required=False,
                                          widget=forms.NumberInput(attrs={"class": "gs-input gs-input--num"}))
    deroga_giustificazione = forms.CharField(required=False, widget=forms.Textarea(attrs=_AREA),
                                             label="Giustificazione deroga copie")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from anagrafica.models import Reparto
        self.fields["destinatari"].queryset = Reparto.objects.filter(is_active=True).order_by("nome")


class RegistroOFIForm(forms.ModelForm):
    """Inserimento/modifica manuale di una voce del registro OFI (MOD.174).

    Campi fedeli al MOD.174 SGI. ``numero`` NON è nel form: viene assegnato in
    view da ``registro_ofi.prossimo_numero()`` (spazio numeri condiviso con l'OFI
    legacy). L'origine resta vuota (voce del registro unico inserita a mano).
    """

    class Meta:
        model = RegistroOFI
        fields = [
            "ref", "data_apertura", "tipo", "modulo_origine",
            "norma_iso27001", "norma_iso45001", "norma_en9100", "rif_norma",
            "processo", "opportunita",
            "fase", "plan", "allegato_link", "do", "verifica", "act",
            "data_richiesta", "data_chiusura",
            "proprietario", "owner_processo", "priorita",
            "reminder_attivo", "note",
        ]
        # Nessuna classe sui widget: lo stile viene dal form-kit canonico `hub-`
        # (core/components/_hub_formkit.html), che stila input/select/textarea
        # dentro `.hub-field` per elemento. Qui solo gli attrs funzionali.
        _area = {"rows": 3}
        widgets = {
            "ref": forms.TextInput(),
            "modulo_origine": forms.TextInput(attrs={
                "list": "ofi-moduli",
                "placeholder": "es. produzione, qualità… (o scegli tra i già presenti)"}),
            "data_apertura": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "tipo": forms.Select(),
            "rif_norma": forms.TextInput(),
            "processo": forms.TextInput(),
            "opportunita": forms.Textarea(attrs=_area),
            "fase": forms.Select(),
            "plan": forms.Textarea(attrs=_area),
            "allegato_link": forms.TextInput(),
            "do": forms.Textarea(attrs=_area),
            "verifica": forms.Textarea(attrs=_area),
            "act": forms.Textarea(attrs=_area),
            "data_richiesta": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_chiusura": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "proprietario": forms.TextInput(),
            "owner_processo": forms.TextInput(),
            "priorita": forms.Select(),
            "note": forms.Textarea(attrs=_area),
        }
        labels = {
            "ref": "REF", "data_apertura": "DATA", "tipo": "OFI / NC",
            "modulo_origine": "Modulo di competenza",
            "rif_norma": "REF NORMA", "processo": "PROCESSO", "opportunita": "OPPORTUNITY",
            "fase": "Fase PDCA (P/D/C/A)", "plan": "PLAN", "allegato_link": "Allegato / Link",
            "do": "DO", "verifica": "CHECK", "act": "ACT",
            "data_richiesta": "DATA REQUIRED", "data_chiusura": "DATA CLOSED",
            "proprietario": "Proprietario", "owner_processo": "OWNER",
            "priorita": "Priorità", "reminder_attivo": "Reminder scadenza attivo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # data_apertura obbligatoria; default a oggi in inserimento (mai in modifica).
        if not self.instance.pk and not self.initial.get("data_apertura"):
            from django.utils import timezone
            self.fields["data_apertura"].initial = timezone.localdate()
