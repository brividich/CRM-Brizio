"""Form delle azioni FSM (sessione 3b) del modulo Suggestion Corner.

Un form per transizione che richiede input dall'utente. Le transizioni senza
input (avvia_do, avvia_check, inserisci_act, chiudi) non hanno form.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django import forms

from anagrafica.models import AreaAziendale, Reparto
from .models import SuggestionCorner

User = get_user_model()


def _reparti_qs():
    return Reparto.objects.filter(is_active=True).order_by("nome")


def _aree_qs():
    return AreaAziendale.objects.filter(is_active=True).select_related("reparto").order_by("nome")


class SegnalazionePubblicaForm(forms.Form):
    """Form pubblico anonimo (§5) — sostituisce Microsoft Forms.

    Provenienza = Reparto oppure Area (un'Area è sotto-articolazione di un
    Reparto): selettore a cascata, almeno uno dei due richiesto. Opzione anonima.
    Campo honeypot `website` nascosto via CSS: se compilato la request è bot.
    """
    reparto_provenienza = forms.ModelChoiceField(
        queryset=_reparti_qs(), required=False, empty_label="Reparto…",
        label="Reparto di provenienza",
    )
    area_provenienza = forms.ModelChoiceField(
        queryset=_aree_qs(), required=False,
        label="Area (opzionale)",
    )
    opportunity = forms.CharField(
        label="Opportunità di miglioramento", widget=forms.Textarea,
        max_length=5000,
    )
    anonima = forms.BooleanField(label="Invia in forma anonima", required=False)
    # Honeypot: gli utenti veri non lo vedono (nascosto via CSS), i bot sì.
    website = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"autocomplete": "off", "tabindex": "-1"}))

    def is_bot(self) -> bool:
        return bool(self.data.get("website"))

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("reparto_provenienza") or cleaned.get("area_provenienza")):
            raise forms.ValidationError("Indicare un reparto o un'area di provenienza.")
        return cleaned


class ModificaSegnalazioneForm(forms.ModelForm):
    """Modifica amministrativa della segnalazione (gestione interna al modulo,
    riservata al team SMS). Consente di correggere reparti, persone, esiti e
    testi PDCA. NON espone `stato` (FSMField protetto: si cambia solo via le
    azioni del workflow) né le date di sistema."""

    class Meta:
        model = SuggestionCorner
        fields = [
            "reparto_provenienza", "area_provenienza",
            "reparto_destinazione", "area_destinazione", "processo_libero",
            "opportunity", "stato_sms",
            "cliente_nome", "cliente_email",
            "incaricato", "controllore",
            "plan_testo", "do_testo", "esito_do",
            "check_testo", "esito_check", "act_testo",
        ]
        widgets = {
            "opportunity": forms.Textarea(attrs={"rows": 5}),
            "plan_testo": forms.Textarea(attrs={"rows": 3}),
            "do_testo": forms.Textarea(attrs={"rows": 3}),
            "check_testo": forms.Textarea(attrs={"rows": 3}),
            "act_testo": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "reparto_provenienza": "Reparto di provenienza",
            "area_provenienza": "Area di provenienza",
            "reparto_destinazione": "Reparto di destinazione",
            "area_destinazione": "Area di destinazione",
            "processo_libero": "Processo (testo libero)",
            "opportunity": "Opportunità di miglioramento",
            "stato_sms": "Classificazione SMS",
            "cliente_nome": "Cliente",
            "cliente_email": "Email cliente",
            "incaricato": "Incaricato (DO)",
            "controllore": "Controllore (CHECK)",
            "plan_testo": "PLAN — piano d'azione",
            "do_testo": "DO — descrizione esecuzione",
            "esito_do": "Esito DO",
            "check_testo": "CHECK — note di controllo",
            "esito_check": "Esito CHECK",
            "act_testo": "ACT — standardizzazione",
        }
        help_texts = {
            "processo_libero": "Compilare solo se il processo non è coperto dalle mappature.",
            "cliente_email": "Usata per la comunicazione al cliente sulle segnalazioni SMS Sì.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reparto_provenienza"].queryset = _reparti_qs()
        self.fields["reparto_destinazione"].queryset = _reparti_qs()
        self.fields["area_provenienza"].queryset = _aree_qs()
        self.fields["area_destinazione"].queryset = _aree_qs()
        for f in ("reparto_provenienza", "area_provenienza",
                  "reparto_destinazione", "area_destinazione"):
            self.fields[f].required = False
        for f in ("incaricato", "controllore"):
            self.fields[f].queryset = User.objects.filter(is_active=True).order_by("username")

    def clean(self):
        cleaned = super().clean()
        # Coerenza gerarchia: se si sceglie un'Area senza Reparto, il Reparto
        # padre è dedotto (il modello lo consolida in save(), qui solo per il form).
        if not (cleaned.get("reparto_provenienza") or cleaned.get("area_provenienza")):
            raise forms.ValidationError(
                {"reparto_provenienza": "Indicare un reparto o un'area di provenienza."}
            )
        return cleaned


class ConfigForm(forms.ModelForm):
    """Configurazione operativa del modulo (soglie solleciti/escalation, gruppo
    team SMS, email responsabile escalation). Singleton pk=1."""

    class Meta:
        from .models import SuggestionCornerConfig
        model = SuggestionCornerConfig
        fields = [
            "giorni_sollecito_1", "giorni_sollecito_2", "giorni_sollecito_3",
            "giorni_escalation_oltre_scadenza", "email_responsabile_escalation",
            "sms_team_group_name",
        ]
        labels = {
            "giorni_sollecito_1": "1° sollecito (giorni prima)",
            "giorni_sollecito_2": "2° sollecito (giorni prima)",
            "giorni_sollecito_3": "3° sollecito (giorni prima)",
            "giorni_escalation_oltre_scadenza": "Escalation (giorni oltre scadenza)",
            "email_responsabile_escalation": "Email responsabile (escalation)",
            "sms_team_group_name": "Gruppo team SMS",
        }


class ComunicazioneClienteForm(forms.Form):
    """Comunicazione al cliente per le segnalazioni SMS Sì (destinatario
    per-segnalazione). L'invio è manuale, riservato al team SMS."""
    cliente_nome = forms.CharField(label="Cliente", max_length=200, required=False)
    cliente_email = forms.EmailField(label="Email cliente")
    messaggio = forms.CharField(
        label="Messaggio (opzionale)", widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )


