import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_assistant", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AiToolPrivacyReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tool_key", models.CharField(db_index=True, max_length=80, unique=True)),
                ("tool_label", models.CharField(blank=True, max_length=120)),
                (
                    "privacy_status",
                    models.CharField(
                        choices=[
                            ("pending", "Da revisionare"),
                            ("approved", "Approvato"),
                            ("restricted", "Uso limitato"),
                            ("blocked", "Bloccato"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "allowed_fields",
                    models.TextField(
                        blank=True,
                        help_text="Campi consentiti nel contesto AI, separati da virgola.",
                    ),
                ),
                (
                    "blocked_fields",
                    models.TextField(
                        blank=True,
                        help_text="Campi vietati, separati da virgola.",
                    ),
                ),
                (
                    "retention_days",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        help_text="Giorni di retention per audit AI di questo tool (vuoto = policy globale).",
                    ),
                ),
                (
                    "notes",
                    models.TextField(
                        blank=True,
                        help_text="Note interne sulla revisione. Non trasmesse al modello.",
                    ),
                ),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_privacy_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "revisione privacy tool AI",
                "verbose_name_plural": "revisioni privacy tool AI",
                "ordering": ["tool_key"],
            },
        ),
    ]
