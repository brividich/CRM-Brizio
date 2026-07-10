from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from anagrafica.models import Fornitore
from assets.models import MaintenanceRule


# Preset "regolamentari": causali tipicamente eseguite da ditte terze certificate
# (F-gas, emissioni, certificazioni, verifiche periodiche di legge). NON applicato di
# default: è solo un suggerimento richiamabile con --preset regulatory. Le causali sono
# quelle del catalogo import (Causali manutenzione.xlsx); il template ha code caus-<causale>.
PRESET_REGULATORY = [
    "A01", "A02", "A03", "A04", "A14", "A15", "A16", "A17", "A18", "A19",
    "28", "36",
]


def _template_code(causale: str) -> str:
    # Stessa convenzione di import_maintenance_causali/derive_collaudo_rules.
    return f"caus-{slugify(str(causale).strip())}"


class Command(BaseCommand):
    help = (
        "Riclassifica le regole di manutenzione come Interna/Esterna in base alla causale. "
        "Dry-run di default, idempotente. Le regole non toccate restano com'erano. "
        "Esempio: --external A16,35 --supplier \"Ditta X\" --commit"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--external",
            default="",
            help="Codici causale da marcare ESTERNA, separati da virgola (es. 'A16,35').",
        )
        parser.add_argument(
            "--preset",
            choices=["regulatory"],
            help="Usa un set predefinito di causali esterne al posto di --external (es. 'regulatory').",
        )
        parser.add_argument(
            "--supplier",
            default="",
            help="Fornitore (id o parte della ragione sociale) da assegnare alle regole esterne. Opzionale.",
        )
        parser.add_argument(
            "--rest-internal",
            action="store_true",
            help="Marca esplicitamente INTERNA tutte le altre regole (default: non tocca le altre).",
        )
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true", help="Simula senza scrivere.")
        mode.add_argument("--commit", action="store_true", help="Esegue in transaction.atomic().")

    def _resolve_supplier(self, raw: str) -> Fornitore | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            supplier = Fornitore.objects.filter(pk=int(raw)).first()
            if supplier is None:
                raise CommandError(f"Fornitore id={raw} non trovato.")
            return supplier
        matches = list(Fornitore.objects.filter(ragione_sociale__icontains=raw)[:5])
        if not matches:
            raise CommandError(f"Nessun fornitore corrisponde a '{raw}'.")
        if len(matches) > 1:
            names = ", ".join(f"[{m.id}] {m.ragione_sociale}" for m in matches)
            raise CommandError(f"Fornitore ambiguo '{raw}': {names}. Usa l'id.")
        return matches[0]

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        preset = options.get("preset")
        raw_external = _clean_list(options.get("external"))
        if preset == "regulatory":
            raw_external = list(PRESET_REGULATORY)
        if not raw_external:
            raise CommandError("Specifica --external <codici> oppure --preset regulatory.")

        supplier = self._resolve_supplier(options.get("supplier") or "")
        target_codes = {_template_code(c) for c in raw_external}

        external_rules = list(
            MaintenanceRule.objects.select_related("intervention_template", "asset_category", "supplier").filter(
                intervention_template__code__in=target_codes
            )
        )
        matched_codes = {r.intervention_template.code for r in external_rules}
        missing = sorted(target_codes - matched_codes)

        changed_ext = 0
        changed_int = 0
        report: list[str] = []

        def _apply():
            nonlocal changed_ext, changed_int
            for rule in external_rules:
                fields = []
                if rule.execution_mode != MaintenanceRule.MODE_EXTERNAL:
                    rule.execution_mode = MaintenanceRule.MODE_EXTERNAL
                    fields.append("execution_mode")
                if supplier is not None and rule.supplier_id != supplier.id:
                    rule.supplier = supplier
                    fields.append("supplier")
                if fields:
                    if not dry_run:
                        rule.save(update_fields=fields + ["updated_at"])
                    changed_ext += 1
                    sup = f" -> {supplier}" if supplier is not None else ""
                    report.append(f"  ESTERNA  {rule.intervention_template.label} ({rule.asset_category.label}){sup}")

            if options.get("rest_internal"):
                others = MaintenanceRule.objects.exclude(intervention_template__code__in=target_codes)
                for rule in others.select_related("intervention_template", "asset_category"):
                    fields = []
                    if rule.execution_mode != MaintenanceRule.MODE_INTERNAL:
                        rule.execution_mode = MaintenanceRule.MODE_INTERNAL
                        fields.append("execution_mode")
                    if rule.supplier_id is not None:
                        rule.supplier = None
                        fields.append("supplier")
                    if fields:
                        if not dry_run:
                            rule.save(update_fields=fields + ["updated_at"])
                        changed_int += 1

        if dry_run:
            _apply()
        else:
            with transaction.atomic():
                _apply()

        self.stdout.write(f"Modalità: {'DRY-RUN' if dry_run else 'COMMIT'}")
        self.stdout.write(f"Causali esterne richieste: {', '.join(raw_external)}")
        if supplier is not None:
            self.stdout.write(f"Fornitore assegnato: [{supplier.id}] {supplier.ragione_sociale}")
        self.stdout.write(
            f"Regole marcate ESTERNA: {changed_ext}"
            + (f" · riportate INTERNA: {changed_int}" if options.get("rest_internal") else "")
        )
        for line in report:
            self.stdout.write(line)
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"Nessuna regola per {len(missing)} causali (nessuna macchina le usa): {', '.join(missing)}"
                )
            )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna modifica salvata."))
        else:
            self.stdout.write(self.style.SUCCESS("Riclassifica completata."))


def _clean_list(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]
