"""Modelli per la centrale MFC e il monitoraggio SNMP read-only."""
from decimal import Decimal
import uuid
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

# I quattro contatori usati ovunque: (campo, etichetta)
CONTATORI = (("a4_bn", "A4 BN"), ("a3_bn", "A3 BN"),
             ("a4_col", "A4 COL"), ("a3_col", "A3 COL"))

_oid_validator = RegexValidator(
    regex=r"^\d+(?:\.\d+)+$",
    message="Inserisci un OID numerico puntato, ad esempio 1.3.6.1.2.1.1.3.0.",
)
# Colonne e sonde: anche "A+B" (solo GET), letti e sommati da snmp.leggi_specifiche.
_oid_colonna_validator = RegexValidator(
    regex=r"^\d+(?:\.\d+)+(?:\+\d+(?:\.\d+)+)*$",
    message="Inserisci un OID numerico puntato (es. 1.3.6.1.2.1.1.3.0) "
            "oppure piu' OID uniti da + da sommare (solo modalita GET).",
)


def etichetta_valore(etichette, numero):
    """Traduce un codice numerico con la mappa "1=Normale, 2=Guasto"; "" se assente."""
    if not etichette or numero is None:
        return ""
    try:
        chiave = int(numero)
    except (TypeError, ValueError, ArithmeticError):
        return ""
    if chiave != numero:
        return ""
    for voce in etichette.split(","):
        codice, sep, testo = voce.partition("=")
        if sep and codice.strip().lstrip("-").isdigit() and int(codice) == chiave:
            return testo.strip()
    return ""


ETICHETTE_HELP = "Testo per i codici numerici, es. 1=Normale, 2=Guasto."


class StatoSNMP(models.TextChoices):
    MAI = "MAI", "Mai interrogato"
    OK = "OK", "Operativo"
    WARNING = "WARNING", "Attenzione"
    ERROR = "ERROR", "Errore"


class CommunitySNMP(models.Model):
    """Credenziale read-only nominata; il valore non viene mai reso nei form."""

    nome = models.CharField(max_length=80, unique=True)
    segreto_cifrato = models.TextField(editable=False)
    versione = models.CharField(max_length=4, blank=True, choices=[
        ("", "Versione della scansione"), ("v1", "SNMPv1"), ("v2c", "SNMPv2c"),
        ("v3", "SNMPv3")])
    porta = models.PositiveIntegerField(null=True, blank=True)
    ordine = models.PositiveIntegerField(default=0)
    attiva = models.BooleanField(default=True)
    aggiornata_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name_plural = "Community SNMP"

    def __str__(self):
        return self.nome


class DiscoverySNMP(models.Model):
    class Stato(models.TextChoices):
        ATTESA = "ATTESA", "In coda"
        CORSO = "CORSO", "In corso"
        COMPLETA = "COMPLETA", "Completata"
        ERRORE = "ERRORE", "Da riprendere"
        ANNULLATA = "ANNULLATA", "Interrotta"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    richiesta_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                    on_delete=models.SET_NULL)
    rete = models.CharField(max_length=64)
    hosts = models.JSONField(default=list)
    community_ids = models.JSONField(default=list)  # 0 = globale; mai segreti
    versione = models.CharField(max_length=4)
    porta = models.PositiveIntegerField(default=161)
    timeout = models.PositiveIntegerField(default=2)
    stato = models.CharField(max_length=10, choices=Stato.choices, default=Stato.ATTESA)
    cursore = models.PositiveIntegerField(default=0)
    candidata = models.PositiveIntegerField(default=0)
    revisione = models.PositiveIntegerField(default=0)
    completati = models.PositiveIntegerField(default=0)
    risultati = models.JSONField(default=list)
    errore = models.CharField(max_length=250, blank=True)
    creata_il = models.DateTimeField(auto_now_add=True)
    aggiornata_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creata_il"]

    @property
    def attiva(self):
        return self.stato in (self.Stato.ATTESA, self.Stato.CORSO)

    @property
    def ferma(self):
        return self.attiva and self.aggiornata_il < timezone.now() - timedelta(minutes=2)

    @property
    def riprendibile(self):
        return self.ferma or self.stato in (self.Stato.ERRORE, self.Stato.ANNULLATA)

    @property
    def percentuale(self):
        return int(100 * self.completati / len(self.hosts)) if self.hosts else 0


