from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import assets.models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0028_alter_assetdetailsectionlayout_code"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetReportTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "report_code",
                    models.CharField(
                        choices=[
                            ("ASSET_DETAIL", "Scheda asset PDF"),
                            ("WORK_MACHINE_MAINTENANCE_MONTH", "Manutenzioni macchine mese"),
                        ],
                        db_index=True,
                        max_length=40,
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("version", models.CharField(blank=True, default="", max_length=40)),
                ("description", models.CharField(blank=True, default="", max_length=255)),
                ("file", models.FileField(upload_to=assets.models._asset_report_template_upload_to)),
                ("original_name", models.CharField(blank=True, default="", max_length=255)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_report_templates_uploaded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["report_code", "-is_active", "-updated_at", "-id"],
            },
        ),
    ]
