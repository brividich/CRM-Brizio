"""Enforcement delle preferenze notifica — punto unico condiviso.

Combina due livelli, con **precedenza all'admin**:
- **Admin globale**: una categoria può essere spenta per TUTTI (``SiteConfig``
  ``notif_cat_<categoria>_off = 1``). Default: accesa.
- **Utente**: se la categoria è accesa a livello globale, si rispetta la
  preferenza personale (``UserOnboarding.notifiche_config`` via
  ``should_send_email``). Default: accesa (fail-open).

Usato da ``core.notifiche.invia_notifica`` (in-app) e disponibile per i sender
email. Le categorie sono in ``core.notifiche_meta.CATEGORIE`` e il tipo→categoria
in ``notifica_categoria``.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_OFF_KEY_FMT = "notif_cat_{}_off"
_TRUE = {"1", "true", "on", "yes"}


def _off_key(category: str) -> str:
    return _OFF_KEY_FMT.format((category or "").strip())


def is_category_enabled_globally(category: str) -> bool:
    """True se la categoria è accesa a livello globale (admin). Default: accesa."""
    try:
        from core.models import SiteConfig

        val = str(SiteConfig.get(_off_key(category), "") or "").strip().lower()
        return val not in _TRUE
    except Exception:
        return True


def set_category_global(category: str, enabled: bool) -> None:
    """Accende/spegne una categoria a livello globale (admin)."""
    from core.models import SiteConfig

    SiteConfig.set(
        _off_key(category),
        "0" if enabled else "1",
        f"Notifiche categoria '{category}': {'accesa' if enabled else 'SPENTA (globale)'}",
    )


def global_disabled_categories() -> set[str]:
    """Insieme delle categorie spente a livello globale."""
    from core.notifiche_meta import CATEGORIE

    return {c for c in CATEGORIE if not is_category_enabled_globally(c)}


def _django_user_from_legacy(legacy_user_id):
    try:
        from core.models import Profile

        prof = (
            Profile.objects.filter(legacy_user_id=legacy_user_id)
            .select_related("user")
            .first()
        )
        return prof.user if prof else None
    except Exception:
        return None


def should_notify(*, tipo: str, legacy_user_id=None, django_user=None) -> bool:
    """True se la notifica ``tipo`` va recapitata all'utente indicato.

    Precedenza admin: categoria spenta globalmente ⇒ ``False`` per tutti.
    Altrimenti rispetta la preferenza utente (default acceso, fail-open)."""
    from core.notifiche_meta import notifica_categoria

    category = notifica_categoria(tipo)

    if not is_category_enabled_globally(category):
        return False

    user = django_user
    if user is None and legacy_user_id:
        user = _django_user_from_legacy(legacy_user_id)
    if user is None:
        return True  # nessun utente risolvibile: fail-open

    # Legge la preferenza utente DIRETTAMENTE dal JSON (non via helper del modello,
    # per non dipendere da metodi in evoluzione su UserOnboarding). Fail-open.
    try:
        from core.models import UserOnboarding

        onb = UserOnboarding.objects.filter(user=user).first()
        if onb is None:
            return True  # nessun record → acceso di default
        cfg = getattr(onb, "notifiche_config", None)
        if not isinstance(cfg, dict):
            return True
        # Valore presente per la categoria = preferenza esplicita; assente = acceso.
        return bool(cfg.get(category, True))
    except Exception:
        return True
