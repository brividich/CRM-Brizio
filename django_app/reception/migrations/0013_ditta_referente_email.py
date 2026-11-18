from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0012_gruppi_allegati"),
    ]

    operations = [
        migrations.AddField(
            model_name="dittaaccreditata",
            name="referente_email",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
