"""Preset di permessi per modulo, salvati dalla pagina Accessi."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0078_ruoli_portale_preset_celle_nuove"),
    ]

    operations = [
        migrations.CreateModel(
            name="PresetPermessiModulo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("modulo", models.CharField(db_index=True, max_length=80)),
                ("nome", models.CharField(max_length=80)),
                ("descrizione", models.CharField(blank=True, default="", max_length=300)),
                ("codici_json", models.TextField(default="[]")),
                ("creato_da", models.CharField(blank=True, default="", max_length=150)),
                ("creato_il", models.DateTimeField(auto_now_add=True)),
                ("aggiornato_il", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Preset permessi di modulo",
                "verbose_name_plural": "Preset permessi di modulo",
                "ordering": ["modulo", "nome"],
            },
        ),
        migrations.AddConstraint(
            model_name="presetpermessimodulo",
            constraint=models.UniqueConstraint(fields=("modulo", "nome"), name="uniq_preset_permessi_modulo_nome"),
        ),
    ]
