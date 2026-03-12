from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from django.db import models


# ---------------------------------------------------------------------------
# Costanti condivise
# ---------------------------------------------------------------------------

class TipoTicket(models.TextChoices):
    IT  = "IT",  "Ticket IT"
    MAN = "MAN", "Ticket Manutenzione"


class StatoTicket(models.TextChoices):
    APERTA      = "APERTA",      "Aperta"
    IN_CARICO   = "IN_CARICO",   "In carico"
    RISOLTO     = "RISOLTO",     "Risolto"
    CHIUSO      = "CHIUSO",      "Chiuso"
    ANNULLATO   = "ANNULLATO",   "Annullato"


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


def _next_ticket_number(tipo: str) -> str:
    """Genera il numero progressivo per l'anno corrente.
    Formato: IT-YYYY-NNNN  /  MAN-YYYY-NNNN
    """
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Ticket"
        verbose_name_plural = "Ticket"

    def save(self, *args, **kwargs):
        if not self.numero_ticket:
            self.numero_ticket = _next_ticket_number(self.tipo)
        # Regola sicurezza: incide_sicurezza → URGENTE locked
        if self.incide_sicurezza:
            self.priorita = PrioritaTicket.URGENTE
        super().save(*args, **kwargs)

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
    def categorie_disponibili(self) -> list:
        return CATEGORIE_IT if self.tipo == TipoTicket.IT else CATEGORIE_MAN

    @property
    def label_categoria(self) -> str:
        tutte = dict(CATEGORIE_IT + CATEGORIE_MAN)
        return tutte.get(self.categoria, self.categoria)


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
    file           = models.FileField(upload_to="tickets/allegati/%Y/%m/")
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
