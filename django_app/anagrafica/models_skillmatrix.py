"""Skill Matrix MOD.187 — strato "abilitazione macchina I/L/U/O" (bridge).

Modulo *additivo* dentro l'app ``anagrafica``: aggiunge l'unico strato mancante
(abilitazione su ``assets.Asset`` con scala I/L/U/O, continuità operativa,
matrice persone×macchine) **riusando** qualifiche/formazione/dipendenti/reparti.

Convenzioni del progetto rispettate:
- dipendente agganciato via ``legacy_anagrafica_id`` (IntegerField), **nessuna FK**
  al modello dipendente;
- compatibilità SQL Server (mssql-django): nessun indice parziale, nessun
  ``UniqueConstraint`` con ``condition``, nessun campo ``unique`` nullable;
- read-only verso gli altri moduli (espone resolver, non accoppia all'indietro).

Importato in ``anagrafica/models.py`` con ``from .models_skillmatrix import *``
(come ``models_formazione``/``models_rischi``).
"""
from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Scala di abilitazione I/L/U/O (MT CN 06 §8.3) — ordinata I < L < U < O.
# Le etichette sono configurabili via SkillMatrixConfig; l'ordinale è fisso.
# Cella vuota = NON in lista (esclusione voluta), modellata come assenza di
# record con ``in_lista=True``, NON come un livello "0".
# ---------------------------------------------------------------------------
class LivelloSkm(models.TextChoices):
    IN_FORMAZIONE = "I", "In formazione"
    INTERMEDIO = "L", "Intermedio"
    AUTONOMO = "U", "Autonomo"
    ESPERTO = "O", "Formatore/Esperto"


# Ordinale per i confronti di soglia. I=1 < L=2 < U=3 < O=4.
ORDINE_LIVELLO: dict[str, int] = {
    LivelloSkm.IN_FORMAZIONE: 1,
    LivelloSkm.INTERMEDIO: 2,
    LivelloSkm.AUTONOMO: 3,
    LivelloSkm.ESPERTO: 4,
}


def ordinale_livello(livello: str | None) -> int:
    """Ordinale del livello (0 se assente/non valido)."""
    return ORDINE_LIVELLO.get(livello or "", 0)


# ---------------------------------------------------------------------------
# Configurazione singleton
# ---------------------------------------------------------------------------
class SkillMatrixConfig(models.Model):
    """Parametri configurabili della skill matrix (singleton, pk=1)."""

    REGOLA_MIN = "MIN"
    REGOLA_MEDIA = "MEDIA"
    REGOLA_BLOCCANTI = "BLOCCANTI"
    REGOLA_MULTIVOCE_CHOICES = [
        (REGOLA_MIN, "Minimo delle voci (più rigoroso)"),
        (REGOLA_MEDIA, "Media delle voci"),
        (REGOLA_BLOCCANTI, "Minimo sulle sole voci bloccanti"),
    ]

    soglia_operativa = models.CharField(
        max_length=1, choices=LivelloSkm.choices, default=LivelloSkm.AUTONOMO,
        help_text="Livello minimo (≥) per contare come operativo nel pool capacità.",
    )
    regola_multivoce = models.CharField(
        max_length=12, choices=REGOLA_MULTIVOCE_CHOICES, default=REGOLA_MIN,
        help_text="Come calcolare il livello complessivo di una macchina multivoce "
                  "(da confermare in sessione CAR).",
    )
    finestra_continuita_mesi = models.PositiveSmallIntegerField(default=12)
    preavviso_continuita_mesi = models.PositiveSmallIntegerField(default=9)
    periodicita_refresh_mesi = models.PositiveSmallIntegerField(default=6)
    preavviso_refresh_giorni = models.PositiveSmallIntegerField(
        default=60,
        help_text="Giorni prima di prossima_revisione entro cui un reparto è "
                  "«in arrivo» nello scadenzario abilitazioni.",
    )
    soglia_uomo_solo = models.PositiveSmallIntegerField(
        default=2, help_text="Numero minimo di persone U/O per non essere a rischio "
                             "uomo-solo (MT CN 06 §8.2.2).",
    )
    includi_car_come_riserva = models.BooleanField(default=False)

    # Etichette configurabili della scala (default = MT CN 06 §8.3).
    etichetta_i = models.CharField(max_length=120, default="In formazione")
    etichetta_l = models.CharField(max_length=120, default="Intermedio")
    etichetta_u = models.CharField(max_length=120, default="Autonomo")
    etichetta_o = models.CharField(max_length=120, default="Formatore/Esperto")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configurazione Skill Matrix"
        verbose_name_plural = "Configurazione Skill Matrix"

    def __str__(self) -> str:
        return "Configurazione Skill Matrix"

    @classmethod
    def get_instance(cls) -> "SkillMatrixConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def soglia_operativa_ordinale(self) -> int:
        return ordinale_livello(self.soglia_operativa)

    def etichetta(self, livello: str) -> str:
        """Etichetta configurata per un livello (fallback alle choices)."""
        mappa = {
            LivelloSkm.IN_FORMAZIONE: self.etichetta_i,
            LivelloSkm.INTERMEDIO: self.etichetta_l,
            LivelloSkm.AUTONOMO: self.etichetta_u,
            LivelloSkm.ESPERTO: self.etichetta_o,
        }
        return mappa.get(livello) or dict(LivelloSkm.choices).get(livello, livello)


