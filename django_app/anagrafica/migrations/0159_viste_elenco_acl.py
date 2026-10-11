"""Binding ACL v2 delle pagine «Viste elenco» (prompt 03), copiati dalle Impostazioni anagrafica.

Stesso schema della 0142: create-only e idempotente; con ACL_STRICT_CANONICAL una route senza
binding è negata ai non superuser. Nelle view resta il cancello «amministrazione anagrafica».
"""
from django.db import migrations

ROTTE = {
    "anagrafica:viste_elenco": "anagrafica:impostazioni",
    "anagrafica:vista_elenco_modifica": "anagrafica:impostazioni",
    "anagrafica:vista_elenco_nuova": "anagrafica:impostazioni",
    "anagrafica:vista_elenco_azione": "anagrafica:impostazioni",
    "anagrafica:vista_elenco_anteprima": "anagrafica:impostazioni",
}
NOTA = "[VISTE_ELENCO_0159] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("anagrafica", "0158_viste_elenco_preset"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]
    operations = [migrations.RunPython(avanti, indietro)]
