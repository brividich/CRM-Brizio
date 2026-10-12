from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestione_specifiche", "0013_registroofi_azioneofi_registro"),
    ]

    operations = [
        migrations.AddField(
            model_name="registroofi",
            name="fonte",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="Fonte del rilievo"),
        ),
        migrations.AddField(
            model_name="registroofi",
            name="norma_iso14001",
            field=models.BooleanField(default=False, verbose_name="ISO 14001"),
        ),
        migrations.AddField(
            model_name="registroofi",
            name="norma_pdr125",
            field=models.BooleanField(default=False, verbose_name="UNI/PdR 125"),
        ),
    ]
