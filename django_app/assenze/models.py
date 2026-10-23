from __future__ import annotations

from django.db import models


class CertificazionePresenza(models.Model):
    """Registro presenze giornaliero — mattina obbligatoria, pomeriggio opzionale."""

    nome_dipendente = models.CharField(max_length=200)
    data            = models.DateField()

    # Turno mattina
    entrata_mattina = models.TimeField()
    uscita_mattina  = models.TimeField()

    # Turno pomeriggio (opzionale)
    turno_pomeriggio   = models.BooleanField(default=False)
    entrata_pomeriggio = models.TimeField(null=True, blank=True)
    uscita_pomeriggio  = models.TimeField(null=True, blank=True)

    note = models.TextField(blank=True, default="")

    # Approvazione
    CONSENSO_CHOICES = [
        ("In attesa",  "In attesa"),
        ("Approvato",  "Approvato"),
        ("Rifiutato",  "Rifiutato"),
    ]
    consenso           = models.CharField(max_length=20, choices=CONSENSO_CHOICES, default="In attesa")
    capo_reparto_email = models.CharField(max_length=200, blank=True, default="")
    salta_approvazione = models.BooleanField(default=False)

    # Origine: "utente" = da richiesta assenze, "admin" = inserimento diretto
    ORIGINE_CHOICES = [("utente", "Utente"), ("admin", "Admin")]
    origine = models.CharField(max_length=10, choices=ORIGINE_CHOICES, default="admin")

    # Collegamento alla riga in tabella assenze (se arrivato via richiesta utente)
    assenza_id = models.IntegerField(null=True, blank=True)

    inserito_da = models.CharField(max_length=200, blank=True, default="")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # Sync SharePoint lista "Certificazione presenza"
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-data", "nome_dipendente"]
        verbose_name = "Certificazione presenza"
        verbose_name_plural = "Certificazioni presenza"

    def __str__(self):
        return f"{self.nome_dipendente} — {self.data}"

    @property
    def ore_mattina(self):
        if self.entrata_mattina and self.uscita_mattina:
            delta = (
                self.uscita_mattina.hour * 60 + self.uscita_mattina.minute
                - self.entrata_mattina.hour * 60 - self.entrata_mattina.minute
            )
            return round(delta / 60, 2) if delta > 0 else 0
        return None

    @property
    def ore_pomeriggio(self):
        if self.turno_pomeriggio and self.entrata_pomeriggio and self.uscita_pomeriggio:
            delta = (
                self.uscita_pomeriggio.hour * 60 + self.uscita_pomeriggio.minute
                - self.entrata_pomeriggio.hour * 60 - self.entrata_pomeriggio.minute
            )
            return round(delta / 60, 2) if delta > 0 else 0
        return None

    @property
    def ore_totali(self):
        return round((self.ore_mattina or 0) + (self.ore_pomeriggio or 0), 2)


class AssenzaSharePointOutbox(models.Model):
    """Coda delle modifiche locali alle assenze ancora da inviare a SharePoint.

    Una riga per record della tabella legacy ``assenze``: le modifiche successive
    aggiornano la stessa riga e ne incrementano ``versione``. Il job periodico
    elimina la riga solo se la versione non e' cambiata durante l'invio, cosi' una
    modifica arrivata a meta' invio non va persa. Finche' la riga esiste, la
    lettura da SharePoint non sovrascrive il record locale.
    """

    AZIONE_UPSERT = "upsert"
    AZIONE_DELETE = "delete"
    AZIONE_CHOICES = [(AZIONE_UPSERT, "Crea/aggiorna"), (AZIONE_DELETE, "Elimina")]

    assenza_id = models.IntegerField(unique=True)
    azione = models.CharField(max_length=10, choices=AZIONE_CHOICES, default=AZIONE_UPSERT)
    # Valorizzato per le eliminazioni: il record locale non esiste piu'.
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")
    versione = models.PositiveIntegerField(default=1)
    tentativi = models.PositiveIntegerField(default=0)
    ultimo_errore = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assenza da inviare a SharePoint"
        verbose_name_plural = "Assenze da inviare a SharePoint"

    def __str__(self):
        return f"{self.azione} assenza {self.assenza_id} (v{self.versione})"


