import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0017_securitymailboxsource_folders"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityEscalationRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("event_type", models.CharField(db_index=True, max_length=120)),
                ("match_payload", models.JSONField(blank=True, default=dict)),
                ("severity", models.CharField(choices=[("info", "Info"), ("low", "Low"), ("medium", "Medium"), ("warning", "Warning"), ("high", "High"), ("critical", "Critical")], default="warning", max_length=24)),
                ("reason", models.TextField(blank=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("hit_count", models.PositiveIntegerField(default=0)),
                ("last_hit_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("origin_alert", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="security.securityalert")),
                ("origin_event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="security.securityeventrecord")),
                ("source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="security.securitysource")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["event_type", "is_active"], name="sec_escal_type_active_idx")],
            },
        ),
    ]
