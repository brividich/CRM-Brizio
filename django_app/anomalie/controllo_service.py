"""Controllo di un OP a blocchi di seriali: lettura, regole di modifica e mail.

Ogni anomalia resta UNA riga della tabella legacy ``anomalie`` (stato, RDC,
segnalazione al cliente e chiusura restano per singola anomalia, come le gestisce
il capocommessa). ``AnomaliaControllo`` e ``AnomaliaBlocco`` le raggruppano:
il controllo è la sessione dell'operatore su un OP, il blocco è l'insieme di
seriali su cui sono state riscontrate una o più anomalie.

La mail al capocommessa con il link di decisione parte:
- ``subito``: dopo ogni salvataggio di blocco, quando il controllo è fermo da
  qualche minuto (stesso debounce della mail di riepilogo, così più salvataggi
  ravvicinati diventano una sola mail);
- ``fine``: una sola volta, a «Termina controllo». Se l'operatore non lo preme,
  il task periodico la manda comunque dopo ``FINE_TIMEOUT_MINUTI`` di inattività,
  così nessuna anomalia resta senza comunicazione.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.db import connections
from django.utils import timezone

logger = logging.getLogger(__name__)

DEBOUNCE_MINUTI = 5
FINE_TIMEOUT_MINUTI = 240
MAX_TENTATIVI_MAIL = 5
SCADENZA_LINK_ORE = 72

_SUP_RE = re.compile(r"^\s*Stato superficie:\s*([^\n]*)\n*", re.IGNORECASE)
_STATI_LIBERI = {"", "in attesa"}


def componi_descrizione(testo: str, stato_superficie: list[str]) -> str:
    """Testo della colonna legacy ``descrizione``: lo stato superficie va in testa,
    nel formato che la pagina mail e la gestione già riconoscono."""
    testo = str(testo or "").strip()
    stati = [str(s).strip() for s in stato_superficie or [] if str(s).strip()]
    if stati:
        return f"Stato superficie: {', '.join(stati)}\n\n{testo}"
    return testo


def separa_descrizione(descrizione: str) -> tuple[list[str], str]:
    """Inverso di ``componi_descrizione``."""
    raw = str(descrizione or "")
    m = _SUP_RE.match(raw)
    if not m:
        return [], raw.strip()
    stati = [s.strip() for s in m.group(1).split(",") if s.strip()]
    return stati, raw[m.end():].strip()


def riga_gestita(row: dict) -> bool:
    """True se il capocommessa ha già deciso qualcosa sulla riga: da quel momento
    l'operatore non può più modificarla dal controllo."""
    if not row:
        return False
    if row.get("chiudere") or row.get("aprire_rdc") or row.get("segnalare_cliente"):
        return True
    if str(row.get("note_capocommessa") or "").strip():
        return True
    return str(row.get("avanzamento") or "").strip().lower() not in _STATI_LIBERI


def carica_righe(ids: list[int]) -> dict[int, dict]:
    """Righe legacy per id, con i campi che servono al controllo."""
    ids = [int(i) for i in ids if i is not None]
    if not ids:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    try:
        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT id, ex_op_nominativo, seriale, descrizione, note_capocommessa, avanzamento,"
                " aprire_rdc, segnalare_cliente, chiudere"
                f" FROM anomalie WHERE id IN ({placeholders})",
                ids,
            )
            cols = [c[0] for c in cur.description]
            return {int(r[0]): dict(zip(cols, r)) for r in cur.fetchall()}
    except Exception:
        logger.exception("controllo: lettura righe anomalie fallita ids=%s", ids)
        return {}


def _allegati(local_id: int) -> list[dict]:
    try:
        from .views import _list_attachments_for_local

        return [
            {"file_id": a["file_id"], "name": a["name"], "size": a["size"], "is_image": a.get("is_image")}
            for a in _list_attachments_for_local(local_id)
        ]
    except Exception:
        logger.warning("controllo: allegati non leggibili id=%s", local_id, exc_info=True)
        return []


