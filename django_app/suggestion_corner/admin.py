"""Admin Django per suggestion_corner.

`stato` è FSMField protected → readonly (si cambia solo via transizioni, sessione 2).
Lo storico è audit immutabile → sola lettura inline.
"""
from __future__ import annotations

from django.contrib import admin

from .models import (
    SuggestionCorner, SuggestionCornerAllegato, SuggestionCornerConfig,
    SuggestionCornerProcessoMapping, SuggestionCornerStorico,
)


class SuggestionCornerAllegatoInline(admin.TabularInline):
    model = SuggestionCornerAllegato
    extra = 0
    fields = ("file", "link_esterno", "caricato_da", "caricato_il")
    readonly_fields = ("caricato_il",)


class SuggestionCornerStoricoInline(admin.TabularInline):
    model = SuggestionCornerStorico
    extra = 0
    can_delete = False
    fields = ("timestamp", "stato_precedente", "stato_nuovo", "campo_modificato", "autore")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SuggestionCorner)
class SuggestionCornerAdmin(admin.ModelAdmin):
    list_display = ("id", "data_segnalazione", "reparto_provenienza", "stato", "stato_sms", "da_portale")
    list_filter = ("stato", "stato_sms", "da_portale", "reparto_provenienza")
    search_fields = ("opportunity", "processo_libero", "legacy_sharepoint_id")
    readonly_fields = ("stato", "created_at", "updated_at", "data_segnalazione")
    inlines = [SuggestionCornerAllegatoInline, SuggestionCornerStoricoInline]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields


@admin.register(SuggestionCornerConfig)
class SuggestionCornerConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "giorni_sollecito_1", "giorni_escalation_oltre_scadenza", "sms_team_group_name")

    def has_add_permission(self, request):
        return not SuggestionCornerConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SuggestionCornerProcessoMapping)
class SuggestionCornerProcessoMappingAdmin(admin.ModelAdmin):
    list_display = ("valore_libero", "processo", "is_default")
    list_editable = ("processo", "is_default")
    search_fields = ("valore_libero",)
