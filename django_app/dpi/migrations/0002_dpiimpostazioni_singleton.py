from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dpi", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="dpiimpostazioni",
            constraint=models.CheckConstraint(
                check=models.Q(pk=1),
                name="dpiimpostazioni_singleton",
            ),
        ),
    ]
