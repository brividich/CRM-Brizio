"""Qualita' delle anomalie: classificazione per S/N e scheda NC per OP (ISO 9001 §10.2).

La segnalazione resta una riga della tabella legacy ``anomalie`` (con il suo trigger
SQL delle automazioni): tutto quello che segue vive in tabelle Django agganciate per
id, senza toccare lo schema legacy.

- ``AnomaliaTipoDifetto``: catalogo configurabile dei tipi di difetto (Pareto).
- ``AnomaliaSchedaQualita``: classificazione della singola anomalia (S/N): origine,
  difetto, gravita', reparto, quantita', decisione sul materiale (EN 9100 §8.7).
- ``AnomaliaNC``: la non conformita' dell'OP, una per OP finche' e' aperta. Raccoglie
  le anomalie dell'OP e ne gestisce il ciclo: contenimento, analisi delle cause,
  azioni correttive, verifica di efficacia, chiusura. Tutte le sezioni sono
  facoltative; lo stato e' calcolato da quello che e' compilato.
- ``AnomaliaNCAzione`` / ``AnomaliaNCEvento`` / ``AnomaliaNCAllegato``: azioni,
  storico e allegati della NC.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class AnomaliaTipoDifetto(models.Model):
    codice = models.SlugField(max_length=40, unique=True)
    nome = models.CharField(max_length=120, unique=True)
    famiglia = models.CharField(max_length=80, blank=True, default="")
    attivo = models.BooleanField(default=True, db_index=True)
    ordine = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Tipo difetto anomalie"
        verbose_name_plural = "Catalogo tipi difetto anomalie"

    def __str__(self) -> str:
        return self.nome


class AnomaliaNC(models.Model):
    class Stato(models.TextChoices):
        APERTA = "APERTA", "Aperta"
        CONTENIMENTO = "CONTENIMENTO", "Contenimento"
        ANALISI = "ANALISI", "Analisi cause"
        AZIONI = "AZIONI", "Azioni in corso"
        VERIFICA = "VERIFICA", "In verifica"
        CHIUSA = "CHIUSA", "Chiusa"

    class MetodoAnalisi(models.TextChoices):
        CINQUE_PERCHE = "CINQUE_PERCHE", "5 perché"
        ISHIKAWA = "ISHIKAWA", "Ishikawa (6M)"
        ESTERNA = "ESTERNA", "Documento esterno"

    class Esito(models.TextChoices):
        EFFICACE = "EFFICACE", "Efficace"
        NON_EFFICACE = "NON_EFFICACE", "Non efficace"

    protocollo = models.CharField(max_length=20, unique=True)
    op_titolo = models.CharField(max_length=100, db_index=True)
    part_number = models.CharField(max_length=120, blank=True, default="", db_index=True)
    # Istantanee dei nominativi dall'OP (ordini_produzione), riallineate a ogni sync.
    capocommessa = models.CharField(max_length=200, blank=True, default="")
    car = models.CharField(max_length=200, blank=True, default="")
    precedente = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="ricadute",
    )
    stato = models.CharField(max_length=14, choices=Stato.choices, default=Stato.APERTA, db_index=True)

    # 1. Contenimento immediato (§10.2.1 a)
    contenimento = models.TextField(blank=True, default="")
    contenimento_data = models.DateField(null=True, blank=True)
    contenimento_da = models.CharField(max_length=150, blank=True, default="")

    # 2. Analisi delle cause (§10.2.1 b)
    analisi_metodo = models.CharField(max_length=14, choices=MetodoAnalisi.choices, blank=True, default="")
    analisi_perche = models.JSONField(default=list, blank=True)       # [str x 5]
    analisi_ishikawa = models.JSONField(default=dict, blank=True)     # {categoria: str}
    analisi_riferimento = models.CharField(max_length=300, blank=True, default="")
    causa_radice = models.TextField(blank=True, default="")
    analisi_data = models.DateField(null=True, blank=True)
    analisi_da = models.CharField(max_length=150, blank=True, default="")

    # 4. Verifica di efficacia (§10.2.1 d)
    verifica_prevista = models.DateField(null=True, blank=True)
    verifica_data = models.DateField(null=True, blank=True)
    verifica_esito = models.CharField(max_length=14, choices=Esito.choices, blank=True, default="")
    verifica_note = models.TextField(blank=True, default="")
    verifica_da = models.CharField(max_length=150, blank=True, default="")

    chiusa_il = models.DateTimeField(null=True, blank=True)
    chiusa_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    note_chiusura = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = "Non conformità (per OP)"
        verbose_name_plural = "Non conformità (per OP)"
        indexes = [models.Index(fields=["op_titolo", "stato"], name="anomalie_nc_op_stato")]

    def __str__(self) -> str:
        return self.protocollo

    @property
    def is_chiusa(self) -> bool:
        return self.stato == self.Stato.CHIUSA


class AnomaliaSchedaQualita(models.Model):
    class Origine(models.TextChoices):
        PRODUZIONE = "PRODUZIONE", "Interna - produzione"
        CONTROLLO = "CONTROLLO", "Interna - controllo qualità"
        FORNITORE = "FORNITORE", "Fornitore / lavorazione esterna"
        CLIENTE = "CLIENTE", "Cliente"
        AUDIT = "AUDIT", "Audit"

    class Gravita(models.TextChoices):
        MINORE = "MINORE", "Minore"
        MAGGIORE = "MAGGIORE", "Maggiore"
        CRITICA = "CRITICA", "Critica"

    class Disposizione(models.TextChoices):
        DA_DEFINIRE = "DA_DEFINIRE", "Da definire"
        USO_TALE = "USO_TALE", "Uso così com'è"
        RILAVORAZIONE = "RILAVORAZIONE", "Rilavorazione"
        RIPARAZIONE = "RIPARAZIONE", "Riparazione"
        DEROGA = "DEROGA", "Concessione / deroga cliente"
        SCARTO = "SCARTO", "Scarto"
        RESO_FORNITORE = "RESO_FORNITORE", "Reso al fornitore"

    # Id della riga legacy ``anomalie`` (niente FK: tabella non gestita da Django).
    anomalia_id = models.IntegerField(unique=True, db_index=True)
    nc = models.ForeignKey(AnomaliaNC, on_delete=models.SET_NULL, null=True, blank=True, related_name="schede")

    # Istantanea dell'OP al momento della registrazione (il P/N di un OP non cambia):
    # serve a Pareto e ricorrenze senza rileggere ogni volta ordini_produzione.
    op_titolo = models.CharField(max_length=100, blank=True, default="", db_index=True)
    part_number = models.CharField(max_length=120, blank=True, default="", db_index=True)

    origine = models.CharField(max_length=12, choices=Origine.choices, blank=True, default="")
    tipo_difetto = models.ForeignKey(
        AnomaliaTipoDifetto, on_delete=models.PROTECT, null=True, blank=True,
        related_name="schede",
    )
    gravita = models.CharField(max_length=10, choices=Gravita.choices, blank=True, default="")
    reparto = models.ForeignKey(
        "anagrafica.Reparto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    quantita_nc = models.PositiveIntegerField(null=True, blank=True)
    quantita_scartata = models.PositiveIntegerField(null=True, blank=True)
    disposizione = models.CharField(
        max_length=16, choices=Disposizione.choices, default=Disposizione.DA_DEFINIRE,
    )
    # True finche' la disposizione e' quella dedotta dal sistema dai flag
    # dell'anomalia; diventa False appena un utente la sceglie a mano.
    disposizione_auto = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = "Scheda qualità anomalia"
        verbose_name_plural = "Schede qualità anomalie"
        indexes = [
            models.Index(fields=["part_number", "tipo_difetto"], name="anomalie_sq_pn_difetto"),
        ]

    def __str__(self) -> str:
        return f"anomalia {self.anomalia_id}"


class AnomaliaNCAzione(models.Model):
    class Tipo(models.TextChoices):
        CORRETTIVA = "CORRETTIVA", "Correttiva"
        PREVENTIVA = "PREVENTIVA", "Preventiva"

    class Stato(models.TextChoices):
        DA_FARE = "DA_FARE", "Da fare"
        IN_CORSO = "IN_CORSO", "In corso"
        FATTA = "FATTA", "Fatta"
        ANNULLATA = "ANNULLATA", "Annullata"

    nc = models.ForeignKey(AnomaliaNC, on_delete=models.CASCADE, related_name="azioni")
    descrizione = models.TextField()
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.CORRETTIVA)
    # Responsabile = utente legacy (le notifiche in-app sono per legacy_user_id).
    responsabile_legacy_id = models.IntegerField(null=True, blank=True, db_index=True)
    responsabile_nome = models.CharField(max_length=200, blank=True, default="")
    scadenza = models.DateField(null=True, blank=True, db_index=True)
    stato = models.CharField(max_length=10, choices=Stato.choices, default=Stato.DA_FARE, db_index=True)
    completata_il = models.DateField(null=True, blank=True)
    esito = models.TextField(blank=True, default="")
    promemoria_il = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["scadenza", "id"]
        verbose_name = "Azione NC"
        verbose_name_plural = "Azioni NC"

    def __str__(self) -> str:
        return f"{self.nc_id}: {self.descrizione[:40]}"

    @property
    def aperta(self) -> bool:
        return self.stato in (self.Stato.DA_FARE, self.Stato.IN_CORSO)


class AnomaliaNCEvento(models.Model):
    nc = models.ForeignKey(AnomaliaNC, on_delete=models.CASCADE, related_name="eventi")
    tipo = models.CharField(max_length=40)
    testo = models.CharField(max_length=500)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    user_nome = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Evento NC"
        verbose_name_plural = "Eventi NC"


class AnomaliaNCAllegato(models.Model):
    class Sezione(models.TextChoices):
        CONTENIMENTO = "CONTENIMENTO", "Contenimento"
        ANALISI = "ANALISI", "Analisi cause"
        AZIONI = "AZIONI", "Azioni"
        VERIFICA = "VERIFICA", "Verifica"
        ALTRO = "ALTRO", "Altro"

    nc = models.ForeignKey(AnomaliaNC, on_delete=models.CASCADE, related_name="allegati")
    sezione = models.CharField(max_length=12, choices=Sezione.choices, default=Sezione.ALTRO)
    nome = models.CharField(max_length=255)
    # Percorso relativo alla cartella allegati anomalie (fuori dalla webroot).
    file_rel = models.CharField(max_length=400)
    size = models.PositiveIntegerField(default=0)
    mime = models.CharField(max_length=100, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Allegato NC"
        verbose_name_plural = "Allegati NC"
