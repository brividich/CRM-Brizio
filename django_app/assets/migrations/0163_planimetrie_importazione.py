"""Importazione delle planimetrie dai PDF: il PDF resta come fonte per la lettura, più lo stato della validazione."""
from django.db import migrations, models

from dati_bi.viste import ripristina_viste_sqlite, sospendi_viste_sqlite


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0162_planimetrie_livelli'),
    ]

    operations = [
        migrations.RunPython(sospendi_viste_sqlite, ripristina_viste_sqlite),
        migrations.AddField(
            model_name='plantlayout',
            name='sorgente_pdf',
            field=models.FileField(blank=True, default='', max_length=200, upload_to='planimetrie_sorgenti/'),
        ),
        migrations.AddField(
            model_name='plantlayout',
            name='importazione',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(ripristina_viste_sqlite, sospendi_viste_sqlite),
    ]
