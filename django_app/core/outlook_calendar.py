"""Client Graph leggero per creare/aggiornare/eliminare eventi Outlook Calendar.

Pattern estratto da `assets/views.py` (che continua a usare la sua implementazione
locale). I moduli nuovi che creano eventi Outlook (tasks, ticket, ecc.) devono
passare da qui per evitare di duplicare logica Graph, gestione errori e config.

Credenziali attese in ambiente: `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`,
`GRAPH_CLIENT_SECRET` (alias `AZURE_*` supportati). Il token viene acquisito
tramite `core.graph_utils.acquire_graph_token` che gia gestisce cache e refresh.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests

from .graph_utils import (
    acquire_graph_token,
    invalidate_graph_token_cache,
    is_placeholder_value,
)

DEFAULT_TIMEZONE = "W. Europe Standard Time"
DEFAULT_START_HOUR = 8
DEFAULT_DURATION_MINUTES = 60
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def _get_first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value and not is_placeholder_value(value):
            return str(value).strip()
    return ""


def _graph_settings() -> dict[str, str]:
    return {
        "tenant_id":     _get_first_env("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id":     _get_first_env("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": _get_first_env("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
    }


def graph_ready() -> bool:
    config = _graph_settings()
    return all(config.values())


def _headers() -> dict[str, str]:
    config = _graph_settings()
    if not graph_ready():
        raise RuntimeError("Configurazione Graph incompleta: tenant, client o secret mancanti.")
    token = acquire_graph_token(config["tenant_id"], config["client_id"], config["client_secret"])
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def build_event_payload(
    *,
    subject: str,
    body_html: str,
    location_label: str,
    due_date: date,
    transaction_id: str,
    reminder_minutes_before_start: int | None = 15,
    start_hour: int = DEFAULT_START_HOUR,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Costruisce il payload Graph per un evento calendario.

    due_date: data di scadenza - l'evento viene creato alle start_hour di quel giorno per duration_minutes.
    transaction_id: idempotency key Graph (deve essere stabile per evitare duplicati a retry).
    reminder_minutes_before_start: se int, imposta il reminder Graph; se None, nessun reminder.
    """
    start_dt = datetime.combine(due_date, datetime.min.time()).replace(hour=start_hour)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    payload: dict[str, Any] = {
        "subject": (subject or "").strip()[:255],
        "body": {"contentType": "HTML", "content": body_html or ""},
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone_name},
        "end":   {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": timezone_name},
        "location": {"displayName": (location_label or "").strip() or "Promemoria"},
        "showAs": "busy",
        "responseRequested": False,
        "transactionId": transaction_id,
    }
    if reminder_minutes_before_start is not None:
        payload["reminderMinutesBeforeStart"] = int(reminder_minutes_before_start)
        payload["isReminderOn"] = True
    return payload


def _graph_error_message(response: requests.Response) -> str:
    """Messaggio d'errore Graph con lo stato HTTP e il codice applicativo.

    Il solo `error.message` non distingue «all'app manca il permesso» (403
    ErrorAccessDenied) da «quella cassetta non e' indirizzabile» (404
    ErrorInvalidUser): due cause diverse, due rimedi diversi, e a log restava
    solo una frase nuda da cui non si capiva quale delle due fosse.
    """
    try:
        body = response.json()
    except ValueError:
        body = {}
    err = body.get("error") if isinstance(body, dict) else None
    code = ""
    msg = ""
    if isinstance(err, dict):
        msg = str(err.get("message") or "").strip()
        code = str(err.get("code") or "").strip()
    if not msg:
        msg = (response.text or "").strip()
    context = " · ".join(part for part in (f"HTTP {response.status_code}", code) if part)
    if not msg:
        return f"Errore Graph {context}"
    # Il contesto va in coda: i chiamanti riconoscono l'errore cercando
    # sottostringhe nel testo di Graph, che resta in testa e intatto.
    return f"{msg} [{context}]"


def _raise_graph_error(response: requests.Response) -> None:
    """Solleva l'errore Graph, buttando il token se il rifiuto e' di credenziali.

    Il token sta in cache fino a un'ora: appena si concede `Calendars.ReadWrite`
    in Entra ID il portale continuerebbe a presentare il token vecchio, privo
    del nuovo ruolo, e sembrerebbe che il permesso non sia servito a niente.
    """
    if response.status_code in {401, 403}:
        config = _graph_settings()
        try:
            invalidate_graph_token_cache(
                config["tenant_id"], config["client_id"], config["client_secret"]
            )
        except Exception:  # pragma: no cover — l'errore vero e' quello sotto
            pass
    raise RuntimeError(_graph_error_message(response))


def create_event(*, target_email: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Crea un evento sul calendario dell'utente target. Ritorna il JSON Graph (contiene `id` e `webLink`)."""
    if not target_email:
        raise RuntimeError("Utente Outlook non valido.")
    url = f"{GRAPH_BASE_URL}/users/{quote(target_email, safe='')}/calendar/events"
    response = requests.post(url, headers=_headers(), json=payload, timeout=20)
    if response.status_code in {200, 201}:
        return response.json()
    _raise_graph_error(response)


def update_event(*, target_email: str, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not target_email or not event_id:
        raise RuntimeError("Outlook update: email o event_id mancanti.")
    url = f"{GRAPH_BASE_URL}/users/{quote(target_email, safe='')}/calendar/events/{quote(event_id, safe='')}"
    response = requests.patch(url, headers=_headers(), json=payload, timeout=20)
    if response.status_code in {200, 201}:
        return response.json()
    _raise_graph_error(response)


def delete_event(*, target_email: str, event_id: str) -> bool:
    """Ritorna True se l'evento e' stato eliminato o non esisteva piu'."""
    if not target_email or not event_id:
        return False
    url = f"{GRAPH_BASE_URL}/users/{quote(target_email, safe='')}/calendar/events/{quote(event_id, safe='')}"
    response = requests.delete(url, headers=_headers(), timeout=20)
    if response.status_code in {200, 202, 204, 404}:
        return True
    _raise_graph_error(response)
