"""Registro accessi: log dei server, degli apparati e degli amministratori di sistema.

Cosa sta dove:

- **Archivio** (file, non database): tutto ciò che arriva, un file al giorno con una
  catena di hash riga per riga, chiuso da un :class:`SigilloGiorno`. È la copia che
  vale per il Garante (accessi degli amministratori di sistema) e per la ISO 27001.
- **Indice** (:class:`EventoRegistro`): solo gli eventi che contano (accessi, accessi
  falliti, gruppi privilegiati, account creati o eliminati, registro cancellato…),
  ognuno con il rimando alla riga dell'archivio.
- **Continuità** (:class:`Interruzione`): ogni periodo in cui la raccolta si è fermata
  o una fonte è rimasta muta, da giustificare in sede di verifica.

Nessuna chiave esterna verso le tabelle del portale: il router può mettere queste
tabelle in un database a parte (vedi ``router.py``); le persone si collegano per id.
"""
from __future__ import annotations

from datetime import time

from django.db import models
from django.utils import timezone

from core.private_attachments import PrivateAttachmentStorage


class Impostazioni(models.Model):
    """Una sola riga (pk=1): come gira il raccoglitore. Si modifica dalla pagina Fonti."""

    attivo = models.BooleanField(default=False)
    cartella_archivio = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Vuota = cartella privata del portale (media_private/registro_log).",
    )
    copia_cartella = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Seconda copia dei giorni sigillati (es. una share del NAS). Vuota = nessuna copia su cartella.",
    )
    copia_sharepoint = models.BooleanField(default=False)
    conservazione_mesi = models.PositiveSmallIntegerField(default=12)
    syslog_attivo = models.BooleanField(default=False)
    syslog_indirizzo = models.CharField(max_length=64, default="0.0.0.0")
    syslog_porta = models.PositiveIntegerField(default=514)
    syslog_tcp = models.BooleanField(default=True)
    orario_inizio = models.TimeField(default=time(7, 0))
    orario_fine = models.TimeField(default=time(19, 0))
    # Accessi ai file, stampe e USB sono controlli sull'attività dei lavoratori (art. 4 L. 300/1970, GDPR):
    # si accendono sulle fonti solo dopo questa conferma, registrata con chi e quando.
    controlli_lavoratori_ok = models.BooleanField(default=False)
    controlli_lavoratori_nota = models.CharField(max_length=500, blank=True, default="")
    controlli_lavoratori_da = models.CharField(max_length=150, blank=True, default="")
    controlli_lavoratori_il = models.DateTimeField(null=True, blank=True)
    # Account dei programmi che leggono i registri (BusinessLog in parallelo, questo raccoglitore): i loro
    # accessi ai server restano solo nell'archivio e lo svuotamento del registro fatto da loro non è un allarme.
    account_raccoglitori = models.CharField(max_length=500, blank=True, default="")
    aggiornato_il = models.DateTimeField(auto_now=True)
    aggiornato_da = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        verbose_name = "Impostazioni del registro accessi"
        verbose_name_plural = "Impostazioni del registro accessi"

    def __str__(self):
        return "Impostazioni del registro accessi"

    @classmethod
    def corrente(cls) -> "Impostazioni":
        obj = cls.objects.filter(pk=1).first()
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def lista_raccoglitori(self) -> set[str]:
        """Account senza dominio, minuscoli (DOMINIO\\svc-blog e svc-blog@dominio diventano svc-blog)."""
        voci = (self.account_raccoglitori or "").replace(";", ",").replace("\n", ",").split(",")
        return {v.strip().split("\\")[-1].split("@")[0].lower() for v in voci if v.strip()}


CANALE_STAMPE = "Microsoft-Windows-PrintService/Operational"
CANALE_USB = "Microsoft-Windows-Partition/Diagnostic"


