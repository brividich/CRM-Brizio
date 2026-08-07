"""Acquisizione automatica dei referti di sorveglianza sanitaria — NOVICROM HUB.

File separato importato da ``anagrafica/models.py`` con ``from .models_sorveglianza
import *``. Non spostare, non rinominare senza aggiornare l'import nel file principale.

PERCHÉ QUESTI MODELLI, E NON ALTRI

Il modello sanitario esiste già: ``TipoVisitaMedica``, ``VisitaMedica``,
``VisitaSessione``. Qui **non** si duplica nulla di quello. Questi modelli
descrivono soltanto il *tragitto* che una scansione compie prima di diventare una
visita registrata: cosa è arrivato, cosa ci si è letto dentro, chi si è deciso che
fosse, e chi l'ha confermato.

LA DIFFERENZA CON I FOGLI FIRME

L'acquisizione dei fogli firme della formazione si regge su un QR: il documento
dice *da sé* di quale foglio si tratta, e l'identificazione è certa. Qui non c'è
alcun codice: il documento va **riconosciuto**, e un riconoscimento è una
probabilità. Da questo discende tutto il resto — la coda di revisione, il punteggio
conservato su ogni riga, la conferma automatica spenta di default, e il fatto che
la data di nascita valga più della somiglianza di un nome.

COSA NON SI CONSERVA

Il testo grezzo prodotto dall'OCR **non viene mai salvato**. Un referto contiene
anche materiale che al datore di lavoro non compete: il giudizio di idoneità sì
(art. 41 D.Lgs 81/08), la diagnosi no. L'OCR però legge tutta la pagina. Perciò
sopravvivono solo i campi riconosciuti, mentre il testo completo vive in memoria
per il tempo dell'estrazione e poi sparisce. Il PDF originale resta, ma
nell'archivio cifrato fuori webroot, raggiungibile solo da una view con ACL e audit.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

__all__ = [
    "RefertoIntakeConfig",
    "RefertoIntakeRiga",
    "AliasEsameProtocollo",
    "AliasEsitoIdoneita",
]


def _esiti_idoneita():
    """Scelte di esito prese dal modello già esistente, senza import circolare.

    ``models_sorveglianza`` è importato in coda a ``models.py``: importare
    ``VisitaMedica`` in testa al file spezzerebbe il caricamento. Django ≥ 5.0
    accetta un callable per ``choices``, che viene risolto quando serve — cioè
    quando l'app è già caricata per intero.
    """
    from .models import VisitaMedica

    return VisitaMedica.Esito.choices


class RefertoIntakeConfig(models.Model):
    """Singleton — cartella dei referti, parametri di lettura e soglie di match.

    I parametri dell'OCR stanno qui, e non fra le costanti del codice, per una
    ragione precisa: la taratura iniziale è stata misurata su **un solo
    certificato di un solo medico**. Funziona, ma non è un ottimo dimostrato. Il
    primo lotto reale può spostarla, e spostarla deve costare una modifica in
    pagina, non un rilascio.

    Sui valori di partenza vale la pena essere espliciti, perché sono
    controintuitivi: 200 dpi e ``--psm 6`` battono i default canonici (300 dpi,
    ``--psm 3``), che sulla stessa pagina producevano una data corrotta. E la
    taratura **non è trasferibile fra rasterizzatori**: lo strumento usato oggi
    dalla segreteria rasterizza con poppler, il portale userà PyMuPDF, e a parità
    di impostazioni gli stessi pixel non escono uguali.

    Pattern identico a :class:`TrainingScanIntakeConfig`: una sola riga (pk=1).
    """

    CARTELLA_DEFAULT = r"\\pclogsys\PortaleNovicrom\scansioni\referti"

    attiva = models.BooleanField(
        default=False,
        help_text="Se spenta, il lavoro periodico non guarda la cartella. Il "
                  "caricamento dalla pagina continua a funzionare comunque.",
    )
    cartella = models.CharField(
        max_length=500, blank=True, default=CARTELLA_DEFAULT,
        help_text="Percorso UNC dove la fotocopiatrice deposita le scansioni dei "
                  "referti. Deve essere raggiungibile dall'utente con cui gira "
                  "l'applicazione: una lettera di unità mappata non è visibile a un servizio.",
    )
    sposta_elaborati = models.BooleanField(
        default=True,
        help_text="Sposta i file letti in «elaborati» e quelli non riusciti in «errori», "
                  "così la cartella d'ingresso resta pulita e niente viene riletto due volte.",
    )
    max_file_per_giro = models.PositiveIntegerField(
        default=25,
        help_text="Quanti file al massimo per passaggio: un arretrato grosso non deve "
                  "bloccare il lavoro periodico. A ~2 secondi per referto, 25 file "
                  "sono meno di un minuto.",
    )

    # ── Lettura ────────────────────────────────────────────────────────────────
    ocr_dpi = models.PositiveSmallIntegerField(
        default=200,
        help_text="Risoluzione di rasterizzazione della pagina. 200 è il valore "
                  "misurato come migliore: le scansioni arrivano a ~150 dpi nativi e "
                  "salire non aggiunge dettaglio, amplifica il rumore.",
    )
    ocr_psm = models.PositiveSmallIntegerField(
        default=6,
        help_text="Modalità di segmentazione della pagina di Tesseract. 6 tratta la "
                  "pagina come un blocco uniforme e mantiene appaiate le colonne del "
                  "protocollo sanitario; 11 le distrugge sistematicamente.",
    )
    ocr_lingua = models.CharField(
        max_length=20, default="ita",
        help_text="Pacchetto lingua di Tesseract.",
    )
    ocr_timeout_secondi = models.PositiveSmallIntegerField(
        default=30,
        help_text="Oltre questo tempo il singolo file va in errore e il giro prosegue: "
                  "una pagina patologica non deve fermare tutte le altre.",
    )

    # ── Riconoscimento del dipendente ──────────────────────────────────────────
    # Le soglie sono percentuali intere e non frazioni: si leggono e si scrivono
    # meglio in un form, e tolgono di mezzo i confronti fra decimali.
    soglia_con_data_nascita = models.PositiveSmallIntegerField(
        default=70,
        help_text="Somiglianza minima del nominativo (0-100) quando la data di nascita "
                  "letta coincide con quella in anagrafica. Può essere bassa: a "
                  "confermare non è il nome, è la data.",
    )
    soglia_senza_data_nascita = models.PositiveSmallIntegerField(
        default=92,
        help_text="Somiglianza minima quando la data di nascita non è leggibile. Alta "
                  "di proposito, e comunque valida solo con un unico candidato.",
    )

    conferma_automatica = models.BooleanField(
        default=False,
        help_text="Se accesa, un riconoscimento pulito registra le visite da sé. Anche "
                  "accesa si ferma davanti a data di nascita discordante, candidati "
                  "multipli, dipendente cessato, esame non a catalogo o nominativo "
                  "letto dal riconoscimento di ripiego.",
    )

    ultima_esecuzione = models.DateTimeField(null=True, blank=True)
    ultimo_esito = models.TextField(
        blank=True, default="",
        help_text="Riepilogo dell'ultimo passaggio, per capire dalla pagina se il "
                  "meccanismo sta girando davvero.",
    )

    class Meta:
        verbose_name = "Acquisizione referti sanitari"
        verbose_name_plural = "Acquisizione referti sanitari"

    def __str__(self) -> str:
        return "Acquisizione referti" + ("" if self.attiva else " (spenta)")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RefertoIntakeRiga(models.Model):
    """Una riga per ogni file passato dall'acquisizione: cos'era, cosa se n'è capito.

    Il file viene archiviato **sempre**, prima ancora di provare a leggerlo, e qui
    resta scritto dov'è finito. Su una lettura riuscita serve a confrontare la
    proposta con l'originale; su una fallita è l'unica cosa che permetta di capire
    se la scansione era storta, tagliata, sbiadita o di un altro medico. Senza
    registro resterebbe solo la frase «non sono riuscito a leggere il referto»,
    che non è una diagnosi.

    Le righe in ``DA_RIVEDERE`` **sono** la coda di revisione: non esiste una
    seconda tabella per quelle: lo stato è un campo, non un modello a parte.
    """

    ESITO_OK = "OK"
    ESITO_DA_RIVEDERE = "DA_RIVEDERE"
    ESITO_DUPLICATO = "DUPLICATO"
    ESITO_RIFIUTATO = "RIFIUTATO"
    ESITO_ERRORE = "ERRORE"
    ESITO_SCARTATO = "SCARTATO"

    ESITO_CHOICES = [
        (ESITO_OK, "Registrato"),
        (ESITO_DA_RIVEDERE, "Da rivedere"),
        (ESITO_DUPLICATO, "Già presente"),
        (ESITO_RIFIUTATO, "Non riconosciuto"),
        (ESITO_ERRORE, "Errore di lettura"),
        (ESITO_SCARTATO, "Scartato a mano"),
    ]
    ORIGINE_CHOICES = [
        ("WEB", "Caricamento dalla pagina"),
        ("CARTELLA", "Cartella di acquisizione"),
    ]

    # ── Il file ────────────────────────────────────────────────────────────────
    nome_file = models.CharField(max_length=255, blank=True, default="")
    percorso = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Dove è stato archiviato, relativo allo storage privato cifrato "
                  "dell'anagrafica.",
    )
    dimensione = models.PositiveIntegerField(default=0, help_text="Byte del file.")
    sha256 = models.CharField(
        max_length=64, blank=True, default="", db_index=True,
        help_text="Impronta del contenuto: è così che lo stesso file ricaricato "
                  "viene riconosciuto invece di essere rielaborato.",
    )
    pagina = models.PositiveSmallIntegerField(
        default=1,
        help_text="Quale pagina del PDF, per le scansioni che ne contengono più d'una: "
                  "una pagina con blocco anagrafico è un certificato a sé.",
    )
    origine = models.CharField(max_length=10, choices=ORIGINE_CHOICES, default="WEB")

    esito = models.CharField(
        max_length=15, choices=ESITO_CHOICES, default=ESITO_DA_RIVEDERE, db_index=True
    )
    messaggio = models.TextField(
        blank=True, default="",
        help_text="Perché è finito in questo stato, in parole leggibili da chi revisiona.",
    )

    # ── Cosa si è letto ────────────────────────────────────────────────────────
    # Solo i campi riconosciuti: il testo integrale dell'OCR non viene mai salvato.
    letto_nominativo = models.CharField(max_length=200, blank=True, default="")
    letto_data_nascita = models.DateField(null=True, blank=True)
    letto_data_giudizio = models.DateField(null=True, blank=True)
    letto_esito_testo = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Il giudizio così com'è scritto sul certificato, prima della "
                  "traduzione in codice.",
    )
    letto_mansione = models.CharField(max_length=200, blank=True, default="")
    letto_protocollo = models.JSONField(
        default=list, blank=True,
        help_text="Esami del protocollo sanitario con la periodicità dichiarata: "
                  "[{'esame': ..., 'periodicita': ...}]. Un certificato ne porta più d'uno.",
    )
    date_trovate = models.JSONField(
        default=list, blank=True,
        help_text="Tutte le occorrenze di data trovate nel documento. La data del "
                  "giudizio si decide per consenso fra queste: l'OCR ne corrompe una "
                  "ogni tanto, e le altre la salvano.",
    )
    nominativo_da_ripiego = models.BooleanField(
        default=False,
        help_text="Il nome viene dalla riga di firma invece che dal blocco anagrafico. "
                  "Quella riga è attraversata dalla firma autografa e restituisce nomi "
                  "verosimili ma sbagliati: una riga così non si conferma mai da sé.",
    )

    # ── Chi si è deciso che fosse ──────────────────────────────────────────────
    legacy_anagrafica_id_proposto = models.IntegerField(null=True, blank=True, db_index=True)
    punteggio = models.PositiveSmallIntegerField(
        default=0, help_text="Somiglianza del nominativo col candidato proposto (0-100)."
    )
    data_nascita_conferma = models.BooleanField(
        default=False,
        help_text="La data di nascita letta coincide con quella in anagrafica. È la "
                  "vera garanzia del riconoscimento, molto più della somiglianza del nome.",
    )
    candidati = models.JSONField(
        default=list, blank=True,
        help_text="Gli altri candidati sopra soglia, per chi revisiona: "
                  "[{'legacy_id': ..., 'nominativo': ..., 'punteggio': ...}].",
    )
    divergenze = models.JSONField(
        default=list, blank=True,
        help_text="Scostamenti fra il certificato e il catalogo (tipicamente la "
                  "periodicità dichiarata dal medico). Non bloccano, ma devono "
                  "arrivare sotto gli occhi di qualcuno invece di essere sovrascritti.",
    )

    visite_create = models.PositiveSmallIntegerField(
        default=0,
        help_text="Quante VisitaMedica sono nate da questa riga: un certificato porta "
                  "un intero protocollo, non una visita sola.",
    )
    documento = models.ForeignKey(
        "anagrafica.DocumentoDipendente",
        null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Il referto archiviato nel fascicolo del dipendente, condiviso da "
                  "tutte le visite nate da questo certificato.",
    )

    # ── Traccia ────────────────────────────────────────────────────────────────
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="referti_intake_caricati",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    confermato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="referti_intake_confermati",
    )
    confermato_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["esito", "-created_at"]),
            models.Index(fields=["legacy_anagrafica_id_proposto", "letto_data_giudizio"]),
        ]
        verbose_name = "Referto acquisito"
        verbose_name_plural = "Referti acquisiti"

    def __str__(self) -> str:
        chi = self.letto_nominativo or self.nome_file or "?"
        return f"{chi} — {self.get_esito_display()}"

    @property
    def da_rivedere(self) -> bool:
        return self.esito == self.ESITO_DA_RIVEDERE


class AliasEsameProtocollo(models.Model):
    """Come il medico chiama un esame ↔ quale tipo di visita è per noi.

    È una tabella e non un dizionario nel codice perché è esattamente il punto in
    cui i certificati reali smentiscono le previsioni: ogni medico scrive
    «Visita Medica», «Vis. medica», «Visita medica periodica» a modo suo. Un nome
    nuovo deve costare una riga inserita da chi revisiona, non un rilascio.

    Un esame che non trova corrispondenza **non viene indovinato**: manda la riga
    in revisione. Inventare un tipo di visita significherebbe inventare una scadenza.
    """

    testo = models.CharField(
        max_length=200, unique=True,
        help_text="Il testo come compare sul certificato. Il confronto avviene "
                  "normalizzato (maiuscole, accenti e spazi non contano).",
    )
    tipo = models.ForeignKey(
        "anagrafica.TipoVisitaMedica",
        on_delete=models.CASCADE, related_name="alias_intake",
    )
    attivo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["testo"]
        verbose_name = "Alias esame del protocollo"
        verbose_name_plural = "Alias esami del protocollo"

    def __str__(self) -> str:
        return f"{self.testo} → {self.tipo}"


class AliasEsitoIdoneita(models.Model):
    """Come è scritto il giudizio ↔ quale esito in codice.

    Stessa ragione degli alias degli esami, con una posta più alta: l'esito di
    idoneità ha sette valori possibili e la differenza fra «idoneo con
    prescrizioni» e «idoneo con limitazioni» ha conseguenze concrete sulla
    mansione. Un giudizio che non si riconosce va in revisione con il testo in
    chiaro sotto gli occhi di una persona — non si sceglie il valore più simile.
    """

    testo = models.CharField(
        max_length=200, unique=True,
        help_text="Il giudizio come compare sul certificato, confrontato normalizzato.",
    )
    esito = models.CharField(max_length=20, choices=_esiti_idoneita)
    attivo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["testo"]
        verbose_name = "Alias esito di idoneità"
        verbose_name_plural = "Alias esiti di idoneità"

    def __str__(self) -> str:
        return f"{self.testo} → {self.get_esito_display()}"
