"""Servizio per invio email di azione anomalie con token sicuro monouso.

Uso:
    from anomalie.mail_action_service import build_anomalie_action_email, send_anomalie_action_email

    token = send_anomalie_action_email(
        recipient_user=request.user,          # o None se non disponibile
        recipient_email="cc@esempio.it",
        recipient_display="Mario Rossi",
        recipient_legacy_user_id=42,
        op_id="OP-2026-001",
        op_nominativo="Lavorazione flangia",
        anomalie_rows=[{"id": 1, "descrizione": "...", ...}, ...],
        action="visualizza",
        expires_hours=48,
        source_automation="anomalia_segnalata",
    )
    # token è l'istanza AnomaliaMailActionToken creata e inviata
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

# Soglia oltre la quale la mail tronca l'elenco a MAX_ANOMALIE_IN_EMAIL
MAX_ANOMALIE_IN_EMAIL = 10


def build_anomalie_action_email(
    *,
    recipient_email: str,
    recipient_display: str,
    op_id: str,
    op_nominativo: str,
    anomalie_rows: list[dict],
    action: str,
    token_str: str,
    expires_at,
    site_url: str | None = None,
) -> tuple[str, str, str]:
    """Costruisce (subject, body_text, body_html) per l'email di notifica anomalie.

    Non invia: restituisce le tre stringhe per poter testare il rendering separatamente.
    """
    if site_url is None:
        site_url = getattr(settings, "SITE_URL", "").rstrip("/")

    action_url = site_url + reverse("anomalie_mail_action", kwargs={"token": token_str})

    n_tot = len(anomalie_rows)
    troncato = n_tot > MAX_ANOMALIE_IN_EMAIL
    anomalie_visibili = anomalie_rows[:MAX_ANOMALIE_IN_EMAIL]

    action_labels = {
        "prendi_in_carico": "Prendi in carico",
        "approva": "Approva",
        "respingi": "Respingi",
        "richiedi_modifica": "Richiedi modifica",
        "chiudi": "Chiudi",
        "visualizza": "Visualizza",
    }
    action_label = action_labels.get(action, action.replace("_", " ").title())

    if n_tot == 1:
        a = anomalie_visibili[0]
        subject = (
            f"[Novicrom Hub] Anomalia #{a.get('id', '?')} su OP {op_id}"
            f" — {action_label}"
        )
    else:
        subject = (
            f"[Novicrom Hub] {n_tot} anomalie su OP {op_id}"
            f" — {action_label} richiesta"
        )

    body_text = _build_plain_text(
        recipient_display=recipient_display,
        op_id=op_id,
        op_nominativo=op_nominativo,
        anomalie_visibili=anomalie_visibili,
        n_tot=n_tot,
        troncato=troncato,
        action_label=action_label,
        action_url=action_url,
        expires_at=expires_at,
    )

    body_html = render_to_string(
        "anomalie/email/anomalie_action_email.html",
        {
            "recipient_display": recipient_display,
            "op_id": op_id,
            "op_nominativo": op_nominativo,
            "anomalie_visibili": anomalie_visibili,
            "n_tot": n_tot,
            "troncato": troncato,
            "max_in_email": MAX_ANOMALIE_IN_EMAIL,
            "action": action,
            "action_label": action_label,
            "action_url": action_url,
            "expires_at": expires_at,
            "site_url": site_url,
        },
    )

    return subject, body_text, body_html


def send_anomalie_action_email(
    *,
    recipient_user=None,
    recipient_email: str,
    recipient_display: str,
    recipient_legacy_user_id: int | None = None,
    op_id: str,
    op_nominativo: str,
    anomalie_rows: list[dict],
    action: str,
    expires_hours: int = 48,
    source_automation: str = "",
    created_by=None,
    site_url: str | None = None,
    from_email: str | None = None,
) -> "AnomaliaMailActionToken":
    """Crea il token, costruisce l'email e la invia.

    Ritorna l'istanza AnomaliaMailActionToken creata.
    """
    from .mail_action_models import AnomaliaMailActionToken

    expires_at = timezone.now() + timedelta(hours=expires_hours)

    token_obj = AnomaliaMailActionToken.objects.create(
        recipient_user=recipient_user,
        recipient_legacy_user_id=recipient_legacy_user_id,
        recipient_email=recipient_email,
        recipient_display=recipient_display,
        op_id=op_id,
        op_nominativo=op_nominativo,
        anomalie_ids=[r["id"] for r in anomalie_rows if r.get("id") is not None],
        anomalie_snapshot=anomalie_rows,
        action=action,
        expires_at=expires_at,
        source_automation=source_automation,
        created_by=created_by,
    )

    subject, body_text, body_html = build_anomalie_action_email(
        recipient_email=recipient_email,
        recipient_display=recipient_display,
        op_id=op_id,
        op_nominativo=op_nominativo,
        anomalie_rows=anomalie_rows,
        action=action,
        token_str=token_obj.token,
        expires_at=expires_at,
        site_url=site_url,
    )

    _from = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@costruzioninovicrom.it")

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=_from,
        to=[recipient_email],
    )
    msg.attach_alternative(body_html, "text/html")

    try:
        msg.send(fail_silently=False)
        logger.info(
            "anomalie mail_action email inviata token=%s op=%s action=%s a=%s",
            token_obj.token[:8],
            op_id,
            action,
            recipient_email,
        )
    except Exception:
        logger.exception(
            "anomalie mail_action email FALLITA token=%s op=%s a=%s",
            token_obj.token[:8],
            op_id,
            recipient_email,
        )
        raise

    return token_obj


def _build_plain_text(
    *,
    recipient_display: str,
    op_id: str,
    op_nominativo: str,
    anomalie_visibili: list[dict],
    n_tot: int,
    troncato: bool,
    action_label: str,
    action_url: str,
    expires_at: Any,
) -> str:
    lines = [
        f"Gentile {recipient_display},",
        "",
        f"Hai {'un'if n_tot == 1 else str(n_tot)} anomali{'a' if n_tot == 1 else 'e'} "
        f"sull'OP {op_id}{(' — ' + op_nominativo) if op_nominativo else ''} "
        f"che {'richiede' if n_tot == 1 else 'richiedono'} la tua attenzione.",
        "",
        "ANOMALIE:",
    ]
    for a in anomalie_visibili:
        desc = a.get("descrizione") or a.get("descrizione_breve") or "(nessuna descrizione)"
        stato = a.get("avanzamento") or a.get("stato") or ""
        lines.append(f"  • #{a.get('id', '?')} — {desc[:120]}" + (f" [{stato}]" if stato else ""))
    if troncato:
        lines.append(f"  … e altre {n_tot - len(anomalie_visibili)} anomalie (apri il link per vedere tutto)")
    lines += [
        "",
        f"AZIONE RICHIESTA: {action_label}",
        "",
        f"Apri la pagina sicura del portale per rispondere:",
        action_url,
        "",
    ]
    if expires_at:
        try:
            from django.utils import timezone as _tz
            local_exp = _tz.localtime(expires_at)
            lines.append(f"Link valido fino a: {local_exp.strftime('%d/%m/%Y %H:%M')}")
        except Exception:
            pass
    lines += [
        "",
        "—",
        "NOVICROM HUB · Portale interno · Email automatica",
        "Non rispondere a questa email.",
    ]
    return "\n".join(lines)


# ── Mail di conferma post-aggiornamento ──────────────────────────────────────

def _resolve_segnalante_email(op_id: str, anomalie_ids: list) -> tuple[str, str]:
    """Email + display dell'operatore che ha creato la/e anomalia/e (created_by_user_id).

    Usa la prima anomalia con un autore risolvibile. Ritorna ("", "") se non trovato.
    """
    if not anomalie_ids:
        return "", ""
    try:
        from django.db import connections
        from core.legacy_utils import legacy_table_columns
        cols = legacy_table_columns("anomalie") or set()
        if "created_by_user_id" not in cols:
            return "", ""
        with connections["default"].cursor() as cur:
            placeholders = ",".join(["%s"] * len(anomalie_ids))
            cur.execute(
                f"SELECT TOP 1 created_by_user_id FROM anomalie "
                f"WHERE id IN ({placeholders}) AND created_by_user_id IS NOT NULL",
                list(anomalie_ids),
            )
            row = cur.fetchone()
        if not row or row[0] is None:
            return "", ""
        legacy_uid = int(row[0])
        # Risolvi email/nome dall'utente legacy
        cur_cols = legacy_table_columns("utenti") or set()
        email_col = "email" if "email" in cur_cols else None
        if not email_col:
            return "", ""
        with connections["default"].cursor() as cur:
            cur.execute(
                f"SELECT {email_col}, nome, cognome FROM utenti WHERE id = %s",
                [legacy_uid],
            )
            u = cur.fetchone()
        if u and u[0]:
            email = str(u[0]).strip()
            display = f"{str(u[1] or '').strip()} {str(u[2] or '').strip()}".strip().title()
            return email, (display or email)
    except Exception:
        logger.warning("_resolve_segnalante_email: errore op=%s", op_id, exc_info=True)
    return "", ""


def _resolve_lista_config(key: str) -> list[str]:
    """Lista email da una chiave della config liste anomalie."""
    try:
        from anomalie.views import _load_anomalie_lists
        cfg = _load_anomalie_lists() or {}
        raw = cfg.get(key) or []
        if isinstance(raw, str):
            raw = [x.strip() for x in raw.replace(";", ",").split(",")]
        return [e.strip() for e in raw if e and "@" in str(e)]
    except Exception:
        return []


def _resolve_lista_fissa_conferma() -> list[str]:
    """Lista email fisse di conferma (chiave 'conferma_aggiornamenti')."""
    return _resolve_lista_config("conferma_aggiornamenti")


def _resolve_lista_rdc_segnalazione() -> list[str]:
    """Lista email dedicata alle anomalie da aprire RDC / segnalare a cliente
    (chiave 'rdc_segnalazione'). Riceve la mail solo quando l'aggiornamento
    contiene almeno un'anomalia con flag aprire_rdc o segnalare."""
    return _resolve_lista_config("rdc_segnalazione")


