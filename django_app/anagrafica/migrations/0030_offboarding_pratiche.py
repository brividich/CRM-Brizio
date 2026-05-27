from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("anagrafica", "0029_aziendale_account_pre_offboarding"),
    ]

    operations = [
        migrations.CreateModel(
            name="OffboardingPratica",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_anagrafica_id", models.IntegerField(db_index=True)),
                ("dipendente_nome", models.CharField(blank=True, default="", max_length=250)),
                ("reparto", models.CharField(blank=True, default="", max_length=200)),
                ("mansione", models.CharField(blank=True, default="", max_length=200)),
                (
                    "motivo",
                    models.CharField(
                        choices=[
                            ("licenziamento", "Licenziamento"),
                            ("dimissioni", "Dimissioni"),
                            ("fine_contratto", "Fine contratto"),
                            ("pensionamento", "Pensionamento"),
                            ("altro", "Altro"),
                        ],
                        default="licenziamento",
                        max_length=30,
                    ),
                ),
                ("data_cessazione_prevista", models.DateField()),
                ("ultimo_giorno_operativo", models.DateField(blank=True, null=True)),
                ("note_hr", models.TextField(blank=True, default="")),
                (
                    "stato",
                    models.CharField(
                        choices=[
                            ("IN_CORSO", "In corso"),
                            ("CHIUSA", "Chiusa"),
                            ("CHIUSA_CON_ECCEZIONI", "Chiusa con eccezioni"),
                            ("ANNULLATA", "Annullata"),
                        ],
                        db_index=True,
                        default="IN_CORSO",
                        max_length=30,
                    ),
                ),
                ("utente_id_pre_offboarding", models.IntegerField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "closed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="offboarding_pratiche_chiuse",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="offboarding_pratiche_create",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="offboarding_pratiche_aggiornate",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Pratica offboarding",
                "verbose_name_plural": "Pratiche offboarding",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="OffboardingTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codice", models.CharField(max_length=60)),
                (
                    "categoria",
                    models.CharField(
                        choices=[
                            ("HR", "HR"),
                            ("IT", "IT / Sistemi informatici"),
                            ("RESPONSABILE", "Responsabile reparto"),
                            ("DPI", "DPI / Sicurezza"),
                            ("AMMINISTRAZIONE", "Amministrazione"),
                            ("ALTRO", "Altro"),
                        ],
                        db_index=True,
                        default="HR",
                        max_length=30,
                    ),
                ),
                ("titolo", models.CharField(max_length=200)),
                ("descrizione", models.TextField(blank=True, default="")),
                (
                    "stato",
                    models.CharField(
                        choices=[
                            ("DA_FARE", "Da fare"),
                            ("COMPLETATO", "Completato"),
                            ("ECCEZIONE", "Eccezione"),
                        ],
                        db_index=True,
                        default="DA_FARE",
                        max_length=20,
                    ),
                ),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "completed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="offboarding_task_completati",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "pratica",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tasks",
                        to="anagrafica.offboardingpratica",
                    ),
                ),
            ],
            options={
                "verbose_name": "Task offboarding",
                "verbose_name_plural": "Task offboarding",
                "ordering": ["categoria", "id"],
                "unique_together": {("pratica", "codice")},
            },
        ),
        migrations.AddIndex(
            model_name="offboardingpratica",
            index=models.Index(fields=["legacy_anagrafica_id", "stato", "-created_at"], name="anagrafica__legacy__b19006_idx"),
        ),
        migrations.AddIndex(
            model_name="offboardingtask",
            index=models.Index(fields=["pratica", "stato"], name="anagrafica__pratica_ce9f4b_idx"),
        ),
        migrations.AddIndex(
            model_name="offboardingtask",
            index=models.Index(fields=["categoria", "stato"], name="anagrafica__categor_18fe4d_idx"),
        ),
    ]
