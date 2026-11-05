"""Collegamento tra gli ingressi del GuestPortal e gli interventi dell'HUB.

I modelli anagrafici dei fornitori restano in ``anagrafica.models``. Qui vivono
solo le tabelle del collegamento con il GuestPortal (applicazione separata):

- ``DittaGuestPortal``: abbinamento una tantum tra un fornitore dell'anagrafica
  del GuestPortal (``Suppliers.SupplierID``) e il fornitore dell'HUB;
- ``IngressoIntervento``: un ingresso (visita del GuestPortal) collegato a un
  ticket, a un ordine di lavoro o a una sessione formativa (docente esterno). Al collegamento si salvano giorno, entrata,
  uscita e nominativo del tecnico: restano come prova dell'intervento anche
  dopo la pulizia GDPR del GuestPortal, con la conservazione del ticket/OdL.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from .nomi import chiave_tecnico


class DittaGuestPortal(models.Model):
    ditta_gp_id = models.PositiveIntegerField(unique=True, help_text="Suppliers.SupplierID del GuestPortal")
    ditta_gp_nome = models.CharField(max_length=200, help_text="Nome della ditta nel GuestPortal al momento dell'abbinamento")
    fornitore = models.ForeignKey(
        "anagrafica.Fornitore", on_delete=models.CASCADE, related_name="ditte_guestportal",
    )
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ditta_gp_nome"]
        verbose_name = "Ditta GuestPortal abbinata"
        verbose_name_plural = "Ditte GuestPortal abbinate"

    def __str__(self) -> str:
        return f"{self.ditta_gp_nome} → {self.fornitore}"


class IngressoIntervento(models.Model):
    MODO_PROPOSTA = "PROPOSTA"
    MODO_MANUALE = "MANUALE"
    MODO_CHOICES = [
        (MODO_PROPOSTA, "Proposta confermata"),
        (MODO_MANUALE, "Collegato a mano"),
    ]

    visita_gp_id = models.PositiveIntegerField(db_index=True, help_text="Visits.VisitID del GuestPortal")
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.CASCADE, related_name="ingressi_esterni",
    )
    work_order = models.ForeignKey(
        "assets.WorkOrder", null=True, blank=True, on_delete=models.CASCADE, related_name="ingressi_esterni",
    )
    sessione_formazione = models.ForeignKey(
        "anagrafica.TrainingSession", null=True, blank=True, on_delete=models.CASCADE,
        related_name="ingressi_esterni", help_text="Sessione formativa: ingresso del docente esterno",
    )
    fornitore = models.ForeignKey(
        "anagrafica.Fornitore", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    # Fotografia dell'ingresso al momento del collegamento (vedi docstring del modulo).
    ingresso = models.DateTimeField(null=True, blank=True)
    uscita = models.DateTimeField(null=True, blank=True)
    tecnico_nome = models.CharField(max_length=200, blank=True)
    azienda = models.CharField(max_length=200, blank=True)
    badge = models.CharField(max_length=20, blank=True)
    modo = models.CharField(max_length=10, choices=MODO_CHOICES, default=MODO_PROPOSTA)
    collegato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    collegato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ingresso", "pk"]
        verbose_name = "Ingresso esterno collegato"
        verbose_name_plural = "Ingressi esterni collegati"
        constraints = [
            models.CheckConstraint(
                condition=(Q(ticket__isnull=False, work_order__isnull=True, sessione_formazione__isnull=True)
                           | Q(ticket__isnull=True, work_order__isnull=False, sessione_formazione__isnull=True)
                           | Q(ticket__isnull=True, work_order__isnull=True, sessione_formazione__isnull=False)),
                name="fornitori_ingresso_un_solo_intervento_v2",
            ),
            models.UniqueConstraint(
                fields=["visita_gp_id", "ticket"], condition=Q(ticket__isnull=False),
                name="fornitori_ingresso_unico_per_ticket",
            ),
            models.UniqueConstraint(
                fields=["visita_gp_id", "work_order"], condition=Q(work_order__isnull=False),
                name="fornitori_ingresso_unico_per_odl",
            ),
            models.UniqueConstraint(
                fields=["visita_gp_id", "sessione_formazione"], condition=Q(sessione_formazione__isnull=False),
                name="fornitori_ingresso_unico_per_sessione",
            ),
        ]

    def __str__(self) -> str:
        return f"Visita {self.visita_gp_id} → {self.ticket or self.work_order or self.sessione_formazione}"

    @property
    def durata_minuti(self) -> int | None:
        if not self.ingresso or not self.uscita:
            return None
        return max(0, int((self.uscita - self.ingresso).total_seconds() // 60))

    @property
    def durata_label(self) -> str:
        minuti = self.durata_minuti
        if minuti is None:
            return "ancora dentro" if self.ingresso and not self.uscita else "—"
        if minuti < 60:
            return f"{minuti} min"
        return f"{minuti // 60} h {minuti % 60:02d} min"


class FornitoreContatori(models.Model):
    """Facoltativo: il fornitore dell'HUB di un codice del modulo Contatori («BASE», «COPYLAB»).

    Serve solo quando il nome non basta a riconoscerlo (vedi ``collegamenti.mappa_codici``)."""

    codice = models.CharField(max_length=10, unique=True, help_text="Macchina.fornitore / Fattura.fornitore")
    fornitore = models.ForeignKey(
        "anagrafica.Fornitore", on_delete=models.CASCADE, related_name="codici_contatori",
    )
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["codice"]
        verbose_name = "Fornitore del modulo Contatori"
        verbose_name_plural = "Fornitori del modulo Contatori"

    def __str__(self) -> str:
        return f"{self.codice} → {self.fornitore}"


class TecnicoFornitore(models.Model):
    """Registro dei tecnici di una ditta (vedi ``fornitori.tecnici``): resta anche dopo la
    pulizia GDPR del GuestPortal, finché non viene eliminato dalla scheda."""

    ORIGINE_MANUALE = "MANUALE"
    ORIGINE_GUESTPORTAL = "GUESTPORTAL"
    ORIGINE_INTERVENTO = "INTERVENTO"
    ORIGINE_CHOICES = [
        (ORIGINE_MANUALE, "Aggiunto a mano"),
        (ORIGINE_GUESTPORTAL, "Dal GuestPortal"),
        (ORIGINE_INTERVENTO, "Da un intervento"),
    ]

    fornitore = models.ForeignKey("anagrafica.Fornitore", on_delete=models.CASCADE, related_name="tecnici")
    nome = models.CharField("Nome e cognome", max_length=200)
    chiave = models.CharField(
        max_length=200, editable=False, help_text="Nome confrontabile: maiuscole e ordine delle parole ignorati",
    )
    qualifica = models.CharField("Qualifica", max_length=120, blank=True)
    telefono = models.CharField("Telefono", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    attestati_fino_al = models.DateField(
        "Attestati validi fino al", null=True, blank=True,
        help_text="Facoltativo: compare nelle scadenze della ditta e nello Scadenzario.",
    )
    note = models.CharField("Note", max_length=255, blank=True)
    attivo = models.BooleanField("Attivo", default=True)
    origine = models.CharField(max_length=12, choices=ORIGINE_CHOICES, default=ORIGINE_MANUALE)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-attivo", "nome", "pk"]
        verbose_name = "Tecnico del fornitore"
        verbose_name_plural = "Tecnici dei fornitori"
        constraints = [
            models.UniqueConstraint(fields=["fornitore", "chiave"], name="fornitori_tecnico_unico_per_fornitore"),
        ]

    def __str__(self) -> str:
        return f"{self.nome} ({self.fornitore})"

    def save(self, *args, **kwargs):
        self.chiave = chiave_tecnico(self.nome)
        super().save(*args, **kwargs)


class AvvisoIngressoNonInRegola(models.Model):
    """Ingresso dal GuestPortal di una ditta con i documenti di sicurezza non in regola,
    già segnalato con una notifica a RSPP/ASPP (una sola volta per visita, mai mail)."""

    visita_id = models.IntegerField(unique=True, help_text="Visits.VisitID del GuestPortal")
    fornitore = models.ForeignKey("anagrafica.Fornitore", on_delete=models.CASCADE, related_name="+")
    azienda = models.CharField(max_length=200, blank=True)
    problemi = models.CharField(max_length=500, blank=True)
    destinatari = models.PositiveIntegerField(default=0)
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creato_il"]
        verbose_name = "Avviso ingresso ditta non in regola"
        verbose_name_plural = "Avvisi ingresso ditte non in regola"

    def __str__(self) -> str:
        return f"{self.azienda} (visita {self.visita_id})"
