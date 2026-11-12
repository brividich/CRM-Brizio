"""Permessi e menu di «Annuncia una visita» e delle richieste di appuntamento (create-only).

- ``reception.annuncia.view``: permesso nuovo della pagina personale, nella dotazione base di ogni
  ruolo (core/permessi/preset.py, modulo «visite_ospiti»). Lo concede «Sincronizza i permessi delle
  pagine» dopo il deploy. Le decisioni su una richiesta le controlla la view (solo il suo referente).
- ``reception:richieste`` e ``reception:richiesta_azione``: come il resto del pannello, copiati da
  Accessi esterni (schema di reception 0002).
- Voce «Annuncia una visita» nella barra in alto, categoria HR se c'è. get_or_create: non tocca
  le personalizzazioni del NavBuilder.
"""
from django.db import migrations

PERMESSO = "reception.annuncia.view"
NOTA = "[RECEPTION_0004] annuncia una visita"
ROTTE_PERSONALI = ("reception:annuncia", "reception:annuncia_decidi")
ROTTE_PANNELLO = ("reception:richieste", "reception:richiesta_azione")
SORELLA = "fornitori:accessi_esterni"
NOTA_PANNELLO = "[RECEPTION_0004] copiato da " + SORELLA
NAV_CODE = "reception_annuncia"


def avanti(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    NavigationItem = apps.get_model("core", "NavigationItem")
    ModuleCategory = apps.get_model("core", "ModuleCategory")

    Permission.objects.get_or_create(code=PERMESSO, defaults={
        "label": "Visite degli ospiti · annuncia una visita", "module": "reception",
        "description": "Pagina personale: annunciare i propri ospiti e rispondere alle richieste di appuntamento.",
        "is_active": True,
    })
    for rotta in ROTTE_PERSONALI:
        if not Binding.objects.filter(route_name=rotta).exists():
            Binding.objects.create(route_name=rotta, path_pattern="", match_strategy="exact", permission_id=PERMESSO,
                                   source_app="reception", priority=80, is_active=True, note=NOTA)
    modello = Binding.objects.filter(route_name=SORELLA, is_active=True).order_by("-priority", "pk").first()
    if modello is not None:
        for rotta in ROTTE_PANNELLO:
            if not Binding.objects.filter(route_name=rotta).exists():
                Binding.objects.create(route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
                                       permission_id=modello.permission_id, source_app="reception",
                                       priority=modello.priority, is_active=True, note=NOTA_PANNELLO)
    NavigationItem.objects.get_or_create(code=NAV_CODE, defaults={
        "label": "Annuncia una visita", "route_name": "reception:annuncia", "section": "topbar", "icon": "id-card",
        "order": 95, "required_permission_code": PERMESSO, "category": ModuleCategory.objects.filter(key="hr").first(),
        "is_visible": True, "is_enabled": True,
    })


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Binding.objects.filter(note__in=[NOTA, NOTA_PANNELLO]).delete()
    apps.get_model("core", "NavigationItem").objects.filter(code=NAV_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("reception", "0003_richieste_appuntamento"), ("reception", "0002_reception_acl")]
    operations = [migrations.RunPython(avanti, indietro)]
