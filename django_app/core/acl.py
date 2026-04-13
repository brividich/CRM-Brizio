from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError

from core.legacy_models import Permesso, Ruolo, UtenteLegacy
from core.legacy_cache import (
    get_cached_acl_pulsanti,
    get_cached_perm_map,
    normalize_legacy_path,
    normalize_legacy_button_url,
)
from core.legacy_utils import get_admin_role_ids, is_legacy_admin


logger = logging.getLogger(__name__)
_ACL_LOG_ONCE_TTL_SECONDS = 300

_ACL_REASON_NO_LEGACY_USER = "no_legacy_user"
_ACL_REASON_ADMIN_BYPASS = "admin_bypass"
_ACL_REASON_NO_ROLE = "no_role_id"
_ACL_REASON_NO_BUTTON = "no_pulsante_match"
_ACL_REASON_OVERRIDE_ALLOW = "user_override_allow"
_ACL_REASON_OVERRIDE_DENY = "user_override_deny"
_ACL_REASON_PERM_MISSING = "missing_permission_record"
_ACL_REASON_PERM_ALLOW = "role_permission_allow"
_ACL_REASON_PERM_DENY = "role_permission_deny"
_ACL_REASON_DB_ERROR = "db_error"


def _get_user_override(legacy_user_id: int, modulo: str, azione: str):
    """Restituisce il record UserPermissionOverride se esiste, altrimenti None."""
    try:
        from core.models import UserPermissionOverride
        return UserPermissionOverride.objects.filter(
            legacy_user_id=legacy_user_id,
            modulo__iexact=modulo,
            azione__iexact=azione,
        ).first()
    except Exception:
        return None


def normalize_acl_path(path: str) -> str:
    return normalize_legacy_path(path)


def _safe_int(value) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_role_name(role_id: int | None) -> str:
    rid = _safe_int(role_id)
    if rid is None:
        return ""
    try:
        role = Ruolo.objects.filter(id=rid).only("nome").first()
    except DatabaseError:
        return ""
    return str(getattr(role, "nome", "") or "").strip()


def _is_admin_role_id(role_id: int | None) -> bool:
    rid = _safe_int(role_id)
    if rid is None:
        return False
    return int(rid) in get_admin_role_ids()


def _log_once_warning(cache_key: str, message: str, **extra) -> None:
    key = f"acl:log:warning:{cache_key}"
    try:
        if not cache.add(key, 1, timeout=_ACL_LOG_ONCE_TTL_SECONDS):
            return
    except Exception:
        pass
    logger.warning(message, extra=extra)


def _path_variants(path_norm: str) -> set[str]:
    norm = normalize_acl_path(path_norm)
    variants = {norm}
    if norm == "/":
        variants.add("/dashboard")
    elif norm == "/dashboard":
        variants.add("/")
    if norm.startswith("/dashboard/"):
        short_path = norm[len("/dashboard"):]
        if short_path:
            variants.add(normalize_acl_path(short_path))

    parts = norm.split("/")
    if len(parts) > 2 and parts[1] in {"admin", "dashboard", "assenze"}:
        variants.add(normalize_acl_path("/" + parts[2]))
    return variants


def _match_pulsante(path_norm: str):
    candidates = []
    seen = set()
    variants = _path_variants(path_norm)
    for pulsante in get_cached_acl_pulsanti():
        url_norm = pulsante.get("url_normalized") or ""
        if not url_norm:
            continue
        for variant in variants:
            if variant == url_norm or variant.startswith(url_norm + "/"):
                pulsante_id = int(pulsante["id"])
                if pulsante_id in seen:
                    break
                seen.add(pulsante_id)
                candidates.append(pulsante)
                break
    if not candidates:
        return None
    return candidates[0]


def _perm_allowed(perm: Permesso | None) -> bool:
    if not perm:
        return False
    can_view = getattr(perm, "can_view", None)
    consentito = getattr(perm, "consentito", None)
    return bool(can_view) or bool(consentito)


def check_permesso(legacy_user: UtenteLegacy | None, path: str) -> bool:
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    ruolo_id = legacy_user.ruolo_id
    if not ruolo_id:
        return False

    path_norm = normalize_acl_path(path)
    try:
        pulsante = _match_pulsante(path_norm)
        if not pulsante:
            _log_once_warning(
                cache_key=f"no-pulsante:{path_norm}",
                message="ACL: nessun pulsante matchato per un path protetto.",
                path=path_norm,
                legacy_user_id=_safe_int(getattr(legacy_user, "id", None)),
            )
            return False
        modulo = (pulsante.get("modulo") or "").strip()
        azione = (pulsante.get("codice") or "").strip()

        # Override per-utente ha precedenza sul ruolo
        override = _get_user_override(int(legacy_user.id), modulo, azione)
        if override is not None and override.can_view is not None:
            return override.can_view

        perm_map = get_cached_perm_map(int(ruolo_id))
        key = ((pulsante.get("modulo_norm") or "").strip(), (pulsante.get("codice_norm") or "").strip())
        return bool(perm_map.get(key, False))
    except DatabaseError:
        return False


