"""Requisiti formali delle celle della Skill Matrix (28/11/2026).

Una mansione (colonna) può chiedere requisiti formali: il corso qualificante
(``CompetenzaSkm.corso_qualificante``, serve da L in su) e, per le sue competenze,
corso, qualifica o patentino, qualifica MOD.128 (``VoceMacchinaCatalogo``: senza,
la persona non supera «I – in formazione»). Le regole di validità sono quelle già
in uso nel Mansionario (``mansionario_competenze.Requisiti``): completamento valido
per i corsi, qualifica non scaduta, persona operativa sul processo MOD.128.

Qui in più c'è la **data di scadenza** di ogni requisito e il segno «da
sospendere»: abilitazione attiva da L in su con un requisito scaduto o mancante.
MT CN 06 §10.2-10.3: si opera e si firma solo con l'autorizzazione vigente;
MT CN 65 §3.7: approvazione CND scaduta, visita visiva o verifica annuale scadute
= sospensione. Il portale segnala, la sospensione la fa la Qualità dalla scheda.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.urls import reverse

from ..models import CompetenzaSkm, LivelloSkm, VoceMacchinaCatalogo
from ..models_skillmatrix import ordinale_livello
from ..scadenze_soglie import GIORNI_PREAVVISO

VALIDO, IN_SCADENZA, SCADUTO, MANCANTE = "valido", "in_scadenza", "scaduto", "mancante"
ETICHETTE = {VALIDO: "valido", IN_SCADENZA: "in scadenza", SCADUTO: "scaduto", MANCANTE: "mancante"}
_ORD_L = ordinale_livello(LivelloSkm.INTERMEDIO)


def requisiti_colonne(comp_ids) -> dict[int, list[dict]]:
    """{comp_id: [requisito]}; requisito = {tipo, id, nome, voce, oggetto}."""
    ids = [int(i) for i in comp_ids if i]
    out: dict[int, list[dict]] = defaultdict(list)
    if not ids:
        return out
    visti: set[tuple] = set()
    for c in CompetenzaSkm.objects.filter(pk__in=ids, corso_qualificante__isnull=False).select_related("corso_qualificante"):
        out[c.pk].append({"tipo": "corso", "id": c.corso_qualificante_id, "nome": c.corso_qualificante.titolo,
                          "voce": "", "qualificante": True})
        visti.add((c.pk, "corso", c.corso_qualificante_id))
    for v in (VoceMacchinaCatalogo.objects.filter(mansione_id__in=ids, attiva=True)
              .select_related("corso", "qualifica", "processo_mpq")):
        for tipo, oid, nome in (("corso", v.corso_id, v.corso.titolo if v.corso_id else ""),
                                ("qualifica", v.qualifica_id, v.qualifica.nome if v.qualifica_id else ""),
                                ("mpq", v.processo_mpq_id, v.processo_mpq.nome if v.processo_mpq_id else "")):
            if not oid or (v.mansione_id, tipo, oid) in visti:
                continue
            visti.add((v.mansione_id, tipo, oid))
            out[v.mansione_id].append({"tipo": tipo, "id": oid, "nome": nome, "voce": v.nome, "qualificante": False})
    return out


def _stato(valido: bool, scadenza: date | None, oggi: date) -> str:
    if not valido:
        return SCADUTO if scadenza and scadenza < oggi else MANCANTE
    if scadenza and scadenza <= oggi + timedelta(days=GIORNI_PREAVVISO):
        return IN_SCADENZA
    return VALIDO


def stati(legacy_ids, per_colonna: dict[int, list[dict]], *, oggi: date) -> dict[tuple, dict]:
    """{(legacy_id, tipo, id): {stato, scadenza}} per tutti i requisiti delle colonne."""
    ids = {int(i) for i in legacy_ids if i}
    reqs = [r for lista in per_colonna.values() for r in lista]
    corsi = {r["id"] for r in reqs if r["tipo"] == "corso"}
    qualifiche = {r["id"] for r in reqs if r["tipo"] == "qualifica"}
    processi = {r["id"] for r in reqs if r["tipo"] == "mpq"}
    out: dict[tuple, dict] = {}
    if not ids or not reqs:
        return out
    if corsi:
        from ..models_formazione import TrainingDeadline
        from .formazione_completamento import ids_con_completamento_valido_multi
        validi = ids_con_completamento_valido_multi(corsi, ids, oggi=oggi)
        scad: dict[tuple, date | None] = {}
        for lid, cid, ds in (TrainingDeadline.objects.filter(legacy_anagrafica_id__in=ids, corso_id__in=corsi)
                             .values_list("legacy_anagrafica_id", "corso_id", "data_scadenza")):
            k = (lid, cid)
            if ds and (scad.get(k) is None or ds > scad[k]):
                scad[k] = ds
        for lid in ids:
            for cid in corsi:
                s = scad.get((lid, cid))
                out[(lid, "corso", cid)] = {"stato": _stato((lid, cid) in validi, s, oggi), "scadenza": s}
    if qualifiche:
        from ..models import DipendenteQualifica
        migliore: dict[tuple, tuple] = {}
        for lid, tid, ds in (DipendenteQualifica.objects.filter(legacy_anagrafica_id__in=ids, tipo_id__in=qualifiche)
                             .values_list("legacy_anagrafica_id", "tipo_id", "data_scadenza")):
            k = (lid, tid)
            # Senza scadenza vince; altrimenti la scadenza più lontana.
            attuale = migliore.get(k)
            if attuale is None or (attuale[0] is not None and (ds is None or ds > attuale[0])):
                migliore[k] = (ds,)
        for lid in ids:
            for tid in qualifiche:
                m = migliore.get((lid, tid))
                ds = m[0] if m else None
                valido = m is not None and (ds is None or ds >= oggi)
                out[(lid, "qualifica", tid)] = {"stato": _stato(valido, ds, oggi), "scadenza": ds}
    if processi:
        from ..models_mpq import AbilitazioneProcesso, ProcessoQualificato
        from .mpq_persone import contesto_processo, stato_persona
        for p in ProcessoQualificato.objects.filter(pk__in=list(processi)):
            attivo = p.stato == ProcessoQualificato.STATO_ATTIVO
            scad_p = p.scadenza_effettiva
            abil = list(p.abilitazioni.filter(legacy_anagrafica_id__in=ids, nominativo_esterno="")
                        .prefetch_related("ruoli_processo", "certificazioni"))
            ctx = contesto_processo(p, abil) if abil else None
            per_lid = {}
            for ab in abil:
                st = stato_persona(ab, oggi=oggi, contesto=ctx)
                ok = (attivo and ab.stato == AbilitazioneProcesso.STATO_ATTIVA and st["operativa"]
                      and not (scad_p and scad_p < oggi))
                s = min([d for d in (st["scadenza"], scad_p) if d], default=None)
                motivo = ", ".join(v["nome"] for v in st["voci"]
                                   if v.get("bloccante", True) and v.get("stato") in ("scaduto", "mancante"))
                if not ok or ab.legacy_anagrafica_id not in per_lid:
                    per_lid[ab.legacy_anagrafica_id] = {"stato": _stato(ok, s, oggi), "scadenza": s, "motivo": motivo}
            for lid in ids:
                out[(lid, "mpq", p.pk)] = per_lid.get(lid, {"stato": MANCANTE, "scadenza": None, "motivo": ""})
    return out


def url_requisito(req: dict, legacy_id: int) -> str:
    if req["tipo"] == "corso":
        return reverse("anagrafica:formazione_corso_detail", args=[req["id"]])
    if req["tipo"] == "mpq":
        return reverse("anagrafica:mpq_processo_detail", args=[req["id"]]) + "#persone"
    return reverse("anagrafica:dipendente_detail", args=[legacy_id]) + "#qualifiche"


def esito_cella(legacy_id: int, livello: str, attiva: bool, reqs: list[dict], st: dict[tuple, dict]) -> dict:
    """Requisiti di una cella con stato e scadenza, più i segni per la matrice.

    ``da_sospendere``: attiva da L in su con un requisito scaduto o mancante;
    ``in_scadenza``: un requisito scade entro la soglia di preavviso.
    """
    righe = []
    for r in reqs:
        s = st.get((legacy_id, r["tipo"], r["id"]), {"stato": MANCANTE, "scadenza": None})
        righe.append({**r, **s, "etichetta": ETICHETTE[s["stato"]]})
    ko = [r for r in righe if r["stato"] in (SCADUTO, MANCANTE)]
    da_sospendere = bool(ko) and attiva and ordinale_livello(livello) >= _ORD_L
    return {
        "requisiti": righe,
        "req_ko": ko,
        "da_sospendere": da_sospendere,
        "req_in_scadenza": any(r["stato"] == IN_SCADENZA for r in righe),
        "scadenza_ko": min([r["scadenza"] for r in ko if r["scadenza"]], default=None),
    }


def link_skill_matrix(coppie) -> dict[tuple[int, int], str]:
    """{(legacy_id, corso_id): link alla Skill Matrix} per la valutazione d'efficacia (MT CN 06 §9.5).

    L'esito conferma o aggiorna il livello nel MOD.187: se il corso è il corso
    qualificante o un requisito di una mansione dove la persona è in lista, il
    link apre quella cella; altrimenti la riga della persona, se è in lista.
    """
    from django.db.models import Q

    from ..models import AbilitazioneMacchina

    coppie = {(int(a), int(b)) for a, b in coppie if a and b}
    if not coppie:
        return {}
    lids = {a for a, _ in coppie}
    corsi = {b for _, b in coppie}
    per_corso: dict[int, set[int]] = defaultdict(set)
    for cid, corso in CompetenzaSkm.objects.filter(corso_qualificante_id__in=corsi).values_list("pk", "corso_qualificante_id"):
        per_corso[corso].add(cid)
    for mid, corso in (VoceMacchinaCatalogo.objects.filter(corso_id__in=corsi, attiva=True, mansione__isnull=False)
                       .values_list("mansione_id", "corso_id")):
        per_corso[corso].add(mid)
    asset_comp = dict(CompetenzaSkm.objects.filter(asset__isnull=False).values_list("asset_id", "pk"))
    celle: dict[int, set[int]] = defaultdict(set)
    for lid, comp_id, asset_id in (AbilitazioneMacchina.objects.filter(legacy_anagrafica_id__in=lids, in_lista=True)
                                   .filter(Q(competenza__isnull=False) | Q(asset__isnull=False))
                                   .values_list("legacy_anagrafica_id", "competenza_id", "asset_id")):
        cid = comp_id or asset_comp.get(asset_id)
        if cid:
            celle[lid].add(cid)
    base = reverse("anagrafica:skill_matrix_macchina")
    out = {}
    for lid, corso in coppie:
        if lid not in celle:
            continue
        comuni = sorted(celle[lid] & per_corso.get(corso, set()))
        out[(lid, corso)] = (f"{base}?persone={lid}&apri={lid}-{comuni[0]}#sm-matrice" if comuni
                             else f"{base}?persone={lid}#sm-matrice")
    return out