def send_anomalie_update_confirmation(
    *,
    op_id: str,
    op_nominativo: str,
    anomalie_rows: list[dict],
    updates_summary: list[dict],
    source_label: str = "",
    extra_emails: list[str] | None = None,
    from_email: str | None = None,
) -> bool:
    """Invia la mail di RIEPILOGO delle modifiche registrate (no token, no azione).

    Destinatari: operatore segnalante + CC/CAR dell'OP + lista fissa configurabile
    (+ extra_emails). `updates_summary` è una lista di dict per anomalia:
    {id, seriale, avanzamento, note, aprire_rdc, segnalare, chiudere}.

    Ritorna True se inviata, False se nessun destinatario o errore.
    """
    from automazioni.services import _resolve_op_recipients

    anomalie_ids = [r.get("id") for r in anomalie_rows if r.get("id") is not None]

    # Anomalie con risalto: da aprire RDC e/o da segnalare a cliente.
    # Vanno in cima alla mail e attivano l'invio alla lista dedicata.
    rdc_rows = [u for u in updates_summary if u.get("aprire_rdc") or u.get("segnalare")]
    altre_rows = [u for u in updates_summary if not (u.get("aprire_rdc") or u.get("segnalare"))]
    has_rdc = bool(rdc_rows)

    destinatari: list[str] = []

    # 1) Operatore segnalante
    seg_email, _ = _resolve_segnalante_email(op_id, anomalie_ids)
    if seg_email:
        destinatari.append(seg_email)

    # 2) CC e CAR dell'OP
    for rec in _resolve_op_recipients(op_id):
        if rec.get("email"):
            destinatari.append(rec["email"])

    # 3) Lista fissa configurabile + extra
    destinatari.extend(_resolve_lista_fissa_conferma())

    # 4) Lista dedicata RDC/segnalazione: solo se ci sono anomalie con quei flag
    if has_rdc:
        destinatari.extend(_resolve_lista_rdc_segnalazione())

    if extra_emails:
        destinatari.extend(extra_emails)

    # Dedup case-insensitive preservando l'ordine
    seen = set()
    to_list = []
    for e in destinatari:
        k = e.strip().lower()
        if k and k not in seen:
            seen.add(k)
            to_list.append(e.strip())

    if not to_list:
        logger.info("send_anomalie_update_confirmation: nessun destinatario op=%s", op_id)
        return False

    n = len(updates_summary)
    n_rdc = len(rdc_rows)
    if has_rdc:
        subject = (
            f"[Novicrom Hub] OP {op_id} — {n_rdc} da APRIRE RDC / SEGNALARE A CLIENTE"
            f" ({n} modific{'a' if n == 1 else 'he'} totali)"
        )
    else:
        subject = (
            f"[Novicrom Hub] Aggiornamento anomalie OP {op_id} — "
            f"{n} modific{'a' if n == 1 else 'he'} registrat{'a' if n == 1 else 'e'}"
        )

    def _fmt_row(u, prefix="  • "):
        flags = []
        if u.get("aprire_rdc"):
            flags.append("Aprire RDC")
        if u.get("segnalare"):
            flags.append("Segnalare a cliente")
        if u.get("chiudere"):
            flags.append("Chiusa")
        flag_str = (" [" + ", ".join(flags) + "]") if flags else ""
        av = u.get("avanzamento") or "(invariato)"
        sn = u.get("seriale") or ""
        out = [prefix + f"#{u.get('id', '?')}" + (f" S/N {sn}" if sn else "") + f" → {av}{flag_str}"]
        if u.get("note"):
            out.append(f"      Note: {str(u['note'])[:200]}")
        return out

    # Corpo testo
    lines = [
        f"Sono state registrate modifiche sulle anomalie dell'OP {op_id}"
        f"{(' — ' + op_nominativo) if op_nominativo else ''}.",
        "",
    ]
    if rdc_rows:
        lines += ["⚠ DA APRIRE RDC / SEGNALARE A CLIENTE:"]
        for u in rdc_rows:
            lines += _fmt_row(u, "  ► ")
        lines.append("")
    if altre_rows:
        lines += ["ALTRE MODIFICHE:"]
        for u in altre_rows:
            lines += _fmt_row(u)
        lines.append("")
    if source_label:
        lines += [f"Origine: {source_label}", ""]
    lines += [
        "—",
        "NOVICROM HUB · Portale interno · Email automatica",
        "Non rispondere a questa email.",
    ]
    body_text = "\n".join(lines)

    body_html = render_to_string(
        "anomalie/email/anomalie_update_confirmation.html",
        {
            "op_id": op_id,
            "op_nominativo": op_nominativo,
            "updates_summary": updates_summary,
            "rdc_rows": rdc_rows,
            "altre_rows": altre_rows,
            "has_rdc": has_rdc,
            "source_label": source_label,
            "n": n,
            "n_rdc": n_rdc,
        },
    )

    _from = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@costruzioninovicrom.it")
    msg = EmailMultiAlternatives(subject=subject, body=body_text, from_email=_from, to=to_list)
    msg.attach_alternative(body_html, "text/html")
    try:
        msg.send(fail_silently=False)
        logger.info("anomalie update confirmation inviata op=%s a=%s n=%s", op_id, to_list, n)
        return True
    except Exception:
        logger.exception("anomalie update confirmation FALLITA op=%s", op_id)
        return False


