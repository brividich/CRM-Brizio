"""Binding ACL delle route «Attrezzature del processo» (MOD.128), copiati da
«Aggiungi requisito» (stesso permesso di gestione MOD.128). Il bootstrap MPQ li
crea comunque all'avvio; qui servono per averli subito dopo il migrate."""
from django.db import migrations

ROTTE = {
    "anagrafica:mpq_attrezzatura_add": "anagrafica:mpq_requisito_add",
    "anagrafica:mpq_attrezzatura_remove": "anagrafica:mpq_requisito_add",
}
NOTA = "[MPQ_0186] copiato da {}"


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
        ("anagrafica", "0185_struttura_mansionario_acl"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
