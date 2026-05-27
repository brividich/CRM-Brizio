from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand

from core.acl_bootstrap_base import prune_stale_pulsanti


class Command(BaseCommand):
    help = (
        "Rimuove dalla tabella Pulsante (e dai Permesso associati) le righe "
        "stale: presenti nel DB ma non più dichiarate nelle _PULSANTI_DEFINITIONS "
        "di ogni app. Usa --dry-run per vedere cosa verrebbe eliminato senza toccare il DB."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra i conteggi senza modificare il DB.",
        )
        parser.add_argument(
            "--apps",
            default="",
            help="Elenco app separato da virgola (es. tasks,assets). Vuoto = tutte.",
        )

    def handle(self, *args, **options):
        dry_run: bool = bool(options.get("dry_run"))
        apps_raw: str = str(options.get("apps") or "").strip()
        apps_filter: set[str] = {a.strip() for a in apps_raw.split(",") if a.strip()}

        total_pulsanti = 0
        total_permessi = 0
        checked = 0

        for app_config in django_apps.get_app_configs():
            app_name = app_config.name
            if apps_filter and app_name not in apps_filter:
                continue

            try:
                bootstrap_module = importlib.import_module(f"{app_name}.acl_bootstrap")
            except ImportError:
                continue

            definitions = getattr(bootstrap_module, "_PULSANTI_DEFINITIONS", None)
            if not isinstance(definitions, list) or not definitions:
                continue

            checked += 1

            # Raggruppa i codici validi per modulo
            # (un'app può dichiarare più moduli in definitions)
            valid_by_modulo: dict[str, set[str]] = {}
            for d in definitions:
                mod = str(d.get("modulo") or "").strip()
                cod = str(d.get("codice") or "").strip()
                if mod and cod:
                    valid_by_modulo.setdefault(mod, set()).add(cod)

            for modulo, valid_codici in valid_by_modulo.items():
                n_p, n_perm = prune_stale_pulsanti(modulo, valid_codici, dry_run=dry_run)
                if n_p or n_perm:
                    prefix = "[DRY-RUN] " if dry_run else ""
                    verb = "da rimuovere" if dry_run else "rimossi"
                    self.stdout.write(
                        f"{prefix}{modulo}: "
                        f"{n_p} pulsanti stale, {n_perm} permessi stale {verb}"
                    )
                    total_pulsanti += n_p
                    total_permessi += n_perm

        prefix = "[DRY-RUN] " if dry_run else ""
        verb = "da rimuovere" if dry_run else "rimossi"
        summary = (
            f"\n{prefix}Scansionate {checked} app — "
            f"totale: {total_pulsanti} pulsanti {verb}, {total_permessi} permessi {verb}"
        )
        if total_pulsanti == 0 and total_permessi == 0:
            self.stdout.write(self.style.SUCCESS(summary + " (DB già pulito)"))
        elif dry_run:
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