class ProfiloSNMP(models.Model):
    """Profilo riutilizzabile per riconoscimento e configurazione SNMP."""

    class Categoria(models.TextChoices):
        STAMPANTE = "STAMPANTE", "Stampante / MFC"
        FIREWALL = "FIREWALL", "Firewall / sicurezza"
        RETE = "RETE", "Switch / router / Wi-Fi"
        SERVER = "SERVER", "Server / hypervisor"
        STORAGE = "STORAGE", "NAS / storage"
        UPS = "UPS", "UPS / alimentazione"
        AMBIENTE = "AMBIENTE", "Sensore / ambiente"
        TVCC_NVR = "TVCC_NVR", "TVCC - Videoregistratore (NVR)"
        TVCC_TELECAMERA = "TVCC_CAMERA", "TVCC - Telecamera IP"
        GENERICO = "GENERICO", "Generico"

    class Versione(models.TextChoices):
        GLOBALE = "", "Usa configurazione globale"
        V1 = "v1", "SNMPv1"
        V2C = "v2c", "SNMPv2c"
        V3 = "v3", "SNMPv3"

    slug = models.SlugField(max_length=80, unique=True)
    nome = models.CharField(max_length=120)
    produttore = models.CharField(max_length=80, db_index=True)
    categoria = models.CharField(
        max_length=16, choices=Categoria.choices, default=Categoria.GENERICO,
        db_index=True,
    )
    famiglia_modelli = models.CharField(max_length=160, blank=True)
    descrizione = models.TextField(blank=True)
    sys_object_id_prefix = models.CharField(
        max_length=255, blank=True, validators=[_oid_validator],
        help_text="Prefisso enterprise usato per il riconoscimento automatico.",
    )
    sys_descr_pattern = models.CharField(
        max_length=255, blank=True,
        help_text="Espressione regolare opzionale applicata a sysDescr.",
    )
    oid_riconoscimento = models.CharField(
        max_length=255, blank=True, validators=[_oid_validator],
        help_text=(
            "OID letto con GET durante il riconoscimento: se risponde, il profilo prevale. "
            "Per apparati con sysObjectID generico (es. Synology si presenta come net-snmp)."
        ),
    )
    versione = models.CharField(
        max_length=4, blank=True, choices=Versione.choices,
    )
    porta = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
    )
    timeout = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
    )
    precaricato = models.BooleanField(default=False)
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["produttore", "nome"]
        verbose_name = "Profilo SNMP"
        verbose_name_plural = "Profili SNMP"

    def __str__(self):
        return f"{self.produttore} - {self.nome}"


class ColonnaProfiloSNMP(models.Model):
    """OID di un profilo, copiabile come sonda o usabile come contatore MFC."""

    class TipoValore(models.TextChoices):
        NUMERO = "NUMERO", "Numero"
        TESTO = "TESTO", "Testo"
        TIMETICKS = "TIMETICKS", "Tempo (TimeTicks)"
        ERRORI_STAMPANTE = "ERR_PRT", "Errori stampante (hrPrinterDetectedErrorState)"
        MAC = "MAC", "Indirizzo MAC (ifPhysAddress)"

    class Modalita(models.TextChoices):
        GET = "GET", "GET (OID esatto)"
        WALK = "WALK", "WALK (colonna MIB)"

    class Aggregazione(models.TextChoices):
        PRIMO = "PRIMO", "Primo valore"
        # Salta i valori vuoti o a zero: in ifPhysAddress la prima riga e' spesso
        # il loopback, senza MAC.
        PRIMO_VALIDO = "VALIDO", "Primo valore non vuoto"
        MASSIMO = "MASSIMO", "Valore massimo"
        MINIMO = "MINIMO", "Valore minimo"
        SOMMA = "SOMMA", "Somma"
        MEDIA = "MEDIA", "Media"

    class ContatoreMFC(models.TextChoices):
        NESSUNO = "", "Non e un contatore MFC"
        A4_BN = "a4_bn", "A4 BN"
        A3_BN = "a3_bn", "A3 BN"
        A4_COL = "a4_col", "A4 colore"
        A3_COL = "a3_col", "A3 colore"

    profilo = models.ForeignKey(
        ProfiloSNMP, on_delete=models.CASCADE, related_name="colonne",
    )
    nome = models.CharField(max_length=100)
    oid = models.CharField(max_length=255, validators=[_oid_colonna_validator])
    tipo_valore = models.CharField(
        max_length=10, choices=TipoValore.choices, default=TipoValore.NUMERO,
    )
    modalita = models.CharField(
        max_length=8, choices=Modalita.choices, default=Modalita.GET,
    )
    aggregazione = models.CharField(
        max_length=10, choices=Aggregazione.choices, default=Aggregazione.PRIMO,
    )
    unita = models.CharField(max_length=24, blank=True)
    fattore = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("1"))
    contatore_mfc = models.CharField(
        max_length=8, blank=True, choices=ContatoreMFC.choices,
    )
    # Soglie predefinite copiate sulle sonde quando il profilo viene applicato.
    soglia_warning_min = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    soglia_warning_max = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    soglia_critica_min = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    soglia_critica_max = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    etichette = models.CharField(max_length=500, blank=True, help_text=ETICHETTE_HELP)
    verificata = models.BooleanField(
        default=False, help_text="OID confermato su un walk reale o su una MIB ufficiale.",
    )
    fonte = models.CharField(
        max_length=200, blank=True,
        help_text="Origine della verifica (walk apparato/firmware o MIB).",
    )
    ordine = models.PositiveIntegerField(default=0)
    attiva = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["profilo", "oid"], name="contatori_profilo_oid_unico",
            ),
            models.UniqueConstraint(
                fields=["profilo", "contatore_mfc"],
                # `> ''` e non `~Q(... = '')`: SQL Server non accetta NOT negli indici filtrati.
                condition=models.Q(contatore_mfc__gt=""),
                name="contatori_profilo_contatore_mfc_unico",
            ),
        ]
        verbose_name = "Colonna profilo SNMP"
        verbose_name_plural = "Colonne profilo SNMP"

    def __str__(self):
        return f"{self.profilo} - {self.nome}"


