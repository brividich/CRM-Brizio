from __future__ import annotations

from django.db import DatabaseError

from core.legacy_models import Permesso, UtenteLegacy
from core.legacy_cache import (
    get_cached_acl_pulsanti,
    get_cached_perm_map,
    normalize_legacy_path,
    normalize_legacy_button_url,
)
from core.legacy_utils import is_legacy_admin


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
    path_input = path or "/"
    path_norm = normalize_acl_path(path_input)
    result = {
        "path_input": path_input,
        "path_normalized": path_norm,
        "legacy_user": None,
        "is_legacy_admin": False,
        "allowed": False,
        "reason": "",
        "pulsante": None,
        "permesso": None,
        "override": None,
        "db_error": "",
    }

    if not legacy_user:
        result["reason"] = "Nessun utente legacy associato all'utente Django autenticato."
        return result

    result["legacy_user"] = {
        "id": int(legacy_user.id),
        "nome": (legacy_user.nome or "").strip(),
        "email": (legacy_user.email or "").strip(),
        "ruolo": (legacy_user.ruolo or "").strip(),
        "ruolo_id": legacy_user.ruolo_id,
        "attivo": bool(legacy_user.attivo),
    }

    if is_legacy_admin(legacy_user):
        result["is_legacy_admin"] = True
        result["allowed"] = True
        result["reason"] = "Utente riconosciuto come admin legacy: bypass ACL consentito."
        return result

    ruolo_id = legacy_user.ruolo_id
    if not ruolo_id:
        result["reason"] = "Utente senza ruolo_id legacy: ACL nega l'accesso."
        return result

    try:
        pulsante = _match_pulsante(path_norm)
        if not pulsante:
            result["reason"] = "Nessun pulsante legacy trovato che corrisponde al path richiesto."
            return result

        result["pulsante"] = {
            "id": int(pulsante["id"]),
            "label": pulsante.get("label", ""),
            "modulo": (pulsante.get("modulo") or "").strip(),
            "azione": (pulsante.get("codice") or "").strip(),
            "url": (pulsante.get("url") or "").strip(),
            "url_normalized": normalize_legacy_button_url(pulsante.get("url") or "/"),
        }

        modulo_str = (pulsante.get("modulo") or "").strip()
        azione_str = (pulsante.get("codice") or "").strip()

        # Check override per-utente
        override = _get_user_override(int(legacy_user.id), modulo_str, azione_str)
        if override is not None:
            result["override"] = {
                "can_view": override.can_view,
                "can_edit": override.can_edit,
                "can_delete": override.can_delete,
                "can_approve": override.can_approve,
            }
            if override.can_view is not None:
                result["allowed"] = override.can_view
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
            result["reason"] = "Nessun record in tabella permessi per ruolo/modulo/azione del pulsante matchato."
            return result

        can_view = getattr(perm, "can_view", None)
        consentito = getattr(perm, "consentito", None)
        allowed = bool(can_view) or (can_view is None and bool(consentito)) or bool(consentito)
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
        result["reason"] = (
            "Permesso consentito (can_view/consentito attivo)."
            if allowed
            else "Record permesso trovato ma non consente can_view/consentito."
        )
        return result
    except DatabaseError as exc:
        result["db_error"] = str(exc)
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
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    ruolo_id = getattr(legacy_user, "ruolo_id", None)
    if not ruolo_id:
        return False
    try:
        override = _get_user_override(int(legacy_user.id), modulo, azione)
        if override is not None and override.can_view is not None:
            return bool(override.can_view)
        perm_map = get_cached_perm_map(int(ruolo_id))
        key = (modulo.lower().strip(), azione.lower().strip())
        return bool(perm_map.get(key, False))
    except DatabaseError:
        return False
