"""E-learning, rilascio 2: token unico dei tentativi e tipo delle slide esistenti.

1. Ogni tentativo esistente riceve un token casuale proprio (un ``default``
   diretto in AddField darebbe a tutte le righe lo stesso valore): poi il campo
   diventa unico con default casuale.
2. Le slide con immagine diventano di tipo IMMAGINE (le altre restano TESTO).

Reverse: i dati restano; il vincolo di unicità viene tolto dall'AlterField inverso.
"""
import uuid

from django.db import migrations, models

import anagrafica.models_formazione


def avanti(apps, schema_editor):
    Attempt = apps.get_model("anagrafica", "TrainingQuizAttempt")
    for pk in Attempt.objects.filter(token="").values_list("pk", flat=True).iterator():
        Attempt.objects.filter(pk=pk).update(token=uuid.uuid4().hex)
    Slide = apps.get_model("anagrafica", "TrainingSlide")
    Slide.objects.exclude(immagine="").exclude(immagine__isnull=True).update(tipo="IMMAGINE")


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0146_elearning_professionale"),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="trainingquizattempt",
            name="token",
            field=models.CharField(default=anagrafica.models_formazione._nuovo_token, max_length=32, unique=True),
        ),
    ]
