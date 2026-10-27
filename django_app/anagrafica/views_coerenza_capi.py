"""«Capo di ogni persona» (ex «Coerenza capi»): il capo di ognuno e da dove viene.

Confronta il capo di reparto/area con quello della regola unica
(``services.capo_team``) e gestisce le eccezioni sulla persona. Il passaggio
alle mansioni del capo si fa dalla pagina «Reparti, aree e capi»
(``views_capi_reparti``): da qui la regola non si accende né si spegne più.
Riservata agli amministratori dell'anagrafica.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

FILTRI = [
    ("tutti", "Tutti"),
    ("cambia", "Il capo cambia"),
    ("senza", "Senza capo"),
    ("ambigui", "Più candidati"),
    ("eccezioni", "Eccezioni"),
]


def _nomi(righe) -> dict[int, str]:
    from core import naming

    return {
        int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome")) or str(r.get("aliasusername") or r["id"])
        for r in righe
        if r.get("id")
    }


def _righe(oggi=None) -> tuple[list[dict], dict[int, str]]:
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from .models import AreaAziendale, DipendenteAnagraficaAziendale, DipendenteRuoloOperativo, Reparto, RuoloOperativo
    from .services import capo_team
    from .services.reparto_canonico import (
        build_reparto_canonico_map,
        resolve_reparto_for_row,
        resolve_responsabile_effettivo,
    )

    mappa = capo_team.mappa_capi(oggi)
    righe_legacy = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo") and r.get("id")]
    nomi = _nomi(righe_legacy)
    ids = [int(r["id"]) for r in righe_legacy if int(r["id"]) in mappa]
    aree = {a.id: a for a in AreaAziendale.objects.select_related("reparto")}
    reparti = {r.id: r for r in Reparto.objects.all()}
    per_nome = {r.nome.strip().casefold(): r for r in reparti.values() if r.is_active}
    canonico = build_reparto_canonico_map(ids)
    schede = {az.legacy_anagrafica_id: az for az in DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=ids)}

    # Team dei permessi di oggi: chi ricopre un ruolo sopra quelli della persona,
    # a qualunque livello e in qualunque reparto (core.permessi.team).
    padri = capo_team._padri_ruoli()
    nomi_ruoli = dict(RuoloOperativo.objects.values_list("id", "nome"))
    ruoli_persona: dict[int, set[int]] = {}
    titolari: dict[int, set[int]] = {}
    for a in DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id__in=ids, ruolo__is_active=True):
        if a.is_conclusa:
            continue
        ruoli_persona.setdefault(a.legacy_anagrafica_id, set()).add(a.ruolo_id)
        titolari.setdefault(a.ruolo_id, set()).add(a.legacy_anagrafica_id)

    righe = []
    for riga in righe_legacy:
        legacy_id = int(riga["id"])
        if legacy_id not in mappa:
            continue
        az = schede.get(legacy_id)
        area = aree.get(az.area_aziendale_id) if az is not None and az.area_aziendale_id else None
        rep = area.reparto if area is not None and area.reparto_id else resolve_reparto_for_row(
            riga, canonico_map=canonico, reparto_by_name=per_nome
        )
        oggi_id = resolve_responsabile_effettivo(area=area, reparto=rep)
        nuovo = mappa[legacy_id]
        ruoli = ruoli_persona.get(legacy_id, set())
        sopra = set().union(*capo_team._livelli_sopra(ruoli, padri)) if ruoli else set()
        team_permessi = sorted(
            {p for r in sopra for p in titolari.get(r, set())} - {legacy_id}, key=lambda i: nomi.get(i, "")
        )
        catena, visti, corrente = [], {legacy_id}, nuovo.legacy_id
        while corrente and corrente not in visti and len(catena) < 8:
            catena.append(corrente)
            visti.add(corrente)
            corrente = mappa.get(corrente, capo_team.Capo(None)).legacy_id
        righe.append({
            "legacy_id": legacy_id,
            "nome": nomi.get(legacy_id, str(legacy_id)),
            "reparto": rep.nome if rep is not None else "",
            "area": area.nome if area is not None else "",
            "ruoli": sorted(nomi_ruoli.get(r, "") for r in ruoli),
            "capo_oggi": nomi.get(oggi_id or 0, "") if oggi_id else "",
            "capo_oggi_id": oggi_id,
            "capo_nuovo": nomi.get(nuovo.legacy_id or 0, "") if nuovo.legacy_id else "",
            "capo_nuovo_id": nuovo.legacy_id,
            "origine": nuovo.origine,
            "origine_label": nuovo.origine_label,
            "alternative": [nomi.get(i, str(i)) for i in nuovo.alternative],
            "catena": [nomi.get(i, str(i)) for i in catena],
            "team_permessi": [nomi.get(i, str(i)) for i in team_permessi],
            "cambia": (oggi_id or None) != (nuovo.legacy_id or None),
            "eccezione_id": getattr(az, "capo_eccezione_legacy_id", None) if az is not None else None,
            "eccezione_motivo": getattr(az, "capo_eccezione_motivo", "") if az is not None else "",
        })
    righe.sort(key=lambda r: r["nome"].casefold())
    return righe, nomi


@login_required
def coerenza_capi(request):
    from .views import _is_anagrafica_admin

    if not _is_anagrafica_admin(request):
        messages.error(request, "Accesso riservato agli amministratori dell'anagrafica.")
        return redirect("anagrafica:dipendenti_list")
    from .services import capo_team

    righe, nomi = _righe()
    filtro = request.GET.get("filtro") or "tutti"
    if filtro not in dict(FILTRI):
        filtro = "tutti"
    conteggi = {
        "tutti": len(righe),
        "cambia": sum(1 for r in righe if r["cambia"]),
        "senza": sum(1 for r in righe if not r["capo_nuovo_id"]),
        "ambigui": sum(1 for r in righe if r["alternative"]),
        "eccezioni": sum(1 for r in righe if r["eccezione_id"]),
    }
    visibili = {
        "tutti": righe,
        "cambia": [r for r in righe if r["cambia"]],
        "senza": [r for r in righe if not r["capo_nuovo_id"]],
        "ambigui": [r for r in righe if r["alternative"]],
        "eccezioni": [r for r in righe if r["eccezione_id"]],
    }[filtro]
    persone = sorted(nomi.items(), key=lambda kv: kv[1].casefold())
    return render(request, "anagrafica/pages/coerenza_capi.html", {
        "righe": visibili,
        "filtri": [(codice, etichetta, conteggi[codice]) for codice, etichetta in FILTRI],
        "filtro": filtro,
        "persone": persone,
        "conteggi": conteggi,
        "regola_attiva": capo_team.regola_unica_attiva(),
    })


@login_required
@require_POST
def coerenza_capi_eccezione(request, legacy_id: int):
    """Imposta o toglie l'eccezione sul capo di una persona (con audit)."""
    from core.audit import log_action

    from .models import DipendenteAnagraficaAziendale
    from .views import _is_anagrafica_admin

    if not _is_anagrafica_admin(request):
        messages.error(request, "Accesso riservato agli amministratori dell'anagrafica.")
        return redirect("anagrafica:dipendenti_list")
    filtro = request.POST.get("filtro") or "tutti"
    if filtro not in dict(FILTRI):
        filtro = "tutti"
    ritorno = redirect(f"{reverse('anagrafica:coerenza_capi')}?filtro={filtro}#p{int(legacy_id)}")
    capo_raw = (request.POST.get("capo") or "").strip()
    motivo = (request.POST.get("motivo") or "").strip()[:200]
    capo_id = int(capo_raw) if capo_raw.isdigit() else None
    if capo_id is not None and capo_id == int(legacy_id):
        messages.error(request, "Una persona non può essere capo di sé stessa.")
        return ritorno
    if capo_id is not None and not motivo:
        messages.error(request, "Per un'eccezione serve il motivo (es. distacco, interim).")
        return ritorno
    az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=int(legacy_id), defaults={"updated_by": request.user},
    )
    prima = az.capo_eccezione_legacy_id
    az.capo_eccezione_legacy_id = capo_id
    az.capo_eccezione_motivo = motivo if capo_id is not None else ""
    az.updated_by = request.user
    az.save(update_fields=["capo_eccezione_legacy_id", "capo_eccezione_motivo", "updated_by", "updated_at"])
    log_action(request, "update", "anagrafica", {
        "oggetto": "capo_eccezione", "legacy_anagrafica_id": int(legacy_id), "prima": prima, "dopo": capo_id,
    })
    messages.success(request, "Eccezione salvata." if capo_id is not None else "Eccezione tolta: vale la regola.")
    return ritorno
