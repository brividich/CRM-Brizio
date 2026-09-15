"""Accessi negati: registrarli, spiegarli in chiaro e risolverli da un punto solo.

Il 403 diceva gia' *chi* aveva deciso, ma in gergo ("Grant ruolo su
'legacy.dashboard.dashboard_anomalie_menu' nega accesso") e senza un modo di
intervenire: bisognava uscire dall'impersonazione, capire quale delle pagine
admin aprire e ritrovare il permesso. Qui stanno le tre cose che servono a
chiudere il giro:

* :func:`record_denial` annota il diniego (una riga per persona e permesso);
* :func:`describe_access` lo spiega in italiano, con lo stato di ruolo, gruppo
  e persona su tre valori: consentito, negato esplicitamente, non impostato;
* :func:`apply_resolution` scrive la decisione dell'amministratore sul layer
  canonico, invalida la cache, lascia l'audit e **ricontrolla l'esito** - perche'
  consentire al ruolo non basta se un'eccezione personale o un gruppo nega.

La decisione resta del resolver (:mod:`core.acl_resolver`): questo modulo non
ne riscrive la precedenza, la legge.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from core.acl_resolver import (
    LEVEL_GROUP_GRANT,
    LEVEL_LEGACY_COMPAT,
    LEVEL_ROLE_GRANT,
    LEVEL_USER_OVERRIDE,
    resolve_permission_decision,
)
from core.audit import log_action
from core.impersonation import display_name_for_user
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Ruolo, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.models import AclDenialEvent, PermissionDefinition, RolePermissionGrant, UserPermissionGrant

logger = logging.getLogger(__name__)

STATE_ALLOW = "allow"
STATE_DENY = "deny"
STATE_UNSET = "unset"
STATE_LABELS = {
    STATE_ALLOW: "Consentito",
    STATE_DENY: "Negato esplicitamente",
    STATE_UNSET: "Non impostato",
}

SCOPE_ROLE = "role"
SCOPE_USER = "user"
ACTION_ALLOW = "allow"
ACTION_DENY = "deny"
ACTION_RESET = "reset"

# Un 403 ripetuto (una pagina che interroga un endpoint negato, un utente che
# ricarica) non deve diventare una scrittura a richiesta.
DENIAL_THROTTLE_SECONDS = 60

FORBIDDEN_FLASH_SESSION_KEY = "_acl_resolution_flash"

_ASSET_SUFFIXES = (".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".map", ".txt", ".woff", ".woff2")


# ── Lettura ────────────────────────────────────────────────────────────────


def grant_state(row: dict | None) -> str:
    """Stato di un grant serializzato dal resolver: l'assenza di riga e' silenzio."""
    if not row or not row.get("exists"):
        return STATE_UNSET
    return STATE_ALLOW if row.get("enabled") else STATE_DENY


def permission_display(permission) -> str:
    """Nome leggibile del permesso: "Dashboard › Menu anomalie", non il codice."""
    if permission is None:
        return ""
    if isinstance(permission, dict):
        label = str(permission.get("label") or "").strip()
        code = str(permission.get("code") or "").strip()
    else:
        label = str(getattr(permission, "label", "") or "").strip()
        code = str(getattr(permission, "code", "") or "").strip()
    if not label:
        return code
    return label.replace(" - ", " › ", 1)


def acting_admin(request) -> bool:
    """L'amministratore *reale* dietro la richiesta, anche durante l'impersonazione.

    Impersonando, ``request.user`` e' la persona impersonata: chiedere a lei se e'
    admin darebbe sempre no. Conta chi ha avviato l'impersonazione, che
    ``resolve_impersonation_context`` ha gia' verificato essere admin.
    """
    if getattr(request, "impersonation_active", False):
        django_user = getattr(request, "impersonator_user", None)
        legacy_user = getattr(request, "impersonator_legacy_user", None)
    else:
        django_user = getattr(request, "user", None)
        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(django_user)
    if not getattr(django_user, "is_authenticated", False):
        return False
    return bool(getattr(django_user, "is_superuser", False)) or is_legacy_admin(legacy_user)


def actor_display(request) -> str:
    return display_name_for_user(
        django_user=getattr(request, "impersonator_user", None) or getattr(request, "user", None),
        legacy_user=getattr(request, "impersonator_legacy_user", None) or getattr(request, "legacy_user", None),
    )


def resolution_action_path() -> str:
    try:
        return reverse("admin_portale:accessi_negati_azione")
    except NoReverseMatch:
        return ""


def is_resolution_action_path(path: str) -> bool:
    target = resolution_action_path()
    if not target:
        return False
    return str(path or "").rstrip("/") == target.rstrip("/")


def _role_info(role_id: int | None) -> dict:
    if not role_id:
        return {"id": None, "name": "", "members": 0}
    name = ""
    members = 0
    try:
        role = Ruolo.objects.filter(id=int(role_id)).first()
        name = str(getattr(role, "nome", "") or "").strip()
        members = UtenteLegacy.objects.filter(ruolo_id=int(role_id), attivo=True).count()
    except DatabaseError:
        pass
    return {"id": int(role_id), "name": name or f"#{role_id}", "members": int(members)}


def _explain(decision, *, person: str, role_name: str) -> str:
    """Il perche' della decisione, in una frase che non richiede il glossario ACL."""
    if decision is None:
        return "Il permesso non esiste più nel catalogo."
    if decision.permission_inactive:
        return "Il permesso è disattivato nel catalogo: nessuna concessione ha effetto finché non viene riattivato."
    group = decision.group_grant or {}
    if decision.allowed:
        if decision.level == LEVEL_USER_OVERRIDE:
            return f"Consentito da un'eccezione personale su {person}."
        if decision.level == LEVEL_GROUP_GRANT:
            return f"Consentito dal gruppo «{group.get('group_label', '')}»."
        if decision.level == LEVEL_ROLE_GRANT:
            return f"Consentito dal ruolo «{role_name}»."
        return "Consentito dalla configurazione legacy (tabella permessi)."
    if decision.level == LEVEL_USER_OVERRIDE:
        return (
            f"C'è un'eccezione personale su {person} che nega questa pagina. "
            "L'eccezione vale più del ruolo e dei gruppi."
        )
    if decision.level == LEVEL_GROUP_GRANT:
        return (
            f"Il gruppo «{group.get('group_label', '')}» (priorità {group.get('priority', '')}) "
            "nega questa pagina, e un gruppo vale più del ruolo."
        )
    if decision.role_grant and decision.role_grant.get("exists"):
        return f"Il ruolo «{role_name}» ha questa pagina impostata su «negato»."
    if decision.level == LEVEL_LEGACY_COMPAT or decision.legacy_compat:
        return f"Nessuna regola nuova si esprime e la configurazione legacy del ruolo «{role_name}» non la concede."
    return (
        f"Nessuno ha ancora concesso questa pagina: né il ruolo «{role_name}», "
        "né un gruppo, né un'eccezione personale."
    )


