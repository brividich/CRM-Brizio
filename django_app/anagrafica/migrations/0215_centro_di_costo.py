"""Centro di costo: raggruppa più reparti (aree del portale); un'area in un solo centro."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0214_fornitore_requisiti_sicurezza"),
    ]

    operations = [
        migrations.CreateModel(
            name="CentroDiCosto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100, unique=True)),
                ("descrizione", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Centro di costo",
                "verbose_name_plural": "Centri di costo",
                "ordering": ["nome"],
            },
        ),
        migrations.AddField(
            model_name="areaaziendale",
            name="centro_di_costo",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="aree", to="anagrafica.centrodicosto", verbose_name="Centro di costo",
            ),
        ),
        migrations.AddField(
            model_name="areaaziendale",
            name="ruoli_reparto",
            field=models.ManyToManyField(
                blank=True, help_text="Ruoli presenti in questo reparto, dall'elenco dell'azienda.",
                related_name="aree_reparto", to="anagrafica.ruolooperativo", verbose_name="Ruoli del reparto",
            ),
        ),
    ]
