import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("anagrafica", "0212_subnav_voce_costo_orario"),
        ("assets", "0156_sidebar_aree"),
    ]

    operations = [
        migrations.CreateModel(
            name="RepartoAssetCollegato",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("testo", models.CharField(max_length=120)),
                ("chiave", models.CharField(help_text="Testo normalizzato (minuscolo, spazi singoli).", max_length=120, unique=True)),
                ("aggiornato_da", models.CharField(blank=True, default="", max_length=150)),
                ("aggiornato_il", models.DateTimeField(auto_now=True)),
                ("area", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="anagrafica.areaaziendale")),
                ("reparto", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="anagrafica.reparto")),
            ],
            options={
                "verbose_name": "Reparto asset collegato",
                "verbose_name_plural": "Reparti asset collegati",
                "ordering": ["testo"],
            },
        ),
    ]
