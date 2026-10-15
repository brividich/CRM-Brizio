"""Organigramma per mansione di rischio: mansione di rischio → persone.

Serve a RSPP e medico competente per leggere i gruppi omogenei del DVR con le
persone esposte, filtrando per fattore di rischio. Il gruppo è una voce del
catalogo ``Mansione``, che è il catalogo delle mansioni di rischio (decisione
15/10/2026, spec Mansionario). Le persone del gruppo sono chi ha la mansione di
rischio scritta in anagrafica, chi la ricava dalle mansioni che svolge
(Mansionario) e le aggiunte individuali; le esclusioni individuali sono elencate
a parte. Lo stato operativo è solo l'etichetta (nessun esito clinico).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Gruppo:
    mansione_rischio: object                              # anagrafica.Mansione
    fattori: list = field(default_factory=list)
    visite: list = field(default_factory=list)
    persone: list[dict] = field(default_factory=list)       # mansione di rischio in anagrafica
    da_mansioni: list[dict] = field(default_factory=list)   # ricavata dalle mansioni svolte
    aggiunte: list[dict] = field(default_factory=list)
    escluse: list[dict] = field(default_factory=list)

    @property
    def n_persone(self) -> int:
        return len(self.persone) + len(self.da_mansioni) + len(self.aggiunte)

    @property
    def mansioni(self) -> list[dict]:
        """Compatibilità con i consumatori a doppio livello: un solo gruppo, sé stesso."""
        return [{"mansione": self.mansione_rischio, "persone": self.persone}]


def costruisci(*, fattore_id: int | None = None, solo_attive: bool = True,
               can_view_visite: bool = False) -> list[Gruppo]:
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from django.utils import timezone

    from ..models import Mansione
    from . import mansionario, stato_operativo

    qs = Mansione.objects.prefetch_related("visite_richieste", "esposizioni_rischio__fattore").order_by("nome")
    if solo_attive:
        qs = qs.filter(is_active=True)
    if fattore_id:
        qs = qs.filter(esposizioni_rischio__fattore_id=fattore_id, esposizioni_rischio__is_active=True).distinct()

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
    ricavate = mansionario.mansioni_rischio_ricavate(list(per_id))
    override = mansionario.override_validi(list(per_id), timezone.localdate())

    def _con_stato(p, **extra):
        s = stati.get(p["legacy_id"])
        return {**p, **extra, "stato": s.etichetta_visibile(can_view_visite) if s else "",
                "bloccante": bool(s and s.bloccante)}

    # Per mansione di rischio: chi la ricava dalle mansioni svolte, chi l'ha aggiunta, chi è escluso.
    da_mansioni: dict[int, list[dict]] = {}
    for lid, voci in ricavate.items():
        if lid in per_id:
            for m, da in voci:
                da_mansioni.setdefault(m.pk, []).append(_con_stato(per_id[lid], da=da))
    aggiunte: dict[int, list[dict]] = {}
    escluse: dict[int, set[int]] = {}
    for lid, gruppo in override.items():
        if lid not in per_id:
            continue
        for o in gruppo:
            if o.azione == o.AZIONE_ESCLUDI:
                escluse.setdefault(o.mansione_rischio_id, set()).add(lid)
            else:
                aggiunte.setdefault(o.mansione_rischio_id, []).append(_con_stato(per_id[lid]))

    def _ordina(lista):
        return sorted(lista, key=lambda p: (p["nome"] or "").casefold())

    gruppi = []
    for m in qs:
        fattori = [e.fattore for e in m.esposizioni_rischio.all() if e.is_active and e.fattore.is_active]
        fuori = escluse.get(m.pk, set())
        persone = [_con_stato(p) for p in per_nome.get(m.nome.strip().casefold(), []) if p["legacy_id"] not in fuori]
        gia = {p["legacy_id"] for p in persone}
        dalle_mansioni = [p for p in da_mansioni.get(m.pk, []) if p["legacy_id"] not in gia | fuori]
        gia |= {p["legacy_id"] for p in dalle_mansioni}
        aggiunti = [p for p in aggiunte.get(m.pk, []) if p["legacy_id"] not in gia]
        gruppi.append(Gruppo(mansione_rischio=m, fattori=fattori, visite=list(m.visite_richieste.all()),
                             persone=_ordina(persone), da_mansioni=_ordina(dalle_mansioni),
                             aggiunte=_ordina(aggiunti),
                             escluse=_ordina([per_id[lid] for lid in fuori])))
    return gruppi


def righe_export(gruppi: list[Gruppo]) -> list[dict]:
    out = []
    for g in gruppi:
        m = g.mansione_rischio
        base = {"codice": "", "mansione_rischio": m.nome,
                "livello": m.get_livello_rischio_display() if m.livello_rischio else "",
                "dvr": " ".join(x for x in (m.dvr_revisione, m.dvr_data.strftime("%d/%m/%Y") if m.dvr_data else "") if x),
                "fattori": ", ".join(f.nome for f in g.fattori),
                "protocollo": ", ".join(v.nome for v in g.visite)}
        for p in g.persone:
            out.append({**base, "mansione": m.nome, "dipendente": p["nome"],
                        "reparto": p["reparto"], "via": "Mansione in anagrafica", "stato": p["stato"]})
        for p in g.da_mansioni:
            out.append({**base, "mansione": ", ".join(p["da"]), "dipendente": p["nome"],
                        "reparto": p["reparto"], "via": "Mansione svolta", "stato": p["stato"]})
        for p in g.aggiunte:
            out.append({**base, "mansione": m.nome, "dipendente": p["nome"],
                        "reparto": p["reparto"], "via": "Aggiunta individuale", "stato": p["stato"]})
    return out
