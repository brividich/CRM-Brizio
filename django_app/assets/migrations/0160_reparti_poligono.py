"""Reparti a forma libera sulla planimetria: vertici in ``PlantLayoutArea.punti`` (vuoto = rettangolo)."""
from django.db import migrations, models

from dati_bi.viste import ripristina_viste_sqlite, sospendi_viste_sqlite


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0159_mappa_ticket'),
    ]

    operations = [
        migrations.RunPython(sospendi_viste_sqlite, ripristina_viste_sqlite),
        migrations.AddField(
            model_name='plantlayoutarea',
            name='punti',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(ripristina_viste_sqlite, sospendi_viste_sqlite),
    ]
