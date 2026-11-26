"""«Correggi» un'anomalia chiusa senza riaprirla.

Capocommessa e controllore correggono un'anomalia già chiusa (errore di battitura,
dato mancante) senza riaprirla: resta chiusa, la correzione chiede un motivo e va
nel registro attività con «prima → dopo».

- **Testo** della segnalazione: il controllore (chi l'ha inserita, chi ha eseguito
  il controllo, l'incaricato «controllore») e chi corregge le note.
- **Note del capocommessa**: chi modifica le anomalie dell'OP (capocommessa, anche
  affidato con «Cambia capocommessa», amministratori del modulo).
- Allegati: si caricano come sempre dal riquadro «Allegati».
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connections
from django.http import JsonResponse
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

MAX_TESTO = 4000
MOTIVO_MIN = 3


def permessi(request, local_id: int, op_id: str, *, autore=None) -> dict:
    """``{"testo": bool, "note": bool}`` su un'anomalia chiusa."""
    from .incaricati import e_incaricato, per_anomalie
    from .views import _can_edit_anomalie_for_op, _is_controllore_anomalia, _request_legacy_user_id

    note = bool(_can_edit_anomalie_for_op(request, op_id))
    testo = note
    if not testo:
        me = _request_legacy_user_id(request)
        if autore is not None and me is not None:
            try:
                testo = int(autore) == int(me)
            except (TypeError, ValueError):
                testo = False
        if not testo:
            testo = bool(_is_controllore_anomalia(request, local_id))
        if not testo and me is not None:
            try:
                testo = e_incaricato({"incaricati": per_anomalie([local_id]).get(int(local_id)) or {}}, "controllore", me)
            except Exception:
                testo = False
    return {"testo": testo, "note": note}


def segna_righe(request, chiuse: list[dict], op_title: str, autori: dict) -> None:
    """``correggi_chiusa`` sulle righe chiuse dell'elenco (una lettura dei permessi dell'OP)."""
    from .views import _can_edit_anomalie_for_op, _controlli_dell_utente, _request_legacy_user_id

    if not chiuse:
        return
    note = bool(_can_edit_anomalie_for_op(request, op_title))
    me = _request_legacy_user_id(request)
    controlli = _controlli_dell_utente(request) if not note else set()
    incaricati = {}
    if not note and me is not None:
        try:
            from .incaricati import per_anomalie

            incaricati = per_anomalie([r.get("local_id") for r in chiuse if r.get("local_id")])
        except Exception:
            incaricati = {}
    for r in chiuse:
        testo = note
        if not testo and me is not None:
            autore = autori.get(r.get("local_id"))
            testo = bool((autore is not None and int(autore) == me)
                         or (r.get("controllo_id") and r["controllo_id"] in controlli))
            if not testo:
                voce = (incaricati.get(r.get("local_id")) or {}).get("controllore") or {}
                testo = str(voce.get("id")) == str(me)
        r["correggi_chiusa"] = {"testo": bool(testo), "note": note} if (testo or note) else None


@login_required
@require_POST
def api_correggi_chiusa(request):
    """``POST {local_id, testo?, note?, motivo}``: corregge un'anomalia chiusa, che resta chiusa."""
    from .mail_action_service import log_anomalia_portal_action
    from .views import (_client_ip, _current_user_identity, _fetch_all_dict, _has_table, _json_error,
                        get_legacy_user, legacy_table_columns, log_action, modifiche_registro)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        local_id = int(data.get("local_id"))
    except Exception:
        return _json_error("local_id non valido", status=400)
    if not _has_table("anomalie"):
        return _json_error("Tabella anomalie non disponibile", status=500)
    righe = _fetch_all_dict("SELECT TOP 1 id, ex_op_nominativo, chiudere, descrizione, note_capocommessa, "
                            "created_by_user_id FROM anomalie WHERE id = %s", [local_id])
    if not righe:
        return _json_error("Anomalia non trovata", status=404)
    row = righe[0]
    if not row.get("chiudere"):
        return _json_error("L'anomalia è aperta: modificala dalla decisione.", status=400)
    op_id = str(row.get("ex_op_nominativo") or "").strip()
    puo = permessi(request, local_id, op_id, autore=row.get("created_by_user_id"))
    if not (puo["testo"] or puo["note"]):
        return _json_error("Permesso negato: correggono un'anomalia chiusa il capocommessa e il controllore", status=403)

    motivo = str(data.get("motivo") or "").strip()[:500]
    if len(motivo) < MOTIVO_MIN:
        return _json_error("Scrivi il motivo della correzione.", status=400)
    nuovi = {}
    if "testo" in data:
        if not puo["testo"]:
            return _json_error("Permesso negato: il testo lo corregge il controllore", status=403)
        testo = str(data.get("testo") or "").strip()[:MAX_TESTO]
        if not testo:
            return _json_error("Il testo della segnalazione non può essere vuoto.", status=400)
        nuovi["descrizione"] = testo
    if "note" in data:
        if not puo["note"]:
            return _json_error("Permesso negato: le note le corregge il capocommessa", status=403)
        nuovi["note_capocommessa"] = str(data.get("note") or "").strip()[:MAX_TESTO]
    prima = {k: str(row.get(k) or "") for k in nuovi}
    nuovi = {k: v for k, v in nuovi.items() if v != prima[k]}
    if not nuovi:
        return _json_error("Nessuna modifica da salvare.", status=400)

    cols = legacy_table_columns("anomalie") or set()
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    sets, params = [], []
    for k, v in nuovi.items():
        sets.append(f"{k} = %s")
        params.append(v)
    if "modified_datetime" in cols:
        sets.append("modified_datetime = SYSUTCDATETIME()")
    if "modified_by_user_id" in cols and legacy_user:
        sets.append("modified_by_user_id = %s")
        params.append(legacy_user.id)
    try:
        with connections["default"].cursor() as cur:
            cur.execute(f"UPDATE anomalie SET {', '.join(sets)} WHERE id = %s AND COALESCE(chiudere, 0) = 1",
                        params + [local_id])
    except DatabaseError as exc:
        return _json_error(str(exc), status=500)

    chi = _current_user_identity(request).get("name") or request.user.username
    try:
        log_action(request, "anomalia_corretta_chiusa", "anomalie",
                   {"local_id": local_id, "op_id": op_id, "campi": sorted(nuovi), "motivo": motivo})
    except Exception:
        logger.exception("api_correggi_chiusa: registro attività non scritto")
    try:
        log_anomalia_portal_action(
            anomalia_id=local_id, op_id=op_id, action="corretta", user=request.user,
            legacy_user_id=int(legacy_user.id) if legacy_user else None, user_display=chi,
            previous_status="Chiusa", new_status="Chiusa", note=f"Motivo: {motivo}",
            ip_address=_client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", ""),
            payload={"modifiche": modifiche_registro(prima, nuovi), "motivo": motivo},
        )
    except Exception:
        logger.warning("api_correggi_chiusa: timeline non scritta id=%s", local_id, exc_info=True)
    return JsonResponse({"success": True, "local_id": local_id, **{
        "testo": nuovi.get("descrizione", prima.get("descrizione")),
        "note": nuovi.get("note_capocommessa", prima.get("note_capocommessa")),
    }})
