"""Binding ACL v2 delle pagine HR dell'e-learning professionale (prompt 05, rilascio 2).

Copiati dalle rotte sorelle (stesso schema delle 0135/0142/0145: create-only,
idempotente; nessun binding se la sorella è coperta da un prefisso). Le rotte del
discente (heartbeat, video) stanno sotto il prefisso condiviso
``/anagrafica/formazione/corsi-online/`` e si proteggono nella view.
"""
from django.db import migrations

ROTTE = {
    "anagrafica:formazione_slide_video_upload": "anagrafica:formazione_slide_import",
    "anagrafica:elearning_impostazioni_corsi": "anagrafica:formazione_elearning_settings",
    "anagrafica:elearning_regola_corso": "anagrafica:formazione_elearning_settings",
    "anagrafica:elearning_cruscotto": "anagrafica:formazione_elearning_hub",
    "anagrafica:elearning_registro": "anagrafica:formazione_elearning_hub",
}
NOTA = "[ELEARNING_0148] copiato da {}"


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
        ("anagrafica", "0147_elearning_token_e_tipi"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
