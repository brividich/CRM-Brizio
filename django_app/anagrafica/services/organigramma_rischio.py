"""Organigramma a doppio livello: mansione di rischio → mansione lavorativa → persone.

Serve a RSPP e medico competente per leggere i gruppi omogenei del DVR con le
persone esposte, filtrando per fattore di rischio. Le persone arrivano dalla
mansione lavorativa (per nome) o da un'aggiunta individuale; chi ha
un'esclusione individuale non compare nel gruppo. Lo stato operativo è solo
l'etichetta (nessun esito clinico).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Gruppo:
    mansione_rischio: object
    fattori: list = field(default_factory=list)
    visite: list = field(default_factory=list)
    mansioni: list[dict] = field(default_factory=list)   # {"mansione": Mansione, "persone": [...]}
    aggiunte: list[dict] = field(default_factory=list)   # persone da override ADD
    escluse: list[dict] = field(default_factory=list)

    @property
    def n_persone(self) -> int:
        return sum(len(m["persone"]) for m in self.mansioni) + len(self.aggiunte)


def costruisci(*, fattore_id: int | None = None, solo_attive: bool = True,
               can_view_visite: bool = False) -> list[Gruppo]:
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from ..models_mansioni_rischio import MansioneRischio
    from . import stato_operativo

    qs = MansioneRischio.objects.prefetch_related(
        "fattori", "visite", "link_mansioni__mansione", "override_dipendenti",
    ).order_by("codice")
    if solo_attive:
        qs = qs.filter(is_active=True)
    if fattore_id:
        qs = qs.filter(fattori__pk=fattore_id).distinct()

    righe = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo", True)]
    per_nome: dict[str, list[dict]] = {}
    per_id: dict[int, dict] = {}
    for r in righe:
        lid = int(r.get("id") or 0)
        persona = {"legacy_id": lid, "nome": naming.nome_completo(r.get("nome"), r.get("cognome")),
                   "reparto": r.get("reparto") or "", "mansione": str(r.get("mansione") or "").strip()}
        per_id[lid] = persona
        per_nome.setdefault(persona["mansione"].casefold(), []).append(persona)
    stati = stato_operativo.calcola(list(per_id))

    def _con_stato(p):
        s = stati.get(p["legacy_id"])
        return {**p, "stato": s.etichetta_visibile(can_view_visite) if s else "", "bloccante": bool(s and s.bloccante)}

    gruppi = []
    for mr in qs:
        override = [o for o in mr.override_dipendenti.all() if o.attivo]
        esclusi = {o.legacy_anagrafica_id for o in override if o.azione == "EXCLUDE"}
        g = Gruppo(mansione_rischio=mr, fattori=list(mr.fattori.all()), visite=list(mr.visite.all()))
        for link in sorted(mr.link_mansioni.all(), key=lambda l: (l.mansione.nome.casefold())):
            persone = [_con_stato(p) for p in per_nome.get(link.mansione.nome.strip().casefold(), [])
                       if p["legacy_id"] not in esclusi]
            persone.sort(key=lambda p: (p["nome"] or "").casefold())
            g.mansioni.append({"mansione": link.mansione, "persone": persone})
        g.aggiunte = [_con_stato(per_id[o.legacy_anagrafica_id]) for o in override
                      if o.azione == "ADD" and o.legacy_anagrafica_id in per_id]
        g.escluse = [per_id[lid] for lid in esclusi if lid in per_id]
        gruppi.append(g)
    return gruppi


def righe_export(gruppi: list[Gruppo]) -> list[dict]:
    out = []
    for g in gruppi:
        mr = g.mansione_rischio
        base = {"codice": mr.codice, "mansione_rischio": mr.nome,
                "livello": mr.get_livello_rischio_dvr_display() if mr.livello_rischio_dvr else "",
                "dvr": " ".join(x for x in (mr.dvr_revisione, mr.dvr_data.strftime("%d/%m/%Y") if mr.dvr_data else "") if x),
                "fattori": ", ".join(f.nome for f in g.fattori),
                "protocollo": ", ".join(v.nome for v in g.visite)}
        for m in g.mansioni:
            for p in m["persone"]:
                out.append({**base, "mansione": m["mansione"].nome, "dipendente": p["nome"],
                            "reparto": p["reparto"], "via": "Mansione lavorativa", "stato": p["stato"]})
        for p in g.aggiunte:
            out.append({**base, "mansione": p["mansione"], "dipendente": p["nome"], "reparto": p["reparto"],
                        "via": "Aggiunta individuale", "stato": p["stato"]})
    return out
