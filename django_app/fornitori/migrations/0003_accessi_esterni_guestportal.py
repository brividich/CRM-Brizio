"""Accessi esterni (GuestPortal): permesso della pagina e link «Accessi azienda» con SSO.

- ``fornitori:accessi_esterni`` mostra dati personali dei visitatori: si lega allo
  stesso permesso del portale esterno (``legacy.portale_esterno.portale_esterno``),
  assegnabile ai ruoli da Amministrazione → Accessi.
- ``fornitori:guestportal_apri`` è tra le rotte condivise (core/middleware.py):
  nessun binding, come il vecchio link diretto.
- La voce di menu ``accessi`` passa dal link diretto al login del GuestPortal alla
  rotta HUB che apre il pannello con l'accesso automatico. Si tocca solo se punta
  ancora all'indirizzo originale (personalizzazioni del NavBuilder preservate).
"""
from django.db import migrations

PERMESSO = "legacy.portale_esterno.portale_esterno"
NOTA = "[ACCESSI_ESTERNI_0003] pagina accessi esterni GuestPortal"
URL_VECCHIO = "http://10.0.0.8/guestportal/public/admin/index.php"
URL_NUOVO = "/fornitori/guestportal/apri/"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")
    NavigationItem = apps.get_model("core", "NavigationItem")

    if PermissionDefinition.objects.filter(code=PERMESSO).exists() and not Binding.objects.filter(
        route_name="fornitori:accessi_esterni"
    ).exists():
        Binding.objects.create(
            route_name="fornitori:accessi_esterni", path_pattern="", match_strategy="exact",
            permission_id=PERMESSO, source_app="fornitori", priority=80, is_active=True, note=NOTA,
        )

    NavigationItem.objects.filter(code="accessi", url_path=URL_VECCHIO).update(url_path=URL_NUOVO)


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    NavigationItem = apps.get_model("core", "NavigationItem")
    Binding.objects.filter(route_name="fornitori:accessi_esterni", note=NOTA).delete()
    NavigationItem.objects.filter(code="accessi", url_path=URL_NUOVO).update(url_path=URL_VECCHIO)


class Migration(migrations.Migration):

    dependencies = [
        ("fornitori", "0002_hide_migrated_anagrafica_supplier_buttons"),
        ("core", "0108_nav_home_azioni_rapide"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
