"""Firma HMAC dei dati mostrati dalla verifica attestato e binding ACL delle rotte HR
nuove della fase 2 (moduli, stato dell'import).

Binding copiati dalle rotte sorelle con lo schema delle 0148/0150 (create-only,
idempotente): se la sorella è coperta solo dal prefisso ``corsi/`` non si crea
nulla, perché lo stesso prefisso copre anche le rotte nuove.
"""
from django.db import migrations, models

ROTTE = {
    "anagrafica:formazione_modulo_save": "anagrafica:formazione_slide_save",
    "anagrafica:formazione_modulo_delete": "anagrafica:formazione_slide_delete",
    "anagrafica:formazione_slide_import_stato": "anagrafica:formazione_slide_import",
}
NOTA = "[ELEARNING_0156] copiato da {}"


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
        ("anagrafica", "0155_elearning_import_background"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.AddField(
            model_name="trainingemployeerecord",
            name="firma_verifica",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.RunPython(avanti, indietro),
    ]
