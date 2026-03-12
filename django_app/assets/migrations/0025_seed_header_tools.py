from django.db import migrations


TOOLS = [
    {
        "code": "avvisi",
        "label": "Avvisi / Work order",
        "description": "Icona campana — apre la lista work order e avvisi asset.",
        "is_active": True,
        "admin_only": False,
        "sort_order": 10,
    },
    {
        "code": "widget",
        "label": "Gestione widget dashboard",
        "description": "Icona griglia — apre il pannello per configurare i widget visibili nella dashboard.",
        "is_active": True,
        "admin_only": False,
        "sort_order": 20,
    },
    {
        "code": "sync",
        "label": "Sincronizzazione inventario cloud",
        "description": "Icona nuvola — apre il pannello per importare l'inventario da file Excel.",
        "is_active": True,
        "admin_only": True,
        "sort_order": 30,
    },
]


def seed_tools(apps, schema_editor):
    AssetHeaderTool = apps.get_model("assets", "AssetHeaderTool")
    for data in TOOLS:
        AssetHeaderTool.objects.get_or_create(code=data["code"], defaults={k: v for k, v in data.items() if k != "code"})


def unseed_tools(apps, schema_editor):
    AssetHeaderTool = apps.get_model("assets", "AssetHeaderTool")
    AssetHeaderTool.objects.filter(code__in=[t["code"] for t in TOOLS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0024_assetheadertool"),
    ]

    operations = [
        migrations.RunPython(seed_tools, reverse_code=unseed_tools),
    ]
