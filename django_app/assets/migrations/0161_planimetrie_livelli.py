"""Pianta base + livelli di servizio, categorie della planimetria e scala reale."""
import django.db.models.deletion
from django.db import migrations, models

from dati_bi.viste import ripristina_viste_sqlite, sospendi_viste_sqlite


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0160_reparti_poligono'),
    ]

    operations = [
        migrations.RunPython(sospendi_viste_sqlite, ripristina_viste_sqlite),
        migrations.AddField(
            model_name='plantlayout',
            name='base',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='livelli', to='assets.plantlayout', verbose_name='Pianta base'),
        ),
        migrations.AddField(
            model_name='plantlayout',
            name='allineamento',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='plantlayout',
            name='colore',
            field=models.CharField(blank=True, default='', max_length=7),
        ),
        migrations.AddField(
            model_name='plantlayout',
            name='asset_categories',
            field=models.ManyToManyField(blank=True, related_name='plant_layouts', to='assets.assetcategory',
                                         verbose_name='Categorie su questa planimetria'),
        ),
        migrations.AddField(
            model_name='plantlayout',
            name='scala',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(ripristina_viste_sqlite, sospendi_viste_sqlite),
    ]
