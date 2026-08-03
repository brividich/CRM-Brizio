from __future__ import annotations

from django.contrib import admin

from .models import ChecklistTaskTemplate, ChiusuraEvento, ChiusuraProposta, ChiusuraVoce


@admin.register(ChecklistTaskTemplate)
class ChecklistTaskTemplateAdmin(admin.ModelAdmin):
    list_display = ("ordine", "descrizione", "responsabile", "reparto", "attivo")
    list_filter = ("attivo",)
    search_fields = ("descrizione", "reparto")


class ChiusuraVoceInline(admin.TabularInline):
    model = ChiusuraVoce
    extra = 0
    fields = ("ordine", "descrizione", "responsabile", "confermato", "confermato_da", "confermato_il")
    readonly_fields = ("confermato_da", "confermato_il")


@admin.register(ChiusuraEvento)
class ChiusuraEventoAdmin(admin.ModelAdmin):
    list_display = ("nome", "data_inizio", "data_fine", "stato", "percentuale_completamento")
    list_filter = ("stato",)
    inlines = [ChiusuraVoceInline]


@admin.register(ChiusuraProposta)
class ChiusuraPropostaAdmin(admin.ModelAdmin):
    list_display = ("descrizione", "evento", "proposto_da", "stato", "proposto_il")
    list_filter = ("stato",)
