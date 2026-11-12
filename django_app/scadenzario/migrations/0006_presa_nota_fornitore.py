import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("scadenzario", "0005_regola_ambito"),
    ]

    operations = [
        migrations.AlterField(
            model_name="presaincarico",
            name="utente",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="scadenze_in_carico", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="presaincarico",
            name="fornitore",
            field=models.ForeignKey(
                blank=True, null=True, help_text="Fornitore esterno a cui è affidata la scadenza",
                on_delete=django.db.models.deletion.SET_NULL, related_name="scadenze_in_carico",
                to="anagrafica.fornitore",
            ),
        ),
        migrations.AddField(
            model_name="presaincarico",
            name="assegnato_da",
            field=models.ForeignKey(
                blank=True, null=True, help_text="Chi l'ha affidata (può riprenderla o lasciarla)",
                on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="presaincarico",
            name="nota_da",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
