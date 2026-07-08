"""Helper condivisi per i management command di promemoria scadenze.

Risoluzione destinatari digest con cascata standard:
override CLI → ``SiteConfig`` (chiave per dominio) → ``settings.ADMINS`` →
superuser attivi con email. Estratto da ``send_visite_expiry_reminders``
(a sua volta speculare a ``dpi/send_dpi_expiry_reminders``) per evitare
una terza copia negli altri command di reminder.
"""

from __future__ import annotations

# Fonte unica: core.reminder_recipients. Restano qui come API storica dei
# management command di reminder (import invariati), ma delegano al canonico.
from core.reminder_recipients import resolve_reminder_recipients, split_emails  # noqa: F401


def get_reminder_recipients(config_key: str, override: list[str] | None = None) -> list[str]:
    """Destinatari del digest: override CLI → SiteConfig → ADMINS → superuser.

    Wrapper sottile su :func:`core.reminder_recipients.resolve_reminder_recipients`.
    """
    return resolve_reminder_recipients(config_key=config_key, override=override)
