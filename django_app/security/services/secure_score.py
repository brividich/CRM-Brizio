"""Microsoft Secure Score nella Panoramica del SOC (Graph ``security/secureScores``).

Al massimo ogni 12 ore (passo ``secure_score`` del ``security_cycle``), se acceso
da ``/soc/impostazioni/``: legge gli ultimi 30 punteggi giornalieri e i profili
dei controlli, e salva in ``m365.secure_score`` (impostazione tecnica del SOC):
punteggio attuale, massimo, percentuale, andamento, variazione su 30 giorni e le
5 azioni non completate che valgono più punti, con il link alla pagina di Microsoft.

Permesso applicativo Graph ``SecurityEvents.Read.All``. Sola lettura.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.models import SecurityCenterSetting
from security.services import soc_settings

logger = logging.getLogger(__name__)

PERMESSO = "SecurityEvents.Read.All"
STATE_KEY = "m365.secure_score"
OGNI_ORE = 12
AZIONI = 5


def calcola(punteggi: list[dict], profili: list[dict]) -> dict:
    """Dal grezzo di Graph al riepilogo da mostrare."""
    if not punteggi:
        return {}
    punteggi = sorted(punteggi, key=lambda s: str(s.get("createdDateTime") or ""), reverse=True)
    ultimo = punteggi[0]
    attuale = float(ultimo.get("currentScore") or 0)
    massimo = float(ultimo.get("maxScore") or 0)
    perc = round(attuale * 100 / massimo, 1) if massimo else 0.0
    storico = []
    for s in reversed(punteggi[:30]):
        mx = float(s.get("maxScore") or 0)
        storico.append(round(float(s.get("currentScore") or 0) * 100 / mx, 1) if mx else 0.0)
    profili_per_nome = {str(p.get("id") or ""): p for p in profili}
    azioni = []
    for c in ultimo.get("controlScores") or []:
        nome = str(c.get("controlName") or "")
        prof = profili_per_nome.get(nome) or {}
        if prof.get("deprecated"):
            continue
        max_c = float(prof.get("maxScore") or 0)
        guadagno = max_c - float(c.get("score") or 0)
        if guadagno <= 0:
            continue
        url = str(prof.get("actionUrl") or "")
        azioni.append({
            "titolo": str(prof.get("title") or nome)[:200],
            "categoria": str(c.get("controlCategory") or prof.get("controlCategory") or ""),
            "punti": round(guadagno, 1),
            "url": url if url.startswith("https://") else "",
        })
    azioni.sort(key=lambda a: a["punti"], reverse=True)
    return {
        "data": str(ultimo.get("createdDateTime") or "")[:10],
        "punteggio": round(attuale, 1),
        "massimo": round(massimo, 1),
        "percentuale": perc,
        "variazione_30gg": round(perc - storico[0], 1) if storico else 0.0,
        "storico": storico,
        "azioni": azioni[:AZIONI],
    }


def aggiorna(now=None, *, forza=False) -> dict:
    """Passo del ciclo SOC. Non solleva. ``forza``: legge anche se l'ultima lettura ha meno di ``OGNI_ORE`` ore."""
    from core import m365_graph

    if not soc_settings.value("defender.secure_score.attivo"):
        return {"attivo": False}
    now = now or timezone.now()
    stato = stato_attuale()
    letto = parse_datetime(str(stato.get("letto_alle") or "")) if stato else None
    if letto and now - letto < timedelta(hours=OGNI_ORE) and not forza:
        return {"saltato": True}
    try:
        punteggi = m365_graph.get_all(f"{m365_graph.GRAPH}/security/secureScores", permesso=PERMESSO,
                                      params={"$top": "30"}, max_pages=1)
        profili = m365_graph.get_all(f"{m365_graph.GRAPH}/security/secureScoreControlProfiles", permesso=PERMESSO,
                                     max_pages=5)
    except m365_graph.GraphError as exc:
        logger.warning("Secure Score: %s", exc)
        return {"ok": False, "errore": str(exc)[:300]}
    riepilogo = calcola(punteggi, profili)
    riepilogo["letto_alle"] = now.isoformat()
    SecurityCenterSetting.objects.update_or_create(
        key=STATE_KEY, defaults={"value": riepilogo, "value_type": "json", "category": "defender"},
    )
    return {"ok": True, "percentuale": riepilogo.get("percentuale")}


def stato_attuale() -> dict:
    from security.services.configuration import get_setting

    valore = get_setting(STATE_KEY, {})
    return valore if isinstance(valore, dict) else {}


def per_panoramica() -> dict | None:
    """Per la Panoramica: ``None`` se spento o mai letto."""
    if not soc_settings.value("defender.secure_score.attivo"):
        return None
    stato = stato_attuale()
    if not stato.get("massimo"):
        return None
    data = str(stato.get("data") or "")
    stato["data_label"] = f"{data[8:10]}/{data[5:7]}/{data[:4]}" if len(data) == 10 else data
    storico = stato.get("storico") or []
    if len(storico) >= 2:
        lo, hi = min(storico), max(storico)
        span = (hi - lo) or 1
        passo = 120 / (len(storico) - 1)
        stato["spark"] = " ".join(f"{i * passo:.1f},{30 - (v - lo) * 28 / span:.1f}" for i, v in enumerate(storico))
    return stato
