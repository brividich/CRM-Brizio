"""Permesso ripetuto: più richieste (una per giorno) gestite come una sola.

La prima richiesta della serie (``capofila``) è l'unica che fa partire le
automazioni: una sola mail di approvazione al capo e una sola conferma a chi
chiede e ad assenza@. Le altre si salvano col flag che spegne i trigger
(``_set_automation_queue_skip``) e seguono la decisione presa sulla capofila.

Le mail della capofila dicono «Permesso ripetuto dal … al …» con i giorni
(``blocco_mail``). Un giorno della serie si può ancora modificare o decidere a
parte dal portale: la propagazione tocca solo i giorni ancora in attesa.
"""
from __future__ import annotations

import html
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

IN_ATTESA = 2


def registra(ids: list[int]) -> None:
    """Lega le richieste ``ids`` alla prima. Va chiamata nella transazione degli insert."""
    from .models import AssenzaSerie

    ids = [int(i) for i in ids if i is not None]
    if len(ids) < 2:
        return
    AssenzaSerie.objects.bulk_create([AssenzaSerie(assenza_id=i, capofila_id=ids[0]) for i in ids])


def _ids_serie(capofila_id: int) -> list[int]:
    from .models import AssenzaSerie

    return list(
        AssenzaSerie.objects.filter(capofila_id=capofila_id).order_by("assenza_id").values_list("assenza_id", flat=True)
    )


def _dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    testo = str(value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(testo[:26], fmt)
        except ValueError:
            continue
    return None


def riepilogo(assenza_id) -> dict | None:
    """Dati della serie di cui ``assenza_id`` è capofila, oppure ``None``.

    Un giorno che non è la capofila non ha riepilogo: le sue mail (se un giorno
    viene deciso a parte) parlano solo di quel giorno.
    """
    try:
        aid = int(assenza_id)
    except (TypeError, ValueError):
        return None
    try:
        ids = _ids_serie(aid)
        if len(ids) < 2 or ids[0] != aid:
            return None
        from .views import _helpers

        segnaposti = ", ".join(["%s"] * len(ids))
        righe = _helpers._fetch_all_dict(
            f"SELECT id, data_inizio, data_fine FROM assenze WHERE id IN ({segnaposti})", ids
        )
    except Exception:
        logger.warning("assenze.serie: serie di %s non letta", assenza_id, exc_info=True)
        return None
    giorni = sorted(
        (_dt(r.get("data_inizio")), _dt(r.get("data_fine"))) for r in righe if _dt(r.get("data_inizio"))
    )
    if len(giorni) < 2:
        return None
    inizio, fine = giorni[0]
    return {
        "dal": inizio.date(),
        "al": giorni[-1][0].date(),
        "n": len(giorni),
        "giorni": [g[0].date() for g in giorni],
        "ora_inizio": inizio.strftime("%H:%M"),
        "ora_fine": fine.strftime("%H:%M") if fine else "",
    }


def testo(r: dict) -> str:
    elenco = ", ".join(g.strftime("%d/%m") for g in r["giorni"])
    orario = f", dalle {r['ora_inizio']} alle {r['ora_fine']}" if r.get("ora_fine") else ""
    return (
        f"Permesso ripetuto dal {r['dal']:%d/%m/%Y} al {r['al']:%d/%m/%Y}: "
        f"{r['n']} giorni lavorativi ({elenco}){orario}."
    )


def suffisso_oggetto(r: dict) -> str:
    return f" · permesso ripetuto dal {r['dal']:%d/%m/%Y} al {r['al']:%d/%m/%Y}"


def blocco_mail(source_code, payload, *, approvazione: bool = False) -> tuple[str, str, dict | None]:
    """(testo, html, riepilogo) da mettere in testa alle mail della capofila; vuoti se non è una serie."""
    if str(source_code or "") != "assenze" or not isinstance(payload, dict):
        return "", "", None
    r = riepilogo(payload.get("id"))
    if r is None:
        return "", "", None
    riga = testo(r)
    nota = " La decisione vale per tutti i giorni ancora in attesa." if approvazione else ""
    html_blocco = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;margin:0 0 16px;">'
        '<tr><td style="padding:14px 16px;border-left:4px solid #0f766e;background:#f0fdfa;border-radius:10px;'
        'color:#134e4a;font-size:14px;line-height:1.6;">'
        f"<strong>{html.escape(riga)}</strong>{html.escape(nota)}"
        "</td></tr></table>"
    )
    return f"{riga}{nota}\n\n", html_blocco, r


def propaga(capofila_id) -> int:
    """Porta la decisione della capofila sui giorni della serie ancora in attesa.

    Scrive col flag che spegne i trigger delle automazioni (le mail sono già
    partite per la capofila) e mette ogni giorno in coda verso SharePoint.
    Ritorna quanti giorni ha aggiornato. Fail-safe.
    """
    try:
        aid = int(capofila_id)
    except (TypeError, ValueError):
        return 0
    try:
        ids = _ids_serie(aid)
        if len(ids) < 2 or ids[0] != aid:
            return 0
        from . import hr
        from .views import _helpers

        capo = _helpers._get_assenza(aid) or {}
        mod = _helpers._as_int(capo.get("moderation_status"))
        if mod is None or mod == IN_ATTESA:
            return 0
        consenso = _helpers._MOD_TO_CONSENSO.get(str(mod)) or _helpers._norm_consenso(capo.get("consenso"))
        aggiornati = 0
        for mid in ids[1:]:
            membro = _helpers._get_assenza(mid) or {}
            if _helpers._as_int(membro.get("moderation_status")) not in (None, IN_ATTESA):
                continue
            updates = {"consenso": consenso, "moderation_status": mod, "modified_datetime": _helpers.timezone.now()}
            updates.update(_helpers._approval_timestamp_update(consenso, membro))
            _helpers._set_automation_queue_skip(True)
            try:
                ok = _helpers._update_assenza(mid, updates)
            finally:
                _helpers._set_automation_queue_skip(False)
            if not ok:
                continue
            hr.registra(
                mid, "approvata" if consenso == "Approvato" else "rifiutata",
                utente="", prima=membro, dopo=updates, motivo=f"Decisa con il permesso ripetuto #{aid}",
            )
            _helpers._sp_enqueue_upsert(mid)
            aggiornati += 1
        return aggiornati
    except Exception:
        logger.warning("assenze.serie: decisione di %s non propagata", capofila_id, exc_info=True)
        return 0
