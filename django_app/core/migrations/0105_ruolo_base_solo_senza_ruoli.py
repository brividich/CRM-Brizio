"""Il ruolo base «Operatore» vale solo per chi non ha altri ruoli (30/10/2026).

Perche' nessuno perda niente al passaggio, i «si'» di Operatore si copiano nelle
caselle vuote di ogni altro ruolo (non amministratore), con i permessi di pagina
che Operatore concede e il ruolo non decide gia'. Dopo il deploy:
«Sincronizza i permessi delle pagine».
"""
from django.db import migrations


def completa(apps, schema_editor):
    from core.permessi.ruolo_base import completa_dal_ruolo_base

    completa_dal_ruolo_base(
        gruppi=apps.get_model("core", "AccessGroup"),
        celle=apps.get_model("core", "RuoloPermessoModulo"),
        grant=apps.get_model("core", "GroupPermissionGrant"),
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0104_eccezione_permesso_persona")]

    operations = [migrations.RunPython(completa, migrations.RunPython.noop)]
