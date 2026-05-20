from django.contrib import admin

from .models import (
    AnagraficaHRPermission,
    DipendenteCambiamentoOrganizzativo,
    Fornitore,
    FornitoreDocumento,
    FornitoreOrdine,
    FornitoreValutazione,
    ImportazioneRetributiva,
    LivelloContrattuale,
    StoricoContratto,
    TipologiaContratto,
    VoceRetributiva,
)


class FornitoreDocumentoInline(admin.TabularInline):
    model = FornitoreDocumento
    extra = 0
    readonly_fields = ("uploaded_by", "uploaded_at")


class FornitoreOrdineInline(admin.TabularInline):
    model = FornitoreOrdine
    extra = 0
    readonly_fields = ("created_by", "created_at")


class FornitoreValutazioneInline(admin.TabularInline):
    model = FornitoreValutazione
    extra = 0
    readonly_fields = ("valutato_da", "created_at", "media")
    fields = ("data", "qualita", "puntualita", "comunicazione", "media", "note", "valutato_da")

    def media(self, obj):
        return obj.media
    media.short_description = "Media"


@admin.register(Fornitore)
class FornitoreAdmin(admin.ModelAdmin):
    list_display = ("ragione_sociale", "categoria", "citta", "telefono", "email", "is_active", "punteggio_medio")
    list_filter = ("categoria", "is_active")
    search_fields = ("ragione_sociale", "piva", "email", "citta")
    inlines = [FornitoreDocumentoInline, FornitoreOrdineInline, FornitoreValutazioneInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(AnagraficaHRPermission)
class AnagraficaHRPermissionAdmin(admin.ModelAdmin):
    list_display = ("accesso",)

    def has_add_permission(self, request):
        return not AnagraficaHRPermission.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class VoceRetributivaInline(admin.TabularInline):
    model = VoceRetributiva
    extra = 0
    readonly_fields = ("tax_code", "pay_item", "categoria", "importo", "is_changed", "importo_precedente", "data_competenza")
    fields = ("tax_code", "pay_item", "categoria", "importo", "is_changed", "importo_precedente")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ImportazioneRetributiva)
class ImportazioneRetributivaAdmin(admin.ModelAdmin):
    list_display = ("data_competenza", "file_nome", "righe_ok", "righe_errore", "importato_da", "data_importazione")
    list_filter = ("data_competenza",)
    readonly_fields = ("data_importazione", "importato_da", "righe_totali", "righe_ok", "righe_errore")
    inlines = []

    def has_add_permission(self, request):
        return False


@admin.register(TipologiaContratto)
class TipologiaContrattoAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "ordine", "is_active")
    list_editable = ("nome", "ordine", "is_active")
    ordering = ("ordine", "codice")


@admin.register(LivelloContrattuale)
class LivelloContrattualeAdmin(admin.ModelAdmin):
    list_display = ("codice", "descrizione", "ordine", "is_active")
    list_editable = ("descrizione", "ordine", "is_active")
    ordering = ("ordine", "codice")


@admin.register(DipendenteCambiamentoOrganizzativo)
class DipendenteCambiamentoOrganizzativoAdmin(admin.ModelAdmin):
    list_display = ("legacy_anagrafica_id", "tipo", "valore_precedente", "valore_nuovo",
                    "data_effetto", "created_by", "created_at")
    list_filter = ("tipo", "data_effetto")
    search_fields = ("legacy_anagrafica_id", "valore_precedente", "valore_nuovo", "note")
    readonly_fields = ("legacy_anagrafica_id", "tipo", "valore_precedente", "valore_nuovo",
                       "data_effetto", "note", "created_at", "created_by")
    date_hierarchy = "data_effetto"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(StoricoContratto)
class StoricoContrattoAdmin(admin.ModelAdmin):
    list_display = ("tax_code", "legacy_anagrafica_id", "data_inizio", "data_fine",
                    "tipologia_contratto", "codice_livello", "qualifica_nome", "created_at")
    list_filter = ("tipologia_contratto", "codice_livello")
    search_fields = ("tax_code", "qualifica_nome", "ccnl")
    readonly_fields = ("created_at", "importato_da")
