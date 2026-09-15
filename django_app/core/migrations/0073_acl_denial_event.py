from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0072_access_groups"),
    ]

    operations = [
        migrations.CreateModel(
            name="AclDenialEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_id", models.IntegerField(db_index=True)),
                ("legacy_role_id", models.IntegerField(blank=True, null=True)),
                ("dedup_key", models.CharField(max_length=300)),
                ("permission_code", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("path", models.CharField(blank=True, default="", max_length=500)),
                ("route_name", models.CharField(blank=True, default="", max_length=160)),
                ("decision_source", models.CharField(blank=True, default="", max_length=60)),
                ("reason", models.CharField(blank=True, default="", max_length=500)),
                ("hits", models.PositiveIntegerField(default=1)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Da decidere"),
                            ("allowed", "Consentito"),
                            ("denied", "Diniego confermato"),
                            ("ignored", "Ignorato"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=12,
                    ),
                ),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_by", models.CharField(blank=True, default="", max_length=200)),
            ],
            options={
                "verbose_name": "Accesso negato",
                "verbose_name_plural": "Accessi negati",
                "ordering": ["-last_seen_at", "-id"],
                "unique_together": {("legacy_user_id", "dedup_key")},
            },
        ),
    ]