class FonteLog(models.Model):
    TIPO_WINDOWS = "windows"
    TIPO_WEF = "wef"
    TIPO_SYSLOG = "syslog"
    TIPO_DOMINIO = "dominio"
    TIPI = [
        (TIPO_WINDOWS, "Server Windows (lettura diretta del registro eventi)"),
        (TIPO_DOMINIO, "Tutti i PC del dominio (lettura diretta di ogni PC, come BusinessLog)"),
        (TIPO_WEF, "Eventi inoltrati a questo server (Windows Event Forwarding)"),
        (TIPO_SYSLOG, "Syslog (ESXi, switch, firewall, NAS, Linux)"),
    ]
    TIPI_WINDOWS = (TIPO_WINDOWS, TIPO_DOMINIO, TIPO_WEF)
    RUOLI = [
        ("dc", "Controller di dominio"),
        ("server", "Server Windows"),
        ("pc", "PC e portatili"),
        ("esxi", "VMware ESXi / vCenter"),
        ("firewall", "Firewall"),
        ("switch", "Switch / rete"),
        ("nas", "NAS / storage"),
        ("linux", "Server Linux"),
        ("altro", "Altro"),
    ]
    EVENTI_ACCESSI = "accessi"
    EVENTI_TUTTO = "tutto"
    EVENTI = [
        (EVENTI_ACCESSI, "Accessi e amministrazione (consigliato)"),
        (EVENTI_TUTTO, "Tutto il registro"),
    ]
    STATO_MAI = "mai"
    STATO_OK = "ok"
    STATO_ERRORE = "errore"

    nome = models.CharField(max_length=120)
    tipo = models.CharField(max_length=12, choices=TIPI)
    ruolo = models.CharField(max_length=12, choices=RUOLI, default="server")
    host = models.CharField(max_length=255, blank=True, default="", help_text="Nome o IP del server da leggere.")
    indirizzi_ip = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Syslog: indirizzi da cui arrivano i messaggi, separati da virgola.",
    )
    canali = models.CharField(max_length=255, blank=True, default="Security,System")
    eventi = models.CharField(max_length=10, choices=EVENTI, default=EVENTI_ACCESSI)
    attiva = models.BooleanField(default=True)
    silenzio_max_ore = models.PositiveSmallIntegerField(default=24)
    FILE_NO = ""
    FILE_MODIFICHE = "modifiche"
    FILE_TUTTO = "tutto"
    AUDIT_FILE = [
        (FILE_NO, "No"),
        (FILE_MODIFICHE, "Modifiche, eliminazioni e permessi (consigliato)"),
        (FILE_TUTTO, "Anche le letture"),
    ]
    audit_file = models.CharField(max_length=10, choices=AUDIT_FILE, blank=True, default=FILE_NO)
    audit_stampe = models.BooleanField(default=False)
    stampe_nomi = models.BooleanField(default=False)
    audit_usb = models.BooleanField(default=False)
    # Come la tabella «Controllo files» di BusinessLog: una cartella per riga, eventualmente «| letture, scritture,
    # eliminazioni». Vuoto = tutte le cartelle che hanno la voce di controllo, con il livello di «audit_file».
    cartelle_file = models.TextField(blank=True, default="")
    # PC del dominio: unità organizzativa da leggere (vuota = tutto il dominio).
    ou_pc = models.CharField(max_length=500, blank=True, default="")
    segnalibri = models.JSONField(default=dict, blank=True)
    stato = models.CharField(max_length=10, default=STATO_MAI)
    ultimo_errore = models.TextField(blank=True, default="")
    ultima_lettura_il = models.DateTimeField(null=True, blank=True)
    ultimo_evento_il = models.DateTimeField(null=True, blank=True)
    righe_oggi = models.PositiveIntegerField(default=0)
    giorno_conteggio = models.DateField(null=True, blank=True)
    errori_consecutivi = models.PositiveSmallIntegerField(default=0)
    riprova_dopo = models.DateTimeField(null=True, blank=True)
    scarto_orologio_s = models.IntegerField(null=True, blank=True)  # syslog: ricevuto - ora del messaggio
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Fonte di log"
        verbose_name_plural = "Fonti di log"

    def __str__(self):
        return self.nome

    def lista_canali(self) -> list[str]:
        canali = [c.strip() for c in (self.canali or "").split(",") if c.strip()]
        for extra, acceso in ((CANALE_STAMPE, self.audit_stampe), (CANALE_USB, self.audit_usb)):
            if acceso and extra.lower() not in {c.lower() for c in canali}:
                canali.append(extra)
        return canali

    def lista_ip(self) -> list[str]:
        return [c.strip() for c in (self.indirizzi_ip or "").replace(";", ",").split(",") if c.strip()]

    def lista_cartelle(self) -> list[tuple[str, frozenset]]:
        from .regole import leggi_cartelle

        return leggi_cartelle(self.cartelle_file)