def describe_access(*, legacy_user, permission_code: str) -> dict:
    """Lo stato di un permesso per una persona, pronto per essere mostrato.

    Ricalcola dal resolver, cosi' quello che si vede e' lo stato di *adesso*,
    non quello del momento in cui il 403 e' stato registrato.
    """
    code = str(permission_code or "").strip()
    permission = None
    try:
        permission = PermissionDefinition.objects.filter(code=code).first() if code else None
    except DatabaseError:
        permission = None
    person = str(getattr(legacy_user, "nome", "") or "").strip() or "questa persona"
    role = _role_info(getattr(legacy_user, "ruolo_id", None))

    decision = None
    if permission is not None and legacy_user is not None:
        decision = resolve_permission_decision(
            permission_code=code,
            legacy_user=legacy_user,
            allow_superuser=False,
            allow_legacy_admin=False,
            permission=permission,
        )

    group = (decision.group_grant if decision else None) or {}
    user_state = grant_state(decision.user_override if decision else None)
    role_state = grant_state(decision.role_grant if decision else None)
    group_state = grant_state(group) if group else STATE_UNSET

    # Cosa ottiene davvero ciascuna scelta, data la precedenza del resolver.
    role_allow_blockers = []
    if user_state == STATE_DENY:
        role_allow_blockers.append(f"l'eccezione personale che nega {person}")
    if group_state == STATE_DENY:
        role_allow_blockers.append(f"il gruppo «{group.get('group_label', '')}»")

    return {
        "permission_code": code,
        "permission_label": permission_display(permission) or code,
        "permission_exists": permission is not None,
        "permission_active": bool(getattr(permission, "is_active", False)),
        "resolvable": bool(permission is not None and permission.is_active and legacy_user is not None),
        "person": {"id": getattr(legacy_user, "id", None), "name": person},
        "role": role,
        "allowed_now": bool(decision.allowed) if decision else False,
        "decided_by": decision.level if decision else "",
        "explanation": _explain(decision, person=person, role_name=role["name"]),
        "user_state": user_state,
        "user_state_label": STATE_LABELS[user_state],
        "role_state": role_state,
        "role_state_label": STATE_LABELS[role_state],
        "group": {
            "label": group.get("group_label", ""),
            "priority": group.get("priority"),
            "state": group_state,
            "state_label": STATE_LABELS[group_state],
        }
        if group
        else None,
        "role_allow_blocked_by": " e ".join(role_allow_blockers),
        "has_user_override": user_state != STATE_UNSET,
    }


