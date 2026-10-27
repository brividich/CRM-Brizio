"""«Reparti, aree e capi» (26/10/2026): la struttura e chi ne è il capo, in una pagina.

Un criterio per tutti (``services.capi_mansione``), quello del file della
Qualità: il capo del reparto è chi ha la «Responsabilità del reparto», il
responsabile dell'area chi ha la «Responsabilità dell'area» (area senza ruolo
responsabile = segue il reparto). Da qui si sceglie il ruolo responsabile, si
assegna o si toglie la persona e si fa una volta il passaggio dai capi scelti a mano. Vedono tutti quelli con accesso a ``/anagrafica/aree/``;
cambiano solo gli amministratori dell'anagrafica.
"""
from __future__ import annotations

from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import AreaAziendale, Reparto, RuoloOperativo
from .models_skillmatrix import AbilitazioneMacchina, CompetenzaSkm
from .services import capi_mansione, capo_team, mansionario_struttura
from .views import _helpers

MODULE = "anagrafica"


def _torna(ancora: str = ""):
    url = reverse("anagrafica:aree_list")
    return redirect(f"{url}#{ancora}" if ancora else url)


def _ruoli_opts():
    return list(RuoloOperativo.objects.filter(is_active=True).order_by("nome"))


def _contesto(request) -> dict:
    regola = capo_team.regola_unica_attiva()
    mappa = capo_team.mappa_capi()
    in_forza = set(mappa)
    picker = _helpers._dipendenti_picker_rows()
    nomi = {p["id"]: p["label"] for p in picker}

    from .services.struttura_v8 import area_coincide_col_reparto

    reparti = list(Reparto.objects.select_related("ruolo_responsabile").order_by("nome"))
    aree = list(AreaAziendale.objects.select_related("ruolo_responsabile", "reparto").order_by("nome"))
    responsabilita = capi_mansione.mansioni_responsabilita()
    resp_aree = capi_mansione.mansioni_responsabilita_aree()
    mansioni = {m.pk: m for m in CompetenzaSkm.objects.filter(
        pk__in=set(responsabilita.values()) | set(resp_aree.values()))}
    tit_rep, tit_area = capi_mansione.titolari_struttura(reparti, aree, in_forza=in_forza)
    abilitazioni = {
        (ab.competenza_id, ab.legacy_anagrafica_id): ab.pk
        for ab in AbilitazioneMacchina.objects.filter(
            competenza_id__in=list(mansioni), in_lista=True, stato=AbilitazioneMacchina.STATO_ATTIVA,
        )
    }

    # Persone per area / reparto (catena canonica) e chi resta senza capo.
    from .services.reparto_canonico import build_area_canonica_map

    area_di = {pid: a for pid, a in build_area_canonica_map(list(in_forza)).items()}
    per_area = Counter(a.pk for a in area_di.values())
    per_reparto = Counter(a.reparto_id for a in area_di.values() if a.reparto_id)
    senza_capo = Counter(
        (area_di[pid].reparto_id if pid in area_di else None) for pid, c in mappa.items() if not c.legacy_id
    )
    origini = Counter(c.origine or "" for c in mappa.values())

    def persone(mid, ids):
        return [{"id": i, "nome": nomi.get(i, f"#{i}"), "abilitazione": abilitazioni.get((mid, i))} for i in ids]

    def a_mano(legacy_id):
        return nomi.get(legacy_id, "") if legacy_id else ""

    schede = []
    aree_per_reparto: dict[int | None, list] = {}
    for a in aree:
        aree_per_reparto.setdefault(a.reparto_id, []).append(a)
    for r in reparti:
        mid = capi_mansione.mansione_reparto(r, responsabilita)
        capi = persone(mid, tit_rep.get(r.pk, [])) if mid else []
        avvisi = []
        if not mid:
            avvisi.append("Scegli il ruolo responsabile")
        elif not capi:
            avvisi.append("Nessuno ha la «Responsabilità del reparto»: vale l'organigramma dei ruoli")
        elif len(capi) > 1:
            avvisi.append(f"{len(capi)} persone con la mansione: approva {capi[0]['nome']}, le altre sono co-capo")
        righe_aree = []
        for a in aree_per_reparto.get(r.pk, []):
            amid = resp_aree.get(a.pk)
            resp = persone(amid, tit_area.get(a.pk, [])) if amid else []
            coincide = area_coincide_col_reparto(a)
            if coincide:
                avviso = ""
            elif not a.ruolo_responsabile_id:
                avviso = "Senza ruolo responsabile: segue il reparto"
            elif not resp:
                avviso = "Nessuno ha la «Responsabilità dell'area»: segue il reparto"
            else:
                avviso = ""
            righe_aree.append({
                "area": a,
                "coincide": coincide,
                "persone": per_area.get(a.pk, 0),
                "mansione": mansioni.get(amid) if amid else None,
                "responsabili": resp,
                "a_mano": a_mano(a.responsabile_legacy_id),
                "avviso": avviso,
            })
        schede.append({
            "reparto": r,
            "mansione": mansioni.get(mid) if mid else None,
            "capi": capi,
            "a_mano": a_mano(r.caporeparto_legacy_id),
            "persone": per_reparto.get(r.pk, 0),
            "senza_capo": senza_capo.get(r.pk, 0),
            "aree": righe_aree,
            "avvisi": avvisi,
        })
    attivi = [s for s in schede if s["reparto"].is_active]
    proposta = None if regola else capi_mansione.proposta()
    for a in proposta.assegnazioni if proposta else []:
        a["nome"] = nomi.get(a["legacy_id"], "")
    return {
        "regola_attiva": regola,
        "schede": schede,
        "aree_senza_reparto": aree_per_reparto.get(None, []),
        "kpi": {
            "reparti": len(attivi),
            "con_capo": sum(1 for s in attivi if s["capi"]),
            "da_sistemare": sum(1 for s in attivi if s["avvisi"]),
            "persone": len(mappa),
            "senza_capo": sum(1 for c in mappa.values() if not c.legacy_id),
            "eccezioni": origini.get(capo_team.ORIGINE_PERSONA, 0),
        },
        "proposta": proposta,
        "aree_senza_ruolo": capi_mansione.aree_senza_ruolo(),
        "ruoli_opts": _ruoli_opts(),
        "dipendenti_picker": picker,
        "reparti_opts": [r for r in reparti if r.is_active],
        "is_admin": _helpers._is_anagrafica_admin(request),
    }