def diagnose_permesso(legacy_user: UtenteLegacy | None, path: str) -> dict:
    return diagnose_permesso_for_context(legacy_user=legacy_user, path=path, forced_role_id=None)


def diagnose_permesso_for_context(
    *,
    legacy_user: UtenteLegacy | None,
    path: str,
    forced_role_id: int | None = None,
) -> dict:
    path_input = path or "/"
    path_norm = normalize_acl_path(path_input)
    variants = sorted(_path_variants(path_norm))
    forced_role_int = _safe_int(forced_role_id)
    result = {
        "path_input": path_input,
        "path_normalized": path_norm,
        "path_variants": variants,
        "legacy_user": None,
        "role": None,
        "forced_role_id": forced_role_int,
        "effective_role_id": None,
        "is_legacy_admin": False,
        "admin_bypass": False,
        "allowed": False,
        "reason_code": "",
        "decision_source": "",
        "reason": "",
        "pulsante": None,
        "matched_variant": "",
        "permesso": None,
        "override": None,
        "db_error": "",
        "legacy_involvement": {
            "engine": "legacy_acl",
            "forced_role_simulation": bool(forced_role_int is not None),
        },
    }

    if legacy_user:
        user_role_id = _safe_int(getattr(legacy_user, "ruolo_id", None))
        result["legacy_user"] = {
            "id": int(legacy_user.id),
            "nome": (legacy_user.nome or "").strip(),
            "email": (legacy_user.email or "").strip(),
            "ruolo": (legacy_user.ruolo or "").strip(),
            "ruolo_id": user_role_id,
            "attivo": bool(legacy_user.attivo),
        }

    effective_role_id = forced_role_int
    if effective_role_id is None and legacy_user:
        effective_role_id = _safe_int(getattr(legacy_user, "ruolo_id", None))
    result["effective_role_id"] = effective_role_id
    if effective_role_id is not None:
        result["role"] = {
            "id": int(effective_role_id),
            "nome": _resolve_role_name(effective_role_id),
            "is_admin_role": _is_admin_role_id(effective_role_id),
        }

    user_is_admin = bool(legacy_user and is_legacy_admin(legacy_user))
    role_is_admin = bool(effective_role_id is not None and _is_admin_role_id(effective_role_id))
    if user_is_admin or role_is_admin:
        result["is_legacy_admin"] = user_is_admin
        result["admin_bypass"] = True
        result["allowed"] = True
        result["decision_source"] = "admin_bypass"
        result["reason_code"] = _ACL_REASON_ADMIN_BYPASS
        result["reason"] = (
            "Utente riconosciuto come admin legacy: bypass ACL consentito."
            if user_is_admin
            else "Ruolo selezionato riconosciuto come admin: bypass ACL simulato."
        )
        return result

    if not legacy_user and effective_role_id is None:
        result["decision_source"] = "input"
        result["reason_code"] = _ACL_REASON_NO_LEGACY_USER
        result["reason"] = "Nessun utente legacy associato all'utente Django autenticato."
        return result

    ruolo_id = effective_role_id
    if not ruolo_id:
        result["decision_source"] = "input"
        result["reason_code"] = _ACL_REASON_NO_ROLE
        result["reason"] = "Utente senza ruolo_id legacy: ACL nega l'accesso."
        return result

    try:
        pulsante = _match_pulsante(path_norm)
        if not pulsante:
            result["decision_source"] = "button_match"
            result["reason_code"] = _ACL_REASON_NO_BUTTON
            result["reason"] = "Nessun pulsante legacy trovato che corrisponde al path richiesto."
            return result

        matched_variant = ""
        url_norm = (pulsante.get("url_normalized") or "").strip()
        for variant in variants:
            if variant == url_norm or variant.startswith(url_norm + "/"):
                matched_variant = variant
                break

        result["pulsante"] = {
            "id": int(pulsante["id"]),
            "label": pulsante.get("label", ""),
            "modulo": (pulsante.get("modulo") or "").strip(),
            "azione": (pulsante.get("codice") or "").strip(),
            "url": (pulsante.get("url") or "").strip(),
            "url_normalized": normalize_legacy_button_url(pulsante.get("url") or "/"),
        }
        result["matched_variant"] = matched_variant

        modulo_str = (pulsante.get("modulo") or "").strip()
        azione_str = (pulsante.get("codice") or "").strip()

        # Check override per-utente
        if legacy_user:
            override = _get_user_override(int(legacy_user.id), modulo_str, azione_str)
            if override is not None:
                result["override"] = {
                    "can_view": override.can_view,
                    "can_edit": override.can_edit,
                    "can_delete": override.can_delete,
                    "can_approve": override.can_approve,
                }
                if override.can_view is not None:
                    result["allowed"] = bool(override.can_view)
                    result["decision_source"] = "user_override"
                    result["reason_code"] = (
                        _ACL_REASON_OVERRIDE_ALLOW if override.can_view else _ACL_REASON_OVERRIDE_DENY
                    )
                    result["reason"] = (
                        "Override per-utente attivo: accesso consentito."
                        if override.can_view
                        else "Override per-utente attivo: accesso negato."
                    )
                    return result

        perm = (
            Permesso.objects.filter(
                ruolo_id=ruolo_id,
                modulo__iexact=modulo_str,
                azione__iexact=azione_str,
            )
            .order_by("-id")
            .first()
        )
        if not perm:
            result["decision_source"] = "role_permission"
            result["reason_code"] = _ACL_REASON_PERM_MISSING
            result["reason"] = "Nessun record in tabella permessi per ruolo/modulo/azione del pulsante matchato."
            return result

        can_view = getattr(perm, "can_view", None)
        consentito = getattr(perm, "consentito", None)
        allowed = _perm_allowed(perm)
        result["permesso"] = {
            "id": int(perm.id),
            "ruolo_id": perm.ruolo_id,
            "modulo": (perm.modulo or "").strip(),
            "azione": (perm.azione or "").strip(),
            "consentito": consentito,
            "can_view": can_view,
            "can_edit": getattr(perm, "can_edit", None),
            "can_delete": getattr(perm, "can_delete", None),
            "can_approve": getattr(perm, "can_approve", None),
        }
        result["allowed"] = allowed
        result["decision_source"] = "role_permission"
        result["reason_code"] = _ACL_REASON_PERM_ALLOW if allowed else _ACL_REASON_PERM_DENY
        result["reason"] = (
            "Permesso consentito (can_view/consentito attivo)."
            if allowed
            else "Record permesso trovato ma non consente can_view/consentito."
        )
        return result
    except DatabaseError as exc:
        result["db_error"] = str(exc)
        result["decision_source"] = "database"
        result["reason_code"] = _ACL_REASON_DB_ERROR
        result["reason"] = "Errore database durante la verifica ACL."
        return result