class Macchina(models.Model):
    """Una multifunzione. Macchine con lo stesso `contratto` sono fatturate in pool."""
    class Fornitore(models.TextChoices):
        BASE = "BASE", "BASE SPA"
        COPYLAB = "COPYLAB", "Copylab"

    class Modello(models.TextChoices):
        """Valori Canon legacy mantenuti per compatibilita con i record esistenti.

        I nuovi modelli sono testo libero ma, se non appartengono a questa lista,
        il form richiede un :class:`ProfiloSNMP` con OID espliciti.
        """
        C5535I = "iR-ADV C5535i", "Canon iR-ADV C5535i"
        DX_C5840I = "iR-ADV DX C5840i", "Canon iR-ADV DX C5840i"
        DX_C3822I = "iR-ADV DX C3822i", "Canon iR-ADV DX C3822i"

    reparto = models.CharField(max_length=60)
    matricola = models.CharField(max_length=40, unique=True)
    modello = models.CharField(
        max_length=120, blank=True,
        help_text="Modello dichiarato dal produttore. Il profilo stabilisce gli OID.",
    )
    contratto = models.CharField(max_length=20, blank=True,
                                 help_text="Stesso contratto = fatturazione in pool")
    fornitore = models.CharField(max_length=10, choices=Fornitore.choices,
                                 default=Fornitore.BASE)
    host = models.GenericIPAddressField(null=True, blank=True,
                                        help_text="IP per lettura SNMP")
    profilo_snmp = models.ForeignKey(
        ProfiloSNMP, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="macchine",
        help_text="Profilo OID; se vuoto il portale prova il riconoscimento automatico.",
    )
    snmp_porta = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Vuoto = profilo o configurazione globale.",
    )
    community_salvata = models.ForeignKey(
        CommunitySNMP, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="Se selezionata, prevale sulla community manuale e globale.")
    snmp_community = models.CharField(
        max_length=60, blank=True,
        help_text="Vuoto = community globale; usare una community read-only.",
    )
    snmp_versione = models.CharField(
        max_length=4, blank=True, choices=ProfiloSNMP.Versione.choices,
        help_text="Vuoto = profilo o configurazione globale.",
    )
    snmp_timeout = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Vuoto = profilo o configurazione globale.",
    )
    attiva = models.BooleanField(default=True)
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="contatori_macchine",
        help_text="Asset del registro HUB collegato (match matricola↔serial / host↔IP).",
    )
    snmp_stato = models.CharField(
        max_length=10, choices=StatoSNMP.choices, default=StatoSNMP.MAI,
    )
    snmp_ultimo_controllo = models.DateTimeField(null=True, blank=True)
    snmp_tempo_risposta_ms = models.PositiveIntegerField(null=True, blank=True)
    snmp_ultimo_errore = models.CharField(max_length=500, blank=True)
    # Ultima lettura completa della stampante (stato, display, avvisi, cassetti, sportelli, toner):
    # stessa struttura di RilevazioneSNMP.dati_stampante, aggiornata dal polling ogni 15 minuti.
    dati_stampante = models.JSONField(default=dict, blank=True)
    dati_stampante_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["reparto"]
        verbose_name_plural = "Macchine"

    def __str__(self):
        return f"{self.reparto} ({self.matricola})"