class Postazione(models.Model):
    """Un PC di una fonte «Tutti i PC del dominio»: elenco da Active Directory, segnalibri e stato suoi.

    Un PC spento non è un errore: si riprova più tardi, senza interruzioni né allarmi.
    """

    STATO_MAI = "mai"
    STATO_OK = "ok"
    STATO_SPENTO = "spento"
    STATO_ERRORE = "errore"

    fonte_id = models.IntegerField(db_index=True)
    nome = models.CharField(max_length=120)
    indirizzo = models.CharField(max_length=255, blank=True, default="")  # nome DNS completo
    sistema = models.CharField(max_length=120, blank=True, default="")
    ultimo_accesso_ad = models.DateTimeField(null=True, blank=True)
    in_ad = models.BooleanField(default=True)  # ancora presente e attivo in Active Directory
    esclusa = models.BooleanField(default=False)  # tolta a mano dalla raccolta
    segnalibri = models.JSONField(default=dict, blank=True)
    stato = models.CharField(max_length=10, default=STATO_MAI)
    ultimo_errore = models.CharField(max_length=500, blank=True, default="")
    errori_consecutivi = models.PositiveSmallIntegerField(default=0)
    riprova_dopo = models.DateTimeField(null=True, blank=True)
    ultima_lettura_il = models.DateTimeField(null=True, blank=True)
    ultimo_contatto_il = models.DateTimeField(null=True, blank=True)
    righe_oggi = models.PositiveIntegerField(default=0)
    giorno_conteggio = models.DateField(null=True, blank=True)
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=["fonte_id", "nome"], name="reglog_postazione_unica")]
        verbose_name = "PC del dominio"
        verbose_name_plural = "PC del dominio"

    def __str__(self):
        return self.nome

    @property
    def host(self) -> str:
        return self.indirizzo or self.nome


class EventoRegistro(models.Model):
    """Un evento importante, estratto dall'archivio. La riga intera resta nel file del giorno."""

    quando = models.DateTimeField(db_index=True)
    ricevuto_il = models.DateTimeField(default=timezone.now)
    fonte_id = models.IntegerField(null=True, blank=True, db_index=True)
    fonte_nome = models.CharField(max_length=120, blank=True, default="")
    host = models.CharField(max_length=255, blank=True, default="")
    canale = models.CharField(max_length=80, blank=True, default="")
    event_id = models.IntegerField(null=True, blank=True)
    categoria = models.CharField(max_length=32, db_index=True)
    esito = models.CharField(max_length=4, blank=True, default="")  # ok | ko
    gravita = models.CharField(max_length=10, default="info")  # info | warning | high
    account = models.CharField(max_length=150, blank=True, default="", db_index=True)
    dominio = models.CharField(max_length=120, blank=True, default="")
    account_target = models.CharField(max_length=255, blank=True, default="")
    ip_origine = models.CharField(max_length=64, blank=True, default="")
    tipo_accesso = models.CharField(max_length=40, blank=True, default="")
    descrizione = models.CharField(max_length=400, blank=True, default="")
    oggetto = models.CharField(max_length=500, blank=True, default="")  # file, stampante o dispositivo
    quantita = models.IntegerField(null=True, blank=True)  # pagine stampate
    privilegiato = models.BooleanField(default=False, db_index=True)
    fuori_orario = models.BooleanField(default=False)
    archivio_giorno = models.DateField(null=True, blank=True)
    archivio_riga = models.IntegerField(null=True, blank=True)
    inviato_soc = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-quando", "-id"]
        indexes = [
            models.Index(fields=["categoria", "quando"], name="reglog_ev_cat_quando"),
            models.Index(fields=["account", "quando"], name="reglog_ev_acc_quando"),
        ]
        verbose_name = "Evento del registro"
        verbose_name_plural = "Eventi del registro"

    def __str__(self):
        return f"{self.quando:%Y-%m-%d %H:%M} {self.categoria} {self.account}"


