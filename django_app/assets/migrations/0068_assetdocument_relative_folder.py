"""Aggiunge il percorso relativo della cartella di origine ai documenti asset.

Conserva la struttura della cartella selezionata con "Carica cartella": i file
restano raggruppati nel portale e replicano la gerarchia su SharePoint.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0067_category_sidebar"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetdocument",
            name="relative_folder",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Percorso relativo della cartella di origine (upload 'Carica cartella'); vuoto per i file singoli.",
                max_length=400,
            ),
        ),
    ]
