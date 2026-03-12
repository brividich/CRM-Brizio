from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.backends.signals import connection_created
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Pulsante


@receiver(post_save, sender=Pulsante)
@receiver(post_delete, sender=Pulsante)
@receiver(post_save, sender=Permesso)
@receiver(post_delete, sender=Permesso)
def invalidate_legacy_acl_cache(sender, **kwargs):
    if kwargs.get("raw", False):
        return
    transaction.on_commit(bump_legacy_cache_version)


@receiver(connection_created)
def enable_sql_debug_cursor(sender, connection, **kwargs):
    """Forza il debug cursor quando il tracciamento SQL e' abilitato da settings/env."""
    if getattr(settings, "SQL_LOG_FORCE_DEBUG_CURSOR", False):
        connection.force_debug_cursor = True
