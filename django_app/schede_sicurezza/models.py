from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .storage import PrivateSchedaSicurezzaStorage, upload_to_scheda_pdf


# ---------------------------------------------------------------------------
# Prodotto chimico
# ---------------------------------------------------------------------------

class ProdottoChimico(models.Model):
    nome = models.CharField(max_length=200, verbose_name="Nome prodotto")
    fornitore = models.CharField(max_length=200, blank=True, default="")
    produttore = models.CharField(max_length=200, blank=True, default="")

    # Campo storico mantenuto temporaneamente per non perdere il dato dei
    # prodotti gia' censiti. Non governa piu' assegnazioni, report o UI: la
    # relazione operativa e' ``mansioni``.
    reparto = models.ForeignKey(
        "anagrafica.Reparto",
        on_delete=models.PROTECT,
        related_name="prodotti_chimici",
        verbose_name="Reparto storico (non operativo)",
        null=True,
        blank=True,
    )
    mansioni = models.ManyToManyField(
        "anagrafica.Mansione",
        blank=True,
        related_name="prodotti_chimici",
        verbose_name="Mansioni di rischio",
        help_text=(
            "Mansioni i cui dipendenti devono consultare e confermare la presa "
            "visione della SDS corrente."
        ),
    )

    # Classificazione interna da censimento (vedi RECON §9), distinta dalla
    # classificazione CLP normativa che vive sulla scheda (versionata).
    famiglia = models.CharField(max_length=100, blank=True, default="")
    sottocategoria = models.CharField(max_length=100, blank=True, default="")

    numero_interno = models.CharField(max_length=50, blank=True, default="", verbose_name="Numero interno")
    codice_prodotto = models.CharField(max_length=100, blank=True, default="", verbose_name="Codice prodotto")
    ubicazione = models.CharField(max_length=200, blank=True, default="")
    quantita_presente = models.CharField(max_length=100, blank=True, default="", verbose_name="Quantità presente")

    # Riferimenti incrociati al censimento Excel/legacy (nessuna FK ad assets.Asset:
    # quel modello copre IT/macchinari, non contenitori chimici — vedi RECON §9).
    tag_id = models.CharField(max_length=100, blank=True, default="")
    asset_id_legacy = models.CharField(max_length=100, blank=True, default="")
    new_asset_id_legacy = models.CharField(max_length=100, blank=True, default="")

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    attivo = models.BooleanField(default=True)

    # Conta le APERTURE della scheda mobile pubblica (QR senza login, vedi
    # views.scheda_mobile): incrementato ad ogni GET, mai decrementato. Non sono
    # visitatori unici — la stessa persona che riapre la pagina conta due volte:
    # non c'e' (per scelta) nessun fingerprint, cookie o IP con cui distinguerli.
    visite_qr = models.PositiveIntegerField(default=0, verbose_name="Visite QR pubblico")

    # Pittogrammi CLP dichiarati sul prodotto in fase di inserimento, quando la
    # SDS non e' (ancora) caricata: la scheda corrente resta la fonte quando
    # esiste e ne porta di suoi. Vedi `pittogrammi_effettivi`.
    pittogrammi = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Pittogrammi di pericolo",
        help_text="Codici GHS dichiarati sul prodotto (la scheda corrente, se presente, ha la precedenza).",
    )

    dpi_obbligatori = models.ManyToManyField(
        "dpi.CategoriaDPI",
        blank=True,
        related_name="prodotti_chimici",
        verbose_name="DPI obbligatori",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Prodotto chimico"
        verbose_name_plural = "Prodotti chimici"

    def __str__(self) -> str:
        return self.nome

    def scheda_corrente(self) -> "SchedaSicurezza | None":
        return self.schede.filter(is_corrente=True).first()

    def pittogrammi_effettivi(self, scheda: "SchedaSicurezza | None" = None) -> list[str]:
        """I codici GHS da mostrare per questo prodotto.

        Precedenza alla scheda corrente (dato normativo, estratto e confermato
        sul PDF); il set dichiarato a mano sul prodotto copre il periodo in cui
        la SDS non e' ancora stata caricata. ``scheda`` si passa quando la si ha
        gia' in mano (prefetch), per non rifare la query.
        """
        if scheda is None:
            scheda = self.scheda_corrente()
        if scheda is not None and scheda.pittogrammi:
            return list(scheda.pittogrammi)
        return list(self.pittogrammi or [])

    def mansioni_label(self) -> str:
        """Etichetta leggibile delle mansioni assegnate (queryset prefetchabile)."""
        nomi = [mansione.nome for mansione in self.mansioni.all()]
        return ", ".join(nomi) if nomi else "Nessuna mansione assegnata"


# ---------------------------------------------------------------------------
# Scheda di sicurezza (versionata)
# ---------------------------------------------------------------------------

SCADENZA_SDS_GIORNI = 1095  # ~36 mesi: soglia oltre la quale una scheda è segnalata "da rivedere"


class EstrazioneStato(models.TextChoices):
    NON_ESEGUITA = "non_eseguita", "Non eseguita"
    OK = "ok", "OK"
    PARZIALE = "parziale", "Parziale"
    FALLITA = "fallita", "Fallita"


class SchedaSicurezza(models.Model):
    prodotto = models.ForeignKey(
        ProdottoChimico,
        on_delete=models.CASCADE,
        related_name="schede",
        verbose_name="Prodotto",
    )
    pdf = models.FileField(
        upload_to=upload_to_scheda_pdf,
        storage=PrivateSchedaSicurezzaStorage(),
        verbose_name="PDF scheda",
    )
    versione = models.CharField(max_length=50, blank=True, default="")
    data_revisione_fornitore = models.DateField(null=True, blank=True)
    data_caricamento = models.DateTimeField(auto_now_add=True)
    caricata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schede_sicurezza_caricate",
    )
    is_corrente = models.BooleanField(default=False, db_index=True)

    # Campi curati: pre-compilati dall'estrazione PyMuPDF, editabili da RSPP/sicurezza.
    pittogrammi = models.JSONField(default=list, blank=True)
    frasi_h = models.JSONField(default=list, blank=True)
    frasi_p = models.JSONField(default=list, blank=True)
    classificazione_clp = models.TextField(blank=True, default="")
    dpi_testo = models.TextField(blank=True, default="", verbose_name="DPI (sezione 8, testo grezzo)")
    primo_soccorso = models.TextField(blank=True, default="", verbose_name="Primo soccorso (sezione 4)")
    incompatibilita = models.TextField(blank=True, default="", verbose_name="Incompatibilità (sezione 10)")
    estratto_grezzo = models.JSONField(default=dict, blank=True, help_text="Mappa sezione -> testo estratto")
    estrazione_stato = models.CharField(
        max_length=15,
        choices=EstrazioneStato.choices,
        default=EstrazioneStato.NON_ESEGUITA,
        db_index=True,
    )

    class Meta:
        ordering = ["-data_caricamento"]
        verbose_name = "Scheda di sicurezza"
        verbose_name_plural = "Schede di sicurezza"
        indexes = [
            models.Index(fields=["prodotto", "is_corrente"], name="ss_scheda_prodotto_corrente"),
        ]

    def __str__(self) -> str:
        return f"{self.prodotto.nome} — v.{self.versione or '?'}"

    def save(self, *args, **kwargs):
        if self.is_corrente:
            SchedaSicurezza.objects.filter(
                prodotto=self.prodotto, is_corrente=True
            ).exclude(pk=self.pk).update(is_corrente=False)
        super().save(*args, **kwargs)

    @property
    def scaduta(self) -> bool:
        """True se la scheda non viene aggiornata da più di SCADENZA_SDS_GIORNI giorni."""
        if not self.data_caricamento:
            return False
        soglia = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI)
        return self.data_caricamento < soglia