class DispositivoSNMP(models.Model):
    """Nodo SNMP generico monitorato dalla centrale.

    Community dal catalogo cifrato, dall'override manuale preesistente o dal
    singleton globale. Tutte le operazioni SNMP sono esclusivamente in lettura.
    """

    class Categoria(models.TextChoices):
        LETTORE = "LETTORE", "Lettore / terminale"
        STAMPANTE = "STAMPANTE", "Stampante / MFC extra"
        FIREWALL = "FIREWALL", "Firewall / sicurezza"
        RETE = "RETE", "Rete"
        SERVER = "SERVER", "Server / hypervisor"
        STORAGE = "STORAGE", "NAS / storage"
        UPS = "UPS", "UPS / alimentazione"
        AMBIENTE = "AMBIENTE", "Sensore ambiente"
        # Videosorveglianza: intervallo di polling e retention propri (ImpostazioniSNMP).
        TVCC_NVR = "TVCC_NVR", "TVCC - Videoregistratore (NVR)"
        TVCC_TELECAMERA = "TVCC_CAMERA", "TVCC - Telecamera IP"
        ALTRO = "ALTRO", "Altro dispositivo"

    CATEGORIE_TVCC = ("TVCC_NVR", "TVCC_CAMERA")

    class Versione(models.TextChoices):
        GLOBALE = "", "Usa configurazione globale"
        V1 = "v1", "SNMPv1"
        V2C = "v2c", "SNMPv2c"
        V3 = "v3", "SNMPv3"

    nome = models.CharField(max_length=100)
    categoria = models.CharField(
        max_length=16, choices=Categoria.choices, default=Categoria.LETTORE,
    )
    host = models.GenericIPAddressField(unique=True)
    porta = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Vuoto = porta SNMP globale.",
    )
    versione = models.CharField(
        max_length=4, blank=True, choices=Versione.choices,
        help_text="Vuoto = versione SNMP globale.",
    )
    community_salvata = models.ForeignKey(
        CommunitySNMP, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="Se selezionata, prevale sulla community manuale e globale.")
    community = models.CharField(
        max_length=60, blank=True,
        help_text="Vuoto = community globale; usare una community read-only.",
    )
    timeout = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Vuoto = timeout del profilo o globale.",
    )
    profilo_snmp = models.ForeignKey(
        ProfiloSNMP, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dispositivi",
        help_text="Profilo OID; se vuoto viene proposto automaticamente dopo il primo test.",
    )
    posizione = models.CharField(max_length=120, blank=True)
    produttore = models.CharField(max_length=80, blank=True)
    modello = models.CharField(max_length=120, blank=True)
    matricola = models.CharField(max_length=80, blank=True)
    note = models.TextField(blank=True)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dispositivi_snmp",
    )
    attivo = models.BooleanField(default=True)
    # False = creato senza un test di connessione riuscito (bozza del wizard o form
    # completo): resta «non verificato» finche' una lettura SNMP non va a buon fine.
    verificato = models.BooleanField(default=True)
    snmp_stato = models.CharField(
        max_length=10, choices=StatoSNMP.choices, default=StatoSNMP.MAI,
    )
    snmp_ultimo_controllo = models.DateTimeField(null=True, blank=True)
    snmp_tempo_risposta_ms = models.PositiveIntegerField(null=True, blank=True)
    snmp_ultimo_errore = models.CharField(max_length=500, blank=True)
    sys_name = models.CharField(max_length=255, blank=True)
    sys_description = models.TextField(blank=True)
    sys_object_id = models.CharField(max_length=255, blank=True)
    sys_uptime_seconds = models.PositiveBigIntegerField(null=True, blank=True)
    firmware = models.CharField(max_length=80, blank=True,
                                help_text="Versione firmware dell'ultima lettura riuscita (sonda «Firmware» o sysDescr).")
    firmware_fonte = models.CharField(max_length=120, blank=True)
    firmware_rilevato_il = models.DateTimeField(null=True, blank=True)
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria", "nome"]
        verbose_name = "Dispositivo SNMP"
        verbose_name_plural = "Dispositivi SNMP"

    def __str__(self):
        return f"{self.nome} ({self.host})"


