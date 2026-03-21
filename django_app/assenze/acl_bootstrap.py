from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, transaction

from core.acl_bootstrap_base import init_missing_permessi, set_ui_meta
from core.legacy_cache import bump_legacy_cache_version, normalize_legacy_button_url
from core.legacy_models import Pulsante

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "assenze_acl_bootstrap_v2"
_BOOTSTRAP_TTL_SECONDS = 300


def _calendar_acl_identity() -> tuple[str, str]:
    """Rileva modulo+codice del pulsante calendario assenze già registrato."""
    fallback = ("assenze", "assenze_calendario")
    try:
        for pulsante in Pulsante.objects.all():
            norm = normalize_legacy_button_url(pulsante.url or "")
            if norm == "/assenze/calendario":
                modulo = (pulsante.modulo or "").strip() or fallback[0]
                codice = (pulsante.codice or "").strip() or fallback[1]
                return modulo, codice
    except DatabaseError:
        return fallback
    return fallback


def bootstrap_assenze_acl_endpoints(force: bool = False) -> None:
    if not force and cache.get(_BOOTSTRAP_CACHE_KEY):
        return

    calendar_modulo, calendar_codice = _calendar_acl_identity()
    definitions = [
        {"modulo": calendar_modulo, "codice": calendar_codice, "label": "Assenze API Eventi (Calendario)", "url": "/assenze/api/eventi", "allow_acl_match": False},
        {"modulo": "assenze", "codice": "assenze_eventi_colors", "label": "Assenze API Colori Calendario", "url": "/assenze/api/eventi/colors", "allow_acl_match": True},
        {"modulo": "assenze", "codice": "assenze_evento_update", "label": "Assenze API Modifica Evento", "url": "/assenze/api/eventi/update", "allow_acl_match": True},
        {"modulo": "assenze", "codice": "assenze_evento_delete", "label": "Assenze API Elimina Evento", "url": "/assenze/api/eventi/delete", "allow_acl_match": True},
        {"modulo": "assenze", "codice": "assenze_sync_push", "label": "Assenze Sync Push SharePoint", "url": "/assenze/api/sync/push", "allow_acl_match": True},
        {"modulo": "assenze", "codice": "assenze_sync_pull", "label": "Assenze Sync Pull SharePoint", "url": "/assenze/api/sync/pull", "allow_acl_match": True},
    ]

    changed = False
    created_ids: list[int] = []
    try:
        with transaction.atomic():
            for item in definitions:
                # assenze usa allow_acl_match per il calendario: lookup solo per URL
                from core.legacy_models import Pulsante as _Pulsante
                modulo = item["modulo"]
                codice = item["codice"]
                label = item["label"]
                url = item["url"]
                allow_match = bool(item["allow_acl_match"])

                pulsante_id = None
                item_changed = False
                try:
                    pulsante = _Pulsante.objects.filter(url__iexact=url).order_by("-id").first()
                    if pulsante is None and allow_match:
                        pulsante = _Pulsante.objects.filter(modulo__iexact=modulo, codice__iexact=codice).order_by("-id").first()
                except DatabaseError:
                    continue

                if pulsante is None:
                    try:
                        pulsante = _Pulsante.objects.create(
                            codice=codice, nome_visibile=label, modulo=modulo, url=url, icona="lock"
                        )
                        item_changed = True
                    except DatabaseError:
                        continue
                else:
                    updates = []
                    if (pulsante.modulo or "").strip() != modulo:
                        pulsante.modulo = modulo
                        updates.append("modulo")
                    if allow_match and (pulsante.codice or "").strip() != codice:
                        pulsante.codice = codice
                        updates.append("codice")
                    if (pulsante.url or "").strip() != url:
                        pulsante.url = url
                        updates.append("url")
                    if (label or "").strip() and (pulsante.nome_visibile or "").strip() != (label or "").strip():
                        pulsante.nome_visibile = label
                        updates.append("nome_visibile")
                    if updates:
                        try:
                            pulsante.save(update_fields=updates)
                            item_changed = True
                        except DatabaseError:
                            continue

                pulsante_id = int(pulsante.id)
                created_ids.append(pulsante_id)
                changed = changed or item_changed

                try:
                    init_missing_permessi(modulo, codice)
                except Exception:
                    pass

    except Exception as exc:
        logger.debug("ACL bootstrap assenze skipped: %s", exc)
        return

    for pid in created_ids:
        set_ui_meta(pid, section="assenze_api", visible_topbar=False)

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass

    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL_SECONDS)
