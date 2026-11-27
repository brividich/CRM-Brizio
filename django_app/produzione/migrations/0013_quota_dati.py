from django.db import migrations, models


class Migration(migrations.Migration):
    """Registro delle quote: l'analisi completa salvata per quota (le pagine la leggono, il giro la calcola)."""

    dependencies = [("produzione", "0012_rinomina_controllo_dimensionale")]

    operations = [
        migrations.AddField(
            model_name="quotacapacita",
            name="dati",
            field=models.TextField(blank=True, default="", help_text="L'analisi completa della quota in JSON (serie, limiti, "
                                                                     "segnali, confronto fra OP): la leggono le pagine."),
        ),
    ]
