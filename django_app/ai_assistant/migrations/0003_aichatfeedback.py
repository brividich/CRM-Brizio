from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_assistant", "0002_aitoolprivacyreview"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AiChatFeedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "prompt",
                    models.TextField(
                        help_text="Il messaggio utente originale, max 500 char.",
                    ),
                ),
                (
                    "response",
                    models.TextField(
                        help_text="La risposta AI originale, max 2000 char.",
                    ),
                ),
                (
                    "rating",
                    models.CharField(
                        choices=[("up", "Positivo"), ("down", "Negativo")],
                        db_index=True,
                        max_length=4,
                    ),
                ),
                (
                    "correction",
                    models.TextField(
                        blank=True,
                        help_text="La risposta corretta proposta dall'utente.",
                    ),
                ),
                ("source_label", models.CharField(default="Feedback chat", max_length=120)),
                (
                    "is_reviewed",
                    models.BooleanField(
                        db_index=True,
                        default=False,
                        help_text="L'amministratore ha visionato questo feedback.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_chat_feedbacks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "knowledge_entry",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feedback_entries",
                        to="ai_assistant.aiknowledgeentry",
                        help_text="Voce FAQ generata automaticamente da questo feedback (se rating=down con correzione).",
                    ),
                ),
            ],
            options={
                "verbose_name": "feedback chat AI",
                "verbose_name_plural": "feedback chat AI",
                "ordering": ["-created_at"],
            },
        ),
    ]
