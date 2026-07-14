from __future__ import annotations

from django.contrib import admin

from .models import PresaVisioneScheda, ProdottoChimico, SchedaSicurezza


class SchedaSicurezzaInline(admin.TabularInline):
    model = SchedaSicurezza
    extra = 0
    fields = ("versione", "is_corrente", "estrazione_stato", "data_caricamento")
    readonly_fields = ("data_caricamento",)


@admin.register(ProdottoChimico)
class ProdottoChimicoAdmin(admin.ModelAdmin):
    list_display = ("nome", "reparto", "fornitore", "produttore", "attivo", "updated_at")
    list_filter = ("reparto", "attivo", "famiglia")
    search_fields = ("nome", "fornitore", "produttore", "codice_prodotto", "numero_interno")
    filter_horizontal = ("dpi_obbligatori",)
    readonly_fields = ("uuid", "created_at", "updated_at")
    inlines = (SchedaSicurezzaInline,)


@admin.register(SchedaSicurezza)
class SchedaSicurezzaAdmin(admin.ModelAdmin):
    list_display = ("prodotto", "versione", "is_corrente", "estrazione_stato", "data_caricamento")
    list_filter = ("is_corrente", "estrazione_stato")
    search_fields = ("prodotto__nome", "versione")
    readonly_fields = ("data_caricamento", "estratto_grezzo")


@admin.register(PresaVisioneScheda)
class PresaVisioneSchedaAdmin(admin.ModelAdmin):
    list_display = ("scheda", "operatore", "data_presa_visione")
    list_filter = ("data_presa_visione",)
    search_fields = ("scheda__prodotto__nome", "operatore__username")
    readonly_fields = ("data_presa_visione",)
