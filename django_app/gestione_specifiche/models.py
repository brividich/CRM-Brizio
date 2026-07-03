"""Modelli dell'app gestione_specifiche (BUILD_SPEC §5).

Principio di retention: nulla viene cancellato fisicamente. Lo storico è dato
dalla catena revisioni, dagli stati terminali (S4/S6/S7/S8) e dall'audit
immutabile `EventoSpecifica` (con snapshot metadati nel payload).

Macchina a stati su `Specifica.stato` (FSMField, protected) — le transizioni
@transition sono definite in `state_machine.py` come metodi iniettati (F2).
"""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django_fsm import FSMField, GET_STATE, transition

from . import constants as C
from .storage import specifica_allegato_storage, upload_to_specifica, upload_to_timbro


def _verifica_periodica_mesi() -> int:
    cfg = getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}
    return int(cfg.get("VERIFICA_PERIODICA_MESI", 6))


class Specifica(models.Model):
    """Specifica/comunicazione/piano di qualità — entità principale del flusso."""

    codice = models.CharField("Codice", max_length=100, db_index=True)
    revisione = models.CharField("Revisione", max_length=30, blank=True, default="")
    titolo = models.CharField("Titolo", max_length=300)
    tipo = models.CharField(
        "Tipo", max_length=20, choices=C.TIPO_CHOICES, default=C.TIPO_SPECIFICA
    )
    fonte = models.CharField(
        "Fonte", max_length=20, choices=C.FONTE_CHOICES, default=C.FONTE_CLIENTE
    )
    # Riferimento cliente (per fonte=cliente) — usato dai filtri elenco (F7).
    cliente = models.CharField("Cliente", max_length=200, blank=True, default="", db_index=True)
    # TAG di processo a livello specifica (classificazione AI/umana, filtro F7).
    tag = models.CharField("TAG processo", max_length=120, blank=True, default="", db_index=True)
    # #5 — incaricato scelto all'inserimento (chi deve prenderla in carico); vuoto = gruppo IN1.
    incaricato = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="specifiche_incaricato", verbose_name="Incaricato",
    )

    stato = FSMField(
        "Stato", max_length=30, choices=C.STATO_CHOICES,
        default=C.STATO_BOZZA, protected=True, db_index=True,
    )
    # Stato salvato prima della SOSPENSIONE (S5), per il ripristino da sospeso.
    stato_precedente = models.CharField("Stato precedente (sospensione)", max_length=30, blank=True, default="")
    # Stato salvato prima dell'ERRORE tecnico (S9), per il ripristino da errore. Slot SEPARATO da
    # stato_precedente: sospensione ed errore possono annidarsi (S5→S9→S5) senza calpestarsi (M2).
    stato_pre_errore = models.CharField("Stato precedente (errore tecnico)", max_length=30, blank=True, default="")

    data_inserimento = models.DateTimeField("Data inserimento", auto_now_add=True)
    data_verifica = models.DateField("Data verifica periodica", null=True, blank=True, db_index=True)
    note = models.TextField("Note", blank=True, default="")

    revisione_precedente = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="revisioni_successive", verbose_name="Revisione precedente",
    )
    master = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="duplicati", verbose_name="Specifica master (per duplicati)",
    )

    allegato = models.FileField(
        "Allegato", upload_to=upload_to_specifica, storage=specifica_allegato_storage,
        null=True, blank=True, max_length=255,
    )
    # Modalità COLLEGAMENTO (alternativa alla copia in `allegato`): percorso UNC del PDF
    # sulla share aziendale — "single source of truth" per tutti, sempre allineato al master
    # (versionato/aggiornato lì, PDF protetti da Adobe). La view protetta lo serve on-demand
    # dalla share con allowlist + anti-traversal; nessuna copia locale. Se valorizzato ha la
    # precedenza sull'allegato locale nel download.
    percorso_esterno = models.CharField(
        "Percorso esterno (share UNC)", max_length=500, blank=True, default="",
    )

    # Hook nullable per agganci futuri al resto del HUB (decisione F0 #9) — NO FK.
    commessa_ref = models.CharField("Rif. commessa", max_length=100, blank=True, default="", db_index=True)
    famiglia_ref = models.CharField("Rif. famiglia", max_length=100, blank=True, default="", db_index=True)

    # Timer verifica periodica (F4): ultimo reminder inviato (ricorrente da data_verifica).
    verifica_reminder_inviata_at = models.DateTimeField("Ultimo reminder verifica", null=True, blank=True)

    created_at = models.DateTimeField("Creato il", auto_now_add=True)
    updated_at = models.DateTimeField("Aggiornato il", auto_now=True)

    class Meta:
        verbose_name = "Specifica"
        verbose_name_plural = "Specifiche"
        ordering = ["-data_inserimento", "codice"]
        indexes = [
            models.Index(fields=["codice"], name="gs_spec_codice_idx"),
            models.Index(fields=["stato"], name="gs_spec_stato_idx"),
            models.Index(fields=["tipo", "stato"], name="gs_spec_tipo_stato_idx"),
            models.Index(fields=["data_verifica"], name="gs_spec_dataverif_idx"),
        ]

    def __str__(self) -> str:
        rev = f" rev.{self.revisione}" if self.revisione else ""
        return f"{self.codice}{rev} — {self.titolo}"

    @property
    def is_attiva(self) -> bool:
        return self.stato in C.STATI_ATTIVI

    def snapshot_metadati(self) -> dict:
        """Snapshot metadati per il payload audit (ricostruzione punto-nel-tempo)."""
        try:
            esito_mod133 = self.mod133.esito
        except Exception:
            esito_mod133 = None
        return {
            "codice": self.codice,
            "revisione": self.revisione,
            "titolo": self.titolo,
            "tipo": self.tipo,
            "fonte": self.fonte,
            "cliente": self.cliente,
            "stato": self.stato,
            "data_verifica": self.data_verifica.isoformat() if self.data_verifica else None,
            "esito_mod133": esito_mod133,
        }

    # --- Macchina a stati (§6) ------------------------------------------------
    # Le transizioni cambiano `stato` (FSMField protected). L'audit
    # `EventoSpecifica` è creato centralmente dal signal post_transition
    # (state_machine.py); ogni transizione prepara attore/payload via
    # `_prep_evento` e genera ESATTAMENTE un evento.

    def _prep_evento(self, attore=None, **payload):
        self._evento_attore = attore
        self._evento_payload = payload

    @transition(field=stato, source=C.STATO_BOZZA, target=C.STATO_FLOW_DOWN)
    def avvia_flow_down(self, attore=None):
        """S1→S2: crea il MOD.133 vuoto (DM) e avvia il timer reminder/escalation."""
        mod, _ = MOD133.objects.get_or_create(specifica=self)
        mod.timer_anchor = timezone.now()
        mod.avviato_da = attore
        mod.save(update_fields=["timer_anchor", "avviato_da", "updated_at"])
        self._prep_evento(attore)

    @transition(field=stato, source=C.STATO_FLOW_DOWN, target=C.STATO_IN_VALIDITA)
    def approva_flow_down(self, attore=None):
        """S2→S3: guardia esito=approvato e approvatore≠compilatore; set
        data_verifica; supera automaticamente la revisione precedente in S3."""
        mod = MOD133.objects.filter(specifica=self).first()
        if mod is None:
            raise ValidationError("MOD.133 assente: impossibile approvare il flow-down.")
        if mod.esito != C.ESITO_APPROVATO:
            raise ValidationError("Il MOD.133 deve avere esito 'approvato' per l'approvazione.")
        if not mod.compilatore_id or not mod.approvatore_id:
            raise ValidationError("Compilatore e approvatore del MOD.133 sono obbligatori.")
        if mod.compilatore_id == mod.approvatore_id:
            raise ValidationError("L'approvatore deve essere diverso dal compilatore.")
        self.data_verifica = date.today() + relativedelta(months=_verifica_periodica_mesi())
        # Side-effect: superamento automatico della revisione precedente in validità.
        prev = self.revisione_precedente
        if prev is not None and prev.stato == C.STATO_IN_VALIDITA:
            prev.supera(attore=attore)
            prev.save()
        self._prep_evento(attore, data_verifica=self.data_verifica.isoformat())

    @transition(field=stato, source=C.STATO_IN_VALIDITA, target=C.STATO_SUPERATO)
    def supera(self, attore=None):
        """S3→S4: superamento (automatico alla nuova revisione approvata)."""
        self._prep_evento(attore, motivo="superamento_automatico")

    @transition(field=stato, source=C.STATO_FLOW_DOWN, target=C.STATO_RESPINTO)
    def respingi_flow_down(self, attore=None, motivo=""):
        """S2→S8: flow-down respinto/non applicabile."""
        self._prep_evento(attore, motivo=motivo)

    @transition(field=stato, source=[C.STATO_FLOW_DOWN, C.STATO_IN_VALIDITA],
                target=C.STATO_SOSPESO)
    def sospendi(self, attore=None, motivo="", data=None, riesame=None):
        """{S2,S3}→S5: motivo e data obbligatori; salva stato_precedente."""
        if not motivo:
            raise ValidationError("Il motivo di sospensione è obbligatorio.")
        if not data:
            raise ValidationError("La data di sospensione è obbligatoria.")
        # Pausa timer (F4): congela il conteggio reminder/escalation se in flow-down.
        if self.stato == C.STATO_FLOW_DOWN:
            mod = MOD133.objects.filter(specifica=self).first()
            if mod is not None and mod.timer_anchor and not mod.timer_pausa_at:
                mod.timer_pausa_at = timezone.now()
                mod.save(update_fields=["timer_pausa_at", "updated_at"])
        self.stato_precedente = self.stato
        self._prep_evento(attore, motivo=motivo, data=str(data), riesame=str(riesame) if riesame else None)

    @transition(field=stato, source=C.STATO_SOSPESO,
                target=GET_STATE(lambda self, **kw: self.stato_precedente,
                                 states=[C.STATO_FLOW_DOWN, C.STATO_IN_VALIDITA]))
    def ripristina(self, attore=None, motivo=""):
        """S5→(S2|S3) secondo stato_precedente; motivo obbligatorio."""
        if not motivo:
            raise ValidationError("Il motivo di ripristino è obbligatorio.")
        if self.stato_precedente not in (C.STATO_FLOW_DOWN, C.STATO_IN_VALIDITA):
            raise ValidationError("Stato precedente non valido per il ripristino.")
        # Ripresa timer (F4): sposta l'anchor in avanti della durata di pausa.
        if self.stato_precedente == C.STATO_FLOW_DOWN:
            mod = MOD133.objects.filter(specifica=self).first()
            if mod is not None and mod.timer_pausa_at and mod.timer_anchor:
                mod.timer_anchor = mod.timer_anchor + (timezone.now() - mod.timer_pausa_at)
                mod.timer_pausa_at = None
                mod.save(update_fields=["timer_anchor", "timer_pausa_at", "updated_at"])
        self._prep_evento(attore, motivo=motivo)

    @transition(field=stato,
                source=[C.STATO_BOZZA, C.STATO_FLOW_DOWN, C.STATO_SOSPESO, C.STATO_ERRORE_TECNICO],
                target=C.STATO_ANNULLATO)
    def annulla(self, attore=None, motivo=""):
        """{S1,S2,S5,S9}→S6: motivo obbligatorio."""
        if not motivo:
            raise ValidationError("Il motivo di annullamento è obbligatorio.")
        self._prep_evento(attore, motivo=motivo)

    @transition(field=stato, source=[C.STATO_BOZZA, C.STATO_FLOW_DOWN],
                target=C.STATO_DUPLICATO)
    def marca_duplicato(self, attore=None, motivo=""):
        """{S1,S2}→S7: riferimento master E motivo obbligatori (Matrice T2)."""
        if not self.master_id:
            raise ValidationError("Per marcare come duplicato è obbligatorio indicare la master.")
        if not motivo:
            raise ValidationError("Il motivo del duplicato è obbligatorio.")
        self._prep_evento(attore, master_id=self.master_id, motivo=motivo)

    @transition(field=stato, source="+", target=C.STATO_ERRORE_TECNICO)
    def errore_tecnico(self, attore=None, errore=None):
        """*→S9: salva lo stato pre-errore (slot dedicato); payload errore obbligatorio."""
        if not errore:
            raise ValidationError("Il payload di errore è obbligatorio.")
        self.stato_pre_errore = self.stato
        # Pausa timer flow-down (M3): il tempo in S9 non deve contare per reminder/escalation.
        # Se e' gia' in pausa (es. veniva da una sospensione), non tocca nulla.
        mod = MOD133.objects.filter(specifica=self).first()
        if mod is not None and mod.timer_anchor and not mod.timer_pausa_at:
            mod.timer_pausa_at = timezone.now()
            mod.save(update_fields=["timer_pausa_at", "updated_at"])
        self._prep_evento(attore, errore=errore)

    @transition(field=stato, source=C.STATO_ERRORE_TECNICO,
                target=GET_STATE(lambda self, **kw: self.stato_pre_errore,
                                 states=[C.STATO_BOZZA, C.STATO_FLOW_DOWN, C.STATO_IN_VALIDITA,
                                         C.STATO_SUPERATO, C.STATO_SOSPESO, C.STATO_ANNULLATO,
                                         C.STATO_DUPLICATO, C.STATO_RESPINTO]))
    def ripristina_da_errore(self, attore=None):
        """S9→stato precedente all'errore (usa lo slot dedicato, non calpesta la sospensione)."""
        if not self.stato_pre_errore:
            raise ValidationError("Stato precedente assente: impossibile ripristinare da errore.")
        # Ripresa timer (M3) SOLO se si torna al flow-down (S2). Se si torna in sospeso (S5) o in
        # un altro stato, il timer deve restare com'e' (in sospeso resta in pausa).
        if self.stato_pre_errore == C.STATO_FLOW_DOWN:
            mod = MOD133.objects.filter(specifica=self).first()
            if mod is not None and mod.timer_pausa_at and mod.timer_anchor:
                mod.timer_anchor = mod.timer_anchor + (timezone.now() - mod.timer_pausa_at)
                mod.timer_pausa_at = None
                mod.save(update_fields=["timer_anchor", "timer_pausa_at", "updated_at"])
        self._prep_evento(attore)