class SigilloGiorno(models.Model):
    """Impronta di un giorno d'archivio, legata a quella del giorno prima."""

    giorno = models.DateField(unique=True)
    file = models.CharField(max_length=500, blank=True, default="")
    righe = models.PositiveIntegerField(default=0)
    byte = models.BigIntegerField(default=0)
    hash_ultima_riga = models.CharField(max_length=64, blank=True, default="")
    sha256_file = models.CharField(max_length=64, blank=True, default="")
    hash_precedente = models.CharField(max_length=64)
    hash_sigillo = models.CharField(max_length=64)
    creato_il = models.DateTimeField(auto_now_add=True)
    verificato_il = models.DateTimeField(null=True, blank=True)
    verifica_ok = models.BooleanField(null=True)
    verifica_esito = models.CharField(max_length=500, blank=True, default="")
    copia_il = models.DateTimeField(null=True, blank=True)
    copia_esito = models.CharField(max_length=500, blank=True, default="")
    eliminato_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-giorno"]
        verbose_name = "Sigillo giornaliero"
        verbose_name_plural = "Sigilli giornalieri"

    def __str__(self):
        return f"Sigillo {self.giorno:%Y-%m-%d}"


class Interruzione(models.Model):
    """Periodo senza raccolta: va spiegato in sede di verifica (manutenzione, guasto…)."""

    MOTIVI = [
        ("raccoglitore_fermo", "Raccoglitore fermo"),
        ("fonte_muta", "Fonte senza messaggi"),
        ("errore_lettura", "Lettura non riuscita"),
        ("eventi_persi", "Eventi sovrascritti prima della lettura"),
        ("sovraccarico", "Troppi messaggi: una parte scartata"),
        ("file_riparato", "File del giorno riparato dopo un arresto"),
        ("errore_scrittura", "Scrittura dell'archivio non riuscita"),
    ]

    fonte_id = models.IntegerField(null=True, blank=True, db_index=True)
    fonte_nome = models.CharField(max_length=120, blank=True, default="")
    motivo = models.CharField(max_length=24, choices=MOTIVI)
    dal = models.DateTimeField(db_index=True)
    al = models.DateTimeField(null=True, blank=True)
    dettaglio = models.CharField(max_length=500, blank=True, default="")
    giustificazione = models.CharField(max_length=500, blank=True, default="")
    giustificata_da = models.CharField(max_length=150, blank=True, default="")
    giustificata_il = models.DateTimeField(null=True, blank=True)
    inviata_soc = models.BooleanField(default=False)

    class Meta:
        ordering = ["-dal"]
        verbose_name = "Interruzione della raccolta"
        verbose_name_plural = "Interruzioni della raccolta"

    def __str__(self):
        return f"{self.get_motivo_display()} dal {self.dal:%Y-%m-%d %H:%M}"

    @property
    def aperta(self) -> bool:
        return self.al is None


class StatoRaccoglitore(models.Model):
    """Una sola riga (pk=1): segnale di vita del processo ``manage.py registro_log``."""

    battito_il = models.DateTimeField(null=True, blank=True)
    avviato_il = models.DateTimeField(null=True, blank=True)
    host = models.CharField(max_length=120, blank=True, default="")
    pid = models.IntegerField(null=True, blank=True)
    giorno_corrente = models.DateField(null=True, blank=True)
    righe_oggi = models.PositiveIntegerField(default=0)
    syslog_in_ascolto = models.CharField(max_length=120, blank=True, default="")
    spazio_libero_mb = models.BigIntegerField(null=True, blank=True)
    coda = models.PositiveIntegerField(default=0)
    errore = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        verbose_name = "Stato del raccoglitore"
        verbose_name_plural = "Stato del raccoglitore"

    def __str__(self):
        return f"Raccoglitore ({self.battito_il or 'mai partito'})"


