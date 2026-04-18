"""
Management command: deduplicate_nav

Trova e rimuove i NavigationItem duplicati all'interno della stessa section.

Modalità:
  --apply           esegue la pulizia (default: dry-run)
  --by-label        abilita dedup per etichetta (topbar flat items senza categoria)

Criteri dedup:
  1. Stesso target (route_name o url_path) → default, tutte le sezioni
  2. Stessa etichetta (label) in topbar flat (no categoria) → richiede --by-label

Logica di scelta del record canonico (per gruppo):
  1. Preferisce il record con code privo di suffisso numerico (-2, -3, ...)
  2. A parità, quello con id minore

I NavigationRoleAccess del duplicato vengono migrati sul canonico se non esistono già.

Uso:
    python manage.py deduplicate_nav                        # dry-run (target)
    python manage.py deduplicate_nav --apply                # applica (target)
    python manage.py deduplicate_nav --by-label             # dry-run (target + label)
    python manage.py deduplicate_nav --by-label --apply     # applica tutto
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


def _migrate_role_access(canonical, duplicates, NavigationRoleAccess, apply: bool) -> int:
    """Migra NavigationRoleAccess dai duplicati al canonico; restituisce il numero di eliminati."""
    if not apply:
        return len(duplicates)
    deleted = 0
    with transaction.atomic():
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
            deleted += 1
    return deleted


class Command(BaseCommand):
    help = (
        "Trova e rimuove NavigationItem duplicati (stesso target o stessa etichetta "
        "topbar flat). Dry-run di default: aggiungere --apply per eseguire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Esegue la pulizia. Senza questo flag opera in dry-run.",
        )
        parser.add_argument(
            "--by-label",
            action="store_true",
            default=False,
            dest="by_label",
            help=(
                "Abilita anche il dedup per etichetta: rimuove voci topbar flat "
                "(senza categoria) con la stessa label, tenendo quella con id minore."
            ),
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        by_label = bool(options["by_label"])
        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"[deduplicate_nav] Modalità: {mode}" + (" + by-label" if by_label else ""))

        from core.models import NavigationItem, NavigationRoleAccess
        from core.navigation_registry import bump_navigation_registry_version

        total_deleted = 0
        found_any = False

        # ── 1. Dedup per target (route_name o url_path) ──────────────────────
        groups: dict[tuple[str, str], list] = defaultdict(list)

        for item in NavigationItem.objects.all().order_by("id"):
            target = (item.route_name or "").strip() or (item.url_path or "").strip()
            if not target:
                continue
            key = (str(item.section or "").strip().lower(), target)
            groups[key].append(item)

        duplicated_groups = {k: v for k, v in groups.items() if len(v) > 1}

        if duplicated_groups:
            found_any = True
            self.stdout.write(
                self.style.WARNING(
                    f"\n[Target] Trovati {len(duplicated_groups)} gruppi con target duplicato:"
                )
            )
            for (section, target), items in sorted(duplicated_groups.items()):
                items_sorted = sorted(items, key=lambda x: (0 if _is_canonical_code(x.code) else 1, x.id))
                canonical = items_sorted[0]
                duplicates = items_sorted[1:]

                self.stdout.write(f"\n  section={section!r} target={target!r}")
                self.stdout.write(f"    CANONICO  id={canonical.id} code={canonical.code!r} label={canonical.label!r}")
                for dup in duplicates:
                    self.stdout.write(
                        f"    DUPLICATO id={dup.id} code={dup.code!r} label={dup.label!r}"
                        + (" → ELIMINATO" if apply else " (sarà eliminato con --apply)")
                    )

                deleted = _migrate_role_access(canonical, duplicates, NavigationRoleAccess, apply)
                if apply:
                    total_deleted += deleted
                else:
                    total_deleted += len(duplicates)
        else:
            self.stdout.write(self.style.SUCCESS("[Target] Nessun duplicato per target. OK."))

        # ── 2. Dedup per etichetta topbar flat (solo con --by-label) ─────────
        if by_label:
            label_groups: dict[str, list] = defaultdict(list)

            for item in NavigationItem.objects.filter(section="topbar", is_visible=True, is_enabled=True).order_by("order", "id"):
                # Salta voci già incluse nel dedup per target
                target = (item.route_name or "").strip() or (item.url_path or "").strip()
                key = ("topbar", target)
                if target and key in duplicated_groups:
                    continue
                # Salta voci con categoria assegnata
                if item.category_id:
                    continue
                label_key = str(item.label or "").strip().lower()
                if label_key:
                    label_groups[label_key].append(item)

            label_dup_groups = {k: v for k, v in label_groups.items() if len(v) > 1}

            if label_dup_groups:
                found_any = True
                self.stdout.write(
                    self.style.WARNING(
                        f"\n[Label] Trovati {len(label_dup_groups)} gruppi con etichetta topbar flat duplicata:"
                    )
                )
                for label_key, items in sorted(label_dup_groups.items()):
                    items_sorted = sorted(items, key=lambda x: (0 if _is_canonical_code(x.code) else 1, x.order, x.id))
                    canonical = items_sorted[0]
                    duplicates = items_sorted[1:]

                    self.stdout.write(f"\n  label={label_key!r}")
                    self.stdout.write(f"    CANONICO  id={canonical.id} code={canonical.code!r} route={canonical.route_name!r}")
                    for dup in duplicates:
                        self.stdout.write(
                            f"    DUPLICATO id={dup.id} code={dup.code!r} route={dup.route_name!r}"
                            + (" → ELIMINATO" if apply else " (sarà eliminato con --apply)")
                        )

                    deleted = _migrate_role_access(canonical, duplicates, NavigationRoleAccess, apply)
                    if apply:
                        total_deleted += deleted
                    else:
                        total_deleted += len(duplicates)
            else:
                self.stdout.write(self.style.SUCCESS("[Label] Nessun duplicato topbar flat per etichetta. OK."))

        # ── Riepilogo ─────────────────────────────────────────────────────────
        if not found_any:
            self.stdout.write(self.style.SUCCESS("\nDB navigazione pulito. Nessun duplicato trovato."))
            return

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
            self.stdout.write(
                self.style.WARNING(
                    f"\n[deduplicate_nav] DRY-RUN completato. {total_deleted} duplicati da eliminare."
                    " Usa --apply per procedere."
                )
            )
