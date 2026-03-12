from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notizia",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("titolo", models.CharField(max_length=300)),
                ("corpo", models.TextField()),
                ("stato", models.CharField(
                    choices=[("bozza", "Bozza"), ("pubblicata", "Pubblicata"), ("archiviata", "Archiviata")],
                    db_index=True,
                    default="bozza",
                    max_length=20,
                )),
                ("versione", models.PositiveIntegerField(default=1)),
                ("hash_versione", models.CharField(blank=True, editable=False, max_length=64)),
                ("obbligatoria", models.BooleanField(db_index=True, default=False)),
                ("pubblicato_il", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("creato_da", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="notizie_create",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "verbose_name": "Notizia",
                "verbose_name_plural": "Notizie",
                "ordering": ["-pubblicato_il", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="NotiziaAudience",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_role_id", models.IntegerField()),
                ("notizia", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="audience",
                    to="notizie.notizia",
                )),
            ],
            options={
                "verbose_name": "Audience ruolo",
                "verbose_name_plural": "Audience ruoli",
            },
        ),
        migrations.CreateModel(
            name="NotiziaAllegato",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome_file", models.CharField(max_length=300)),
                ("file", models.FileField(blank=True, null=True, upload_to="notizie/allegati/")),
                ("url_esterno", models.CharField(blank=True, max_length=500)),
                ("hash_file", models.CharField(blank=True, max_length=64)),
                ("dimensione_bytes", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("notizia", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="allegati",
                    to="notizie.notizia",
                )),
            ],
            options={
                "verbose_name": "Allegato",
                "verbose_name_plural": "Allegati",
                "ordering": ["nome_file"],
            },
        ),
        migrations.CreateModel(
            name="NotiziaLettura",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_id", models.IntegerField(db_index=True)),
                ("versione_letta", models.PositiveIntegerField()),
                ("hash_versione_letta", models.CharField(max_length=64)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("ack_at", models.DateTimeField(blank=True, null=True)),
                ("notizia", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="letture",
                    to="notizie.notizia",
                )),
            ],
            options={
                "verbose_name": "Lettura",
                "verbose_name_plural": "Letture",
                "ordering": ["-versione_letta"],
            },
        ),
        migrations.AddConstraint(
            model_name="notiziaaudience",
            constraint=models.UniqueConstraint(
                fields=("notizia", "legacy_role_id"),
                name="notizie_audience_notizia_role_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="notizialettura",
            constraint=models.UniqueConstraint(
                fields=("notizia", "legacy_user_id", "versione_letta"),
                name="notizie_lettura_notizia_user_ver_uniq",
            ),
        ),
    ]
