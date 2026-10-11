"""E-learning, rilascio 1: sblocco HR dei tentativi esauriti + binding ACL della rotta.

``tentativi_extra`` si somma al massimo configurato in ElearningConfig. Il binding
ACL v2 della nuova rotta è copiato da quello della rotta sorella «assegna» (stesso
schema delle 0135/0142: create-only, idempotente, nessun binding se la sorella è
coperta da un prefisso).
"""
from django.db import migrations, models

ROTTE = {
    "anagrafica:formazione_elearning_sblocca": "anagrafica:formazione_elearning_assign",
}
NOTA = "[ELEARNING_0145] copiato da {}"


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
        ("anagrafica", "0144_sicurezza_operativa_deroga_default"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.AddField(
            model_name="trainingelearningenrollment",
            name="tentativi_extra",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(avanti, indietro),
    ]
