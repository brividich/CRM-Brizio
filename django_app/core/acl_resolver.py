"""Punto unico in cui si decide se un permesso canonico e' concesso.

Fino a qui la stessa decisione era scritta in quattro posti diversi:
``core.acl_v2.evaluate_permission_code_access``, ``core.acl_v2.resolve_acl_access``
(che la riscriveva invece di chiamarla), ``core.navigation_registry`` per la
visibilita' del menu e ``core.acl`` per il layer legacy. Quattro copie che
divergono sono quattro comportamenti diversi sulla stessa pagina.

Qui la decisione e' una sola, e vale questa precedenza:

1. superuser Django
2. admin legacy
3. override utente (``UserPermissionGrant``)
4. gruppi di accesso (``GroupPermissionGrant``): fra i gruppi che si esprimono
   decide quello con ``priority`` piu' alta; a parita' vince il diniego
5. grant di ruolo (``RolePermissionGrant``)
6. compat legacy (tabella ``permessi``), solo se nessuno dei precedenti si e'
   espresso: una riga di grant che esiste - anche a ``enabled=False`` - e' una
   decisione presa, e il legacy non la ribalta
7. altrimenti diniego

"Esprimersi" significa avere una riga: l'assenza e' silenzio, ``enabled=False``
e' un no esplicito. E' la distinzione che tiene in piedi la migrazione, perche'
il fallback legacy resta vivo solo dove il canonico tace davvero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import DatabaseError

from core.legacy_utils import is_legacy_admin
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    PermissionDefinition,
    RolePermissionGrant,
    UserPermissionGrant,
)


LEVEL_SUPERUSER = "superuser_bypass"
LEVEL_LEGACY_ADMIN = "legacy_admin_bypass"
LEVEL_USER_OVERRIDE = "user_override"
LEVEL_GROUP_GRANT = "group_grant"
LEVEL_ROLE_GRANT = "role_grant"
LEVEL_LEGACY_COMPAT = "legacy_compat"
LEVEL_DENY = "deny"


@dataclass
class Decision:
    """Esito della valutazione, con il perche' in chiaro e chi ha deciso."""

    allowed: bool = False
    level: str = LEVEL_DENY
    reason: str = ""
    permission_code: str = ""
    permission: dict | None = None
    permission_missing: bool = False
    permission_inactive: bool = False
    user_override: dict | None = None
    group_grant: dict | None = None
    group_grants: list[dict] = field(default_factory=list)
    role_grant: dict | None = None
    legacy_compat: dict | None = None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "level": self.level,
            "reason": self.reason,
            "permission_code": self.permission_code,
            "permission": self.permission,
            "user_override": self.user_override,
            "group_grant": self.group_grant,
            "group_grants": self.group_grants,
            "role_grant": self.role_grant,
            "legacy_compat": self.legacy_compat,
            "error": self.error,
        }


def _serialize_group_grant(grant: GroupPermissionGrant) -> dict:
    group = grant.group
    return {
        "exists": True,
        "id": int(grant.id),
        "enabled": bool(grant.enabled),
        "group_id": int(group.id),
        "group_code": group.code,
        "group_label": group.label,
        "priority": int(group.priority or 0),
        "note": grant.note or "",
    }


def user_group_ids(legacy_user_id: int | None) -> list[int]:
    """Id dei gruppi attivi a cui appartiene l'utente legacy."""
    if not legacy_user_id:
        return []
    try:
        return list(
            AccessGroupMembership.objects.filter(
                legacy_user_id=int(legacy_user_id),
                group__is_active=True,
            ).values_list("group_id", flat=True)
        )
    except DatabaseError:
        return []


