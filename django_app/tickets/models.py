from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from django.db import IntegrityError, models, transaction

from .storage import PrivateTicketStorage

# ---------------------------------------------------------------------------
# Costanti condivise
# ---------------------------------------------------------------------------

class TipoTicket(models.TextChoices):
    IT  = "IT",  "Ticket IT"
    MAN = "MAN", "Ticket Manutenzione"


class StatoTicket(models.TextChoices):
    APERTA      = "APERTA",      "Aperta"
    IN_CARICO   = "IN_CARICO",   "In carico"
    IN_ATTESA   = "IN_ATTESA",   "In attesa"
    RISOLTO     = "RISOLTO",     "Risolto"
    CHIUSO      = "CHIUSO",      "Chiuso"
    ANNULLATO   = "ANNULLATO",   "Annullato"


class TipoFermo(models.TextChoices):
    NESSUNO = "NESSUNO", "Nessun fermo"
    PARZIALE = "PARZIALE", "Fermo parziale"
    TOTALE   = "TOTALE",   "Fermo totale"


class EsitoIntervento(models.TextChoices):
    IN_CORSO          = "IN_CORSO",          "In corso"
    COMPLETATO        = "COMPLETATO",        "Completato"
    SOSPESO           = "SOSPESO",           "Sospeso"
    RICHIEDE_RICAMBI  = "RICHIEDE_RICAMBI",  "Richiede ricambi"


class PrioritaTicket(models.TextChoices):
    BASSA   = "BASSA",   "Bassa"
    MEDIA   = "MEDIA",   "Media"
    ALTA    = "ALTA",    "Alta"
    URGENTE = "URGENTE", "Urgente"


CATEGORIE_IT = [
    ("PC",        "PC / Notebook"),
    ("SERVER",    "Server"),
    ("STAMPANTE", "Stampante / Scanner"),
    ("RETE",      "Rete / Connettività"),
    ("SOFTWARE",  "Software / Sistema Operativo"),
    ("TELEFONIA", "Telefonia"),
    ("ALTRO_IT",  "Altro IT"),
]

CATEGORIE_MAN = [
    ("CNC",        "Macchina CNC"),
    ("MACCHINARIO","Macchinario generico"),
    ("STRUTTURALE","Strutturale / Edificio"),
    ("GENERICA",   "Generica"),
    ("ALTRO_MAN",  "Altro Manutenzione"),
]


# ---------------------------------------------------------------------------
# Categorie ticket dinamiche
# ---------------------------------------------------------------------------

class CategoriaTicket(models.Model):
    """Categorie configurabili per i ticket IT e MAN, gestite dall'admin assets."""

    tipo      = models.CharField(max_length=5, choices=TipoTicket.choices, db_index=True)
    codice    = models.CharField(max_length=30, unique=True)
    etichetta = models.CharField(max_length=100)
    ordine    = models.PositiveIntegerField(default=0)
    attivo    = models.BooleanField(default=True)

    class Meta:
        ordering = ["tipo", "ordine", "etichetta"]
        verbose_name = "Categoria ticket"
        verbose_name_plural = "Categorie ticket"

    def __str__(self) -> str:
        return f"[{self.tipo}] {self.etichetta}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        _invalidate_categoria_label_cache()

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        _invalidate_categoria_label_cache()
        return result


_CATEGORIA_LABEL_CACHE_KEY = "ticket_categoria_label_map"
_CATEGORIA_LABEL_CACHE_TTL = 300  # 5 minuti


def _get_categoria_label_map() -> dict[str, str]:
    """Dizionario codice→etichetta per tutte le categorie, con cache Django (5 min).
    Una sola query DB per miss di cache; 0 query per tutti i ticket successivi."""
    from django.core.cache import cache
    cached = cache.get(_CATEGORIA_LABEL_CACHE_KEY)
    if cached is not None:
        return cached
    db_map = dict(CategoriaTicket.objects.values_list("codice", "etichetta"))
    result: dict[str, str] = {**dict(CATEGORIE_IT + CATEGORIE_MAN), **db_map}
    cache.set(_CATEGORIA_LABEL_CACHE_KEY, result, _CATEGORIA_LABEL_CACHE_TTL)
    return result


def _invalidate_categoria_label_cache() -> None:
    from django.core.cache import cache
    cache.delete(_CATEGORIA_LABEL_CACHE_KEY)


