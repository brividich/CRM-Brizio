from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0020_asset_filters_and_conflict_settings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="KickoffMeeting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero", models.PositiveIntegerField(verbose_name="Numero incontro")),
                ("titolo", models.CharField(blank=True, default="", max_length=240, verbose_name="Titolo")),
                ("data", models.DateField(verbose_name="Data")),
                ("ora", models.TimeField(blank=True, null=True, verbose_name="Ora")),
                ("luogo", models.CharField(blank=True, default="", max_length=200, verbose_name="Luogo")),
                ("partecipanti_testo", models.TextField(blank=True, default="", verbose_name="Partecipanti")),
                ("ordine_del_giorno", models.TextField(blank=True, default="", verbose_name="Ordine del giorno")),
                ("note", models.TextField(blank=True, default="", verbose_name="Note / Verbale")),
                ("problemi_aperti", models.TextField(blank=True, default="", verbose_name="Problemi aperti")),
                ("next_steps", models.TextField(blank=True, default="", verbose_name="Next steps")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="kickoff_meetings_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="meetings",
                        to="tasks.project",
                        verbose_name="Kickoff",
                    ),
                ),
            ],
            options={
                "verbose_name": "Incontro kickoff",
                "verbose_name_plural": "Incontri kickoff",
                "ordering": ["numero"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="kickoffmeeting",
            unique_together={("project", "numero")},
        ),
    ]