# ---------------------------------------------------------------------------
# Presa visione (pattern locale, specchiato da procedure_refresh — vedi RECON §2)
# ---------------------------------------------------------------------------

class PresaVisioneScheda(models.Model):
    scheda = models.ForeignKey(
        SchedaSicurezza,
        on_delete=models.PROTECT,
        related_name="prese_visione",
        verbose_name="Scheda",
    )
    operatore = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prese_visione_schede_sicurezza",
        verbose_name="Operatore",
    )
    data_presa_visione = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-data_presa_visione"]
        verbose_name = "Presa visione scheda"
        verbose_name_plural = "Prese visione schede"
        constraints = [
            models.UniqueConstraint(
                fields=["scheda", "operatore"],
                name="ss_unique_presa_visione_scheda_operatore",
            )
        ]

    def __str__(self) -> str:
        return f"{self.operatore} — {self.scheda} ({self.data_presa_visione:%Y-%m-%d})"


# ---------------------------------------------------------------------------
# Personalizzazione dell'etichetta da contenitore
# ---------------------------------------------------------------------------

def upload_to_logo_etichetta(instance, filename: str) -> str:
    from pathlib import Path

    suffix = Path(filename or "").suffix.lower()[:10]
    return f"schede_sicurezza/etichetta/logo_{uuid.uuid4().hex[:12]}{suffix}"


