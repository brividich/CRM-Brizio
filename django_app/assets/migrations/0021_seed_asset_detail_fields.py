from django.db import migrations
from django.utils.text import slugify


DEFAULT_DETAIL_FIELDS = [
    ("Corse XYZ", "METRICS", "WORK_MACHINE", "computed:travel_xyz", "TEXT", 10),
    ("Anno macchina", "METRICS", "WORK_MACHINE", "work_machine:year", "AUTO", 20),
    ("Configurazione", "METRICS", "WORK_MACHINE", "computed:machine_configuration", "TEXT", 30),
    ("Salute batteria", "METRICS", "STANDARD", "computed:battery_health", "TEXT", 10),
    ("Carico medio CPU", "METRICS", "STANDARD", "computed:cpu_load", "TEXT", 20),
    ("Spazio libero", "METRICS", "STANDARD", "computed:storage_free", "TEXT", 30),
    ("Produttore", "SPECS", "WORK_MACHINE", "asset:manufacturer", "TEXT", 10),
    ("Modello", "SPECS", "WORK_MACHINE", "asset:model", "TEXT", 20),
    ("Numero seriale", "SPECS", "WORK_MACHINE", "asset:serial_number", "TEXT", 30),
    ("Reparto", "SPECS", "WORK_MACHINE", "asset:reparto", "TEXT", 40),
    ("Corsa X", "SPECS", "WORK_MACHINE", "work_machine:x_mm", "MM", 50),
    ("Corsa Y", "SPECS", "WORK_MACHINE", "work_machine:y_mm", "MM", 60),
    ("Corsa Z", "SPECS", "WORK_MACHINE", "work_machine:z_mm", "MM", 70),
    ("Diametro", "SPECS", "WORK_MACHINE", "work_machine:diameter_mm", "MM", 80),
    ("Mandrino", "SPECS", "WORK_MACHINE", "work_machine:spindle_mm", "MM", 90),
    ("Anno", "SPECS", "WORK_MACHINE", "work_machine:year", "AUTO", 100),
    ("TMC", "SPECS", "WORK_MACHINE", "work_machine:tmc", "AUTO", 110),
    ("TCR", "SPECS", "WORK_MACHINE", "work_machine:tcr_enabled", "BOOL", 120),
    ("Pressione", "SPECS", "WORK_MACHINE", "work_machine:pressure_bar", "BAR", 130),
    ("CNC", "SPECS", "WORK_MACHINE", "work_machine:cnc_controlled", "BOOL", 140),
    ("5 assi", "SPECS", "WORK_MACHINE", "work_machine:five_axes", "BOOL", 150),
    ("Accuracy from", "SPECS", "WORK_MACHINE", "work_machine:accuracy_from", "TEXT", 160),
    ("Prossima manutenzione", "SPECS", "WORK_MACHINE", "work_machine:next_maintenance_date", "DATE", 170),
    ("Soglia reminder", "SPECS", "WORK_MACHINE", "work_machine:maintenance_reminder_days", "AUTO", 180),
    ("Processore", "SPECS", "STANDARD", "it:cpu", "TEXT", 10),
    ("Numero seriale", "SPECS", "STANDARD", "asset:serial_number", "TEXT", 20),
    ("Memoria", "SPECS", "STANDARD", "it:ram", "TEXT", 30),
    ("Sistema operativo", "SPECS", "STANDARD", "it:os", "TEXT", 40),
    ("Archiviazione", "SPECS", "STANDARD", "it:disco", "TEXT", 50),
    ("Grafica", "SPECS", "STANDARD", "extra:graphics", "TEXT", 60),
    ("Schermo", "SPECS", "STANDARD", "extra:display", "TEXT", 70),
    ("Data acquisto", "SPECS", "STANDARD", "computed:purchase_date", "TEXT", 80),
    ("Tag asset", "PROFILE", "ALL", "asset:asset_tag", "TEXT", 10),
    ("Reparto", "PROFILE", "WORK_MACHINE", "asset:reparto", "TEXT", 20),
    ("TCR", "PROFILE", "WORK_MACHINE", "work_machine:tcr_enabled", "BOOL", 30),
    ("CNC", "PROFILE", "WORK_MACHINE", "work_machine:cnc_controlled", "BOOL", 40),
    ("5 assi", "PROFILE", "WORK_MACHINE", "work_machine:five_axes", "BOOL", 50),
    ("Prossima manutenzione", "PROFILE", "WORK_MACHINE", "work_machine:next_maintenance_date", "DATE", 60),
    ("Soglia reminder", "PROFILE", "WORK_MACHINE", "work_machine:maintenance_reminder_days", "AUTO", 70),
    ("Accuracy from", "PROFILE", "WORK_MACHINE", "work_machine:accuracy_from", "TEXT", 80),
    ("Produttore", "PROFILE", "STANDARD", "asset:manufacturer", "TEXT", 20),
    ("Modello", "PROFILE", "STANDARD", "asset:model", "TEXT", 30),
    ("Ultimo sync", "PROFILE", "STANDARD", "computed:sync_text", "TEXT", 40),
    ("Reparto", "ASSIGNMENT", "ALL", "asset:assignment_reparto", "TEXT", 10),
    ("Posizione", "ASSIGNMENT", "ALL", "asset:assignment_location", "TEXT", 20),
    ("Assegnato a", "ASSIGNMENT", "ALL", "asset:assignment_to", "TEXT", 30),
    ("Ultimo aggiornamento", "ASSIGNMENT", "ALL", "asset:updated_at", "DATE", 40),
]


def _make_code(section: str, asset_scope: str, source_ref: str) -> str:
    return slugify(f"{section}-{asset_scope}-{source_ref}")[:80] or slugify(source_ref)[:80] or "asset-detail-field"


def seed_asset_detail_fields(apps, schema_editor):
    AssetDetailField = apps.get_model("assets", "AssetDetailField")
    for label, section, asset_scope, source_ref, value_format, sort_order in DEFAULT_DETAIL_FIELDS:
        AssetDetailField.objects.get_or_create(
            code=_make_code(section, asset_scope, source_ref),
            defaults={
                "label": label,
                "section": section,
                "asset_scope": asset_scope,
                "source_ref": source_ref,
                "value_format": value_format,
                "sort_order": sort_order,
                "show_if_empty": True,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0020_assetdetailfield"),
    ]

    operations = [
        migrations.RunPython(seed_asset_detail_fields, migrations.RunPython.noop),
    ]
