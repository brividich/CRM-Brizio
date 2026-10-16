"""«Il mio team»: la vista del capo reparto sulle persone di cui è responsabile.

Il team è quello del **responsabile effettivo** già usato da assenze, DPI e
anomalie (``reparto_canonico.build_responsabile_effettivo_map``: il responsabile
dell'area vince sul caporeparto del reparto). Nessun dato sanitario: per ogni
persona solo il semaforo di conformità alla mansione (in regola / in scadenza /
non conforme), senza esiti, giudizi o prescrizioni. Il link alla scheda compare
solo a chi la può aprire (ACL lato server, come la subnav).
"""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core import naming
from core.legacy_anagrafica import fetch_anagrafica_rows

logger = logging.getLogger(__name__)

ESITI = {
    "ko": ("danger", "Non conforme"),
    "warn": ("warning", "In scadenza"),
    "ok": ("ok", "In regola"),
    "na": ("neutral", "Nessun requisito"),
}
_ORDINE = {"ko": 0, "warn": 1, "ok": 2, "na": 3}


def membri_team(responsabile_id: int) -> list[int]:
    """Persone in forza il cui responsabile effettivo è ``responsabile_id`` (mai sé stesso)."""
    from anagrafica.models import DipendenteAnagraficaAziendale
    from anagrafica.services.reparto_canonico import build_responsabile_effettivo_map

    cessati = set(
        DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=False)
        .values_list("legacy_anagrafica_id", flat=True)
    )
    return sorted(
        lid for lid, resp in build_responsabile_effettivo_map().items()
        if int(resp) == int(responsabile_id) and int(lid) != int(responsabile_id) and lid not in cessati
    )


def _puo_aprire_scheda(request, legacy_id: int) -> bool:
    from core.middleware import acl_allows_path

    try:
        return bool(acl_allows_path(f"/anagrafica/dipendenti/{legacy_id}/", django_user=request.user,
                                    legacy_user=getattr(request, "legacy_user", None), request=None))
    except Exception:
        logger.warning("Il mio team: verifica ACL scheda fallita per %s", legacy_id, exc_info=True)
        return False


@login_required
def mio_team(request):
    from anagrafica.models import DipendenteAnagraficaAziendale
    from anagrafica.services import conformita as conformita_service
    from anagrafica.views import _current_legacy_anagrafica_id

    io = _current_legacy_anagrafica_id(request)
    membri = membri_team(io) if io else []
    righe: list[dict] = []
    if membri:
        anagrafiche = {int(r["id"]): r for r in fetch_anagrafica_rows(ids=membri)}
        aree = dict(
            DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=membri)
            .select_related("area_aziendale").values_list("legacy_anagrafica_id", "area_aziendale__nome")
        )
        mansioni = {lid: str(r.get("mansione") or "") for lid, r in anagrafiche.items() if r.get("mansione")}
        try:
            stati = conformita_service.stato_conformita_batch(
                membri, include_visite_dettaglio=False, mansioni_per_legacy=mansioni or None,
            )
        except Exception:
            logger.exception("Il mio team: conformità non calcolabile")
            stati = {}
        for lid in membri:
            r = anagrafiche.get(lid, {})
            esito = (stati.get(lid) or {}).get("complessivo") or "na"
            tono, etichetta = ESITI.get(esito, ESITI["na"])
            righe.append({
                "id": lid,
                "nome": naming.nome_completo(r.get("nome"), r.get("cognome")) or f"#{lid}",
                "reparto": str(r.get("reparto") or ""),
                "area": aree.get(lid) or "",
                "mansione": str(r.get("mansione") or ""),
                "esito": esito, "tono": tono, "esito_label": etichetta,
                "scheda": _puo_aprire_scheda(request, lid),
            })
        righe.sort(key=lambda x: (_ORDINE.get(x["esito"], 9), x["nome"]))
    conteggi = {k: sum(1 for r in righe if r["esito"] == k) for k in ESITI}
    return render(request, "anagrafica/pages/mio_team.html", {
        "righe": righe,
        "collegato": io is not None,
        "conteggi": conteggi,
    })
