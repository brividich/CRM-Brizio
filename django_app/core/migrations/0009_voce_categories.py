from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_anagrafica_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="anagraficavoce",
            name="categoria",
            field=models.CharField(blank=True, default="Campi extra", max_length=100),
        ),
        migrations.AddField(
            model_name="checklistvoce",
            name="categoria",
            field=models.CharField(blank=True, default="Generale", max_length=100),
        ),
    ]

