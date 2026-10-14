"""Bacheca: sezione «Risorse self-help» per categoria, colore e sigla delle copertine."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0079_preset_permessi_modulo"),
    ]

    operations = [
        migrations.AddField(
            model_name="hublinkcategory",
            name="sezione",
            field=models.CharField(
                choices=[("documenti", "Documenti & collegamenti"), ("self_help", "Risorse self-help")],
                default="documenti",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="hublinkcategory",
            name="colore",
            field=models.CharField(
                blank=True, default="", help_text="Colore delle copertine self-help, es. #1f4f86.", max_length=7
            ),
        ),
        migrations.AddField(
            model_name="hublink",
            name="sigla",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Testo grande della copertina self-help (es. VPN, 2FA). Vuoto = dal titolo.",
                max_length=8,
            ),
        ),
    ]
