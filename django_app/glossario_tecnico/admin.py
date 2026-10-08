from django.contrib import admin

from .models import Termine, Variante


class VarianteInline(admin.TabularInline):
    model = Variante
    extra = 0
    fields = ("testo", "tipo", "lingua", "chiave")
    readonly_fields = ("chiave",)


@admin.register(Termine)
class TermineAdmin(admin.ModelAdmin):
    list_display = ("termine", "categoria", "stato", "fonte", "usa_nel_rag", "updated_at")
    list_filter = ("categoria", "stato", "fonte", "usa_nel_rag")
    search_fields = ("termine", "termine_en", "varianti__testo")
    readonly_fields = ("validato_da", "validato_il", "created_at", "updated_at")
    inlines = [VarianteInline]