# ---------------------------------------------------------------------------
# Catalogo competenze MOD.187 (backbone import + cache match asset)
# ---------------------------------------------------------------------------
class CompetenzaSkm(models.Model):
    """Una competenza del foglio MOD.187 (macchina | processo | contatore).

    Backbone del catalogo: NON duplica qualifiche/asset, ma li **collega**.
    - tipo=macchina → ``asset`` (assets.Asset) risolto in F2a;
    - tipo=processo → ``tipo_qualifica`` (TipoQualifica) se corrispondente;
    - tipo=contatore → "corsi attivati" (gestito a parte come intero).
    """

    TIPO_MACCHINA = "macchina"
    TIPO_PROCESSO = "processo"
    TIPO_CONTATORE = "contatore"
    TIPO_CHOICES = [
        (TIPO_MACCHINA, "Macchina"),
        (TIPO_PROCESSO, "Processo"),
        (TIPO_CONTATORE, "Contatore"),
    ]

    CONF_ESATTO = "esatto"
    CONF_PARZIALE = "parziale"
    CONF_ASSENTE = "assente"
    CONF_NA = "na"
    CONFIDENZA_CHOICES = [
        (CONF_ESATTO, "Esatto"),
        (CONF_PARZIALE, "Parziale"),
        (CONF_ASSENTE, "Assente"),
        (CONF_NA, "Non applicabile"),
    ]

    competenza_key = models.CharField(max_length=120, unique=True)
    display = models.CharField(max_length=255, blank=True, default="")
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default=TIPO_MACCHINA, db_index=True)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="competenze_skm",
        help_text="Asset risolto (solo tipo=macchina).",
    )
    tipo_qualifica = models.ForeignKey(
        "anagrafica.TipoQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="competenze_skm",
        help_text="Qualifica collegata (solo tipo=processo, se corrispondente).",
    )
    alias_storici = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")

    # Esito del match asset (F2a). Mai usato come baseline finché non confermato.
    match_confidenza = models.CharField(
        max_length=10, choices=CONFIDENZA_CHOICES, default=CONF_NA, blank=True,
    )
    match_strategia = models.CharField(max_length=20, blank=True, default="")
    match_confermato = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tipo", "competenza_key"]
        verbose_name = "Competenza Skill Matrix"
        verbose_name_plural = "Competenze Skill Matrix"

    def __str__(self) -> str:
        return self.display or self.competenza_key


# ---------------------------------------------------------------------------
# Abilitazione macchina (lo strato nuovo)
# ---------------------------------------------------------------------------
class AbilitazioneMacchina(models.Model):
    """Abilitazione I/L/U/O di un dipendente su un asset/macchina."""

    STATO_ATTIVA = "attiva"
    STATO_SOSPESA = "sospesa"
    STATO_CHOICES = [
        (STATO_ATTIVA, "Attiva"),
        (STATO_SOSPESA, "Sospesa"),
    ]

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.PROTECT, related_name="abilitazioni_skm",
    )
    livello = models.CharField(max_length=1, choices=LivelloSkm.choices)
    in_lista = models.BooleanField(
        default=True, help_text="Chi non è in lista non opera su quell'asset.",
    )
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_ATTIVA)
    conteggiabile_nel_carico = models.BooleanField(
        default=True, help_text="False per i CAR: visibili ma fuori dal pool capacità.",
    )
    livello_richiesto = models.CharField(
        max_length=1, choices=LivelloSkm.choices, null=True, blank=True,
        help_text="Livello atteso per la mansione su quell'asset (marker ▲).",
    )
    car_legacy_id = models.IntegerField(null=True, blank=True, db_index=True)
    data_assegnazione = models.DateField(null=True, blank=True)
    prossima_revisione = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset__name", "legacy_anagrafica_id"]
        verbose_name = "Abilitazione macchina"
        verbose_name_plural = "Abilitazioni macchina"
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_anagrafica_id", "asset"],
                name="skm_uniq_abilitazione_persona_asset",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.asset_id} = {self.livello}"

    @property
    def ordinale(self) -> int:
        return ordinale_livello(self.livello)

    def is_operativa(self, soglia_ordinale: int) -> bool:
        """Operativa rispetto a una soglia già risolta (per il resolver, no query)."""
        return (
            self.stato == self.STATO_ATTIVA
            and self.in_lista
            and self.conteggiabile_nel_carico
            and self.ordinale >= soglia_ordinale
        )

    @property
    def is_operational(self) -> bool:
        """Operativa secondo la soglia corrente di SkillMatrixConfig."""
        return self.is_operativa(SkillMatrixConfig.get_instance().soglia_operativa_ordinale)

    @property
    def sotto_livello_richiesto(self) -> bool:
        """True se sotto il livello atteso per la mansione (marker ▲)."""
        if not self.livello_richiesto:
            return False
        return self.ordinale < ordinale_livello(self.livello_richiesto)


