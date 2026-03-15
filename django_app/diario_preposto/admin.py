from django.contrib import admin

from .models import DiarioPrepostoImpostazioni, SegnalazioneAllegato, SegnalazionePreposto


class AllegatoInline(admin.TabularInline):
    model = SegnalazioneAllegato
    extra = 0
    readonly_fields = ("uploaded_at",)


@admin.register(SegnalazionePreposto)
class SegnalazionePrepostoAdmin(admin.ModelAdmin):
    list_display = ("titolo", "preposto", "chi_segnala", "data_segnalazione", "created_at")
    list_filter = ("data_segnalazione",)
    search_fields = ("titolo", "descrizione", "preposto", "chi_segnala")
    readonly_fields = ("created_at", "updated_at", "creato_da")
    inlines = [AllegatoInline]


@admin.register(DiarioPrepostoImpostazioni)
class DiarioPrepostoImpostazioniAdmin(admin.ModelAdmin):
    pass
