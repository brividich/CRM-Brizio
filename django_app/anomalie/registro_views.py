"""Registro attività delle anomalie (supervisore): ogni azione registrata, leggibile.

``GET /api/anomalie/registro``: eventi di ``AnomaliaActionLog`` (portale, link della
mail, sistema) con chi, cosa, su quale anomalia, i campi cambiati (``payload
["modifiche"]``) e da dove. Sola lettura, per amministratori del modulo e per la lista
«Supervisori» (email) delle notifiche. Errori sempre in JSON.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone

from .codice import codice_anomalia, id_da_codice

logger = logging.getLogger(__name__)

# Azione registrata → verbo della frase.
VERBI = {
    "crea": "ha inserito", "aggiorna": "ha modificato", "chiudi": "ha chiuso", "riapri": "ha riaperto",
    "segnalato": "ha registrato la segnalazione su", "qualita": "ha aggiornato la decisione qualità di",
    "richiesta_info": "ha chiesto informazioni su", "risposta_info": "ha risposto alla richiesta di informazioni su",
    "risposta_cliente": "ha registrato la risposta del cliente su", "risposta_terzista": "ha registrato la risposta del terzista su",
    "azione": "ha registrato l'azione effettuata su", "spostata": "ha spostato («Taglia»)",
    "op_modificato": "ha modificato i dati dell'OP di", "prendi_in_carico": "ha preso in carico",
    "approva": "ha approvato dal link della mail", "respingi": "ha respinto dal link della mail",
    "richiedi_modifica": "ha chiesto una modifica dal link della mail su", "aggiorna_avanzamento": "ha deciso dal link della mail su",
    "visualizza": "ha visto dal link della mail",
}
# Filtro «Azione» della pagina → azioni registrate.
GRUPPI = {
    "inserimento": {"crea"},
    "clona": {"crea"},
    "modifica": {"aggiorna", "qualita", "aggiorna_avanzamento", "approva", "respingi", "richiedi_modifica",
                 "op_modificato", "prendi_in_carico"},
    "chiusura": {"chiudi", "riapri"},
    "segnalazioni": {"segnalato", "risposta_cliente", "risposta_terzista"},
    "informazioni": {"richiesta_info", "risposta_info"},
    "spostamenti": {"spostata"},
    "azioni": {"azione"},
}
FONTI = {"portal": "Portale", "mail_action": "Link della mail", "system": "Sistema"}


def puo_vedere_registro(request) -> bool:
    from core.acl import user_can_modulo_action

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        if user_can_modulo_action(request, "anomalie", "admin_anomalie"):
            return True
    except Exception:
        pass
    try:
        from .escalation_config import LISTA_SUPERVISORI_KEY
        from .views import _load_anomalie_lists

        email = str(getattr(user, "email", "") or "").strip().lower()
        supervisori = {str(e).strip().lower() for e in (_load_anomalie_lists().get(LISTA_SUPERVISORI_KEY) or [])}
        return bool(email) and email in supervisori
    except Exception:
        return False


def _seriali(ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    try:
        from .automazioni_service import _fetch

        out = {}
        for i in range(0, len(ids), 500):
            blocco = ids[i:i + 500]
            for r in _fetch(f"SELECT id, seriale FROM anomalie WHERE id IN ({','.join(['%s'] * len(blocco))})", blocco):
                out[int(r["id"])] = str(r.get("seriale") or "")
        return out
    except Exception:
        logger.warning("registro: S/N non letti", exc_info=True)
        return {}


@login_required
def api_registro(request):
    from .mail_action_models import AnomaliaActionLog

    if not puo_vedere_registro(request):
        return JsonResponse({"success": False, "error": "Il registro attività lo vedono amministratori e supervisori."},
                            status=403)
    g = request.GET
    try:
        giorni = max(1, min(int(g.get("giorni") or 7), 365))
    except ValueError:
        giorni = 7
    qs = AnomaliaActionLog.objects.filter(created_at__gte=timezone.now() - timedelta(days=giorni))
    op = str(g.get("op") or "").strip()
    if op:
        qs = qs.filter(op_id__iexact=op)
    codice = str(g.get("codice") or "").strip()
    if codice:
        aid = id_da_codice(codice)
        if aid is None:
            return JsonResponse({"success": True, "eventi": [], "persone": [], "op": []})
        qs = qs.filter(anomalia_id=aid)
    persona = str(g.get("persona") or "").strip()
    if persona:
        qs = qs.filter(user_display__icontains=persona)
    azione = str(g.get("azione") or "").strip()
    if azione in GRUPPI:
        qs = qs.filter(action__in=GRUPPI[azione])
    fonte = str(g.get("fonte") or "").strip()
    if fonte in FONTI:
        qs = qs.filter(source=fonte)
    logs = list(qs.order_by("-created_at")[:400])
    if azione == "clona":
        logs = [x for x in logs if (x.payload or {}).get("clonata_da")]
    elif azione == "inserimento":
        logs = [x for x in logs if not (x.payload or {}).get("clonata_da")]
    seriali = _seriali(sorted({int(x.anomalia_id) for x in logs if x.anomalia_id}))
    eventi = []
    for x in logs:
        quando = timezone.localtime(x.created_at)
        payload = x.payload if isinstance(x.payload, dict) else {}
        modifiche = [m for m in (payload.get("modifiche") or []) if isinstance(m, (list, tuple)) and len(m) == 3]
        if not modifiche and x.previous_status and x.new_status and x.previous_status != x.new_status:
            modifiche = [["Stato", x.previous_status, x.new_status]]
        verbo = VERBI.get(x.action, x.action)
        if x.action == "crea" and payload.get("clonata_da"):
            verbo = f"ha clonato da {codice_anomalia(payload['clonata_da'])}"
        eventi.append({
            "id": x.pk, "quando": quando.isoformat(), "giorno": quando.strftime("%Y-%m-%d"), "ora": quando.strftime("%H:%M"),
            "chi": x.user_display or "—", "azione": x.action, "verbo": verbo,
            "anomalia_id": x.anomalia_id, "codice": codice_anomalia(x.anomalia_id), "op_id": x.op_id,
            "seriale": seriali.get(int(x.anomalia_id), "") if x.anomalia_id else "",
            "modifiche": modifiche, "note": (x.note or "")[:500], "fonte": FONTI.get(x.source, x.source),
        })
    persone = sorted({e["chi"] for e in eventi if e["chi"] != "—"})
    return JsonResponse({"success": True, "eventi": eventi, "persone": persone,
                         "op": sorted({e["op_id"] for e in eventi if e["op_id"]})})