class MOD133(models.Model):
    """Modulo MOD.133 di flow-down requisiti, 1:1 con la specifica."""

    specifica = models.OneToOneField(
        Specifica, on_delete=models.CASCADE, related_name="mod133", verbose_name="Specifica"
    )
    compilatore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mod133_compilati", verbose_name="Compilatore",
    )
    approvatore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mod133_approvati", verbose_name="Approvatore",
    )
    data_chiusura_compilazione = models.DateTimeField("Chiusura compilazione", null=True, blank=True)
    data_approvazione = models.DateTimeField("Data approvazione", null=True, blank=True)
    esito = models.CharField(
        "Esito", max_length=20, choices=C.ESITO_CHOICES, null=True, blank=True
    )

    # Timer reminder/escalation (F4). avviato_da = DM che ha avviato il flow-down.
    avviato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mod133_avviati", verbose_name="Avviato da (DM)",
    )
    timer_anchor = models.DateTimeField("Inizio timer flow-down", null=True, blank=True)
    timer_pausa_at = models.DateTimeField("Timer in pausa da", null=True, blank=True)
    reminder_inviato = models.BooleanField("Reminder 7gg inviato", default=False)
    escalation_inviata = models.BooleanField("Escalation 14gg inviata", default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "MOD.133"
        verbose_name_plural = "MOD.133"

    def __str__(self) -> str:
        return f"MOD.133 — {self.specifica.codice}"


class RigaMOD133(models.Model):
    """Riga di flow-down del MOD.133 (griglia requisiti/impatti)."""

    mod133 = models.ForeignKey(
        MOD133, on_delete=models.CASCADE, related_name="righe", verbose_name="MOD.133"
    )
    ordine = models.PositiveSmallIntegerField("Ordine", default=0)
    rif_paragrafo = models.CharField("Rif. paragrafo specifica", max_length=100, blank=True, default="")
    argomento = models.CharField("Argomento", max_length=300, blank=True, default="")
    descrizione_modifiche = models.TextField("Descrizione modifiche", blank=True, default="")
    descrizione_impatto = models.TextField("Descrizione impatto", blank=True, default="")
    rif_doc_cn = models.CharField("Rif. documento CN", max_length=100, blank=True, default="")
    rif_paragrafo_cn = models.CharField("Rif. paragrafo CN", max_length=100, blank=True, default="")
    tag_processo = models.CharField("TAG processo", max_length=120, blank=True, default="")
    impatto_documenti = models.BooleanField("Impatto documenti", default=False)
    impatto_operativo = models.BooleanField("Impatto operativo", default=False)
    genera_ofi = models.BooleanField("Genera OFI", default=False)
    # Rif. al registro OFI/MOD.174: registro inesistente nel portale (BLOCKER B1)
    # → numero OFI legacy come intero nullable; sostituibile con FK additiva in futuro.
    ofi = models.PositiveIntegerField("Numero OFI (MOD.174)", null=True, blank=True)

    class Meta:
        verbose_name = "Riga MOD.133"
        verbose_name_plural = "Righe MOD.133"
        ordering = ["mod133", "ordine", "id"]

    def __str__(self) -> str:
        return f"Riga {self.ordine} — {self.argomento or self.rif_paragrafo}"


class AzioneOFI(models.Model):
    """Sotto-flusso di modifica documento CN generato da una riga MOD.133 (F5)."""

    riga_mod133 = models.ForeignKey(
        RigaMOD133, on_delete=models.CASCADE, related_name="azioni_ofi", verbose_name="Riga MOD.133"
    )
    # Numero OFI nel registro MOD.174 (vedi nota su RigaMOD133.ofi / BLOCKER B1).
    ofi = models.PositiveIntegerField("Numero OFI (MOD.174)", null=True, blank=True)
    # Registro documenti CN inesistente → CharField col codice documento.
    documento_cn = models.CharField("Documento CN", max_length=150, blank=True, default="")
    tipo_azione = models.CharField("Tipo azione", max_length=100, blank=True, default="")
    stato = models.CharField(
        "Stato azione", max_length=20, choices=C.AZIONE_OFI_STATO_CHOICES, default=C.AZIONE_OFI_BOZZA
    )
    modo_approvazione = models.CharField(
        "Modo approvazione", max_length=30, choices=C.MODO_APPROVAZIONE_CHOICES,
    )
    approvatore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="azioni_ofi_approvate", verbose_name="Approvatore",
    )
    data_approvazione = models.DateTimeField("Data approvazione", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Azione OFI"
        verbose_name_plural = "Azioni OFI"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        # Default del modo approvazione dalla configurazione (decisione F0 #2).
        if not self.modo_approvazione:
            cfg = getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}
            self.modo_approvazione = cfg.get("APPROVAZIONE_DOC_CN_MODE", C.APPROV_CAR_FLOW)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Azione OFI {self.ofi or '—'} su {self.documento_cn or 'doc CN'}"