def serializza_controllo(controllo, *, con_allegati: bool = True) -> dict:
    from .quality_models import AnomaliaSegnalazioneMeta

    metas = list(
        AnomaliaSegnalazioneMeta.objects.filter(controllo=controllo)
        .order_by("blocco_id", "ordine_nel_blocco", "id")
    )
    righe = carica_righe([m.anomalia_id for m in metas])
    per_blocco: dict[int, list] = {}
    for meta in metas:
        row = righe.get(meta.anomalia_id)
        if row is None:
            continue
        stati, testo = separa_descrizione(row.get("descrizione"))
        per_blocco.setdefault(meta.blocco_id, []).append({
            "local_id": meta.anomalia_id,
            "testo": testo,
            "avanzamento": str(row.get("avanzamento") or ""),
            "chiusa": bool(row.get("chiudere")),
            "aprire_rdc": bool(row.get("aprire_rdc")),
            "segnalare": bool(row.get("segnalare_cliente")),
            "note_capocommessa": str(row.get("note_capocommessa") or ""),
            "gestita": riga_gestita(row),
            "allegati": _allegati(meta.anomalia_id) if con_allegati else [],
        })
    blocchi = []
    for blocco in controllo.blocchi.all().order_by("ordine", "id"):
        anomalie = per_blocco.get(blocco.pk, [])
        blocchi.append({
            "id": blocco.pk,
            "ordine": blocco.ordine,
            "fase": blocco.fase,
            "seriali": blocco.seriali if isinstance(blocco.seriali, list) else [],
            "seriale_label": blocco.seriale_label,
            "stato_superficie": blocco.stato_superficie if isinstance(blocco.stato_superficie, list) else [],
            "anomalie": anomalie,
            "bloccato": any(a["gestita"] for a in anomalie),
        })
    return {
        "id": controllo.pk,
        "op_id": controllo.op_id,
        "op_item_id": controllo.op_item_id,
        "fase": controllo.fase,
        "mail_mode": controllo.mail_mode,
        "operatore": controllo.operatore_display,
        "created_at": controllo.created_at.isoformat() if controllo.created_at else "",
        "terminato": controllo.terminato_at is not None,
        "da_notificare": len(controllo.da_notificare or []),
        "ultima_mail_at": controllo.ultima_mail_at.isoformat() if controllo.ultima_mail_at else "",
        "mail_errore": controllo.mail_errore,
        "blocchi": blocchi,
    }


def accoda_notifica(controllo, ids: list[int]) -> None:
    pending = [int(i) for i in (controllo.da_notificare or [])]
    for i in ids:
        if int(i) not in pending:
            pending.append(int(i))
    controllo.da_notificare = pending
    controllo.ultimo_salvataggio_at = timezone.now()
    controllo.save(update_fields=["da_notificare", "ultimo_salvataggio_at", "updated_at"])


def gruppi_per_blocco(anomalie_rows: list[dict]) -> list[dict]:
    """Raggruppa righe anomalia per blocco di seriali (ordine di comparsa).

    Le righe nate fuori da un controllo restano gruppi da una riga sola.
    Arricchisce ogni riga con ``fase``, ``blocco_id``, ``blocco_label``.
    """
    from .quality_models import AnomaliaSegnalazioneMeta

    ids = []
    for row in anomalie_rows:
        try:
            ids.append(int(row.get("id")))
        except (TypeError, ValueError):
            continue
    metas = {
        m.anomalia_id: m
        for m in AnomaliaSegnalazioneMeta.objects.filter(anomalia_id__in=ids).select_related("blocco", "controllo")
    }
    gruppi: list[dict] = []
    per_chiave: dict[str, dict] = {}
    for row in anomalie_rows:
        try:
            meta = metas.get(int(row.get("id")))
        except (TypeError, ValueError):
            meta = None
        stati, testo = separa_descrizione(row.get("descrizione"))
        row["testo"] = testo
        row["stato_superficie"] = ", ".join(stati)
        row["fase"] = meta.fase if meta else row.get("fase", "")
        if meta and meta.blocco_id:
            chiave = f"b{meta.blocco_id}"
            titolo = meta.blocco.seriale_label or row.get("seriale") or ""
            controllo = meta.controllo
            sottotitolo = " · ".join(filter(None, [
                f"Fase {meta.blocco.fase}" if meta.blocco.fase else "",
                f"controllo di {controllo.operatore_display}" if controllo and controllo.operatore_display else "",
                timezone.localtime(controllo.created_at).strftime("%d/%m/%Y") if controllo and controllo.created_at else "",
            ]))
        else:
            chiave = f"r{row.get('id')}"
            titolo = row.get("seriale") or ""
            sottotitolo = f"Fase {row['fase']}" if row.get("fase") else ""
        row["blocco_id"] = meta.blocco_id if meta else None
        gruppo = per_chiave.get(chiave)
        if gruppo is None:
            gruppo = {"chiave": chiave, "titolo": titolo, "sottotitolo": sottotitolo, "righe": []}
            per_chiave[chiave] = gruppo
            gruppi.append(gruppo)
        gruppo["righe"].append(row)
    return gruppi


def _destinatari(op_id: str) -> tuple[dict | None, dict | None]:
    """(principale, copia): capocommessa e CAR; per i collaudi di benestare il CAR
    è il principale (stessa regola dell'automazione AU51)."""
    from automazioni.services import _resolve_op_recipients

    from .views import _op_is_benestare

    recipients = _resolve_op_recipients(op_id) or []
    cc_rec = next((r for r in recipients if r.get("role") == "CC" and r.get("email")), None)
    car_rec = next((r for r in recipients if r.get("role") == "CAR" and r.get("email")), None)
    if _op_is_benestare(op_id):
        primary = car_rec or cc_rec
    else:
        primary = cc_rec or car_rec
    secondary = None
    for rec in (cc_rec, car_rec):
        if rec and rec is not primary and (not primary or rec["email"].lower() != primary["email"].lower()):
            secondary = rec
    return primary, secondary


