"""Ruolo CAMM «CAM Manager» (05/11/2026): era nell'elenco dei centri di costo ma
non nel catalogo. Solo dove l'elenco è stato caricato: su un database vuoto non
crea nulla. «Riporta a» resta da indicare: l'utente non l'ha specificato."""
from django.db import migrations

from anagrafica.centri_costo_dati import assicura_cam_manager


def avanti(apps, schema_editor):
    assicura_cam_manager(
        apps.get_model("anagrafica", "RuoloOperativo"),
        apps.get_model("anagrafica", "AmbitoRuolo"),
        apps.get_model("anagrafica", "AreaAziendale"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0216_centri_costo_elenco_acl_menu"),
    ]

    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
