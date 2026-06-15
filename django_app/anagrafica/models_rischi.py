"""Modelli sicurezza — Fattori di Rischio, Categorie Corso, Esposizioni.

Hub safety trasversale che lega formazione, qualifiche, DPI e sorveglianza
sanitaria. Vedi `docs/anagrafica/formazione/PROPOSTA_FATTORI_RISCHIO.md`.

File separato importato da `anagrafica/models.py` tramite
`from .models_rischi import *`.

PATCH-RISK-01: solo modelli + migrazione + admin minimo. Nessuna UI, nessuna
derivazione scadenze (arriva in PATCH-RISK-03). Decisioni R1-R5 validate il
2026-05-23.
"""
from __future__ import annotations

from django.db import models


__all__ = [
    "FattoreRischio",
    "CategoriaCorso",
    "EsposizioneRischio",
]


# ─────────────────────────────────────────────────────────────
# FATTORE DI RISCHIO
# ─────────────────────────────────────────────────────────────

class FattoreRischio(models.Model):
    """Fattore di rischio lavorativo (D.Lgs. 81/08).

    Hub safety trasversale: definisce la periodicità di rinnovo formazione e
    sorveglianza sanitaria, e (in patch successiva) si legherà a qualifiche,
    DPI e tipi visita medica via M2M.
    """

    CAT_CHIMICO        = "CHIMICO"
    CAT_FISICO         = "FISICO"
    CAT_BIOLOGICO      = "BIOLOGICO"
    CAT_ERGONOMICO     = "ERGONOMICO"
    CAT_INFORTUNISTICO = "INFORTUNISTICO"
    CAT_ALTRO          = "ALTRO"

    CATEGORIA_CHOICES = [
        (CAT_CHIMICO,        "Chimico"),
        (CAT_FISICO,         "Fisico"),
        (CAT_BIOLOGICO,      "Biologico"),
        (CAT_ERGONOMICO,     "Ergonomico / MMC"),
        (CAT_INFORTUNISTICO, "Infortunistico"),
        (CAT_ALTRO,          "Altro"),
    ]

    codice      = models.CharField(max_length=20, unique=True)
    nome        = models.CharField(max_length=200)
    categoria   = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default=CAT_ALTRO)
    descrizione = models.TextField(blank=True)

    # Periodicità di rinnovo della formazione legata al fattore (0 = una tantum).
    # Usata per derivare TrainingCourse.validita_mesi quando il corso non ha override.
    periodicita_formazione_mesi = models.PositiveSmallIntegerField(
        default=0,
        help_text="Frequenza rinnovo formazione in mesi. 0 = una tantum.",
    )
    # Periodicità sorveglianza sanitaria (0 = non prevista). Patch successiva.
    periodicita_sorveglianza_mesi = models.PositiveSmallIntegerField(
        default=0,
        help_text="Frequenza visita medica in mesi. 0 = non prevista.",
    )

    richiede_formazione    = models.BooleanField(default=True)
    richiede_visita_medica = models.BooleanField(default=False)
    richiede_dpi           = models.BooleanField(default=False)

    # PATCH-RISK-03: i requisiti concreti generati dal fattore. Una mansione
    # esposta a questo fattore (via EsposizioneRischio) eredita queste visite
    # e categorie DPI; i corsi derivano dalle CategoriaCorso collegate
    # (reverse ``categorie_corso``). Risolto in services/mansionario.py.
    tipi_visita = models.ManyToManyField(
        "anagrafica.TipoVisitaMedica", blank=True, related_name="fattori_rischio",
        help_text="Visite mediche generate da questo fattore di rischio.",
    )
    categorie_dpi = models.ManyToManyField(
        "dpi.CategoriaDPI", blank=True, related_name="fattori_rischio",
        help_text="Categorie DPI generate da questo fattore di rischio.",
    )

    is_active  = models.BooleanField(default=True)
    note       = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria", "nome"]
        verbose_name = "Fattore di rischio"
        verbose_name_plural = "Fattori di rischio"
        indexes = [models.Index(fields=["categoria", "is_active"])]

    def __str__(self) -> str:
        return f"[{self.codice}] {self.nome}"


# ─────────────────────────────────────────────────────────────
# CATEGORIA CORSO
# ─────────────────────────────────────────────────────────────

class CategoriaCorso(models.Model):
    """Categoria formativa: raggruppa corsi e li lega a uno o più fattori di rischio.

    Affianca (non sostituisce) `TrainingPlan.categoria` (CharField). Convivono:
    il piano resta classificato in modo grossolano (OBBLIGATORIA/CONSIGLIATA/
    FACOLTATIVA), la categoria del corso è la chiave di derivazione scadenze.
    """

    codice          = models.CharField(max_length=20, unique=True)
    nome            = models.CharField(max_length=200)
    descrizione     = models.TextField(blank=True)
    fattori_rischio = models.ManyToManyField(
        FattoreRischio, blank=True, related_name="categorie_corso",
    )
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Categoria corso"
        verbose_name_plural = "Categorie corso"

    def __str__(self) -> str:
        return f"[{self.codice}] {self.nome}"


# ─────────────────────────────────────────────────────────────
# ESPOSIZIONE MANSIONE / AREA → FATTORE DI RISCHIO
# ─────────────────────────────────────────────────────────────

class EsposizioneRischio(models.Model):
    """Una Mansione e/o un'AreaAziendale è esposta a un fattore di rischio.

    Si integra con `TrainingRequirementRule` (che già targetta mansione/area/ruolo):
    in PATCH-RISK-03 la regola di obbligatorietà sarà *generata* dalle esposizioni
    invece di essere inserita a mano.
    """

    fattore  = models.ForeignKey(
        FattoreRischio, on_delete=models.CASCADE, related_name="esposizioni",
    )
    mansione = models.ForeignKey(
        "anagrafica.Mansione", null=True, blank=True,
        on_delete=models.CASCADE, related_name="esposizioni_rischio",
    )
    area = models.ForeignKey(
        "anagrafica.AreaAziendale", null=True, blank=True,
        on_delete=models.CASCADE, related_name="esposizioni_rischio",
    )
    note      = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Esposizione a rischio"
        verbose_name_plural = "Esposizioni a rischio"
        indexes = [
            models.Index(fields=["fattore", "is_active"]),
            models.Index(fields=["mansione", "is_active"]),
            models.Index(fields=["area", "is_active"]),
        ]

    def __str__(self) -> str:
        target = self.mansione or self.area or "—"
        return f"{target} → {self.fattore.codice}"
