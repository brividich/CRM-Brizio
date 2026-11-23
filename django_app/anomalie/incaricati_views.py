"""API «Cambia incaricato» di un'anomalia (capocommessa, CAR, amministratori).

- ``GET /api/anomalie/incaricato/persone?ruolo=cc``: chi si può scegliere;
- ``POST /api/anomalie/incaricato``: ``{local_id, ruolo, persona_id (vuoto = di serie), nota}``;
- ``POST /api/anomalie/incaricato/op``: «Cambia capocommessa» ``{op_id, persona_id (vuoto = di
  serie), nota, ambito: "op" | "anomalie", anomalie: [id]}``. Di serie vale per tutto l'OP
  (anche le anomalie che si apriranno e le mail dell'OP); con ``ambito="anomalie"`` solo
  per le anomalie scelte.

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
        logger.exception("api_incaricato_cambia: registro attività non scritto")
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


@login_required
@require_POST
def api_incaricato_op(request):
    from .mail_action_service import log_anomalia_portal_action
    from .qualita_views import _chi, _riga
    from .views import _capo_car_di_op, _client_ip, _safe_text, get_legacy_user

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        data = {}
    op_id = _safe_text(data.get("op_id"), 200) or ""
    if not op_id:
        return _err("OP mancante")
    ambito = "anomalie" if str(data.get("ambito") or "").strip() == "anomalie" else "op"
    nota = _safe_text(data.get("nota"), 500) or ""
    raw_id = str(data.get("persona_id") or "").strip()
    nuova = None
    if raw_id:
        nuova = inc.persona(raw_id)
        if nuova is None:
            return _err("Persona non trovata fra gli utenti attivi", 404)
    capo, car = _capo_car_di_op(op_id)
    chi = _chi(request)
    legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    legacy_id = int(legacy.id) if legacy else None
    ip, ua = _client_ip(request), request.META.get("HTTP_USER_AGENT", "")
    di_serie = capo or "capocommessa dell'OP"

    def _nome(voce):
        return (voce or {}).get("nome") or f"{di_serie} (di serie)"

    if ambito == "op":
        if not inc.puo_cambiare_su_op(request, capo, car, op_id):
            return _err("Il capocommessa dell'OP lo cambiano capocommessa, CAR e amministratori", 403)
        try:
            attuale = inc.per_op(op_id).get("cc")
            righe = inc.anomalie_op(op_id)
            correnti = inc.per_anomalie([r["id"] for r in righe])
            singole = sum(1 for v in correnti.values() if "cc" in v and not v["cc"].get("op"))
            if (attuale or {}).get("id") == (nuova or {}).get("id") and not singole:
                return _err("È già il capocommessa di tutto l'OP" if nuova else "L'OP ha già il capocommessa di serie")
            prima, dopo, ripulite = inc.imposta_op(op_id, "cc", nuova, chi=chi, nota=nota)
        except DatabaseError:
            logger.exception("capocommessa OP: salvataggio fallito op=%s", op_id)
            return _err("Capocommessa non salvato: il database non ha la tabella degli incaricati dell'OP "
                        "(serve «migrate anomalie»)", 500)
        modifiche = [["Capocommessa dell'OP", _nome(prima), _nome(dopo)]]
        if ripulite:
            modifiche.append(["Anomalie con un capocommessa scelto a parte", str(ripulite), "seguono l'OP"])
        # Evento dell'OP (anomalia 0, come «Modifica OP»): log_anomalia_portal_action lo salterebbe.
        try:
            from .mail_action_models import AnomaliaActionLog

            AnomaliaActionLog.objects.create(
                anomalia_id=0, op_id=op_id[:100], user=request.user, legacy_user_id=legacy_id,
                user_display=chi[:200], action="capo_op", note=nota, source=AnomaliaActionLog.Source.PORTAL,
                ip_address=ip, user_agent=str(ua)[:500],
                payload={"modifiche": modifiche, "ruolo": "cc", "ambito": "op"},
            )
        except Exception:
            logger.warning("capocommessa OP: registro non scritto op=%s", op_id, exc_info=True)
        _audit(request, {"op_id": op_id, "ambito": "op", "da": (prima or {}).get("id"), "a": (dopo or {}).get("id")})
        avviso = _avvisa(op_id, dopo, chi, nota, righe, tutto_op=True)
        return JsonResponse({"success": True, "ambito": "op", "capo_affidato": inc.per_op(op_id).get("cc"),
                             "capo_di_serie": capo, "n": len([r for r in righe if not r.get("chiudere")]),
                             "mail": bool(avviso.get("mail")), "senza_email": bool(dopo) and not avviso.get("email")})

    # Solo alcune anomalie dell'OP.
    try:
        ids = sorted({int(str(x).split(":")[-1]) for x in (data.get("anomalie") or [])})
    except (TypeError, ValueError):
        return _err("Anomalie non valide")
    if not ids:
        return _err("Scegli almeno un'anomalia")
    from . import decisione_qualita as dq

    info = dq.info_per_anomalie(ids)
    scelte = []
    for aid in ids:
        row = _riga(aid)
        if row is None or inc.op_key(row.get("ex_op_nominativo")) != inc.op_key(op_id):
            return _err("Un'anomalia scelta non è di questo OP")
        if row.get("chiudere"):
            continue
        if not inc.puo_cambiare(request, row, info.get(aid)):
            return _err("Il capocommessa lo cambiano capocommessa, CAR e amministratori", 403)
        scelte.append((aid, row))
    if not scelte:
        return _err("Le anomalie scelte sono tutte chiuse")
    cambiate = []
    try:
        for aid, row in scelte:
            attuale = ((info.get(aid) or {}).get("incaricati") or {}).get("cc")
            propria = bool(attuale) and not attuale.get("op")
            # Già sua (o già di serie senza scelta propria da togliere): niente da fare.
            if nuova is None and not propria:
                continue
            if nuova is not None and (attuale or {}).get("id") == nuova["id"] and propria:
                continue
            prima, dopo = inc.imposta(aid, "cc", nuova, chi=chi, nota=nota)
            dopo_eff = dopo or inc.per_op(op_id).get("cc")
            log_anomalia_portal_action(
                anomalia_id=aid, op_id=op_id, action="incaricato", user=request.user, legacy_user_id=legacy_id,
                user_display=chi, note=nota, ip_address=ip, user_agent=ua,
                payload={"modifiche": [["Capocommessa", _nome(prima or attuale), _nome(dopo_eff)]], "ruolo": "cc"},
            )
            cambiate.append(row)
    except DatabaseError:
        logger.exception("capocommessa anomalie: salvataggio fallito op=%s", op_id)
        return _err("Capocommessa non salvato: il database non ha la tabella degli incaricati "
                    "(serve «migrate anomalie»)", 500)
    if not cambiate:
        return _err("Nessuna anomalia cambiata: hanno già quel capocommessa")
    _audit(request, {"op_id": op_id, "ambito": "anomalie", "anomalie": [r.get("id") for r in cambiate],
                     "a": (nuova or {}).get("id")})
    avviso = _avvisa(op_id, nuova, chi, nota, cambiate, tutto_op=False)
    return JsonResponse({"success": True, "ambito": "anomalie", "n": len(cambiate),
                         "mail": bool(avviso.get("mail")), "senza_email": bool(nuova) and not avviso.get("email")})


def _audit(request, dati: dict) -> None:
    try:
        log_action(request, "anomalia_capo_op", "anomalie", dati)
    except Exception:
        logger.exception("_audit: registro attività non scritto")


def _avvisa(op_id, dopo, chi, nota, righe, *, tutto_op: bool) -> dict:
    if not dopo:
        return {}
    try:
        return inc.avvisa_op(op_id=op_id, persona_id=dopo["id"], chi=chi, nota=nota, righe=righe, tutto_op=tutto_op)
    except Exception:
        logger.warning("capocommessa OP: avviso non inviato op=%s", op_id, exc_info=True)
        return {}
