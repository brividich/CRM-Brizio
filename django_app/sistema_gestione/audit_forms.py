from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import (
    Audit,
    AuditAgenda,
    AuditEsito,
    AuditPersona,
    Auditor,
    ChecklistSezione,
    ProgrammaAudit,
    Processo,
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
            "processo", "ordine", "area", "enti", "punti_9100", "punti_45001",
            "punti_27001", "punti_pdr125", "altre_normative", "note",
        ]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["processo"].required = True
        self.fields["processo"].queryset = Processo.objects.filter(Q(attivo=True) | Q(pk=self.instance.processo_id))
        for nome in ("area", "enti", "punti_9100", "punti_45001", "punti_27001", "punti_pdr125", "altre_normative"):
            self.fields[nome].required = False
            self.fields[nome].widget = forms.HiddenInput()

    def clean(self):
        dati = super().clean()
        processo = dati.get("processo")
        if processo:
            dati.update(area=f"{processo} (Rev.{processo.revisione})"[:255], enti=processo.enti, altre_normative=processo.procedure[:500])
            for nome in ("punti_9100", "punti_45001", "punti_27001", "punti_pdr125"):
                dati[nome] = getattr(processo, nome)
        return dati


class AuditForm(forms.ModelForm):
    class Meta:
        model = Audit
        fields = [
            "numero", "programma", "righe", "tipo", "en9100", "iso45001", "iso27001", "pdr125",
            "lead_auditor", "auditor", "processi_catalogo", "processi", "punti_norma", "procedure_criteri", "esclusioni",
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
        for nome, label in {"en9100": "EN 9100", "iso45001": "ISO 45001", "iso27001": "ISO/IEC 27001", "pdr125": "UNI/PdR 125", "righe": "Righe del programma (facoltativo)"}.items():
            self.fields[nome].label = label
        self.fields["processi"].required = False
        self.fields["processi"].widget = forms.HiddenInput()
        self.fields["processi_catalogo"].required = True
        selezionati = self.instance.processi_catalogo.values_list("pk", flat=True) if self.instance.pk else []
        self.fields["processi_catalogo"].queryset = Processo.objects.filter(Q(attivo=True) | Q(pk__in=selezionati))
        self.fields["processi_catalogo"].label = "Processi da verificare"
        self.fields["processi_catalogo"].help_text = "Seleziona dal catalogo. Codici e revisioni vengono conservati nel piano; criteri vuoti vengono compilati dalle schede."
        self.fields["processi_catalogo"].widget = forms.CheckboxSelectMultiple(choices=self.fields["processi_catalogo"].choices)
        self.fields["lead_auditor"].queryset = Auditor.objects.filter(attivo=True)
        self.fields["auditor"].queryset = Auditor.objects.filter(attivo=True)
        programma = self.data.get("programma") if self.is_bound else self.initial.get("programma", self.instance.programma_id)
        programma = getattr(programma, "pk", programma)
        try:
            programma = int(programma) if programma else None
        except (TypeError, ValueError):
            programma = None
        self.fields["righe"].queryset = RigaProgramma.objects.filter(programma_id=programma).order_by("ordine", "id")

    def clean(self):
        dati = super().clean()
        processi = list(dati.get("processi_catalogo") or [])
        precedenti = {p["id"]: p for p in (self.instance.processi_snapshot or [])}
        schede = [precedenti.get(p.pk, p.snapshot()) for p in processi]
        if processi:
            dati["processi"] = "\n".join(f'{p["codice"]} - {p["nome"]} (Rev.{p["revisione"]})' for p in schede)
            if not dati.get("procedure_criteri"):
                dati["procedure_criteri"] = "\n".join(f'{p["codice"]}: {p["procedure"]}' for p in schede if p["procedure"])
            if not dati.get("punti_norma"):
                dati["punti_norma"] = "\n".join(
                    f'{p["codice"]} - {label}: {p[campo]}' for p in schede
                    for flag, campo, label in [("en9100", "punti_9100", "EN 9100"), ("iso45001", "punti_45001", "ISO 45001"),
                                               ("iso27001", "punti_27001", "ISO 27001"), ("pdr125", "punti_pdr125", "PdR 125")]
                    if dati.get(flag) and p[campo])
        self.instance.processi_snapshot = schede
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
        utenti_team = {a.user_id for a in [dati.get("lead_auditor"), *list(dati.get("auditor") or [])] if a and a.user_id}
        conflitti.extend(str(p) for p in processi if p.responsabile_id in utenti_team)
        if conflitti and not (dati.get("imparzialita_deroga_motivo") or "").strip():
            self.add_error(
                "imparzialita_deroga_motivo",
                "Possibile conflitto di imparzialità per: " + ", ".join(conflitti) + ". Indica la deroga motivata.",
            )
        return dati

    @property
    def sezioni(self):
        gruppi = [
            ("1. Campo di audit", "Scegli i processi dal catalogo e le norme applicabili.",
             "numero programma righe tipo processi_catalogo en9100 iso45001 iso27001 pdr125"),
            ("2. Criteri e limiti", "Lascia i criteri vuoti per usare quelli delle schede processo. Precisa le esclusioni.",
             "punti_norma procedure_criteri esclusioni"),
            ("3. Team e indipendenza", "Assegna il Lead Auditor e il team; motiva eventuali conflitti.",
             "lead_auditor auditor imparzialita_deroga_motivo"),
            ("4. Date e metodo", "Salva il piano, poi completa persone e agenda dalla scheda audit.",
             "data_inizio data_fine durata_stimata sede metodo_intervista metodo_esame_documenti metodo_osservazione_diretta metodo_verifica_evidenze"),
        ]
        return [{"titolo": titolo, "aiuto": aiuto, "campi": [self[n] for n in nomi.split()]} for titolo, aiuto, nomi in gruppi]


class ProcessoForm(forms.ModelForm):
    motivo = forms.CharField(max_length=500, label="Motivo della revisione", help_text="Descrivi cosa cambia. Per una nuova scheda: prima emissione.")
    versione = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Processo
        fields = ["codice", "nome", "categoria", "responsabile", "enti", "scopo", "input", "output",
                  "rischi", "indicatori", "procedure", "punti_9100", "punti_45001", "punti_27001",
                  "punti_pdr125", "frequenza_mesi", "attivo"]
        widgets = {nome: forms.Textarea(attrs={"rows": 3}) for nome in
                   ("scopo", "input", "output", "rischi", "indicatori", "procedure")}
        labels = {"input": "Ingressi", "output": "Risultati attesi", "indicatori": "Indicatori, obiettivi e frequenza di misura",
                  "procedure": "Procedure e documenti di riferimento (codice e revisione)", "frequenza_mesi": "Frequenza audit (mesi)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["versione"] = self.instance.revisione if self.instance.pk else 0
        for nome in ("responsabile", "scopo", "input", "output", "rischi", "indicatori", "procedure"):
            self.fields[nome].required = True
        self.fields["frequenza_mesi"].min_value = 1
        self.fields["frequenza_mesi"].max_value = 120

    def clean_frequenza_mesi(self):
        valore = self.cleaned_data["frequenza_mesi"]
        if not 1 <= valore <= 120:
            raise ValidationError("Indica una frequenza fra 1 e 120 mesi.")
        return valore

    def clean_codice(self):
        codice = self.cleaned_data["codice"].strip().upper()
        if Processo.objects.filter(codice__iexact=codice).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Codice processo già utilizzato.")
        return codice

    def clean(self):
        dati = super().clean()
        if self.instance.pk and dati.get("versione") != self.instance.revisione:
            raise ValidationError("La scheda è stata aggiornata da un altro utente. Ricarica prima di salvare.")
        return dati


class AuditPersonaForm(forms.ModelForm):
    class Meta:
        model = AuditPersona
        fields = ["nome", "funzione_ente", "email", "ruolo", "data_intervista", "intervistato"]
        widgets = {"data_intervista": _DATE}


class AuditAgendaForm(forms.ModelForm):
    class Meta:
        model = AuditAgenda
        fields = ["quando", "processo", "processo_area", "attivita", "auditor", "ordine"]
        widgets = {"quando": _DATETIME, "attivita": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, audit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit = audit
        self.fields["processo"].queryset = audit.processi_catalogo.all() if audit else Processo.objects.none()
        self.fields["processo"].required = True
        self.fields["processo_area"].required = False
        self.fields["processo_area"].widget = forms.HiddenInput()
        self.fields["attivita"].required = True
        self.fields["attivita"].help_text = "Cosa verificherai, su quale campione e con quale metodo."

    def clean(self):
        dati = super().clean()
        processo = dati.get("processo")
        if processo:
            scheda = next((p for p in self.audit.processi_snapshot if p["id"] == processo.pk), None)
            dati["processo_area"] = (f'{scheda["codice"]} - {scheda["nome"]}' if scheda else str(processo))[:255]
        quando = dati.get("quando")
        if quando and self.audit:
            from django.utils import timezone
            giorno = timezone.localtime(quando).date()
            if not self.audit.data_inizio <= giorno <= (self.audit.data_fine or self.audit.data_inizio):
                self.add_error("quando", "L'attività deve ricadere nelle date del piano.")
        return dati


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
