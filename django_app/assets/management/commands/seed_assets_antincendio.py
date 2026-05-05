from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction

from assets.models import (
    Asset,
    AssetCategory,
    AssetCategoryField,
    AssetDetailField,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
)


ANTINCENDIO_CODE = "antincendio"
PROVA_ANTINCENDIO_CODE = "prova-antincendio"


@dataclass
class SeedStats:
    category_created: int = 0
    category_updated: int = 0
    fields_created: int = 0
    fields_updated: int = 0
    template_created: int = 0
    template_updated: int = 0
    rule_created: int = 0
    rule_updated: int = 0

    @property
    def total(self) -> int:
        return (
            self.category_created
            + self.category_updated
            + self.fields_created
            + self.fields_updated
            + self.template_created
            + self.template_updated
            + self.rule_created
            + self.rule_updated
        )


class Command(BaseCommand):
    help = "Seed idempotente della categoria Antincendio e del preset manutenzione Prova antincendio."

    def handle(self, *args, **options):
        with transaction.atomic():
            stats = SeedStats()
            category, created, updated = self._seed_category()
            stats.category_created += int(created)
            stats.category_updated += int(updated)

            field_stats = self._seed_category_fields(category)
            stats.fields_created += field_stats[0]
            stats.fields_updated += field_stats[1]

            template, created, updated = self._seed_template(category)
            stats.template_created += int(created)
            stats.template_updated += int(updated)

            _rule, created, updated = self._seed_rule(category, template)
            stats.rule_created += int(created)
            stats.rule_updated += int(updated)

        self.stdout.write(f"Categoria Antincendio: {self._status(stats.category_created, stats.category_updated)}")
        self.stdout.write(f"Campi dinamici: {stats.fields_created} creati, {stats.fields_updated} aggiornati")
        self.stdout.write(f"Template Prova antincendio: {self._status(stats.template_created, stats.template_updated)}")
        self.stdout.write(f"Regola Prova antincendio: {self._status(stats.rule_created, stats.rule_updated)}")
        self.stdout.write(self.style.SUCCESS(f"Totale oggetti coinvolti: {stats.total}"))

    def _seed_category(self):
        defaults = {
            "label": "Antincendio",
            "base_asset_type": Asset.TYPE_OTHER,
            "description": "Asset e dispositivi legati alla prevenzione e gestione antincendio.",
            "sort_order": 80,
            "is_active": True,
        }
        category, created = AssetCategory.objects.get_or_create(code=ANTINCENDIO_CODE, defaults=defaults)
        if created:
            return category, True, False

        updates = []
        if not category.label:
            category.label = defaults["label"]
            updates.append("label")
        if category.base_asset_type != Asset.TYPE_OTHER:
            category.base_asset_type = Asset.TYPE_OTHER
            updates.append("base_asset_type")
        if not category.description:
            category.description = defaults["description"]
            updates.append("description")
        if category.sort_order == 100:
            category.sort_order = defaults["sort_order"]
            updates.append("sort_order")
        if not category.is_active:
            category.is_active = True
            updates.append("is_active")
        if updates:
            category.save(update_fields=updates)
        return category, False, bool(updates)

    def _seed_category_fields(self, category: AssetCategory) -> tuple[int, int]:
        rows = [
            {
                "code": "tipo_presidio",
                "label": "Tipo presidio",
                "field_type": AssetCategoryField.TYPE_TEXT,
                "placeholder": "Estintore, Pompa antincendio, Idrante, Altro",
                "sort_order": 10,
            },
            {
                "code": "ubicazione",
                "label": "Ubicazione",
                "field_type": AssetCategoryField.TYPE_TEXT,
                "sort_order": 20,
            },
            {
                "code": "matricola",
                "label": "Matricola",
                "field_type": AssetCategoryField.TYPE_TEXT,
                "sort_order": 30,
            },
            {
                "code": "data_ultima_verifica",
                "label": "Data ultima verifica",
                "field_type": AssetCategoryField.TYPE_DATE,
                "sort_order": 40,
            },
            {
                "code": "data_prossima_verifica",
                "label": "Data prossima verifica",
                "field_type": AssetCategoryField.TYPE_DATE,
                "sort_order": 50,
            },
            {
                "code": "note_sicurezza",
                "label": "Note sicurezza",
                "field_type": AssetCategoryField.TYPE_TEXTAREA,
                "sort_order": 60,
            },
        ]
        created_count = 0
        updated_count = 0
        for row in rows:
            field, created = AssetCategoryField.objects.get_or_create(
                code=row["code"],
                defaults={
                    "category": category,
                    "label": row["label"],
                    "field_type": row["field_type"],
                    "detail_section": AssetDetailField.SECTION_SPECS,
                    "placeholder": row.get("placeholder", ""),
                    "sort_order": row["sort_order"],
                    "is_required": False,
                    "show_in_form": True,
                    "show_in_detail": True,
                    "is_active": True,
                },
            )
            if created:
                created_count += 1
                continue

            updates = []
            expected = {
                "category": category,
                "label": row["label"],
                "field_type": row["field_type"],
                "placeholder": row.get("placeholder", ""),
                "sort_order": row["sort_order"],
                "is_required": False,
                "show_in_form": True,
                "show_in_detail": True,
                "is_active": True,
            }
            for attr, value in expected.items():
                if getattr(field, attr) != value:
                    setattr(field, attr, value)
                    updates.append(attr)
            if updates:
                field.save(update_fields=updates)
                updated_count += 1
        return created_count, updated_count

    def _seed_template(self, category: AssetCategory):
        defaults = {
            "label": "Prova antincendio",
            "description": "Verifica/prova periodica dei presidi e impianti antincendio.",
            "asset_category": category,
            "sort_order": 80,
            "is_active": True,
        }
        template, created = MaintenanceInterventionTemplate.objects.get_or_create(
            code=PROVA_ANTINCENDIO_CODE,
            defaults=defaults,
        )
        if created:
            return template, True, False

        updates = []
        for attr, value in defaults.items():
            if getattr(template, attr) != value:
                setattr(template, attr, value)
                updates.append(attr)
        if updates:
            template.save(update_fields=updates)
        return template, False, bool(updates)

    def _seed_rule(self, category: AssetCategory, template: MaintenanceInterventionTemplate):
        threshold_type = getattr(MaintenanceRule, "THRESHOLD_DAYS", "DAYS")
        defaults = {
            "threshold_type": threshold_type,
            "threshold_value": 180,
            "warning_days": 30,
            "sort_order": 80,
            "is_active": True,
            "notes": "Frequenza configurabile secondo piano manutentivo interno.",
        }
        rule, created = MaintenanceRule.objects.get_or_create(
            asset_category=category,
            intervention_template=template,
            defaults=defaults,
        )
        if created:
            return rule, True, False

        updates = []
        for attr, value in defaults.items():
            if getattr(rule, attr) != value:
                setattr(rule, attr, value)
                updates.append(attr)
        if updates:
            rule.save(update_fields=updates)
        return rule, False, bool(updates)

    def _status(self, created: int, updated: int) -> str:
        if created:
            return "creata"
        if updated:
            return "aggiornata"
        return "gia presente"
