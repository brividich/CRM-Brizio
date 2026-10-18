from django.contrib import admin

from .models import ApiClient


@admin.register(ApiClient)
class ApiClientAdmin(admin.ModelAdmin):
    """Solo consultazione e disattivazione: i token si creano con
    ``manage.py dati_api_client`` (il token in chiaro si vede una volta sola)."""

    list_display = ("nome", "attivo", "ambiti", "ultimo_accesso", "creato_il")
    list_filter = ("attivo",)
    search_fields = ("nome", "note")
    readonly_fields = ("token_hash", "ultimo_accesso", "creato_il", "creato_da")
    fields = ("nome", "attivo", "ambiti", "note", "token_hash", "ultimo_accesso", "creato_il", "creato_da")

    def has_add_permission(self, request):
        return False
