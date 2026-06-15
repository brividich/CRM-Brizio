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

    # Anomalie con risalto, divise per tipo di azione richiesta.
    # Vanno in cima alla mail e attivano l'invio alla lista dedicata.
    # Un'anomalia "aprire_rdc" prevale: se ha anche "segnalare" resta tra le RDC.
    aprire_rdc_rows = [u for u in updates_summary if u.get("aprire_rdc")]
    segnalare_rows = [
        u for u in updates_summary if u.get("segnalare") and not u.get("aprire_rdc")
    ]
    altre_rows = [
        u for u in updates_summary if not (u.get("aprire_rdc") or u.get("segnalare"))
    ]
    has_rdc = bool(aprire_rdc_rows) or bool(segnalare_rows)

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

    # P/N dell'OP (per intestazione + dettaglio anomalie)
    op_pn = _fetch_pn_for_ops([op_id]).get(str(op_id).strip().lower(), "")

    n = len(updates_summary)
    n_aprire = len(aprire_rdc_rows)
    n_segnalare = len(segnalare_rows)
    # P/N davanti all'OP nell'oggetto
    pn_subj = f"P/N {op_pn} · " if op_pn else ""
    if has_rdc:
        parti = []
        if n_aprire:
            parti.append(f"{n_aprire} da APRIRE RDC")
        if n_segnalare:
            parti.append(f"{n_segnalare} da SEGNALARE A CLIENTE")
        subject = f"[Novicrom Hub] {pn_subj}{op_id} — " + " / ".join(parti)
    else:
        subject = (
            f"[Novicrom Hub] {pn_subj}Aggiornamento anomalie {op_id} — "
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
        out += _detail_lines(u)
        return out

    def _detail_lines(u):
        out = []
        if u.get("descrizione"):
            out.append(f"      Descrizione: {str(u['descrizione'])[:300]}")
        if u.get("numero_rdc"):
            out.append(f"      N° RDC: {u['numero_rdc']}")
        if u.get("pezzi_recuperato"):
            out.append("      Pezzo recuperato: sì")
        if u.get("note"):
            out.append(f"      Note: {str(u['note'])[:200]}")
        return out

    # Corpo testo
    lines = [
        f"Sono state registrate modifiche sulle anomalie dell'OP {op_id}"
        f"{(' · P/N ' + op_pn) if op_pn else ''}"
        f"{(' — ' + op_nominativo) if op_nominativo else ''}.",
        "",
    ]
    if aprire_rdc_rows:
        lines += ["⚠ DA APRIRE RDC:"]
        for u in aprire_rdc_rows:
            lines += _fmt_row(u, "  ► ")
        lines.append("")
    if segnalare_rows:
        lines += ["⚠ DA SEGNALARE A CLIENTE:"]
        for u in segnalare_rows:
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
            "op_pn": op_pn,
            "op_nominativo": op_nominativo,
            "updates_summary": updates_summary,
            "aprire_rdc_rows": aprire_rdc_rows,
            "segnalare_rows": segnalare_rows,
            "altre_rows": altre_rows,
            "has_rdc": has_rdc,
            "source_label": source_label,
            "n": n,
            "n_aprire": n_aprire,
            "n_segnalare": n_segnalare,
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


# ── Promemoria & escalation "OP da controllare" ──────────────────────────────

def _fetch_op_da_controllare(soglia_ore: int) -> list[dict]:
    """Raggruppa per OP le anomalie aperte ferme in stato 'In attesa'.

    Un'anomalia entra nel set se: non chiusa (`COALESCE(chiudere,0)=0`) e avanzamento
    uguale allo STATO_DA_GESTIRE. Per ogni OP calcola da quante ore è ferma la più
    vecchia (su `created_datetime`, fallback `modified_datetime`). `over_threshold`
    indica se la più vecchia supera `soglia_ore`.

    Ritorna lista di dict per OP: {op_id, pn, n_anomalie, seriali, ore_max, over_threshold}.
    """
    from .escalation_config import STATO_DA_GESTIRE
    try:
        from core.legacy_utils import legacy_table_columns
        from django.db import connections, connection as _conn
    except Exception:
        return []

    cols = legacy_table_columns("anomalie") or set()
    if not cols:
        return []
    age_col = "created_datetime" if "created_datetime" in cols else (
        "modified_datetime" if "modified_datetime" in cols else None
    )
    if age_col is None:
        return []

    is_sqlite = _conn.vendor == "sqlite"
    op_expr = "ex_op_nominativo" if is_sqlite else "CAST(ex_op_nominativo AS NVARCHAR(MAX))"
    sql = (
        f"SELECT {op_expr} AS op_id, id, seriale, {age_col} AS age_ts "
        f"FROM anomalie "
        f"WHERE COALESCE(chiudere, 0) = 0 AND LOWER(COALESCE(avanzamento, '')) = LOWER(%s)"
    )
    try:
        with connections["default"].cursor() as cur:
            cur.execute(sql, [STATO_DA_GESTIRE])
            rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    except Exception:
        logger.exception("_fetch_op_da_controllare: query fallita")
        return []

    from django.utils import timezone as _tz
    now = _tz.now()

    def _ore(ts) -> float:
        if ts is None:
            return 0.0
        try:
            import datetime as _dt
            if isinstance(ts, str):
                ts = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if _tz.is_naive(ts):
                ts = _tz.make_aware(ts, _tz.utc)
            return max(0.0, (now - ts).total_seconds() / 3600.0)
        except Exception:
            return 0.0

    grouped: dict[str, dict] = {}
    for r in rows:
        op = str(r.get("op_id") or "").strip()
        if not op:
            continue
        g = grouped.setdefault(op, {"op_id": op, "ids": [], "seriali": [], "ore_max": 0.0})
        g["ids"].append(r.get("id"))
        sn = str(r.get("seriale") or "").strip()
        if sn:
            g["seriali"].append(sn)
        g["ore_max"] = max(g["ore_max"], _ore(r.get("age_ts")))

    if not grouped:
        return []

    pn_map = _fetch_pn_for_ops(list(grouped.keys()))
    out = []
    for op, g in grouped.items():
        out.append({
            "op_id": op,
            "pn": pn_map.get(op.lower(), ""),
            "n_anomalie": len(g["ids"]),
            "seriali": g["seriali"],
            "ore_max": round(g["ore_max"], 1),
            "over_threshold": g["ore_max"] >= soglia_ore,
        })
    out.sort(key=lambda x: x["ore_max"], reverse=True)
    return out


def _fetch_pn_for_ops(op_titles: list[str]) -> dict[str, str]:
    """Mappa op_title (lower) -> P/N da ordini_produzione, se la colonna esiste."""
    if not op_titles:
        return {}
    try:
        from core.legacy_utils import legacy_table_columns
        from django.db import connections, connection as _conn
        cols = legacy_table_columns("ordini_produzione") or set()
        pn_col = "pn" if "pn" in cols else ("part_number" if "part_number" in cols else None)
        if pn_col is None:
            return {}
        is_sqlite = _conn.vendor == "sqlite"
        title_expr = "title" if is_sqlite else "CAST(title AS NVARCHAR(MAX))"
        placeholders = ",".join(["%s"] * len(op_titles))
        sql = f"SELECT {title_expr} AS t, {pn_col} AS pn FROM ordini_produzione WHERE LOWER({title_expr}) IN ({placeholders})"
        with connections["default"].cursor() as cur:
            cur.execute(sql, [t.lower() for t in op_titles])
            return {
                str(r[0] or "").strip().lower(): str(r[1] or "").strip()
                for r in cur.fetchall()
            }
    except Exception:
        return {}


def _resolve_op_cc_car_legacy_ids(op_id: str) -> list[tuple[int, str]]:
    """Risolve (legacy_user_id, display) di CC e CAR dell'OP per i reminder dashboard.

    Riusa il pattern di anomalie.views._notify_anomalia_event: dai nominativi CC/CAR
    (via _resolve_op_recipients) cerca l'utente legacy per alias email o per nome.
    """
    from automazioni.services import _resolve_op_recipients
    out: list[tuple[int, str]] = []
    try:
        from core.legacy_models import UtenteLegacy
    except Exception:
        return out
    seen: set[int] = set()
    for rec in _resolve_op_recipients(op_id):
        display = str(rec.get("display") or "").strip()
        email = str(rec.get("email") or "").strip()
        user = None
        try:
            if email:
                alias = email.split("@")[0].strip()
                user = UtenteLegacy.objects.filter(email__istartswith=f"{alias}@").first()
            if user is None and display:
                user = UtenteLegacy.objects.filter(nome__icontains=display).first()
        except Exception:
            user = None
        if user and user.id not in seen:
            seen.add(user.id)
            out.append((user.id, display or email or str(user.id)))
    return out


def create_dashboard_reminders(op_rows: list[dict], *, soglia_ore: int) -> int:
    """Crea promemoria in-app (core.Notifica) per CC/CAR degli OP da controllare.

    Idempotente: per ogni (utente, OP) non duplica se esiste già una notifica non letta
    dello stesso tipo che punta allo stesso OP. Aggiorna il messaggio a "in ritardo" quando
    l'OP supera la soglia. Ritorna il numero di notifiche create.
    """
    from core.models import Notifica

    created = 0
    for op in op_rows:
        op_id = op.get("op_id") or ""
        if not op_id:
            continue
        over = bool(op.get("over_threshold"))
        n = op.get("n_anomalie") or 0
        ritardo = f" — in ritardo da {int(op.get('ore_max') or 0)}h" if over else ""
        messaggio = (
            f"OP {op_id}: {n} anomali{'a' if n == 1 else 'e'} da gestire (stato 'In attesa'){ritardo}."
        )[:500]
        url = f"/gestione-anomalie?op={op_id}"
        for legacy_uid, _display in _resolve_op_cc_car_legacy_ids(op_id):
            try:
                # Idempotenza: una sola notifica non letta per (utente, OP)
                exists = Notifica.objects.filter(
                    legacy_user_id=legacy_uid,
                    tipo="anomalia_da_gestire",
                    url_azione=url,
                    letta=False,
                ).first()
                if exists:
                    # Aggiorna il testo se è cambiato lo stato di ritardo
                    if exists.messaggio != messaggio:
                        exists.messaggio = messaggio
                        exists.save(update_fields=["messaggio"])
                    continue
                Notifica.objects.create(
                    legacy_user_id=legacy_uid,
                    tipo="anomalia_da_gestire",
                    messaggio=messaggio,
                    url_azione=url,
                )
                created += 1
            except Exception:
                logger.warning("create_dashboard_reminders: notifica fallita op=%s uid=%s", op_id, legacy_uid, exc_info=True)
    return created


def send_escalation_resoconto(op_rows: list[dict], *, soglia_ore: int, from_email: str | None = None) -> bool:
    """Invia UNA mail aggregata con il resoconto degli OP/PN oltre soglia.

    Destinatari: CC/CAR di tutti gli OP coinvolti + lista fissa supervisori
    (config liste anomalie chiave `escalation_supervisori`). Ritorna True se inviata.
    """
    from .escalation_config import LISTA_SUPERVISORI_KEY
    from automazioni.services import _resolve_op_recipients

    over_rows = [op for op in op_rows if op.get("over_threshold")]
    if not over_rows:
        return False

    # Arricchisci ogni OP con i nomi CC/CAR per la tabella
    enriched = []
    destinatari: list[str] = []
    for op in over_rows:
        recs = _resolve_op_recipients(op.get("op_id") or "")
        cc_car = ", ".join(
            f"{r.get('display') or r.get('email')}" for r in recs if (r.get("display") or r.get("email"))
        )
        for r in recs:
            if r.get("email"):
                destinatari.append(r["email"])
        enriched.append({**op, "cc_car": cc_car})

    destinatari.extend(_resolve_lista_config(LISTA_SUPERVISORI_KEY))

    seen = set()
    to_list = []
    for e in destinatari:
        k = str(e).strip().lower()
        if k and "@" in k and k not in seen:
            seen.add(k)
            to_list.append(str(e).strip())
    if not to_list:
        logger.info("send_escalation_resoconto: nessun destinatario")
        return False

    n_op = len(enriched)
    tot_anomalie = sum(op.get("n_anomalie") or 0 for op in enriched)
    subject = (
        f"[Novicrom Hub] {n_op} OP da controllare — {tot_anomalie} anomali"
        f"{'a' if tot_anomalie == 1 else 'e'} in attesa oltre {soglia_ore}h"
    )

    lines = [
        f"Resoconto OP da controllare (anomalie in stato 'In attesa' da oltre {soglia_ore} ore).",
        "",
    ]
    for op in enriched:
        sn = ", ".join(op.get("seriali") or [])
        pn = f" · P/N {op['pn']}" if op.get("pn") else ""
        lines.append(
            f"  • OP {op['op_id']}{pn} — {op['n_anomalie']} anomalie · ferma da {int(op.get('ore_max') or 0)}h"
            + (f" · S/N {sn}" if sn else "")
            + (f" · {op['cc_car']}" if op.get("cc_car") else "")
        )
    lines += [
        "",
        "—",
        "NOVICROM HUB · Portale interno · Email automatica",
        "Non rispondere a questa email.",
    ]
    body_text = "\n".join(lines)

    body_html = render_to_string(
        "anomalie/email/anomalie_escalation_resoconto.html",
        {
            "op_rows": enriched,
            "n_op": n_op,
            "tot_anomalie": tot_anomalie,
            "soglia_ore": soglia_ore,
        },
    )

    _from = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@costruzioninovicrom.it")
    msg = EmailMultiAlternatives(subject=subject, body=body_text, from_email=_from, to=to_list)
    msg.attach_alternative(body_html, "text/html")
    try:
        msg.send(fail_silently=False)
        logger.info("anomalie escalation resoconto inviato a=%s n_op=%s", to_list, n_op)
        return True
    except Exception:
        logger.exception("anomalie escalation resoconto FALLITO")
        return False


# ── Timeline / log azioni portale ───────────────────────────────────────────

def log_anomalia_portal_action(
    *,
    anomalia_id: int | None,
    op_id: str,
    action: str,
    user=None,
    legacy_user_id: int | None = None,
    user_display: str = "",
    previous_status: str = "",
    new_status: str = "",
    note: str = "",
    ip_address: str | None = None,
    user_agent: str = "",
) -> None:
    """Registra un'azione su anomalia eseguita dal portale (source=PORTAL).

    Fire-and-forget: ogni errore viene assorbito e loggato, non deve mai far
    fallire il salvataggio dell'anomalia. Speculare a _write_action_log del
    flusso mail-action, così la timeline (AnomaliaActionLog) copre entrambi i
    canali. Senza anomalia_id il log e' inutile (non agganciabile all'OP) e si
    salta.
    """
    if not anomalia_id:
        return
    try:
        from anomalie.mail_action_models import AnomaliaActionLog

        AnomaliaActionLog.objects.create(
            anomalia_id=int(anomalia_id),
            op_id=str(op_id or "")[:100],
            user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
            legacy_user_id=legacy_user_id,
            user_display=str(user_display or "")[:200],
            action=str(action or "")[:32],
            previous_status=str(previous_status or "")[:100],
            new_status=str(new_status or "")[:100],
            note=str(note or ""),
            source=AnomaliaActionLog.Source.PORTAL,
            ip_address=ip_address,
            user_agent=str(user_agent or "")[:500],
        )
    except Exception:
        logger.warning("log_anomalia_portal_action: scrittura log fallita op=%s id=%s", op_id, anomalia_id, exc_info=True)