class Distribuzione(models.Model):
    """Distribuzione tracciata di una specifica verso reparti/canali (F6)."""

    specifica = models.ForeignKey(
        Specifica, on_delete=models.CASCADE, related_name="distribuzioni", verbose_name="Specifica"
    )
    canale = models.CharField("Canale", max_length=20, choices=C.CANALE_CHOICES)
    destinatari = models.ManyToManyField(
        "anagrafica.Reparto", blank=True, related_name="distribuzioni_specifiche",
        verbose_name="Reparti destinatari",
    )
    presa_visione_richiesta = models.BooleanField("Presa visione richiesta", default=False)
    cartacea = models.BooleanField("Copia cartacea", default=False)
    n_copie_distribuite = models.PositiveSmallIntegerField("Copie distribuite", default=0)
    n_copie_ritirate = models.PositiveSmallIntegerField("Copie ritirate", default=0)
    deroga_giustificazione = models.TextField("Giustificazione deroga copie", blank=True, default="")
    data_distribuzione = models.DateTimeField("Data distribuzione", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Distribuzione"
        verbose_name_plural = "Distribuzioni"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Distribuzione {self.get_canale_display()} — {self.specifica.codice}"


class EventoSpecifica(models.Model):
    """Audit immutabile delle transizioni/eventi di una specifica (§5).

    Solo create: update e delete sono impediti a livello di modello.
    """

    specifica = models.ForeignKey(
        Specifica, on_delete=models.CASCADE, related_name="eventi", verbose_name="Specifica"
    )
    stato_da = models.CharField("Stato da", max_length=30, blank=True, default="")
    stato_a = models.CharField("Stato a", max_length=30)
    attore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="eventi_specifiche", verbose_name="Attore",
    )
    timestamp = models.DateTimeField("Timestamp", auto_now_add=True)
    trigger = models.CharField("Trigger", max_length=60, blank=True, default="")
    payload = models.JSONField("Payload", default=dict, blank=True)

    class Meta:
        verbose_name = "Evento specifica (audit)"
        verbose_name_plural = "Eventi specifica (audit)"
        ordering = ["specifica", "timestamp", "id"]
        indexes = [
            models.Index(fields=["specifica", "timestamp"], name="gs_evt_spec_ts_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("EventoSpecifica è immutabile: update non consentito.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("EventoSpecifica è immutabile: delete non consentito.")

    def __str__(self) -> str:
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.specifica_id}: {self.stato_da}→{self.stato_a}"


class ConfigPresaVisione(models.Model):
    """Configurazione presa visione per (tipo documento × reparto) — decisione F0 #3.

    `reparto` nullo = regola di default per quel tipo documento (tutti i reparti).
    """

    tipo_documento = models.CharField("Tipo documento", max_length=20, choices=C.TIPO_CHOICES)
    reparto = models.ForeignKey(
        "anagrafica.Reparto", null=True, blank=True, on_delete=models.CASCADE,
        related_name="config_presa_visione", verbose_name="Reparto (vuoto = tutti)",
    )
    richiesta = models.BooleanField("Presa visione richiesta", default=False)

    class Meta:
        verbose_name = "Config presa visione"
        verbose_name_plural = "Config presa visione"
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_documento", "reparto"], name="gs_configpv_tipo_reparto_uniq"
            ),
        ]

    def __str__(self) -> str:
        rep = self.reparto.nome if self.reparto else "TUTTI"
        return f"{self.get_tipo_documento_display()} / {rep}: {'sì' if self.richiesta else 'no'}"


