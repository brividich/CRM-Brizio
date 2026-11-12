"""Soglie del sovraccarico: da ogni prospetto alle Impostazioni Skill Matrix, valide per tutti."""
import django.core.validators
from django.db import migrations, models

ROTTA_TOLTA = "anagrafica:prospetto_soglie"


def togli_binding(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name=ROTTA_TOLTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0221_prospetto_acl_menu"),
    ]

    operations = [
        migrations.AddField(
            model_name="skillmatrixconfig",
            name="soglia_concentrazione",
            field=models.PositiveSmallIntegerField(
                default=80,
                help_text="Da questa % di tempo media degli operativi la mansione è a carico concentrato.",
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(100)],
            ),
        ),
        migrations.AddField(
            model_name="skillmatrixconfig",
            name="soglia_mansioni_persona",
            field=models.PositiveSmallIntegerField(
                default=8,
                help_text="Oltre questo numero di mansioni la persona è segnalata.",
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(100)],
            ),
        ),
        migrations.RemoveField(model_name="prospettostruttura", name="soglia_mansioni_persona"),
        migrations.RemoveField(model_name="prospettostruttura", name="soglia_concentrazione"),
        migrations.RunPython(togli_binding, migrations.RunPython.noop),
    ]
