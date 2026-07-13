from django.contrib import admin
from .models import Macchina, LetturaContatori, Fattura, RigaFattura, ImpostazioniSNMP


@admin.register(Macchina)
class MacchinaAdmin(admin.ModelAdmin):
    list_display = ("reparto", "matricola", "modello", "contratto", "fornitore", "host", "attiva")
    list_filter = ("fornitore", "attiva", "contratto")
    search_fields = ("reparto", "matricola")


@admin.register(LetturaContatori)
class LetturaAdmin(admin.ModelAdmin):
    list_display = ("macchina", "trimestre", "data", "a4_bn", "a3_bn", "a4_col", "a3_col", "totale", "fonte")
    list_filter = ("trimestre", "fonte")


class RigaInline(admin.TabularInline):
    model = RigaFattura
    extra = 0


@admin.register(Fattura)
class FatturaAdmin(admin.ModelAdmin):
    list_display = ("numero", "trimestre", "data", "fornitore", "periodo_al")
    inlines = [RigaInline]


@admin.register(ImpostazioniSNMP)
class ImpostazioniSNMPAdmin(admin.ModelAdmin):
    list_display = ("community", "port", "timeout", "version")