class AssenzaOrigineSharePoint(models.Model):
    """Dove e' nata una richiesta collegata alla lista SharePoint.

    Durante la convivenza con le vecchie app, la richiesta la gestisce il sistema
    in cui e' nata: ``creata_su_sharepoint=True`` significa approvata dal flusso
    Power Automate e in sola lettura sul portale. Scritta dalla sincronizzazione
    (lettura: da ``createdBy`` di Graph; invio: creata dal portale).
    """

    assenza_id = models.IntegerField(unique=True)
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")
    creata_su_sharepoint = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Origine assenza (SharePoint)"
        verbose_name_plural = "Origini assenze (SharePoint)"

    def __str__(self):
        luogo = "SharePoint" if self.creata_su_sharepoint else "portale"
        return f"assenza {self.assenza_id} nata su {luogo}"


class AssenzaCapoScelto(models.Model):
    """Capo scelto a mano dal dipendente nella richiesta, diverso da quello proposto.

    La tabella ``assenze`` è legacy: la scelta vive qui, per ``assenza_id``. Se
    c'è una riga, la richiesta la vede in coda e la approva **solo** questo capo,
    non il capo dell'organigramma.
    """

    assenza_id = models.IntegerField(unique=True)
    capo_legacy_user_id = models.IntegerField(db_index=True)
    capo_nominativo = models.CharField(max_length=200, blank=True, default="")
    scelto_da = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Capo scelto per l'assenza"
        verbose_name_plural = "Capi scelti per le assenze"

    def __str__(self):
        return f"assenza {self.assenza_id} → capo {self.capo_legacy_user_id}"


class AssenzaInseritaDa(models.Model):
    """Chi ha inserito la richiesta dal portale e con quale profilo Assenze.

    La tabella ``assenze`` è legacy e non ha l'autore: la riga vive qui, per
    ``assenza_id``. Le automazioni la leggono come ``inserito_da_gruppo``
    (``CAR`` / ``AMMINISTRAZIONE`` / ``UTENTI``) per scegliere i destinatari:
    con «Salta approvazione» il caporeparto non va avvisato di ciò che ha
    inserito lui stesso.
    """

    assenza_id = models.IntegerField(unique=True)
    gruppo = models.CharField(max_length=20, blank=True, default="")
    inserito_da = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Autore richiesta assenza"
        verbose_name_plural = "Autori richieste assenza"

    def __str__(self):
        return f"assenza {self.assenza_id} inserita da {self.inserito_da} ({self.gruppo})"