# ── Account di Active Directory e amministratori di sistema ─────────────────────


class AccountAD(models.Model):
    """Fotografia di un account di Active Directory, letta via LDAP (solo lettura)."""

    TIPO_PERSONA = "persona"
    TIPO_SERVIZIO = "servizio"
    TIPO_SCONOSCIUTO = "sconosciuto"
    TIPI = [(TIPO_PERSONA, "Persona"), (TIPO_SERVIZIO, "Account di servizio"), (TIPO_SCONOSCIUTO, "Da classificare")]

    sam = models.CharField(max_length=150, unique=True)
    upn = models.CharField(max_length=255, blank=True, default="")
    nome = models.CharField(max_length=255, blank=True, default="")
    email = models.CharField(max_length=255, blank=True, default="")
    dn = models.CharField(max_length=500, blank=True, default="")
    abilitato = models.BooleanField(default=True)
    ultimo_accesso = models.DateTimeField(null=True, blank=True)
    password_cambiata_il = models.DateTimeField(null=True, blank=True)
    password_non_scade = models.BooleanField(default=False)
    creato_ad_il = models.DateTimeField(null=True, blank=True)
    gruppi_privilegiati = models.JSONField(default=list, blank=True)
    tipo = models.CharField(max_length=12, choices=TIPI, default=TIPO_SCONOSCIUTO)
    anagrafica_id = models.IntegerField(null=True, blank=True)
    anagrafica_nome = models.CharField(max_length=255, blank=True, default="")
    persona_cessata = models.BooleanField(default=False)
    abbinamento_manuale = models.BooleanField(default=False)
    responsabile = models.CharField(max_length=255, blank=True, default="")
    nota = models.CharField(max_length=500, blank=True, default="")
    visto_il = models.DateTimeField(null=True, blank=True)
    sparito_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sam"]
        verbose_name = "Account di Active Directory"
        verbose_name_plural = "Account di Active Directory"

    def __str__(self):
        return self.sam

    @property
    def privilegiato(self) -> bool:
        return bool(self.gruppi_privilegiati)


def _percorso_nomina(instance, filename):
    return f"registro_log/nomine/{timezone.now():%Y}/{filename}"


class AmministratoreSistema(models.Model):
    """Elenco degli amministratori di sistema con la nomina (provvedimento del Garante, ISO 27001 A.5.18)."""

    TIPI = [("interno", "Dipendente"), ("esterno", "Fornitore esterno")]

    nome = models.CharField(max_length=255)
    account = models.CharField(max_length=500, blank=True, default="", help_text="Account usati, separati da virgola.")
    anagrafica_id = models.IntegerField(null=True, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPI, default="interno")
    societa = models.CharField(max_length=255, blank=True, default="")
    ambito = models.TextField(blank=True, default="", help_text="Sistemi che amministra.")
    nominato_il = models.DateField(null=True, blank=True)
    documento_nomina = models.FileField(
        upload_to=_percorso_nomina, blank=True, max_length=500,
        storage=PrivateAttachmentStorage(download_hint="Scarica dal Registro accessi › Amministratori di sistema."),
    )
    revocato_il = models.DateField(null=True, blank=True)
    prossima_revisione = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)
    aggiornato_da = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        ordering = ["nome"]
        verbose_name = "Amministratore di sistema"
        verbose_name_plural = "Amministratori di sistema"

    def __str__(self):
        return self.nome

    def lista_account(self) -> list[str]:
        return [a.strip() for a in (self.account or "").replace(";", ",").split(",") if a.strip()]

    @property
    def attivo(self) -> bool:
        return self.revocato_il is None or self.revocato_il > timezone.localdate()


