from __future__ import annotations

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Notizia,
    NotiziaAllegato,
    NotiziaAudience,
    NotiziaLettura,
    STATO_PUBBLICATA,
    STATO_ARCHIVIATA,
    compute_hash_versione,
)


class NotiziaAllegatoInline(admin.StackedInline):
    model = NotiziaAllegato
    extra = 0
    fields = ("nome_file", "file", "url_esterno", "hash_file", "dimensione_bytes")
    readonly_fields = ("hash_file", "dimensione_bytes")


class NotiziaAudienceInline(admin.TabularInline):
    model = NotiziaAudience
    extra = 1
    fields = ("legacy_role_id",)


@admin.register(Notizia)
class NotiziaAdmin(admin.ModelAdmin):
    list_display = ("titolo", "stato_badge", "versione", "obbligatoria", "pubblicato_il", "created_at")
    list_filter = ("stato", "obbligatoria")
    search_fields = ("titolo", "corpo")
    readonly_fields = ("versione", "hash_versione", "pubblicato_il", "created_at", "updated_at")
    inlines = [NotiziaAllegatoInline, NotiziaAudienceInline]
    actions = ["pubblica_notizia_action", "archivia_notizia_action"]
    fieldsets = (
        (None, {
            "fields": ("titolo", "corpo", "obbligatoria", "creato_da"),
        }),
        ("Stato e versioning", {
            "fields": ("stato", "versione", "hash_versione", "pubblicato_il"),
            "classes": ("collapse",),
        }),
        ("Timestamp", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Stato")
    def stato_badge(self, obj: Notizia) -> str:
        colors = {
            "bozza": "#888",
            "pubblicata": "#16a34a",
            "archiviata": "#dc2626",
        }
        color = colors.get(obj.stato, "#888")
        return format_html(
            '<span style="color:{};font-weight:600">{}</span>',
            color,
            obj.get_stato_display(),
        )

    @admin.action(description="Pubblica le notizie selezionate")
    def pubblica_notizia_action(self, request, queryset):
        count = 0
        for notizia in queryset:
            prima_pub = notizia.stato != STATO_PUBBLICATA
            if not prima_pub:
                notizia.versione += 1
            notizia.hash_versione = compute_hash_versione(notizia)
            notizia.stato = STATO_PUBBLICATA
            notizia.pubblicato_il = timezone.now()
            notizia.save(update_fields=["versione", "hash_versione", "stato", "pubblicato_il"])
            count += 1
        self.message_user(request, f"{count} notizia/e pubblicata/e.")

    @admin.action(description="Archivia le notizie selezionate")
    def archivia_notizia_action(self, request, queryset):
        count = queryset.filter(stato=STATO_PUBBLICATA).update(stato=STATO_ARCHIVIATA)
        self.message_user(request, f"{count} notizia/e archiviata/e.")


@admin.register(NotiziaLettura)
class NotiziaLetturaAdmin(admin.ModelAdmin):
    list_display = ("notizia", "legacy_user_id", "versione_letta", "opened_at", "ack_at")
    list_filter = ("notizia",)
    search_fields = ("legacy_user_id",)
    readonly_fields = ("notizia", "legacy_user_id", "versione_letta", "hash_versione_letta", "opened_at", "ack_at")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
