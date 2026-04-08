from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0037_seed_maintenance_operations_sidebar_buttons"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetMaintenanceCalendarEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("due_date", models.DateField(db_index=True)),
                ("target_legacy_user_id", models.IntegerField(db_index=True)),
                ("target_display_name", models.CharField(blank=True, default="", max_length=200)),
                ("target_email", models.CharField(max_length=200)),
                ("subject", models.CharField(blank=True, default="", max_length=255)),
                ("transaction_id", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("graph_event_id", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("graph_event_web_link", models.CharField(blank=True, default="", max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="maintenance_calendar_events",
                        to="assets.asset",
                    ),
                ),
                (
                    "base_rule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="calendar_events",
                        to="assets.maintenancerule",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_maintenance_calendar_events_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Evento calendario manutenzione asset",
                "verbose_name_plural": "Eventi calendario manutenzione asset",
                "ordering": ["due_date", "target_display_name", "target_email", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="assetmaintenancecalendarevent",
            constraint=models.UniqueConstraint(
                fields=("asset", "base_rule", "due_date", "target_legacy_user_id"),
                name="uniq_asset_maintenance_calendar_event",
            ),
        ),
    ]
