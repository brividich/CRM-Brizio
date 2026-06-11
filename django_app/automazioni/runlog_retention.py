"""Retention configurabile dei RunLog automazioni (GDPR - limitazione conservazione).

`AutomationRunLog.payload_json` puo' contenere dati personali (nominativi CC/CAR,
email, autori) ripresi dal record che ha innescato la regola. Per il principio di
limitazione della conservazione (art. 5(1)(e) GDPR) i log operativi/diagnostici
vanno cancellati quando non piu' necessari allo scopo (debug del motore).

La finestra di conservazione e' una decisione del TITOLARE del trattamento, non
tecnica: qui forniamo un default ragionevole per log applicativi (90 giorni) ma
reso configurabile via SiteConfig dalla pagina Impostazioni automazioni, cosi'
puo' essere allineata alla policy aziendale senza toccare codice o cron.

NB: questo NON e' l'audit trail legale del portale (core.log_action), che ha le
proprie regole e non va toccato da qui.
"""
from __future__ import annotations

# -- Chiave SiteConfig e default ------------------------------------------
KEY_RETENTION_DAYS = "automazioni_runlog_retention_days"

DEFAULT_RETENTION_DAYS = 90   # default per log operativi/diagnostici
RETENTION_MIN = 7             # sotto questa soglia si perde utilita' diagnostica
RETENTION_MAX = 3650          # 10 anni: tetto di sicurezza


def _clamp_int(raw, default: int, lo: int, hi: int) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(v, hi))


def get_retention_days() -> int:
    """Giorni di conservazione dei RunLog automazioni (da SiteConfig, con default).

    Degrada in sicurezza: se SiteConfig non e' leggibile ritorna il default.
    """
    try:
        from core.models import SiteConfig
        raw = SiteConfig.get(KEY_RETENTION_DAYS, "")
    except Exception:
        return DEFAULT_RETENTION_DAYS
    return _clamp_int(raw, DEFAULT_RETENTION_DAYS, RETENTION_MIN, RETENTION_MAX)


def set_retention_days(days) -> int:
    """Salva la finestra di retention in SiteConfig (clampata) e ritorna il valore salvato."""
    value = _clamp_int(days, DEFAULT_RETENTION_DAYS, RETENTION_MIN, RETENTION_MAX)
    from core.models import SiteConfig
    SiteConfig.set(
        KEY_RETENTION_DAYS,
        str(value),
        "Giorni di conservazione dei RunLog automazioni (GDPR - limitazione conservazione).",
    )
    return value
