"""Servizio di convergenza PeriodicVerification -> MaintenanceRule.

Logica condivisa tra il management command `migrate_periodic_to_rules` (batch/CLI)
e l'azione UI "Converti in regola" della pagina manutenzione periodica, così che la
mutazione effettiva viva in un solo posto.

Strategia (identica al command storico):
  - frequency_months -> giorni (×30, minimo 1).
  - Tutti gli asset del piano devono appartenere alla stessa AssetCategory.
  - Riusa template/regola esistenti (per label+categoria / template+categoria+DAYS).
  - Imposta is_legacy=True sul PeriodicVerification: da quel momento il trigger
    temporale è gestito dalla MaintenanceRule, il record resta come riferimento
    fornitore/contratto.

NB: legge la categoria dagli asset (asset_category_id) ma non modifica la
classificazione asset.
"""
from __future__ import annotations

import re
from typing import Any

from django.db import transaction
from django.utils.text import slugify

from assets.models import (
    AssetMaintenanceRuleState,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    PeriodicVerification,
    WorkOrder,
)


def months_to_days(months: int) -> int:
    return max(1, round((months or 0) * 30))


def make_template_code(label: str) -> str:
    base = slugify(label)[:70] or "manutenzione"
    return re.sub(r"-+", "-", base).strip("-")


def plan_periodic_verification_migration(pv: PeriodicVerification) -> dict[str, Any]:
    """Calcola il piano senza scrivere nulla. Ritorna un dict con ``ok`` + dettagli o motivo."""
    assets = list(pv.assets.all())
    if not assets:
        return {"ok": False, "reason": "no_asset", "message": "Nessun asset collegato al piano."}

    if any(asset.asset_category_id is None for asset in assets):
        return {
            "ok": False,
            "reason": "no_category",
            "message": "Assegna una categoria a tutti gli asset prima di inglobare il piano.",
        }

    category_ids = sorted({asset.asset_category_id for asset in assets})
    categories = {row.id: row for row in AssetCategory.objects.filter(pk__in=category_ids)}
    if len(categories) != len(category_ids):
        return {"ok": False, "reason": "no_category", "message": "Categoria asset non trovata."}
    category_groups = [
        {
            "category": categories[category_id],
            "category_id": category_id,
            "assets": [asset for asset in assets if asset.asset_category_id == category_id],
        }
        for category_id in category_ids
    ]

    threshold_days = months_to_days(pv.frequency_months)
    template_label = (pv.name or "Manutenzione periodica")[:120]

    template_category_id = category_ids[0] if len(category_ids) == 1 else None
    existing_template = MaintenanceInterventionTemplate.objects.filter(
        label=template_label,
        asset_category_id=template_category_id,
    ).first()
    if existing_template is None and template_category_id is not None:
        existing_template = MaintenanceInterventionTemplate.objects.filter(
            label=template_label,
            asset_category__isnull=True,
        ).first()

    return {
        "ok": True,
        "reason": "",
        "message": "",
        "category": category_groups[0]["category"],
        "category_id": category_groups[0]["category_id"],
        "category_groups": category_groups,
        "template_category_id": template_category_id,
        "threshold_days": threshold_days,
        "template_label": template_label,
        "existing_template": existing_template,
    }


def migrate_periodic_verification_to_rule(pv: PeriodicVerification) -> dict[str, Any]:
    """Esegue la migrazione del singolo piano (transazionale, idempotente).

    Ritorna ``{"ok": True, "template", "rule", "created_template", "created_rule", ...}``
    oppure ``{"ok": False, "reason", "message"}`` se il piano non è migrabile.
    """
    plan = plan_periodic_verification_migration(pv)
    if not plan["ok"]:
        return plan

    with transaction.atomic():
        template = plan["existing_template"]
        created_template = False
        if not template:
            code = make_template_code(plan["template_label"])
            if MaintenanceInterventionTemplate.objects.filter(code=code).exists():
                code = f"{code}-pv{pv.id}"
            template = MaintenanceInterventionTemplate.objects.create(
                code=code,
                label=plan["template_label"],
                description=pv.notes or "",
                asset_category_id=plan["template_category_id"],
                is_active=True,
            )
            created_template = True

        rules = []
        created_rules = 0
        for group in plan["category_groups"]:
            rule = MaintenanceRule.objects.filter(
                legacy_periodic_verifications=pv,
                asset_category_id=group["category_id"],
            ).first()
            if rule is None and pv.is_legacy:
                rule = MaintenanceRule.objects.filter(
                    intervention_template=template,
                    asset_category_id=group["category_id"],
                    threshold_type=MaintenanceRule.THRESHOLD_DAYS,
                    threshold_value=plan["threshold_days"],
                ).first()
            if rule is None:
                rule = MaintenanceRule.objects.create(
                    intervention_template=template,
                    asset_category_id=group["category_id"],
                    scope_type=MaintenanceRule.SCOPE_ASSETS,
                    threshold_type=MaintenanceRule.THRESHOLD_DAYS,
                    threshold_value=plan["threshold_days"],
                    warning_days=max(7, plan["threshold_days"] // 10),
                    execution_mode=(
                        MaintenanceRule.MODE_EXTERNAL if pv.supplier_id else MaintenanceRule.MODE_INTERNAL
                    ),
                    supplier=pv.supplier,
                    first_due_date=pv.next_verification_date,
                    is_active=pv.is_active,
                )
                rule.assets.set(group["assets"])
                created_rules += 1
            rule.legacy_periodic_verifications.add(pv)
            rules.append(rule)

            asset_ids = [asset.id for asset in group["assets"]]
            WorkOrder.objects.filter(
                periodic_verification=pv,
                asset_id__in=asset_ids,
                maintenance_rule__isnull=True,
            ).update(maintenance_rule=rule)
            for asset in group["assets"]:
                latest_workorder = (
                    WorkOrder.objects.filter(
                        periodic_verification=pv,
                        asset=asset,
                        status=WorkOrder.STATUS_DONE,
                    )
                    .order_by("-closed_at", "-id")
                    .first()
                )
                executed_on = (
                    latest_workorder.closed_at.date()
                    if latest_workorder is not None and latest_workorder.closed_at is not None
                    else pv.last_verification_date
                )
                if executed_on is not None or latest_workorder is not None:
                    AssetMaintenanceRuleState.objects.update_or_create(
                        asset=asset,
                        base_rule=rule,
                        defaults={
                            "last_execution_date": executed_on,
                            "last_work_order": latest_workorder,
                            "notes": "Storico inglobato dal precedente piano periodico.",
                        },
                    )

        if not pv.is_legacy:
            pv.is_legacy = True
            pv.save(update_fields=["is_legacy", "updated_at"])

    return {
        "ok": True,
        "reason": "",
        "message": "",
        "category": plan["category"],
        "threshold_days": plan["threshold_days"],
        "template": template,
        "rule": rules[0],
        "rules": rules,
        "created_template": created_template,
        "created_rule": bool(created_rules),
        "created_rules": created_rules,
    }
