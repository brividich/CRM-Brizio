"""Verifica la prontezza all'attivazione di ACL_STRICT_CANONICAL.

Spegnere il fallback legacy (`ACL_STRICT_CANONICAL=True`) nega l'accesso a
ogni route senza RoutePermissionBinding canonico. Questo comando misura
**prima** quanti accessi oggi *consentiti* dipendono dal fallback legacy: se
sono zero, attivare strict non introduce regressioni.

Per ogni ruolo legacy (o quelli indicati) simula `resolve_acl_access` su tutte
le route applicative (escluse Django admin) e conta quelle che oggi passano
SOLO grazie al fallback legacy (`decision_source == legacy_fallback` e
`allowed=True`). Quelle sono le route che strict-mode romperebbe.

Sola lettura: nessuna modifica a DB o settings.

Esempi:
    python manage.py acl_strict_readiness
    python manage.py acl_strict_readiness --role utente
    python manage.py acl_strict_readiness --format json
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.urls import get_resolver

from core.acl_v2 import resolve_acl_access, normalize_acl_path
from core.legacy_models import Ruolo, UtenteLegacy
from core.management.commands.acl_fallback_report import (
    is_django_admin_route,
    route_pattern_to_path,
)


class Command(BaseCommand):
    help = (
        "Misura quante route oggi passano SOLO via fallback legacy (per ruolo): "
        "se zero, ACL_STRICT_CANONICAL e' attivabile senza regressioni."
    )

    def add_arguments(self, parser):
        parser.add_argument("--role", help="Limita a un ruolo legacy: nome o ID.")
        parser.add_argument(
            "--format", choices=("text", "json"), default="text",
            help="Formato output (default: text).",
        )

    def handle(self, *args, **opts):
        fmt = opts.get("format") or "text"
        role_filter = (opts.get("role") or "").strip()

        # Silenzia il rumore dei warning ACL durante la simulazione di massa.
        logging.getLogger("core.acl").setLevel(logging.ERROR)

        routes: list[str] = []
        self._collect(get_resolver().url_patterns, "", routes)
        # Path concreti: i segnaposto diventano "1" per risolvere il route name.
        paths = sorted({
            route_pattern_to_path(r).replace("/_/", "/1/").replace("/_", "/1")
            for r in routes
        })

        roles = self._select_roles(role_filter)
        if not roles:
            self.stderr.write("Nessun ruolo trovato.")
            return

        report: dict[str, list[str]] = {}
        for role in roles:
            user = (
                UtenteLegacy.objects.filter(ruolo_id=role.id)
                .order_by("id")
                .first()
            )
            # Simuliamo un utente "minimale" del ruolo: se non c'e' un utente
            # reale, usiamo un proxy con solo ruolo_id (come il diagnose --role).
            legacy_user = user or _RoleProxy(role.id)
            fallback_allowed: list[str] = []
            for pth in paths:
                try:
                    decision = resolve_acl_access(
                        path=pth, legacy_user=legacy_user, django_user=None,
                        include_legacy_diagnostic=False,
                    )
                except Exception:
                    continue
                if (
                    decision.get("decision_source") == "legacy_fallback"
                    and bool(decision.get("allowed"))
                ):
                    fallback_allowed.append(normalize_acl_path(pth))
            report[f"{role.nome} (id={role.id})"] = sorted(set(fallback_allowed))

        total = sum(len(v) for v in report.values())

        if fmt == "json":
            self.stdout.write(json.dumps(
                {"routes_checked": len(paths), "fallback_allowed_total": total,
                 "by_role": report},
                indent=2, ensure_ascii=False,
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("ACL strict readiness"))
        self.stdout.write(f"Route applicative verificate: {len(paths)}")
        self.stdout.write(
            f"Accessi consentiti SOLO via fallback legacy: {total} "
            f"(se 0 -> ACL_STRICT_CANONICAL attivabile senza regressioni)"
        )
        self.stdout.write("")
        for role_label, paths_fb in report.items():
            self.stdout.write(f"  {role_label}: {len(paths_fb)} route via fallback")
            for p in paths_fb:
                self.stdout.write(f"      - {p}")

    def _select_roles(self, role_filter: str):
        qs = Ruolo.objects.all().order_by("id")
        if not role_filter:
            return list(qs)
        if role_filter.isdigit():
            return list(qs.filter(id=int(role_filter)))
        return list(qs.filter(nome__iexact=role_filter))

    def _collect(self, patterns, prefix, out):
        for p in patterns:
            pattern_str = str(getattr(p, "pattern", "") or "")
            full = prefix + pattern_str
            if hasattr(p, "url_patterns"):
                self._collect(p.url_patterns, full, out)
            else:
                name = getattr(p, "name", "") or ""
                if name and not is_django_admin_route(full):
                    out.append(full)


class _RoleProxy:
    """Utente legacy minimale per simulare un ruolo senza un utente reale."""

    def __init__(self, ruolo_id: int):
        self.id = -1
        self.ruolo_id = ruolo_id
        self.ruolo = ""
        self.nome = "[simulazione ruolo]"
        self.email = ""