def resolve_group_grant(*, permission_code: str, legacy_user_id: int | None) -> tuple[dict | None, list[dict]]:
    """Grant di gruppo vincente su un permesso, piu' tutti quelli in gioco.

    Vince la priorita' piu' alta; a parita' il diniego, cosi' l'esito non
    dipende dall'ordine in cui i gruppi sono stati creati.
    """
    group_ids = user_group_ids(legacy_user_id)
    if not group_ids:
        return None, []

    try:
        grants = list(
            GroupPermissionGrant.objects.filter(
                group_id__in=group_ids,
                permission_id=permission_code,
            ).select_related("group")
        )
    except DatabaseError:
        return None, []

    serialized = sorted(
        (_serialize_group_grant(grant) for grant in grants),
        key=lambda row: (-int(row["priority"]), bool(row["enabled"]), int(row["group_id"])),
    )
    winner = serialized[0] if serialized else None
    return winner, serialized


def resolve_permission_decision(
    *,
    permission_code: str,
    legacy_user=None,
    django_user=None,
    legacy_role_id: int | None = None,
    legacy_user_id: int | None = None,
    allow_superuser: bool = True,
    allow_legacy_admin: bool = True,
    permission: PermissionDefinition | None = None,
    with_legacy_compat: bool = True,
) -> Decision:
    """Valuta ``permission_code`` per un utente: unica sede della decisione."""
    decision = Decision(permission_code=permission_code)
    if not permission_code:
        decision.reason = "Permission code mancante."
        return decision

    if allow_superuser and bool(getattr(django_user, "is_superuser", False)):
        decision.allowed = True
        decision.level = LEVEL_SUPERUSER
        decision.reason = "Utente Django superuser: bypass ACL."
        return decision

    if allow_legacy_admin and legacy_user is not None and is_legacy_admin(legacy_user):
        decision.allowed = True
        decision.level = LEVEL_LEGACY_ADMIN
        decision.reason = "Utente riconosciuto come admin legacy: bypass ACL."
        return decision

    if legacy_role_id is None and legacy_user is not None:
        legacy_role_id = getattr(legacy_user, "ruolo_id", None)
    if legacy_user_id is None and legacy_user is not None:
        legacy_user_id = getattr(legacy_user, "id", None)

    if permission is None:
        try:
            permission = PermissionDefinition.objects.filter(code=permission_code).first()
        except DatabaseError as exc:
            decision.error = str(exc)
            decision.reason = "Errore di lettura del catalogo permessi."
            return decision

    if permission is None:
        decision.permission_missing = True
        decision.reason = f"Permission '{permission_code}' non trovata."
        return decision

    decision.permission = {
        "code": permission.code,
        "label": permission.label,
        "module": permission.module,
        "description": permission.description,
        "is_active": bool(permission.is_active),
    }
    if not bool(permission.is_active):
        decision.permission_inactive = True
        decision.reason = f"Permission '{permission.code}' trovata ma disattiva."
        return decision

    # 3. Override utente: la parola dell'amministratore sulla singola persona.
    user_grant = None
    if legacy_user_id:
        try:
            user_grant = (
                UserPermissionGrant.objects.filter(
                    legacy_user_id=int(legacy_user_id),
                    permission_id=permission.code,
                )
                .order_by("-id")
                .first()
            )
        except DatabaseError as exc:
            decision.error = str(exc)
    if user_grant is not None:
        decision.user_override = {
            "exists": True,
            "id": int(user_grant.id),
            "enabled": bool(user_grant.enabled),
            "legacy_user_id": int(user_grant.legacy_user_id),
            "note": user_grant.note or "",
        }
        decision.allowed = bool(user_grant.enabled)
        decision.level = LEVEL_USER_OVERRIDE
        decision.reason = (
            f"Override utente canonico su '{permission.code}' consente accesso."
            if decision.allowed
            else f"Override utente canonico su '{permission.code}' nega accesso."
        )
        return decision
    decision.user_override = {"exists": False, "enabled": None}

    # 4. Gruppi di accesso, per priorita'.
    winner, all_grants = resolve_group_grant(
        permission_code=permission.code,
        legacy_user_id=legacy_user_id,
    )
    decision.group_grants = all_grants
    if winner is not None:
        decision.group_grant = winner
        decision.allowed = bool(winner["enabled"])
        decision.level = LEVEL_GROUP_GRANT
        decision.reason = (
            f"Gruppo '{winner['group_label']}' (priorita' {winner['priority']}) "
            + ("consente" if decision.allowed else "nega")
            + f" '{permission.code}'."
        )
        return decision

    # 5. Grant di ruolo.
    role_grant = None
    if legacy_role_id:
        try:
            role_grant = (
                RolePermissionGrant.objects.filter(
                    legacy_role_id=int(legacy_role_id),
                    permission_id=permission.code,
                )
                .order_by("-id")
                .first()
            )
        except DatabaseError as exc:
            decision.error = str(exc)
    if role_grant is not None:
        decision.role_grant = {
            "exists": True,
            "id": int(role_grant.id),
            "enabled": bool(role_grant.enabled),
            "legacy_role_id": int(role_grant.legacy_role_id),
            "note": role_grant.note or "",
        }
        decision.allowed = bool(role_grant.enabled)
        decision.level = LEVEL_ROLE_GRANT
        decision.reason = (
            f"Grant ruolo su '{permission.code}' consente accesso."
            if decision.allowed
            else f"Grant ruolo su '{permission.code}' nega accesso."
        )
        return decision
    decision.role_grant = {"exists": False, "enabled": None}

    # 6. Compat legacy: solo qui, dove il canonico non si e' espresso.
    if with_legacy_compat:
        # Import locale: acl_v2 importa questo modulo, tenerlo fuori dall'import
        # di modulo evita il ciclo.
        from core.acl_v2 import evaluate_legacy_permission_code_compat

        legacy_compat = evaluate_legacy_permission_code_compat(
            permission_code=permission.code,
            legacy_role_id=legacy_role_id,
            legacy_user_id=legacy_user_id,
            legacy_user=legacy_user,
        )
        if legacy_compat is not None:
            decision.legacy_compat = legacy_compat
            decision.allowed = bool(legacy_compat.get("enabled", False))
            decision.level = str(legacy_compat.get("source") or LEVEL_LEGACY_COMPAT)
            decision.reason = str(legacy_compat.get("reason") or "")
            return decision

    decision.allowed = False
    decision.level = LEVEL_ROLE_GRANT
    decision.reason = f"Nessuna concessione su '{permission.code}': accesso negato."
    return decision


