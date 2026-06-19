"""
Configurazione del report scadenze (visite mediche / contratti), gestita da UI.

Centralizza chiavi SiteConfig, default e (de)serializzazione tipizzata cosi' che
sia il management command `report_scadenze_settimanale` sia la pagina Impostazioni
del modulo automazioni leggano/scrivano dalla stessa fonte, senza che il cliente
debba toccare CLI, .env o cron. La cadenza (lunedi 06:00) e' fissa: lo Schedule
django-q resta sempre registrato e il command si auto-silenzia se 'attivo' e' off.
"""
from __future__ import annotations

from django.conf import settings

# ── Chiavi SiteConfig ──────────────────────────────────────────────────────
KEY_ATTIVO = "scadenze_report_attivo"
KEY_GIORNI = "scadenze_report_giorni"
KEY_EMAIL_VISITE = "scadenze_email_sorveglianza_sanitaria"
KEY_EMAIL_CONTRATTI = "scadenze_email_hr_personale"
KEY_EMAIL_QUALIFICHE = "scadenze_email_qualifiche"
KEY_INCLUDI_VISITE = "scadenze_includi_visite"
KEY_INCLUDI_CONTRATTI = "scadenze_includi_contratti"
KEY_INCLUDI_QUALIFICHE = "scadenze_includi_qualifiche"

DEFAULT_GIORNI = 30
GIORNI_MIN = 1
GIORNI_MAX = 365

# Cadenza fissa mostrata in UI e usata dallo Schedule django-q.
CADENZA_LABEL = "Ogni lunedì alle 06:00"
CADENZA_CRON = "0 6 * * 1"


def _parse_bool(raw: str, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "on", "yes", "si", "sì"}


def _emails(raw: str) -> list[str]:
    """Normalizza una stringa email separata da virgola/; in lista pulita."""
    if not raw:
        return []
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",")]
    return [p for p in parts if p]


def get_scadenze_config() -> dict:
    """Legge la configurazione corrente da SiteConfig con fallback ai default.

    Degrada in sicurezza (SiteConfig.get assorbe DatabaseError ritornando il default).
    """
    from core.models import SiteConfig

    fallback_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""

    try:
        giorni = int(SiteConfig.get(KEY_GIORNI, "") or DEFAULT_GIORNI)
    except (TypeError, ValueError):
        giorni = DEFAULT_GIORNI
    giorni = max(GIORNI_MIN, min(giorni, GIORNI_MAX))

    email_visite_raw = SiteConfig.get(KEY_EMAIL_VISITE, "") or fallback_email
    email_contratti_raw = SiteConfig.get(KEY_EMAIL_CONTRATTI, "") or fallback_email
    email_qualifiche_raw = SiteConfig.get(KEY_EMAIL_QUALIFICHE, "") or fallback_email

    return {
        "attivo": _parse_bool(SiteConfig.get(KEY_ATTIVO, ""), default=False),
        "giorni": giorni,
        "email_visite_raw": SiteConfig.get(KEY_EMAIL_VISITE, ""),
        "email_contratti_raw": SiteConfig.get(KEY_EMAIL_CONTRATTI, ""),
        "email_qualifiche_raw": SiteConfig.get(KEY_EMAIL_QUALIFICHE, ""),
        "email_visite": _emails(email_visite_raw),
        "email_contratti": _emails(email_contratti_raw),
        "email_qualifiche": _emails(email_qualifiche_raw),
        "includi_visite": _parse_bool(SiteConfig.get(KEY_INCLUDI_VISITE, ""), default=True),
        "includi_contratti": _parse_bool(SiteConfig.get(KEY_INCLUDI_CONTRATTI, ""), default=True),
        "includi_qualifiche": _parse_bool(SiteConfig.get(KEY_INCLUDI_QUALIFICHE, ""), default=True),
        "cadenza_label": CADENZA_LABEL,
    }


def save_scadenze_config(
    *,
    attivo: bool,
    giorni: int,
    email_visite: str,
    email_contratti: str,
    includi_visite: bool,
    includi_contratti: bool,
    email_qualifiche: str = "",
    includi_qualifiche: bool = True,
) -> bool:
    """Persiste la configurazione in SiteConfig. Ritorna True se tutto salvato."""
    from core.models import SiteConfig

    try:
        giorni = int(giorni)
    except (TypeError, ValueError):
        giorni = DEFAULT_GIORNI
    giorni = max(GIORNI_MIN, min(giorni, GIORNI_MAX))

    ok = True
    ok &= SiteConfig.set(KEY_ATTIVO, "1" if attivo else "0",
                         "Report scadenze: attiva/disattiva l'invio settimanale.")
    ok &= SiteConfig.set(KEY_GIORNI, str(giorni),
                         "Report scadenze: giorni di anticipo (finestra di preavviso).")
    ok &= SiteConfig.set(KEY_EMAIL_VISITE, str(email_visite or "").strip(),
                         "Report scadenze: destinatari visite mediche (sorveglianza sanitaria).")
    ok &= SiteConfig.set(KEY_EMAIL_CONTRATTI, str(email_contratti or "").strip(),
                         "Report scadenze: destinatari contratti / periodi di prova (HR).")
    ok &= SiteConfig.set(KEY_EMAIL_QUALIFICHE, str(email_qualifiche or "").strip(),
                         "Report scadenze: destinatari qualifiche / abilitazioni (formazione/HSE).")
    ok &= SiteConfig.set(KEY_INCLUDI_VISITE, "1" if includi_visite else "0",
                         "Report scadenze: includi le visite mediche.")
    ok &= SiteConfig.set(KEY_INCLUDI_CONTRATTI, "1" if includi_contratti else "0",
                         "Report scadenze: includi contratti e periodi di prova.")
    ok &= SiteConfig.set(KEY_INCLUDI_QUALIFICHE, "1" if includi_qualifiche else "0",
                         "Report scadenze: includi qualifiche e abilitazioni.")
    return ok