class SondaSNMP(models.Model):
    """Lettore configurabile di un singolo OID su un dispositivo."""

    class TipoValore(models.TextChoices):
        NUMERO = "NUMERO", "Numero"
        TESTO = "TESTO", "Testo"
        TIMETICKS = "TIMETICKS", "Tempo (TimeTicks)"
        ERRORI_STAMPANTE = "ERR_PRT", "Errori stampante (hrPrinterDetectedErrorState)"
        MAC = "MAC", "Indirizzo MAC (ifPhysAddress)"

    class Modalita(models.TextChoices):
        GET = "GET", "GET (OID esatto)"
        WALK = "WALK", "WALK (colonna MIB)"

    class Aggregazione(models.TextChoices):
        PRIMO = "PRIMO", "Primo valore"
        # Salta i valori vuoti o a zero: in ifPhysAddress la prima riga e' spesso
        # il loopback, senza MAC.
        PRIMO_VALIDO = "VALIDO", "Primo valore non vuoto"
        MASSIMO = "MASSIMO", "Valore massimo"
        MINIMO = "MINIMO", "Valore minimo"
        SOMMA = "SOMMA", "Somma"
        MEDIA = "MEDIA", "Media"

    dispositivo = models.ForeignKey(
        DispositivoSNMP, on_delete=models.CASCADE, related_name="sonde",
    )
    profilo_colonna = models.ForeignKey(
        ColonnaProfiloSNMP, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sonde_generate",
        help_text="Colonna del catalogo che ha generato questa sonda; vuoto se manuale.",
    )
    nome = models.CharField(max_length=100)
    oid = models.CharField(max_length=255, validators=[_oid_colonna_validator])
    tipo_valore = models.CharField(
        max_length=10, choices=TipoValore.choices, default=TipoValore.NUMERO,
    )
    modalita = models.CharField(
        max_length=8, choices=Modalita.choices, default=Modalita.GET,
    )
    aggregazione = models.CharField(
        max_length=10, choices=Aggregazione.choices, default=Aggregazione.PRIMO,
    )
    unita = models.CharField(max_length=24, blank=True)
    fattore = models.DecimalField(
        max_digits=14, decimal_places=6, default=Decimal("1"),
        help_text="Moltiplicatore applicato al valore numerico grezzo.",
    )
    etichette = models.CharField(max_length=500, blank=True, help_text=ETICHETTE_HELP)
    soglia_warning_min = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    soglia_warning_max = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    soglia_critica_min = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    soglia_critica_max = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    attiva = models.BooleanField(default=True)
    ordine = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordine", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["dispositivo", "oid"], name="contatori_sonda_oid_unico",
            ),
        ]
        verbose_name = "Sonda SNMP"
        verbose_name_plural = "Sonde SNMP"

    def __str__(self):
        return f"{self.dispositivo.nome} · {self.nome}"

    def stato_per_valore(self, valore):
        if valore is None:
            return StatoSNMP.ERROR
        if ((self.soglia_critica_min is not None and valore < self.soglia_critica_min)
                or (self.soglia_critica_max is not None and valore > self.soglia_critica_max)):
            return StatoSNMP.ERROR
        if ((self.soglia_warning_min is not None and valore < self.soglia_warning_min)
                or (self.soglia_warning_max is not None and valore > self.soglia_warning_max)):
            return StatoSNMP.WARNING
        return StatoSNMP.OK


class RilevazioneSNMP(models.Model):
    """Esito immutabile di un'interrogazione di un dispositivo generico."""

    dispositivo = models.ForeignKey(
        DispositivoSNMP, on_delete=models.CASCADE, related_name="rilevazioni",
    )
    rilevata_il = models.DateTimeField(default=timezone.now, db_index=True)
    stato = models.CharField(max_length=10, choices=StatoSNMP.choices)
    tempo_risposta_ms = models.PositiveIntegerField(null=True, blank=True)
    errore = models.CharField(max_length=500, blank=True)
    sys_name = models.CharField(max_length=255, blank=True)
    sys_description = models.TextField(blank=True)
    sys_object_id = models.CharField(max_length=255, blank=True)
    sys_uptime_seconds = models.PositiveBigIntegerField(null=True, blank=True)
    dati_stampante = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-rilevata_il", "-pk"]
        verbose_name = "Rilevazione SNMP"
        verbose_name_plural = "Rilevazioni SNMP"


