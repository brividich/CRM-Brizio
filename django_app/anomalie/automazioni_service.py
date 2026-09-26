"""Automazioni aggiuntive del modulo anomalie.

Girano tutte dentro il task orario `anomalie_escalation` (nessuno Schedule nuovo) e
sono spente di default: si accendono da Configurazione > Promemoria & escalation.

- Difetto ricorrente per P/N: N anomalie sullo stesso P/N in X giorni -> mail a
  supervisori e lista RDC/qualita', una sola volta per P/N per finestra.
- RDC richiesto senza numero: «Aprire RDC» attivo, numero RDC vuoto da oltre X giorni
  -> promemoria in dashboard a CC/CAR e sezione nel resoconto giornaliero.
- Digest settimanale KPI: il lunedi' all'ora del resoconto, ai supervisori.
- OP completato: quando l'ultima anomalia aperta di un OP viene chiusa -> mail a
  CC/CAR con il link al Report OP.

La tabella `anomalie` e' legacy (SQL Server in prod, SQLite nei test): le query
restano semplici e l'aggregazione si fa in Python. Le date sono DATETIME2 scritte
con SYSUTCDATETIME, quindi naive ma UTC.
"""
from __future__ import annotations

import datetime as _dt
import logging
from collections import defaultdict
from urllib.parse import quote

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger("anomalie.automazioni")

TIPO_REMINDER_RDC = "anomalia_rdc_mancante"
OP_COMPLETATO_FINESTRA_ORE = 48


# ── Accesso dati ───────────────────────────────────────────────────────────

def _anomalie_cols() -> set[str]:
    try:
        from core.legacy_utils import legacy_table_columns
        return set(legacy_table_columns("anomalie") or set())
    except Exception:
        return set()


def _is_sqlite() -> bool:
    from django.db import connection
    return connection.vendor == "sqlite"


def _text(col: str) -> str:
    """Le colonne testo legacy possono essere NTEXT: su SQL Server vanno castate."""
    return col if _is_sqlite() else f"CAST({col} AS NVARCHAR(MAX))"