def get_categorie(tipo: str) -> list[tuple[str, str]]:
    """Restituisce le categorie attive per il tipo indicato (IT o MAN).
    Se la tabella è vuota per quel tipo, usa il fallback hardcoded."""
    qs = list(
        CategoriaTicket.objects.filter(tipo=tipo, attivo=True)
        .order_by("ordine", "etichetta")
        .values_list("codice", "etichetta")
    )
    if qs:
        return qs
    return CATEGORIE_IT if tipo == TipoTicket.IT else CATEGORIE_MAN


def _next_ticket_number(tipo: str, year: int | None = None) -> str:
    """Genera il numero progressivo per l'anno indicato (default: anno corrente).
    Formato: IT-YYYY-NNNN  /  MAN-YYYY-NNNN
    """
    if year is None:
        year = datetime.now(dt_timezone.utc).year
    prefix = f"{tipo}-{year}-"
    last = (
        Ticket.objects.filter(numero_ticket__startswith=prefix)
        .order_by("-numero_ticket")
        .values_list("numero_ticket", flat=True)
        .first()
    )
    if last:
        try:
            seq = int(last.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


# ---------------------------------------------------------------------------
# Ticket
# ---------------------------------------------------------------------------

class Ticket(models.Model):
    numero_ticket   = models.CharField(max_length=30, unique=True, editable=False)
    tipo            = models.CharField(max_length=5,  choices=TipoTicket.choices, db_index=True)
    titolo          = models.CharField(max_length=300)
    descrizione     = models.TextField()
    categoria       = models.CharField(max_length=30)

    priorita        = models.CharField(
        max_length=10,
        choices=PrioritaTicket.choices,
        default=PrioritaTicket.MEDIA,
    )
    incide_sicurezza = models.BooleanField(default=False)

    stato = models.CharField(
        max_length=15,
        choices=StatoTicket.choices,
        default=StatoTicket.APERTA,
        db_index=True,
    )

    # Asset link (opzionale)
    asset = models.ForeignKey(
        "assets.Asset",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    asset_descrizione_libera = models.CharField(max_length=300, blank=True)

    # Richiedente (denormalizzato)
    richiedente_nome            = models.CharField(max_length=200)
    richiedente_email           = models.CharField(max_length=200, blank=True)
    richiedente_legacy_user_id  = models.IntegerField(null=True, blank=True)

    # Assegnazione
    assegnato_a     = models.CharField(max_length=200, blank=True)
    assegnato_email = models.CharField(max_length=200, blank=True)
    delegato_fornitore = models.ForeignKey(
        "anagrafica.Fornitore",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets_delegati",
    )

    note_interne = models.TextField(blank=True)

    # SharePoint
    sharepoint_item_id = models.CharField(max_length=100, blank=True)

    # ── Campi analitici per KPI ──────────────────────────────────────────────
    componente          = models.CharField(max_length=200, blank=True,
                            help_text="Componente/sotto-sistema interessato (es. Mandrino, Inverter, PLC)")
    causa_radice        = models.CharField(max_length=500, blank=True,
                            help_text="Causa radice identificata a chiusura")
    tipo_fermo          = models.CharField(
                            max_length=10,
                            choices=TipoFermo.choices,
                            default=TipoFermo.NESSUNO,
                            help_text="Tipo di fermo produzione causato dal guasto")
    ore_fermo_macchina  = models.DecimalField(
                            max_digits=7, decimal_places=2,
                            null=True, blank=True,
                            help_text="Ore di fermo macchina totali")
    data_presa_in_carico = models.DateTimeField(null=True, blank=True,
                            help_text="Timestamp automatico del primo passaggio IN_CARICO")
    data_primo_intervento = models.DateTimeField(null=True, blank=True,
                            help_text="Timestamp del primo TicketIntervento registrato")
    risolto_da_nome     = models.CharField(max_length=200, blank=True,
                            help_text="Tecnico/manutentore che ha risolto il ticket")
    ricorrente          = models.BooleanField(default=False,
                            help_text="Il problema si è già verificato in passato")
    data_prevista_risoluzione = models.DateField(
                            null=True, blank=True,
                            help_text="Data prevista risoluzione (valorizzata quando il ticket è IN_ATTESA)")
    ticket_origine      = models.ForeignKey(
                            "self",
                            null=True, blank=True,
                            on_delete=models.SET_NULL,
                            related_name="ticket_ricorrenti",
                            help_text="Ticket precedente da cui deriva (se ricorrente)")
    # ────────────────────────────────────────────────────────────────────────

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Ticket"
        verbose_name_plural = "Ticket"

    def save(self, *args, **kwargs):
        # Regola sicurezza: incide_sicurezza → URGENTE locked
        if self.incide_sicurezza:
            self.priorita = PrioritaTicket.URGENTE
        if self.numero_ticket:
            return super().save(*args, **kwargs)
        max_attempts = 5
        for attempt in range(max_attempts):
            self.numero_ticket = _next_ticket_number(self.tipo)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.numero_ticket = ""
                if not self._state.adding or attempt == max_attempts - 1:
                    raise

    def __str__(self):
        return f"[{self.numero_ticket}] {self.titolo}"

    @property
    def label_stato(self) -> str:
        return dict(StatoTicket.choices).get(self.stato, self.stato)

    @property
    def label_priorita(self) -> str:
        return dict(PrioritaTicket.choices).get(self.priorita, self.priorita)

    @property
    def label_tipo(self) -> str:
        return dict(TipoTicket.choices).get(self.tipo, self.tipo)

    @property
    def is_aperta(self) -> bool:
        return self.stato == StatoTicket.APERTA

    @property
    def is_chiuso(self) -> bool:
        return self.stato in (StatoTicket.CHIUSO, StatoTicket.ANNULLATO)

    @property
    def label_tipo_fermo(self) -> str:
        return dict(TipoFermo.choices).get(self.tipo_fermo, self.tipo_fermo)

    @property
    def categorie_disponibili(self) -> list:
        return get_categorie(self.tipo)

    @property
    def label_categoria(self) -> str:
        return _get_categoria_label_map().get(self.categoria, self.categoria)


# ---------------------------------------------------------------------------
# Commento / attività
# ---------------------------------------------------------------------------

class TicketCommento(models.Model):
    ticket      = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="commenti")
    autore_nome = models.CharField(max_length=200)
    autore_email= models.CharField(max_length=200, blank=True)
    testo       = models.TextField()
    is_interno  = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Commento ticket"
        verbose_name_plural = "Commenti ticket"

    def __str__(self):
        return f"Commento #{self.pk} su {self.ticket.numero_ticket}"


# ---------------------------------------------------------------------------
# Allegati
# ---------------------------------------------------------------------------

class TicketAllegato(models.Model):
    ticket         = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="allegati")
    file           = models.FileField(upload_to="tickets/allegati/%Y/%m/", storage=PrivateTicketStorage)
    nome_originale = models.CharField(max_length=255)
    tipo_mime      = models.CharField(max_length=100, blank=True)
    uploaded_at    = models.DateTimeField(auto_now_add=True)
    uploaded_by_nome = models.CharField(max_length=200)

    class Meta:
        ordering = ["uploaded_at"]
        verbose_name = "Allegato ticket"
        verbose_name_plural = "Allegati ticket"

    def __str__(self):
        return self.nome_originale


