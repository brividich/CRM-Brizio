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