def unresolvable_reason(decision: dict, *, person: str) -> str:
    """Perche' un 403 non si risolve con un grant: va detto dove si interviene."""
    source = str(decision.get("decision_source") or "")
    if source == "legacy_fallback":
        return (
            "Questa pagina non è ancora collegata a un permesso del nuovo sistema, quindi non si "
            "concede da qui: va collegata da «ACL Route Coverage»."
        )
    if source == "canonical_permission_inactive":
        return "Il permesso di questa pagina è disattivato nel catalogo: va riattivato da «ACL Canonico»."
    if source == "deny_missing_role":
        return f"{person} non ha un ruolo assegnato: assegnalo da «Gestione Utenti»."
    if source == "deny_missing_legacy_user":
        return "L'account non è collegato a un utente del portale."
    return ""


def build_forbidden_context(request, decision: dict | None) -> dict:
    """Contesto della pagina 403: nome leggibile per tutti, pannello per l'admin."""
    decision = decision or {}
    canonical = decision.get("canonical") or {}
    permission = canonical.get("permission") or None
    context = {
        "page_label": permission_display(permission),
        "path": decision.get("path_normalized") or getattr(request, "path", ""),
        "resolve": None,
        "resolve_unavailable": "",
        "flash": None,
    }
    session = getattr(request, "session", None)
    if session is not None:
        try:
            context["flash"] = session.pop(FORBIDDEN_FLASH_SESSION_KEY, None)
        except Exception:
            context["flash"] = None

    if not (getattr(request, "impersonation_active", False) and acting_admin(request)):
        return context

    target = getattr(request, "legacy_user", None)
    person = str(getattr(target, "nome", "") or "").strip() or "questa persona"
    code = str((permission or {}).get("code") or "")
    if code and decision.get("decision_source") == "canonical":
        resolve = describe_access(legacy_user=target, permission_code=code)
        resolve["next"] = request.get_full_path() if request.method == "GET" else context["path"]
        resolve["action_url"] = resolution_action_path()
        context["resolve"] = resolve
    else:
        context["resolve_unavailable"] = unresolvable_reason(decision, person=person)
    return context


# ── Registrazione ──────────────────────────────────────────────────────────


def record_denial(request, decision: dict | None) -> None:
    """Annota un 403. Non deve mai far fallire la risposta che lo accompagna."""
    if not decision or decision.get("allowed"):
        return
    legacy_user = getattr(request, "legacy_user", None)
    legacy_user_id = getattr(legacy_user, "id", None)
    if not legacy_user_id:
        return

    permission = (decision.get("canonical") or {}).get("permission") or {}
    code = str(permission.get("code") or "")[:120]
    path = str(decision.get("path_normalized") or getattr(request, "path", "") or "")[:500]
    # Il browser chiede da solo favicon e simili: non sono pagine che qualcuno
    # ha cercato di aprire, e riempirebbero il pannello di rumore.
    if not code and path.lower().rstrip("/").endswith(_ASSET_SUFFIXES):
        return
    dedup_key = (f"perm:{code}" if code else f"path:{path}")[:300]

    digest = hashlib.sha1(f"{legacy_user_id}|{dedup_key}".encode("utf-8")).hexdigest()
    try:
        if not cache.add(f"acl_denial:{digest}", 1, DENIAL_THROTTLE_SECONDS):
            return
    except Exception:
        pass

    now = timezone.now()
    fields = {
        "legacy_role_id": getattr(legacy_user, "ruolo_id", None),
        "permission_code": code,
        "path": path,
        "route_name": str(decision.get("route_name") or "")[:160],
        "decision_source": str(decision.get("decision_source") or "")[:60],
        "reason": str(decision.get("reason") or "")[:500],
        "last_seen_at": now,
    }
    try:
        rows = AclDenialEvent.objects.filter(legacy_user_id=int(legacy_user_id), dedup_key=dedup_key)
        if rows.update(hits=F("hits") + 1, **fields):
            # Era stato consentito ma la persona e' ancora fuori: la decisione
            # non ha avuto l'effetto voluto, torna fra quelle da guardare.
            rows.filter(status=AclDenialEvent.STATUS_ALLOWED).update(
                status=AclDenialEvent.STATUS_OPEN, resolved_at=None
            )
            return
        try:
            with transaction.atomic():
                AclDenialEvent.objects.create(legacy_user_id=int(legacy_user_id), dedup_key=dedup_key, **fields)
        except IntegrityError:
            rows.update(hits=F("hits") + 1, **fields)
    except Exception:
        logger.exception("registrazione accesso negato fallita: user=%s key=%s", legacy_user_id, dedup_key)


