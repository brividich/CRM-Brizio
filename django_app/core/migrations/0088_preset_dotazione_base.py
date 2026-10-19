"""Ogni preset concede la dotazione base: login, home/dashboard, profilo, notizie (19/10/2026).

Aggiunge ai ruoli nati dai preset le celle «bacheca» e «notizie» mancanti.
Tocca solo le celle con nota «preset …»: quelle cambiate a mano restano.
I permessi di pagina si accendono con «Sincronizza i permessi delle pagine».
"""
from django.db import migrations


def riallinea(apps, schema_editor):
    from core.permessi.preset import riallinea_preset_modello

    riallinea_preset_modello(
        gruppi=apps.get_model("core", "AccessGroup"),
        celle=apps.get_model("core", "RuoloPermessoModulo"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0087_home_personalizzata"),
    ]

    operations = [
        migrations.RunPython(riallinea, migrations.RunPython.noop),
    ]
