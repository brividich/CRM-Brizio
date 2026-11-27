from django.db import migrations, models

from dati_bi.viste import ripristina_viste_sqlite, sospendi_viste_sqlite


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0175_documento_data_scadenza"),
    ]

    operations = [
        # Solo SQLite: le viste bi_* leggono assets_asset e bloccano il rifacimento della tabella.
        migrations.RunPython(sospendi_viste_sqlite, ripristina_viste_sqlite),
        migrations.AddField(
            model_name="asset",
            name="acronimo",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Sigla con cui l'asset è riconosciuto in azienda (es. DM11, AGV1, MK2).",
                max_length=32,
                verbose_name="Acronimo",
            ),
        ),
        migrations.RunPython(ripristina_viste_sqlite, sospendi_viste_sqlite),
    ]
