from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from .models import CategoriaScadenza, RegolaVisibilita, ScadenzaGenerica, VoceConfig

_INPUT = {"class": "sz-input"}


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = CategoriaScadenza
        fields = ["nome", "descrizione", "email_avviso", "preavviso_giorni", "ripeti_ogni_giorni",
                  "avvisa_dopo_scadenza", "is_active"]
        labels = {
            "nome": "Nome",
            "descrizione": "Descrizione",
            "email_avviso": "Destinatari del riepilogo mensile",
            "preavviso_giorni": "Preavviso (giorni)",
            "ripeti_ogni_giorni": "Ripeti l'avviso ogni (giorni)",
            "avvisa_dopo_scadenza": "Avvisa anche dopo la scadenza",
            "is_active": "Attiva",
        }
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 2, **_INPUT}),
            "email_avviso": forms.Textarea(attrs={"rows": 2, "placeholder": "nome@costruzioninovicrom.it, ...", **_INPUT}),
        }


class ScadenzaForm(forms.ModelForm):
    class Meta:
        model = ScadenzaGenerica
        fields = ["categoria", "titolo", "descrizione", "ubicazione", "ultimo_controllo", "validita_mesi",
                  "data_scadenza", "preavviso_giorni", "ripeti_ogni_giorni", "email_avviso", "responsabile",
                  "asset", "fornitore", "is_active"]
        labels = {
            "categoria": "Categoria",
            "titolo": "Attività",
            "descrizione": "Descrizione",
            "ubicazione": "Ubicazione",
            "ultimo_controllo": "Ultimo controllo",
            "validita_mesi": "Validità (mesi)",
            "data_scadenza": "Scadenza",
            "preavviso_giorni": "Preavviso (giorni)",
            "ripeti_ogni_giorni": "Ripeti l'avviso ogni (giorni)",
            "email_avviso": "Destinatari dell'avviso",
            "responsabile": "Responsabile",
            "asset": "Asset collegato",
            "fornitore": "Fornitore",
            "is_active": "Attiva",
        }
        help_texts = {
            "data_scadenza": "Vuota: si calcola da ultimo controllo + validità.",
            "validita_mesi": "Serve per «Rinnovato oggi»: la prossima scadenza si calcola da qui.",
            "email_avviso": "Vuoto: nessun avviso singolo, l'attività resta nel riepilogo mensile della categoria.",
            "responsabile": "La vede anche senza altri permessi e la trova con «Solo le mie».",
            "preavviso_giorni": "Vuoto: quello della categoria.",
            "ripeti_ogni_giorni": "Vuoto: quello della categoria.",
        }
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 2, **_INPUT}),
            "email_avviso": forms.Textarea(attrs={"rows": 2, "placeholder": "nome@costruzioninovicrom.it, ...", **_INPUT}),
            "ultimo_controllo": forms.DateInput(attrs={"type": "date", **_INPUT}, format="%Y-%m-%d"),
            "data_scadenza": forms.DateInput(attrs={"type": "date", **_INPUT}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, categorie_ammesse=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = CategoriaScadenza.objects.filter(is_active=True)
        if self.instance.pk:
            qs = CategoriaScadenza.objects.filter(pk=self.instance.categoria_id) | qs
        if categorie_ammesse is not None:
            qs = qs.filter(pk__in=categorie_ammesse)
        self.fields["categoria"].queryset = qs.distinct().order_by("nome")
        self.fields["responsabile"].queryset = get_user_model().objects.filter(is_active=True).order_by(
            "last_name", "first_name", "username")
        self.fields["responsabile"].label_from_instance = lambda u: u.get_full_name() or u.username
        self.fields["asset"].required = False
        self.fields["fornitore"].required = False
        from anagrafica.models import Fornitore
        from assets.models import Asset

        self.fields["asset"].queryset = Asset.objects.order_by("name")
        self.fields["fornitore"].queryset = Fornitore.objects.filter(is_active=True).order_by("ragione_sociale")

    def clean(self):
        dati = super().clean()
        if not dati.get("data_scadenza") and dati.get("ultimo_controllo") and dati.get("validita_mesi"):
            from .models import _add_months

            dati["data_scadenza"] = _add_months(dati["ultimo_controllo"], dati["validita_mesi"])
        return dati


class RinnovoForm(forms.Form):
    eseguito_il = forms.DateField(label="Eseguito il", widget=forms.DateInput(attrs={"type": "date", **_INPUT}, format="%Y-%m-%d"))
    nuova_scadenza = forms.DateField(
        label="Nuova scadenza", required=False,
        widget=forms.DateInput(attrs={"type": "date", **_INPUT}, format="%Y-%m-%d"),
        help_text="Vuota: data del controllo + validità dell'attività.",
    )
    note = forms.CharField(label="Note", required=False, widget=forms.Textarea(attrs={"rows": 2, **_INPUT}))
    allegato = forms.FileField(label="Allegato (verbale, certificato…)", required=False)

    MAX_MB = 20

    def clean_allegato(self):
        f = self.cleaned_data.get("allegato")
        if f and f.size > self.MAX_MB * 1024 * 1024:
            raise forms.ValidationError(f"File troppo grande (massimo {self.MAX_MB} MB).")
        return f


class VoceForm(forms.Form):
    attiva = forms.ChoiceField(
        label="Compare nello scadenzario",
        choices=[("", "Come la voce superiore"), ("1", "Sì"), ("0", "No")], required=False,
    )
    modalita = forms.ChoiceField(label="Chi la vede", choices=VoceConfig.MODALITA_CHOICES, required=False)


class RegolaForm(forms.Form):
    TIPO_CHOICES = [("ruolo_portale", "Ruolo del portale"), ("ruolo_aziendale", "Ruolo aziendale"), ("persona", "Persona")]

    tipo = forms.ChoiceField(label="Chi", choices=TIPO_CHOICES)
    ruolo_portale = forms.ModelChoiceField(label="Ruolo del portale", queryset=None, required=False)
    ruolo_aziendale = forms.ModelChoiceField(label="Ruolo aziendale", queryset=None, required=False)
    persona = forms.TypedChoiceField(label="Persona", choices=(), coerce=int, required=False, empty_value=None)
    livello = forms.ChoiceField(label="Può", choices=RegolaVisibilita.LIVELLO_CHOICES, initial=RegolaVisibilita.LIVELLO_VEDE)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from anagrafica.models import RuoloOperativo
        from core.models import AccessGroup

        self.fields["ruolo_portale"].queryset = AccessGroup.objects.filter(is_active=True).order_by("label")
        self.fields["ruolo_portale"].label_from_instance = lambda g: g.label
        self.fields["ruolo_aziendale"].queryset = RuoloOperativo.objects.filter(is_active=True).order_by("nome")
        self.fields["ruolo_aziendale"].label_from_instance = lambda r: r.nome
        self.fields["persona"].choices = [("", "—")] + persone_choices()

    def clean(self):
        dati = super().clean()
        tipo = dati.get("tipo")
        if tipo and not dati.get(tipo):
            raise forms.ValidationError("Scegli il ruolo o la persona.")
        return dati


def opzioni_chi() -> list[tuple[str, list[tuple[str, str]]]]:
    """Scelte del menu unico «Aggiungi»: valore ``tipo:id`` raggruppato per tipo."""
    from anagrafica.models import RuoloOperativo
    from core.models import AccessGroup

    return [
        ("Ruoli aziendali", [(f"ruolo_aziendale:{r.pk}", r.nome)
                             for r in RuoloOperativo.objects.filter(is_active=True).order_by("nome")]),
        ("Ruoli del portale", [(f"ruolo_portale:{g.pk}", g.label)
                               for g in AccessGroup.objects.filter(is_active=True).order_by("label")]),
        ("Persone", [(f"persona:{uid}", nome) for uid, nome in persone_choices()]),
    ]


def persone_choices() -> list[tuple[int, str]]:
    """Persone con utenza del portale: (utenti.id, «Cognome Nome»)."""
    from core.legacy_models import AnagraficaDipendente

    righe = AnagraficaDipendente.objects.filter(utente_id__isnull=False).values_list("utente_id", "cognome", "nome")
    esito = {}
    for uid, cognome, nome in righe:
        etichetta = " ".join(p for p in ((cognome or "").strip(), (nome or "").strip()) if p) or f"Utente {uid}"
        esito.setdefault(int(uid), etichetta)
    return sorted(esito.items(), key=lambda x: x[1].casefold())
