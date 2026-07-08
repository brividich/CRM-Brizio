"""Risoluzione **unica** dei destinatari dei digest/reminder del portale.

Fonte di verità condivisa: prima esisteva in triplice copia quasi identica
(`anagrafica.services.reminders.get_reminder_recipients`,
`assets…send_maintenance_reminders._get_recipients`,
`monitoring.services._admin_recipients`). Ora quei tre delegano qui.

Cascata: ``override`` (CLI) → ``settings[setting_emails_key]`` (per monitoring) →
``SiteConfig[config_key]`` → ``settings.ADMINS`` → superuser attivi con email.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model

from core.models import SiteConfig


def split_emails(raw: str) -> list[str]:
    """Spezza una stringa di email separate da virgole/punti e virgola/newline."""
    cleaned = (raw or "").replace("\r", "\n").replace(",", "\n").replace(";", "\n")
    return [email.strip() for email in cleaned.split("\n") if email.strip()]


def resolve_reminder_recipients(
    *,
    config_key: str | None = None,
    override: list[str] | None = None,
    setting_emails_key: str | None = None,
) -> list[str]:
    """Destinatari del digest secondo la cascata standard.

    - ``override``: se valorizzato vince (ritornato ripulito, **non** ordinato,
      per preservare il contratto storico di ``get_reminder_recipients``).
    - ``setting_emails_key``: nome di un setting (lista o stringa csv) da provare
      prima del ``SiteConfig`` — usato da monitoring (``MONITORING_ADMIN_EMAILS``).
    - ``config_key``: chiave ``SiteConfig`` per il dominio (es. ``assets_reminder_emails``).
    - fallback: ``settings.ADMINS`` → superuser attivi con email.

    Tutti i rami non-override ritornano ``sorted(set(...))`` (deterministico).
    """
    if override:
        return [email.strip() for email in override if email.strip()]

    recipients: list[str] = []

    if setting_emails_key:
        explicit = getattr(settings, setting_emails_key, None)
        if explicit:
            if isinstance(explicit, (list, tuple)):
                recipients.extend(str(item).strip() for item in explicit if str(item).strip())
            else:
                recipients.extend(split_emails(str(explicit)))

    if not recipients and config_key:
        recipients.extend(split_emails(SiteConfig.get(config_key, "")))

    if not recipients:
        admins = getattr(settings, "ADMINS", ()) or ()
        recipients.extend(str(email).strip() for _name, email in admins if str(email).strip())

    if not recipients:
        User = get_user_model()
        recipients.extend(
            User.objects.filter(is_active=True, is_superuser=True)
            .exclude(email="")
            .values_list("email", flat=True)
            .distinct()
        )

    return sorted(set(recipients))
