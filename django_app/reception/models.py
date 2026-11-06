"""Visitatori della reception su SQL Server: prendono il posto del database MySQL del GuestPortal.

Gli id di ``Visita`` e ``DittaAccreditata`` restano quelli del GuestPortal: ci puntano
``fornitori.IngressoIntervento.visita_gp_id`` e ``fornitori.DittaGuestPortal.ditta_gp_id``.
Si usano solo con ``RECEPTION_NATIVA=1``: prima di allora le tabelle restano vuote.
"""
from __future__ import annotations

from django.db import models


class Ospite(models.Model):
    nome = models.CharField(max_length=100)
    cognome = models.CharField(max_length=100)
    email = models.CharField(max_length=255, blank=True, db_index=True)
    telefono = models.CharField(max_length=50, blank=True)
    azienda = models.CharField(max_length=255, blank=True)
    informativa_letta_il = models.DateTimeField(null=True, blank=True)
    informativa_ip = models.CharField(max_length=45, blank=True)
    anonimizzato = models.BooleanField(default=False)
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ospite"
        verbose_name_plural = "Ospiti"

    def __str__(self) -> str:
        return self.nome_completo

    @property
    def nome_completo(self) -> str:
        return "Ospite anonimizzato" if self.anonimizzato else f"{self.nome} {self.cognome}".strip()


class Referente(models.Model):
    """Dipendente che riceve i visitatori. Elenco a parte, come nel GuestPortal."""

    nome = models.CharField(max_length=100)
    cognome = models.CharField(max_length=100)
    email = models.CharField(max_length=255, unique=True)
    reparto = models.CharField(max_length=100, blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["cognome", "nome"]
        verbose_name = "Referente"
        verbose_name_plural = "Referenti"

    def __str__(self) -> str:
        return self.nome_elenco

    @property
    def nome_elenco(self) -> str:
        return f"{self.cognome} {self.nome}".strip()


class CategoriaVisita(models.Model):
    nome = models.CharField(max_length=100)
    icona = models.CharField(max_length=10, blank=True)
    ordine = models.IntegerField(default=0)
    attiva = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Motivo di visita"
        verbose_name_plural = "Motivi di visita"

    def __str__(self) -> str:
        return self.nome


class Cartellino(models.Model):
    numero = models.CharField(max_length=20, unique=True)
    disponibile = models.BooleanField(default=True)
    ultima_assegnazione = models.DateTimeField(null=True, blank=True)
    ultima_restituzione = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["numero"]
        verbose_name = "Cartellino"
        verbose_name_plural = "Cartellini"

    def __str__(self) -> str:
        return self.numero


class DittaAccreditata(models.Model):
    nome = models.CharField(max_length=200, unique=True)
    note = models.CharField(max_length=500, blank=True)
    attiva = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Ditta accreditata"
        verbose_name_plural = "Ditte accreditate"

    def __str__(self) -> str:
        return self.nome


class ContattoDitta(models.Model):
    ditta = models.ForeignKey(DittaAccreditata, on_delete=models.CASCADE, related_name="contatti")
    nome = models.CharField(max_length=100)
    cognome = models.CharField(max_length=100)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["cognome", "nome"]
        verbose_name = "Nominativo della ditta"
        verbose_name_plural = "Nominativi delle ditte"

    def __str__(self) -> str:
        return f"{self.cognome} {self.nome}".strip()


class Visita(models.Model):
    DENTRO = "CHECKEDIN"
    USCITO = "CHECKEDOUT"
    PREREGISTRATO = "PREREGISTERED"
    NON_PRESENTATO = "NOSHOW"
    STATI = [(DENTRO, "Presente"), (USCITO, "Uscito"), (PREREGISTRATO, "Preregistrato"), (NON_PRESENTATO, "Non presentato")]

    NORMALE = "NORMAL"
    PREREG = "PREREG"
    FORNITORE = "SUPPLIER"
    TIPI = [(NORMALE, "Visitatore"), (PREREG, "Preregistrato"), (FORNITORE, "Fornitore / consulente")]

    MAIL_DA_INVIARE = 0
    MAIL_INVIATA = 1
    MAIL_FALLITA = 2
    MAIL_IN_CORSO = 3

    SENZA_CARTELLINO = "N/A"

    ospite = models.ForeignKey(Ospite, on_delete=models.PROTECT, related_name="visite")
    cartellino = models.CharField(max_length=20, default=SENZA_CARTELLINO, db_index=True)
    referente_nome = models.CharField(max_length=255)
    referente_email = models.CharField(max_length=255, blank=True)
    motivo = models.CharField(max_length=500, blank=True)
    ingresso = models.DateTimeField(null=True, blank=True, db_index=True)
    uscita = models.DateTimeField(null=True, blank=True)
    stato = models.CharField(max_length=20, choices=STATI, default=DENTRO, db_index=True)
    tipo = models.CharField(max_length=10, choices=TIPI, default=NORMALE)
    ditta = models.ForeignKey(DittaAccreditata, null=True, blank=True, on_delete=models.SET_NULL, related_name="visite")
    contatto = models.ForeignKey(ContattoDitta, null=True, blank=True, on_delete=models.SET_NULL, related_name="visite")
    creata_da = models.CharField(max_length=50, default="CHIOSCO")
    mail_stato = models.PositiveSmallIntegerField(default=MAIL_DA_INVIARE, db_index=True)
    note = models.CharField(max_length=1000, blank=True)
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ingresso", "-pk"]
        verbose_name = "Visita"
        verbose_name_plural = "Visite"

    def __str__(self) -> str:
        return f"Visita {self.pk}"


class Preregistrazione(models.Model):
    codice = models.CharField(max_length=8, unique=True)
    ospite_nome = models.CharField(max_length=200)
    ospite_email = models.CharField(max_length=255, blank=True)
    ospite_azienda = models.CharField(max_length=200, blank=True)
    referente_nome = models.CharField(max_length=255)
    referente_email = models.CharField(max_length=255, blank=True)
    motivo = models.CharField(max_length=500, blank=True)
    creata_da = models.CharField(max_length=100, blank=True)
    creata_il = models.DateTimeField(auto_now_add=True)
    scade_il = models.DateTimeField(db_index=True)
    usata_il = models.DateTimeField(null=True, blank=True)
    visita = models.ForeignKey(Visita, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    data_visita = models.DateField(null=True, blank=True)
    ora_inizio = models.TimeField(null=True, blank=True)
    ora_fine = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creata_il"]
        verbose_name = "Pre-registrazione"
        verbose_name_plural = "Pre-registrazioni"

    def __str__(self) -> str:
        return self.codice


class EventoVisita(models.Model):
    """Correzioni a una visita: chi ha fatto cosa. Sparisce con la visita alla scadenza."""

    visita_id_rif = models.IntegerField(db_index=True)
    azione = models.CharField(max_length=50)
    autore = models.CharField(max_length=255, blank=True)
    ip = models.CharField(max_length=45, blank=True)
    dettaglio = models.TextField(blank=True)
    quando = models.DateTimeField()

    class Meta:
        ordering = ["-quando", "-pk"]
        verbose_name = "Correzione di una visita"
        verbose_name_plural = "Correzioni delle visite"

    def __str__(self) -> str:
        return f"{self.visita_id_rif}: {self.azione}"
