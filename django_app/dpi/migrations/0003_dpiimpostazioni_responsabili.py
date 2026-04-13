from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dpi", "0002_dpiimpostazioni_singleton"),
    ]

    operations = [
        migrations.AddField(
            model_name="dpiimpostazioni",
            name="responsabili",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
