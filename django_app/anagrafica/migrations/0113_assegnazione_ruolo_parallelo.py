from django.db import migrations, models


class Migration(migrations.Migration):
    """Spostamento con ruolo «in parallelo»: si aggiunge invece di sostituire."""

    dependencies = [
        ("anagrafica", "0112_ruoli_ambiti"),
    ]

    operations = [
        migrations.AddField(
            model_name="dipendenteassegnazione",
            name="ruolo_parallelo",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Il ruolo si aggiunge a quello in essere invece di sostituirlo: "
                    "serve quando i due incarichi convivono pur essendo dello stesso ambito."
                ),
                verbose_name="Ruolo in parallelo",
            ),
        ),
    ]
