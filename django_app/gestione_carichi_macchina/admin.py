from django.contrib import admin

from .models import (
    CicloStandard,
    Commessa,
    FamigliaAlias,
    FamigliaPezzo,
    Macchina,
    MacchinaAlias,
    MacchinaFamigliaAffinita,
    Operazione,
    Pianificazione,
)


@admin.register(Macchina)
class MacchinaAdmin(admin.ModelAdmin):
    list_display = ("codice", "descrizione", "categoria", "attacco", "stato_pianificazione", "ha_secondo_turno", "ha_turno_notte", "attivo")
    list_editable = ("ha_secondo_turno", "ha_turno_notte")
    list_filter = ("categoria", "attacco", "stato_pianificazione", "attivo", "ha_turno_notte", "ha_secondo_turno")
    search_fields = ("asset__asset_tag", "asset__name")
    raw_id_fields = ("asset",)


@admin.register(MacchinaAlias)
class MacchinaAliasAdmin(admin.ModelAdmin):
    list_display = ("codice_foglio", "macchina", "fonte", "da_confermare")
    list_filter = ("fonte", "da_confermare")
    search_fields = ("codice_foglio",)
    raw_id_fields = ("macchina",)


class FamigliaAliasInline(admin.TabularInline):
    model = FamigliaAlias
    extra = 1


@admin.register(FamigliaPezzo)
class FamigliaPezzoAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome", "alias__alias")
    inlines = [FamigliaAliasInline]


@admin.register(MacchinaFamigliaAffinita)
class MacchinaFamigliaAffinitaAdmin(admin.ModelAdmin):
    list_display = ("macchina", "famiglia", "occorrenze", "ore_medie", "pool_equivalenza", "da_confermare")
    list_filter = ("da_confermare",)
    search_fields = ("macchina__asset__asset_tag", "famiglia__nome", "pool_equivalenza")
    raw_id_fields = ("macchina", "famiglia")


@admin.register(Commessa)
class CommessaAdmin(admin.ModelAdmin):
    list_display = ("numero", "cliente", "pezzo", "quantita", "data_consegna", "priorita", "stato")
    list_filter = ("stato", "priorita")
    search_fields = ("numero", "cliente", "pezzo")


class OperazioneInline(admin.TabularInline):
    model = Operazione
    extra = 1
    raw_id_fields = ("macchina_preferita",)


@admin.register(CicloStandard)
class CicloStandardAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "famiglia", "attivo")
    list_filter = ("attivo",)
    search_fields = ("codice", "nome")
    inlines = [OperazioneInline]


@admin.register(Pianificazione)
class PianificazioneAdmin(admin.ModelAdmin):
    list_display = ("macchina", "data", "turno", "famiglia", "qta", "ore", "stato", "fase", "fonte")
    list_filter = ("turno", "stato", "fase", "fonte")
    search_fields = ("macchina__asset__asset_tag", "testo_originale")
    raw_id_fields = ("macchina", "commessa", "operazione", "famiglia")
    date_hierarchy = "data"