# ── Scrittura ──────────────────────────────────────────────────────────────


def _sync_events(*, permission_code: str, legacy_user, scope: str, role_id: int | None, actor: str) -> None:
    """Allinea lo stato dei 403 registrati all'esito reale, persona per persona."""
    events = AclDenialEvent.objects.filter(
        permission_code=permission_code,
        status__in=[AclDenialEvent.STATUS_OPEN, AclDenialEvent.STATUS_ALLOWED, AclDenialEvent.STATUS_DENIED],
    )
    if scope == SCOPE_USER:
        events = events.filter(legacy_user_id=int(legacy_user.id))
    else:
        events = events.filter(legacy_role_id=int(role_id))
    events = list(events[:500])
    if not events:
        return
    users = {
        int(u.id): u
        for u in UtenteLegacy.objects.filter(id__in={int(e.legacy_user_id) for e in events})
    }
    now = timezone.now()
    for event in events:
        person = users.get(int(event.legacy_user_id))
        if person is None:
            continue
        allowed = resolve_permission_decision(
            permission_code=permission_code,
            legacy_user=person,
            allow_superuser=False,
            allow_legacy_admin=False,
        ).allowed
        new_status = AclDenialEvent.STATUS_ALLOWED if allowed else AclDenialEvent.STATUS_DENIED
        # Sugli altri membri del ruolo si registra solo cio' che la scelta ha
        # sbloccato: un "no" dato a Riccardo non e' una decisione presa su Maria.
        if int(event.legacy_user_id) != int(legacy_user.id) and not allowed:
            continue
        AclDenialEvent.objects.filter(pk=event.pk).update(status=new_status, resolved_at=now, resolved_by=actor[:200])


