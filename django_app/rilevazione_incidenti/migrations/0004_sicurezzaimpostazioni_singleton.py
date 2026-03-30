from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rilevazione_incidenti", "0003_sicurezzaimpostazioni_reparti_cause"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="sicurezzaimpostazioni",
            constraint=models.CheckConstraint(
                check=models.Q(pk=1),
                name="sicurezzaimpostazioni_singleton",
            ),
        ),
    ]