@login_required
def reparti_capi(request):
    return render(request, "anagrafica/pages/aree_list.html", _contesto(request))


def _solo_admin(request):
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Reparti, aree e capi li cambia l'amministrazione dell'anagrafica.")
        return _torna()
    return None


@login_required
@require_POST
def capi_passaggio(request):
    """Una volta: assegna le «Responsabilità» a chi oggi è capo e accende la regola unica."""
    if (negato := _solo_admin(request)) is not None:
        return negato
    if capo_team.regola_unica_attiva():
        messages.info(request, "Il passaggio è già fatto: i capi vengono dalle mansioni.")
        return _torna()
    if request.POST.get("conferma") != "1":
        messages.error(request, "Per fare il passaggio spunta la conferma.")
        return _torna("passaggio")
    try:
        esito = capi_mansione.applica_passaggio(user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _torna("passaggio")
    log_action(request, "update", MODULE, {"oggetto": "capi_da_mansione", **esito})
    messages.success(request, f"Passaggio fatto: {esito['assegnazioni']} mansioni assegnate, "
                              f"{esito['schede']} schede e {esito['mapping']} righe di assenze/automazioni allineate.")
    return _torna()


@login_required
@require_POST
def capi_ruolo_aree(request):
    """Le aree senza ruolo responsabile prendono quello del reparto (come nel file della Qualità)."""
    if (negato := _solo_admin(request)) is not None:
        return negato
    ids = [int(v) for v in request.POST.getlist("area") if str(v).isdigit()]
    fatte = capi_mansione.ruolo_del_reparto_alle_aree(ids or None)
    log_action(request, "update", MODULE, {"oggetto": "capi_ruolo_aree", "aree": ids, "fatte": fatte})
    messages.success(request, f"Ruolo responsabile dato a {fatte} aree: ognuna ha ora la sua «Responsabilità dell'area».")
    return _torna("passaggio")


@login_required
@require_POST
def capo_assegna(request, mansione_id: int):
    """Mette una persona sulla «Responsabilità» di un reparto o di un'area."""
    if (negato := _solo_admin(request)) is not None:
        return negato
    mansione = get_object_or_404(CompetenzaSkm, pk=mansione_id)
    ancora = request.POST.get("ancora", "")
    if not capi_mansione.e_mansione_capo(mansione.pk):
        messages.error(request, "Questa mansione non decide il capo di nessun reparto o area.")
        return _torna(ancora)
    raw = (request.POST.get("legacy_id") or "").strip()
    if not raw.isdigit():
        messages.error(request, "Scegli la persona.")
        return _torna(ancora)
    ab = mansionario_struttura.assegna(mansione, legacy_anagrafica_id=int(raw),
                                       livello=capi_mansione.LIVELLO_PASSAGGIO, user=request.user)
    log_action(request, "update", MODULE, {"oggetto": "capo_mansione_assegna", "mansione": mansione.pk,
                                           "legacy_anagrafica_id": int(raw)}, oggetto=ab)
    messages.success(request, f"Assegnata «{mansione.nome}».")
    return _torna(ancora)


@login_required
@require_POST
def capo_togli(request, abilitazione_id: int):
    if (negato := _solo_admin(request)) is not None:
        return negato
    ab = get_object_or_404(AbilitazioneMacchina, pk=abilitazione_id)
    ancora = request.POST.get("ancora", "")
    if not capi_mansione.e_mansione_capo(ab.competenza_id):
        messages.error(request, "Questa mansione non decide il capo di nessun reparto o area.")
        return _torna(ancora)
    mansionario_struttura.togli(ab)
    log_action(request, "update", MODULE, {"oggetto": "capo_mansione_togli", "mansione": ab.competenza_id,
                                           "legacy_anagrafica_id": ab.legacy_anagrafica_id}, oggetto=ab)
    messages.success(request, "Tolta la «Responsabilità».")
    return _torna(ancora)
