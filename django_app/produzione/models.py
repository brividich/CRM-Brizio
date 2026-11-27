"""Documenti di produzione degli OP.

Gli OP stanno nella tabella ``ordini_produzione`` (vedi ``core/ordini_produzione.py``),
che non appartiene a nessun modulo: qui un documento cita l'OP col suo titolo, come
fanno Gestione anomalie e il Registro FAI. I FAI restano nel Registro FAI e la scheda
dell'OP li mostra insieme a questi documenti.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class TipoDocumento(models.Model):
    """Tipi di documento di produzione, decisi in Impostazioni."""

    etichetta = models.CharField(max_length=80, unique=True)
    descrizione = models.CharField(max_length=255, blank=True, default="")
    ordine = models.PositiveIntegerField(default=100)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "etichetta"]
        verbose_name = "Tipo di documento di produzione"
        verbose_name_plural = "Tipi di documento di produzione"

    def __str__(self) -> str:
        return self.etichetta


class DocumentoOP(models.Model):
    op = models.CharField(max_length=100, db_index=True, verbose_name="OP")
    tipo = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name="documenti")
    titolo = models.CharField(max_length=200, blank=True, default="", verbose_name="Titolo o numero")
    revisione = models.CharField(max_length=40, blank=True, default="", verbose_name="Rev.")
    data = models.DateField(null=True, blank=True, verbose_name="Data")
    percorso = models.CharField(max_length=500, blank=True, default="", verbose_name="Cartella o file di rete")
    note = models.TextField(blank=True, default="", max_length=2000)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    creato_il = models.DateTimeField(auto_now_add=True)
    modificato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tipo__ordine", "tipo__etichetta", "-data", "-id"]
        verbose_name = "Documento di produzione"
        verbose_name_plural = "Documenti di produzione"

    def __str__(self) -> str:
        return f"{self.tipo} {self.titolo}".strip()


class CartellaReportCMM(models.Model):
    """Cartella di un P/N nella share dei report CMM e quando è stata letta l'ultima volta."""

    pn = models.CharField(max_length=100, db_index=True, verbose_name="P/N")
    percorso = models.CharField(max_length=500, unique=True)
    letta_il = models.DateTimeField(null=True, blank=True)
    errore = models.CharField(max_length=300, blank=True, default="")
    in_lettura_dal = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Cartella report CMM"
        verbose_name_plural = "Cartelle report CMM"

    def __str__(self) -> str:
        return self.percorso


class ReportCMM(models.Model):
    """Un report CMM in PDF della share, letto con il lettore di Gestione anomalie."""

    cartella = models.ForeignKey(CartellaReportCMM, on_delete=models.CASCADE, related_name="report")
    pn = models.CharField(max_length=100, verbose_name="P/N")  # indice: prod_rcmm_pn_prog_cop (pn in testa)
    op = models.CharField(max_length=100, db_index=True, blank=True, default="", verbose_name="OP")
    percorso = models.CharField(max_length=500, unique=True)
    file = models.CharField(max_length=255)
    dimensione = models.BigIntegerField(default=0)
    modificato = models.FloatField(default=0)
    fase = models.CharField(max_length=40, blank=True, default="")
    programma = models.CharField(max_length=200, blank=True, default="", verbose_name="Programma")
    programma_base = models.CharField(max_length=200, blank=True, default="",
                                      verbose_name="Programma senza revisione")
    seriale = models.CharField(max_length=100, blank=True, default="", verbose_name="S/N")
    data = models.DateField(null=True, blank=True)
    pn_report = models.CharField(max_length=100, blank=True, default="", verbose_name="P/N nel report")
    righe = models.PositiveIntegerField(default=0)
    fuori = models.PositiveIntegerField(default=0)
    da_verificare = models.PositiveIntegerField(default=0)
    errore = models.CharField(max_length=300, blank=True, default="")
    letto_il = models.DateTimeField(auto_now=True)
    # Escluso dall'analisi (prova, rilavorazione, doppione): il PDF resta, il report non conta.
    escluso = models.BooleanField(default=False)
    escluso_motivo = models.CharField(max_length=120, blank=True, default="")
    escluso_nota = models.CharField(max_length=300, blank=True, default="")
    escluso_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    escluso_il = models.DateTimeField(null=True, blank=True)
    avvisato = models.BooleanField(default=False, help_text="Avviso dei fuori tolleranza già inviato.")
    # Versione del lettore che ha letto il PDF: i report senza quote letti da un lettore più vecchio si
    # rileggono al giro dopo (es. formato vecchio dei report, riconosciuto dalla versione 2).
    lettore = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["-data", "-modificato", "-id"]
        # Le letture del modulo filtrano per P/N (e programma) o per data: indici di copertura con le colonne che
        # leggono, senza tornare alla tabella (SQL Server; altrove «include» è ignorato).
        indexes = [
            models.Index(fields=["pn", "programma_base"], include=["righe", "escluso", "data", "fuori", "seriale", "op", "letto_il", "escluso_il"], name="prod_rcmm_pn_prog_cop"),
            models.Index(fields=["data"], include=["pn", "righe", "escluso", "fuori"], name="prod_rcmm_data"),
        ]
        verbose_name = "Report CMM"
        verbose_name_plural = "Report CMM"

    def __str__(self) -> str:
        return self.file

    @property
    def da_rileggere(self) -> bool:
        """Report senza quote letto da un lettore più vecchio: il giro lo rilegge."""
        from .report_cmm_indice import LETTORE

        return not self.righe and self.lettore < LETTORE