def _fetch(sql: str, params: list) -> list[dict]:
    from django.db import connections
    with connections["default"].cursor() as cur:
        cur.execute(sql, params)
        names = [c[0] for c in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def _as_utc(ts):
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(ts, _dt.date) and not isinstance(ts, _dt.datetime):
        ts = _dt.datetime.combine(ts, _dt.time())
    if timezone.is_naive(ts):
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts


def _naive_utc(ts: _dt.datetime) -> _dt.datetime:
    """Parametro di confronto con le colonne DATETIME2 naive UTC."""
    return ts.astimezone(_dt.timezone.utc).replace(tzinfo=None)


def _local_label(ts) -> str:
    ts = _as_utc(ts)
    return timezone.localtime(ts).strftime("%d/%m/%Y") if ts else ""


def _select_base(cols: set[str], extra: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    wanted = ["id", "ex_op_nominativo", "seriale", "created_datetime", "modified_datetime",
              "chiudere", "aprire_rdc", "numero_rdc", "descrizione", "avanzamento", *extra]
    present = [c for c in dict.fromkeys(wanted) if c in cols]
    text_cols = {"ex_op_nominativo", "seriale", "numero_rdc", "descrizione", "avanzamento"}
    parts = [f"{_text(c)} AS {c}" if c in text_cols else c for c in present]
    return ", ".join(parts), present


def _site_url() -> str:
    return str(getattr(settings, "SITE_URL", "") or "").rstrip("/")


def op_url(op_id: str) -> str:
    return f"/gestione-anomalie?op={quote(str(op_id or ''), safe='/')}"


def report_url(op_id: str) -> str:
    return f"{_site_url()}/api/anomalie/report?op_id={quote(str(op_id or ''), safe='')}"


def _marker_exists(tipo: str, chiave: str, since=None) -> bool:
    from anomalie.automation_models import AnomalieAutomazioneMarker
    qs = AnomalieAutomazioneMarker.objects.filter(tipo=tipo, chiave=chiave)
    if since is not None:
        qs = qs.filter(creato_il__gte=since)
    return qs.exists()


def _marker_set(tipo: str, chiave: str, dettaglio: dict | None = None) -> None:
    from anomalie.automation_models import AnomalieAutomazioneMarker
    AnomalieAutomazioneMarker.objects.create(tipo=tipo, chiave=chiave[:255], dettaglio=dettaglio or {})


def _dedup_emails(emails) -> list[str]:
    seen, out = set(), []
    for e in emails:
        k = str(e or "").strip()
        if k and "@" in k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out


def _supervisori() -> list[str]:
    from anomalie.escalation_config import LISTA_SUPERVISORI_KEY
    from anomalie.mail_action_service import _resolve_lista_config
    return _resolve_lista_config(LISTA_SUPERVISORI_KEY)


def _render_mail(**ctx) -> str:
    return render_to_string("anomalie/email/anomalie_automazione.html", ctx)


def _send(*, kind: str, subject: str, lines: list[str], html: str, to: list[str], op_id: str = "",
          context: dict | None = None) -> bool:
    from anomalie.mail_action_service import send_and_log_email
    body_text = "\n".join(lines + ["", "—", "NOVICROM HUB · Email automatica", "Non rispondere a questa email."])
    sent, _row = send_and_log_email(
        kind=kind, subject=subject, body_text=body_text, body_html=html, to=to,
        op_id=op_id, context=context or {}, fail_silently=True,
    )
    return bool(sent)


# ── 1. Difetto ricorrente per P/N ──────────────────────────────────────────

def find_ricorrenze_pn(*, soglia_n: int, giorni: int, now=None) -> list[dict]:
    """P/N con almeno `soglia_n` anomalie create negli ultimi `giorni` giorni."""
    from anomalie.mail_action_service import _fetch_pn_for_ops

    cols = _anomalie_cols()
    if not {"created_datetime", "ex_op_nominativo"} <= cols:
        return []
    now = now or timezone.now()
    since = now - _dt.timedelta(days=giorni)
    select, _ = _select_base(cols)
    rows = _fetch(f"SELECT {select} FROM anomalie WHERE created_datetime >= %s", [_naive_utc(since)])
    ops = sorted({str(r.get("ex_op_nominativo") or "").strip() for r in rows} - {""})
    pn_map = _fetch_pn_for_ops(ops)

    groups: dict[str, dict] = {}
    for r in rows:
        op = str(r.get("ex_op_nominativo") or "").strip()
        pn = pn_map.get(op.lower(), "").strip()
        if not pn:
            continue
        g = groups.setdefault(pn.upper(), {"pn": pn, "anomalie": []})
        g["anomalie"].append({
            "id": r.get("id"),
            "op_id": op,
            "seriale": str(r.get("seriale") or "").strip(),
            "descrizione": str(r.get("descrizione") or "").strip(),
            "creata": _local_label(r.get("created_datetime")),
            "chiusa": bool(r.get("chiudere")),
        })
    out = []
    for key, g in groups.items():
        if len(g["anomalie"]) >= soglia_n:
            g["chiave"] = key
            g["n"] = len(g["anomalie"])
            g["anomalie"].sort(key=lambda a: a["id"] or 0)
            out.append(g)
    out.sort(key=lambda g: g["n"], reverse=True)
    return out


def notify_ricorrenze_pn(*, soglia_n: int, giorni: int, now=None) -> int:
    """Invia un allarme per ogni P/N ricorrente non gia' segnalato nella finestra."""
    from anomalie.automation_models import AnomalieAutomazioneMarker as M
    from anomalie.mail_action_service import _resolve_lista_rdc_segnalazione

    now = now or timezone.now()
    since = now - _dt.timedelta(days=giorni)
    to = _dedup_emails(_supervisori() + _resolve_lista_rdc_segnalazione())
    if not to:
        return 0
    sent = 0
    for g in find_ricorrenze_pn(soglia_n=soglia_n, giorni=giorni, now=now):
        if _marker_exists(M.Tipo.RICORRENZA_PN, g["chiave"], since=since):
            continue
        subject = f"[Novicrom Hub] Difetto ricorrente: P/N {g['pn']} — {g['n']} anomalie in {giorni} giorni"
        rows = [[a["creata"], a["op_id"], a["seriale"] or "—", (a["descrizione"] or "—")[:120],
                 "Chiusa" if a["chiusa"] else "Aperta"] for a in g["anomalie"]]
        lines = [f"Il P/N {g['pn']} ha accumulato {g['n']} anomalie negli ultimi {giorni} giorni "
                 f"(soglia {soglia_n}). Valutare un'azione correttiva sulla causa comune.", ""]
        lines += [f"  • {r[0]} · OP {r[1]} · S/N {r[2]} · {r[4]} · {r[3]}" for r in rows]
        html = _render_mail(
            badge="Difetto ricorrente", eyebrow="Allarme qualità",
            title=f"P/N {g['pn']}: {g['n']} anomalie in {giorni} giorni",
            intro=(f"Superata la soglia di {soglia_n} anomalie sullo stesso P/N. "
                   "Valutare un'azione correttiva sulla causa comune."),
            columns=["Data", "OP", "S/N", "Descrizione", "Stato"], rows=rows,
            cta_url=f"{_site_url()}/gestione-anomalie/statistiche" if _site_url() else "",
            cta_label="Apri le statistiche",
        )
        if _send(kind="ricorrenza_pn", subject=subject, lines=lines, html=html, to=to,
                 context={"pn": g["pn"], "n": g["n"], "giorni": giorni}):
            _marker_set(M.Tipo.RICORRENZA_PN, g["chiave"], {"n": g["n"], "giorni": giorni})
            sent += 1
    return sent


# ── 2. RDC richiesto senza numero ──────────────────────────────────────────

def find_rdc_senza_numero(*, giorni: int, now=None) -> list[dict]:
    """OP con anomalie aperte, «Aprire RDC» attivo e numero RDC vuoto da oltre `giorni`."""
    from anomalie.mail_action_service import _fetch_pn_for_ops

    cols = _anomalie_cols()
    if not {"aprire_rdc", "numero_rdc", "ex_op_nominativo"} <= cols:
        return []
    now = now or timezone.now()
    select, _ = _select_base(cols)
    rows = _fetch(
        f"SELECT {select} FROM anomalie WHERE COALESCE(aprire_rdc, 0) = 1 AND COALESCE(chiudere, 0) = 0",
        [],
    )
    grouped: dict[str, dict] = {}
    for r in rows:
        if str(r.get("numero_rdc") or "").strip():
            continue
        ts = _as_utc(r.get("created_datetime") or r.get("modified_datetime"))
        eta_giorni = (now - ts).total_seconds() / 86400.0 if ts else 0.0
        if eta_giorni < giorni:
            continue
        op = str(r.get("ex_op_nominativo") or "").strip()
        if not op:
            continue
        g = grouped.setdefault(op, {"op_id": op, "ids": [], "seriali": [], "giorni_max": 0.0})
        g["ids"].append(r.get("id"))
        sn = str(r.get("seriale") or "").strip()
        if sn:
            g["seriali"].append(sn)
        g["giorni_max"] = max(g["giorni_max"], eta_giorni)
    if not grouped:
        return []
    pn_map = _fetch_pn_for_ops(list(grouped))
    out = [{
        "op_id": op,
        "pn": pn_map.get(op.lower(), ""),
        "n_anomalie": len(g["ids"]),
        "seriali": g["seriali"],
        "giorni_max": int(g["giorni_max"]),
    } for op, g in grouped.items()]
    out.sort(key=lambda x: x["giorni_max"], reverse=True)
    return out


def sync_rdc_reminders(rdc_rows: list[dict]) -> int:
    """Promemoria dashboard a CC/CAR per gli RDC senza numero; chiude quelli risolti."""
    from core.models import Notifica
    from anomalie.mail_action_service import _resolve_op_cc_car_legacy_ids

    created = 0
    keep_urls = set()
    for op in rdc_rows:
        url = op_url(op["op_id"])
        keep_urls.add(url)
        n = op["n_anomalie"]
        messaggio = (
            f"OP {op['op_id']}: RDC da aprire su {n} anomali{'a' if n == 1 else 'e'} "
            f"senza numero RDC da {op['giorni_max']} giorni."
        )[:500]
        for legacy_uid, _display in _resolve_op_cc_car_legacy_ids(op["op_id"]):
            try:
                exists = Notifica.objects.filter(
                    legacy_user_id=legacy_uid, tipo=TIPO_REMINDER_RDC, url_azione=url, letta=False,
                ).first()
                if exists:
                    if exists.messaggio != messaggio:
                        exists.messaggio = messaggio
                        exists.save(update_fields=["messaggio"])
                    continue
                Notifica.objects.create(
                    legacy_user_id=legacy_uid, tipo=TIPO_REMINDER_RDC, messaggio=messaggio, url_azione=url,
                )
                created += 1
            except Exception:
                logger.warning("sync_rdc_reminders: notifica fallita op=%s uid=%s", op["op_id"], legacy_uid, exc_info=True)
    Notifica.objects.filter(tipo=TIPO_REMINDER_RDC, letta=False).exclude(url_azione__in=keep_urls).update(letta=True)
    return created


# ── 3. Digest settimanale KPI ──────────────────────────────────────────────

def build_digest(*, soglia_ore: int, now=None) -> dict:
    """KPI degli ultimi 7 giorni + stato attuale del backlog."""
    from anomalie.escalation_config import STATO_DA_GESTIRE
    from anomalie.mail_action_service import _fetch_pn_for_ops

    cols = _anomalie_cols()
    now = now or timezone.now()
    since = now - _dt.timedelta(days=7)
    select, _ = _select_base(cols)
    where = ["COALESCE(chiudere, 0) = 0"]
    params: list = []
    for c in ("created_datetime", "modified_datetime"):
        if c in cols:
            where.append(f"{c} >= %s")
            params.append(_naive_utc(since))
    rows = _fetch(f"SELECT {select} FROM anomalie WHERE {' OR '.join(where)}", params)

    nuove, chiuse, durate = [], [], []
    aperte = in_attesa_oltre = rdc_senza = 0
    for r in rows:
        created = _as_utc(r.get("created_datetime"))
        modified = _as_utc(r.get("modified_datetime"))
        closed = bool(r.get("chiudere"))
        if created and created >= since:
            nuove.append(r)
        if closed and modified and modified >= since:
            chiuse.append(r)
            if created:
                durate.append((modified - created).total_seconds() / 86400.0)
        if not closed:
            aperte += 1
            if str(r.get("avanzamento") or "").strip().lower() == STATO_DA_GESTIRE.lower() and created \
                    and (now - created).total_seconds() / 3600.0 >= soglia_ore:
                in_attesa_oltre += 1
            if r.get("aprire_rdc") and not str(r.get("numero_rdc") or "").strip():
                rdc_senza += 1

    per_op: dict[str, int] = defaultdict(int)
    for r in nuove:
        per_op[str(r.get("ex_op_nominativo") or "").strip() or "(senza OP)"] += 1
    pn_map = _fetch_pn_for_ops([op for op in per_op if op != "(senza OP)"])
    per_pn: dict[str, int] = defaultdict(int)
    for op, n in per_op.items():
        pn = pn_map.get(op.lower(), "")
        if pn:
            per_pn[pn] += n

    def _top(d: dict) -> list[tuple[str, int]]:
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    return {
        "dal": timezone.localtime(since).strftime("%d/%m/%Y"),
        "al": timezone.localtime(now).strftime("%d/%m/%Y"),
        "nuove": len(nuove),
        "chiuse": len(chiuse),
        "aperte": aperte,
        "in_attesa_oltre": in_attesa_oltre,
        "rdc_senza_numero": rdc_senza,
        "tempo_medio_giorni": round(sum(durate) / len(durate), 1) if durate else None,
        "top_op": _top(per_op),
        "top_pn": _top(per_pn),
        "soglia_ore": soglia_ore,
    }


def send_digest(*, soglia_ore: int, now=None, force: bool = False) -> bool:
    """Una volta per settimana ISO (il marcatore evita doppioni anche con `force`)."""
    from anomalie.automation_models import AnomalieAutomazioneMarker as M

    now = now or timezone.now()
    iso = timezone.localtime(now).isocalendar()
    chiave = f"{iso[0]}-W{iso[1]:02d}"
    if not force and _marker_exists(M.Tipo.DIGEST, chiave):
        return False
    to = _dedup_emails(_supervisori())
    if not to:
        return False
    d = build_digest(soglia_ore=soglia_ore, now=now)
    tm = f"{d['tempo_medio_giorni']} gg" if d["tempo_medio_giorni"] is not None else "—"
    kpis = [
        {"label": "Nuove", "value": d["nuove"]},
        {"label": "Chiuse", "value": d["chiuse"]},
        {"label": "Aperte oggi", "value": d["aperte"]},
        {"label": f"In attesa > {soglia_ore}h", "value": d["in_attesa_oltre"]},
        {"label": "RDC senza numero", "value": d["rdc_senza_numero"]},
        {"label": "Tempo medio chiusura", "value": tm},
    ]
    rows = [["OP", op, n] for op, n in d["top_op"]] + [["P/N", pn, n] for pn, n in d["top_pn"]]
    riepilogo = (
        f"{d['nuove']} {'nuova anomalia' if d['nuove'] == 1 else 'nuove anomalie'}, "
        f"{d['chiuse']} {'chiusa' if d['chiuse'] == 1 else 'chiuse'}"
    )
    subject = f"[Novicrom Hub] Anomalie — settimana {d['dal']}–{d['al']}: {riepilogo}"
    lines = [f"Digest anomalie dal {d['dal']} al {d['al']}.", ""]
    lines += [f"  {k['label']}: {k['value']}" for k in kpis]
    if rows:
        lines += ["", "Più anomalie nella settimana:"] + [f"  • {r[0]} {r[1]}: {r[2]}" for r in rows]
    html = _render_mail(
        badge="Digest settimanale", eyebrow=f"Dal {d['dal']} al {d['al']}",
        title=riepilogo[:1].upper() + riepilogo[1:],
        intro="Andamento della settimana e stato attuale delle anomalie aperte.",
        kpis=kpis, columns=["Tipo", "Riferimento", "Nuove"] if rows else [], rows=rows,
        cta_url=f"{_site_url()}/gestione-anomalie/statistiche" if _site_url() else "",
        cta_label="Apri le statistiche",
    )
    if _send(kind="digest_settimanale", subject=subject, lines=lines, html=html, to=to, context={"settimana": chiave}):
        _marker_set(M.Tipo.DIGEST, chiave, {"nuove": d["nuove"], "chiuse": d["chiuse"]})
        return True
    return False


# ── 4. OP completato ───────────────────────────────────────────────────────

def _op_rows(op_ids: list[str]) -> dict[str, list[dict]]:
    cols = _anomalie_cols()
    if "ex_op_nominativo" not in cols or not op_ids:
        return {}
    select, _ = _select_base(cols)
    lowered = sorted({o.strip().lower() for o in op_ids if o and o.strip()})
    out: dict[str, list[dict]] = defaultdict(list)
    for i in range(0, len(lowered), 200):
        chunk = lowered[i:i + 200]
        ph = ",".join(["%s"] * len(chunk))
        for r in _fetch(f"SELECT {select} FROM anomalie WHERE LOWER({_text('ex_op_nominativo')}) IN ({ph})", chunk):
            out[str(r.get("ex_op_nominativo") or "").strip().lower()].append(r)
    return out


def _recent_ops(now, ore: int) -> list[str]:
    cols = _anomalie_cols()
    col = "modified_datetime" if "modified_datetime" in cols else ("created_datetime" if "created_datetime" in cols else None)
    if col is None or "ex_op_nominativo" not in cols:
        return []
    since = now - _dt.timedelta(hours=ore)
    rows = _fetch(
        f"SELECT DISTINCT {_text('ex_op_nominativo')} AS op FROM anomalie WHERE {col} >= %s",
        [_naive_utc(since)],
    )
    return [str(r["op"]).strip() for r in rows if str(r.get("op") or "").strip()]


def notify_op_completati(op_ids: list[str] | None = None, *, now=None) -> int:
    """Mail a CC/CAR per gli OP che hanno tutte le anomalie chiuse.

    Senza `op_ids` guarda gli OP toccati nelle ultime 48 ore (mai lo storico intero).
    Chiave del marcatore = OP + numero di anomalie: se all'OP se ne aggiunge una e
    viene chiusa anche quella, l'OP torna a essere notificato.
    """
    from anomalie.automation_models import AnomalieAutomazioneMarker as M
    from anomalie.mail_action_service import _fetch_pn_for_ops
    from automazioni.services import _resolve_op_recipients

    now = now or timezone.now()
    if op_ids is None:
        op_ids = _recent_ops(now, OP_COMPLETATO_FINESTRA_ORE)
    by_op = _op_rows(op_ids)
    sent = 0
    for op_key, rows in by_op.items():
        if not rows or any(not r.get("chiudere") for r in rows):
            continue
        op_id = str(rows[0].get("ex_op_nominativo") or "").strip()
        chiave = f"{op_key}#{len(rows)}"
        if _marker_exists(M.Tipo.OP_COMPLETATO, chiave):
            continue
        recs = _resolve_op_recipients(op_id)
        to = _dedup_emails(r.get("email") for r in recs)
        if not to:
            # Nessun destinatario risolvibile: si marca comunque per non riprovare a ogni run.
            _marker_set(M.Tipo.OP_COMPLETATO, chiave, {"inviata": False})
            continue
        pn = _fetch_pn_for_ops([op_id]).get(op_key, "")
        table = [[str(r.get("seriale") or "—"), str(r.get("avanzamento") or "—"),
                  _local_label(r.get("modified_datetime"))] for r in sorted(rows, key=lambda r: r.get("id") or 0)]
        n = len(rows)
        subject = f"[Novicrom Hub] OP {op_id}: tutte le anomalie chiuse ({n})"
        lines = [f"Tutte le {n} anomalie dell'OP {op_id}{f' (P/N {pn})' if pn else ''} risultano chiuse.",
                 f"Report OP: {report_url(op_id)}", ""]
        lines += [f"  • S/N {r[0]} · {r[1]} · {r[2]}" for r in table]
        html = _render_mail(
            badge="OP completato", eyebrow=f"P/N {pn}" if pn else "Gestione anomalie",
            title=f"OP {op_id}: tutte le anomalie chiuse",
            intro=f"{'L' if n == 1 else 'Tutte le'} {n} anomali{'a registrata risulta chiusa' if n == 1 else 'e registrate risultano chiuse'}. "
                  "Il Report OP riepiloga descrizioni, note e allegati.",
            columns=["S/N", "Avanzamento", "Ultima modifica"], rows=table,
            cta_url=report_url(op_id), cta_label="Apri il Report OP",
        )
        if _send(kind="op_completato", subject=subject, lines=lines, html=html, to=to, op_id=op_id,
                 context={"n": n}):
            _marker_set(M.Tipo.OP_COMPLETATO, chiave, {"inviata": True, "to": len(to)})
            sent += 1
    return sent
