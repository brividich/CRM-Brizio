"""Interventi: modalita' di esecuzione interna/esterna dichiarata nel form."""
from django.db import migrations, models

from dati_bi.viste import ripristina_viste_sqlite, sospendi_viste_sqlite


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0160_reparti_poligono"),
    ]

    operations = [
        migrations.RunPython(sospendi_viste_sqlite, ripristina_viste_sqlite),
        migrations.AddField(
            model_name="workorder",
            name="execution_mode",
            field=models.CharField(
                blank=True,
                choices=[("INTERNAL", "Interna"), ("EXTERNAL", "Esterna (ditta terza)")],
                default="",
                help_text="Interna (squadra manutenzione) o esterna (ditta terza).",
                max_length=20,
            ),
        ),
        migrations.RunPython(ripristina_viste_sqlite, sospendi_viste_sqlite),
    ]
