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
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    PeriodicVerification,
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

    category_ids = {asset.asset_category_id for asset in assets}
    if None in category_ids or len(category_ids) > 1:
        return {
            "ok": False,
            "reason": "multi_category",
            "message": "Gli asset del piano devono appartenere a un'unica categoria asset.",
        }

    category_id = next(iter(category_ids))
    category = AssetCategory.objects.filter(pk=category_id).first()
    if category is None:
        return {"ok": False, "reason": "no_category", "message": "Categoria asset non trovata."}

    threshold_days = months_to_days(pv.frequency_months)
    template_label = (pv.name or "Manutenzione periodica")[:120]

    existing_template = (
        MaintenanceInterventionTemplate.objects.filter(
            label=template_label, asset_category_id=category_id
        ).first()
        or MaintenanceInterventionTemplate.objects.filter(
            label=template_label, asset_category__isnull=True
        ).first()
    )
    existing_rule = None
    if existing_template:
        existing_rule = MaintenanceRule.objects.filter(
            intervention_template=existing_template,
            asset_category_id=category_id,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
        ).first()

    return {
        "ok": True,
        "reason": "",
        "message": "",
        "category": category,
        "category_id": category_id,
        "threshold_days": threshold_days,
        "template_label": template_label,
        "existing_template": existing_template,
        "existing_rule": existing_rule,
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
                asset_category_id=plan["category_id"],
                is_active=True,
            )
            created_template = True

        rule = plan["existing_rule"]
        created_rule = False
        if not rule:
            rule = MaintenanceRule.objects.create(
                intervention_template=template,
                asset_category_id=plan["category_id"],
                threshold_type=MaintenanceRule.THRESHOLD_DAYS,
                threshold_value=plan["threshold_days"],
                warning_days=max(7, plan["threshold_days"] // 10),
                is_active=True,
            )
            created_rule = True

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
        "rule": rule,
        "created_template": created_template,
        "created_rule": created_rule,
    }
