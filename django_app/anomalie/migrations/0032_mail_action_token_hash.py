"""Il link mail delle anomalie tiene nel database solo l'impronta del segreto.

La colonna ``token`` diventa ``token_hash`` e i segreti già salvati vengono
sostituiti dalla loro impronta SHA-256: i link delle mail già inviate restano
validi, perché la pagina cerca per impronta del segreto ricevuto nell'URL.
"""
import hashlib
import re

from django.db import migrations, models

_IMPRONTA = re.compile(r"^[0-9a-f]{64}$")


def _impronte(apps, schema_editor):
    Token = apps.get_model("anomalie", "AnomaliaMailActionToken")
    for pk, valore in Token.objects.values_list("pk", "token_hash").iterator():
        valore = str(valore or "")
        # Un segreto è lungo 43 caratteri: una riga già a 64 esadecimali è un'impronta.
        if _IMPRONTA.match(valore):
            continue
        Token.objects.filter(pk=pk).update(token_hash=hashlib.sha256(valore.encode("utf-8")).hexdigest())


class Migration(migrations.Migration):

    dependencies = [
        ("anomalie", "0031_anomalia_op_incaricato"),
    ]

    operations = [
        migrations.RenameField(model_name="anomaliamailactiontoken", old_name="token", new_name="token_hash"),
        migrations.AlterField(
            model_name="anomaliamailactiontoken",
            name="token_hash",
            field=models.CharField(db_index=True, editable=False, max_length=64, unique=True),
        ),
        migrations.RunPython(_impronte, migrations.RunPython.noop),
    ]
