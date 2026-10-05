"""Organizza la navigazione Assets per inventario IT e Officina."""

from django.db import migrations


VOCI = (
    ("servers", "Server", "django:assets:asset_list?asset_type=SERVER&rows={rows}", "asset_type=SERVER", 30),
    ("workstations", "PC e portatili", "django:assets:asset_list?asset_type=PC&rows={rows}", "asset_type=PC", 40),
    ("virtual_machines", "Macchine virtuali", "django:assets:asset_list?asset_type=VM&rows={rows}", "asset_type=VM", 45),
    ("networking", "Rete", "django:assets:asset_list?asset_type=FIREWALL&rows={rows}", "asset_type=FIREWALL", 50),
    ("printers", "Stampanti", "django:assets:asset_list?asset_type=STAMPANTE&rows={rows}", "asset_type=STAMPANTE", 55),
    ("hardware_devices", "Altri dispositivi", "django:assets:asset_list?asset_type=HW&rows={rows}", "asset_type=HW", 60),
)


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    hardware = Button.objects.filter(code="hardware").first()
    if hardware is None:
        return

    Button.objects.filter(code="dashboard").update(
        label="Inventario completo", sort_order=10, is_visible=True
    )
    Button.objects.filter(pk=hardware.pk).update(
        label="Inventario IT",
        target_url="django:assets:device_list",
        active_match="/assets/dispositivi/",
        is_subitem=False,
        parent=None,
        sort_order=20,
        is_visible=True,
    )
    Button.objects.filter(code="work_machines").update(
        label="Officina", sort_order=60, is_visible=True
    )

    for code, label, target, match, order in VOCI:
        defaults = {
            "section": hardware.section,
            "parent": hardware,
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
        ("assets", "0121_asset_immagine"),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
