# Migrazione: spostamento allegati segnalazioni su storage privato.
# Sostituisce l'esposizione via /media/ con accesso autenticato.

import diario_preposto.storage
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("diario_preposto", "0004_diarioprepostoimpostazioni_singleton"),
    ]

    operations = [
        migrations.AlterField(
            model_name="segnalazioneallegato",
            name="file",
            field=models.FileField(
                storage=diario_preposto.storage.PrivateDiarioPrepostoStorage,
                upload_to="diario_preposto/allegati/",
            ),
        ),
    ]