class FlessibilitaImpostazioni(models.Model):
    """Orari ammessi per le richieste di Flessibilita' (riga unica, pk=1).

    Gli orari non sono liberi: l'entrata e l'uscita si scelgono da due elenchi
    decisi dall'Amministrazione (es. 07:00/08:00/09:00 e 16:00/17:00/18:00).
    Stanno qui e non fra le costanti del codice perche' cambiarli e' una
    decisione organizzativa, non un rilascio.
    """

    ENTRATE_DEFAULT = "07:00,08:00,09:00"
    USCITE_DEFAULT = "16:00,17:00,18:00"

    orari_entrata = models.CharField(
        max_length=200,
        default=ENTRATE_DEFAULT,
        verbose_name="Orari di entrata ammessi",
        help_text="Elenco separato da virgola, formato HH:MM. Es. 07:00,08:00,09:00",
    )
    orari_uscita = models.CharField(
        max_length=200,
        default=USCITE_DEFAULT,
        verbose_name="Orari di uscita ammessi",
        help_text="Elenco separato da virgola, formato HH:MM. Es. 16:00,17:00,18:00",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "Impostazioni flessibilità"
        verbose_name_plural = "Impostazioni flessibilità"

    def __str__(self):
        return f"Flessibilità: entrata {self.orari_entrata} · uscita {self.orari_uscita}"

    @staticmethod
    def _parse(raw: str) -> list[str]:
        """Normalizza un elenco "HH:MM,HH:MM" scartando le voci non valide."""
        out: list[str] = []
        for chunk in str(raw or "").replace(";", ",").split(","):
            value = chunk.strip()
            if not value:
                continue
            parts = value.split(":")
            if len(parts) != 2:
                continue
            try:
                ore, minuti = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            if not (0 <= ore <= 23 and 0 <= minuti <= 59):
                continue
            normalizzato = f"{ore:02d}:{minuti:02d}"
            if normalizzato not in out:
                out.append(normalizzato)
        return sorted(out)

    @property
    def entrate(self) -> list[str]:
        return self._parse(self.orari_entrata) or self._parse(self.ENTRATE_DEFAULT)

    @property
    def uscite(self) -> list[str]:
        return self._parse(self.orari_uscita) or self._parse(self.USCITE_DEFAULT)

    @classmethod
    def get_solo(cls) -> "FlessibilitaImpostazioni":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class FlessibilitaAbilitato(models.Model):
    """Dipendente autorizzato a richiedere la Flessibilita'.

    La flessibilita' non spetta a tutti: senza questo elenco chiunque potrebbe
    richiederla. Identificato per ``legacy_anagrafica_id`` come il resto del
    modulo (vedi il ponte utente/anagrafica in `anagrafica`).
    """

    legacy_anagrafica_id = models.IntegerField(unique=True, db_index=True)
    nominativo = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Copia del nominativo al momento dell'abilitazione, per leggibilità dello storico.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["nominativo", "legacy_anagrafica_id"]
        verbose_name = "Abilitato alla flessibilità"
        verbose_name_plural = "Abilitati alla flessibilità"

    def __str__(self):
        return self.nominativo or f"anagrafica {self.legacy_anagrafica_id}"


# ─── HR: impostazioni, calendario aziendale, saldi, contatori, copertura ─────


class AssenzeImpostazioniHR(models.Model):
    """Impostazioni HR del modulo (riga unica, pk=1).

    Servono a contare le assenze in ore: quante ore vale una giornata, se il
    sabato si lavora, il santo patrono. Più i solleciti ai capi per le richieste
    ferme in attesa.
    """

    ore_giornata = models.DecimalField(
        max_digits=4, decimal_places=2, default=8,
        verbose_name="Ore di una giornata lavorativa",
        help_text="Una giornata di ferie vale queste ore.",
    )
    sabato_lavorativo = models.BooleanField(default=False, verbose_name="Il sabato è lavorativo")
    patrono_giorno = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Patrono: giorno")
    patrono_mese = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Patrono: mese")
    patrono_nome = models.CharField(max_length=100, blank=True, default="", verbose_name="Patrono: nome")
    sollecito_attivo = models.BooleanField(default=True, verbose_name="Solleciti ai capi attivi")
    sollecito_dopo_giorni = models.PositiveSmallIntegerField(
        default=2, verbose_name="Sollecita dopo (giorni in attesa)",
    )
    sollecito_ripeti_giorni = models.PositiveSmallIntegerField(
        default=2, verbose_name="Ripeti il sollecito ogni (giorni)",
    )
    outlook_capo_attivo = models.BooleanField(
        default=False, verbose_name="Assenze approvate nel calendario Outlook del capo",
        help_text="Serve il permesso applicativo Calendars.ReadWrite di Microsoft Graph.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "Impostazioni HR assenze"
        verbose_name_plural = "Impostazioni HR assenze"

    def __str__(self):
        return f"Impostazioni HR assenze ({self.ore_giornata} ore/giorno)"

    @classmethod
    def get_solo(cls) -> "AssenzeImpostazioniHR":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ChiusuraAziendale(models.Model):
    """Periodo in cui l'azienda è chiusa per tutti (es. agosto, ponti, Natale).

    Vale per tutta l'azienda: non crea richieste per le persone. Se
    ``scala_ferie`` è vero, i giorni lavorativi del periodo si tolgono dal saldo
    ferie di ognuno.
    """

    data_inizio = models.DateField()
    data_fine = models.DateField()
    descrizione = models.CharField(max_length=200)
    scala_ferie = models.BooleanField(default=True, verbose_name="Scala dalle ferie")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-data_inizio"]
        verbose_name = "Chiusura aziendale"
        verbose_name_plural = "Chiusure aziendali"

    def __str__(self):
        return f"{self.descrizione} ({self.data_inizio} - {self.data_fine})"


class SaldoAssenze(models.Model):
    """Saldo ferie e permessi di un dipendente a una data (dal cedolino).

    NON PIÙ USATO: dal 23/10/2026 i saldi si leggono da ``anagrafica.SaldoCedolino``
    (``assenze.hr.saldi_anagrafica``). Resta per non perdere le righe già inserite.

    Il residuo stimato si calcola togliendo le richieste non rifiutate che
    iniziano dopo ``situazione_al`` e le chiusure aziendali che scalano le ferie.
    """

    ORIGINE_MANUALE = "manuale"
    ORIGINE_IMPORT = "import"
    ORIGINE_CHOICES = [(ORIGINE_MANUALE, "Manuale"), (ORIGINE_IMPORT, "Import da file")]

    legacy_anagrafica_id = models.IntegerField(unique=True, db_index=True)
    nominativo = models.CharField(max_length=200, blank=True, default="")
    ferie_ore = models.DecimalField(max_digits=7, decimal_places=2, default=0, verbose_name="Ferie (ore)")
    permessi_ore = models.DecimalField(
        max_digits=7, decimal_places=2, default=0, verbose_name="Permessi ROL ed ex festività (ore)",
    )
    situazione_al = models.DateField(verbose_name="Situazione al")
    note = models.CharField(max_length=300, blank=True, default="")
    origine = models.CharField(max_length=10, choices=ORIGINE_CHOICES, default=ORIGINE_MANUALE)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["nominativo"]
        verbose_name = "Saldo ferie e permessi"
        verbose_name_plural = "Saldi ferie e permessi"

    def __str__(self):
        return f"{self.nominativo or self.legacy_anagrafica_id} al {self.situazione_al}"


class ContatoreAssenza(models.Model):
    """Limite di legge o di contratto su un tipo di assenza (es. assemblea, 104).

    Si aggancia alla «Motivazione richiesta» (confronto senza maiuscole) e conta
    le richieste non rifiutate della persona nel periodo. Superare il limite non
    blocca: avvisa chi chiede e chi approva.
    """

    UNITA_ORE = "ore"
    UNITA_GIORNI = "giorni"
    UNITA_CHOICES = [(UNITA_ORE, "Ore"), (UNITA_GIORNI, "Giorni")]
    PERIODO_MESE = "mese"
    PERIODO_ANNO = "anno"
    PERIODO_CHOICES = [(PERIODO_MESE, "Al mese"), (PERIODO_ANNO, "All'anno")]

    nome = models.CharField(max_length=100)
    motivazione = models.CharField(max_length=200, verbose_name="Motivazione richiesta")
    unita = models.CharField(max_length=10, choices=UNITA_CHOICES, default=UNITA_ORE)
    limite = models.DecimalField(max_digits=7, decimal_places=2)
    periodo = models.CharField(max_length=10, choices=PERIODO_CHOICES, default=PERIODO_ANNO)
    attivo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["nome"]
        verbose_name = "Contatore assenza"
        verbose_name_plural = "Contatori assenze"

    def __str__(self):
        return f"{self.nome}: {self.limite} {self.unita} {self.get_periodo_display().lower()}"


class SogliaCopertura(models.Model):
    """Quante persone di un reparto possono essere assenti nello stesso giorno.

    Non blocca: avvisa il capo quando approvare una richiesta porterebbe il
    reparto oltre la soglia. Il reparto è quello scritto in anagrafica.
    """

    reparto = models.CharField(max_length=200, unique=True)
    max_assenti = models.PositiveSmallIntegerField(verbose_name="Assenti al massimo nello stesso giorno")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["reparto"]
        verbose_name = "Soglia di copertura"
        verbose_name_plural = "Soglie di copertura"

    def __str__(self):
        return f"{self.reparto}: max {self.max_assenti} assenti"


class AssenzaModifica(models.Model):
    """Storico di una richiesta: chi l'ha creata, cambiata, decisa o eliminata.

    La tabella ``assenze`` è legacy e non ha uno storico: la riga vive qui, per
    ``assenza_id``, e sopravvive all'eliminazione della richiesta.
    """

    AZIONE_CREATA = "creata"
    AZIONE_MODIFICATA = "modificata"
    AZIONE_APPROVATA = "approvata"
    AZIONE_RIFIUTATA = "rifiutata"
    AZIONE_ELIMINATA = "eliminata"
    AZIONE_CHOICES = [
        (AZIONE_CREATA, "Creata"),
        (AZIONE_MODIFICATA, "Modificata"),
        (AZIONE_APPROVATA, "Approvata"),
        (AZIONE_RIFIUTATA, "Rifiutata"),
        (AZIONE_ELIMINATA, "Eliminata"),
    ]

    assenza_id = models.IntegerField(db_index=True)
    quando = models.DateTimeField(auto_now_add=True)
    utente = models.CharField(max_length=200, blank=True, default="")
    azione = models.CharField(max_length=20, choices=AZIONE_CHOICES)
    modifiche = models.JSONField(default=list, blank=True)
    motivo = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-quando", "-id"]
        verbose_name = "Modifica richiesta assenza"
        verbose_name_plural = "Storico richieste assenza"

    def __str__(self):
        return f"assenza {self.assenza_id}: {self.azione} da {self.utente}"


class AssenzaSollecito(models.Model):
    """Ultimo sollecito mandato al capo per una richiesta ferma in attesa."""

    assenza_id = models.IntegerField(unique=True)
    ultimo_invio = models.DateTimeField()
    invii = models.PositiveIntegerField(default=0)
    destinatario = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "Sollecito richiesta assenza"
        verbose_name_plural = "Solleciti richieste assenza"

    def __str__(self):
        return f"assenza {self.assenza_id}: {self.invii} solleciti"


class AssenzaOutlook(models.Model):
    """Evento creato via Graph nel calendario Outlook del capo per un'assenza approvata."""

    assenza_id = models.IntegerField(unique=True)
    email = models.CharField(max_length=200, blank=True, default="")
    event_id = models.CharField(max_length=512, blank=True, default="")
    impronta = models.CharField(max_length=64, blank=True, default="")
    rimosso_da_utente = models.BooleanField(default=False)
    ultimo_errore = models.CharField(max_length=500, blank=True, default="")
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assenza nel calendario Outlook"
        verbose_name_plural = "Assenze nel calendario Outlook"

    def __str__(self):
        return f"assenza {self.assenza_id} → {self.email or '?'}"


class CalendarioOutlookCapo(models.Model):
    """Id del calendario «Assenze del team (NOVICROM HUB)» nella casella di un capo."""

    email = models.CharField(max_length=200, unique=True)
    calendario_id = models.CharField(max_length=512, blank=True, default="")
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Calendario Outlook del capo"
        verbose_name_plural = "Calendari Outlook dei capi"

    def __str__(self):
        return self.email
