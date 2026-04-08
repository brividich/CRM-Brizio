from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _populate_asset_calendar_source_keys(apps, schema_editor):
    AssetCalendarEvent = apps.get_model("assets", "AssetCalendarEvent")
    for row in AssetCalendarEvent.objects.all().iterator():
        due_date = getattr(row, "due_date", None)
        due_value = due_date.isoformat() if due_date else ""
        row.event_kind = "MAINTENANCE"
        row.source_key = (
            f"MAINTENANCE:{int(row.asset_id or 0)}:{int(getattr(row, 'maintenance_rule_id', 0) or 0)}:"
            f"{due_value}:{int(row.target_legacy_user_id or 0)}"
        )
        row.save(update_fields=["event_kind", "source_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0038_assetmaintenancecalendarevent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(
            old_name="AssetMaintenanceCalendarEvent",
            new_name="AssetCalendarEvent",
        ),
        migrations.RemoveConstraint(
            model_name="assetcalendarevent",
            name="uniq_asset_maintenance_calendar_event",
        ),
        migrations.RenameField(
            model_name="assetcalendarevent",
            old_name="base_rule",
            new_name="maintenance_rule",
        ),
        migrations.AddField(
            model_name="assetcalendarevent",
            name="event_kind",
            field=models.CharField(
                choices=[
                    ("MAINTENANCE", "Manutenzione"),
                    ("ADMIN_DEADLINE", "Scadenza amministrativa"),
                    ("PERIODIC_VERIFICATION", "Verifica periodica"),
                    ("ASSISTANCE_CONTRACT", "Contratto assistenza"),
                ],
                db_index=True,
                default="MAINTENANCE",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="assetcalendarevent",
            name="source_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="assetcalendarevent",
            name="administrative_deadline",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="calendar_events",
                to="assets.assetadministrativedeadline",
            ),
        ),
        migrations.AddField(
            model_name="assetcalendarevent",
            name="assistance_contract",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="calendar_events",
                to="assets.assistancecontract",
            ),
        ),
        migrations.AddField(
            model_name="assetcalendarevent",
            name="periodic_verification",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="calendar_events",
                to="assets.periodicverification",
            ),
        ),
        migrations.AlterField(
            model_name="assetcalendarevent",
            name="asset",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="calendar_events",
                to="assets.asset",
            ),
        ),
        migrations.AlterField(
            model_name="assetcalendarevent",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="asset_calendar_events_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="assetcalendarevent",
            name="maintenance_rule",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="calendar_events",
                to="assets.maintenancerule",
            ),
        ),
        migrations.AlterModelOptions(
            name="assetcalendarevent",
            options={
                "ordering": ["due_date", "target_display_name", "target_email", "id"],
                "verbose_name": "Evento calendario asset",
                "verbose_name_plural": "Eventi calendario asset",
            },
        ),
        migrations.RunPython(_populate_asset_calendar_source_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="assetcalendarevent",
            name="source_key",
            field=models.CharField(db_index=True, max_length=255, unique=True),
        ),
    ]