def user_can_modulo_action(request, modulo: str, azione: str) -> bool:
    """Controlla se l'utente ha can_view=True per modulo+azione nel sistema Permessi.
    Superuser e legacy admin hanno sempre accesso.
    Per gli altri ruoli, la visibilità è gestita dal pannello Accessi."""
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is None:
        from core.legacy_utils import get_legacy_user
        legacy_user = get_legacy_user(request.user)
    return bool(
        evaluate_modulo_action_access(
            legacy_user=legacy_user,
            modulo=modulo,
            azione=azione,
        ).get("allowed", False)
    )


def evaluate_modulo_action_access(*, legacy_user: UtenteLegacy | None, modulo: str, azione: str) -> dict:
    """Valuta l'accesso legacy per uno specifico modulo+azione."""
    modulo_norm = str(modulo or "").strip().lower()
    azione_norm = str(azione or "").strip().lower()
    result = {
        "allowed": False,
        "source": "input",
        "reason": "",
        "modulo": modulo_norm,
        "azione": azione_norm,
        "role_id": _safe_int(getattr(legacy_user, "ruolo_id", None)) if legacy_user else None,
        "override": None,
        "db_error": "",
    }
    if not legacy_user:
        result["reason"] = "Utente legacy assente."
        return result
    if is_legacy_admin(legacy_user):
        result["allowed"] = True
        result["source"] = "legacy_admin"
        result["reason"] = "Utente riconosciuto come admin legacy."
        return result
    ruolo_id = result["role_id"]
    if not ruolo_id or not modulo_norm or not azione_norm:
        result["reason"] = "Ruolo legacy o coordinate modulo/azione mancanti."
        return result
    try:
        override = _get_user_override(int(legacy_user.id), modulo_norm, azione_norm)
        if override is not None and override.can_view is not None:
            allowed = bool(override.can_view)
            result["allowed"] = allowed
            result["source"] = "user_override"
            result["reason"] = (
                "Override utente legacy consente accesso."
                if allowed
                else "Override utente legacy nega accesso."
            )
            result["override"] = {"exists": True, "can_view": allowed}
            return result

        perm_map = get_cached_perm_map(int(ruolo_id))
        key = (modulo_norm, azione_norm)
        allowed = bool(perm_map.get(key, False))
        result["allowed"] = allowed
        result["source"] = "role_permission"
        result["reason"] = (
            "Permesso ruolo legacy consente accesso."
            if allowed
            else "Permesso ruolo legacy assente o non abilitato."
        )
        result["override"] = {"exists": False, "can_view": None}
        return result
    except DatabaseError as exc:
        result["source"] = "database"
        result["reason"] = "Errore database durante la verifica modulo/azione legacy."
        result["db_error"] = str(exc)
        return result
