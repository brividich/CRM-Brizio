"""Script di migrazione dati: da PeriodicVerification a MaintenanceRule.

Per ogni PeriodicVerification attiva non ancora migrata, il command suggerisce
(o crea) un MaintenanceInterventionTemplate + MaintenanceRule equivalente, poi
marca la PeriodicVerification come is_legacy=True.

Eseguire sempre --dry-run prima di --apply.

Uso:
    python manage.py migrate_periodic_to_rules --dry-run
    python manage.py migrate_periodic_to_rules --dry-run --pv-id 42
    python manage.py migrate_periodic_to_rules --apply --pv-id 42
    python manage.py migrate_periodic_to_rules --only-legacy

Strategia:
  - frequency_months viene convertito in giorni (×30, minimo 1).
  - Tutti gli asset della PeriodicVerification devono appartenere alla stessa
    AssetCategory; se ci sono categorie miste o assenti, il piano viene saltato.
  - Il label del MaintenanceInterventionTemplate è derivato dal nome del piano.
    Se esiste già un template con lo stesso label e categoria, viene riusato.
  - Se esiste già una MaintenanceRule per (template, categoria, DAYS), viene
    riusata senza duplicati.
  - Con --apply: crea template/regola se necessario e imposta is_legacy=True.
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from assets.models import (
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    PeriodicVerification,
)


def _months_to_days(months: int) -> int:
    return max(1, round(months * 30))


def _make_code(label: str) -> str:
    base = slugify(label)[:70] or "manutenzione"
    base = re.sub(r"-+", "-", base).strip("-")
    return base


class Command(BaseCommand):
    help = "Migra PeriodicVerification verso MaintenanceRule e marca is_legacy=True."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Non modifica nulla, mostra solo il piano di migrazione.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Applica la migrazione (crea template/regole + imposta is_legacy=True).",
        )
        parser.add_argument(
            "--pv-id",
            type=int,
            default=0,
            help="Limita a una singola PeriodicVerification (ID). 0 = tutte.",
        )
        parser.add_argument(
            "--only-legacy",
            action="store_true",
            help="Mostra solo le PeriodicVerification già migrate (is_legacy=True).",
        )

    def handle(self, *args, **options):
        dry_run: bool = bool(options.get("dry_run"))
        apply: bool = bool(options.get("apply"))
        pv_id: int = int(options.get("pv_id") or 0)
        only_legacy: bool = bool(options.get("only_legacy"))

        if not dry_run and not apply and not only_legacy:
            raise CommandError(
                "Specifica --dry-run, --apply o --only-legacy.\n"
                "Esempio: python manage.py migrate_periodic_to_rules --dry-run"
            )
        if dry_run and apply:
            raise CommandError("--dry-run e --apply sono mutuamente esclusivi.")

        today = timezone.localdate()

        # Modalità sola lettura: mostra piani già migrati
        if only_legacy:
            qs = PeriodicVerification.objects.filter(is_legacy=True).order_by("name", "id")
            if pv_id:
                qs = qs.filter(pk=pv_id)
            qs = qs.prefetch_related("assets")
            count = qs.count()
            self.stdout.write(f"PeriodicVerification con is_legacy=True: {count}")
            for pv in qs:
                asset_tags = ", ".join(
                    a.asset_tag for a in pv.assets.all().order_by("asset_tag")[:10]
                ) or "-"
                self.stdout.write(f"  [{pv.id}] {pv.name!r}  asset={asset_tags}")
            return

        qs = (
            PeriodicVerification.objects
            .filter(is_active=True, is_legacy=False)
            .prefetch_related("assets__asset_category")
            .order_by("name", "id")
        )
        if pv_id:
            qs = qs.filter(pk=pv_id)

        pvs = list(qs)
        if not pvs:
            self.stdout.write("Nessuna PeriodicVerification attiva non-legacy trovata.")
            return

        self.stdout.write(
            f"{'[DRY-RUN] ' if dry_run else ''}Analisi di {len(pvs)} PeriodicVerification..."
        )
        self.stdout.write(f"Data di riferimento: {today:%d/%m/%Y}\n")

        results = {
            "migrated": 0,
            "skipped_no_asset": 0,
            "skipped_multi_category": 0,
            "template_created": 0,
            "template_reused": 0,
            "rule_created": 0,
            "rule_reused": 0,
        }

        for pv in pvs:
            assets = list(pv.assets.all())
            if not assets:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [{pv.id}] {pv.name!r} — nessun asset collegato. Saltata."
                    )
                )
                results["skipped_no_asset"] += 1
                continue

            # Categoria unica richiesta
            category_ids: set[int | None] = {a.asset_category_id for a in assets}
            if None in category_ids or len(category_ids) > 1:
                cat_labels = []
                for a in assets[:5]:
                    label = a.asset_category.label if a.asset_category_id else "—nessuna—"
                    cat_labels.append(f"{a.asset_tag}({label})")
                self.stdout.write(
                    self.style.WARNING(
                        f"  [{pv.id}] {pv.name!r} — categorie miste/assenti: "
                        f"{', '.join(cat_labels)}. Saltata."
                    )
                )
                results["skipped_multi_category"] += 1
                continue

            category_id: int = next(iter(category_ids))  # type: ignore[assignment]
            category = AssetCategory.objects.filter(pk=category_id).first()
            if category is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [{pv.id}] {pv.name!r} — categoria {category_id} non trovata. Saltata."
                    )
                )
                results["skipped_multi_category"] += 1
                continue

            threshold_days = _months_to_days(pv.frequency_months)
            template_label = pv.name[:120]

            # Cerca template esistente per label + categoria (o globale)
            existing_template = (
                MaintenanceInterventionTemplate.objects
                .filter(label=template_label, asset_category_id=category_id)
                .first()
            ) or MaintenanceInterventionTemplate.objects.filter(
                label=template_label, asset_category__isnull=True
            ).first()

            if existing_template:
                template_action = f"RIUSA template [{existing_template.id}] {existing_template.label!r}"
                results["template_reused"] += 1
            else:
                results["template_created"] += 1
                template_action = f"CREA template label={template_label!r}"

            # Cerca regola esistente per (template, categoria, DAYS)
            rule_filter_template_id = existing_template.id if existing_template else None
            existing_rule = None
            if rule_filter_template_id:
                existing_rule = MaintenanceRule.objects.filter(
                    intervention_template_id=rule_filter_template_id,
                    asset_category_id=category_id,
                    threshold_type=MaintenanceRule.THRESHOLD_DAYS,
                ).first()

            if existing_rule:
                rule_action = (
                    f"RIUSA regola [{existing_rule.id}] "
                    f"{existing_rule.threshold_value}gg"
                )
                results["rule_reused"] += 1
            else:
                rule_action = (
                    f"CREA regola (categoria={category.label!r}, "
                    f"giorni={threshold_days})"
                )
                results["rule_created"] += 1

            asset_tags = ", ".join(a.asset_tag for a in assets[:6])
            self.stdout.write(
                f"  [{pv.id}] {pv.name!r}  "
                f"freq={pv.frequency_months}mesi->{threshold_days}gg  "
                f"asset={asset_tags}"
            )
            self.stdout.write(f"         template: {template_action}")
            self.stdout.write(f"         regola:   {rule_action}")

            if apply:
                with transaction.atomic():
                    # Crea o recupera template
                    if not existing_template:
                        code = _make_code(template_label)
                        # Gestisci collisioni di slug
                        if MaintenanceInterventionTemplate.objects.filter(code=code).exists():
                            code = f"{code}-pv{pv.id}"
                        existing_template = MaintenanceInterventionTemplate.objects.create(
                            code=code,
                            label=template_label,
                            description=pv.notes or "",
                            asset_category_id=category_id,
                            is_active=True,
                        )

                    # Crea o recupera regola
                    if not existing_rule:
                        MaintenanceRule.objects.create(
                            intervention_template=existing_template,
                            asset_category_id=category_id,
                            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
                            threshold_value=threshold_days,
                            warning_days=max(7, threshold_days // 10),
                            is_active=True,
                        )

                    # Marca come legacy
                    pv.is_legacy = True
                    pv.save(update_fields=["is_legacy", "updated_at"])

                results["migrated"] += 1
                self.stdout.write(
                    self.style.SUCCESS(f"         -> Migrato.")
                )

        self.stdout.write("")
        self.stdout.write("=== Riepilogo ===")
        if dry_run:
            self.stdout.write(f"  Template da creare:  {results['template_created']}")
            self.stdout.write(f"  Template da riusare: {results['template_reused']}")
            self.stdout.write(f"  Regole da creare:    {results['rule_created']}")
            self.stdout.write(f"  Regole da riusare:   {results['rule_reused']}")
        else:
            self.stdout.write(f"  Migrati:             {results['migrated']}")
            self.stdout.write(f"  Template creati:     {results['template_created']}")
            self.stdout.write(f"  Template riusati:    {results['template_reused']}")
            self.stdout.write(f"  Regole create:       {results['rule_created']}")
            self.stdout.write(f"  Regole riusate:      {results['rule_reused']}")
        self.stdout.write(
            f"  Saltati (no asset/categoria): "
            f"{results['skipped_no_asset'] + results['skipped_multi_category']}"
        )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nDry-run completato. Usa --apply per applicare la migrazione."
                )
            )
        elif apply and results["migrated"] > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nMigrazione completata: {results['migrated']} piani migrati."
                )
            )
