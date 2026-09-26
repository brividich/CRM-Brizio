"""Configurazione guidata delle caselle mail del Security Center.

Il flusso dei dati è: casella mail (SecurityMailboxSource) -> ingestione Graph ->
messaggi -> parser -> eventi -> regole -> alert/KPI. Le «Sorgenti» della Configuration
Studio (SecuritySourceConfig) e l'autoconfigurazione descrivono solo COME riconoscere i
report: senza una casella da leggere non arriva nessun dato. Qui c'è ciò che serve per
collegarla dall'interfaccia: stato delle credenziali, anteprima senza importare,
importazione manuale.
"""
from __future__ import annotations

import os
from datetime import timedelta

from django.utils import timezone
from django.utils.text import slugify

from security.models import SecurityMailboxMessage, SecurityMailboxSource
from security.services.configuration import get_setting

GRAPH_CREDENTIAL_KEYS = ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")
PREVIEW_DAYS = 3
PREVIEW_LIMIT = 25


def graph_credentials_status():
    """Quali credenziali Graph sono presenti e da dove arrivano. MAI i valori."""
    keys = []
    for key in GRAPH_CREDENTIAL_KEYS:
        if str(get_setting(key, "") or "").strip():
            origin = "Configurazione SOC"
        elif os.getenv(key, "").strip():
            origin = "Ambiente del server (.env)"
        else:
            origin = ""
        keys.append({"key": key, "configured": bool(origin), "origin": origin})
    return {"keys": keys, "complete": all(k["configured"] for k in keys)}


def unique_code_for(name: str) -> str:
    base = slugify(name)[:70] or "casella"
    code, n = base, 2
    while SecurityMailboxSource.objects.filter(code=code).exists():
        code = f"{base}-{n}"
        n += 1
    return code


class _PreviewWindow:
    """Vista della sorgente con la finestra spostata agli ultimi giorni: l'anteprima
    mostra la posta recente e non tocca il punto da cui ripartirà l'ingestione."""

    def __init__(self, source, days):
        self._source = source
        self.last_success_at = timezone.now() - timedelta(days=days)
        # Niente download degli allegati in anteprima: serve solo capire cosa arriva.
        self.process_attachments = False

    def __getattr__(self, name):
        return getattr(self._source, name)


def preview_mailbox(source, days=PREVIEW_DAYS, limit=PREVIEW_LIMIT):
    """Legge le mail recenti SENZA importarle e dice cosa succederebbe a ciascuna.

    Ritorna ``{"ok": bool, "error": str, "rows": [...]}``; ogni riga: mittente, oggetto,
    ricevuta il, accettata dai filtri della casella, parser che la riconosce o motivo
    per cui verrebbe scartata.
    """
    from security.services.mailbox_ingestion import should_accept_message
    from security.services.mailbox_providers import get_provider
    from security.services.parser_engine import _match_enabled_parser, skip_reason

    try:
        messages = get_provider(source).list_messages(_PreviewWindow(source, days), limit=limit)
    except Exception as exc:  # credenziali, permessi Graph, casella inesistente
        return {"ok": False, "error": str(exc)[:500], "rows": []}

    rows = []
    for message in reversed(messages):  # più recenti in alto
        accepted = should_accept_message(source, message)
        # Messaggio NON salvato: serve solo a chiedere ai parser se lo riconoscono.
        probe = SecurityMailboxMessage(
            sender=message.sender or "",
            subject=message.subject or "",
            body=message.body_text or message.body_html or "",
        )
        parser = _match_enabled_parser(probe)
        detail = "" if parser else skip_reason(probe)[1]
        rows.append(
            {
                "received_at": message.received_at,
                "sender": message.sender,
                "subject": message.subject,
                "accepted": accepted,
                "parser": parser.name if parser else "",
                "detail": detail,
            }
        )
    return {"ok": True, "error": "", "rows": rows}


def run_summary(run):
    """Testo per l'utente dall'esito di un'ingestione (run_mailbox_ingestion non solleva)."""
    if run is None:
        return "warning", "Casella disattivata: nessuna lettura eseguita."
    if run.status == "failed":
        return "error", f"Lettura fallita: {run.error_message[:300]}"
    return "success", (
        f"Lettura completata: {run.imported_messages_count} mail importate, "
        f"{run.duplicate_messages_count} già presenti, {run.skipped_messages_count} scartate dai filtri, "
        f"{run.generated_alerts_count} alert generati."
    )
