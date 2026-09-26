from django.contrib import admin
from .models import (
    DispositivoSNMP,
    Fattura,
    ImpostazioniSNMP,
    LetturaContatori,
    LetturaMensileContatori,
    Macchina,
    RigaFattura,
    RilevazioneSNMP,
    SondaSNMP,
    ValoreSNMP,
)


@admin.register(Macchina)
class MacchinaAdmin(admin.ModelAdmin):
    list_display = ("reparto", "matricola", "modello", "contratto", "fornitore", "host", "attiva")
    list_filter = ("fornitore", "attiva", "contratto")
    search_fields = ("reparto", "matricola")


@admin.register(LetturaContatori)
class LetturaAdmin(admin.ModelAdmin):
    list_display = ("macchina", "trimestre", "data", "a4_bn", "a3_bn", "a4_col", "a3_col", "totale", "fonte")
    list_filter = ("trimestre", "fonte")


class RigaInline(admin.TabularInline):
    model = RigaFattura
    extra = 0


@admin.register(Fattura)
class FatturaAdmin(admin.ModelAdmin):
    list_display = ("numero", "trimestre", "data", "fornitore", "periodo_al")
    inlines = [RigaInline]


@admin.register(ImpostazioniSNMP)
class ImpostazioniSNMPAdmin(admin.ModelAdmin):
    list_display = ("community", "port", "timeout", "version")


class SondaInline(admin.TabularInline):
    model = SondaSNMP
    extra = 0


@admin.register(LetturaMensileContatori)
class LetturaMensileAdmin(admin.ModelAdmin):
    list_display = ("macchina", "mese", "rilevata_il", "totale")
    list_filter = ("mese",)
    readonly_fields = ("macchina", "mese", "rilevata_il", "a4_bn", "a3_bn", "a4_col", "a3_col")

    def has_add_permission(self, request):
        return False


@admin.register(DispositivoSNMP)
class DispositivoSNMPAdmin(admin.ModelAdmin):
    list_display = (
        "nome", "categoria", "host", "posizione", "snmp_stato",
        "snmp_ultimo_controllo", "attivo",
    )
    list_filter = ("categoria", "snmp_stato", "attivo")
    search_fields = ("nome", "host", "matricola", "modello", "sys_name")
    inlines = [SondaInline]


class ValoreInline(admin.TabularInline):
    model = ValoreSNMP
    extra = 0
    readonly_fields = ("sonda", "valore_numero", "valore_testo", "stato", "errore")
    can_delete = False


@admin.register(RilevazioneSNMP)
class RilevazioneSNMPAdmin(admin.ModelAdmin):
    list_display = ("dispositivo", "rilevata_il", "stato", "tempo_risposta_ms")
    list_filter = ("stato", "dispositivo__categoria")
    readonly_fields = (
        "dispositivo", "rilevata_il", "stato", "tempo_risposta_ms", "errore",
        "sys_name", "sys_description", "sys_object_id", "sys_uptime_seconds",
    )
    inlines = [ValoreInline]