class ClassificaForm(forms.Form):
    stato_sms = forms.ChoiceField(
        choices=[
            (SuggestionCorner.StatoSMS.SMS_SI, "SMS Sì"),
            (SuggestionCorner.StatoSMS.SMS_NO, "SMS No"),
        ],
        label="Esito classificazione",
    )


class PlanForm(forms.Form):
    incaricato = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("username"),
        label="Incaricato (DO)",
    )
    controllore = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("username"),
        label="Controllore (CHECK)",
    )
    data_limite_esecuzione = forms.DateField(
        label="Scadenza esecuzione (DO)", widget=forms.DateInput(attrs={"type": "date"}),
    )
    data_limite_controllo = forms.DateField(
        label="Scadenza controllo (CHECK)", widget=forms.DateInput(attrs={"type": "date"}),
    )
    plan_testo = forms.CharField(label="Piano", widget=forms.Textarea, required=False)

    def clean(self):
        cleaned = super().clean()
        inc = cleaned.get("incaricato")
        ctrl = cleaned.get("controllore")
        if inc and ctrl and inc == ctrl:
            raise forms.ValidationError("Il controllore deve essere diverso dall'incaricato.")
        return cleaned


class CompletaDoForm(forms.Form):
    esito_do = forms.ChoiceField(
        choices=[
            (SuggestionCorner.EsitoAttivita.SI, "Sì"),
            (SuggestionCorner.EsitoAttivita.NO, "No"),
        ],
        label="Esito esecuzione",
    )
    do_testo = forms.CharField(label="Descrizione esecuzione", widget=forms.Textarea, required=False)


class DoRifareForm(forms.Form):
    nuova_data_limite_esecuzione = forms.DateField(
        label="Nuova scadenza esecuzione", widget=forms.DateInput(attrs={"type": "date"}),
    )


class CheckForm(forms.Form):
    check_testo = forms.CharField(label="Note controllo", widget=forms.Textarea, required=False)


class CheckRinviatoForm(forms.Form):
    nuova_data_limite_controllo = forms.DateField(
        label="Nuova scadenza controllo", widget=forms.DateInput(attrs={"type": "date"}),
    )
