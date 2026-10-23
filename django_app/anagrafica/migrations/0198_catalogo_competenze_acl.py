"""Binding ACL delle pagine «Catalogo competenze» e «Matrice delle competenze» del Mansionario:
copiato da quello del Mansionario. Nelle view restano i controlli propri (vedere = chi vede il
Mansionario, rinominare e unire = amministrazione anagrafica)."""
from django.db import migrations

ROTTE = {
    "anagrafica:mansionario_catalogo": "anagrafica:mansionario",
    "anagrafica:mansionario_matrice_competenze": "anagrafica:mansionario",
}
NOTA = "[MANSIONARIO_0198] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:dipendenti_list"):
            modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
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
        ("anagrafica", "0197_catalogo_competenze"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
