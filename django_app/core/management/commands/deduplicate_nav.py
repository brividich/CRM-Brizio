"""
Management command: deduplicate_nav

Trova e rimuove i NavigationItem duplicati: stesso target (route_name o url_path)
all'interno della stessa section. Tipica causa: api_navigation_bootstrap_from_legacy
eseguito più volte senza force=1, che genera codici come 'assets-2', 'assets-3'.

Logica di scelta del record canonico (per gruppo):
  1. Preferisce il record con code privo di suffisso numerico (-2, -3, ...)
  2. A parità, quello con id minore

I NavigationRoleAccess del duplicato vengono migrati sul canonico se non esistono già.

Uso:
    python manage.py deduplicate_nav              # dry-run (mostra cosa farebbe)
    python manage.py deduplicate_nav --apply      # esegue la pulizia
"""
from __future__ import annotations

import re
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction


_NUMERIC_SUFFIX = re.compile(r"-\d+$")


def _is_canonical_code(code: str) -> bool:
    """Restituisce True se il code NON ha suffisso numerico tipo -2, -3."""
    return not _NUMERIC_SUFFIX.search(str(code or ""))


class Command(BaseCommand):
    help = "Trova e rimuove NavigationItem duplicati (stesso target nella stessa section)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Esegue la pulizia. Senza questo flag opera in dry-run.",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"[deduplicate_nav] Modalità: {mode}")

        from core.models import NavigationItem, NavigationRoleAccess
        from core.navigation_registry import bump_navigation_registry_version

        # Raccoglie tutti gli item con target non vuoto, raggruppati per (section, target)
        groups: dict[tuple[str, str], list] = defaultdict(list)
        no_target: list = []

        for item in NavigationItem.objects.all().order_by("id"):
            target = (item.route_name or "").strip() or (item.url_path or "").strip()
            if not target:
                no_target.append(item)
                continue
            key = (str(item.section or "").strip().lower(), target)
            groups[key].append(item)

        duplicated_groups = {k: v for k, v in groups.items() if len(v) > 1}

        if not duplicated_groups:
            self.stdout.write(self.style.SUCCESS("Nessun duplicato trovato. DB pulito."))
            return

        self.stdout.write(
            self.style.WARNING(
                f"Trovati {len(duplicated_groups)} gruppi con duplicati:"
            )
        )

        total_deleted = 0

        for (section, target), items in sorted(duplicated_groups.items()):
            # Ordina: prima quelli senza suffisso numerico, poi per id asc
            items_sorted = sorted(items, key=lambda x: (0 if _is_canonical_code(x.code) else 1, x.id))
            canonical = items_sorted[0]
            duplicates = items_sorted[1:]

            self.stdout.write(
                f"\n  section={section!r} target={target!r}"
            )
            self.stdout.write(
                f"    CANONICO  id={canonical.id} code={canonical.code!r} label={canonical.label!r}"
            )
            for dup in duplicates:
                self.stdout.write(
                    f"    DUPLICATO id={dup.id} code={dup.code!r} label={dup.label!r}"
                    + (" → DA ELIMINARE" if apply else " (sarà eliminato con --apply)")
                )

            if apply:
                with transaction.atomic():
                    # Migra NavigationRoleAccess orfani sul canonico
                    existing_role_ids = set(
                        NavigationRoleAccess.objects.filter(item=canonical)
                        .values_list("legacy_role_id", flat=True)
                    )
                    for dup in duplicates:
                        for access in NavigationRoleAccess.objects.filter(item=dup):
                            if int(access.legacy_role_id) not in existing_role_ids:
                                access.item = canonical
                                access.save(update_fields=["item"])
                                existing_role_ids.add(int(access.legacy_role_id))
                            else:
                                access.delete()
                        dup.delete()
                        total_deleted += 1

        if apply:
            try:
                bump_navigation_registry_version()
            except Exception:
                pass
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[deduplicate_nav] Eliminati {total_deleted} duplicati. Cache navigazione invalidata."
                )
            )
        else:
            count = sum(len(v) - 1 for v in duplicated_groups.values())
            self.stdout.write(
                self.style.WARNING(
                    f"\n[deduplicate_nav] DRY-RUN completato. {count} duplicati da eliminare."
                    " Usa --apply per procedere."
                )
            )
