"""Bonifica dei binding ACL senza togliere accesso a nessuno.

Il problema che questo comando chiude: 343 binding per-route sono disattivati, e
le pagine che dovrebbero governare ricadono su un binding di prefisso di un'altra
pagina. E' cosi' che ``/assets/impostazioni/`` finisce governata dal permesso
dell'inventario (`/assets` -> ``legacy.assets.view_assets``), e che concedere il
permesso "giusto" non produce alcun effetto.

Riattivare i binding, pero', cambia il permesso richiesto da quelle pagine: chi
oggi entra grazie al prefisso permissivo (o al fallback legacy) resterebbe fuori.
Per questo il comando calcola, ruolo per ruolo, chi perderebbe l'accesso e crea i
grant necessari perche' il saldo sia zero: **la bonifica non revoca mai nulla**.
I grant di grandfathering sono marcati in nota, cosi' dopo il go-live si possono
rivedere e stringere sapendo esattamente quali sono.

Dry-run per default. Esempi:

    python manage.py acl_cleanup --report bonifica.json
    python manage.py acl_cleanup --apply --backup-dir C:\\temp\\acl-backup
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from core.acl import check_permesso, normalize_acl_path
from core.acl_resolver import resolve_permission_decision
from core.acl_v2 import _find_canonical_binding
from core.legacy_models import Ruolo, UtenteLegacy
from core.legacy_utils import is_legacy_admin
from core.models import (
    RolePermissionGrant,
    RoutePermissionBinding,
    UserPermissionGrant,
)

_SAMPLE_SEGMENT_RE = re.compile(r"<[^>]+>")

GRANDFATHER_NOTE = "[ACL_CLEANUP] grandfathering: accesso preesistente conservato"
REACTIVATION_NOTE = "[ACL_CLEANUP] binding per-route riattivato"
LEGACY_SYNC_NOTE = "[ACL_CLEANUP] riallineato al permesso legacy concesso nel pannello"
BACKUP_MODELS = (
    ("route_bindings", RoutePermissionBinding),
    ("role_grants", RolePermissionGrant),
    ("user_grants", UserPermissionGrant),
)


def _simulated_user(ruolo: Ruolo) -> UtenteLegacy:
    """Utente legacy non persistito: porta solo il ruolo dentro il risolutore."""
    return UtenteLegacy(
        id=-1,
        nome=f"[simulazione ruolo {ruolo.nome}]",
        email="",
        password="",
        ruolo=ruolo.nome,
        attivo=True,
        deve_cambiare_password=False,
        ruolo_id=ruolo.id,
    )


class Command(BaseCommand):
    help = (
        "Riattiva i binding ACL per-route conservando gli accessi esistenti "
        "(grandfathering). Dry-run per default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (default: dry-run).")
        parser.add_argument("--report", help="Percorso del report JSON da scrivere.")
        parser.add_argument("--backup-dir", help="Dove salvare il dump delle tabelle prima di scrivere.")
        parser.add_argument(
            "--limit", type=int, default=0, help="Analizza solo i primi N binding (per prove rapide)."
        )
        parser.add_argument(
            "--sync-legacy",
            action="store_true",
            help=(
                "Porta a True i grant canonici a False il cui permesso legacy e' invece "
                "concesso: sono le spunte fatte nel pannello 'Gestione Accessi' che non "
                "hanno mai avuto effetto. Additivo, non revoca nulla."
            ),
        )

    # ------------------------------------------------------------------ handle
    def handle(self, *args, **opts):
        apply_changes = bool(opts.get("apply"))
        limit = int(opts.get("limit") or 0)

        roles = list(Ruolo.objects.all().order_by("id"))
        simulated = {int(r.id): _simulated_user(r) for r in roles}

        path_map = self._route_path_map()
        active_bindings = self._load_active_bindings()

        candidates = list(
            RoutePermissionBinding.objects.filter(is_active=False)
            .exclude(route_name="")
            .select_related("permission")
            .order_by("route_name", "id")
        )
        if limit:
            candidates = candidates[:limit]

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "apply" if apply_changes else "dry-run",
            "roles": [{"id": int(r.id), "nome": r.nome} for r in roles],
            "bindings_to_activate": [],
            "bindings_orphan_route": [],
            "role_grants_to_create": [],
            "user_grants_to_create": [],
            "legacy_divergences": [],
        }

        for binding in candidates:
            path = path_map.get(str(binding.route_name or "").lower())
            if not path:
                # La route non esiste piu' fra quelle servite: il binding e'
                # orfano, riattivarlo non governerebbe nulla.
                report["bindings_orphan_route"].append(binding.route_name)
                continue

            new_code = str(binding.permission_id)
            old_binding, matched_by = _find_canonical_binding(
                route_name=binding.route_name, path_norm=path, bindings=active_bindings
            )
            old_code = str(old_binding.permission_id) if old_binding is not None else ""

            entry = {
                "binding_id": int(binding.id),
                "route_name": binding.route_name,
                "path": path,
                "new_permission": new_code,
                "old_permission": old_code,
                "old_matched_by": matched_by,
                "roles_grandfathered": [],
            }

            if old_code != new_code:
                for role in roles:
                    legacy_user = simulated[int(role.id)]
                    if is_legacy_admin(legacy_user):
                        # Gli admin legacy entrano per bypass: un grant su di loro
                        # sarebbe rumore, non una concessione che serve a qualcosa.
                        continue
                    before = self._allowed_before(
                        old_binding=old_binding, path=path, legacy_user=legacy_user
                    )
                    if not before:
                        continue
                    after = resolve_permission_decision(
                        permission_code=new_code,
                        legacy_user=legacy_user,
                        allow_superuser=False,
                        allow_legacy_admin=False,
                    ).allowed
                    if after:
                        continue
                    entry["roles_grandfathered"].append({"id": int(role.id), "nome": role.nome})
                    report["role_grants_to_create"].append(
                        {"legacy_role_id": int(role.id), "permission": new_code, "route": binding.route_name}
                    )

                # Gli override per-utente sul vecchio permesso vanno riportati sul
                # nuovo, altrimenti la singola persona perde cio' che le era stato
                # dato a mano.
                if old_code:
                    for grant in UserPermissionGrant.objects.filter(
                        permission_id=old_code, enabled=True
                    ):
                        report["user_grants_to_create"].append(
                            {
                                "legacy_user_id": int(grant.legacy_user_id),
                                "permission": new_code,
                                "from_permission": old_code,
                            }
                        )

            report["bindings_to_activate"].append(entry)

        report["legacy_divergences"] = self._collect_legacy_divergences()

        if apply_changes:
            backup_dir = opts.get("backup_dir")
            if backup_dir:
                self._write_backup(Path(backup_dir))
            self._apply(report, sync_legacy=bool(opts.get("sync_legacy")))

        self._render(report, apply_changes=apply_changes)
        if opts.get("report"):
            Path(opts["report"]).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            self.stdout.write(f"Report scritto in {opts['report']}")
        return None

    # ------------------------------------------------------------------ helper
    def _route_path_map(self) -> dict[str, str]:
        """route_name -> path concreto, dalla ricognizione del pannello ACL.

        I path parametrici (``/assets/view/<int:id>``) diventano un campione
        (``/assets/view/1``): serve solo a capire quale binding li governa oggi,
        e un segmento vale l'altro per il matching di prefisso.
        """
        from admin_portale.acl_v2_views import _collect_route_coverage_rows

        rows, _summary = _collect_route_coverage_rows()
        mapping: dict[str, str] = {}
        for row in rows:
            route_name = str(row.get("route_name") or "").strip().lower()
            path = str(row.get("path_normalized") or "").strip()
            if not route_name or not path:
                continue
            mapping.setdefault(route_name, normalize_acl_path(_SAMPLE_SEGMENT_RE.sub("1", path)))
        return mapping

    def _load_active_bindings(self) -> list[RoutePermissionBinding]:
        return list(
            RoutePermissionBinding.objects.filter(is_active=True)
            .select_related("permission")
            .order_by("priority", "id")
        )

    def _allowed_before(self, *, old_binding, path: str, legacy_user) -> bool:
        """Accesso di oggi: dal binding che governa ora, o dal fallback legacy."""
        if old_binding is not None:
            return resolve_permission_decision(
                permission_code=str(old_binding.permission_id),
                legacy_user=legacy_user,
                allow_superuser=False,
                allow_legacy_admin=False,
                permission=old_binding.permission,
            ).allowed
        return bool(check_permesso(legacy_user, path))

    def _collect_legacy_divergences(self) -> list[dict]:
        """Grant canonici a False che il legacy oggi concede.

        Sono l'anomalia che rende inutile il pannello 'Gestione Accessi': la
        spunta finisce nella tabella ``permessi``, ma la riga canonica a False
        esiste e ha la precedenza, quindi la concessione non si vede mai. Il
        grant canonico e' fermo alla fotografia del bootstrap.
        """
        from core.acl_v2 import evaluate_legacy_permission_code_compat

        divergences: list[dict] = []
        for grant in RolePermissionGrant.objects.filter(enabled=False).select_related("permission"):
            compat = evaluate_legacy_permission_code_compat(
                permission_code=str(grant.permission_id),
                legacy_role_id=int(grant.legacy_role_id),
            )
            if compat is not None and bool(compat.get("enabled", False)):
                divergences.append(
                    {
                        "id": int(grant.id),
                        "legacy_role_id": int(grant.legacy_role_id),
                        "permission": str(grant.permission_id),
                        "legacy_reason": str(compat.get("reason") or ""),
                    }
                )
        return divergences

    def _write_backup(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for name, model in BACKUP_MODELS:
            payload = list(model.objects.all().values())
            target = directory / f"{name}-{stamp}.json"
            target.write_text(json.dumps(payload, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
            self.stdout.write(f"Backup {name}: {target}")

    @transaction.atomic
    def _apply(self, report: dict, *, sync_legacy: bool) -> None:
        for row in report["role_grants_to_create"]:
            grant, created = RolePermissionGrant.objects.get_or_create(
                legacy_role_id=row["legacy_role_id"],
                permission_id=row["permission"],
                defaults={"enabled": True, "note": GRANDFATHER_NOTE},
            )
            if not created and not grant.enabled:
                grant.enabled = True
                grant.note = GRANDFATHER_NOTE
                grant.save(update_fields=["enabled", "note"])

        for row in report["user_grants_to_create"]:
            UserPermissionGrant.objects.get_or_create(
                legacy_user_id=row["legacy_user_id"],
                permission_id=row["permission"],
                defaults={"enabled": True, "note": GRANDFATHER_NOTE},
            )

        binding_ids = [entry["binding_id"] for entry in report["bindings_to_activate"]]
        RoutePermissionBinding.objects.filter(id__in=binding_ids).update(is_active=True, priority=120)

        if sync_legacy:
            RolePermissionGrant.objects.filter(
                id__in=[row["id"] for row in report["legacy_divergences"]]
            ).update(enabled=True, note=LEGACY_SYNC_NOTE)

        from core.legacy_cache import bump_legacy_cache_version

        transaction.on_commit(bump_legacy_cache_version)

    def _render(self, report: dict, *, apply_changes: bool) -> None:
        head = "APPLICATO" if apply_changes else "DRY-RUN (nessuna scrittura)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"acl_cleanup - {head}"))
        self.stdout.write(f"Binding per-route da riattivare : {len(report['bindings_to_activate'])}")
        self.stdout.write(f"  binding orfani ignorati       : {len(report['bindings_orphan_route'])}")
        self.stdout.write(f"Grant di ruolo per grandfathering: {len(report['role_grants_to_create'])}")
        self.stdout.write(f"Override utente da riportare     : {len(report['user_grants_to_create'])}")
        self.stdout.write(
            f"Grant canonici che ignorano il legacy: {len(report['legacy_divergences'])} "
            "(riallineati solo con --sync-legacy)"
        )
        changed = [e for e in report["bindings_to_activate"] if e["old_permission"] != e["new_permission"]]
        self.stdout.write(f"Pagine che cambiano permesso     : {len(changed)}")
        for entry in changed[:10]:
            self.stdout.write(
                f"  {entry['route_name']}: {entry['old_permission'] or '(fallback legacy)'} -> {entry['new_permission']}"
            )
        if len(changed) > 10:
            self.stdout.write(f"  ... e altre {len(changed) - 10} (vedi --report)")
