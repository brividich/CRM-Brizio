from django.contrib import admin

from .models import AnagraficaHRPermission, Fornitore, FornitoreDocumento, FornitoreOrdine, FornitoreValutazione


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