class AvvisoStampante(models.Model):
    """Registro avvisi di una stampante: un avviso dalla prima volta che compare a quando sparisce.

    Viene dalla tabella avvisi della stampante (Printer-MIB) o, se manca, dagli errori rilevati
    (Host-Resources). Una riga aperta (``chiuso_il`` vuoto) è un avviso ancora presente.
    """

    dispositivo = models.ForeignKey(DispositivoSNMP, on_delete=models.CASCADE, null=True, blank=True,
                                    related_name="avvisi_stampante")
    macchina = models.ForeignKey("Macchina", on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="avvisi_stampante")
    chiave = models.CharField(max_length=255)
    testo = models.CharField(max_length=255)
    descrizione = models.CharField(max_length=120, blank=True)
    gravita = models.CharField(max_length=20, blank=True)
    gruppo = models.CharField(max_length=40, blank=True)
    chi = models.CharField(max_length=40, blank=True, help_text="Chi deve intervenire, secondo la stampante.")
    critico = models.BooleanField(default=False)
    informativo = models.BooleanField(default=False, help_text="Evento di normale funzionamento (accensione, pronta).")
    aperto_il = models.DateTimeField(default=timezone.now)
    ultimo_visto_il = models.DateTimeField(default=timezone.now)
    chiuso_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-aperto_il", "-pk"]
        indexes = [models.Index(fields=["dispositivo", "chiuso_il"], name="contatori_avvprt_disp_chiuso"),
                   models.Index(fields=["macchina", "chiuso_il"], name="contatori_avvprt_mac_chiuso")]
        verbose_name = "Avviso stampante"
        verbose_name_plural = "Avvisi stampante"

    def __str__(self):
        return f"{self.macchina or self.dispositivo} · {self.testo}"

    @property
    def durata_secondi(self):
        return max(0, int(((self.chiuso_il or self.ultimo_visto_il) - self.aperto_il).total_seconds()))


class SostituzioneConsumabile(models.Model):
    """Cambio di un consumabile (toner, tamburo, fusore…) dedotto dalle letture SNMP.

    Si registra quando il livello di un consumabile risale di più di 5 punti da una lettura
    alla successiva. ``rilevata_il`` è la prima lettura con il livello nuovo: il cambio è
    avvenuto fra ``ultima_lettura_prima`` e ``rilevata_il``.
    """

    dispositivo = models.ForeignKey(DispositivoSNMP, on_delete=models.CASCADE, null=True, blank=True,
                                    related_name="sostituzioni_consumabili")
    macchina = models.ForeignKey("Macchina", on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="sostituzioni_consumabili")
    nome = models.CharField(max_length=120)
    tipo = models.CharField(max_length=40, blank=True)
    pct_prima = models.PositiveSmallIntegerField()
    pct_dopo = models.PositiveSmallIntegerField()
    ultima_lettura_prima = models.DateTimeField(null=True, blank=True)
    rilevata_il = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-rilevata_il", "-pk"]
        indexes = [models.Index(fields=["dispositivo", "nome", "rilevata_il"], name="contatori_sost_disp_nome_dt"),
                   models.Index(fields=["macchina", "nome", "rilevata_il"], name="contatori_sost_mac_nome_dt")]
        verbose_name = "Sostituzione consumabile"
        verbose_name_plural = "Sostituzioni consumabili"

    def __str__(self):
        return f"{self.macchina or self.dispositivo} · {self.nome} {self.pct_prima}% → {self.pct_dopo}%"


class FirmwareSNMP(models.Model):
    """Storico delle versioni firmware viste su un dispositivo: una riga per versione."""

    dispositivo = models.ForeignKey(
        DispositivoSNMP, on_delete=models.CASCADE, related_name="firmware_storico",
    )
    versione = models.CharField(max_length=80)
    fonte = models.CharField(max_length=120, blank=True)
    primo_rilevamento = models.DateTimeField(default=timezone.now)
    ultimo_rilevamento = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-primo_rilevamento", "-pk"]
        verbose_name = "Firmware rilevato"
        verbose_name_plural = "Firmware rilevati"

    def __str__(self):
        return f"{self.dispositivo} {self.versione}"


class ValoreSNMP(models.Model):
    """Valore storicizzato di una sonda durante una rilevazione."""

    rilevazione = models.ForeignKey(
        RilevazioneSNMP, on_delete=models.CASCADE, related_name="valori",
    )
    sonda = models.ForeignKey(
        SondaSNMP, on_delete=models.CASCADE, related_name="valori",
    )
    valore_numero = models.DecimalField(
        max_digits=30, decimal_places=6, null=True, blank=True,
    )
    valore_testo = models.TextField(blank=True)
    stato = models.CharField(max_length=10, choices=StatoSNMP.choices)
    errore = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["sonda__ordine", "sonda__nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["rilevazione", "sonda"], name="contatori_valore_sonda_rilevazione_unico",
            ),
        ]
        verbose_name = "Valore SNMP"
        verbose_name_plural = "Valori SNMP"

    @property
    def valore_display(self):
        if self.valore_numero is not None:
            etichetta = etichetta_valore(self.sonda.etichette, self.valore_numero)
            if etichetta:
                return etichetta
            valore = format(self.valore_numero.normalize(), "f")
            return f"{valore} {self.sonda.unita}".strip()
        return self.valore_testo or "—"