def describe_user_groups(legacy_user_id: int | None) -> list[dict]:
    """Gruppi dell'utente in ordine di peso: serve a diagnostica e pannello."""
    if not legacy_user_id:
        return []
    try:
        groups = list(
            AccessGroup.objects.filter(
                is_active=True,
                memberships__legacy_user_id=int(legacy_user_id),
            ).order_by("-priority", "label", "id")
        )
    except DatabaseError:
        return []
    return [
        {
            "id": int(group.id),
            "code": group.code,
            "label": group.label,
            "priority": int(group.priority or 0),
        }
        for group in groups
    ]


def group_grants_map(legacy_user_id: int | None) -> dict[str, bool]:
    """Permessi decisi dai gruppi dell'utente, gia' risolti per priorita'.

    Serve a chi valuta molti permessi in un colpo solo (il menu): la regola di
    precedenza fra gruppi resta qui, non viene riscritta dal chiamante.
    """
    group_ids = user_group_ids(legacy_user_id)
    if not group_ids:
        return {}
    try:
        rows = list(
            GroupPermissionGrant.objects.filter(group_id__in=group_ids)
            .select_related("group")
            .only("enabled", "permission_id", "group__priority", "group__id")
        )
    except DatabaseError:
        return {}

    best: dict[str, tuple[int, bool]] = {}
    for row in rows:
        code = str(row.permission_id or "").strip()
        if not code:
            continue
        priority = int(row.group.priority or 0)
        enabled = bool(row.enabled)
        current = best.get(code)
        # Priorita' piu' alta; a parita' vince il diniego.
        if current is None or priority > current[0] or (priority == current[0] and not enabled):
            best[code] = (priority, enabled)
    return {code: enabled for code, (_priority, enabled) in best.items()}
