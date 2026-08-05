import re

from django.db import migrations
from django.utils.text import slugify


def _unique_template_code(Template, label, periodic_id):
    base = re.sub(r"-+", "-", slugify(label)[:70] or "manutenzione").strip("-")
    candidate = base
    if Template.objects.filter(code=candidate).exists():
        candidate = f"{base}-pv{periodic_id}"
    suffix = 2
    while Template.objects.filter(code=candidate).exists():
        candidate = f"{base}-pv{periodic_id}-{suffix}"
        suffix += 1
    return candidate


def ingest_periodic_verifications(apps, schema_editor):
    AssetCategory = apps.get_model("assets", "AssetCategory")
    MaintenanceTemplate = apps.get_model("assets", "MaintenanceInterventionTemplate")
    MaintenanceRule = apps.get_model("assets", "MaintenanceRule")
    MaintenanceState = apps.get_model("assets", "AssetMaintenanceRuleState")
    PeriodicVerification = apps.get_model("assets", "PeriodicVerification")
    WorkOrder = apps.get_model("assets", "WorkOrder")

    for periodic in PeriodicVerification.objects.prefetch_related("assets").all():
        assets = list(periodic.assets.all())
        if not assets or any(asset.asset_category_id is None for asset in assets):
            continue

        grouped_assets = {}
        for asset in assets:
            grouped_assets.setdefault(asset.asset_category_id, []).append(asset)
        category_ids = sorted(grouped_assets)
        existing_categories = set(
            AssetCategory.objects.filter(pk__in=category_ids).values_list("pk", flat=True)
        )
        if existing_categories != set(category_ids):
            continue

        label = (periodic.name or "Manutenzione periodica")[:120]
        threshold_days = max(1, round((periodic.frequency_months or 0) * 30))
        template_category_id = category_ids[0] if len(category_ids) == 1 else None
        template = MaintenanceTemplate.objects.filter(
            label=label,
            asset_category_id=template_category_id,
        ).first()
        if template is None and template_category_id is not None:
            template = MaintenanceTemplate.objects.filter(
                label=label,
                asset_category_id=None,
            ).first()
        if template is None:
            template = MaintenanceTemplate.objects.create(
                code=_unique_template_code(MaintenanceTemplate, label, periodic.pk),
                label=label,
                maintenance_type="ROUTINE",
                description=periodic.notes or "",
                asset_category_id=template_category_id,
                is_active=True,
            )

        for category_id in category_ids:
            group = grouped_assets[category_id]
            rule = MaintenanceRule.objects.filter(
                legacy_periodic_verifications=periodic,
                asset_category_id=category_id,
            ).first()
            if rule is None and periodic.is_legacy:
                rule = MaintenanceRule.objects.filter(
                    intervention_template=template,
                    asset_category_id=category_id,
                    threshold_type="DAYS",
                    threshold_value=threshold_days,
                ).first()
            if rule is None:
                rule = MaintenanceRule.objects.create(
                    intervention_template=template,
                    asset_category_id=category_id,
                    scope_type="ASSETS",
                    threshold_type="DAYS",
                    threshold_value=threshold_days,
                    warning_days=max(7, threshold_days // 10),
                    execution_mode="EXTERNAL" if periodic.supplier_id else "INTERNAL",
                    supplier_id=periodic.supplier_id,
                    first_due_date=periodic.next_verification_date,
                    is_active=periodic.is_active,
                )
                rule.assets.set(group)
            rule.legacy_periodic_verifications.add(periodic)

            asset_ids = [asset.pk for asset in group]
            WorkOrder.objects.filter(
                periodic_verification=periodic,
                asset_id__in=asset_ids,
                maintenance_rule_id=None,
            ).update(maintenance_rule=rule)
            for asset in group:
                latest = (
                    WorkOrder.objects.filter(
                        periodic_verification=periodic,
                        asset=asset,
                        status="DONE",
                    )
                    .order_by("-closed_at", "-id")
                    .first()
                )
                executed_on = (
                    latest.closed_at.date()
                    if latest is not None and latest.closed_at is not None
                    else periodic.last_verification_date
                )
                if executed_on is not None or latest is not None:
                    MaintenanceState.objects.update_or_create(
                        asset=asset,
                        base_rule=rule,
                        defaults={
                            "last_execution_date": executed_on,
                            "last_work_order": latest,
                            "notes": "Storico inglobato dal precedente piano periodico.",
                        },
                    )

        if not periodic.is_legacy:
            periodic.is_legacy = True
            periodic.save(update_fields=["is_legacy", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0088_maintenanceinterventiontemplate_estimated_duration_minutes_and_more"),
    ]

    operations = [
        migrations.RunPython(ingest_periodic_verifications, migrations.RunPython.noop),
    ]
