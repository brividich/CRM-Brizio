"""Risincronizza i grant canonici ai permessi legacy effettivi.

Colma il buco di ``bootstrap_acl_v2 --import-legacy``, che allinea i
``RolePermissionGrant`` ai permessi legacy **solo** per le route ancora in
fallback (``_apply_route_suggestions`` filtra su ``status_before ==
STATUS_LEGACY_FALLBACK``). Le route gia' bindate al canonico — la maggioranza dei
moduli di dominio — restano con grant non allineati, ed e' la causa per cui un
permesso assegnato lato legacy non si traduceva in accesso (vedi caso tickets).

Questo comando lavora a partire dai ``RoutePermissionBinding`` attivi che puntano
a una permission-ponte ``legacy.<modulo>.<azione>`` e, per ciascuno, allinea il
grant del ruolo al valore legacy effettivo (``can_view`` OR ``consentito``).

Strategia conservativa di default:
- aggiorna solo grant assenti o marcati ``[ACL_V2_BOOTSTRAP]`` (idempotente);
- con ``--force`` sovrascrive anche i grant manuali (richiede review esplicita);
- ``--dry-run`` (default) non scrive nulla e stampa il diff prima/dopo per ruolo;
- NON tocca ``UserPermissionGrant`` (override utente): restano autoritativi.

Esempi:
    python manage.py acl_sync_legacy_grants                 # dry-run, tutto
    python manage.py acl_sync_legacy_grants --app tickets   # dry-run su un modulo
    python manage.py acl_sync_legacy_grants --apply         # scrive
    python manage.py acl_sync_legacy_grants --apply --force  # sovrascrive anche i manuali
    python manage.py acl_sync_legacy_grants --format json
"""
from __future__ import annotations

import json
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import DatabaseError, transaction

from core.legacy_models import Ruolo
from core.models import RolePermissionGrant, RoutePermissionBinding

# Riuso degli helper gia' esistenti nel bootstrap per non duplicare la logica.
from core.management.commands.bootstrap_acl_v2 import (
    MIGRATION_NOTE_MARKER,
    _legacy_acl_indexes,
)

SYNC_NOTE_MARKER = "[ACL_V2_SYNC]"


