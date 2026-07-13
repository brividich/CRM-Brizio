# Generated for Security Center AI Patch 5

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0002_securityalert_acknowledged_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="securityremediationticket",
            name="cve_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="first_seen_at",
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="last_seen_at",
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="linked_alerts",
            field=models.ManyToManyField(blank=True, related_name="linked_remediation_tickets", to="security.securityalert"),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="max_cvss",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="max_exposed_devices",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="occurrence_count",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="organization",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="severity",
            field=models.CharField(choices=[("info", "Info"), ("low", "Low"), ("medium", "Medium"), ("warning", "Warning"), ("high", "High"), ("critical", "Critical")], db_index=True, default="warning", max_length=24),
        ),
        migrations.AddField(
            model_name="securityremediationticket",
            name="source_system",
            field=models.CharField(blank=True, db_index=True, max_length=80),
        ),
    ]
