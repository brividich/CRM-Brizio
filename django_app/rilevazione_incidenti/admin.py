from django.contrib import admin

from .models import SicurezzaImpostazioni


@admin.register(SicurezzaImpostazioni)
class SicurezzaImpostazioniAdmin(admin.ModelAdmin):
    fieldsets = (
        ("SharePoint", {"fields": ("sharepoint_site_id", "sharepoint_list_id")}),
        ("Accessi", {"fields": ("acl_preposti", "acl_rspp")}),
    )

    def has_add_permission(self, request):
        return not SicurezzaImpostazioni.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