def register_pending_update(
    *,
    op_id: str,
    op_nominativo: str,
    update_row: dict,
    modified_by: str = "",
) -> None:
    """Registra/aggiorna un OP nella coda di debounce per la mail di conferma web.

    Accumula gli update nello snapshot e azzera il flag notified: il task periodico
    invierà la mail quando l'OP è fermo da più della soglia.
    """
    from .mail_action_models import AnomaliaPendingNotification
    from django.utils import timezone as _tz

    op_str = str(op_id or "").strip()
    if not op_str:
        return
    try:
        obj, _created = AnomaliaPendingNotification.objects.get_or_create(
            op_id=op_str,
            defaults={
                "op_nominativo": op_nominativo or "",
                "last_modified_at": _tz.now(),
                "last_modified_by": modified_by or "",
                "updates_snapshot": [],
            },
        )
        snapshot = obj.updates_snapshot if isinstance(obj.updates_snapshot, list) else []
        # Sostituisci l'eventuale update precedente per la stessa anomalia
        snapshot = [u for u in snapshot if str(u.get("id")) != str(update_row.get("id"))]
        snapshot.append(update_row)
        obj.updates_snapshot = snapshot
        obj.op_nominativo = op_nominativo or obj.op_nominativo
        obj.last_modified_at = _tz.now()
        obj.last_modified_by = modified_by or obj.last_modified_by
        obj.notified = False
        obj.save(update_fields=[
            "updates_snapshot", "op_nominativo", "last_modified_at", "last_modified_by", "notified",
        ])
    except Exception:
        logger.warning("register_pending_update: errore op=%s", op_str, exc_info=True)


