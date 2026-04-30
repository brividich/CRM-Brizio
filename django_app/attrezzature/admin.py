from django.contrib import admin

from .models import (
    Attrezzatura,
    AttrezzaturaAvanzamento,
    AttrezzaturaImportBatch,
    AttrezzaturaImportRow,
    AttrezzaturaNota,
    AttrezzaturaPartNumber,
    AttrezzaturaTask,
)


@admin.register(Attrezzatura)
class AttrezzaturaAdmin(admin.ModelAdmin):
    list_display = ("codice", "part_number", "descrizione", "stato", "disponibilita_stato", "avanzamento_percentuale", "data_consegna_prevista")
    search_fields = ("codice", "part_number", "descrizione", "note_consegna", "note_rocco")
    list_filter = ("stato", "disponibilita_stato", "origine_import")
    date_hierarchy = "created_at"


@admin.register(AttrezzaturaPartNumber)
class AttrezzaturaPartNumberAdmin(admin.ModelAdmin):
    list_display = ("attrezzatura", "part_number", "is_principale", "fonte", "created_at")
    search_fields = ("part_number", "attrezzatura__codice", "attrezzatura__descrizione")
    list_filter = ("is_principale", "fonte")


@admin.register(AttrezzaturaAvanzamento)
class AttrezzaturaAvanzamentoAdmin(admin.ModelAdmin):
    list_display = ("attrezzatura", "stato_precedente", "stato_nuovo", "avanzamento_precedente", "avanzamento_nuovo", "origine", "created_at")
    search_fields = ("attrezzatura__codice", "attrezzatura__part_number", "nota", "origine")
    list_filter = ("origine", "stato_nuovo")


@admin.register(AttrezzaturaTask)
class AttrezzaturaTaskAdmin(admin.ModelAdmin):
    list_display = ("titolo", "tipo", "stato", "priorita", "part_number", "codice_attrezzo", "assegnato_a", "scadenza", "origine")
    search_fields = ("titolo", "descrizione", "part_number", "codice_attrezzo", "external_kickoff_id", "external_kickoff_activity_id")
    list_filter = ("tipo", "stato", "priorita", "origine")


@admin.register(AttrezzaturaNota)
class AttrezzaturaNotaAdmin(admin.ModelAdmin):
    list_display = ("attrezzatura", "task", "origine", "created_by", "created_at")
    search_fields = ("testo", "attrezzatura__codice", "attrezzatura__part_number")
    list_filter = ("origine",)


@admin.register(AttrezzaturaImportBatch)
class AttrezzaturaImportBatchAdmin(admin.ModelAdmin):
    list_display = ("file_name", "status", "uploaded_by", "uploaded_at", "total_rows", "created_count", "updated_count", "warning_count", "error_count")
    search_fields = ("file_name",)
    list_filter = ("status",)


@admin.register(AttrezzaturaImportRow)
class AttrezzaturaImportRowAdmin(admin.ModelAdmin):
    list_display = ("batch", "excel_sheet", "excel_row_number", "azione", "codice_letto", "part_number_letto", "attrezzatura")
    search_fields = ("codice_letto", "part_number_letto", "row_hash")
    list_filter = ("azione", "excel_sheet")
