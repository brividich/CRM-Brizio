from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0036_dipendenteanagraficacivile_figli_a_carico_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentodipendente",
            name="retention_until",
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text="Data limite GDPR. Calcolata automaticamente; modificabile manualmente.",
                null=True,
                verbose_name="Conservare fino al",
            ),
        ),
        migrations.AddIndex(
            model_name="documentodipendente",
            index=models.Index(fields=["retention_until"], name="anagrafica__retenti_idx"),
        ),
    ]