def apply_resolution(request, *, legacy_user, permission_code: str, scope: str, action: str) -> dict:
    """Consente o nega un permesso sul ruolo o sulla persona, e dice cosa ne e' uscito.

    Ritorna ``{"ok", "level", "message", "allowed_now"}``: ``level`` e' il livello
    del messaggio (``success`` / ``warning`` / ``error``).
    """
    code = str(permission_code or "").strip()
    if scope not in {SCOPE_ROLE, SCOPE_USER}:
        return {"ok": False, "level": "error", "message": "Scegli se intervenire sul ruolo o sulla persona.", "allowed_now": False}
    if action not in {ACTION_ALLOW, ACTION_DENY, ACTION_RESET}:
        return {"ok": False, "level": "error", "message": "Azione non riconosciuta.", "allowed_now": False}
    if action == ACTION_RESET and scope != SCOPE_USER:
        return {"ok": False, "level": "error", "message": "Solo un'eccezione personale si può togliere.", "allowed_now": False}
    if legacy_user is None:
        return {"ok": False, "level": "error", "message": "Utente non trovato.", "allowed_now": False}

    permission = PermissionDefinition.objects.filter(code=code).first() if code else None
    if permission is None:
        return {"ok": False, "level": "error", "message": "Permesso non trovato nel catalogo.", "allowed_now": False}
    if not permission.is_active:
        return {
            "ok": False,
            "level": "error",
            "message": "Il permesso è disattivato nel catalogo: riattivalo da «ACL Canonico».",
            "allowed_now": False,
        }

    person = str(legacy_user.nome or "").strip() or f"utente #{legacy_user.id}"
    role = _role_info(legacy_user.ruolo_id)
    if scope == SCOPE_ROLE and not role["id"]:
        return {"ok": False, "level": "error", "message": f"{person} non ha un ruolo assegnato.", "allowed_now": False}

    label = permission_display(permission)
    before = describe_access(legacy_user=legacy_user, permission_code=code)

    try:
        with transaction.atomic():
            if scope == SCOPE_ROLE:
                RolePermissionGrant.objects.update_or_create(
                    legacy_role_id=int(role["id"]),
                    permission_id=code,
                    defaults={"enabled": action == ACTION_ALLOW},
                )
            elif action == ACTION_RESET:
                UserPermissionGrant.objects.filter(legacy_user_id=int(legacy_user.id), permission_id=code).delete()
            else:
                UserPermissionGrant.objects.update_or_create(
                    legacy_user_id=int(legacy_user.id),
                    permission_id=code,
                    defaults={"enabled": action == ACTION_ALLOW, "note": "Da «Accessi negati»"},
                )
    except DatabaseError as exc:
        logger.exception("risoluzione accesso negato fallita: code=%s", code)
        return {"ok": False, "level": "error", "message": f"Errore durante il salvataggio: {exc}", "allowed_now": False}

    bump_legacy_cache_version()
    after = describe_access(legacy_user=legacy_user, permission_code=code)
    allowed_now = bool(after["allowed_now"])
    actor = actor_display(request)

    try:
        _sync_events(permission_code=code, legacy_user=legacy_user, scope=scope, role_id=role["id"], actor=actor)
    except DatabaseError:
        logger.exception("allineamento accessi negati fallito: code=%s", code)

    log_action(
        request,
        "acl_risolvi_accesso",
        "admin_portale",
        {
            "permission_code": code,
            "scope": scope,
            "action": action,
            "legacy_user_id": int(legacy_user.id),
            "legacy_role_id": role["id"],
            "role_name": role["name"],
            "before": {"role": before["role_state"], "user": before["user_state"], "allowed": before["allowed_now"]},
            "after": {"role": after["role_state"], "user": after["user_state"], "allowed": allowed_now},
        },
        oggetto_tipo="core.permissiondefinition",
        oggetto_id=code,
    )

    target = f"a tutto il ruolo «{role['name']}» ({role['members']} persone attive)" if scope == SCOPE_ROLE else f"solo a {person}"
    if action == ACTION_ALLOW:
        if allowed_now:
            return {"ok": True, "level": "success", "message": f"«{label}» consentito {target}.", "allowed_now": True}
        return {
            "ok": True,
            "level": "warning",
            "message": f"Salvato, ma {person} resta bloccato: {after['explanation']}",
            "allowed_now": False,
        }
    if action == ACTION_DENY:
        target = f"al ruolo «{role['name']}»" if scope == SCOPE_ROLE else f"a {person}"
        if not allowed_now:
            return {"ok": True, "level": "success", "message": f"«{label}» negato {target}.", "allowed_now": False}
        return {
            "ok": True,
            "level": "warning",
            "message": f"Salvato, ma {person} può ancora aprire la pagina: {after['explanation']}",
            "allowed_now": True,
        }
    return {
        "ok": True,
        "level": "success" if allowed_now else "warning",
        "message": f"Tolta l'eccezione personale su «{label}» per {person}. Ora: {after['explanation']}",
        "allowed_now": allowed_now,
    }


def ignore_denial(request, event: AclDenialEvent) -> None:
    AclDenialEvent.objects.filter(pk=event.pk).update(
        status=AclDenialEvent.STATUS_IGNORED,
        resolved_at=timezone.now(),
        resolved_by=actor_display(request)[:200],
    )
    log_action(
        request,
        "acl_accesso_negato_ignorato",
        "admin_portale",
        {"legacy_user_id": int(event.legacy_user_id), "dedup_key": event.dedup_key},
        oggetto_tipo="core.acldenialevent",
        oggetto_id=str(event.pk),
    )


def flash_to_forbidden(request, result: dict) -> None:
    """Il 403 e' reso dal middleware ACL, prima dei messages: passa dalla sessione."""
    session = getattr(request, "session", None)
    if session is None:
        return
    session[FORBIDDEN_FLASH_SESSION_KEY] = {"level": result.get("level", "success"), "message": result.get("message", "")}
    session.modified = True
