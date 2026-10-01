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
        attachments = _preview_attachments(message)
        attachment_parsers = {a["parser"] for a in attachments if a["parser"]}
        detail = "" if (parser or attachment_parsers) else skip_reason(probe)[1]
        rows.append(
            {
                "received_at": message.received_at,
                "sender": message.sender,
                "subject": message.subject,
                "accepted": accepted,
                "parser": parser.name if parser else "",
                "attachments": attachments,
                "recognized": bool(parser or attachment_parsers),
                "label": "Riconosciuta" if parser else ("Allegati letti" if attachment_parsers else "Non riconosciuta"),
                "detail": detail,
            }
        )
    return {"ok": True, "error": "", "rows": rows}


def _preview_attachments(message):
    """Allegati di una mail (gli ZIP gia' aperti) e quale parser leggerebbe ciascuno."""
    from security.models import SecuritySourceFile
    from security.services.mailbox_ingestion import _expand_attachments
    from security.services.parser_engine import _match_enabled_parser
    from security.services.text_extraction import extract_text

    rows = []
    try:
        expanded = list(_expand_attachments(message.attachments or []))
    except Exception:  # noqa: BLE001 - l'anteprima non deve mai rompersi per un allegato
        return rows
    for attachment in expanded[:30]:
        text, warnings = extract_text(attachment.filename, attachment.content_bytes)
        probe = SecuritySourceFile(original_name=attachment.filename, content=text)
        parser = _match_enabled_parser(probe)
        rows.append({
            "name": attachment.filename,
            "size_kb": max(1, round((attachment.size_bytes or len(attachment.content_bytes)) / 1024)),
            "from_zip": getattr(attachment, "from_archive", ""),
            "parser": parser.name if parser else "",
            "warning": warnings[0] if warnings else "",
        })
    return rows


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


# «Importa storico»: quanto lavorare subito, dentro la richiesta web. Il resto lo smaltisce
# lo schedule security_cycle (ogni 15 minuti, max_messages_per_run mail a giro).
HISTORY_DRAIN_SECONDS = 45
HISTORY_DRAIN_MAX_RUNS = 10


def start_history_import(source, since_date, *, actor=None, request=None):
    """Riporta indietro il punto da cui riparte la lettura e smaltisce un primo blocco.

    La lettura è incrementale: la prima volta prende gli ultimi 14 giorni, poi va solo
    avanti da ``last_success_at``. Lo storico si recupera spostando quel punto indietro;
    il watermark avanza sulle mail effettivamente lette, quindi niente va perso e le mail
    già importate vengono scartate come duplicati.
    """
    import time
    from datetime import datetime

    from security.services.configuration import audit_config_change
    from security.services.mailbox_ingestion import run_mailbox_ingestion

    since = timezone.make_aware(datetime.combine(since_date, datetime.min.time()), timezone.get_current_timezone())
    old = source.last_success_at
    source.last_success_at = since
    source.save(update_fields=["last_success_at"])
    audit_config_change(actor, "history_import", source, "last_success_at", old, since, request=request)

    totals = {"runs": 0, "imported": 0, "duplicates": 0, "alerts": 0, "error": "", "caught_up": False}
    started = time.monotonic()
    while totals["runs"] < HISTORY_DRAIN_MAX_RUNS and time.monotonic() - started < HISTORY_DRAIN_SECONDS:
        before = source.last_success_at
        run = run_mailbox_ingestion(source)
        if run is None:
            totals["error"] = "Casella disattivata."
            break
        totals["runs"] += 1
        if run.status == "failed":
            totals["error"] = run.error_message[:300]
            break
        totals["imported"] += run.imported_messages_count
        totals["duplicates"] += run.duplicate_messages_count
        totals["alerts"] += run.generated_alerts_count
        source.refresh_from_db(fields=["last_success_at"])
        fetched = run.imported_messages_count + run.duplicate_messages_count + run.skipped_messages_count
        if fetched < source.max_messages_per_run:
            totals["caught_up"] = True  # ultimo blocco non pieno: casella smaltita
            break
        if source.last_success_at == before:
            break  # watermark fermo: evitare di rileggere all'infinito lo stesso blocco
    totals["reached"] = source.last_success_at
    return totals


# ---- filtri pronti per fornitore e cartelle (pagina della casella) -----------------------------

# Parole nell'oggetto delle mail dei report supportati. L'ordine conta: e' quello dei filtri consigliati.
SUBJECT_PRESETS = [
    ("watchguard", "WatchGuard (Firebox, Endpoint Security)", ["Firebox", "WatchGuard", "Threats detected", "Endpoint Security"]),
    ("synology", "Synology Active Backup", ["Active Backup", "attività di backup"]),
    ("veeam", "Veeam Backup & Replication", ["Veeam", "[Success]", "[Warning]", "[Failed]"]),
    ("defender", "Microsoft Defender", ["Defender", "vulnerabilities notification"]),
]


def recommended_subject_filters():
    return [word for _code, _label, words in SUBJECT_PRESETS for word in words]


def subject_filter_state(source):
    """``(preset attivi, righe extra)`` letti dal testo dei filtri della casella."""
    lines = [line.strip() for line in (source.subject_include_text or "").splitlines() if line.strip()]
    lowered = {line.lower() for line in lines}
    active = [code for code, _label, words in SUBJECT_PRESETS if all(word.lower() in lowered for word in words)]
    covered = {word.lower() for code, _label, words in SUBJECT_PRESETS if code in active for word in words}
    extra = [line for line in lines if line.lower() not in covered]
    return active, extra


def build_subject_filters(presets, extra_text):
    words = [word for code, _label, preset_words in SUBJECT_PRESETS if code in presets for word in preset_words]
    for line in (extra_text or "").splitlines():
        line = line.strip()
        if line and line.lower() not in {w.lower() for w in words}:
            words.append(line)
    return "\n".join(words)


def load_folders(source):
    """Cartelle della casella da Graph, per sceglierle. Mai un'eccezione verso la pagina."""
    from security.services.mailbox_providers import GraphMailboxProvider

    try:
        folders = GraphMailboxProvider().folder_tree(source)
    except Exception as exc:  # credenziali, permessi, casella inesistente
        return {"ok": False, "error": str(exc)[:400], "folders": []}
    chosen = {entry.get("id") for entry in source.folders or [] if isinstance(entry, dict)}
    for folder in folders:
        folder["checked"] = folder["id"] in chosen
    return {"ok": True, "error": "", "folders": folders}
