from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rentri", "0002_rentriimpostazioni"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="rentriimpostazioni",
            constraint=models.CheckConstraint(
                check=models.Q(pk=1),
                name="rentriimpostazioni_singleton",
            ),
        ),
    ]
