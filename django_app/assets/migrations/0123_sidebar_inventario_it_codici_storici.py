"""Riallinea la sidebar IT usando i codici persistiti dalle migrazioni storiche."""

from django.db import migrations


VOCI_IT = (
    ("servers", "Server", "django:assets:asset_list?asset_type=SERVER&rows={rows}", "asset_type=SERVER", 30),
    ("workstations", "PC e portatili", "django:assets:asset_list?asset_type=PC&rows={rows}", "asset_type=PC", 40),
    ("virtual_machines", "Macchine virtuali", "django:assets:asset_list?asset_type=VM&rows={rows}", "asset_type=VM", 45),
    ("networking", "Rete", "django:assets:asset_list?asset_type=FIREWALL&rows={rows}", "asset_type=FIREWALL", 50),
    ("printers", "Stampanti", "django:assets:asset_list?asset_type=STAMPANTE&rows={rows}", "asset_type=STAMPANTE", 55),
    ("hardware_devices", "Altri dispositivi", "django:assets:asset_list?asset_type=HW&rows={rows}", "asset_type=HW", 60),
)


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")

    # La sidebar persistita usa "inventario" e "device_list" (migrations
    # 0079 e 0050), mentre i seed runtime piu' recenti usano altri codici.
    inventory = Button.objects.filter(code="inventario").first()
    legacy_dashboard = Button.objects.filter(code="dashboard").first()
    inventory_root = inventory or legacy_dashboard
    if inventory_root is not None:
        Button.objects.filter(pk=inventory_root.pk).update(
            label="Inventario completo", is_visible=True
        )
    if inventory is not None and legacy_dashboard is not None:
        Button.objects.filter(pk=legacy_dashboard.pk).update(is_visible=False)

    inventory_it = Button.objects.filter(code="hardware").first()
    legacy_device_list = Button.objects.filter(code="device_list").first()
    if inventory_it is None:
        inventory_it = legacy_device_list
    if inventory_it is None:
        inventory_it = Button.objects.create(
            code="hardware",
            section="MAIN",
            label="Inventario IT",
            target_url="django:assets:device_list",
            active_match="/assets/dispositivi/",
            is_subitem=False,
            sort_order=20,
            is_visible=True,
        )
    else:
        Button.objects.filter(pk=inventory_it.pk).update(
            section="MAIN",
            label="Inventario IT",
            target_url="django:assets:device_list",
            active_match="/assets/dispositivi/",
            parent=None,
            is_subitem=False,
            sort_order=20,
            is_visible=True,
        )

    if legacy_device_list is not None and legacy_device_list.pk != inventory_it.pk:
        Button.objects.filter(pk=legacy_device_list.pk).update(is_visible=False)

    Button.objects.filter(code="work_machines").update(
        label="Officina", is_visible=True, sort_order=60
    )

    for code, label, target, match, order in VOCI_IT:
        defaults = {
            "section": "MAIN",
            "parent": inventory_it,
            "label": label,
            "target_url": target,
            "active_match": match,
            "is_subitem": True,
            "sort_order": order,
            "is_visible": True,
        }
        row = Button.objects.filter(code=code).first()
        if row is None:
            Button.objects.create(code=code, **defaults)
        else:
            Button.objects.filter(pk=row.pk).update(**defaults)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0122_sidebar_inventario_it"),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
