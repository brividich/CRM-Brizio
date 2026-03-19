from django.contrib import admin

from core.models import SiteConfig, UserUiPreference


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("chiave", "descrizione", "updated_at")
    search_fields = ("chiave", "descrizione", "valore")
    ordering = ("chiave",)
    readonly_fields = ("updated_at",)


@admin.register(UserUiPreference)
class UserUiPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "nav_mode", "font_scale", "sidebar_collapsed")
    list_filter = ("nav_mode", "font_scale", "sidebar_collapsed")
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user",)
