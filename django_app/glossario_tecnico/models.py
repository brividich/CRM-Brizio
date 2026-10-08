"""Glossario tecnico (metalmeccanica, qualità, SGI): termini con varianti.

Le definizioni sono scritte con parole nostre; delle norme si memorizza solo il
codice. Un termine nasce in «bozza» (seed, import, proposta AI accettata) e
diventa utilizzabile dall'assistente solo quando una persona lo valida.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .chiave import normalizza_chiave


class Termine(models.Model):
    CATEGORIE = [
        ("lavorazione", "Lavorazione"),
        ("quotatura", "Quotatura"),
        ("tolleranza_dimensionale", "Tolleranza dimensionale"),
        ("gdt", "Tolleranze geometriche (GD&T)"),
        ("rugosita", "Rugosità"),
        ("filettatura", "Filettatura"),
        ("trattamento_termico", "Trattamento termico"),
        ("trattamento_superficiale", "Trattamento superficiale"),
        ("materiale", "Materiale"),
        ("controllo_qualita", "Controllo qualità"),
        ("sgi_documentale", "SGI documentale"),
        ("sigla_aziendale", "Sigla aziendale"),
    ]
    BOZZA = "bozza"
    VALIDATO = "validato"
    DEPRECATO = "deprecato"
    STATI = [(BOZZA, "Bozza"), (VALIDATO, "Validato"), (DEPRECATO, "Deprecato")]
    FONTI = [
        ("manuale", "Inserito a mano"),
        ("seed", "Elenco iniziale"),
        ("ai_proposta", "Proposta AI accettata"),
        ("import_csv", "Import CSV"),
    ]

    termine = models.CharField(max_length=150, verbose_name="Termine")
    termine_en = models.CharField(max_length=150, blank=True, default="", verbose_name="Termine inglese")
    categoria = models.CharField(max_length=30, choices=CATEGORIE, db_index=True, verbose_name="Categoria")
    definizione = models.TextField(verbose_name="Definizione")
    simbolo = models.CharField(max_length=20, blank=True, default="", verbose_name="Simbolo")
    esempio_disegno = models.CharField(max_length=200, blank=True, default="", verbose_name="Esempio a disegno")
    norma_rif = models.CharField(max_length=60, blank=True, default="", verbose_name="Norma di riferimento")
    stato = models.CharField(max_length=10, choices=STATI, default=BOZZA, db_index=True, verbose_name="Stato")
    fonte = models.CharField(max_length=20, choices=FONTI, default="manuale", verbose_name="Fonte")
    usa_nel_rag = models.BooleanField(default=True, verbose_name="Usa nell'assistente")
    note_interne = models.TextField(blank=True, default="", verbose_name="Note interne")
    validato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="glossario_termini_validati", verbose_name="Validato da",
    )
    validato_il = models.DateTimeField(null=True, blank=True, verbose_name="Validato il")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["termine"]
        verbose_name = "Termine"
        verbose_name_plural = "Termini"
        constraints = [models.UniqueConstraint(fields=["termine", "categoria"], name="uq_termine_categoria")]

    def __str__(self) -> str:
        return self.termine


class Variante(models.Model):
    TIPI = [
        ("sinonimo", "Sinonimo"),
        ("gergo", "Gergo d'officina"),
        ("abbreviazione", "Abbreviazione / sigla"),
        ("simbolo", "Simbolo"),
        ("traduzione", "Traduzione"),
        ("grafia_errata", "Grafia errata frequente"),
    ]

    termine = models.ForeignKey(Termine, on_delete=models.CASCADE, related_name="varianti")
    testo = models.CharField(max_length=150, verbose_name="Testo")
    tipo = models.CharField(max_length=15, choices=TIPI, verbose_name="Tipo")
    lingua = models.CharField(max_length=2, default="it", verbose_name="Lingua")
    chiave = models.CharField(max_length=150, unique=True, db_index=True, editable=False)

    class Meta:
        ordering = ["tipo", "testo"]
        verbose_name = "Variante"
        verbose_name_plural = "Varianti"

    def __str__(self) -> str:
        return self.testo

    def clean(self) -> None:
        self.chiave = normalizza_chiave(self.testo)
        if not self.chiave:
            raise ValidationError({"testo": "Il testo della variante è vuoto."})
        altra = Variante.objects.filter(chiave=self.chiave).exclude(pk=self.pk).select_related("termine").first()
        if altra is not None:
            raise ValidationError({
                "testo": f"«{self.testo}» è già una variante di «{altra.termine.termine}»: "
                         "una variante può appartenere a un solo termine.",
            })

    def save(self, *args, **kwargs) -> None:
        self.chiave = normalizza_chiave(self.testo)
        super().save(*args, **kwargs)