class VerificaAnnuale(models.Model):
    """Verifica annuale dell'operato degli amministratori di sistema (Garante 2008, punto 4.4)."""

    ESITI = [("conforme", "Conforme"), ("rilievi", "Conforme con rilievi"), ("non_conforme", "Non conforme")]

    anno = models.PositiveSmallIntegerField(unique=True)
    eseguita_il = models.DateField()
    eseguita_da = models.CharField(max_length=255)
    esito = models.CharField(max_length=14, choices=ESITI)
    rilievi = models.TextField(blank=True, default="")
    azioni = models.TextField(blank=True, default="")
    riepilogo = models.JSONField(default=dict, blank=True)
    registrata_il = models.DateTimeField(auto_now_add=True)
    registrata_da = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        ordering = ["-anno"]
        verbose_name = "Verifica annuale degli amministratori"
        verbose_name_plural = "Verifiche annuali degli amministratori"

    def __str__(self):
        return f"Verifica {self.anno}"


class Indagine(models.Model):
    """Consultazione motivata degli eventi riservati (file, stampe, USB).

    Questi eventi si raccolgono sempre, ma si guardano solo dentro un'indagine aperta da chi
    configura il SOC, con il motivo (es. sospetto furto di file o di proprietà intellettuale),
    le persone e il periodo. Ogni apertura, consultazione ed export resta nell'audit.
    """

    motivo = models.TextField()
    riferimento = models.CharField(max_length=255, blank=True, default="", help_text="Es. numero dell'incidente o della pratica.")
    account = models.CharField(max_length=500, blank=True, default="", help_text="Account da esaminare, separati da virgola.")
    dal = models.DateField()
    al = models.DateField()
    filtro_testo = models.CharField(max_length=255, blank=True, default="", help_text="Facoltativo: parte del percorso, stampante o dispositivo.")
    aperta_da = models.CharField(max_length=150)
    aperta_il = models.DateTimeField(auto_now_add=True)
    chiusa_il = models.DateTimeField(null=True, blank=True)
    chiusa_da = models.CharField(max_length=150, blank=True, default="")
    esito = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-aperta_il"]
        verbose_name = "Indagine"
        verbose_name_plural = "Indagini"

    def __str__(self):
        return f"Indagine {self.pk} del {self.aperta_il:%Y-%m-%d}"

    def lista_account(self) -> list[str]:
        return [a.strip() for a in (self.account or "").replace(";", ",").split(",") if a.strip()]

    @property
    def aperta(self) -> bool:
        return self.chiusa_il is None


# ── Infrastruttura: ESXi / vCenter e controller iLO / iDRAC (solo stato attuale) ──


class ApparatoInfra(models.Model):
    """Un host ESXi/vCenter o un controller iLO/iDRAC letto in sola lettura.

    Si tiene solo l'ultima fotografia (sovrascritta a ogni lettura): niente storico.
    I loro accessi e messaggi arrivano dal syslog nell'archivio.
    """

    TIPO_VSPHERE = "vsphere"
    TIPO_REDFISH = "redfish"
    TIPI = [(TIPO_VSPHERE, "VMware ESXi / vCenter"), (TIPO_REDFISH, "iLO / iDRAC (Redfish)")]

    nome = models.CharField(max_length=120)
    tipo = models.CharField(max_length=10, choices=TIPI)
    indirizzo = models.CharField(max_length=255)
    porta = models.PositiveIntegerField(default=443)
    utente = models.CharField(max_length=150, blank=True, default="")
    password_cifrata = models.TextField(blank=True, default="")
    verifica_certificato = models.BooleanField(default=False)
    attivo = models.BooleanField(default=True)
    stato = models.JSONField(default=dict, blank=True)
    problemi = models.JSONField(default=list, blank=True)
    letto_il = models.DateTimeField(null=True, blank=True)
    errore = models.CharField(max_length=500, blank=True, default="")
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tipo", "nome"]
        verbose_name = "Apparato (ESXi, iLO, iDRAC)"
        verbose_name_plural = "Apparati (ESXi, iLO, iDRAC)"

    def __str__(self):
        return self.nome
