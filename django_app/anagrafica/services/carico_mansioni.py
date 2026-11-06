"""Carico sulle mansioni: una regola sola per Prospetto, report, schede e centri di costo.

Conta le assegnazioni attive in lista delle persone in forza e legge le soglie da
``SkillMatrixConfig``. Scoperta, uomo solo, carico concentrato, troppe mansioni e
persona chiave sono segnali dai coefficienti: il portale non conosce le ore
richieste da una mansione.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from ..models import AbilitazioneMacchina, CostoOrarioMensile
from ..models_skillmatrix import CompetenzaSkm, SkillMatrixConfig
from . import capo_team
from .mansionario_struttura import TIPI_MANSIONE

logger = logging.getLogger(__name__)
ZERO = Decimal(0)
OK = "ok"
SCOPERTA = "scoperta"
UOMO_SOLO = "uomo solo"
SENZA_TITOLARE = "nessun titolare"


@dataclass
class Abil:
    mansione_id: int
    livello: str
    operativa: bool
    coefficiente: Decimal | None
    id_reale: int | None = None


def quote(sue: list) -> list:
    """(id mansione, peso) con somma 1: stessa regola di ``reportistica.sezioni_costi._quote``."""
    contate = [a for a in sue if a.coefficiente is not None]
    somma = sum((a.coefficiente for a in contate), ZERO)
    if not contate or somma <= 0:
        return [(None, Decimal(1))]
    return [(a.mansione_id, a.coefficiente / somma) for a in contate]


def classifica(r: dict, *, responsabilita: bool, soglia_uomo_solo: int, soglia_concentrazione: int) -> None:
    """Scrive in ``r`` stato e carico partendo da lista, operativi e fte_operativi."""
    if responsabilita:
        r["stato"] = OK if r["lista"] else SENZA_TITOLARE
    elif not r["operativi"]:
        r["stato"] = SCOPERTA
    elif r["operativi"] < soglia_uomo_solo:
        r["stato"] = UOMO_SOLO
    else:
        r["stato"] = OK
    # Quanta parte del loro tempo danno qui gli operativi, senza chi è in lista sotto la soglia
    # (altrimenti supera il 100%): alta = poco margine se aumenta il lavoro.
    r["concentrazione"] = (int((r["fte_operativi"] / r["operativi"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                           if r["operativi"] else None)
    r["concentrato"] = (not responsabilita and r["concentrazione"] is not None
                        and r["concentrazione"] >= soglia_concentrazione)


def _riga_vuota(m) -> dict:
    return {"mansione": m, "lista": 0, "operativi": 0, "fte": ZERO, "fte_operativi": ZERO,
            "persone_ids": set(), "operativi_ids": set(), "livelli": Counter()}


def _conteggi(righe) -> dict:
    contate = [r for r in righe if not r["mansione"].is_responsabilita]
    scoperte = sum(1 for r in contate if r["stato"] == SCOPERTA)
    uomo_solo = sum(1 for r in contate if r["stato"] == UOMO_SOLO)
    concentrate = sum(1 for r in contate if r["concentrato"])
    return {"mansioni": len(contate), "scoperte": scoperte, "uomo_solo": uomo_solo, "concentrate": concentrate,
            "da_guardare": sum(1 for r in contate if r["stato"] != OK or r["concentrato"])}


@dataclass
class Carico:
    config: SkillMatrixConfig
    in_forza: set
    alias: dict
    per_mansione: dict = field(default_factory=dict)
    per_persona: dict = field(default_factory=dict)
    cessati_in_lista: int = 0

    def conteggi(self, ids=None) -> dict:
        righe = self.per_mansione.values() if ids is None else [self.per_mansione[i] for i in ids if i in self.per_mansione]
        return _conteggi(righe)

    def per_area(self) -> dict:
        gruppi: dict = defaultdict(list)
        for r in self.per_mansione.values():
            gruppi[r["mansione"].area_id].append(r)
        return {k: _conteggi(v) for k, v in gruppi.items()}

    def per_centro(self) -> dict:
        gruppi: dict = defaultdict(list)
        for r in self.per_mansione.values():
            m = r["mansione"]
            gruppi[m.area.centro_di_costo_id if m.area_id else None].append(r)
        return {k: _conteggi(v) for k, v in gruppi.items()}

    def persona(self, legacy_id: int) -> dict:
        """I segnali di una persona, con le mansioni pronte da mostrare."""
        pid = self.alias.get(legacy_id, legacy_id)
        x = self.per_persona.get(pid)
        if x is None:
            return {"n": 0, "operative": 0, "troppe": False, "soglia": self.config.soglia_mansioni_persona,
                    "chiave": [], "concentrate": [], "in_forza": pid in self.in_forza}

        def voci(ids):
            return sorted(({"id": i, "nome": self.per_mansione[i]["mansione"].nome,
                            "carico": self.per_mansione[i]["concentrazione"]} for i in ids),
                          key=lambda v: v["nome"].casefold())

        return {"n": len(x["mansioni"]), "operative": len(x["operative"]), "troppe": x["troppe"],
                "soglia": self.config.soglia_mansioni_persona, "chiave": voci(x["chiave"]),
                "concentrate": voci(x["concentrate"]), "in_forza": True}


def calcola() -> Carico:
    """La situazione di oggi."""
    from ..reportistica.dati import carica_dipendenti

    config = SkillMatrixConfig.get_instance()
    soglia_ordinale = config.soglia_operativa_ordinale
    mansioni = {m.pk: m for m in CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, attiva=True)
                .select_related("area__centro_di_costo")}
    in_forza = set(capo_team.mappa_capi())
    alias = {i: p.id for p in carica_dipendenti() for i in p.tutti_gli_id}
    c = Carico(config=config, in_forza=in_forza, alias=alias,
               per_mansione={mid: _riga_vuota(m) for mid, m in mansioni.items()})
    abil: dict = defaultdict(dict)
    for a in AbilitazioneMacchina.objects.filter(
            in_lista=True, stato=AbilitazioneMacchina.STATO_ATTIVA, competenza_id__in=list(mansioni)):
        pid = alias.get(a.legacy_anagrafica_id, a.legacy_anagrafica_id)
        if pid not in in_forza:
            c.cessati_in_lista += 1
            continue
        abil[pid][a.competenza_id] = Abil(a.competenza_id, a.livello, a.is_operativa(soglia_ordinale), a.coefficiente, a.pk)
    for pid, sue in abil.items():
        elenco = list(sue.values())
        for a in elenco:
            r = c.per_mansione[a.mansione_id]
            r["lista"] += 1
            r["persone_ids"].add(pid)
            r["livelli"][a.livello] += 1
            if a.operativa:
                r["operativi"] += 1
                r["operativi_ids"].add(pid)
        operative = {a.mansione_id for a in elenco if a.operativa}
        for mid, peso in quote(elenco):
            if mid is None:
                continue
            c.per_mansione[mid]["fte"] += peso
            if mid in operative:
                c.per_mansione[mid]["fte_operativi"] += peso
        c.per_persona[pid] = {"mansioni": [a.mansione_id for a in elenco], "operative": sorted(operative),
                              "troppe": len(elenco) > config.soglia_mansioni_persona, "chiave": [], "concentrate": []}
    for mid, r in c.per_mansione.items():
        m = r["mansione"]
        classifica(r, responsabilita=m.is_responsabilita, soglia_uomo_solo=config.soglia_uomo_solo,
                   soglia_concentrazione=config.soglia_concentrazione)
        if m.is_responsabilita:
            continue
        if r["operativi"] == 1:
            c.per_persona[next(iter(r["operativi_ids"]))]["chiave"].append(mid)
        if r["concentrato"]:
            for pid in r["operativi_ids"]:
                c.per_persona[pid]["concentrate"].append(mid)
    return c


def oggi() -> Carico | None:
    """Per le pagine di consultazione: senza anagrafica leggibile la pagina resta in piedi."""
    try:
        return calcola()
    except Exception:
        logger.warning("carico sulle mansioni non calcolato", exc_info=True)
        return None


def su_riepilogo(righe: list, c: Carico | None) -> list:
    """Il Mansionario mostra le liste com'erano, ma operativi e segnali sono quelli del carico.

    ``fuori_forza``: persone in lista non più in forza, da togliere. Senza carico restano i
    numeri delle liste; le mansioni non attive non sono nel carico e restano come sono.
    """
    for r in righe:
        r.update(fuori_forza=0, concentrazione=None, concentrato=False)
        x = c.per_mansione.get(r["mansione"].pk) if c else None
        if x is None:
            continue
        r["operativi"] = x["operativi"]
        r["uomo_solo"] = x["operativi"] < c.config.soglia_uomo_solo
        r["concentrazione"], r["concentrato"] = x["concentrazione"], x["concentrato"]
        r["fuori_forza"] = sum(1 for i in r["persone_ids"] if c.alias.get(i, i) not in c.in_forza)
    return righe


def frasi_persona(c: Carico | None, legacy_id: int) -> list[str]:
    """I segnali di una persona in parole: stessa regola della scheda dipendente."""
    if c is None:
        return []
    p = c.persona(legacy_id)
    frasi = []
    if p["chiave"]:
        frasi.append("Unico operativo su " + ", ".join(v["nome"] for v in p["chiave"]))
    if p["troppe"]:
        frasi.append(f"Su {p['n']} mansioni (soglia {p['soglia']})")
    if p["concentrate"]:
        frasi.append("Carico concentrato su " + ", ".join(v["nome"] for v in p["concentrate"]))
    return frasi


def costi_per_persona(c: Carico) -> tuple:
    """(mese, {persona in forza: riga di costo}) dell'ultimo mese caricato. Solo per chi vede i costi."""
    mese = CostoOrarioMensile.objects.order_by("-mese").values_list("mese", flat=True).first()
    costi: dict = {}
    if mese:
        for riga in CostoOrarioMensile.objects.filter(mese=mese, legacy_anagrafica_id__isnull=False):
            pid = c.alias.get(riga.legacy_anagrafica_id, riga.legacy_anagrafica_id)
            if pid in c.in_forza:
                costi.setdefault(pid, riga)
    return mese, costi


def costi_per_centro(c: Carico) -> dict:
    """RML e costo orario medio per centro, ultimo mese caricato: stessi numeri del Prospetto. Solo per chi vede i costi."""
    from .reparto_canonico import build_area_canonica_map

    mese, costi = costi_per_persona(c)
    if not mese:
        return {"mese": None, "centri": {}}
    area_di = build_area_canonica_map(list(c.in_forza))
    gruppi: dict = defaultdict(lambda: {"rml": ZERO, "ore": []})
    for pid, riga in costi.items():
        area = area_di.get(pid)
        g = gruppi[area.centro_di_costo_id if area is not None else None]
        g["rml"] += riga.rml
        g["ore"].append(riga.costo_orario)
    due = Decimal("0.01")
    return {"mese": mese, "centri": {
        k: {"rml": g["rml"].quantize(due, rounding=ROUND_HALF_UP),
            "costo_medio": (sum(g["ore"], ZERO) / len(g["ore"])).quantize(due, rounding=ROUND_HALF_UP),
            "con_costo": len(g["ore"])}
        for k, g in gruppi.items()}}
