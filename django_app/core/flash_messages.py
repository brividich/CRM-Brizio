"""Messaggi flash mostrati subito, in qualunque modulo, con un unico aspetto.

Problema: molte pagine (o le risposte HTMX/fetch parziali, o i download) non
stampano i ``django.contrib.messages``. I messaggi restavano in sessione e
comparivano tutti insieme alla prima pagina che li stampava, in un altro modulo.

Consegna, in base alla risposta:

* pagina intera: ``{% flash_messages_fallback %}`` in fondo a ``core/base.html``
  mostra come toast i messaggi che il template non ha già stampato;
* richiesta asincrona (HTMX, fetch, XHR): ``FlashMessagesDeliveryMiddleware``
  mette i messaggi aggiunti *da questa richiesta* nell'header ``X-Hub-Flash``,
  letto da ``core/js/hub-flash.js`` (che intercetta fetch e XHR);
* download (``Content-Disposition: attachment``): stesso contenuto nel cookie
  ``hub_flash`` di breve durata, letto dalla pagina rimasta aperta.

Le richieste asincrone prendono solo i messaggi nuovi: un polling in background
non deve "rubare" i messaggi destinati alla pagina che sta per caricarsi.
"""

from __future__ import annotations

import base64
import json
import re

from django.contrib.messages import get_messages
from django.http import FileResponse, StreamingHttpResponse

HEADER = "X-Hub-Flash"
COOKIE = "hub_flash"
COOKIE_MAX_AGE = 120
MAX_ITEMS = 10
MAX_TEXT = 600
MAX_COOKIE_BYTES = 3000
LONG_TEXT = 160

_BREAK_RE = re.compile(r"[.;](?=\s)")


def summarize(text: str) -> str:
    """Prima frase per i messaggi lunghi (il testo intero resta nei dettagli)."""
    if len(text) <= LONG_TEXT:
        return text
    for match in _BREAK_RE.finditer(text):
        if 20 <= match.end() <= LONG_TEXT:
            cut = match.end()
        elif match.end() > LONG_TEXT:
            break
        else:
            continue
        return text[:cut]
    return text[:140].rstrip() + "…"


def group(messages_list):
    """Raggruppa i messaggi identici (stesso livello e testo) con un contatore."""
    items, index = [], {}
    for message in messages_list:
        level = message.level_tag or "info"
        text = str(message)
        key = (level, text)
        if key in index:
            index[key]["count"] += 1
            continue
        summary = summarize(text)
        item = {"level": level, "text": text, "count": 1, "summary": summary, "long": summary != text}
        index[key] = item
        items.append(item)
    return items


def pending_messages(request):
    """Tutti i messaggi non ancora mostrati in questa richiesta (vuota se già iterati)."""
    storage = getattr(request, "_messages", None)
    if storage is None or getattr(storage, "used", False):
        return []
    try:
        if not len(storage):
            return []
    except Exception:
        return []
    return list(get_messages(request))


def take_new_messages(request):
    """Messaggi aggiunti durante questa richiesta, tolti dalla coda.

    Quelli ereditati da richieste precedenti restano in sessione per la pagina
    che li deve mostrare.
    """
    storage = getattr(request, "_messages", None)
    if storage is None or getattr(storage, "used", False):
        return []
    queued = list(getattr(storage, "_queued_messages", None) or [])
    if queued:
        storage._queued_messages = []
    return queued


def _payload(items):
    return [
        {"level": item["level"], "text": item["text"][:MAX_TEXT], "count": item["count"]}
        for item in items[:MAX_ITEMS]
    ]


def _is_async(request) -> bool:
    headers = request.headers
    if headers.get("HX-Request") or headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    return headers.get("Sec-Fetch-Mode") in {"cors", "same-origin"}


def _is_download(response) -> bool:
    if response.get("Content-Disposition", "").lower().startswith("attachment"):
        return True
    if isinstance(response, (FileResponse, StreamingHttpResponse)):
        return "text/html" not in response.get("Content-Type", "")
    return False


def _cookie_value(payload):
    while payload:
        raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        value = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        if len(value) <= MAX_COOKIE_BYTES:
            return value
        payload = payload[:-1]
    return ""


class FlashMessagesDeliveryMiddleware:
    """Va messo DOPO ``MessageMiddleware``: agisce prima che salvi lo storage."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if 300 <= response.status_code < 400:
            return response
        # La pagina successiva mostrerà i messaggi: non anticiparli.
        if any(h in response for h in ("HX-Redirect", "HX-Location", "HX-Refresh")):
            return response
        if _is_async(request):
            items = group(take_new_messages(request))
            if items:
                response[HEADER] = json.dumps(_payload(items), ensure_ascii=True, separators=(",", ":"))
        elif _is_download(response):
            items = group(take_new_messages(request))
            value = _cookie_value(_payload(items)) if items else ""
            if value:
                response.set_cookie(
                    COOKIE, value, max_age=COOKIE_MAX_AGE, path="/",
                    samesite="Lax", secure=request.is_secure(), httponly=False,
                )
        return response