class AutoApprovazioneConfig(models.Model):
    """#3 — Config (singleton) dell'auto-approvazione del MOD.133.

    Quando ``attiva``, il «Procedi con l'approvazione» approva il MOD.133 automaticamente a nome
    dell'``approvatore`` di riferimento (MSO): nell'audit risulta approvato da lui, con marcatore
    `auto=true`. La segregazione dei compiti resta (l'approvatore di record e' l'MSO, ≠ compilatore).
    """
    attiva = models.BooleanField("Auto-approvazione attiva", default=False)
    approvatore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", verbose_name="Approvatore di riferimento (MSO)",
    )
    nota = models.CharField("Nota", max_length=300, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Config auto-approvazione MOD.133"
        verbose_name_plural = "Config auto-approvazione MOD.133"

    def __str__(self) -> str:
        return f"Auto-approvazione {'ON' if self.attiva else 'OFF'}"

    @classmethod
    def get_config(cls) -> "AutoApprovazioneConfig":
        """Ritorna la config singleton (la crea vuota/OFF se non esiste)."""
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class NotificaConfig(models.Model):
    """#5 — Config (singleton) dell'assegnazione/notifica delle nuove specifiche.

    ``reparto_in1`` è il reparto (anagrafica ``area``) i cui membri formano il «gruppo IN1»;
    ``utenti_aggiuntivi`` sono persone extra assegnabili singolarmente (oltre al reparto);
    ``email_attiva`` invia anche l'email HTML oltre alla notifica in-app.
    """
    reparto_in1 = models.CharField("Reparto IN1", max_length=100, default="IN1",
                                   help_text="Reparto (area anagrafica) del gruppo IN1.")
    email_attiva = models.BooleanField("Invia anche email", default=True)
    utenti_aggiuntivi = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="+",
        verbose_name="Nomi aggiuntivi assegnabili",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Config notifiche/assegnazione"
        verbose_name_plural = "Config notifiche/assegnazione"

    def __str__(self) -> str:
        return f"NotificaConfig(reparto={self.reparto_in1})"

    @classmethod
    def get_config(cls) -> "NotificaConfig":
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class TimbroCapocommessa(models.Model):
    """#2 — Timbro «RICEVUTO» per capocommessa, sovrapposto al composito su ogni pagina.

    Il file va caricato **senza data** (la data odierna viene scritta dinamicamente in compose):
    contiene RICEVUTO + codice (es. CNOT102) + firma. Lo `utente` collega il timbro al
    capocommessa: in compilazione si usa il timbro del compilatore. Storage privato cifrato.
    """
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="timbri_capocommessa", verbose_name="Capocommessa",
    )
    codice = models.CharField("Codice timbro", max_length=50, help_text="Es. CNOT102")
    nome = models.CharField("Nome/descrizione", max_length=150, blank=True, default="")
    file = models.FileField("File timbro (senza data)", upload_to=upload_to_timbro,
                            storage=specifica_allegato_storage)
    attivo = models.BooleanField("Attivo", default=True)
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Timbro capocommessa"
        verbose_name_plural = "Timbri capocommessa"
        ordering = ["codice"]

    def __str__(self) -> str:
        return f"Timbro {self.codice}"


class ClienteCartellaShare(models.Model):
    """Mappatura persistente Cliente -> cartella reale sulla share (memoria stabile).

    Deriva la cartella di destinazione del composito dal ``cliente`` della specifica. Una volta
    confermata resta (le cartelle cambiano di rado, ~2-3/anno): la ``cartella`` e' l'etichetta
    RELATIVA alla radice della share (es. ``DUCATI``, ``FERRARI - FERRARI GES``), risolta a path
    reale al momento dell'uso (validata contro l'allowlist).
    """
    cliente = models.CharField("Cliente", max_length=200, unique=True)
    cartella = models.CharField("Cartella share (relativa alla radice)", max_length=300)
    attivo = models.BooleanField("Attivo", default=True)
    note = models.CharField("Note", max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mappatura cliente-cartella share"
        verbose_name_plural = "Mappature cliente-cartella share"
        ordering = ["cliente"]

    def __str__(self) -> str:
        return f"{self.cliente} -> {self.cartella}"
