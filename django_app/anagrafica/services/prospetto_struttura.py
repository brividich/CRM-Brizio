"""Prospetto dei cambiamenti: cosa succederebbe se spostassi reparti, persone, ruoli o mansioni.

Niente si scrive finché non si applica. Il prospetto copia lo stato di oggi in memoria,
ci applica le modifiche e fa girare gli stessi calcoli sui due stati: quello che cambia
fra «Oggi» e «Dopo» dipende solo dalle modifiche.

Fonti, le stesse delle altre pagine:
- persone in forza, area e ruoli: ``esplora_struttura.Dati``;
- capo: ``capo_team.mappa_capi`` con la stessa regola, sulle persone modificate;
- operativi e «uomo solo»: ``AbilitazioneMacchina.is_operativa`` e ``soglia_uomo_solo``;
- teste equivalenti e costo per mansione: i pesi di ``reportistica.sezioni_costi._quote``;
- RML e costo orario: ``CostoOrarioMensile`` dell'ultimo mese.

Un'avvertenza vale per tutto il carico: il portale non conosce le ore richieste da una
mansione. «Carico concentrato» e «su troppe mansioni» sono segnali dai coefficienti e
dalle soglie delle impostazioni della skill matrix, non una misura di ore.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from ..models import AbilitazioneMacchina, CostoOrarioMensile, DipendenteAnagraficaAziendale
from ..models_skillmatrix import SkillMatrixConfig, ordinale_livello
from ..models_struttura import ProspettoModifica as M
from . import capo_team, esplora_struttura, ruoli_in_blocco
from .mansionario_struttura import assegna, togli

SENZA_CENTRO = "Senza centro di costo"
SENZA_REPARTO = "Senza reparto"
ZERO = Decimal(0)


def _quote(sue: list) -> list:
    """(id mansione, peso) con somma 1: stessa regola di ``sezioni_costi._quote``, sullo stato simulato."""
    contate = [a for a in sue if a.coefficiente is not None]
    somma = sum((a.coefficiente for a in contate), ZERO)
    if not contate or somma <= 0:
        return [(None, Decimal(1))]
    return [(a.mansione_id, a.coefficiente / somma) for a in contate]


@dataclass
class Abil:
    mansione_id: int
    livello: str
    operativa: bool
    coefficiente: Decimal | None
    id_reale: int | None = None


@dataclass
class Stato:
    area_di: dict = field(default_factory=dict)        # persona → area
    centro_area: dict = field(default_factory=dict)    # area → centro o None
    ruoli_di: dict = field(default_factory=dict)       # persona → set di ruoli
    area_mansione: dict = field(default_factory=dict)  # mansione → area o None
    abil: dict = field(default_factory=dict)           # persona → {mansione: Abil}

    def copia(self) -> "Stato":
        return Stato(
            dict(self.area_di), dict(self.centro_area), {k: set(v) for k, v in self.ruoli_di.items()},
            dict(self.area_mansione),
            {p: {m: Abil(a.mansione_id, a.livello, a.operativa, a.coefficiente, a.id_reale) for m, a in v.items()}
             for p, v in self.abil.items()},
        )


class Base:
    """Lo stato di oggi e i cataloghi: si legge una volta, vale per Oggi e per Dopo."""

    def __init__(self):
        from ..reportistica.dati import carica_dipendenti

        self.dati = esplora_struttura.Dati.carica()
        d = self.dati
        self.config = SkillMatrixConfig.get_instance()
        self.soglia_ordinale = self.config.soglia_operativa_ordinale
        self.aree = {a.pk: a for a in d.aree}
        self.centri = {c.pk: c for c in d.centri}
        self.mansioni = {m.pk: m for m in d.mansioni}
        self.ruoli = d.ruoli
        dipendenti = carica_dipendenti()
        self.alias = {i: p.id for p in dipendenti for i in p.tutti_gli_id}
        self.nomi = {p.id: p.nominativo for p in dipendenti}
        self.mansione_rischio = {p.id: p.mansione for p in dipendenti}
        self.principale = dict(DipendenteAnagraficaAziendale.objects.exclude(ruolo_aziendale="").values_list(
            "legacy_anagrafica_id", "ruolo_aziendale"))
        self.mese = CostoOrarioMensile.objects.order_by("-mese").values_list("mese", flat=True).first()
        self.costi = {}
        if self.mese:
            for c in CostoOrarioMensile.objects.filter(mese=self.mese, legacy_anagrafica_id__isnull=False):
                pid = self.alias.get(c.legacy_anagrafica_id, c.legacy_anagrafica_id)
                if pid in d.in_forza:
                    self.costi.setdefault(pid, c)
        self.cessati_in_lista = 0
        abil: dict[int, dict] = defaultdict(dict)
        for a in AbilitazioneMacchina.objects.filter(
                in_lista=True, stato=AbilitazioneMacchina.STATO_ATTIVA, competenza_id__in=list(self.mansioni)):
            pid = self.alias.get(a.legacy_anagrafica_id, a.legacy_anagrafica_id)
            if pid not in d.in_forza:
                self.cessati_in_lista += 1
                continue
            abil[pid][a.competenza_id] = Abil(a.competenza_id, a.livello, a.is_operativa(self.soglia_ordinale),
                                              a.coefficiente, a.pk)
        self.stato = Stato(
            area_di=dict(d.area_di), centro_area={a.pk: a.centro_di_costo_id for a in d.aree},
            ruoli_di={p: set(r) for p, r in d.ruoli_di.items()},
            area_mansione={m.pk: m.area_id for m in d.mansioni}, abil=dict(abil),
        )

    def nome_persona(self, pid) -> str:
        return self.nomi.get(pid) or f"#{pid}"

    def nome_ruolo(self, rid) -> str:
        r = self.ruoli.get(rid)
        return (r.sigla or r.nome) if r else "—"

    def nome_area(self, aid) -> str:
        a = self.aree.get(aid)
        return a.nome if a else SENZA_REPARTO

    def nome_centro(self, cid) -> str:
        c = self.centri.get(cid)
        return c.nome if c else SENZA_CENTRO

    def centro_persona(self, stato: Stato, pid):
        return stato.centro_area.get(stato.area_di.get(pid))


# ── Applicare le modifiche allo stato in memoria ────────────────────────────

def _togli_mansione(stato: Stato, pid: int, mid: int) -> None:
    (stato.abil.get(pid) or {}).pop(mid, None)


def _aggiungi_mansione(stato: Stato, base: Base, pid: int, mid: int, livello: str) -> None:
    """La nuova prende 1/n e le altre si riducono in proporzione, come i segnali dei coefficienti."""
    sue = stato.abil.setdefault(pid, {})
    if mid in sue:
        sue[mid].livello = livello
        sue[mid].operativa = ordinale_livello(livello) >= base.soglia_ordinale
        return
    n = len(sue) + 1
    somma = sum((a.coefficiente for a in sue.values() if a.coefficiente is not None), ZERO)
    for a in sue.values():
        if a.coefficiente is not None and somma > 0:
            a.coefficiente = a.coefficiente / somma * (n - 1) / n
    sue[mid] = Abil(mid, livello, ordinale_livello(livello) >= base.soglia_ordinale, Decimal(1) / n)


def _mansioni_da_lasciare(stato: Stato, pid: int, area_id) -> list[int]:
    return [m for m in (stato.abil.get(pid) or {}) if area_id and stato.area_mansione.get(m) == area_id]


def descrivi(base: Base, m: M) -> str:
    if m.tipo == M.REPARTO_CENTRO:
        a = base.aree.get(m.soggetto_id)
        return f"Reparto {a.nome if a else '#' + str(m.soggetto_id)} → {base.nome_centro(m.destinazione_id)}"
    if m.tipo == M.PERSONA_REPARTO:
        frase = f"{base.nome_persona(m.soggetto_id)} → reparto {base.nome_area(m.destinazione_id)}"
        return frase + (", lascia le mansioni del reparto di prima" if m.modo == M.LASCIA else ", tiene le sue mansioni")
    if m.tipo == M.PERSONA_RUOLO:
        verbo = {ruoli_in_blocco.AGGIUNGI: "aggiunge", ruoli_in_blocco.SOSTITUISCI: "passa al ruolo",
                 ruoli_in_blocco.CHIUDI: "lascia"}.get(m.modo, m.modo)
        return f"{base.nome_persona(m.soggetto_id)} {verbo} {base.nome_ruolo(m.destinazione_id)}"
    if m.tipo == M.PERSONA_MANSIONE:
        mans = base.mansioni.get(m.destinazione_id)
        nome = mans.nome if mans else f"#{m.destinazione_id}"
        if m.modo == M.TOGLI:
            return f"{base.nome_persona(m.soggetto_id)} esce dalla mansione {nome}"
        return f"{base.nome_persona(m.soggetto_id)} entra nella mansione {nome} a livello {m.livello}"
    if m.tipo == M.MANSIONE_REPARTO:
        mans = base.mansioni.get(m.soggetto_id)
        return f"Mansione {mans.nome if mans else '#' + str(m.soggetto_id)} → reparto {base.nome_area(m.destinazione_id)}"
    return m.tipo


def problema(base: Base, m: M) -> str:
    """Perché una modifica non si può simulare o applicare; vuoto se va bene."""
    d = base.dati
    if m.tipo == M.REPARTO_CENTRO:
        if m.soggetto_id not in base.aree:
            return "il reparto non esiste più"
        if m.destinazione_id and m.destinazione_id not in base.centri:
            return "il centro di costo non esiste più"
        return ""
    if m.tipo == M.MANSIONE_REPARTO:
        mans = base.mansioni.get(m.soggetto_id)
        if mans is None:
            return "la mansione non è più attiva"
        if mans.is_responsabilita:
            return "una «Responsabilità» segue il suo reparto: non si sposta"
        if m.destinazione_id not in base.aree:
            return "il reparto non esiste più"
        return ""
    if m.soggetto_id not in d.in_forza:
        return "la persona non è più in forza"
    if m.tipo == M.PERSONA_REPARTO:
        a = base.aree.get(m.destinazione_id)
        if a is None:
            return "il reparto non esiste più"
        if not a.reparto_id:
            return f"{a.nome} non è in un reparto del portale: lo spostamento lo scarterebbe. Sceglilo prima"
        return ""
    if m.tipo == M.PERSONA_RUOLO:
        r = base.ruoli.get(m.destinazione_id)
        if r is None:
            return "il ruolo non esiste più"
        try:
            ruoli_in_blocco._controlla(r, m.modo, timezone.localdate())
        except ValueError as exc:
            return str(exc)
        return ""
    if m.tipo == M.PERSONA_MANSIONE:
        if m.destinazione_id not in base.mansioni:
            return "la mansione non è più attiva"
        return ""
    return "modifica sconosciuta"


def simula(base: Base, modifiche) -> Stato:
    s = base.stato.copia()
    for m in modifiche:
        if problema(base, m):
            continue
        if m.tipo == M.REPARTO_CENTRO:
            s.centro_area[m.soggetto_id] = m.destinazione_id or None
        elif m.tipo == M.MANSIONE_REPARTO:
            s.area_mansione[m.soggetto_id] = m.destinazione_id
        elif m.tipo == M.PERSONA_REPARTO:
            prima = s.area_di.get(m.soggetto_id)
            if m.modo == M.LASCIA and prima != m.destinazione_id:
                for mid in _mansioni_da_lasciare(s, m.soggetto_id, prima):
                    _togli_mansione(s, m.soggetto_id, mid)
            s.area_di[m.soggetto_id] = m.destinazione_id
        elif m.tipo == M.PERSONA_RUOLO:
            ruoli = s.ruoli_di.setdefault(m.soggetto_id, set())
            if m.modo == ruoli_in_blocco.CHIUDI:
                ruoli.discard(m.destinazione_id)
            else:
                if m.modo == ruoli_in_blocco.SOSTITUISCI:
                    nome = (base.principale.get(m.soggetto_id) or "").casefold()
                    ruoli -= {r for r in ruoli if base.ruoli[r].nome.casefold() == nome}
                ruoli.add(m.destinazione_id)
        elif m.tipo == M.PERSONA_MANSIONE:
            if m.modo == M.TOGLI:
                _togli_mansione(s, m.soggetto_id, m.destinazione_id)
            else:
                _aggiungi_mansione(s, base, m.soggetto_id, m.destinazione_id, m.livello or "U")
    return s


def _mappa_capi(base: Base, s: Stato | None) -> dict:
    if s is None:
        return capo_team.mappa_capi()

    def varianti(persone):
        for pid, p in persone.items():
            if pid in s.area_di:
                p.area_id = s.area_di[pid]
                area = base.aree.get(p.area_id)
                if area is not None and area.reparto_id:
                    p.reparto_id = area.reparto_id
            p.ruoli = {r for r in s.ruoli_di.get(pid, set()) if base.ruoli.get(r) is not None and base.ruoli[r].is_active}

    return capo_team.mappa_capi(varianti=varianti)


# ── Misure ──────────────────────────────────────────────────────────────────

def misure(base: Base, s: Stato, *, soglia_mansioni: int, soglia_concentrazione: int, capi: dict) -> dict:
    in_forza = base.dati.in_forza
    # Persone per centro e per reparto
    per_centro: dict = defaultdict(lambda: {"persone": set(), "reparti": set(), "rml": ZERO, "ore": []})
    per_area: dict = defaultdict(lambda: {"persone": set(), "rml": ZERO, "ore": []})
    for pid in in_forza:
        aid = s.area_di.get(pid)
        cid = s.centro_area.get(aid)
        per_centro[cid]["persone"].add(pid)
        per_area[aid]["persone"].add(pid)
        c = base.costi.get(pid)
        if c is not None:
            per_centro[cid]["rml"] += c.rml
            per_centro[cid]["ore"].append(c.costo_orario)
            per_area[aid]["rml"] += c.rml
            per_area[aid]["ore"].append(c.costo_orario)
    for aid, cid in s.centro_area.items():
        per_centro[cid]["reparti"].add(aid)

    # Mansioni: operativi, teste equivalenti e costo ripartito con i coefficienti
    per_mansione: dict = {mid: {"lista": 0, "operativi": 0, "fte": ZERO, "fte_operativi": ZERO, "rml": ZERO, "ora": ZERO, "persone": set(),
                                "operativi_ids": set()} for mid in base.mansioni}
    senza_mansioni = {"fte": ZERO, "rml": ZERO, "ora": ZERO, "persone": set()}
    per_persona: dict = {}
    for pid in in_forza:
        sue = list((s.abil.get(pid) or {}).values())
        operative = [a.mansione_id for a in sue if a.operativa]
        per_persona[pid] = {"mansioni": len(sue), "operative": operative}
        for a in sue:
            r = per_mansione[a.mansione_id]
            r["lista"] += 1
            r["persone"].add(pid)
            if a.operativa:
                r["operativi"] += 1
                r["operativi_ids"].add(pid)
        c = base.costi.get(pid)
        for mid, peso in _quote(sue):
            r = per_mansione[mid] if mid is not None else senza_mansioni
            r["fte"] += peso
            if mid in operative:
                r["fte_operativi"] += peso
            r["persone"].add(pid)
            if c is not None:
                r["rml"] += c.rml * peso
                r["ora"] += c.costo_orario * peso

    soglia_solo = base.config.soglia_uomo_solo
    for mid, r in per_mansione.items():
        mans = base.mansioni[mid]
        if mans.is_responsabilita:
            r["stato"] = "ok" if r["lista"] else "nessun titolare"
        elif not r["operativi"]:
            r["stato"] = "scoperta"
        elif r["operativi"] < soglia_solo:
            r["stato"] = "uomo solo"
        else:
            r["stato"] = "ok"
        # Quanta parte del loro tempo danno qui gli operativi, senza chi è in lista sotto la soglia
        # (altrimenti supera il 100%): alta = poco margine se aumenta il lavoro.
        r["concentrazione"] = (int((r["fte_operativi"] / r["operativi"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                               if r["operativi"] else None)
        r["concentrato"] = (not mans.is_responsabilita and r["concentrazione"] is not None
                            and r["concentrazione"] >= soglia_concentrazione)

    # Persone: su troppe mansioni e persone chiave (unico operativo)
    uniche: dict[int, list] = defaultdict(list)
    for mid, r in per_mansione.items():
        if r["operativi"] == 1 and not base.mansioni[mid].is_responsabilita:
            uniche[next(iter(r["operativi_ids"]))].append(mid)
    troppe = {pid for pid, x in per_persona.items() if x["mansioni"] > soglia_mansioni}

    contate = [r for mid, r in per_mansione.items() if not base.mansioni[mid].is_responsabilita]
    previsti_scoperti = []
    for a in base.dati.aree:
        if not a.is_active:
            continue
        presenti = {r for p, ar in s.area_di.items() if ar == a.pk for r in s.ruoli_di.get(p, set())}
        for r in a.ruoli_reparto.all():
            if r.pk not in presenti:
                previsti_scoperti.append((a.pk, r.pk))
    ore = [c.costo_orario for c in base.costi.values()]
    return {
        "per_centro": per_centro, "per_area": per_area, "per_mansione": per_mansione, "per_persona": per_persona,
        "senza_mansioni": senza_mansioni, "uniche": dict(uniche), "troppe": troppe, "capi": capi,
        "previsti_scoperti": set(previsti_scoperti),
        "kpi": {
            "persone_senza_centro": len(per_centro[None]["persone"]) if None in per_centro else 0,
            "senza_capo": sum(1 for pid in in_forza if not (capi.get(pid) and capi[pid].legacy_id)),
            "scoperte": sum(1 for r in contate if r["stato"] == "scoperta"),
            "uomo_solo": sum(1 for r in contate if r["stato"] == "uomo solo"),
            "concentrate": sum(1 for r in contate if r["concentrato"]),
            "troppe": len(troppe), "chiave": len(uniche),
            "ruoli_scoperti": len(previsti_scoperti),
            "rml": sum((c.rml for c in base.costi.values()), ZERO),
            "costo_medio": sum(ore, ZERO) / len(ore) if ore else None,
        },
    }


def _euro(v) -> Decimal | None:
    return None if v is None else Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _media(valori) -> Decimal | None:
    return sum(valori, ZERO) / len(valori) if valori else None


def _delta(prima, dopo):
    return None if prima is None or dopo is None else dopo - prima


# ── Confronto ───────────────────────────────────────────────────────────────

KPI = [
    ("persone_senza_centro", "Persone senza centro di costo", True),
    ("senza_capo", "Persone senza capo", True),
    ("scoperte", "Mansioni scoperte (nessun operativo)", True),
    ("uomo_solo", "Mansioni con poche persone (uomo solo)", True),
    ("concentrate", "Mansioni con carico concentrato", True),
    ("troppe", "Persone su troppe mansioni", True),
    ("chiave", "Persone chiave (unico operativo)", True),
    ("ruoli_scoperti", "Ruoli previsti senza nessuno nel reparto", True),
]


def _righe_kpi(prima: dict, dopo: dict, altro: dict | None = None) -> list[dict]:
    out = []
    for k, etichetta, _meno_e_meglio in KPI:
        p, d = prima["kpi"][k], dopo["kpi"][k]
        out.append({"chiave": k, "voce": etichetta, "prima": p, "dopo": d, "delta": d - p, "peggiora": d > p, "migliora": d < p,
                    "altro": altro["kpi"][k] if altro else None})
    return out


def _righe_centri(base: Base, prima: dict, dopo: dict, altro: dict | None = None) -> list[dict]:
    chiavi = {k for k in prima["per_centro"] if prima["per_centro"][k]["persone"] or prima["per_centro"][k]["reparti"]}
    chiavi |= {k for k in dopo["per_centro"] if dopo["per_centro"][k]["persone"] or dopo["per_centro"][k]["reparti"]}
    out = []
    for cid in sorted(chiavi, key=lambda c: (c is None, base.nome_centro(c).casefold())):
        p, d = prima["per_centro"][cid], dopo["per_centro"][cid]
        mp, md = _media(p["ore"]), _media(d["ore"])
        riga = {
            "voce": base.nome_centro(cid), "senza": cid is None, "persone_prima": len(p["persone"]), "persone_dopo": len(d["persone"]),
            "delta": len(d["persone"]) - len(p["persone"]), "reparti_prima": len(p["reparti"]), "reparti_dopo": len(d["reparti"]),
            "rml_prima": _euro(p["rml"]), "rml_dopo": _euro(d["rml"]), "rml_delta": _euro(d["rml"] - p["rml"]),
            "medio_prima": _euro(mp), "medio_dopo": _euro(md), "medio_delta": _euro(_delta(mp, md)),
            "persone_altro": len(altro["per_centro"][cid]["persone"]) if altro else None,
            "rml_altro": _euro(altro["per_centro"][cid]["rml"]) if altro else None,
        }
        riga["cambia"] = bool(riga["delta"] or riga["reparti_prima"] != riga["reparti_dopo"] or riga["rml_delta"])
        out.append(riga)
    return out


def _righe_reparti(base: Base, prima: dict, dopo: dict) -> list[dict]:
    chiavi = set(prima["per_area"]) | set(dopo["per_area"])
    out = []
    for aid in sorted(chiavi, key=lambda a: (a is None, base.nome_area(a).casefold())):
        p, d = prima["per_area"][aid], dopo["per_area"][aid]
        if p["persone"] == d["persone"]:
            continue
        mp, md = _media(p["ore"]), _media(d["ore"])
        out.append({
            "voce": base.nome_area(aid), "persone_prima": len(p["persone"]), "persone_dopo": len(d["persone"]),
            "delta": len(d["persone"]) - len(p["persone"]),
            "entrano": sorted(base.nome_persona(x) for x in d["persone"] - p["persone"]),
            "escono": sorted(base.nome_persona(x) for x in p["persone"] - d["persone"]),
            "rml_prima": _euro(p["rml"]), "rml_dopo": _euro(d["rml"]), "medio_prima": _euro(mp), "medio_dopo": _euro(md),
            "resta_vuoto": bool(p["persone"]) and not d["persone"],
        })
    return out


_GRAVITA = {"scoperta": 3, "nessun titolare": 3, "uomo solo": 2, "ok": 0}


def _righe_mansioni(base: Base, s_prima: Stato, s_dopo: Stato, prima: dict, dopo: dict, *, tutte: bool) -> list[dict]:
    out = []
    for mid, mans in base.mansioni.items():
        p, d = prima["per_mansione"][mid], dopo["per_mansione"][mid]
        cambia = (p["persone"] != d["persone"] or p["operativi"] != d["operativi"] or p["fte"] != d["fte"]
                  or s_prima.area_mansione.get(mid) != s_dopo.area_mansione.get(mid))
        problema_ora = d["stato"] != "ok" or d["concentrato"]
        if not cambia and not (tutte and problema_ora):
            continue
        out.append({
            "id": mid, "voce": mans.nome, "reparto_prima": base.nome_area(s_prima.area_mansione.get(mid)),
            "reparto_dopo": base.nome_area(s_dopo.area_mansione.get(mid)),
            "lista_prima": p["lista"], "lista_dopo": d["lista"], "operativi_prima": p["operativi"], "operativi_dopo": d["operativi"],
            "fte_prima": d_due(p["fte"]), "fte_dopo": d_due(d["fte"]),
            "conc_prima": p["concentrazione"], "conc_dopo": d["concentrazione"],
            "stato_prima": p["stato"], "stato_dopo": d["stato"], "concentrato_dopo": d["concentrato"],
            "peggiora": _GRAVITA.get(d["stato"], 0) > _GRAVITA.get(p["stato"], 0) or (d["concentrato"] and not p["concentrato"]),
            "migliora": _GRAVITA.get(d["stato"], 0) < _GRAVITA.get(p["stato"], 0) or (p["concentrato"] and not d["concentrato"]),
            "costo_prima": _euro(p["ora"] / p["fte"]) if p["fte"] else None, "costo_dopo": _euro(d["ora"] / d["fte"]) if d["fte"] else None,
            "rml_prima": _euro(p["rml"]), "rml_dopo": _euro(d["rml"]), "cambia": cambia,
        })
    out.sort(key=lambda r: (not r["peggiora"], not r["cambia"], -_GRAVITA.get(r["stato_dopo"], 0), r["voce"].casefold()))
    return out


def d_due(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _nome_capo(base: Base, capi: dict, pid) -> str:
    c = capi.get(pid)
    return base.nome_persona(c.legacy_id) if c and c.legacy_id else "nessuno"


def _righe_persone(base: Base, modifiche, s_prima: Stato, s_dopo: Stato, prima: dict, dopo: dict,
                   *, requisiti: bool, visite: bool) -> list[dict]:
    """Chi è toccato: chi cambia reparto, centro, ruolo o mansioni, e chi cambia capo di conseguenza."""
    from . import cambio_mansione

    toccati = {m.soggetto_id for m in modifiche if m.tipo in (M.PERSONA_REPARTO, M.PERSONA_RUOLO, M.PERSONA_MANSIONE)}
    for pid in base.dati.in_forza:
        if (base.centro_persona(s_prima, pid) != base.centro_persona(s_dopo, pid)
                or _nome_capo(base, prima["capi"], pid) != _nome_capo(base, dopo["capi"], pid)):
            toccati.add(pid)
    righe = []
    for pid in toccati & base.dati.in_forza:
        ap, ad = s_prima.area_di.get(pid), s_dopo.area_di.get(pid)
        rp, rd = s_prima.ruoli_di.get(pid, set()), s_dopo.ruoli_di.get(pid, set())
        mp, md = set(s_prima.abil.get(pid) or {}), set(s_dopo.abil.get(pid) or {})
        cap_p, cap_d = prima["capi"].get(pid), dopo["capi"].get(pid)
        # Mansioni del reparto nuovo previste dai suoi ruoli che non ha, e mansioni rimaste fuori dal reparto.
        da_assegnare, fuori = [], []
        if ad != ap and ad:
            for mid, area in s_dopo.area_mansione.items():
                if area == ad and mid not in md and {r.pk for r in base.mansioni[mid].ruoli.all()} & rd:
                    da_assegnare.append(base.mansioni[mid].nome)
            fuori = [base.mansioni[mid].nome for mid in md if s_dopo.area_mansione.get(mid) == ap and ap]
        c = base.costi.get(pid)
        avvisi = []
        if cap_d and cap_d.legacy_id and len(cap_d.alternative or []):
            avvisi.append(f"capo fra più candidati: approva {base.nome_persona(cap_d.legacy_id)}")
        if not (cap_d and cap_d.legacy_id) and (cap_p and cap_p.legacy_id):
            avvisi.append("resterebbe senza capo")
        if dopo["per_persona"][pid]["mansioni"] > prima["per_persona"][pid]["mansioni"] and pid in dopo["troppe"]:
            avvisi.append(f"su {dopo['per_persona'][pid]['mansioni']} mansioni")
        ruoli_fn = lambda ids: ", ".join(sorted(base.nome_ruolo(r) for r in ids)) or "—"  # noqa: E731
        riga = {
            "id": pid, "nome": base.nome_persona(pid),
            "modificata": any(m.soggetto_id == pid and m.tipo in (M.PERSONA_REPARTO, M.PERSONA_RUOLO, M.PERSONA_MANSIONE) for m in modifiche),
            "reparto_prima": base.nome_area(ap), "reparto_dopo": base.nome_area(ad), "cambia_reparto": ap != ad,
            "centro_prima": base.nome_centro(base.centro_persona(s_prima, pid)), "centro_dopo": base.nome_centro(base.centro_persona(s_dopo, pid)),
            "ruoli_prima": ruoli_fn(rp), "ruoli_dopo": ruoli_fn(rd), "cambia_ruoli": rp != rd,
            "capo_prima": _nome_capo(base, prima["capi"], pid), "capo_dopo": _nome_capo(base, dopo["capi"], pid),
            "cambia_capo": _nome_capo(base, prima["capi"], pid) != _nome_capo(base, dopo["capi"], pid),
            "mansioni_prima": len(mp), "mansioni_dopo": len(md),
            "mansioni_tolte": sorted(base.mansioni[x].nome for x in mp - md), "mansioni_nuove": sorted(base.mansioni[x].nome for x in md - mp),
            "da_assegnare": sorted(da_assegnare), "fuori_reparto": sorted(fuori), "avvisi": avvisi,
            "costo_orario": _euro(c.costo_orario) if c else None, "rml": _euro(c.rml) if c else None,
            "requisiti": None,
        }
        if requisiti and ap != ad and ad:
            mansione = (base.mansione_rischio.get(pid) or "").strip()
            if not mansione:
                riga["requisiti_nota"] = "Mansione di rischio non indicata: i requisiti non si possono confrontare."
            else:
                try:
                    conf = cambio_mansione.confronta(pid, mansione, area_nuova_id=ad, area_attuale_id=ap or None)
                    riga["requisiti"] = conf.as_dict(include_visite_dettaglio=visite)
                except Exception:
                    riga["requisiti_nota"] = "Requisiti non calcolabili per questa persona."
        righe.append(riga)
    righe.sort(key=lambda r: (not r["modificata"], r["nome"].casefold()))
    return righe


def _avvisi(base: Base, modifiche, righe_reparti, s_prima: Stato, s_dopo: Stato, prima: dict, dopo: dict) -> list[dict]:
    out = []
    for r in righe_reparti:
        if r["resta_vuoto"]:
            out.append({"livello": "warn", "testo": f"Il reparto {r['voce']} resterebbe senza persone."})
    nuovi = dopo["previsti_scoperti"] - prima["previsti_scoperti"]
    for aid, rid in sorted(nuovi, key=lambda x: (base.nome_area(x[0]), base.nome_ruolo(x[1]))):
        out.append({"livello": "warn", "testo": f"Nel reparto {base.nome_area(aid)} non resterebbe nessuno con il ruolo {base.nome_ruolo(rid)}, previsto dall'elenco."})
    for pid, mansioni in dopo["uniche"].items():
        nuove = set(mansioni) - set(prima["uniche"].get(pid, []))
        if nuove:
            nomi = ", ".join(sorted(base.mansioni[m].nome for m in nuove))
            out.append({"livello": "warn", "testo": f"{base.nome_persona(pid)} resterebbe l'unico operativo su: {nomi}."})
    for pid in sorted(dopo["troppe"] - prima["troppe"], key=base.nome_persona):
        out.append({"livello": "warn", "testo": f"{base.nome_persona(pid)} passerebbe a {dopo['per_persona'][pid]['mansioni']} mansioni."})
    # Chi lascia il reparto ma guida un'unità: il capo non cambia da solo.
    for m in modifiche:
        if m.tipo != M.PERSONA_REPARTO or problema(base, m):
            continue
        guida = []
        for mid, mans in base.mansioni.items():
            if mans.is_responsabilita and m.soggetto_id in {x for x in prima["per_mansione"][mid]["persone"]} and m.soggetto_id in dopo["per_mansione"][mid]["persone"]:
                guida.append(mans.nome)
        if guida:
            out.append({"livello": "info", "testo": f"{base.nome_persona(m.soggetto_id)} resta capo: conserva {', '.join(sorted(guida))}. Se non deve più esserlo, toglie la mansione a parte."})
    if base.cessati_in_lista:
        out.append({"livello": "info", "testo": f"{base.cessati_in_lista} assegnazioni di persone non più in forza sono ancora nelle liste delle mansioni: qui non contano, nei report di copertura sì."})
    return out


def costruisci(prospetto, *, altro=None, visite: bool = False, requisiti: bool = True) -> dict:
    """Tutto il prospetto: stessi calcoli su Oggi e su Dopo, e sull'altro prospetto se chiesto."""
    base = Base()
    modifiche = list(prospetto.modifiche.all())
    soglie = {"soglia_mansioni": base.config.soglia_mansioni_persona, "soglia_concentrazione": base.config.soglia_concentrazione}
    s_dopo = simula(base, modifiche)
    capi_prima = _mappa_capi(base, None)
    capi_dopo = _mappa_capi(base, s_dopo)
    prima = misure(base, base.stato, capi=capi_prima, **soglie)
    dopo = misure(base, s_dopo, capi=capi_dopo, **soglie)
    mis_altro = None
    if altro is not None:
        s_altro = simula(base, list(altro.modifiche.all()))
        mis_altro = misure(base, s_altro, capi=_mappa_capi(base, s_altro), **soglie)
    reparti = _righe_reparti(base, prima, dopo)
    return {
        "base": base,
        "righe_modifiche": [{"m": m, "testo": descrivi(base, m), "problema": problema(base, m)} for m in modifiche],
        "kpi": _righe_kpi(prima, dopo, mis_altro),
        "centri": _righe_centri(base, prima, dopo, mis_altro),
        "reparti": reparti,
        "mansioni": _righe_mansioni(base, base.stato, s_dopo, prima, dopo, tutte=False),
        "mansioni_critiche": _righe_mansioni(base, base.stato, s_dopo, prima, dopo, tutte=True),
        "persone": _righe_persone(base, modifiche, base.stato, s_dopo, prima, dopo, requisiti=requisiti, visite=visite),
        "avvisi": _avvisi(base, modifiche, reparti, base.stato, s_dopo, prima, dopo),
        "persone_su_troppe": sorted(
            ({"id": pid, "nome": base.nome_persona(pid), "n": dopo["per_persona"][pid]["mansioni"]} for pid in dopo["troppe"]),
            key=lambda x: (-x["n"], x["nome"].casefold())),
        "persone_chiave": sorted(
            ({"id": pid, "nome": base.nome_persona(pid), "mansioni": sorted(base.mansioni[m].nome for m in ms)} for pid, ms in dopo["uniche"].items()),
            key=lambda x: (-len(x["mansioni"]), x["nome"].casefold())),
        "totali": {"rml": _euro(prima["kpi"]["rml"]), "costo_medio": _euro(prima["kpi"]["costo_medio"]), "mese": base.mese,
                   "persone": len(base.dati.in_forza), "con_costo": len(base.costi), "uomo_solo": base.config.soglia_uomo_solo,
                   "soglia_concentrazione": base.config.soglia_concentrazione, "soglia_mansioni": base.config.soglia_mansioni_persona,
                   "somma_rml_dopo": _euro(sum((r["rml"] for r in dopo["per_centro"].values()), ZERO))},
        "senza_mansioni": {"prima": d_due(prima["senza_mansioni"]["fte"]), "dopo": d_due(dopo["senza_mansioni"]["fte"])},
        "ha_modifiche": bool(modifiche),
    }