class ImpostazioniEtichetta(models.Model):
    """Impostazioni uniche (riga pk=1) dell'etichetta stampabile per i contenitori.

    Una sola etichetta per tutti i prodotti: deve essere riconoscibile a colpo
    d'occhio in reparto, quindi niente varianti per prodotto.
    """

    class PosizioneQr(models.TextChoices):
        DESTRA = "destra", "QR a destra"
        SINISTRA = "sinistra", "QR a sinistra"

    class RigaExtra(models.TextChoices):
        NESSUNA = "", "Nessuna"
        NUMERO_INTERNO = "numero_interno", "Numero interno"
        CODICE_PRODOTTO = "codice_prodotto", "Codice prodotto"
        FORNITORE = "fornitore", "Fornitore"
        PRODUTTORE = "produttore", "Produttore"
        UBICAZIONE = "ubicazione", "Ubicazione"

    TESTO_QR_DEFAULT = "Scheda di sicurezza e primo soccorso"

    larghezza_mm = models.PositiveSmallIntegerField(default=100, verbose_name="Larghezza (mm)")
    altezza_mm = models.PositiveSmallIntegerField(default=50, verbose_name="Altezza (mm)")
    posizione_qr = models.CharField(max_length=10, choices=PosizioneQr.choices, default=PosizioneQr.DESTRA,
                                    verbose_name="Posizione QR")
    testo_qr = models.CharField(max_length=80, blank=True, default=TESTO_QR_DEFAULT,
                                verbose_name="Testo sotto il QR")
    mostra_logo = models.BooleanField(default=True, verbose_name="Mostra il logo")
    logo = models.FileField(upload_to=upload_to_logo_etichetta, blank=True, default="",
                            verbose_name="Logo dell'etichetta")
    logo_altezza_mm = models.PositiveSmallIntegerField(default=8, verbose_name="Altezza logo (mm)")
    nome_dimensione_pt = models.PositiveSmallIntegerField(default=11, verbose_name="Dimensione nome (pt)")
    nome_maiuscolo = models.BooleanField(default=True, verbose_name="Nome in maiuscolo")
    riga_extra = models.CharField(max_length=20, choices=RigaExtra.choices, blank=True, default="",
                                  verbose_name="Riga sotto il nome")
    mostra_pittogrammi = models.BooleanField(default=True, verbose_name="Mostra i pittogrammi di pericolo")
    mostra_dpi = models.BooleanField(
        default=True,
        verbose_name="Mostra i DPI obbligatori",
        help_text="Segnali di obbligo blu accanto ai pittogrammi, dai «DPI obbligatori» del prodotto.",
    )
    testo_emergenza = models.CharField(max_length=80, blank=True, default="",
                                       verbose_name="Riga emergenza",
                                       help_text="Es. «Emergenza 112 – Centro Antiveleni 02 66101029». Vuota = non stampata.")
    colore_fascia = models.CharField(max_length=7, blank=True, default="",
                                     verbose_name="Colore fascia emergenza",
                                     help_text="Esadecimale, es. #B91C1C. Vuoto = testo nero senza fascia.")
    mostra_bordo = models.BooleanField(default=False, verbose_name="Bordo di taglio",
                                       help_text="Utile se stampi su foglio e ritagli.")
    aggiornato_il = models.DateTimeField(auto_now=True)
    aggiornato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "Impostazioni etichetta SDS"
        verbose_name_plural = "Impostazioni etichetta SDS"

    def __str__(self) -> str:
        return f"Etichetta SDS {self.larghezza_mm}×{self.altezza_mm} mm"

    @classmethod
    def correnti(cls) -> "ImpostazioniEtichetta":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def valore_riga_extra(self, prodotto: ProdottoChimico) -> str:
        if not self.riga_extra:
            return ""
        return str(getattr(prodotto, self.riga_extra, "") or "")
