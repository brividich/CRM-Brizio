"""Genera automaticamente WorkOrder periodici da MaintenanceRule attive.

Schedulare come task Windows quotidiano (suggerito alle 06:00, prima di send_maintenance_reminders):

    python manage.py generate_scheduled_workorders

Logica per ogni (asset, rule) — l'ultima esecuzione si legge da AssetMaintenanceRuleState,
la stessa fonte dello scadenzario (qualunque sia l'origine dell'OdL che l'ha registrata):
  - threshold_type=DAYS: last_execution_date + threshold_value giorni.
  - threshold_type=HOURS/KM/CYCLES: usa il valore corrente di AssetMeter e lo confronta
    con il valore al momento dell'ultima esecuzione. Se la differenza >= threshold_value, genera.
  - Controlla override: se l'asset ha un MaintenanceRuleAssetOverride con is_disabled=True, salta.
  - Se esiste già un WO OPEN per quella coppia (asset, rule), salta (nessun duplicato).
  - Se non trovato (mai eseguito): genera subito (next_due = today, oppure per contatori: 0).

Titolo OdL: "{template.label} — {asset.asset_tag}"
Il command è idempotente: esecuzioni multiple nello stesso giorno non generano duplicati.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from assets.maintenance import copy_template_checklist_to_workorder, meter_schedule_payload
from assets.models import (
    Asset,
    AssetMaintenanceRuleState,
    AssetMeter,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    WorkOrder,
)

_METER_TYPE_MAP = {
    MaintenanceRule.THRESHOLD_HOURS: AssetMeter.METER_HOURS,
    MaintenanceRule.THRESHOLD_KM: AssetMeter.METER_KM,
    MaintenanceRule.THRESHOLD_CYCLES: AssetMeter.METER_CYCLES,
}


class Command(BaseCommand):
    help = "Genera WorkOrder periodici per le MaintenanceRule attive in scadenza."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Non crea nulla, stampa solo cosa verrebbe creato.",
        )
        parser.add_argument(
            "--category",
            type=int,
            default=0,
            help="Limita a una singola AssetCategory (ID). 0 = tutte.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Numero massimo di OdL da creare (0 = nessun limite).",
        )

    def handle(self, *args, **options):
        dry_run: bool = bool(options.get("dry_run"))
        category_id: int = int(options.get("category") or 0)
        limit: int = int(options.get("limit") or 0)

        today = timezone.localdate()

        rules_qs = (
            MaintenanceRule.objects
            .filter(is_active=True)
            .select_related("intervention_template", "asset_category")
        )
        if category_id:
            rules_qs = rules_qs.filter(asset_category_id=category_id)

        rules = list(rules_qs)
        if not rules:
            self.stdout.write("Nessuna MaintenanceRule attiva trovata.")
            return

        # Precarica tutti gli override disabilitati per evitare N+1
        disabled_pairs: set[tuple[int, int]] = set(
            MaintenanceRuleAssetOverride.objects
            .filter(is_disabled=True)
            .values_list("asset_id", "base_rule_id")
        )

        # Precarica tutti gli OdL OPEN periodici per evitare query per ogni coppia
        open_periodic_pairs: set[tuple[int, int]] = set(
            WorkOrder.objects
            .filter(status=WorkOrder.STATUS_OPEN, origin=WorkOrder.ORIGIN_PERIODIC)
            .exclude(maintenance_rule_id=None)
            .values_list("asset_id", "maintenance_rule_id")
        )

        # Precarica contatori (asset_id, meter_type) -> current_value
        meter_map: dict[tuple[int, str], float] = {
            (m["asset_id"], m["meter_type"]): float(m["current_value"])
            for m in AssetMeter.objects.values("asset_id", "meter_type", "current_value")
        }

        # Ultima esecuzione per coppia (asset, regola): STESSA fonte dello scadenzario.
        # Prima il generatore interrogava solo gli OdL con origin=PERIODIC chiusi, quindi non
        # vedeva né le esecuzioni registrate dallo scadenzario (che nascono MANUAL) né lo
        # storico registrato senza OdL — e riapriva una manutenzione appena fatta.
        state_map: dict[tuple[int, int], AssetMaintenanceRuleState] = {
            (state.asset_id, state.base_rule_id): state
            for state in AssetMaintenanceRuleState.objects.select_related("last_work_order")
        }

        created = 0
        skipped_disabled = 0
        skipped_open = 0
        skipped_not_due = 0
        skipped_no_meter = 0

        for rule in rules:
            assets = list(
                Asset.objects
                .filter(asset_category_id=rule.asset_category_id, status=Asset.STATUS_IN_USE)
                .only("id", "asset_tag", "name")
            )

            for asset in assets:
                if limit and created >= limit:
                    break

                if (asset.id, rule.id) in disabled_pairs:
                    skipped_disabled += 1
                    continue

                override = _get_override(asset.id, rule.id)
                effective_threshold_type = rule.threshold_type
                effective_threshold_value = rule.threshold_value
                effective_template = rule.intervention_template
                if override:
                    if override.override_threshold_type:
                        effective_threshold_type = override.override_threshold_type
                    if override.override_threshold_value is not None:
                        effective_threshold_value = override.override_threshold_value
                    if override.override_intervention_template_id:
                        effective_template = override.override_intervention_template

                if (asset.id, rule.id) in open_periodic_pairs:
                    skipped_open += 1
                    continue

                # --- Valutazione scadenza ---
                due = False
                due_reason = ""

                state = state_map.get((asset.id, rule.id))

                if effective_threshold_type == MaintenanceRule.THRESHOLD_DAYS:
                    last_execution_date = state.last_execution_date if state else None
                    if last_execution_date:
                        next_due = last_execution_date + timedelta(days=effective_threshold_value)
                    else:
                        next_due = today
                    horizon = today + timedelta(days=rule.warning_days)
                    if next_due <= horizon:
                        due = True
                        due_reason = f"scadenza {next_due:%d-%m-%Y}"
                    else:
                        skipped_not_due += 1
                        continue

                elif effective_threshold_type in _METER_TYPE_MAP:
                    meter_type_key = _METER_TYPE_MAP[effective_threshold_type]
                    current_val = meter_map.get((asset.id, meter_type_key))
                    if current_val is None:
                        skipped_no_meter += 1
                        continue
                    # Valore del contatore all'ultima esecuzione, dallo stesso stato che legge
                    # lo scadenzario: anche qui l'origine dell'OdL non deve contare.
                    last_wo = state.last_work_order if state else None
                    base_val = (
                        float(last_wo.meter_value_at_close)
                        if last_wo is not None and last_wo.meter_value_at_close is not None
                        else 0.0
                    )
                    payload = meter_schedule_payload(
                        current_value=current_val,
                        base_value=base_val,
                        threshold_value=effective_threshold_value,
                        warning_units=rule.warning_days,
                        unit_label=meter_type_key,
                    )
                    if payload["due"]:
                        due = True
                        remaining = payload["remaining"] or 0.0
                        due_reason = f"contatore {meter_type_key}={current_val:.0f} (restano {remaining:.0f}/{effective_threshold_value})"
                    else:
                        skipped_not_due += 1
                        continue
                else:
                    # threshold_type non gestito
                    skipped_disabled += 1
                    continue

                if not due:
                    continue

                # --- Genera OdL ---
                title = f"{effective_template.label} — {asset.asset_tag}"
                if dry_run:
                    self.stdout.write(
                        f"[DRY] asset={asset.asset_tag} rule={rule.id} "
                        f"tipo={effective_threshold_type} {due_reason} titolo={title!r}"
                    )
                    created += 1
                    continue

                with transaction.atomic():
                    wo = WorkOrder(
                        asset=asset,
                        maintenance_rule=rule,
                        origin=WorkOrder.ORIGIN_PERIODIC,
                        kind=WorkOrder.KIND_PREVENTIVE,
                        status=WorkOrder.STATUS_OPEN,
                        title=title,
                        description=getattr(effective_template, "description", "") or "",
                        reference_batch=f"auto-{today:%Y%m%d}",
                    )
                    wo.save()
                    steps_copied = copy_template_checklist_to_workorder(
                        wo, template_id=getattr(effective_template, "pk", None)
                    )
                    open_periodic_pairs.add((asset.id, rule.id))
                    created += 1
                    checklist_suffix = f" (+{steps_copied} step checklist)" if steps_copied else ""
                    self.stdout.write(f"  Creato WO #{wo.pk}: {title}{checklist_suffix}")

            if limit and created >= limit:
                break

        summary = (
            f"Creati={created} "
            f"GiaAperti={skipped_open} "
            f"NonInScadenza={skipped_not_due} "
            f"Disabilitati/Override={skipped_disabled} "
            f"SenzaContatore={skipped_no_meter}"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING(f"[DRY-RUN] {summary}"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))


def _get_override(asset_id: int, rule_id: int) -> MaintenanceRuleAssetOverride | None:
    try:
        return MaintenanceRuleAssetOverride.objects.select_related(
            "override_intervention_template"
        ).get(asset_id=asset_id, base_rule_id=rule_id)
    except MaintenanceRuleAssetOverride.DoesNotExist:
        return None
