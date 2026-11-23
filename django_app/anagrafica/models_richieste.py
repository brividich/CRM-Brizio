"""Richieste su mansioni e competenze (specifica della Qualità v1.0 del 23/11/2026).

Ogni formazione su una mansione parte da una richiesta approvata: resta traccia di chi ha
chiesto, perché e chi ha approvato. Una tabella sola per i due tipi di richiesta:

- **RAM**, richiesta di aggiornamento mansione: aggiunta (o cambio di livello), sospensione,
  rimozione. La approva chi ha il ruolo RDD.
- **RAC**, richiesta di acquisizione competenza. La approva chi ha il ruolo MSO.

Nessuno approva la propria richiesta. Sospensione e rimozione, una volta approvate,
aggiornano la skill matrix senza sessione formativa; le altre aspettano la sessione.

Le persone sono identificate da ``legacy_anagrafica_id`` senza chiave esterna, come nel
resto della skill matrix. Il registro degli eventi è di sola aggiunta.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from .models_skillmatrix import LivelloSkm

__all__ = ["RichiestaCompetenze", "RichiestaEvento", "ContatoreRichieste"]


class ContatoreRichieste(models.Model):
    """Ultimo numero usato per prefisso e anno (RAM-2026-0001, RAC-2026-0001)."""

    prefisso = models.CharField(max_length=6)
    anno = models.PositiveSmallIntegerField()
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["prefisso", "anno"], name="anag_richieste_contatore_unico")]
        verbose_name = "Contatore richieste"
        verbose_name_plural = "Contatori richieste"

    def __str__(self) -> str:
        return f"{self.prefisso}-{self.anno}: {self.ultimo}"


class RichiestaCompetenze(models.Model):
    TIPO_AGGIUNTA = "aggiunta"
    TIPO_SOSPENSIONE = "sospensione"
    TIPO_RIMOZIONE = "rimozione"
    TIPO_COMPETENZA = "competenza"
    TIPO_CHOICES = [
        (TIPO_AGGIUNTA, "Assegnazione di mansione"),
        (TIPO_SOSPENSIONE, "Sospensione di mansione"),
        (TIPO_RIMOZIONE, "Rimozione di mansione"),
        (TIPO_COMPETENZA, "Acquisizione di competenza"),
    ]
    TIPI_MANSIONE = (TIPO_AGGIUNTA, TIPO_SOSPENSIONE, TIPO_RIMOZIONE)
    TIPI_SENZA_SESSIONE = (TIPO_SOSPENSIONE, TIPO_RIMOZIONE)

    STATO_IN_APPROVAZIONE = "in_approvazione"
    STATO_APPROVATA = "approvata"
    STATO_RESPINTA = "respinta"
    STATO_EVASA = "evasa"
    STATO_CHOICES = [
        (STATO_IN_APPROVAZIONE, "In approvazione"),
        (STATO_APPROVATA, "Approvata"),
        (STATO_RESPINTA, "Respinta"),
        (STATO_EVASA, "Evasa"),
    ]
    STATI_APERTI = (STATO_IN_APPROVAZIONE, STATO_APPROVATA)

    codice = models.CharField(max_length=20, unique=True)
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, db_index=True)
    stato = models.CharField(max_length=16, choices=STATO_CHOICES, default=STATO_IN_APPROVAZIONE, db_index=True)
    legacy_anagrafica_id = models.IntegerField(db_index=True, help_text="Persona a cui si riferisce la richiesta.")
    mansione = models.ForeignKey(
        "anagrafica.CompetenzaSkm", on_delete=models.PROTECT, null=True, blank=True, related_name="richieste",
    )
    competenza = models.ForeignKey(
        "anagrafica.CompetenzaCatalogo", on_delete=models.PROTECT, null=True, blank=True, related_name="richieste",
    )
    livello = models.CharField(
        max_length=1, choices=LivelloSkm.choices, blank=True, default="",
        help_text="Livello da raggiungere (vuoto per sospensione e rimozione).",
    )
    motivazione = models.TextField(blank=True, default="")

    richiedente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="richieste_competenze_fatte",
    )
    richiedente_legacy_id = models.IntegerField(null=True, blank=True)
    richiedente_nome = models.CharField(max_length=160, blank=True, default="")
    creata_il = models.DateTimeField(auto_now_add=True)

    deciso_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="richieste_competenze_decise",
    )
    deciso_da_nome = models.CharField(max_length=160, blank=True, default="")
    decisa_il = models.DateTimeField(null=True, blank=True)
    nota_decisione = models.TextField(blank=True, default="")
    evasa_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creata_il", "-pk"]
        verbose_name = "Richiesta su mansioni e competenze"
        verbose_name_plural = "Richieste su mansioni e competenze"

    def __str__(self) -> str:
        return self.codice

    @property
    def su_mansione(self) -> bool:
        return self.tipo in self.TIPI_MANSIONE

    @property
    def senza_sessione(self) -> bool:
        return self.tipo in self.TIPI_SENZA_SESSIONE

    @property
    def aperta(self) -> bool:
        return self.stato in self.STATI_APERTI

    @property
    def oggetto(self) -> str:
        if self.mansione_id:
            return self.mansione.nome
        return self.competenza.nome if self.competenza_id else ""


class RichiestaEvento(models.Model):
    """Registro di sola aggiunta: chi ha fatto cosa, quando, con quale valore prima e dopo."""

    richiesta = models.ForeignKey(RichiestaCompetenze, on_delete=models.PROTECT, related_name="eventi")
    quando = models.DateTimeField(auto_now_add=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    utente_nome = models.CharField(max_length=160, blank=True, default="")
    azione = models.CharField(max_length=40)
    prima = models.CharField(max_length=160, blank=True, default="")
    dopo = models.CharField(max_length=160, blank=True, default="")
    nota = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["quando", "pk"]
        verbose_name = "Evento di una richiesta"
        verbose_name_plural = "Eventi delle richieste"

    def __str__(self) -> str:
        return f"{self.richiesta_id}: {self.azione}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Il registro delle richieste è di sola aggiunta: una riga non si modifica.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Il registro delle richieste è di sola aggiunta: una riga non si cancella.")
