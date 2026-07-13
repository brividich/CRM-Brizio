# Generated for AI-MEMORY-02 semantic retrieval fallback storage.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0008_aiconversation_aiconversationmessage_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIKnowledgeEmbedding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(db_index=True, max_length=80)),
                ("model_name", models.CharField(blank=True, max_length=160)),
                ("dimensions", models.PositiveIntegerField(db_index=True, default=384)),
                ("embedding_hash", models.CharField(db_index=True, max_length=64)),
                ("embedding", models.JSONField(blank=True, default=list)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "chunk",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="knowledge_embedding",
                        to="security.aiknowledgechunk",
                    ),
                ),
            ],
            options={
                "ordering": ["chunk__document", "chunk__chunk_index"],
                "indexes": [
                    models.Index(
                        fields=["provider", "model_name", "dimensions"],
                        name="security_ai_provide_2705a6_idx",
                    ),
                    models.Index(fields=["embedding_hash"], name="security_ai_embeddi_cb8f77_idx"),
                ],
            },
        ),
    ]
