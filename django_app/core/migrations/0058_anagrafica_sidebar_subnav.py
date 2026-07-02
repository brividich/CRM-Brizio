from django.db import migrations

SEED = [
    {"code": "anagrafica-sub-dipendenti", "label": "Dipendenti",
     "route_name": "anagrafica:dipendenti_list", "order": 10},
    {"code": "anagrafica-sub-ex-dipendenti", "label": "Ex dipendenti",
     "route_name": "anagrafica:ex_dipendenti_list", "order": 20},
    {"code": "anagrafica-sub-ruoli-operativi", "label": "Ruoli operativi",
     "route_name": "anagrafica:ruoli_operativi_list", "order": 30},
]


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    for row in SEED:
        NavigationItem.objects.get_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "section": "subnav",
                "parent_code": "anagrafica",
                "route_name": row["route_name"],
                "order": row["order"],
                "is_visible": True,
                "is_enabled": True,
            },
        )


def unseed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code__in=[r["code"] for r in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0057_actionitem")]
    operations = [migrations.RunPython(seed, unseed)]