# ---------------------------------------------------------------------------
# Macchine "più voci" (catalogo voci per tipo macchina) — popolamento CAR
# ---------------------------------------------------------------------------
class VoceMacchinaCatalogo(models.Model):
    """Voce valutabile di una macchina multivoce (es. set-up, programmazione BM).

    Valutata per *tipo* di macchina, non per singolo asset. Catalogo predisposto
    vuoto: il popolamento è una sessione CAR (non bloccante per il resto).
    """

    codice = models.CharField(max_length=60, unique=True)
    nome = models.CharField(max_length=150)
    descrizione = models.TextField(blank=True, default="")
    asset_type = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Tipo macchina a cui si applica (vuoto = generica).",
    )
    bloccante = models.BooleanField(
        default=False, help_text="Conta per la regola multivoce BLOCCANTI.",
    )
    ordine = models.PositiveSmallIntegerField(default=0)
    attiva = models.BooleanField(default=True)

    class Meta:
        ordering = ["asset_type", "ordine", "codice"]
        verbose_name = "Voce macchina (catalogo)"
        verbose_name_plural = "Voci macchina (catalogo)"

    def __str__(self) -> str:
        return self.nome


class AbilitazioneMacchinaVoce(models.Model):
    """Livello per singola voce di un'abilitazione multivoce."""

    abilitazione = models.ForeignKey(
        AbilitazioneMacchina, on_delete=models.CASCADE, related_name="voci",
    )
    voce = models.ForeignKey(VoceMacchinaCatalogo, on_delete=models.PROTECT, related_name="+")
    livello = models.CharField(max_length=1, choices=LivelloSkm.choices)

    class Meta:
        verbose_name = "Voce abilitazione macchina"
        verbose_name_plural = "Voci abilitazione macchina"
        constraints = [
            models.UniqueConstraint(
                fields=["abilitazione", "voce"], name="skm_uniq_abilitazione_voce",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.abilitazione_id}/{self.voce_id} = {self.livello}"


# ---------------------------------------------------------------------------
# Storico append-only (ricalca DipendenteQualificaStorico)
# ---------------------------------------------------------------------------
class AbilitazioneMacchinaStorico(models.Model):
    """Scatto datato di un'abilitazione (import/refresh/manuale). Append-only."""

    FONTE_IMPORT = "import"
    FONTE_REFRESH = "refresh"
    FONTE_MANUALE = "manuale"
    FONTE_CHOICES = [
        (FONTE_IMPORT, "Import baseline"),
        (FONTE_REFRESH, "Refresh semestrale"),
        (FONTE_MANUALE, "Manuale"),
    ]

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.PROTECT, related_name="abilitazioni_skm_storico",
    )
    livello = models.CharField(max_length=1, choices=LivelloSkm.choices, blank=True, default="")
    data_rilevazione = models.DateField()
    fonte = models.CharField(max_length=10, choices=FONTE_CHOICES, default=FONTE_IMPORT)
    car_legacy_id = models.IntegerField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, default="")
    registrato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_rilevazione", "-id"]
        verbose_name = "Storico abilitazione macchina"
        verbose_name_plural = "Storico abilitazioni macchina"
        indexes = [
            models.Index(
                fields=["legacy_anagrafica_id", "asset", "data_rilevazione"],
                name="skm_idx_storico_persona_asset",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.asset_id} {self.data_rilevazione} = {self.livello}"


# ---------------------------------------------------------------------------
# Continuità operativa (regola finestra mesi da esecuzione reale di produzione)
# ---------------------------------------------------------------------------
class ProcessoCriticoContinuita(models.Model):
    """Catalogo processi soggetti a continuità operativa (Annual Proficiency)."""

    nome = models.CharField(max_length=150, unique=True)
    riferimento_normativo = models.CharField(max_length=200, blank=True, default="")
    finestra_mesi = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Override della finestra di config (vuoto = usa config).",
    )
    preavviso_mesi = models.PositiveSmallIntegerField(null=True, blank=True)
    tipo_qualifica = models.ForeignKey(
        "anagrafica.TipoQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="processi_continuita",
    )
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["nome"]
        verbose_name = "Processo critico (continuità)"
        verbose_name_plural = "Processi critici (continuità)"

    def __str__(self) -> str:
        return self.nome

    def finestra(self, config: "SkillMatrixConfig | None" = None) -> int:
        if self.finestra_mesi:
            return self.finestra_mesi
        return (config or SkillMatrixConfig.get_instance()).finestra_continuita_mesi

    def preavviso(self, config: "SkillMatrixConfig | None" = None) -> int:
        if self.preavviso_mesi:
            return self.preavviso_mesi
        return (config or SkillMatrixConfig.get_instance()).preavviso_continuita_mesi


