from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0005_dipendenteanagraficacivile_aziendale_hrpermission"),
    ]

    operations = [
        migrations.CreateModel(
            name="AreaAziendale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100, unique=True)),
                ("descrizione", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Area aziendale",
                "verbose_name_plural": "Aree aziendali",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="RuoloAziendale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=200, unique=True)),
                ("descrizione", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Ruolo aziendale",
                "verbose_name_plural": "Ruoli aziendali",
                "ordering": ["nome"],
            },
        ),
    ]
