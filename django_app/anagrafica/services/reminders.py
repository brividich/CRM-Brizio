"""Helper condivisi per i management command di promemoria scadenze.

Risoluzione destinatari digest con cascata standard:
override CLI → ``SiteConfig`` (chiave per dominio) → ``settings.ADMINS`` →
superuser attivi con email. Estratto da ``send_visite_expiry_reminders``
(a sua volta speculare a ``dpi/send_dpi_expiry_reminders``) per evitare
una terza copia negli altri command di reminder.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model

from core.models import SiteConfig


def split_emails(raw: str) -> list[str]:
    """Spezza una stringa di email separate da virgole/punti e virgola/newline."""
    cleaned = (raw or "").replace("\r", "\n").replace(",", "\n").replace(";", "\n")
    return [email.strip() for email in cleaned.split("\n") if email.strip()]


def get_reminder_recipients(config_key: str, override: list[str] | None = None) -> list[str]:
    """Destinatari del digest: override CLI → SiteConfig → ADMINS → superuser."""
    if override:
        return [email.strip() for email in override if email.strip()]

    recipients: list[str] = []
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
