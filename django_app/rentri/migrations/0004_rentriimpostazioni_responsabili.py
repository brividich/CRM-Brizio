from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rentri", "0003_rentriimpostazioni_singleton"),
    ]

    operations = [
        migrations.AddField(
            model_name="rentriimpostazioni",
            name="responsabili",
            field=models.JSONField(blank=True, default=list, verbose_name="Referenti"),
        ),
    ]