class ContinuitaOperativa(models.Model):
    """Continuità di un dipendente su un processo critico."""

    STATO_MANTENUTA = "mantenuta"
    STATO_IN_SCADENZA = "in_scadenza"
    STATO_PERSA = "persa"
    STATO_NA = "na"

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    processo = models.ForeignKey(
        ProcessoCriticoContinuita, on_delete=models.CASCADE, related_name="continuita",
    )
    ultima_esecuzione = models.DateField(
        null=True, blank=True,
        help_text="Ultima esecuzione reale di produzione (popolata in F5).",
    )
    abilitazione = models.ForeignKey(
        AbilitazioneMacchina, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="continuita",
        help_text="Abilitazione che viene sospesa se la continuità è persa.",
    )
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["processo__nome", "legacy_anagrafica_id"]
        verbose_name = "Continuità operativa"
        verbose_name_plural = "Continuità operative"
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_anagrafica_id", "processo"],
                name="skm_uniq_continuita_persona_processo",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.processo_id} -> {self.stato()}"

    def stato(self, oggi=None, config: "SkillMatrixConfig | None" = None) -> str:
        """Stato derivato: mantenuta / in_scadenza / persa / na."""
        if self.ultima_esecuzione is None:
            return self.STATO_NA
        oggi = oggi or timezone.localdate()
        config = config or SkillMatrixConfig.get_instance()
        finestra = self.processo.finestra(config)
        preavviso = self.processo.preavviso(config)
        # ~30,44 giorni/mese: sufficiente per la soglia mensile della norma.
        limite = self.ultima_esecuzione + timedelta(days=int(finestra * 30.44))
        soglia_preavviso = self.ultima_esecuzione + timedelta(days=int(preavviso * 30.44))
        if oggi > limite:
            return self.STATO_PERSA
        if oggi >= soglia_preavviso:
            return self.STATO_IN_SCADENZA
        return self.STATO_MANTENUTA


# ---------------------------------------------------------------------------
# Refresh semestrale (campagna CAR)
# ---------------------------------------------------------------------------
class CampagnaRefresh(models.Model):
    """Tornata di rivalutazione semestrale. Merito = SOLO CAR sul proprio reparto."""

    STATO_APERTA = "aperta"
    STATO_CHIUSA = "chiusa"
    STATO_CHOICES = [
        (STATO_APERTA, "Aperta"),
        (STATO_CHIUSA, "Chiusa"),
    ]

    periodo_inizio = models.DateField()
    periodo_fine = models.DateField(null=True, blank=True)
    scadenza = models.DateField(null=True, blank=True)
    reparto = models.CharField(max_length=120, blank=True, default="")
    area = models.CharField(max_length=120, blank=True, default="")
    avviatore_ruolo = models.CharField(
        max_length=120, blank=True, default="",
        help_text="Ruolo che innesca la tornata (solo trigger, NON approvatore).",
    )
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_APERTA)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-periodo_inizio", "-id"]
        verbose_name = "Campagna refresh"
        verbose_name_plural = "Campagne refresh"

    def __str__(self) -> str:
        return f"Refresh {self.periodo_inizio} ({self.reparto or self.area or 'tutti'})"


# ---------------------------------------------------------------------------
# Contatore "corsi attivati" (intero per dipendente, NON un livello)
# ---------------------------------------------------------------------------
class SkmCorsiAttivati(models.Model):
    """Contatore "corsi attivati" del MOD.187 (intero per dipendente)."""

    legacy_anagrafica_id = models.IntegerField(unique=True, db_index=True)
    numero = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Corsi attivati (contatore)"
        verbose_name_plural = "Corsi attivati (contatore)"

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.numero}"
