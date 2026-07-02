from django.db import migrations, models


class Migration(migrations.Migration):
    """M2: slot separato per lo stato pre-errore (S9), distinto da stato_precedente (sospensione)."""

    dependencies = [
        ("gestione_specifiche", "0003_specifica_percorso_esterno"),
    ]

    operations = [
        migrations.AddField(
            model_name="specifica",
            name="stato_pre_errore",
            field=models.CharField(
                blank=True, default="", max_length=30,
                verbose_name="Stato precedente (errore tecnico)",
            ),
        ),
    ]