class LetturaContatori(models.Model):
    """Snapshot dei 4 contatori di una macchina in un dato trimestre."""
    class Fonte(models.TextChoices):
        SNMP = "SNMP", "SNMP"
        MANUALE = "MANUALE", "Manuale"
        FATTURA = "FATTURA", "Da fattura"

    macchina = models.ForeignKey(Macchina, on_delete=models.CASCADE, related_name="letture")
    trimestre = models.CharField(max_length=8, help_text='Es. "2026-Q2"')
    data = models.DateField(help_text="Data della rilevazione")
    a4_bn = models.PositiveIntegerField(default=0)
    a3_bn = models.PositiveIntegerField(default=0)
    a4_col = models.PositiveIntegerField(default=0)
    a3_col = models.PositiveIntegerField(default=0)
    fonte = models.CharField(max_length=10, choices=Fonte.choices, default=Fonte.MANUALE)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-trimestre", "macchina__reparto"]
        unique_together = ("macchina", "trimestre")
        verbose_name = "Lettura contatori"
        verbose_name_plural = "Letture contatori"

    def __str__(self):
        return f"{self.macchina.reparto} {self.trimestre}"

    @property
    def totale(self):
        return self.a4_bn + self.a3_bn + self.a4_col + self.a3_col


class LetturaConsumabile(models.Model):
    """Livello di un consumabile (toner, tamburo, fusore) letto via SNMP.

    Una riga per consumabile e lettura: lo storico serve alla stima dei giorni
    residui e a mostrare i livelli senza interrogare le stampanti all'apertura.
    """
    macchina = models.ForeignKey(Macchina, on_delete=models.CASCADE, related_name="consumabili")
    nome = models.CharField(max_length=120)
    pct = models.PositiveSmallIntegerField(null=True, blank=True,
                                           help_text="Livello in %; vuoto se la stampante non lo dichiara")
    rilevata_il = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-rilevata_il", "nome"]
        indexes = [models.Index(fields=["macchina", "nome", "rilevata_il"], name="contatori_cons_mac_nome_dt")]
        verbose_name = "Lettura consumabile"
        verbose_name_plural = "Letture consumabili"

    def __str__(self):
        return f"{self.macchina} {self.nome} {self.pct}%"