class MisuraCMM(models.Model):
    """Una riga di misura di un report CMM. ``chiave`` = nome della quota senza spazi, maiuscolo."""

    report = models.ForeignKey(ReportCMM, on_delete=models.CASCADE, related_name="misure")
    indice = models.PositiveIntegerField(default=0)
    pagina = models.PositiveIntegerField(default=0)
    sezione = models.CharField(max_length=200, blank=True, default="")
    nome = models.CharField(max_length=200)
    chiave = models.CharField(max_length=200)  # senza indice: si legge sempre per report (cluster report_id, id)
    tipo = models.CharField(max_length=40, blank=True, default="")
    misurato = models.FloatField()
    nominale = models.FloatField()
    tol_sup = models.FloatField()
    tol_inf = models.FloatField(help_text="Col suo segno: limite inferiore = nominale + tol_inf.")
    fuori = models.BooleanField(default=False)
    fuori_di = models.FloatField(null=True, blank=True)
    da_verificare = models.BooleanField(default=False)

    class Meta:
        ordering = ["report_id", "indice"]
        verbose_name = "Misura CMM"
        verbose_name_plural = "Misure CMM"

    def __str__(self) -> str:
        return self.nome


class NotaQuotaCMM(models.Model):
    """Evento scritto a mano su una quota («cambiato inserto»): linea verticale sul grafico dal report indicato."""

    pn = models.CharField(max_length=100, db_index=True)
    programma_base = models.CharField(max_length=200)
    quota = models.CharField(max_length=230, help_text="chiave|nominale; vuoto = tutte le quote del programma")
    report = models.ForeignKey(ReportCMM, on_delete=models.CASCADE, related_name="note_quote")
    testo = models.CharField(max_length=160)
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["report__data", "id"]
        verbose_name = "Nota su una quota CMM"
        verbose_name_plural = "Note sulle quote CMM"


class AliasQuotaCMM(models.Model):
    """«È la stessa quota di…»: la quota d'origine (anche di un altro programma del P/N) va nella quota di destinazione."""

    pn = models.CharField(max_length=100, db_index=True)
    prog_origine = models.CharField(max_length=200)
    quota_origine = models.CharField(max_length=230)
    prog_destinazione = models.CharField(max_length=200)
    quota_destinazione = models.CharField(max_length=230)
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["pn", "prog_origine", "quota_origine"], name="prod_alias_quota_unico")]
        verbose_name = "Quote CMM unite"
        verbose_name_plural = "Quote CMM unite"