# ---------------------------------------------------------------------------
# Impostazioni per tipo (singleton IT + singleton MAN)
# ---------------------------------------------------------------------------

class TicketImpostazioni(models.Model):
    tipo                = models.CharField(max_length=5, choices=TipoTicket.choices, unique=True)
    sharepoint_list_id  = models.CharField(max_length=100, blank=True)
    # [{"nome": "Mario Rossi", "email": "mario@example.com"}, ...]
    team_gestori        = models.JSONField(default=list)
    # Lista di username/email autorizzati ad aprire. Vuota = tutti.
    acl_apertura        = models.JSONField(default=list)
    # Lista di username/email autorizzati a gestire. Vuota = solo admin.
    acl_gestione        = models.JSONField(default=list)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Impostazioni ticket"
        verbose_name_plural = "Impostazioni ticket"

    def __str__(self):
        return f"TicketImpostazioni [{self.tipo}]"

    @classmethod
    def get_or_create_for(cls, tipo: str) -> "TicketImpostazioni":
        obj, _ = cls.objects.get_or_create(tipo=tipo)
        return obj


# ---------------------------------------------------------------------------
# Log cambio stato (storia transizioni)
# ---------------------------------------------------------------------------

class TicketStatoLog(models.Model):
    ticket       = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="stato_log")
    da_stato     = models.CharField(max_length=15, blank=True)
    a_stato      = models.CharField(max_length=15)
    utente_nome  = models.CharField(max_length=200)
    utente_email = models.CharField(max_length=200, blank=True)
    nota         = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Log stato ticket"
        verbose_name_plural = "Log stati ticket"

    def __str__(self):
        return f"{self.ticket.numero_ticket}: {self.da_stato}→{self.a_stato}"

    @property
    def label_da(self) -> str:
        return dict(StatoTicket.choices).get(self.da_stato, self.da_stato) if self.da_stato else "—"

    @property
    def label_a(self) -> str:
        return dict(StatoTicket.choices).get(self.a_stato, self.a_stato)


