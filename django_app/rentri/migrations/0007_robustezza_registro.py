from django.db import migrations, models


def segna_storico(apps, schema_editor):
    """I movimenti già presenti non sono nati dal portale nuovo: origine «storico»."""
    RegistroRifiuti = apps.get_model("rentri", "RegistroRifiuti")
    RegistroRifiuti.objects.all().update(origine="storico")


class Migration(migrations.Migration):

    dependencies = [
        ("rentri", "0006_allegati_storage_privato"),
    ]

    operations = [
        migrations.AddField(
            model_name="registrorifiuti",
            name="unita",
            field=models.CharField(blank=True, choices=[("kg", "kg"), ("t", "t"), ("l", "litri"), ("m3", "m³")], default="", max_length=3),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="origine",
            field=models.CharField(choices=[("portale", "Portale"), ("import", "Import CSV"), ("sharepoint", "SharePoint"), ("storico", "Storico")], default="portale", max_length=12),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="consolidato_il",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="consolidato_da",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="annullato",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="annullato_il",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="annullato_da",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="motivo_annullamento",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="registrorifiuti",
            name="sync_errore",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.RunPython(segna_storico, migrations.RunPython.noop),
    ]
