"""Migra il vecchio motore manutenzioni nel dominio Piano/Applicazione/Occorrenza.

Cosa converte:

``MaintenanceRule`` (soglia a GIORNI)
    -> ``MaintenancePlanAssignment``. Ambito CATEGORIA -> applicazione sulla
    categoria; ambito "solo asset selezionati" -> un ``AssetGroup`` che raccoglie
    quegli asset (e' esattamente il concetto di gruppo operativo) + applicazione
    sul gruppo.

``MaintenanceRuleAssetOverride``
    -> applicazione sull'asset singolo (periodicita' personalizzata) oppure
    esclusione dell'asset dal piano.

``AssetMaintenanceRuleState``
    -> occorrenza gia' eseguita, cosi' l'ultima esecuzione resta nota al nuovo
    motore senza tenere in vita una seconda fonte di verita'.

``AssetAdministrativeDeadline``
    -> piano di tipo amministrativo + applicazione sull'asset + occorrenza aperta
    alla scadenza corrente. Le esecuzioni storiche diventano occorrenze eseguite.

Cosa **non** converte, e lo dichiara:

- le regole a soglia ORE/KM/CICLI: i contatori escono dal flusso manutentivo;
- le verifiche periodiche mai assorbite (``is_legacy=False``): vengono elencate.

Sempre disponibile ``--dry-run``. Il comando e' ripetibile: cerca prima se
l'oggetto corrispondente esiste gia' e in tal caso non lo duplica.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from assets.models import (
    AssetAdministrativeDeadline,
    AssetGroup,
    AssetGroupMembership,
    AssetMaintenanceRuleState,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    PeriodicVerification,
)


def _unique_code(model, base: str, fallback: str) -> str:
    candidate = (slugify(base)[:70] or fallback).strip("-")
    if not model.objects.filter(code=candidate).exists():
        return candidate
    suffix = 2
    while model.objects.filter(code=f"{candidate}-{suffix}").exists():
        suffix += 1
    return f"{candidate}-{suffix}"


class Command(BaseCommand):
    help = "Converte regole, override, stati e scadenze amministrative nel nuovo dominio manutenzione."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Non scrive nulla, riporta solo i conteggi.")
        parser.add_argument("--skip-rules", action="store_true", help="Non migrare regole e override.")
        parser.add_argument("--skip-history", action="store_true", help="Non migrare l'ultima esecuzione registrata.")
        parser.add_argument(
            "--skip-deadlines",
            action="store_true",
            help="Non migrare le scadenze amministrative.",
        )

    def handle(self, *args, **options):
        self.dry_run = bool(options.get("dry_run"))
        self.stats = {
            "assignments_created": 0,
            "groups_created": 0,
            "overrides_migrated": 0,
            "exclusions_migrated": 0,
            "history_occurrences": 0,
            "deadline_plans": 0,
            "deadline_assignments": 0,
            "deadline_occurrences": 0,
            "skipped_meter_rules": 0,
            "skipped_existing": 0,
        }

        if not options.get("skip_rules"):
            self._migrate_rules()
        if not options.get("skip_history"):
            self._migrate_history()
        if not options.get("skip_deadlines"):
            self._migrate_administrative_deadlines()

        self._report_unconverted()

        prefix = "[DRY-RUN] " if self.dry_run else ""
        self.stdout.write("")
        for key, value in self.stats.items():
            self.stdout.write(f"{prefix}{key}: {value}")
        style = self.style.WARNING if self.dry_run else self.style.SUCCESS
        self.stdout.write(style(f"{prefix}Migrazione completata."))

    # -- regole ------------------------------------------------------------
    def _migrate_rules(self):
        rules = (
            MaintenanceRule.objects.select_related("intervention_template", "asset_category", "supplier", "assigned_to")
            .prefetch_related("assets")
            .order_by("id")
        )
        for rule in rules:
            if rule.threshold_type != MaintenanceRule.THRESHOLD_DAYS:
                self.stats["skipped_meter_rules"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  Regola #{rule.id} ({rule}) a soglia {rule.threshold_type}: NON migrata, "
                        "i contatori escono dal flusso manutentivo."
                    )
                )
                continue
            if MaintenancePlanAssignment.objects.filter(legacy_rule=rule).exists():
                self.stats["skipped_existing"] += 1
                continue

            plan = rule.intervention_template
            common = {
                "plan": plan,
                "frequency": MaintenancePlanAssignment.FREQ_DAYS,
                "interval": max(1, int(rule.threshold_value or 1)),
                "warning_days": int(rule.warning_days or 0),
                "first_due_date": rule.first_due_date,
                "execution_mode": rule.execution_mode,
                "supplier": rule.supplier,
                "assigned_to": rule.assigned_to,
                "auto_generate": rule.auto_generate_workorders,
                "is_active": rule.is_active,
                "notes": rule.notes,
                "legacy_rule": rule,
            }

            if rule.scope_type == MaintenanceRule.SCOPE_CATEGORY:
                self._create_assignment(
                    target_type=MaintenancePlanAssignment.TARGET_CATEGORY,
                    asset_category=rule.asset_category,
                    **common,
                )
            else:
                assets = list(rule.assets.all())
                if not assets:
                    continue
                group = self._group_for_rule(rule, assets)
                self._create_assignment(
                    target_type=MaintenancePlanAssignment.TARGET_GROUP,
                    asset_group=group,
                    **common,
                )

        self._migrate_overrides()

    def _group_for_rule(self, rule: MaintenanceRule, assets: list) -> AssetGroup | None:
        code = f"regola-{rule.id}"
        label = f"{rule.intervention_template.label} — asset selezionati"[:120]
        if self.dry_run:
            self.stats["groups_created"] += 1
            self.stdout.write(f"  [DRY] gruppo {code!r} con {len(assets)} asset")
            return None
        group, created = AssetGroup.objects.get_or_create(
            code=code,
            defaults={
                "label": label,
                "description": f"Gruppo creato dalla migrazione della regola #{rule.id}.",
                "is_active": True,
            },
        )
        if created:
            self.stats["groups_created"] += 1
        for asset in assets:
            AssetGroupMembership.objects.get_or_create(group=group, asset=asset)
        return group

    def _create_assignment(self, **kwargs):
        if self.dry_run:
            self.stats["assignments_created"] += 1
            plan = kwargs.get("plan")
            self.stdout.write(
                f"  [DRY] applicazione {getattr(plan, 'label', '?')} -> {kwargs.get('target_type')} "
                f"ogni {kwargs.get('interval')} giorni"
            )
            return None
        assignment = MaintenancePlanAssignment.objects.create(**kwargs)
        self.stats["assignments_created"] += 1
        return assignment

    def _migrate_overrides(self):
        overrides = MaintenanceRuleAssetOverride.objects.select_related(
            "asset", "base_rule", "base_rule__intervention_template", "override_intervention_template"
        ).order_by("id")
        for override in overrides:
            rule = override.base_rule
            if rule.threshold_type != MaintenanceRule.THRESHOLD_DAYS:
                continue
            if not override.has_effective_override:
                continue
            plan = rule.intervention_template
            if MaintenancePlanAssignment.objects.filter(
                plan=plan, asset=override.asset, target_type=MaintenancePlanAssignment.TARGET_ASSET
            ).exists():
                self.stats["skipped_existing"] += 1
                continue

            if override.is_disabled:
                self.stats["exclusions_migrated"] += 1
                if self.dry_run:
                    self.stdout.write(f"  [DRY] esclusione {override.asset} dal piano {plan.label}")
                    continue
                MaintenancePlanAssignment.objects.create(
                    plan=plan,
                    target_type=MaintenancePlanAssignment.TARGET_ASSET,
                    asset=override.asset,
                    is_excluded=True,
                    frequency=MaintenancePlanAssignment.FREQ_DAYS,
                    interval=max(1, int(rule.threshold_value or 1)),
                    warning_days=int(rule.warning_days or 0),
                    notes=override.notes or "Esclusione migrata dal vecchio override.",
                    legacy_rule=rule,
                )
                continue

            interval = int(
                override.override_threshold_value
                if override.override_threshold_value is not None
                else rule.threshold_value or 1
            )
            self.stats["overrides_migrated"] += 1
            if self.dry_run:
                self.stdout.write(
                    f"  [DRY] personalizzazione {override.asset} su {plan.label}: ogni {interval} giorni"
                )
                continue
            MaintenancePlanAssignment.objects.create(
                plan=override.override_intervention_template or plan,
                target_type=MaintenancePlanAssignment.TARGET_ASSET,
                asset=override.asset,
                frequency=MaintenancePlanAssignment.FREQ_DAYS,
                interval=max(1, interval),
                warning_days=int(rule.warning_days or 0),
                first_due_date=rule.first_due_date,
                execution_mode=rule.execution_mode,
                supplier=rule.supplier,
                assigned_to=rule.assigned_to,
                notes=override.notes,
                legacy_rule=rule,
            )

    # -- storico -----------------------------------------------------------
    def _migrate_history(self):
        states = (
            AssetMaintenanceRuleState.objects.select_related(
                "asset", "base_rule", "base_rule__intervention_template", "last_work_order"
            )
            .exclude(last_execution_date=None)
            .order_by("id")
        )
        for state in states:
            plan = state.base_rule.intervention_template
            executed_on = state.last_execution_date
            if MaintenanceOccurrence.objects.filter(
                plan=plan, asset=state.asset, due_date=executed_on
            ).exists():
                self.stats["skipped_existing"] += 1
                continue
            self.stats["history_occurrences"] += 1
            if self.dry_run:
                continue
            MaintenanceOccurrence.objects.create(
                plan=plan,
                asset=state.asset,
                due_date=executed_on,
                warning_days=int(state.base_rule.warning_days or 0),
                status=MaintenanceOccurrence.STATUS_DONE,
                completed_on=executed_on,
                work_order=state.last_work_order,
                completion_notes=(state.notes or "Ultima esecuzione migrata dal vecchio motore.")[:2000],
                source=MaintenanceOccurrence.SOURCE_MIGRATION,
            )

    # -- scadenze amministrative -------------------------------------------
    def _migrate_administrative_deadlines(self):
        deadlines = (
            AssetAdministrativeDeadline.objects.select_related("asset")
            .prefetch_related("completions")
            .filter(is_active=True)
            .order_by("id")
        )
        plans_by_title: dict[str, MaintenanceInterventionTemplate] = {}

        for deadline in deadlines:
            title = (deadline.title or "Scadenza amministrativa").strip()[:120]
            plan = plans_by_title.get(title.lower())
            if plan is None:
                plan = MaintenanceInterventionTemplate.objects.filter(
                    label=title, maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
                ).first()
            if plan is None:
                self.stats["deadline_plans"] += 1
                if not self.dry_run:
                    plan = MaintenanceInterventionTemplate.objects.create(
                        code=_unique_code(MaintenanceInterventionTemplate, title, f"scadenza-{deadline.id}"),
                        label=title,
                        maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
                        description=deadline.notes or "",
                        attachment_required=True,
                        schedule_anchor="FIXED_CALENDAR",
                    )
            if plan is not None:
                plans_by_title[title.lower()] = plan
            if self.dry_run or plan is None:
                self.stats["deadline_assignments"] += 1
                self.stats["deadline_occurrences"] += 1
                continue

            assignment = MaintenancePlanAssignment.objects.filter(
                plan=plan, asset=deadline.asset, target_type=MaintenancePlanAssignment.TARGET_ASSET
            ).first()
            if assignment is None:
                # Il vecchio modello non registrava la periodicita': si mette il
                # default annuale ma la generazione automatica resta spenta finche'
                # un responsabile non conferma. Inventarla in silenzio produrrebbe
                # scadenze finte.
                assignment = MaintenancePlanAssignment.objects.create(
                    plan=plan,
                    target_type=MaintenancePlanAssignment.TARGET_ASSET,
                    asset=deadline.asset,
                    frequency=MaintenancePlanAssignment.FREQ_YEARS,
                    interval=1,
                    warning_days=int(deadline.warning_days or 30),
                    schedule_anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
                    first_due_date=deadline.due_date,
                    auto_generate=False,
                    notes="Periodicita' da confermare: il vecchio modello di scadenza non la registrava.",
                )
                self.stats["deadline_assignments"] += 1

            for completion in deadline.completions.all():
                if MaintenanceOccurrence.objects.filter(
                    plan=plan, asset=deadline.asset, due_date=completion.completed_on
                ).exists():
                    continue
                MaintenanceOccurrence.objects.create(
                    plan=plan,
                    assignment=assignment,
                    asset=deadline.asset,
                    due_date=completion.completed_on,
                    warning_days=int(deadline.warning_days or 30),
                    schedule_anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
                    status=MaintenanceOccurrence.STATUS_DONE,
                    completed_on=completion.completed_on,
                    completed_by=completion.completed_by,
                    completion_notes=completion.notes or "",
                    source=MaintenanceOccurrence.SOURCE_MIGRATION,
                )

            if not MaintenanceOccurrence.objects.filter(
                plan=plan, asset=deadline.asset, due_date=deadline.due_date
            ).exists():
                MaintenanceOccurrence.objects.create(
                    plan=plan,
                    assignment=assignment,
                    asset=deadline.asset,
                    due_date=deadline.due_date,
                    warning_days=int(deadline.warning_days or 30),
                    schedule_anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
                    source=MaintenanceOccurrence.SOURCE_MIGRATION,
                )
                self.stats["deadline_occurrences"] += 1

    # -- residui -----------------------------------------------------------
    def _report_unconverted(self):
        pending = PeriodicVerification.objects.filter(is_active=True, is_legacy=False)
        count = pending.count()
        if not count:
            return
        self.stdout.write(
            self.style.WARNING(
                f"\n{count} verifiche periodiche non ancora assorbite in un piano "
                "(is_legacy=False): vanno convertite a mano o ri-eseguendo l'ingest."
            )
        )
        for verification in pending.only("id", "name")[:20]:
            self.stdout.write(f"  - #{verification.id} {verification.name}")
