"""Admin Django per gestione_specifiche.

`stato` è un FSMField protected → readonly in admin (si cambia solo via
transizioni). `EventoSpecifica` è audit immutabile → sola lettura.
"""
from __future__ import annotations

from django.contrib import admin

from .models import (
    AzioneOFI, ClienteCartellaShare, ConfigPresaVisione, Distribuzione, EventoSpecifica,
    MOD133, RigaMOD133, RigaMOD133Documento, Specifica,
)


@admin.register(RigaMOD133Documento)
class RigaMOD133DocumentoAdmin(admin.ModelAdmin):
    """Documenti CN ulteriori impattati da una riga MOD.133 (4.1)."""

    list_display = ("codice_documento", "riga", "rif_paragrafo", "ordine")
    search_fields = ("codice_documento", "rif_paragrafo")
    raw_id_fields = ("riga",)
    list_select_related = ("riga",)


@admin.register(ClienteCartellaShare)
class ClienteCartellaShareAdmin(admin.ModelAdmin):
    list_display = ("cliente", "cartella", "attivo", "note", "updated_at")
    list_filter = ("attivo",)
    search_fields = ("cliente", "cartella")
    list_editable = ("cartella", "attivo")
    ordering = ("cliente",)


class RigaMOD133Inline(admin.TabularInline):
    model = RigaMOD133
    extra = 0
    fields = (
        "ordine", "rif_paragrafo", "argomento", "tag_processo",
        "impatto_documenti", "impatto_operativo", "genera_ofi", "ofi",
    )


class EventoSpecificaInline(admin.TabularInline):
    model = EventoSpecifica
    extra = 0
    can_delete = False
    fields = ("timestamp", "stato_da", "stato_a", "attore", "trigger")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class DistribuzioneInline(admin.TabularInline):
    model = Distribuzione
    extra = 0
    fields = ("canale", "presa_visione_richiesta", "cartacea",
              "n_copie_distribuite", "n_copie_ritirate", "data_distribuzione")


@admin.register(Specifica)
class SpecificaAdmin(admin.ModelAdmin):
    list_display = ("codice", "revisione", "titolo", "tipo", "fonte", "stato",
                    "cliente", "data_verifica", "data_inserimento")
    list_filter = ("tipo", "fonte", "stato")
    search_fields = ("codice", "titolo", "cliente", "tag", "commessa_ref", "famiglia_ref")
    readonly_fields = ("stato", "stato_precedente", "stato_pre_errore", "data_inserimento", "created_at", "updated_at")
    autocomplete_fields = ("revisione_precedente", "master")
    inlines = (EventoSpecificaInline, DistribuzioneInline)
    date_hierarchy = "data_inserimento"
    ordering = ("-data_inserimento",)

    def has_delete_permission(self, request, obj=None):
        # M10: cancellare una Specifica farebbe CASCADE sugli EventoSpecifica -> distrugge l'audit
        # trail immutabile. Gli stati terminali (Annullato/Duplicato) sostituiscono la delete.
        return False


@admin.register(MOD133)
class MOD133Admin(admin.ModelAdmin):
    list_display = ("specifica", "compilatore", "approvatore", "esito",
                    "data_chiusura_compilazione", "data_approvazione")
    list_filter = ("esito",)
    search_fields = ("specifica__codice", "specifica__titolo")
    autocomplete_fields = ("specifica", "compilatore", "approvatore")
    inlines = (RigaMOD133Inline,)


@admin.register(AzioneOFI)
class AzioneOFIAdmin(admin.ModelAdmin):
    list_display = ("ofi", "documento_cn", "tipo_azione", "stato",
                    "modo_approvazione", "approvatore", "data_approvazione")
    list_filter = ("stato", "modo_approvazione")
    search_fields = ("documento_cn", "tipo_azione", "ofi")


@admin.register(Distribuzione)
class DistribuzioneAdmin(admin.ModelAdmin):
    list_display = ("specifica", "canale", "presa_visione_richiesta", "cartacea",
                    "n_copie_distribuite", "n_copie_ritirate", "data_distribuzione")
    list_filter = ("canale", "presa_visione_richiesta", "cartacea")
    search_fields = ("specifica__codice",)
    filter_horizontal = ("destinatari",)


@admin.register(EventoSpecifica)
class EventoSpecificaAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "specifica", "stato_da", "stato_a", "attore", "trigger")
    list_filter = ("trigger", "stato_a")
    search_fields = ("specifica__codice",)
    readonly_fields = ("specifica", "stato_da", "stato_a", "attore", "timestamp", "trigger", "payload")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfigPresaVisione)
class ConfigPresaVisioneAdmin(admin.ModelAdmin):
    list_display = ("tipo_documento", "reparto", "richiesta")
    list_filter = ("tipo_documento", "richiesta")
