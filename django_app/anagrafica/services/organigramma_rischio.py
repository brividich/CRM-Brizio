"""Organigramma per mansione di rischio: mansione di rischio → persone.

Serve a RSPP e medico competente per leggere i gruppi omogenei del DVR con le
persone esposte, filtrando per fattore di rischio. Il gruppo è una voce del
catalogo ``Mansione``, che è il catalogo delle mansioni di rischio (decisione
15/10/2026, spec Mansionario); le persone arrivano dalla mansione scritta sulla
loro anagrafica (per nome). Lo stato operativo è solo l'etichetta (nessun esito
clinico).

Il vecchio modello ``MansioneRischio`` (vuoto in produzione) non alimenta più
l'organigramma: aggiunte ed esclusioni individuali tornano quando la mansione di
rischio della persona sarà calcolata dalle mansioni assegnate (fase 5).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Gruppo:
    mansione_rischio: object                              # anagrafica.Mansione
    fattori: list = field(default_factory=list)
    visite: list = field(default_factory=list)
    persone: list[dict] = field(default_factory=list)
    aggiunte: list[dict] = field(default_factory=list)   # in attesa della fase 5
    escluse: list[dict] = field(default_factory=list)

    @property
    def n_persone(self) -> int:
        return len(self.persone) + len(self.aggiunte)

    @property
    def mansioni(self) -> list[dict]:
        """Compatibilità con i consumatori a doppio livello: un solo gruppo, sé stesso."""
        return [{"mansione": self.mansione_rischio, "persone": self.persone}]


def costruisci(*, fattore_id: int | None = None, solo_attive: bool = True,
               can_view_visite: bool = False) -> list[Gruppo]:
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from ..models import Mansione
    from . import stato_operativo

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

    def _con_stato(p):
        s = stati.get(p["legacy_id"])
        return {**p, "stato": s.etichetta_visibile(can_view_visite) if s else "", "bloccante": bool(s and s.bloccante)}

    gruppi = []
    for m in qs:
        fattori = [e.fattore for e in m.esposizioni_rischio.all() if e.is_active and e.fattore.is_active]
        persone = [_con_stato(p) for p in per_nome.get(m.nome.strip().casefold(), [])]
        persone.sort(key=lambda p: (p["nome"] or "").casefold())
        gruppi.append(Gruppo(mansione_rischio=m, fattori=fattori, visite=list(m.visite_richieste.all()),
                             persone=persone))
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
    return out
