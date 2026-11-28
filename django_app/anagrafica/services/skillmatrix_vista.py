"""Skill Matrix MOD.187: una sola costruzione della matrice per pagina, Excel e PDF (28/11/2026).

Colonne = mansioni attive della skill matrix (macchine con asset e processi con
almeno una persona in lista), raggruppate per reparto con il capo reparto (CAR)
sopra, come nel modulo MOD.187. Righe = persone in lista (non cessate),
raggruppate per il reparto dove hanno più mansioni; il CAR del reparto va per
primo. La stessa struttura alimenta la pagina, l'Excel, il «Report HUB» e il
PDF «MOD.187», così i numeri sono sempre gli stessi ovunque.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date

from django.db.models import Q
from django.utils import timezone

from ..models import (AbilitazioneMacchina, CompetenzaSkm, LivelloSkm, ProfiloMansioniPersona, Reparto,
                      SkillMatrixConfig)

logger = logging.getLogger(__name__)

LIVELLI = ("I", "L", "U", "O")
LEGENDA = {"I": "principiante", "L": "intermedio", "U": "autonomo", "O": "insegna / programma BM"}
SENZA_REPARTO = "Senza reparto"


def _naturale(testo: str) -> list:
    """DM3 prima di DM10: i numeri si confrontano come numeri."""
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", (testo or "").casefold())]


def _persone(ids) -> dict[int, dict]:
    from core.legacy_models import AnagraficaDipendente
    esito = {}
    for r in AnagraficaDipendente.objects.filter(id__in=list(ids)).values("id", "nome", "cognome"):
        cognome = (r["cognome"] or "").strip()
        nome = (r["nome"] or "").strip()
        esito[r["id"]] = {"cognome": cognome, "nome": nome,
                          "mod": f"{cognome} {nome}".strip().upper() or f"ID {r['id']}",
                          "vista": f"{cognome.title()} {nome.title()}".strip() or f"ID {r['id']}"}
    return esito


def _cessati() -> set[int]:
    try:
        from core.persone_tendine import cessati_anagrafica_ids
        return cessati_anagrafica_ids()
    except Exception:  # noqa: BLE001
        logger.warning("Skill Matrix: elenco cessati non letto", exc_info=True)
        return set()


def costruisci(*, reparto: str = "", solo: str = "", solo_macchine: bool = False, persone=None,
               macchine_ids=None, oggi: date | None = None) -> dict:
    """La matrice filtrata.

    - ``reparto``: solo le colonne di quel reparto (e chi vi è in lista);
    - ``solo``: ``rivalutare`` (revisione passata), ``sospese`` o ``sospendere`` (requisito
      formale scaduto o mancante su un'abilitazione attiva): solo le righe che ne hanno;
    - ``solo_macchine``: niente colonne dei processi;
    - ``persone``: solo questi ``legacy_anagrafica_id`` (selezione multipla);
    - ``macchine_ids``: solo queste macchine (filtri «scoperte» / «uomo solo»).
    """
    oggi = oggi or timezone.localdate()
    config = SkillMatrixConfig.get_instance()
    soglia = config.soglia_operativa_ordinale

    comp_qs = (CompetenzaSkm.objects.filter(attiva=True, responsabilita_reparto__isnull=True,
                                            responsabilita_area__isnull=True)
               .filter(Q(tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False) | Q(tipo=CompetenzaSkm.TIPO_PROCESSO))
               .select_related("asset", "reparto"))
    if solo_macchine:
        comp_qs = comp_qs.filter(tipo=CompetenzaSkm.TIPO_MACCHINA)
    competenze = list(comp_qs)
    if macchine_ids is not None:
        competenze = [c for c in competenze if c.asset_id in set(macchine_ids)]
    per_asset = {c.asset_id: c for c in competenze if c.asset_id}
    per_id = {c.pk: c for c in competenze}

    abil = (AbilitazioneMacchina.objects.filter(in_lista=True)
            .filter(Q(competenza_id__in=list(per_id)) | Q(asset_id__in=list(per_asset))))
    cessati = _cessati()
    celle: dict[tuple[int, int], AbilitazioneMacchina] = {}
    for ab in abil:
        if ab.legacy_anagrafica_id in cessati:
            continue
        comp = per_id.get(ab.competenza_id) or per_asset.get(ab.asset_id)
        if comp is not None:
            celle[(ab.legacy_anagrafica_id, comp.pk)] = ab

    # Processi senza nessuno in lista: fuori (rumore). Le macchine restano sempre (scoperte).
    usate = {cid for (_, cid) in celle}
    competenze = [c for c in competenze if c.tipo == CompetenzaSkm.TIPO_MACCHINA or c.pk in usate]
    for c in competenze:
        c.rep = c.reparto_effettivo or SENZA_REPARTO
    if reparto:
        competenze = [c for c in competenze if c.rep.casefold() == reparto.casefold()]
    competenze.sort(key=lambda c: (c.rep == SENZA_REPARTO, c.rep.casefold(), not c.asset_id, _naturale(c.nome)))
    ids_colonne = {c.pk for c in competenze}

    car_per_reparto = {r["nome"]: r["caporeparto_legacy_id"]
                       for r in Reparto.objects.values("nome", "caporeparto_legacy_id")}

    # Persone e loro reparto (dove hanno più mansioni fra quelle a schermo).
    per_persona: dict[int, list[CompetenzaSkm]] = defaultdict(list)
    for (lid, cid), ab in celle.items():
        if cid in ids_colonne:
            per_persona[lid].append(per_id[cid])
    if persone is not None:
        voluti = {int(x) for x in persone}
        per_persona = {lid: v for lid, v in per_persona.items() if lid in voluti}
    car_ids = {v for v in car_per_reparto.values() if v}
    anag = _persone(set(per_persona) | car_ids)
    from . import skillmatrix_requisiti as req
    req_colonne = req.requisiti_colonne(ids_colonne)
    req_stati = req.stati(set(per_persona), req_colonne, oggi=oggi)
    orari = dict(ProfiloMansioniPersona.objects.filter(legacy_anagrafica_id__in=list(per_persona))
                 .values_list("legacy_anagrafica_id", "orario"))

    righe = []
    for lid, comps in per_persona.items():
        rep = Counter(c.rep for c in comps).most_common(1)[0][0]
        car = car_per_reparto.get(rep) == lid
        celle_riga = []
        flag = {"rivalutare": False, "sospese": False, "sospendere": False}
        for c in competenze:
            ab = celle.get((lid, c.pk))
            if ab is None:
                celle_riga.append(None)
                continue
            arretrata = bool(ab.prossima_revisione and ab.prossima_revisione < oggi)
            sospesa = ab.stato == AbilitazioneMacchina.STATO_SOSPESA
            flag["rivalutare"] |= arretrata
            flag["sospese"] |= sospesa
            esito = req.esito_cella(lid, ab.livello or "", not sospesa, req_colonne.get(c.pk, []), req_stati)
            flag["sospendere"] |= esito["da_sospendere"]
            celle_riga.append({
                "id": ab.pk, "comp": c.pk, "livello": ab.livello or "", "richiesto": ab.livello_richiesto or "",
                "operativa": ab.is_operativa(soglia) and not sospesa, "sotto": ab.sotto_livello_richiesto,
                "arretrata": arretrata, "sospesa": sospesa,
                "revisione": ab.prossima_revisione,
                "da_sospendere": esito["da_sospendere"], "req_in_scadenza": esito["req_in_scadenza"],
                "req_ko": [r["nome"] for r in esito["req_ko"]], "scadenza_ko": esito["scadenza_ko"],
            })
        if solo in flag and not flag[solo]:
            continue
        p = anag.get(lid, {"mod": f"ID {lid}", "vista": f"ID {lid}", "cognome": "", "nome": ""})
        righe.append({
            "lid": lid, "nome": p["vista"], "nome_mod": p["mod"], "reparto": rep, "car": car,
            "ruolo": f"CAR {rep}" if car else rep, "orario": orari.get(lid, "") or "",
            "celle": celle_riga, "n_operative": sum(1 for x in celle_riga if x and x["operativa"]),
        })
    righe.sort(key=lambda r: (r["reparto"] == SENZA_REPARTO, r["reparto"].casefold(), not r["car"], r["nome"].casefold()))

    gruppi_righe = []
    for r in righe:
        if not gruppi_righe or gruppi_righe[-1]["reparto"] != r["reparto"]:
            gruppi_righe.append({"reparto": r["reparto"], "righe": []})
        gruppi_righe[-1]["righe"].append(r)

    colonne = []
    for i, c in enumerate(competenze):
        conta = Counter(r["celle"][i]["livello"] for r in righe if r["celle"][i])
        colonne.append({
            "comp": c, "id": c.pk, "nome": c.nome, "reparto": c.rep, "asset_id": c.asset_id,
            "macchina": c.tipo == CompetenzaSkm.TIPO_MACCHINA,
            "conta": {k: conta.get(k, 0) for k in LIVELLI}, "totale": sum(conta.get(k, 0) for k in LIVELLI),
            "operativi": sum(1 for r in righe if r["celle"][i] and r["celle"][i]["operativa"]),
        })
    gruppi_colonne = []
    for col in colonne:
        if not gruppi_colonne or gruppi_colonne[-1]["reparto"] != col["reparto"]:
            car_id = car_per_reparto.get(col["reparto"])
            car = anag.get(car_id, {}) if car_id else {}
            gruppi_colonne.append({"reparto": col["reparto"], "car": car.get("vista", ""), "colonne": []})
        gruppi_colonne[-1]["colonne"].append(col)

    return {
        "colonne": colonne, "gruppi_colonne": gruppi_colonne, "righe": righe, "gruppi_righe": gruppi_righe,
        "reparti": sorted({c.rep for c in comp_qs_reparti()}, key=str.casefold),
        "n_rivalutare": sum(1 for r in righe for x in r["celle"] if x and x["arretrata"]),
        "n_sospese": sum(1 for r in righe for x in r["celle"] if x and x["sospesa"]),
        "n_sospendere": sum(1 for r in righe for x in r["celle"] if x and x["da_sospendere"]),
        "oggi": oggi, "config": config,
    }


def comp_qs_reparti():
    """Reparti che hanno colonne in skill matrix (per i pulsanti dei filtri)."""
    qs = (CompetenzaSkm.objects.filter(attiva=True, responsabilita_reparto__isnull=True,
                                       responsabilita_area__isnull=True)
          .filter(Q(tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False) | Q(tipo=CompetenzaSkm.TIPO_PROCESSO))
          .select_related("asset", "reparto"))
    for c in qs:
        c.rep = c.reparto_effettivo or SENZA_REPARTO
        yield c


def livello_valido(livello: str) -> bool:
    return livello in dict(LivelloSkm.choices)