def invia_mail_controllo(controllo) -> dict:
    """Manda al capocommessa (in copia il CAR) la mail con il link di decisione per
    le anomalie del controllo non ancora comunicate. Idempotente: svuota la coda
    solo a invio riuscito."""
    from .mail_action_service import (
        _alert_admins_send_failure,
        send_anomalie_action_email,
        send_anomalie_update_confirmation,
    )

    ids = [int(i) for i in (controllo.da_notificare or [])]
    if not ids:
        return {"sent": False, "reason": "nessuna_anomalia"}
    righe = carica_righe(ids)
    rows = [righe[i] for i in ids if i in righe and not righe[i].get("chiudere")]
    if not rows:
        controllo.da_notificare = []
        controllo.save(update_fields=["da_notificare", "updated_at"])
        return {"sent": False, "reason": "nessuna_anomalia"}

    primary, secondary = _destinatari(controllo.op_id)
    try:
        if not primary:
            raise ValueError("Capocommessa e CAR dell'OP non hanno un indirizzo email risolvibile.")
        send_anomalie_action_email(
            recipient_email=primary["email"],
            recipient_display=primary.get("display") or primary["email"],
            op_id=controllo.op_id,
            op_nominativo=controllo.op_id,
            anomalie_rows=rows,
            action="aggiorna_avanzamento",
            expires_hours=SCADENZA_LINK_ORE,
            source_automation=f"controllo:{controllo.pk}",
            created_by=controllo.operatore,
            cc=[secondary["email"]] if secondary else None,
        )
    except Exception as exc:
        controllo.mail_tentativi = int(controllo.mail_tentativi or 0) + 1
        controllo.mail_errore = str(exc)[:2000]
        fields = ["mail_tentativi", "mail_errore", "updated_at"]
        if controllo.mail_tentativi >= MAX_TENTATIVI_MAIL:
            controllo.da_notificare = []
            fields.append("da_notificare")
            _alert_admins_send_failure(
                context="mail controllo OP al capocommessa",
                op_id=controllo.op_id,
                detail=f"Invio non riuscito dopo {controllo.mail_tentativi} tentativi: {controllo.mail_errore}",
            )
        controllo.save(update_fields=fields)
        logger.warning("controllo %s: mail al capocommessa non inviata: %s", controllo.pk, exc)
        return {"sent": False, "reason": "errore", "error": controllo.mail_errore}

    controllo.da_notificare = []
    controllo.ultima_mail_at = timezone.now()
    controllo.mail_tentativi = 0
    controllo.mail_errore = ""
    controllo.save(update_fields=["da_notificare", "ultima_mail_at", "mail_tentativi", "mail_errore", "updated_at"])

    # Copia di riepilogo (senza link) al segnalante e alla lista fissa «conferma
    # aggiornamenti», come per ogni altro salvataggio; CC/CAR hanno già la mail sopra.
    try:
        send_anomalie_update_confirmation(
            op_id=controllo.op_id,
            op_nominativo=controllo.op_id,
            anomalie_rows=rows,
            updates_summary=[
                {
                    "id": r["id"],
                    "seriale": r.get("seriale") or "",
                    "avanzamento": r.get("avanzamento") or "",
                    "descrizione": r.get("descrizione") or "",
                }
                for r in rows
            ],
            source_label=f"Controllo OP · fase {controllo.fase} · {controllo.operatore_display}",
            include_op_recipients=False,
        )
    except Exception:
        logger.warning("controllo %s: riepilogo al segnalante non inviato", controllo.pk, exc_info=True)

    return {
        "sent": True,
        "to": primary.get("display") or primary["email"],
        "cc": (secondary.get("display") or secondary["email"]) if secondary else "",
        "n": len(rows),
    }


def flush_controlli() -> dict:
    """Task periodico: manda le mail dei controlli pronti."""
    from .quality_models import AnomaliaControllo

    now = timezone.now()
    # Niente filtri sul JSONField (su SQL Server i confronti JSON sono fragili):
    # si guardano i controlli recenti e si verifica la coda in Python.
    candidati = AnomaliaControllo.objects.filter(ultimo_salvataggio_at__gte=now - timedelta(days=14))
    inviati = 0
    for controllo in candidati:
        if not controllo.da_notificare:
            continue
        fermo = now - controllo.ultimo_salvataggio_at
        if controllo.mail_mode == AnomaliaControllo.MailMode.FINE:
            pronto = controllo.terminato_at is not None or fermo >= timedelta(minutes=FINE_TIMEOUT_MINUTI)
        else:
            pronto = fermo >= timedelta(minutes=DEBOUNCE_MINUTI)
        if pronto and invia_mail_controllo(controllo).get("sent"):
            inviati += 1
    return {"controlli_inviati": inviati}