class LetturaMensileContatori(models.Model):
    """Snapshot cumulativo mensile, indipendente dalla riconciliazione trimestrale."""

    macchina = models.ForeignKey(
        Macchina, on_delete=models.CASCADE, related_name="letture_mensili",
    )
    mese = models.DateField(help_text="Primo giorno del mese di rilevazione")
    rilevata_il = models.DateTimeField(default=timezone.now)
    a4_bn = models.PositiveIntegerField()
    a3_bn = models.PositiveIntegerField()
    a4_col = models.PositiveIntegerField()
    a3_col = models.PositiveIntegerField()

    class Meta:
        ordering = ["-mese", "macchina__reparto"]
        constraints = [models.UniqueConstraint(
            fields=["macchina", "mese"], name="contatori_mfc_mese_unico",
        )]
        verbose_name = "Lettura mensile MFC"
        verbose_name_plural = "Letture mensili MFC"

    @property
    def totale(self):
        return self.a4_bn + self.a3_bn + self.a4_col + self.a3_col

    @property
    def ritardo(self):
        """Distanza dalla chiusura del fornitore (giorno 1 alle 00:00, ora locale)."""
        chiusura = timezone.make_aware(datetime.combine(self.mese, time.min))
        return max(self.rilevata_il - chiusura, timedelta(0))

    @property
    def ritardo_testo(self):
        """"" se letta entro un'ora dalla chiusura, altrimenti "+31 h" / "+3 gg"."""
        ore = int(self.ritardo.total_seconds() // 3600)
        if ore < 1:
            return ""
        return f"+{ore} h" if ore < 48 else f"+{ore // 24} gg"

    def __str__(self):
        return f"{self.macchina} {self.mese:%Y-%m}"


class Fattura(models.Model):
    """Testata fattura fornitore relativa a un trimestre."""
    class Dettaglio(models.TextChoices):
        FORMATO = "FORMATO", "A4/A3 B/N e colore"
        TOTALI = "TOTALI", "Solo totali B/N e colore"

    numero = models.CharField(max_length=30)
    data = models.DateField()
    fornitore = models.CharField(max_length=10, default="BASE")
    dettaglio = models.CharField(
        "Letture in fattura", max_length=8, choices=Dettaglio.choices, default=Dettaglio.FORMATO,
        help_text="Copylab fattura solo i totali B/N e colore: si confrontano con A4+A3 interni.")
    trimestre = models.CharField(max_length=8, help_text='Es. "2026-Q2"')
    periodo_dal = models.DateField(null=True, blank=True)
    periodo_al = models.DateField(help_text="Data di chiusura letture fornitore")

    class Meta:
        ordering = ["-periodo_al"]
        unique_together = ("numero", "trimestre")

    def __str__(self):
        return f"{self.numero} ({self.trimestre})"


class ImpostazioniSNMP(models.Model):
    """Parametri SNMP globali della flotta. Singleton: esiste una sola riga (pk=1)."""
    class Versione(models.TextChoices):
        V1 = "v1", "SNMPv1"
        V2C = "v2c", "SNMPv2c"

    community = models.CharField(max_length=60, default="", blank=True,
                                 help_text="Community SNMP in sola lettura usata quando l'apparato "
                                           "non ne ha una propria. Vuota = nessuna lettura finché "
                                           "non la imposti.")
    port = models.PositiveIntegerField(default=161)
    timeout = models.PositiveIntegerField(default=3, help_text="Secondi di attesa per macchina")
    version = models.CharField(max_length=4, choices=Versione.choices, default=Versione.V1)
    # Videosorveglianza: il monitor gira ogni 5 minuti; questi intervalli dicono ogni
    # quanto un NVR / una telecamera viene davvero interrogato (minimo un giro).
    tvcc_intervallo_nvr = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(5)],
        help_text="Minuti tra due interrogazioni SNMP di un videoregistratore (NVR). Minimo 5.")
    tvcc_intervallo_telecamere = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(5)],
        help_text="Minuti tra due interrogazioni SNMP di una telecamera IP. Minimo 5.")
    tvcc_retention_giorni = models.PositiveIntegerField(
        default=14, validators=[MinValueValidator(1)],
        help_text="Giorni di storico delle rilevazioni SNMP TVCC: le piu' vecchie vengono "
                  "cancellate ogni notte. Lo stato attuale del dispositivo resta.")

    class Meta:
        verbose_name = "Impostazioni SNMP"
        verbose_name_plural = "Impostazioni SNMP"

    def __str__(self):
        return f"SNMP {self.version} · {self.community}:{self.port}"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RigaFattura(models.Model):
    """
    Un'unità di fatturazione (un contratto) con le letture del fornitore alla
    chiusura del periodo. Per il pool 2020/124 la riga contiene le letture cumulate
    di CQF+CQI, come le stampa la fattura. Nelle fatture «solo totali» il totale B/N
    sta in `a4_bn`, il totale colore in `a4_col` e i campi A3 restano a zero.
    """
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="righe")
    contratto = models.CharField(max_length=20)
    descrizione = models.CharField(max_length=120, blank=True)
    a4_bn = models.PositiveIntegerField(default=0)
    a3_bn = models.PositiveIntegerField(default=0)
    a4_col = models.PositiveIntegerField(default=0)
    a3_col = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["contratto"]
        unique_together = ("fattura", "contratto")
        verbose_name = "Riga fattura"
        verbose_name_plural = "Righe fattura"

    def __str__(self):
        return f"{self.fattura.numero} · {self.contratto}"


class MacPortaSwitch(models.Model):
    """MAC visto su una porta di uno switch (tabella MAC: BRIDGE-MIB / Q-BRIDGE-MIB, sola lettura).

    Scritto da ``contatori.tabella_mac``: ogni lettura di uno switch sostituisce le sue righe.
    ``mac_sulla_porta`` serve a distinguere le porte d'accesso (1-3 MAC: lì c'è il PC) dalle
    porte verso altri switch o access point (molti MAC: non dicono dove sta il PC).
    """

    dispositivo = models.ForeignKey(DispositivoSNMP, on_delete=models.CASCADE, related_name="mac_porte")
    mac = models.CharField(max_length=17, db_index=True)
    porta = models.CharField(max_length=120, blank=True, default="", help_text="Nome della porta (ifName) o numero.")
    if_index = models.PositiveIntegerField(null=True, blank=True)
    vlan = models.PositiveIntegerField(null=True, blank=True)
    mac_sulla_porta = models.PositiveIntegerField(default=1)
    letto_il = models.DateTimeField()

    class Meta:
        ordering = ["dispositivo", "porta", "mac"]
        indexes = [models.Index(fields=["dispositivo", "letto_il"], name="cont_macporta_disp_idx")]

    def __str__(self):
        return f"{self.mac} @ {self.dispositivo.nome} {self.porta}"

    @property
    def porta_accesso(self):
        return self.mac_sulla_porta <= 3
