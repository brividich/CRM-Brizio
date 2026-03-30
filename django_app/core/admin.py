from django import forms
from django.contrib import admin

from core.models import (
    PERMISSION_CODE_CANONICAL_RE,
    PERMISSION_CODE_CONVENTION_HINT,
    PermissionDefinition,
    RolePermissionGrant,
    RoutePermissionBinding,
    SiteConfig,
    UserPermissionGrant,
    UserUiPreference,
)


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


class PermissionDefinitionAdminForm(forms.ModelForm):
    class Meta:
        model = PermissionDefinition
        fields = "__all__"

    def clean_code(self):
        code = str(self.cleaned_data.get("code") or "").strip().lower()
        if not PERMISSION_CODE_CANONICAL_RE.match(code):
            raise forms.ValidationError(PERMISSION_CODE_CONVENTION_HINT)
        return code


@admin.register(PermissionDefinition)
class PermissionDefinitionAdmin(admin.ModelAdmin):
    form = PermissionDefinitionAdminForm
    list_display = ("code", "label", "module", "is_active", "updated_at")
    list_filter = ("module", "is_active")
    search_fields = ("code", "label", "description")
    ordering = ("module", "code")
    fieldsets = (
        (
            "Permission Code",
            {
                "fields": ("code", "label", "module", "description", "is_active"),
                "description": PERMISSION_CODE_CONVENTION_HINT,
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(RolePermissionGrant)
class RolePermissionGrantAdmin(admin.ModelAdmin):
    list_display = ("legacy_role_id", "permission", "enabled", "updated_at")
    list_filter = ("enabled", "legacy_role_id")
    search_fields = ("permission__code", "permission__label", "note")
    ordering = ("legacy_role_id", "permission__code")
    autocomplete_fields = ("permission",)


@admin.register(UserPermissionGrant)
class UserPermissionGrantAdmin(admin.ModelAdmin):
    list_display = ("legacy_user_id", "permission", "enabled", "updated_at")
    list_filter = ("enabled",)
    search_fields = ("legacy_user_id", "permission__code", "permission__label", "note")
    ordering = ("legacy_user_id", "permission__code")
    autocomplete_fields = ("permission",)


@admin.register(RoutePermissionBinding)
class RoutePermissionBindingAdmin(admin.ModelAdmin):
    list_display = ("route_name", "path_pattern", "match_strategy", "permission", "priority", "is_active")
    list_filter = ("match_strategy", "is_active", "source_app")
    search_fields = ("route_name", "path_pattern", "permission__code", "permission__label", "note")
    ordering = ("priority", "route_name", "path_pattern")
    autocomplete_fields = ("permission",)
