from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from .models import (
    Audit,
    AuditAgenda,
    AuditEsito,
    AuditPersona,
    Auditor,
    ChecklistSezione,
    ProgrammaAudit,
    RigaProgramma,
)
from .services.audit import conflitti_imparzialita

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
_DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class AuditorForm(forms.ModelForm):
    class Meta:
        model = Auditor
        fields = [
            "interno", "user", "nome_esterno", "ente_esterno",
            "req_diploma", "req_norme", "req_tecniche_audit", "req_settore", "req_esperienza_2_anni",
            "requisiti_verificati_il", "audit_svolti_pregressi", "formazione_processi_il", "attivo",
        ]
        widgets = {"requisiti_verificati_il": _DATE, "formazione_processi_il": _DATE}


class ProgrammaAuditForm(forms.ModelForm):
    class Meta:
        model = ProgrammaAudit
        fields = ["anno", "rif_riesame", "periodi", "esclusioni_27002"]
        widgets = {
            "anno": forms.NumberInput(attrs={"min": 2020, "max": 2100}),
            "periodi": forms.Textarea(attrs={"rows": 3}),
            "esclusioni_27002": forms.Textarea(attrs={"rows": 3}),
        }


class RigaProgrammaForm(forms.ModelForm):
    class Meta:
        model = RigaProgramma
        fields = [
            "ordine", "area", "enti", "punti_9100", "punti_45001",
            "punti_27001", "punti_pdr125", "altre_normative", "note",
        ]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}


class AuditForm(forms.ModelForm):
    class Meta:
        model = Audit
        fields = [
            "numero", "programma", "righe", "tipo", "en9100", "iso45001", "iso27001", "pdr125",
            "lead_auditor", "auditor", "processi", "punti_norma", "procedure_criteri", "esclusioni",
            "data_inizio", "data_fine", "durata_stimata", "sede",
            "metodo_intervista", "metodo_esame_documenti", "metodo_osservazione_diretta",
            "metodo_verifica_evidenze", "imparzialita_deroga_motivo",
        ]
        widgets = {
            "data_inizio": _DATE,
            "data_fine": _DATE,
            "processi": forms.Textarea(attrs={"rows": 3}),
            "punti_norma": forms.Textarea(attrs={"rows": 3}),
            "procedure_criteri": forms.Textarea(attrs={"rows": 3}),
            "esclusioni": forms.Textarea(attrs={"rows": 2}),
            "imparzialita_deroga_motivo": forms.Textarea(attrs={"rows": 2}),
            "auditor": forms.CheckboxSelectMultiple(),
            "righe": forms.CheckboxSelectMultiple(),
        }
        help_texts = {
            "numero": "Lascia vuoto per la numerazione automatica RAIS-AAAA-NN.",
            "imparzialita_deroga_motivo": "Obbligatorio se un auditor appartiene al reparto/processo verificato.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero"].required = False
        self.fields["lead_auditor"].queryset = Auditor.objects.filter(attivo=True)
        self.fields["auditor"].queryset = Auditor.objects.filter(attivo=True)
        programma = self.data.get("programma") or getattr(self.instance, "programma_id", None)
        self.fields["righe"].queryset = RigaProgramma.objects.filter(programma_id=programma).order_by("ordine", "id")

    def clean(self):
        dati = super().clean()
        inizio, fine = dati.get("data_inizio"), dati.get("data_fine")
        if inizio and fine and fine < inizio:
            self.add_error("data_fine", "La data finale non può precedere quella iniziale.")
        if not any(dati.get(campo) for campo in ("en9100", "iso45001", "iso27001", "pdr125")):
            raise ValidationError("Seleziona almeno una norma di riferimento.")
        conflitti = conflitti_imparzialita(
            processi=dati.get("processi") or "",
            lead=dati.get("lead_auditor"),
            auditor=dati.get("auditor") or [],
        )
        if conflitti and not (dati.get("imparzialita_deroga_motivo") or "").strip():
            self.add_error(
                "imparzialita_deroga_motivo",
                "Possibile conflitto di imparzialità per: " + ", ".join(conflitti) + ". Indica la deroga motivata.",
            )
        return dati


class AuditPersonaForm(forms.ModelForm):
    class Meta:
        model = AuditPersona
        fields = ["nome", "funzione_ente", "email", "ruolo", "data_intervista", "intervistato"]
        widgets = {"data_intervista": _DATE}


class AuditAgendaForm(forms.ModelForm):
    class Meta:
        model = AuditAgenda
        fields = ["quando", "processo_area", "attivita", "auditor", "ordine"]
        widgets = {"quando": _DATETIME, "attivita": forms.Textarea(attrs={"rows": 2})}


class ComunicazioneAuditForm(forms.Form):
    metodo = forms.ChoiceField(choices=Audit.COM_CHOICES)
    deroga_motivo = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
        label="Motivo della deroga al preavviso (se necessario)",
    )


class AuditRapportoForm(forms.ModelForm):
    class Meta:
        model = Audit
        fields = ["giudizio", "punti_forza"]
        widgets = {
            "giudizio": forms.Textarea(attrs={"rows": 4}),
            "punti_forza": forms.Textarea(attrs={"rows": 4}),
        }


class AuditEsitoForm(forms.ModelForm):
    class Meta:
        model = AuditEsito
        fields = ["esito", "evidenze"]
        widgets = {"evidenze": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        dati = super().clean()
        if dati.get("esito") in {AuditEsito.ESITO_OFI, AuditEsito.ESITO_NC} and not (
            dati.get("evidenze") or ""
        ).strip():
            self.add_error("evidenze", "Descrivi l'evidenza che genera il rilievo.")
        return dati


class AuditDomandaAggiuntivaForm(forms.ModelForm):
    sezione = forms.ModelChoiceField(queryset=ChecklistSezione.objects.none())

    class Meta:
        model = AuditEsito
        fields = ["sezione", "punti_aggiuntivi", "testo_aggiuntivo", "esito", "evidenze"]
        widgets = {
            "testo_aggiuntivo": forms.Textarea(attrs={"rows": 3}),
            "evidenze": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, audit=None, **kwargs):
        super().__init__(*args, **kwargs)
        modello_ids = audit.esiti.filter(domanda__isnull=False).values_list(
            "domanda__sezione__modello_id", flat=True,
        ) if audit else []
        self.fields["sezione"].queryset = ChecklistSezione.objects.filter(
            modello_id__in=set(modello_ids),
        ).order_by("ordine")


class ValutazioneRddForm(forms.ModelForm):
    class Meta:
        model = Audit
        fields = ["valutazione_rdd", "car_autorizzate"]
        widgets = {
            "valutazione_rdd": forms.Textarea(attrs={"rows": 4}),
            "car_autorizzate": forms.Textarea(attrs={"rows": 2}),
        }
