"""Sezioni di report sulla struttura: ruoli, mansioni, capi (27/10/2026).

Quattro viste dello stesso dato, nel perimetro di persone del modello:

- **Ruoli e mansioni per persona**: chi fa cosa, con livello, capo e disallineamenti;
- **Chi ricopre ogni ruolo**: per ruolo le persone, anche quelle senza nessuna sua mansione;
- **Capi e responsabilità**: per reparto e area il ruolo responsabile, chi ha la
  «Responsabilità» e quante persone restano senza capo;
- **Copertura delle mansioni**: per mansione persone in lista, operativi, livelli,
  «uomo solo» e titolari.

Stessa regola del Mansionario e di «Reparti, aree e capi» (``capi_mansione``,
``capo_team``): i numeri del report e delle pagine coincidono.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.db.models import Q

from report_conformita.registry import TONE_DANGER, TONE_OK, TONE_WARN, Kpi

from .dati import Contesto
from .sezioni import (
    EN_9100,
    GRUPPO_ORGANICO,
    GRUPPO_PERSONE,
    ISO_9001,
    ISO_45001,
    MULTI,
    SCELTA,
    SI_NO,
    Opzione,
    Risultato,
    Sezione,
    _registra,
)

LIVELLI = {"I": "in formazione", "L": "intermedio", "U": "autonomo", "O": "esperto"}


def _scelte_ruoli():
    from anagrafica.models import RuoloOperativo

    return [(str(r.pk), r.nome) for r in RuoloOperativo.objects.filter(is_active=True).order_by("nome")]


def _scelte_tipi():
    return (("", "Tutte"), ("macchina", "Macchine"), ("processo", "Processi"), ("responsabilita", "Solo responsabilità"))


def _per_persona(ctx: Contesto) -> tuple[dict[int, object], dict[int, int]]:
    """(id canonico → Dipendente, qualsiasi id legacy → id canonico) per il perimetro."""
    persone = {p.id: p for p in ctx.dipendenti()}
    alias = {i: p.id for p in persone.values() for i in p.tutti_gli_id}
    return persone, alias


def _ruoli_di(alias: dict[int, int]) -> dict[int, list]:
    from django.utils import timezone

    from anagrafica.models import DipendenteRuoloOperativo

    oggi = timezone.localdate()
    out: dict[int, list] = defaultdict(list)
    for a in (DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
                                                      legacy_anagrafica_id__in=list(alias))
              .select_related("ruolo").order_by("ruolo__nome")):
        pid = alias[a.legacy_anagrafica_id]
        if all(x.ruolo_id != a.ruolo_id for x in out[pid]):
            out[pid].append(a)
    return out


def _mansioni_di(alias: dict[int, int]) -> dict[int, list]:
    from anagrafica.models import AbilitazioneMacchina

    out: dict[int, list] = defaultdict(list)
    for ab in (AbilitazioneMacchina.objects.filter(legacy_anagrafica_id__in=list(alias), in_lista=True,
                                                   competenza__isnull=False)
               .select_related("competenza").prefetch_related("competenza__ruoli").order_by("competenza__display")):
        out[alias[ab.legacy_anagrafica_id]].append(ab)
    return out


def _perimetro_ristretto(ctx: Contesto) -> bool:
    per = ctx.perimetro
    return bool(per.reparti or per.aree or per.mansioni or per.contratti or per.livelli or per.persone
                or per.qualifiche or per.assunti_dal or per.assunti_al)


def _nomi_capi(ctx: Contesto) -> dict[int, str]:
    return {p.id: p.nominativo for p in ctx._tutti()}


# ═══════════════════════════════════════════════════════════════════════════
# Ruoli e mansioni per persona
# ═══════════════════════════════════════════════════════════════════════════

def _ruoli_mansioni_persona(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import SkillMatrixConfig
    from anagrafica.services import capo_team

    res = Risultato()
    persone, alias = _per_persona(ctx)
    ruoli = _ruoli_di(alias)
    mansioni = _mansioni_di(alias)
    soglia = SkillMatrixConfig.get_instance().soglia_operativa_ordinale
    mappa = capo_team.mappa_capi()
    nomi = _nomi_capi(ctx)
    filtro_ruoli = {int(r) for r in o["ruoli"]}
    n_senza_ruolo = n_senza_mansioni = n_fuori_ruolo = 0
    for pid, p in sorted(persone.items(), key=lambda kv: kv[1].nominativo.casefold()):
        suoi_ruoli = ruoli.get(pid, [])
        if filtro_ruoli and not any(a.ruolo_id in filtro_ruoli for a in suoi_ruoli):
            continue
        sue = mansioni.get(pid, [])
        ids_ruoli = {a.ruolo_id for a in suoi_ruoli}
        # Mansioni che nessun ruolo della persona prevede (la mansione ha ruoli e nessuno è suo).
        fuori = [ab for ab in sue if (rr := {r.pk for r in ab.competenza.ruoli.all()}) and not rr & ids_ruoli]
        avvisi = []
        if not suoi_ruoli:
            avvisi.append("senza ruolo")
            n_senza_ruolo += 1
        if not sue:
            avvisi.append("nessuna mansione")
            n_senza_mansioni += 1
        if fuori:
            avvisi.append(f"{len(fuori)} mansioni non previste dai suoi ruoli")
            n_fuori_ruolo += 1
        if o["solo_disallineati"] and not avvisi:
            continue
        capo = next((mappa[i] for i in p.tutti_gli_id if i in mappa), None)
        capo_nome = nomi.get(ctx.canonico(capo.legacy_id), "") if capo and capo.legacy_id else ""
        operative = sum(1 for ab in sue if ab.is_operativa(soglia))
        tono = TONE_DANGER if not suoi_ruoli or not sue else (TONE_WARN if fuori else "")
        if o["una_riga_per"] == "mansione" and sue:
            for ab in sue:
                res.riga({
                    "nominativo": p.nominativo, "reparto": p.reparto, "area": p.area,
                    "ruoli": ", ".join(a.ruolo.nome for a in suoi_ruoli), "mansione": ab.competenza.nome,
                    "livello": f"{ab.livello} · {LIVELLI.get(ab.livello, '')}" if ab.livello else "",
                    "operativa": "Sì" if ab.is_operativa(soglia) else "No",
                    "n_mansioni": len(sue), "operative": operative, "capo": capo_nome,
                    "avvisi": "non prevista dai suoi ruoli" if ab in fuori else "",
                }, TONE_WARN if ab in fuori else "")
            continue
        res.riga({
            "nominativo": p.nominativo, "reparto": p.reparto, "area": p.area,
            "ruoli": ", ".join(a.ruolo.nome for a in suoi_ruoli),
            "mansione": "; ".join(f"{ab.competenza.nome} ({ab.livello or '—'})" for ab in sue),
            "livello": "", "operativa": "", "n_mansioni": len(sue), "operative": operative, "capo": capo_nome,
            "avvisi": ", ".join(avvisi),
        }, tono)
    res.kpis = [
        Kpi("Persone", len(persone)),
        Kpi("Senza ruolo", n_senza_ruolo, TONE_DANGER if n_senza_ruolo else TONE_OK),
        Kpi("Senza mansioni", n_senza_mansioni, TONE_DANGER if n_senza_mansioni else TONE_OK),
        Kpi("Con mansioni fuori ruolo", n_fuori_ruolo, TONE_WARN if n_fuori_ruolo else TONE_OK),
    ]
    res.note = [f"Situazione al {ctx.today:%d/%m/%Y}: ruoli in essere e mansioni in lista nel Mansionario.",
                "Livelli: I in formazione · L intermedio · U autonomo · O esperto. Capo secondo la regola unica "
                "(Reparti, aree e capi)."]
    return res


_registra(Sezione(
    key="ruoli_mansioni_persona",
    titolo="Ruoli e mansioni per persona",
    gruppo=GRUPPO_PERSONE,
    descrizione="Per ogni persona i ruoli, le mansioni con il livello, il capo e cosa non torna.",
    builder=_ruoli_mansioni_persona,
    riferimenti=(f"{ISO_9001} §5.3", f"{ISO_9001} §7.2", f"{EN_9100} §7.2"),
    colonne=(("nominativo", "Nominativo"), ("reparto", "Reparto"), ("area", "Area aziendale"), ("ruoli", "Ruoli"),
             ("mansione", "Mansioni"), ("livello", "Livello"), ("operativa", "Operativa"),
             ("n_mansioni", "N. mansioni"), ("operative", "Operative"), ("capo", "Capo"), ("avvisi", "Da sistemare")),
    predefinite=("nominativo", "reparto", "ruoli", "mansione", "capo", "avvisi"),
    opzioni=(
        Opzione("una_riga_per", "Una riga per", SCELTA, (("persona", "Persona"), ("mansione", "Persona e mansione")),
                "persona", aiuto="«Persona e mansione» riempie anche le colonne Livello e Operativa."),
        Opzione("ruoli", "Solo chi ha questi ruoli", MULTI, _scelte_ruoli, aiuto="Nessuno = tutti."),
        Opzione("solo_disallineati", "Solo chi ha qualcosa da sistemare", SI_NO, predefinito=False,
                aiuto="Senza ruolo, senza mansioni o con mansioni non previste dai suoi ruoli."),
    ),
))


# ═══════════════════════════════════════════════════════════════════════════
# Chi ricopre ogni ruolo
# ═══════════════════════════════════════════════════════════════════════════

def _ruoli_persone(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import RuoloOperativo

    res = Risultato()
    persone, alias = _per_persona(ctx)
    ruoli = _ruoli_di(alias)
    mansioni = _mansioni_di(alias)
    filtro = {int(r) for r in o["ruoli"]}
    per_ruolo: dict[int, list] = defaultdict(list)
    for pid, assegnati in ruoli.items():
        for a in assegnati:
            per_ruolo[a.ruolo_id].append((pid, a))
    catalogo = {r.pk: r for r in RuoloOperativo.objects.filter(is_active=True)}
    senza_mansione = vuoti = 0
    for rid, r in sorted(catalogo.items(), key=lambda kv: kv[1].nome.casefold()):
        if filtro and rid not in filtro:
            continue
        righe = per_ruolo.get(rid, [])
        if not righe:
            if o["mostra_vuoti"]:
                vuoti += 1
                res.riga({"ruolo": r.nome, "sigla": r.sigla or "", "nominativo": "— nessuno —", "reparto": "",
                          "area": "", "dal": None, "mansioni_ruolo": "", "avviso": "ruolo senza persone"},
                         TONE_WARN)
            continue
        for pid, a in sorted(righe, key=lambda x: persone[x[0]].nominativo.casefold()):
            p = persone[pid]
            sue = [ab for ab in mansioni.get(pid, []) if rid in {x.pk for x in ab.competenza.ruoli.all()}]
            if not sue:
                senza_mansione += 1
            elif o["solo_senza_mansione"]:
                continue
            res.riga({
                "ruolo": r.nome, "sigla": r.sigla or "", "nominativo": p.nominativo, "reparto": p.reparto,
                "area": p.area, "dal": a.data_inizio,
                "mansioni_ruolo": "; ".join(f"{ab.competenza.nome} ({ab.livello or '—'})" for ab in sue),
                "avviso": "" if sue else "nessuna mansione del ruolo",
            }, "" if sue else TONE_DANGER)
    res.kpis = [
        Kpi("Ruoli con persone", len([k for k in per_ruolo if not filtro or k in filtro])),
        Kpi("Assegnazioni", sum(len(v) for k, v in per_ruolo.items() if not filtro or k in filtro)),
        Kpi("Senza mansioni del ruolo", senza_mansione, TONE_DANGER if senza_mansione else TONE_OK),
    ]
    if o["mostra_vuoti"]:
        res.kpis.append(Kpi("Ruoli senza persone", vuoti, TONE_WARN if vuoti else TONE_OK))
    res.note = ["Chi ricopre il ruolo oggi, indipendentemente dalle mansioni; accanto le mansioni del ruolo che ha in "
                "lista. «Nessuna mansione del ruolo»: il ruolo c'è ma nel Mansionario non svolge niente di suo."]
    return res


_registra(Sezione(
    key="ruoli_persone",
    titolo="Chi ricopre ogni ruolo",
    gruppo=GRUPPO_PERSONE,
    descrizione="Per ruolo le persone che lo ricoprono, con le mansioni del ruolo che hanno in lista.",
    builder=_ruoli_persone,
    riferimenti=(f"{ISO_9001} §5.3", f"{ISO_45001} §5.3"),
    colonne=(("ruolo", "Ruolo"), ("sigla", "Sigla"), ("nominativo", "Nominativo"), ("reparto", "Reparto"),
             ("area", "Area aziendale"), ("dal", "Dal"), ("mansioni_ruolo", "Mansioni del ruolo in lista"),
             ("avviso", "Da sistemare")),
    predefinite=("ruolo", "nominativo", "reparto", "mansioni_ruolo", "avviso"),
    opzioni=(
        Opzione("ruoli", "Solo questi ruoli", MULTI, _scelte_ruoli, aiuto="Nessuno = tutti."),
        Opzione("solo_senza_mansione", "Solo chi non ha nessuna mansione del ruolo", SI_NO, predefinito=False),
        Opzione("mostra_vuoti", "Mostra anche i ruoli senza persone", SI_NO, predefinito=False),
    ),
))


# ═══════════════════════════════════════════════════════════════════════════
# Capi e responsabilità
# ═══════════════════════════════════════════════════════════════════════════

def _capi_responsabilita(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import AreaAziendale, Reparto
    from anagrafica.services import capi_mansione, capo_team
    from anagrafica.services.struttura_v8 import area_coincide_col_reparto

    res = Risultato()
    persone, alias = _per_persona(ctx)
    nomi = _nomi_capi(ctx)
    mappa = capo_team.mappa_capi()
    reparti = list(Reparto.objects.filter(is_active=True).select_related("ruolo_responsabile").order_by("nome"))
    aree = list(AreaAziendale.objects.filter(is_active=True).select_related("ruolo_responsabile", "reparto")
                .order_by("nome"))
    tit_rep, tit_area = capi_mansione.titolari_struttura(reparti, aree, in_forza=set(mappa))
    resp_rep = capi_mansione.mansioni_responsabilita()
    resp_aree = capi_mansione.mansioni_responsabilita_aree()
    per_area = Counter(p.area.casefold() for p in persone.values() if p.area)
    per_rep = Counter(p.reparto.casefold() for p in persone.values() if p.reparto)
    senza_capo = Counter()
    for pid, p in persone.items():
        c = next((mappa[i] for i in p.tutti_gli_id if i in mappa), None)
        if c is None or not c.legacy_id:
            senza_capo[(p.reparto or "").casefold()] += 1

    def _nomi(ids):
        return ", ".join(nomi.get(ctx.canonico(i), f"#{i}") for i in ids)

    scoperte = 0
    for r in reparti:
        tit = tit_rep.get(r.pk, [])
        if not resp_rep.get(r.pk):
            stato, tono = "manca il ruolo responsabile", TONE_DANGER
        elif not tit:
            stato, tono = "nessuno ha la «Responsabilità»: vale l'organigramma", TONE_DANGER
        elif len(tit) > 1:
            stato, tono = f"{len(tit)} co-capi", TONE_WARN
        else:
            stato, tono = "ok", ""
        scoperte += 1 if tono == TONE_DANGER else 0
        res.riga({"reparto": r.nome, "area": "", "livello": "Reparto",
                  "ruolo": r.ruolo_responsabile.nome if r.ruolo_responsabile_id else "",
                  "titolari": _nomi(tit), "persone": per_rep.get(r.nome.casefold(), 0),
                  "senza_capo": senza_capo.get(r.nome.casefold(), 0), "stato": stato}, tono)
        if not o["includi_aree"]:
            continue
        for a in (x for x in aree if x.reparto_id == r.pk):
            if area_coincide_col_reparto(a):
                continue
            tit_a = tit_area.get(a.pk, [])
            if not a.ruolo_responsabile_id:
                stato, tono = "segue il reparto (nessun ruolo responsabile)", ""
            elif not resp_aree.get(a.pk) or not tit_a:
                stato, tono = "nessuno ha la «Responsabilità dell'area»: segue il reparto", TONE_WARN
            else:
                stato, tono = "ok" if len(tit_a) == 1 else f"{len(tit_a)} co-responsabili", ""
            if o["solo_problemi"] and not tono:
                continue
            res.riga({"reparto": r.nome, "area": a.nome, "livello": "Area",
                      "ruolo": a.ruolo_responsabile.nome if a.ruolo_responsabile_id else "",
                      "titolari": _nomi(tit_a), "persone": per_area.get(a.nome.casefold(), 0),
                      "senza_capo": "", "stato": stato}, tono)
    if o["solo_problemi"]:
        tenute = [(r, t) for r, t in zip(res.righe, res.toni) if t]
        res.righe, res.toni = [r for r, _t in tenute], [t for _r, t in tenute]
    totale_senza = sum(senza_capo.values())
    res.kpis = [
        Kpi("Reparti", len(reparti)),
        Kpi("Reparti senza capo dalla mansione", scoperte, TONE_DANGER if scoperte else TONE_OK),
        Kpi("Persone senza capo", totale_senza, TONE_DANGER if totale_senza else TONE_OK),
        Kpi("Regola unica", "accesa" if capo_team.regola_unica_attiva() else "spenta"),
    ]
    res.note = ["Il capo del reparto è chi ha la «Responsabilità del reparto», il responsabile dell'area chi ha la "
                "«Responsabilità dell'area»; area senza ruolo responsabile = segue il reparto.",
                "Con la regola unica spenta i moduli usano ancora i capi scelti a mano (pagina «Reparti, aree e capi»)."]
    return res


_registra(Sezione(
    key="capi_responsabilita",
    titolo="Capi e responsabilità",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Reparti e aree con ruolo responsabile, chi ha la «Responsabilità» e persone senza capo.",
    builder=_capi_responsabilita,
    riferimenti=(f"{ISO_9001} §5.3", f"{ISO_45001} §5.3", "D.Lgs. 81/2008 art. 19"),
    colonne=(("reparto", "Reparto"), ("area", "Area aziendale"), ("livello", "Livello"),
             ("ruolo", "Ruolo responsabile"), ("titolari", "Capo / responsabile"), ("persone", "Persone"),
             ("senza_capo", "Senza capo"), ("stato", "Stato")),
    predefinite=("reparto", "area", "ruolo", "titolari", "persone", "stato"),
    opzioni=(
        Opzione("includi_aree", "Mostra anche le aree", SI_NO, predefinito=True),
        Opzione("solo_problemi", "Solo righe da sistemare", SI_NO, predefinito=False),
    ),
))


# ═══════════════════════════════════════════════════════════════════════════
# Copertura delle mansioni
# ═══════════════════════════════════════════════════════════════════════════

def _copertura_mansioni(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.services import mansionario_struttura as mstr

    res = Risultato()
    persone, alias = _per_persona(ctx)
    righe = mstr.riepilogo()
    filtro_ruoli = {int(r) for r in o["ruoli"]}
    nel_perimetro = set(alias)
    scoperte = uomo_solo = 0
    for r in sorted(righe, key=lambda x: ((x["reparto"] or "").casefold(), x["nome"].casefold())):
        m = r["mansione"]
        if o["tipo"] == "responsabilita" and not m.is_responsabilita:
            continue
        if o["tipo"] in ("macchina", "processo") and (m.tipo != o["tipo"] or m.is_responsabilita):
            continue
        if filtro_ruoli and not any(x.pk in filtro_ruoli for x in r["ruoli"]):
            continue
        ids = [i for i in r["persone_ids"] if i in nel_perimetro]
        if _perimetro_ristretto(ctx) and not ids and o["solo_perimetro"]:
            continue
        lv = r["livelli"]
        if m.is_responsabilita:
            stato, tono = ("ok", "") if r["in_lista"] else ("nessun titolare", TONE_DANGER)
        elif not r["operativi"]:
            stato, tono = "nessun operativo", TONE_DANGER
        elif r["uomo_solo"]:
            stato, tono = "uomo solo", TONE_WARN
        else:
            stato, tono = "ok", ""
        scoperte += 1 if tono == TONE_DANGER else 0
        uomo_solo += 1 if stato == "uomo solo" else 0
        res.riga({
            "mansione": r["nome"], "tipo": "Responsabilità" if m.is_responsabilita else m.get_tipo_display(),
            "reparto": r["reparto"], "area": m.area.nome if m.area_id else "",
            "ruoli": ", ".join(x.nome for x in r["ruoli"]), "in_lista": r["in_lista"], "operativi": r["operativi"],
            "livelli": f"O {lv['O']} · U {lv['U']} · L {lv['L']} · I {lv['I']}",
            "persone": ", ".join(persone[alias[i]].nominativo for i in ids) if o["mostra_nomi"] else "",
            "rischi": ", ".join(x.nome for x in r["rischi"]), "stato": stato,
        }, tono)
    res.kpis = [Kpi("Mansioni", len(res.righe)),
                Kpi("Scoperte", scoperte, TONE_DANGER if scoperte else TONE_OK),
                Kpi("Uomo solo", uomo_solo, TONE_WARN if uomo_solo else TONE_OK)]
    res.note = ["Operativi: in lista al livello di soglia della skill matrix o sopra. «Uomo solo»: meno operativi "
                "della soglia (MT CN 06 §8.2.2). Per le «Responsabilità» conta solo che ci sia un titolare."]
    return res


_registra(Sezione(
    key="copertura_mansioni",
    titolo="Copertura delle mansioni",
    gruppo=GRUPPO_PERSONE,
    descrizione="Per mansione persone in lista, operativi, livelli, «uomo solo» e titolari delle responsabilità.",
    builder=_copertura_mansioni,
    riferimenti=(f"{ISO_9001} §7.1.2", f"{ISO_9001} §7.2", f"{EN_9100} §7.2"),
    colonne=(("mansione", "Mansione"), ("tipo", "Tipo"), ("reparto", "Reparto"), ("area", "Area aziendale"),
             ("ruoli", "Ruoli"), ("in_lista", "In lista"), ("operativi", "Operativi"), ("livelli", "Livelli"),
             ("persone", "Persone"), ("rischi", "Mansione di rischio"), ("stato", "Stato")),
    predefinite=("mansione", "reparto", "ruoli", "in_lista", "operativi", "stato"),
    opzioni=(
        Opzione("tipo", "Mansioni", SCELTA, _scelte_tipi, ""),
        Opzione("ruoli", "Solo mansioni di questi ruoli", MULTI, _scelte_ruoli, aiuto="Nessuno = tutte."),
        Opzione("mostra_nomi", "Riempi la colonna Persone con i nomi", SI_NO, predefinito=True),
        Opzione("solo_perimetro", "Con un perimetro: solo mansioni con persone del perimetro", SI_NO,
                predefinito=True),
    ),
))
