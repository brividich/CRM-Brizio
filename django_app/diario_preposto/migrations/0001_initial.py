from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SegnalazionePreposto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("titolo", models.CharField(max_length=300)),
                ("data_segnalazione", models.DateTimeField()),
                ("descrizione", models.TextField()),
                ("preposto", models.CharField(blank=True, max_length=200)),
                ("chi_segnala", models.CharField(blank=True, max_length=200)),
                (
                    "creato_da",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="segnalazioni_preposto_create",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Segnalazione Preposto",
                "verbose_name_plural": "Segnalazioni Preposto",
                "ordering": ["-data_segnalazione", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SegnalazioneAllegato",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome_file", models.CharField(max_length=300)),
                ("file", models.FileField(upload_to="diario_preposto/allegati/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "segnalazione",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allegati",
                        to="diario_preposto.segnalazionepreposto",
                    ),
                ),
            ],
            options={
                "verbose_name": "Allegato segnalazione",
                "verbose_name_plural": "Allegati segnalazione",
                "ordering": ["nome_file"],
            },
        ),
        migrations.CreateModel(
            name="DiarioPrepostoImpostazioni",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "acl_scrittura",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Lista di username o email autorizzati alla scrittura (oltre agli admin legacy).",
                    ),
                ),
            ],
            options={
                "verbose_name": "Impostazioni Diario Preposto",
                "verbose_name_plural": "Impostazioni Diario Preposto",
            },
        ),
    ]
