from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assenze", "0014_cambio_capo_abilitato"),
    ]

    operations = [
        migrations.CreateModel(
            name="CapoAggiunto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_anagrafica_id", models.IntegerField(db_index=True, unique=True)),
                ("nominativo", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.CharField(blank=True, default="", max_length=200)),
            ],
            options={
                "verbose_name": "Capo reparto aggiunto a mano",
                "verbose_name_plural": "Capi reparto aggiunti a mano",
                "ordering": ["nominativo", "legacy_anagrafica_id"],
            },
        ),
        migrations.CreateModel(
            name="CapoFissoDipendente",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dipendente_legacy_anagrafica_id", models.IntegerField(db_index=True, unique=True)),
                ("dipendente_nominativo", models.CharField(blank=True, default="", max_length=200)),
                ("capo_legacy_anagrafica_id", models.IntegerField(db_index=True)),
                ("capo_nominativo", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.CharField(blank=True, default="", max_length=200)),
            ],
            options={
                "verbose_name": "Capo fisso del dipendente",
                "verbose_name_plural": "Capi fissi dei dipendenti",
                "ordering": ["dipendente_nominativo", "dipendente_legacy_anagrafica_id"],
            },
        ),
    ]
