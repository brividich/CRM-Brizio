"""Voce «Scadenzario» nella barra in alto (scadenze_globali): oggi la pagina si apriva
solo dai link interni. Solo se manca: non tocca una voce già creata dal Navigation Builder."""

from django.db import migrations

NAV_CODE = "scadenzario"
NAV_ITEM = dict(
    label="Scadenzario",
    section="topbar",
    order=95,
    route_name="scadenze_globali",
    active_patterns="scadenze_globali,scadenzario:gestione,scadenzario:elenco,scadenzario:scadenza_nuova,scadenzario:scadenza_dettaglio,scadenzario:scadenza_modifica,scadenzario:categorie,scadenzario:categoria_modifica,scadenzario:avvisi",
    description="Scadenze di tutti i moduli e scadenze generiche in un'unica pagina.",
    icon="calendar",
    is_visible=True,
    is_enabled=True,
)


def add_nav(apps, schema_editor):
    Nav = apps.get_model("core", "NavigationItem")
    if Nav.objects.filter(route_name="scadenze_globali").exists():
        return
    Nav.objects.get_or_create(code=NAV_CODE, defaults=NAV_ITEM)


def remove_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=NAV_CODE, route_name="scadenze_globali").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("scadenzario", "0001_iniziale"),
        ("core", "0108_nav_home_azioni_rapide"),
    ]

    operations = [
        migrations.RunPython(add_nav, remove_nav),
    ]
