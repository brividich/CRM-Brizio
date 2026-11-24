from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0173_qr_pubblico_contenuti"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetcategorydocumentfolder",
            name="facoltativa",
            field=models.BooleanField(default=False),
        ),
    ]