class ImpostazioniQuoteCMM(models.Model):
    """Una sola riga: chi riceve gli avvisi delle quote CMM e quando."""

    avvisa_fuori = models.BooleanField(default=True, verbose_name="Avvisa quando un report nuovo ha quote fuori tolleranza")
    avvisa_deriva = models.BooleanField(default=True, verbose_name="Avvisa quando una quota va in deriva")
    destinatari = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+", verbose_name="Chi riceve gli avvisi")
    finestra = models.PositiveSmallIntegerField(
        default=30, choices=[(30, "Ultimi 30 pezzi"), (50, "Ultimi 50 pezzi"), (100, "Ultimi 100 pezzi")],
        verbose_name="Pezzi su cui si calcolano Cpk e Ppk",
        help_text="La stessa finestra in catalogo, scheda P/N, report, Quote CMM, Analisi quote e PDF di capacità.")

    class Meta:
        verbose_name = "Impostazioni avvisi quote CMM"

    @classmethod
    def attuali(cls) -> "ImpostazioniQuoteCMM":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ArticoloPN(models.Model):
    """Anagrafica del P/N: una riga per articolo, creata da sola dagli OP, dai KICK-OFF e dalle cartelle della share
    Collaudo, completata a mano. In fondo il riepilogo precalcolato (report, OP, Cpk) che tiene veloce il catalogo:
    lo aggiornano il giro dei report CMM e la sincronizzazione (``produzione/articoli.py``)."""

    STATI = [("attivo", "Attivo"), ("fermo", "Fermo"), ("obsoleto", "Obsoleto")]
    ORIGINI = [("op", "OP"), ("kickoff", "KICK-OFF"), ("collaudo", "Cartella Collaudo"), ("manuale", "A mano")]

    pn = models.CharField(max_length=100, unique=True, verbose_name="P/N")
    descrizione = models.CharField(max_length=200, blank=True, default="")
    cliente = models.CharField(max_length=180, blank=True, default="")
    disegno = models.CharField(max_length=80, blank=True, default="")
    revisione = models.CharField(max_length=40, blank=True, default="", verbose_name="Revisione")
    materiale = models.CharField(max_length=80, blank=True, default="")
    famiglia = models.CharField(max_length=80, blank=True, default="")
    stato = models.CharField(max_length=10, choices=STATI, blank=True, default="",
                             help_text="Vuoto = deciso dall'attività (report e OP degli ultimi 12 mesi).")
    note = models.TextField(blank=True, default="", max_length=2000)
    origine = models.CharField(max_length=10, choices=ORIGINI, default="op")
    cartella_collaudo = models.CharField(max_length=500, blank=True, default="")
    creato_il = models.DateTimeField(auto_now_add=True)
    modificato_il = models.DateTimeField(auto_now=True)
    modificato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    # Riepilogo precalcolato
    n_op = models.PositiveIntegerField(default=0)
    op_aperti = models.PositiveIntegerField(default=0)
    n_report = models.PositiveIntegerField(default=0)
    n_report_12m = models.PositiveIntegerField(default=0)
    fuori_30g = models.PositiveIntegerField(default=0, help_text="Report degli ultimi 30 giorni con quote fuori.")
    ultimo_report = models.DateField(null=True, blank=True)
    cpk_peggiore = models.FloatField(null=True, blank=True)
    quote_non_capaci = models.PositiveIntegerField(default=0, help_text="Quote «al limite» o «non capaci» (spc.verdetto) sulla finestra di riferimento.")
    quote_deriva = models.PositiveIntegerField(default=0, help_text="Quote in deriva verso un limite.")
    quote_fuori_ultimo = models.PositiveIntegerField(default=0, help_text="Quote fuori nell'ultimo report di ogni programma.")
    analisi_il = models.DateTimeField(null=True, blank=True, help_text="Quando Cpk, deriva e fuori sono stati calcolati.")
    rischio_max = models.FloatField(null=True, blank=True, help_text="Rischio più alto che il prossimo pezzo esca (0-1).")
    salute = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Salute CMM 0-100 (articoli.salute).")
    andamento = models.CharField(max_length=200, blank=True, default="",
                                 help_text="Report per mese degli ultimi 12 mesi, separati da virgola.")
    riepilogo_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["pn"]
        verbose_name = "Articolo (P/N)"
        verbose_name_plural = "Articoli (P/N)"

    def __str__(self) -> str:
        return self.pn

    @property
    def stato_effettivo(self) -> str:
        """Lo stato scelto a mano, altrimenti dall'attività: attivo con report o OP aperti negli ultimi 12 mesi."""
        if self.stato:
            return self.stato
        if self.n_report_12m or self.op_aperti:
            return "attivo"
        return "fermo" if (self.n_report or self.n_op) else "archivio"


class QuotaCapacita(models.Model):
    """Una quota di un programma di un P/N con la sua capacità e il rischio, ricalcolata con l'analisi del P/N
    (``articoli.analizza``). Serve a Quote CMM e al confronto della stessa caratteristica fra P/N diversi."""

    pn = models.CharField(max_length=100, db_index=True, verbose_name="P/N")
    prog = models.CharField(max_length=200, blank=True, default="", verbose_name="Programma")
    quota_id = models.CharField(max_length=260)
    nome = models.CharField(max_length=200)
    caratteristica = models.CharField(max_length=120, db_index=True,
                                      help_text="Nome senza numerazione, maiuscolo (es. «Ø40 H7»): unisce i P/N.")
    nominale = models.FloatField()
    lsl = models.FloatField(null=True, blank=True)
    usl = models.FloatField(null=True, blank=True)
    n = models.PositiveIntegerField(default=0)
    cpk = models.FloatField(null=True, blank=True)
    ppk = models.FloatField(null=True, blank=True)
    indice = models.FloatField(null=True, blank=True, help_text="Il peggiore fra Cpk e Ppk.")
    cpk_basso = models.FloatField(null=True, blank=True)
    verdetto = models.CharField(max_length=20, blank=True, default="")
    metodo = models.CharField(max_length=12, blank=True, default="")
    rischio = models.FloatField(null=True, blank=True)
    deriva = models.BooleanField(default=False)
    fuori_ultimo = models.BooleanField(default=False)
    famiglia = models.PositiveSmallIntegerField(null=True, blank=True)
    dati = models.TextField(blank=True, default="", help_text="L'analisi completa della quota in JSON (serie, limiti, "
                                                             "segnali, confronto fra OP): la leggono le pagine.")
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Capacità di una quota"
        verbose_name_plural = "Capacità delle quote"
        constraints = [models.UniqueConstraint(fields=["pn", "prog", "quota_id"], name="prod_qcap_unica")]

    def __str__(self) -> str:
        return f"{self.pn} {self.prog} {self.nome}"
