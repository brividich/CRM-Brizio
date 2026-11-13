"""API «Cambia incaricato» di un'anomalia (capocommessa, CAR, amministratori).

- ``GET /api/anomalie/incaricato/persone?ruolo=cc``: chi si può scegliere;
- ``POST /api/anomalie/incaricato``: ``{local_id, ruolo, persona_id (vuoto = di serie), nota}``.

Errori sempre in JSON. Ogni cambio va nel registro attività (``incaricato``) con
prima e dopo, e il nuovo incaricato riceve notifica e mail.
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.audit import log_action

from . import incaricati as inc

logger = logging.getLogger(__name__)


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": msg}, status=status)


@login_required
def api_incaricato_persone(request):
    return JsonResponse({"success": True, "persone": inc.persone("tutti")})


@login_required
@require_POST
def api_incaricato_cambia(request):
    from . import decisione_qualita as dq
    from .mail_action_service import log_anomalia_portal_action
    from .qualita_views import _chi, _riga
    from .views import _capo_car_di_op, _client_ip, _safe_text, get_legacy_user

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        data = {}
    try:
        local_id = int(str(data.get("local_id") or "").split(":")[-1])
    except ValueError:
        return _err("local_id non valido")
    ruolo = str(data.get("ruolo") or "").strip()
    if ruolo and not inc.ruolo_valido(ruolo):
        return _err("Ruolo non valido")
    nota = _safe_text(data.get("nota"), 500) or ""
    row = _riga(local_id)
    if row is None:
        return _err("Anomalia non trovata", 404)
    if row.get("chiudere"):
        return _err("L'anomalia è chiusa")
    info = dq.info_per_anomalie([local_id]).get(local_id)
    if not inc.puo_cambiare(request, row, info):
        return _err("L'incaricato lo cambiano capocommessa, CAR e amministratori", 403)
    # Senza ruolo (il caso normale): l'anomalia passa subito alla persona scelta,
    # al posto di chi la ha adesso.
    ruolo = ruolo or inc.ruolo_attuale(dq.ruoli_in_carico(row, info))
    if not ruolo:
        return _err("L'anomalia non è in carico a nessuno (è chiusa?)")

    raw_id = str(data.get("persona_id") or "").strip()
    nuova = None
    if raw_id:
        nuova = inc.persona(raw_id)
        if nuova is None:
            return _err("Persona non trovata fra gli utenti attivi", 404)

    attuale = ((info or {}).get("incaricati") or {}).get(ruolo)
    if (attuale or {}).get("id") == (nuova or {}).get("id"):
        return _err("È già l'incaricato" if nuova else "Il ruolo segue già la regola di serie")
    chi = _chi(request)
    try:
        prima, dopo = inc.imposta(local_id, ruolo, nuova, chi=chi, nota=nota)
    except DatabaseError:
        logger.exception("incaricato: salvataggio fallito id=%s", local_id)
        return _err("Incaricato non salvato: il database non ha la tabella degli incaricati "
                    "(serve «migrate anomalie»)", 500)

    op_id = str(row.get("ex_op_nominativo") or "").strip()
    di_serie = inc.nome_di_serie(ruolo, row, info)
    etichetta = "Incaricato"
    modifiche = [[etichetta, (prima or {}).get("nome") or f"{di_serie} (di serie)",
                  (dopo or {}).get("nome") or f"{di_serie} (di serie)"]]
    legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    log_anomalia_portal_action(
        anomalia_id=local_id, op_id=op_id, action="incaricato", user=request.user,
        legacy_user_id=int(legacy.id) if legacy else None, user_display=chi, note=nota,
        ip_address=_client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", ""),
        payload={"modifiche": modifiche, "ruolo": ruolo},
    )
    try:
        log_action(request, "anomalia_incaricato", "anomalie", {
            "local_id": local_id, "op_id": op_id, "ruolo": ruolo,
            "da": (prima or {}).get("id"), "a": (dopo or {}).get("id"),
        })
    except Exception:
        pass
    avviso = {}
    if dopo:
        try:
            avviso = inc.avvisa(anomalia_id=local_id, op_id=op_id, ruolo=ruolo, persona_id=dopo["id"], chi=chi, nota=nota,
                                seriale=str(row.get("seriale") or ""), descrizione=str(row.get("descrizione") or ""))
        except Exception:
            logger.warning("incaricato: avviso non inviato id=%s", local_id, exc_info=True)

    info = dq.info_per_anomalie([local_id]).get(local_id)
    capo, car = _capo_car_di_op(op_id)
    io = dq.chi_sono(request, capo, car)
    return JsonResponse({
        "success": True,
        "incaricati": (info or {}).get("incaricati") or {},
        "ruoli_in_carico": sorted(dq.ruoli_in_carico(row, info)),
        "in_carico_a_me": dq.in_carico_a_me(io, row, info),
        "puo_cambiare_incaricato": inc.puo_cambiare(request, row, info),
        "mail": bool(avviso.get("mail")),
        "senza_email": bool(dopo) and not avviso.get("email"),
    })