def fotografia(ctx: dict) -> dict:
    """Quello che resta del confronto al momento di applicare: i numeri, non i calcoli."""
    return {
        "kpi": [{"voce": r["voce"], "prima": r["prima"], "dopo": r["dopo"]} for r in ctx["kpi"]],
        "centri": [{"voce": r["voce"], "persone_prima": r["persone_prima"], "persone_dopo": r["persone_dopo"]} for r in ctx["centri"] if r["cambia"]],
        "mese_costi": ctx["totali"]["mese"].isoformat() if ctx["totali"]["mese"] else "",
        "soglie": {k: ctx["totali"][k] for k in ("uomo_solo", "soglia_concentrazione", "soglia_mansioni")},
    }


# ── Applicare davvero ───────────────────────────────────────────────────────

def _applica_una(base: Base, m: M, prospetto, data, user) -> str:
    note = f"Prospetto «{prospetto.nome}»"[:500]
    if m.tipo == M.REPARTO_CENTRO:
        area = base.aree[m.soggetto_id]
        area.centro_di_costo = base.centri.get(m.destinazione_id)
        area.save(update_fields=["centro_di_costo"])
        return "centro di costo aggiornato"
    if m.tipo == M.MANSIONE_REPARTO:
        mans = base.mansioni[m.soggetto_id]
        mans.area = base.aree[m.destinazione_id]
        mans.save(update_fields=["area", "reparto"])
        return "mansione spostata"
    if m.tipo == M.PERSONA_REPARTO:
        from .assegnazioni import crea_assegnazione

        area = base.aree[m.destinazione_id]
        prima = base.stato.area_di.get(m.soggetto_id)
        crea_assegnazione(m.soggetto_id, data_inizio=data, reparto=area.reparto.nome, area_aziendale_id=area.pk, note=note, user=user)
        testo = "spostamento registrato" + ("" if data <= timezone.localdate() else f", dal {data:%d/%m/%Y}")
        if m.modo == M.LASCIA and prima != area.pk:
            da_togliere = _mansioni_da_lasciare(base.stato, m.soggetto_id, prima)
            if data > timezone.localdate():
                return testo + f"; {len(da_togliere)} mansioni del reparto di prima da togliere alla decorrenza, dal Mansionario"
            for mid in da_togliere:
                ab = AbilitazioneMacchina.objects.filter(pk=base.stato.abil[m.soggetto_id][mid].id_reale).first()
                if ab is not None:
                    togli(ab)
            testo += f"; tolte {len(da_togliere)} mansioni del reparto di prima"
        return testo
    if m.tipo == M.PERSONA_RUOLO:
        esito = ruoli_in_blocco.esegui([m.soggetto_id], ruolo=base.ruoli[m.destinazione_id], modo=m.modo, data=data, note=note, user=user, applica=True)[0]
        if esito.azione == "errore":
            raise ValueError(esito.dettaglio)
        return esito.dettaglio
    if m.tipo == M.PERSONA_MANSIONE:
        mans = base.mansioni[m.destinazione_id]
        if m.modo == M.TOGLI:
            sua = (base.stato.abil.get(m.soggetto_id) or {}).get(m.destinazione_id)
            if sua is None:
                return "non era in lista"
            ab = AbilitazioneMacchina.objects.filter(pk=sua.id_reale).first()
            if ab is not None:
                togli(ab)
            return "tolta dalla lista"
        ab = assegna(mans, legacy_anagrafica_id=m.soggetto_id, livello=m.livello or "U", user=user)
        return f"in lista a livello {ab.livello}"
    raise ValueError("modifica sconosciuta")


