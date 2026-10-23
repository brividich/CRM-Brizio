import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0001_initial"),
        ("core", "0094_permesso_le_mie_assenze"),
    ]

    operations = [
        migrations.AddField(
            model_name="postazionecondivisa",
            name="asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="postazioni_condivise",
                to="assets.asset",
            ),
        ),
    ]
