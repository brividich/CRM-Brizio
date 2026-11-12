from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0103_admin_subnav_accessi_bloccati")]

    operations = [
        migrations.CreateModel(
            name="EccezionePermessoPersona",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_id", models.IntegerField(db_index=True)),
                ("modulo", models.CharField(max_length=80)),
                ("azione", models.CharField(max_length=40)),
                (
                    "ambito_massimo",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("", "Negato"),
                            ("propri", "Al massimo i propri"),
                            ("team", "Al massimo propri e del team"),
                        ],
                        default="",
                        max_length=10,
                    ),
                ),
                ("motivo", models.CharField(max_length=255)),
                ("creata_da", models.CharField(blank=True, default="", max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Eccezione sui permessi di una persona",
                "verbose_name_plural": "Eccezioni sui permessi delle persone",
                "ordering": ["legacy_user_id", "modulo", "azione"],
                "unique_together": {("legacy_user_id", "modulo", "azione")},
            },
        ),
    ]