def applica(prospetto, *, data, user) -> Counter:
    """Registra ogni modifica sul percorso che userebbe la sua pagina; un errore non ferma le altre."""
    base = Base()
    conta: Counter = Counter()
    ctx = costruisci(prospetto, requisiti=False)
    prospetto.fotografia = fotografia(ctx)
    for m in prospetto.modifiche.all():
        ostacolo = problema(base, m)
        try:
            if ostacolo:
                raise ValueError(ostacolo)
            with transaction.atomic():
                m.esito = _applica_una(base, m, prospetto, data, user)[:500]
            m.esito_ok = True
            conta["ok"] += 1
        except Exception as exc:  # il motivo resta sulla riga e si mostra
            m.esito = (str(exc) or exc.__class__.__name__)[:500]
            m.esito_ok = False
            conta["errori"] += 1
        m.save(update_fields=["esito", "esito_ok"])
    capo_team.invalida_cache()
    prospetto.stato = prospetto.STATO_APPLICATO
    prospetto.applicato_il = timezone.now()
    prospetto.applicato_da = user if getattr(user, "is_authenticated", False) else None
    prospetto.decorrenza = data
    prospetto.save(update_fields=["stato", "applicato_il", "applicato_da", "decorrenza", "fotografia", "updated_at"])
    return conta