def flush_pending_update_notifications(*, threshold_minutes: int = 5) -> dict:
    """Invia la mail di conferma per gli OP fermi da più di `threshold_minutes`.

    Chiamato dal task periodico. Ritorna {"sent": n, "checked": m}.
    """
    from .mail_action_models import AnomaliaPendingNotification
    from django.utils import timezone as _tz
    from datetime import timedelta

    cutoff = _tz.now() - timedelta(minutes=threshold_minutes)
    pending = list(
        AnomaliaPendingNotification.objects.filter(notified=False, last_modified_at__lte=cutoff)
    )
    sent = 0
    for p in pending:
        snapshot = p.updates_snapshot if isinstance(p.updates_snapshot, list) else []
        if not snapshot:
            p.notified = True
            p.save(update_fields=["notified"])
            continue
        ok = send_anomalie_update_confirmation(
            op_id=p.op_id,
            op_nominativo=p.op_nominativo or "",
            anomalie_rows=[{"id": u.get("id"), "seriale": u.get("seriale")} for u in snapshot],
            updates_summary=snapshot,
            source_label=f"Modifiche da portale (debounce {threshold_minutes} min)",
        )
        p.notified = True
        p.save(update_fields=["notified"])
        if ok:
            sent += 1
    return {"sent": sent, "checked": len(pending)}