class Command(BaseCommand):
    help = (
        "Allinea i grant canonici (RolePermissionGrant) ai permessi legacy effettivi "
        "anche per le route gia' bindate al canonico. Dry-run di default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Scrive le modifiche. Senza questo flag il comando e' in dry-run.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Esplicita la modalita' dry-run (default). Ignorato se usato con --apply assente.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Sovrascrive anche i grant manuali (senza marker bootstrap/sync). Usare con review.",
        )
        parser.add_argument("--app", help="Limita a un modulo/source_app (es. 'tickets').")
        parser.add_argument("--role", help="Limita a un ruolo legacy: nome o ID.")
        parser.add_argument(
            "--format", choices=("text", "json"), default="text",
            help="Formato output (default: text).",
        )

    def handle(self, *args, **opts):
        apply_changes = bool(opts.get("apply"))
        force = bool(opts.get("force"))
        app_filter = (opts.get("app") or "").strip().lower()
        role_filter_id = self._resolve_role_filter(opts.get("role"))
        fmt = opts.get("format") or "text"

        role_names = {int(r.id): str(r.nome or "") for r in Ruolo.objects.all()}

        try:
            _, _, grants_index = _legacy_acl_indexes()
        except DatabaseError as exc:
            self.stderr.write(self.style.ERROR(f"Errore lettura indici legacy: {exc}"))
            return

        bindings = (
            RoutePermissionBinding.objects.filter(
                is_active=True, permission__code__startswith="legacy."
            )
            .select_related("permission")
            .order_by("permission_id")
        )

        # Pianificazione: raccolgo le azioni da applicare senza scrivere.
        planned: list[dict] = []
        # diff[role_id] = {"enable": n, "disable": n, "noop": n, "skip_manual": n}
        diff: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        seen_keys: set[tuple[int, str]] = set()
        for binding in bindings:
            source_app = (binding.source_app or "").strip().lower()
            parts = (binding.permission_id or "").split(".")
            if len(parts) < 3 or parts[0] != "legacy":
                continue
            modulo = parts[1].strip().lower()
            azione = ".".join(parts[2:]).strip().lower()
            if app_filter and app_filter not in (source_app, modulo):
                continue

            legacy_role_grants = grants_index.get((modulo, azione), {})
            for legacy_role_id, legacy_enabled in legacy_role_grants.items():
                if role_filter_id is not None and int(legacy_role_id) != role_filter_id:
                    continue
                key = (int(legacy_role_id), binding.permission_id)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                planned.append(
                    {
                        "role_id": int(legacy_role_id),
                        "permission_code": binding.permission_id,
                        "modulo": modulo,
                        "azione": azione,
                        "legacy_enabled": bool(legacy_enabled),
                    }
                )

        # Valuto ogni azione contro lo stato corrente del grant.
        existing = {
            (g.legacy_role_id, g.permission_id): g
            for g in RolePermissionGrant.objects.filter(
                permission_id__in={p["permission_code"] for p in planned}
            )
        }
        actions: list[dict] = []
        for item in planned:
            role_id = item["role_id"]
            code = item["permission_code"]
            want = item["legacy_enabled"]
            grant = existing.get((role_id, code))

            if grant is None:
                actions.append({**item, "op": "create", "from": None, "to": want})
                diff[role_id]["enable" if want else "noop"] += 1
                continue

            is_managed = (
                MIGRATION_NOTE_MARKER in (grant.note or "")
                or SYNC_NOTE_MARKER in (grant.note or "")
            )
            if bool(grant.enabled) == want:
                diff[role_id]["noop"] += 1
                continue
            if not is_managed and not force:
                actions.append({**item, "op": "skip_manual", "from": bool(grant.enabled), "to": want})
                diff[role_id]["skip_manual"] += 1
                continue
            actions.append({**item, "op": "update", "from": bool(grant.enabled), "to": want})
            diff[role_id]["enable" if want else "disable"] += 1

        if apply_changes:
            self._apply(actions)

        if fmt == "json":
            self.stdout.write(json.dumps(
                {
                    "applied": apply_changes,
                    "force": force,
                    "diff_by_role": {
                        str(rid): dict(counts) for rid, counts in sorted(diff.items())
                    },
                    "actions": actions,
                },
                indent=2, default=str,
            ))
            return

        self._render_text(actions, diff, role_names, apply_changes, force)

    # ------------------------------------------------------------------ helpers

    def _resolve_role_filter(self, raw) -> int | None:
        value = (str(raw or "")).strip()
        if not value:
            return None
        if value.isdigit():
            return int(value)
        ruolo = Ruolo.objects.filter(nome__iexact=value).first()
        return int(ruolo.id) if ruolo else -1  # -1 = nessun match: non tocca nulla

    def _apply(self, actions: list[dict]) -> None:
        with transaction.atomic():
            for a in actions:
                if a["op"] not in ("create", "update"):
                    continue
                RolePermissionGrant.objects.update_or_create(
                    legacy_role_id=a["role_id"],
                    permission_id=a["permission_code"],
                    defaults={
                        "enabled": bool(a["to"]),
                        "note": f"{SYNC_NOTE_MARKER} legacy grant sync {a['modulo']}.{a['azione']}",
                    },
                )

    def _render_text(self, actions, diff, role_names, applied, force) -> None:
        header = "ACL sync legacy -> canonical grants"
        self.stdout.write(self.style.MIGRATE_HEADING(header))
        mode = self.style.SUCCESS("APPLY") if applied else self.style.WARNING("DRY-RUN (nessuna scrittura)")
        self.stdout.write(f"Modalita'       : {mode}{'  +FORCE' if force else ''}")
        self.stdout.write("")

        creates = sum(1 for a in actions if a["op"] == "create")
        updates = sum(1 for a in actions if a["op"] == "update")
        skips = sum(1 for a in actions if a["op"] == "skip_manual")
        self.stdout.write(f"Grant da creare : {creates}")
        self.stdout.write(f"Grant da modific: {updates}")
        self.stdout.write(f"Grant manuali saltati (usa --force): {skips}")
        self.stdout.write("")

        self.stdout.write("Diff per ruolo:")
        for role_id, counts in sorted(diff.items()):
            name = role_names.get(role_id, f"role:{role_id}")
            self.stdout.write(
                f"  {name:<18} (id={role_id}): "
                f"+abilita={counts.get('enable', 0):>4}  "
                f"-disabilita={counts.get('disable', 0):>4}  "
                f"invariati={counts.get('noop', 0):>4}  "
                f"manuali_saltati={counts.get('skip_manual', 0):>4}"
            )

        if skips:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Alcuni grant hanno una nota manuale e non sono stati toccati. "
                "Verificali e, se vanno allineati al legacy, rilancia con --force."
            ))
        if not applied:
            self.stdout.write("")
            self.stdout.write("Rilancia con --apply per scrivere le modifiche.")