# ---------------------------------------------------------------------------
# Sessioni di intervento (per KPI tempi / manutentori)
# ---------------------------------------------------------------------------

class TicketIntervento(models.Model):
    ticket                = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="interventi")
    tecnico_nome          = models.CharField(max_length=200)
    tecnico_email         = models.CharField(max_length=200, blank=True)
    data_inizio           = models.DateTimeField()
    data_fine             = models.DateTimeField(null=True, blank=True)
    ore_lavorate          = models.DecimalField(
                              max_digits=6, decimal_places=2,
                              null=True, blank=True,
                              help_text="Ore effettive di lavoro (calcolate o manuali)")
    descrizione_lavoro    = models.TextField(blank=True, help_text="Cosa è stato fatto")
    componente_interessato = models.CharField(max_length=200, blank=True,
                              help_text="Componente lavorato in questa sessione")
    azioni_svolte         = models.TextField(blank=True,
                              help_text="Elenco azioni/procedure eseguite")
    esito                 = models.CharField(
                              max_length=20,
                              choices=EsitoIntervento.choices,
                              default=EsitoIntervento.IN_CORSO)
    note                  = models.TextField(blank=True)
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_inizio"]
        verbose_name = "Intervento ticket"
        verbose_name_plural = "Interventi ticket"

    def __str__(self):
        return f"Intervento #{self.pk} su {self.ticket.numero_ticket} ({self.tecnico_nome})"

    @property
    def label_esito(self) -> str:
        return dict(EsitoIntervento.choices).get(self.esito, self.esito)

    costo_manodopera_eur = models.DecimalField(
                              max_digits=10, decimal_places=2,
                              null=True, blank=True,
                              help_text="Costo manodopera per questa sessione (€)")
    materiali_costo_eur  = models.DecimalField(
                              max_digits=10, decimal_places=2,
                              null=True, blank=True,
                              help_text="Costo materiali/ricambi per questa sessione (€)")
    numero_rapportino    = models.CharField(
                              max_length=50, blank=True,
                              help_text="Numero rapportino fornitore (opzionale)")

    @property
    def durata_ore(self):
        """Ore calcolate da inizio/fine se ore_lavorate non è impostato."""
        if self.ore_lavorate is not None:
            return float(self.ore_lavorate)
        if self.data_fine and self.data_inizio:
            delta = self.data_fine - self.data_inizio
            return round(delta.total_seconds() / 3600, 2)
        return None

    @property
    def costo_totale_eur(self):
        """Somma manodopera + materiali se almeno uno è valorizzato."""
        m = float(self.costo_manodopera_eur or 0)
        r = float(self.materiali_costo_eur or 0)
        if m or r:
            return round(m + r, 2)
        return None


# ---------------------------------------------------------------------------
# Componenti sostituiti (dettaglio ricambi per sessione di intervento)
# ---------------------------------------------------------------------------

class TicketComponenteSostituito(models.Model):
    intervento      = models.ForeignKey(
                          TicketIntervento,
                          on_delete=models.CASCADE,
                          related_name="componenti_sostituiti",
                      )
    nome            = models.CharField(max_length=200, help_text="Nome componente/ricambio")
    codice_parte    = models.CharField(max_length=100, blank=True, help_text="Codice parte / P/N")
    quantita        = models.PositiveIntegerField(default=1)
    costo_unitario_eur = models.DecimalField(
                          max_digits=10, decimal_places=2,
                          null=True, blank=True,
                          help_text="Costo unitario (€)")
    note            = models.CharField(max_length=300, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Componente sostituito"
        verbose_name_plural = "Componenti sostituiti"

    def __str__(self):
        return f"{self.nome} x{self.quantita} (intervento #{self.intervento_id})"

    @property
    def costo_totale_eur(self):
        if self.costo_unitario_eur is not None:
            return round(float(self.costo_unitario_eur) * self.quantita, 2)
        return None
