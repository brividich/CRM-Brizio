"""Messaggi flash mostrati subito, in qualunque modulo.

Problema: molte pagine (o le risposte HTMX parziali) non stampano i
``django.contrib.messages``. I messaggi restavano in sessione e comparivano
tutti insieme alla prima pagina che li stampava, magari in un altro modulo.

Due rimedi complementari:

* ``{% flash_messages_fallback %}`` in ``core/base.html``: se il template della
  pagina non ha già iterato i messaggi, li mostra come toast.
* ``HtmxFlashMessagesMiddleware``: su una risposta HTMX non-redirect consuma i
  messaggi pendenti e li consegna nell'header ``HX-Trigger`` (evento
  ``hubFlash``), che ``core/base.html`` trasforma in toast.
"""

from __future__ import annotations

import json

from django.contrib.messages import get_messages

HX_EVENT = "hubFlash"


def pending_messages(request):
    """Messaggi non ancora mostrati in questa richiesta (lista vuota se già iterati)."""
    storage = getattr(request, "_messages", None)
    if storage is None or getattr(storage, "used", False):
        return []
    try:
        if not len(storage):
            return []
    except Exception:
        return []
    return list(get_messages(request))


def serialize(messages_list):
    return [{"level": m.level_tag or "info", "text": str(m)} for m in messages_list]


class HtmxFlashMessagesMiddleware:
    """Va messo DOPO ``MessageMiddleware``: deve agire prima che salvi lo storage."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.headers.get("HX-Request"):
            return response
        if not (200 <= response.status_code < 300):
            return response
        # La pagina successiva mostrerà i messaggi: non anticiparli.
        if any(h in response for h in ("HX-Redirect", "HX-Location", "HX-Refresh")):
            return response
        items = serialize(pending_messages(request))
        if not items:
            return response
        triggers = {}
        existing = response.get("HX-Trigger", "")
        if existing:
            try:
                parsed = json.loads(existing)
                triggers = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                triggers = {name.strip(): None for name in existing.split(",") if name.strip()}
        triggers[HX_EVENT] = items
        response["HX-Trigger"] = json.dumps(triggers, ensure_ascii=True)
        return response
