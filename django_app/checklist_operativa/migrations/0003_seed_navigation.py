"""Data migration: voce topbar "Checklist Operativa".

Punta alla pagina Gestione (accessibile a chiunque sia loggato: ogni
responsabile vede solo i propri task). Nessun required_permission_code:
Configurazione e Riepilogo restano raggiungibili dai link interni alla
pagina per chi ha il permesso ``checklist_operativa.configurazione.manage``.
"""
from django.db import migrations

NAV = dict(
    code="checklist_operativa",
    label="Checklist Operativa",
    route_name="checklist_operativa:gestione",
    section="topbar",
    icon="check-square",
    order=90,
)


def forwards(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    # get_or_create sul code (mai update_or_create: non sovrascrive personalizzazioni NavBuilder)
    NavigationItem.objects.get_or_create(
        code=NAV["code"],
        defaults={
            "label": NAV["label"],
            "route_name": NAV["route_name"],
            "section": NAV["section"],
            "icon": NAV["icon"],
            "order": NAV["order"],
        },
    )
    # Campo "di codice" aggiornabile anche su record esistenti.
    NavigationItem.objects.filter(code=NAV["code"]).update(route_name=NAV["route_name"])


def backwards(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="checklist_operativa").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("checklist_operativa", "0002_seed_template_da_excel"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
