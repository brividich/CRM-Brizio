"""Esplora la struttura: centro di costo → reparto → ruolo → mansione → competenza.

Una pagina sola per scendere, risalire e prendere altre strade. Il punto scelto sta
tutto nell'indirizzo, così ogni vista si può mandare con un link.

Qui «reparto» è l'area aziendale (vedi ``centri_costo_dati``). Le persone in forza e
la loro area sono quelle di «Reparti, aree e capi», con le stesse funzioni. Lo stesso
ruolo può stare in più reparti: per questo il percorso conserva il reparto da cui si
è arrivati, e le altre posizioni diventano una strada laterale.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from ..models import AreaAziendale, CentroDiCosto, DipendenteRuoloOperativo, RuoloOperativo
from ..models_skillmatrix import AbilitazioneMacchinaVoce, VoceMacchinaCatalogo
from . import capo_team, mansionario_struttura, struttura_vista
from .reparto_canonico import build_area_canonica_map

SENZA = 0  # valore nell'indirizzo per «Senza centro», «Senza reparto», «Senza ruolo»
LIVELLI = ("centro", "area", "ruolo", "mansione", "competenza")
ETICHETTE_SENZA = {"centro": "Senza centro di costo", "area": "Senza reparto", "ruolo": "Senza ruolo"}


def url(**percorso) -> str:
    """Indirizzo di un punto: ``None`` = livello non scelto, ``SENZA`` = la voce «Senza…»."""
    valori = {k: percorso[k] for k in LIVELLI if percorso.get(k) is not None}
    base = reverse("anagrafica:esplora_struttura")
    return f"{base}?{urlencode(valori)}" if valori else base


def _intero(valore) -> int | None:
    testo = str(valore if valore is not None else "").strip()
    return int(testo) if testo.isdigit() and len(testo) < 10 else None


def _quanti(n: int, uno: str, tanti: str) -> str:
    return f"{n} {uno if n == 1 else tanti}"


def _etichetta_ruolo(ruolo) -> str:
    return f"{ruolo.sigla} · {ruolo.nome}" if ruolo.sigla and ruolo.sigla != ruolo.nome else ruolo.nome


@dataclass
class Dati:
    """Tutta la struttura letta una volta: ogni colonna e ogni strada lavorano sugli stessi numeri."""

    aree: list = field(default_factory=list)
    centri: list = field(default_factory=list)
    mansioni: list = field(default_factory=list)
    in_forza: set = field(default_factory=set)
    area_di: dict = field(default_factory=dict)
    ruoli_di: dict = field(default_factory=dict)
    ruoli: dict = field(default_factory=dict)
    _carico: object = None

    @property
    def carico(self):
        """Carico sulle mansioni, letto una volta sola e solo se serve."""
        if self._carico is None:
            from .carico_mansioni import calcola

            self._carico = calcola()
        return self._carico

    @classmethod
    def carica(cls) -> "Dati":
        d = cls()
        d.centri = list(CentroDiCosto.objects.order_by("nome"))
        d.aree = list(AreaAziendale.objects.select_related("reparto", "centro_di_costo")
                      .prefetch_related("ruoli_reparto").order_by("nome"))
        d.mansioni = struttura_vista._mansioni()
        d.in_forza = set(capo_team.mappa_capi())
        d.area_di = {pid: a.pk for pid, a in build_area_canonica_map(list(d.in_forza)).items()}
        d.ruoli = {r.pk: r for r in RuoloOperativo.objects.all()}
        oggi = timezone.localdate()
        ruoli_di: dict[int, set] = defaultdict(set)
        for pid, rid in (DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
                         .values_list("legacy_anagrafica_id", "ruolo_id")):
            if pid in d.in_forza:
                ruoli_di[pid].add(rid)
        d.ruoli_di = ruoli_di
        return d

    # ── Reparti ──────────────────────────────────────────────────────────
    def persone_area(self, area_id: int) -> set:
        """Persone in forza del reparto; ``SENZA`` = in forza e senza area."""
        if area_id == SENZA:
            return {p for p in self.in_forza if p not in self.area_di}
        return {p for p, a in self.area_di.items() if a == area_id}

    def mansioni_area(self, area) -> list:
        """Mansioni del reparto, comprese le «Responsabilità» che lo governano."""
        if area is None:
            return [m for m in self.mansioni
                    if not m.area_id and not m.responsabilita_reparto_id and not m.responsabilita_area_id]
        return [m for m in self.mansioni
                if m.area_id == area.pk or m.responsabilita_area_id == area.pk
                or (area.reparto_id and m.responsabilita_reparto_id == area.reparto_id)]

    def aree_centro(self, centro_id: int) -> list:
        """Reparti del centro: quelli spenti solo se hanno ancora persone o mansioni."""
        out = []
        for a in self.aree:
            if (a.centro_di_costo_id or SENZA) != centro_id:
                continue
            if a.is_active or self.persone_area(a.pk) or self.mansioni_area(a):
                out.append(a)
        return out

    def ha_senza_area(self) -> bool:
        return bool(self.persone_area(SENZA) or self.mansioni_area(None))

    # ── Ruoli di un reparto ──────────────────────────────────────────────
    def ruoli_area(self, area) -> dict[int, dict]:
        """{id ruolo o SENZA: persone, mansioni, dichiarato}: da elenco, da persone o da mansioni."""
        area_id = area.pk if area is not None else SENZA
        out: dict[int, dict] = defaultdict(lambda: {"persone": set(), "mansioni": [], "dichiarato": False})
        if area is not None:
            for r in area.ruoli_reparto.all():
                out[r.pk]["dichiarato"] = True
        for pid in self.persone_area(area_id):
            for rid in self.ruoli_di.get(pid) or {SENZA}:
                out[rid]["persone"].add(pid)
        for m in self.mansioni_area(area):
            ruoli = list(m.ruoli.all())
            for r in ruoli:
                out[r.pk]["mansioni"].append(m)
            if not ruoli:
                out[SENZA]["mansioni"].append(m)
        return dict(out)

    def aree_del_ruolo(self, ruolo_id: int) -> list:
        """Tutti i reparti in cui il ruolo compare, con più persone prima."""
        righe = []
        for a in self.aree:
            info = self.ruoli_area(a).get(ruolo_id)
            if info:
                righe.append((a, info))
        righe.sort(key=lambda x: (-len(x[1]["persone"]), x[0].nome.casefold()))
        return righe

    def area_per_mansione(self, m):
        if m.area_id:
            return next((a for a in self.aree if a.pk == m.area_id), None)
        if m.responsabilita_area_id:
            return next((a for a in self.aree if a.pk == m.responsabilita_area_id), None)
        if m.responsabilita_reparto_id:
            return next((a for a in self.aree if a.reparto_id == m.responsabilita_reparto_id), None)
        return None

    def url_mansione(self, m, *, ruolo_id=None, competenza=None) -> str:
        area = self.area_per_mansione(m)
        if ruolo_id is None:
            primo = next(iter(m.ruoli.all()), None)
            ruolo_id = primo.pk if primo else SENZA
        return url(centro=(area.centro_di_costo_id or SENZA) if area else SENZA, area=area.pk if area else SENZA,
                   ruolo=ruolo_id, mansione=m.pk, competenza=competenza)


def _voce(id_, nome, *, sotto="", n=None, url_, scelta=False, avviso=False) -> dict:
    return {"id": id_, "nome": nome, "sotto": sotto, "n": n, "url": url_, "scelta": scelta, "avviso": avviso}


def _risolvi(d: Dati, params) -> dict:
    """Dall'indirizzo al percorso valido: completa i livelli sopra, scarta quelli che non tornano."""
    scelti = {k: _intero(params.get(k)) for k in LIVELLI}
    aree = {a.pk: a for a in d.aree}
    mansioni = {m.pk: m for m in d.mansioni}
    voce = None
    if scelti["competenza"]:
        voce = VoceMacchinaCatalogo.objects.select_related("catalogo", "corso", "qualifica", "processo_mpq").filter(
            pk=scelti["competenza"], attiva=True).first()
        if voce is None or (scelti["mansione"] is not None and voce.mansione_id != scelti["mansione"]):
            voce, scelti["competenza"] = None, None
        elif voce.mansione_id in mansioni:
            scelti["mansione"] = voce.mansione_id
        else:
            voce, scelti["competenza"] = None, None
    m = mansioni.get(scelti["mansione"]) if scelti["mansione"] else None
    if scelti["mansione"] and m is None:
        scelti["mansione"] = None
    # Entrando da una mansione o da un ruolo senza reparto, si sceglie il reparto che lo contiene.
    if m is not None and scelti["area"] is None:
        area_m = d.area_per_mansione(m)
        scelti["area"] = area_m.pk if area_m else SENZA
    if scelti["ruolo"] is None and m is not None:
        primo = next(iter(m.ruoli.all()), None)
        scelti["ruolo"] = primo.pk if primo else SENZA
    if scelti["ruolo"] and scelti["area"] is None:
        elenco = d.aree_del_ruolo(scelti["ruolo"])
        if elenco:
            scelti["area"] = elenco[0][0].pk
        else:
            scelti["ruolo"] = None
    area = None
    if scelti["area"] not in (None, SENZA):
        area = aree.get(scelti["area"])
        if area is None:
            scelti["area"] = None
    if area is not None:
        scelti["centro"] = area.centro_di_costo_id or SENZA
    elif scelti["area"] == SENZA:
        scelti["centro"] = SENZA
    if scelti["centro"] not in (None, SENZA) and not any(c.pk == scelti["centro"] for c in d.centri):
        scelti.update(centro=None, area=None)
    # Scendendo, ogni livello deve appartenere a quello sopra.
    if scelti["area"] is None:
        scelti.update(ruolo=None, mansione=None, competenza=None)
        m, voce = None, None
    info = None
    if scelti["ruolo"] is not None:
        info = d.ruoli_area(area).get(scelti["ruolo"])
        if info is None:
            scelti.update(ruolo=None, mansione=None, competenza=None)
            m, voce = None, None
    if m is not None and (info is None or m not in info["mansioni"]):
        scelti.update(mansione=None, competenza=None)
        m, voce = None, None
    if voce is None:
        scelti["competenza"] = None
    return {"scelti": scelti, "area": area, "info": info, "mansione": m, "voce": voce}


def _centri_colonna(d: Dati, scelti) -> list:
    voci = []
    for c in d.centri:
        aree = d.aree_centro(c.pk)
        if not c.is_active and not aree:
            continue
        persone = sum(len(d.persone_area(a.pk)) for a in aree)
        voci.append(_voce(c.pk, c.nome, sotto=_quanti(len(aree), "reparto", "reparti")
                          + ("" if c.is_active else " · non attivo"), n=persone, url_=url(centro=c.pk),
                          scelta=scelti["centro"] == c.pk))
    aree_senza = d.aree_centro(SENZA)
    if aree_senza or d.ha_senza_area():
        persone = sum(len(d.persone_area(a.pk)) for a in aree_senza) + len(d.persone_area(SENZA))
        voci.append(_voce(SENZA, ETICHETTE_SENZA["centro"], sotto=_quanti(len(aree_senza), "reparto", "reparti"),
                          n=persone, url_=url(centro=SENZA), scelta=scelti["centro"] == SENZA, avviso=True))
    return voci


def _aree_colonna(d: Dati, scelti) -> list:
    voci = [_voce(a.pk, a.nome, sotto=(f"in {a.reparto.nome}" if a.reparto_id else "senza reparto del portale")
                  + ("" if a.is_active else " · non attiva"),
                  n=len(d.persone_area(a.pk)), url_=url(centro=scelti["centro"], area=a.pk),
                  scelta=scelti["area"] == a.pk) for a in d.aree_centro(scelti["centro"])]
    if scelti["centro"] == SENZA and d.ha_senza_area():
        voci.append(_voce(SENZA, ETICHETTE_SENZA["area"], sotto="persone o mansioni senza area",
                          n=len(d.persone_area(SENZA)), url_=url(centro=SENZA, area=SENZA),
                          scelta=scelti["area"] == SENZA, avviso=True))
    return voci


def _ruoli_colonna(d: Dati, scelti, area) -> list:
    righe = []
    for rid, info in d.ruoli_area(area).items():
        ruolo = d.ruoli.get(rid)
        nome = _etichetta_ruolo(ruolo) if ruolo else ETICHETTE_SENZA["ruolo"]
        n_m = len(info["mansioni"])
        righe.append(_voce(rid, nome, sotto=_quanti(n_m, "mansione", "mansioni"), n=len(info["persone"]),
                           url_=url(centro=scelti["centro"], area=scelti["area"], ruolo=rid),
                           scelta=scelti["ruolo"] == rid, avviso=rid == SENZA))
    righe.sort(key=lambda v: (v["id"] == SENZA, v["nome"].casefold()))
    return righe


def _segnale_mansione(d: Dati, m) -> str:
    """«scoperta», «uomo solo», «carico concentrato»: vuoto se non c'è niente da guardare."""
    r = d.carico.per_mansione.get(m.pk)
    if r is None:
        return ""
    if r["stato"] != "ok":
        return r["stato"]
    return "carico concentrato" if r["concentrato"] else ""


def _kpi_da_guardare(d: Dati, mansioni_ids) -> tuple:
    n = d.carico.conteggi(mansioni_ids)["da_guardare"]
    return ("Mansioni da guardare", n, bool(n))


def _mansioni_colonna(d: Dati, scelti, info) -> list:
    voci = []
    conteggi = _conteggi_voci([m.pk for m in info["mansioni"]])
    for m in sorted(info["mansioni"], key=lambda x: x.nome.casefold()):
        n = conteggi.get(m.pk, 0)
        segnale = _segnale_mansione(d, m)
        voci.append(_voce(m.pk, m.nome, sotto=" · ".join(x for x in (_quanti(n, "competenza", "competenze"), segnale) if x),
                          url_=url(centro=scelti["centro"], area=scelti["area"], ruolo=scelti["ruolo"], mansione=m.pk),
                          scelta=scelti["mansione"] == m.pk, avviso=bool(segnale)))
    return voci


def _conteggi_voci(mansioni_ids) -> dict[int, int]:
    conteggi: dict[int, int] = defaultdict(int)
    for mid in VoceMacchinaCatalogo.objects.filter(mansione_id__in=list(mansioni_ids), attiva=True).values_list(
            "mansione_id", flat=True):
        conteggi[mid] += 1
    return conteggi


def _competenze_colonna(scelti, m) -> list:
    return [_voce(v.pk, v.nome, sotto=f"minimo {v.livello_minimo}" + (" · bloccante" if v.bloccante else ""),
                  url_=url(centro=scelti["centro"], area=scelti["area"], ruolo=scelti["ruolo"], mansione=m.pk, competenza=v.pk),
                  scelta=scelti["competenza"] == v.pk)
            for v in VoceMacchinaCatalogo.objects.filter(mansione=m, attiva=True).order_by("ordine", "nome")]


def _briciole(d: Dati, ris) -> list:
    s = ris["scelti"]
    out = [{"nome": "Tutti i centri di costo", "url": url()}]
    if s["centro"] is not None:
        c = next((x for x in d.centri if x.pk == s["centro"]), None)
        out.append({"livello": "Centro di costo", "nome": c.nome if c else ETICHETTE_SENZA["centro"],
                    "url": url(centro=s["centro"])})
    if s["area"] is not None:
        out.append({"livello": "Reparto", "nome": ris["area"].nome if ris["area"] else ETICHETTE_SENZA["area"],
                    "url": url(centro=s["centro"], area=s["area"])})
    if s["ruolo"] is not None:
        r = d.ruoli.get(s["ruolo"])
        out.append({"livello": "Ruolo", "nome": _etichetta_ruolo(r) if r else ETICHETTE_SENZA["ruolo"],
                    "url": url(centro=s["centro"], area=s["area"], ruolo=s["ruolo"])})
    if s["mansione"] is not None:
        out.append({"livello": "Mansione", "nome": ris["mansione"].nome,
                    "url": url(centro=s["centro"], area=s["area"], ruolo=s["ruolo"], mansione=s["mansione"])})
    if s["competenza"] is not None:
        out.append({"livello": "Competenza", "nome": ris["voce"].nome, "url": ""})
    out[-1]["url_corrente"] = True
    return out


def _persone(ids) -> list:
    nomi = struttura_vista._nomi(sorted(ids))
    righe = [{"id": i, "nome": nomi.get(i) or f"#{i}"} for i in ids]
    righe.sort(key=lambda p: p["nome"].casefold())
    return righe


def _dettaglio_radice(d: Dati) -> dict:
    n_voci = VoceMacchinaCatalogo.objects.filter(mansione__in=[m.pk for m in d.mansioni], attiva=True).count()
    con_voci = len(set(VoceMacchinaCatalogo.objects.filter(mansione__in=[m.pk for m in d.mansioni], attiva=True)
                       .values_list("mansione_id", flat=True)))
    senza_centro = [a for a in d.aree_centro(SENZA)]
    return {
        "tipo": "Tutta l'azienda", "titolo": "Da dove vuoi partire?",
        "kpi": [("Centri di costo", sum(1 for c in d.centri if c.is_active), False),
                ("Persone in forza", len(d.in_forza), False),
                ("Reparti senza centro", len(senza_centro), bool(senza_centro)),
                ("Mansioni attive", len(d.mansioni), False),
                ("Mansioni senza competenze", len(d.mansioni) - con_voci, len(d.mansioni) > con_voci),
                ("Competenze", n_voci, not n_voci)],
    }


def _dettaglio_centro(d: Dati, s) -> dict:
    c = next((x for x in d.centri if x.pk == s["centro"]), None)
    aree = d.aree_centro(s["centro"])
    ids = set().union(*[d.persone_area(a.pk) for a in aree]) if aree else set()
    if s["centro"] == SENZA:
        ids |= d.persone_area(SENZA)
    mansioni = {m.pk for a in aree for m in d.mansioni_area(a)}
    ruoli = {rid for a in aree for rid in d.ruoli_area(a) if rid != SENZA}
    return {
        "tipo": "Centro di costo", "titolo": c.nome if c else ETICHETTE_SENZA["centro"],
        "testo": c.descrizione if c else "Reparti non collegati a un centro di costo. La Direzione può restare qui.",
        "kpi": [("Reparti", len(aree), False), ("Persone", len(ids), False), ("Ruoli", len(ruoli), False),
                ("Mansioni", len(mansioni), False), _kpi_da_guardare(d, mansioni)],
        "persone": _persone(ids),
    }


def _dettaglio_area(d: Dati, s, area) -> dict:
    ids = d.persone_area(s["area"])
    ruoli = d.ruoli_area(area)
    return {
        "tipo": "Reparto", "titolo": area.nome if area else ETICHETTE_SENZA["area"],
        "testo": (f"Nel reparto del portale {area.reparto.nome}." if area and area.reparto_id
                  else ("Non è in un reparto del portale." if area else "Persone e mansioni senza area aziendale.")),
        "kpi": [("Persone", len(ids), False), ("Ruoli", sum(1 for r in ruoli if r != SENZA), False),
                ("Mansioni", len(d.mansioni_area(area)), False),
                _kpi_da_guardare(d, [m.pk for m in d.mansioni_area(area)])],
        "persone": _persone(ids),
    }


def _dettaglio_ruolo(d: Dati, s, area, info) -> dict:
    ruolo = d.ruoli.get(s["ruolo"])
    testo = ""
    if ruolo:
        pezzi = [ruolo.get_classe_display()] if ruolo.classe else []
        if info["dichiarato"]:
            pezzi.append("previsto per questo reparto nell'elenco aziendale")
        testo = " · ".join(pezzi)
    altri = []
    if ruolo:
        altri = [{"nome": a.nome, "sotto": f"{_quanti(len(i['persone']), 'persona', 'persone')} · {_quanti(len(i['mansioni']), 'mansione', 'mansioni')}",
                  "url": url(centro=a.centro_di_costo_id or SENZA, area=a.pk, ruolo=ruolo.pk)}
                 for a, i in d.aree_del_ruolo(ruolo.pk) if area is None or a.pk != area.pk]
    gerarchia = []
    if ruolo:
        def _posto(r, cosa):
            elenco = d.aree_del_ruolo(r.pk)
            qui = next((a for a, _i in elenco if area is not None and a.pk == area.pk), None)
            dove = qui or (elenco[0][0] if elenco else None)
            return {"nome": _etichetta_ruolo(r), "sotto": cosa,
                    "url": url(centro=dove.centro_di_costo_id or SENZA, area=dove.pk, ruolo=r.pk) if dove else ""}

        sopra = d.ruoli.get(ruolo.riporta_a_id) if ruolo.riporta_a_id else None
        if sopra:
            gerarchia.append(_posto(sopra, "riporta a"))
        gerarchia += [_posto(r, "gli riporta") for r in d.ruoli.values() if r.riporta_a_id == ruolo.pk and r.is_active]
    return {
        "tipo": "Ruolo", "titolo": _etichetta_ruolo(ruolo) if ruolo else ETICHETTE_SENZA["ruolo"], "testo": testo,
        "kpi": [("Persone qui", len(info["persone"]), False), ("Mansioni qui", len(info["mansioni"]), False)]
               + ([("Reparti con questo ruolo", len(altri) + (1 if area is not None else 0), False)] if ruolo else []),
        "persone": _persone(info["persone"]),
        "altri_reparti": altri, "gerarchia": gerarchia,
    }


def _kpi_carico_mansione(d: Dati, m) -> list:
    r = d.carico.per_mansione.get(m.pk)
    if r is None or m.is_responsabilita:
        return []
    carico = "—" if r["concentrazione"] is None else f"{r['concentrazione']}%"
    return [("Carico", carico, r["concentrato"]), ("Stato", r["stato"], r["stato"] != "ok")]


def _dettaglio_mansione(d: Dati, s, m) -> dict:
    persone = [p for p in mansionario_struttura.persone(m) if p["legacy_id"] in d.in_forza]
    altri = [{"nome": _etichetta_ruolo(r), "sotto": "stessa mansione sotto un altro ruolo",
              "url": d.url_mansione(m, ruolo_id=r.pk)} for r in m.ruoli.all() if r.pk != s["ruolo"]]
    n_voci = VoceMacchinaCatalogo.objects.filter(mansione=m, attiva=True).count()
    tecnico = []
    if m.asset_id:
        tecnico.append(("Macchina", str(m.asset)))
    if m.processo_sgi_id:
        tecnico.append(("Processo", str(m.processo_sgi)))
    rischi = [x.nome for x in m.mansioni_rischio.all()]
    if rischi:
        tecnico.append(("Mansioni di rischio", ", ".join(rischi)))
    return {
        "tipo": "Mansione", "titolo": m.nome, "dati": tecnico,
        "kpi": [("Persone in lista", len(persone), False),
                ("Operative", sum(1 for p in persone if p["operativa"]), False),
                ("Competenze", n_voci, not n_voci)] + _kpi_carico_mansione(d, m),
        "persone_titolo": "Persone in lista",
        "persone": [{"id": p["legacy_id"], "nome": p["nome"], "nota": f"livello {p['livello']}"
                     + ("" if p["operativa"] else " · non operativa")} for p in persone],
        "altri_ruoli": altri,
    }


def _dettaglio_competenza(d: Dati, voce) -> dict:
    valutazioni = list(AbilitazioneMacchinaVoce.objects.filter(
        voce=voce, abilitazione__in_lista=True).select_related("abilitazione"))
    valutazioni = [v for v in valutazioni if v.abilitazione.legacy_anagrafica_id in d.in_forza]
    nomi = struttura_vista._nomi([v.abilitazione.legacy_anagrafica_id for v in valutazioni])
    dati = [("Livello minimo", voce.get_livello_minimo_display()), ("Bloccante", "Sì" if voce.bloccante else "No")]
    if voce.corso_id:
        dati.append(("Corso richiesto", voce.corso.titolo))
    if voce.qualifica_id:
        dati.append(("Qualifica richiesta", voce.qualifica.nome))
    if voce.processo_mpq_id:
        dati.append(("Abilitazione MOD.128", voce.processo_mpq.nome))
    altre = []
    if voce.catalogo_id:
        mansioni = {m.pk: m for m in d.mansioni}
        for v in VoceMacchinaCatalogo.objects.filter(catalogo_id=voce.catalogo_id, attiva=True).exclude(pk=voce.pk):
            m = mansioni.get(v.mansione_id)
            if m is not None:
                altre.append({"nome": m.nome, "sotto": "stessa competenza su un'altra mansione",
                              "url": d.url_mansione(m, competenza=v.pk)})
    persone = [{"id": v.abilitazione.legacy_anagrafica_id,
                "nome": nomi.get(v.abilitazione.legacy_anagrafica_id) or f"#{v.abilitazione.legacy_anagrafica_id}",
                "nota": f"livello {v.livello}"} for v in valutazioni]
    persone.sort(key=lambda p: p["nome"].casefold())
    return {
        "tipo": "Competenza", "titolo": voce.nome, "testo": voce.descrizione, "dati": dati,
        "kpi": [("Persone valutate", len(persone), False), ("Altre mansioni", len(altre), False)],
        "persone": persone, "persone_titolo": "Persone valutate", "altre_mansioni": altre,
    }


def cerca(d: Dati, testo: str) -> list:
    """Tutti i punti della struttura il cui nome contiene il testo, senza limiti: si salta lì."""
    chiave = testo.casefold()
    out = []
    for c in d.centri:
        if chiave in c.nome.casefold():
            out.append({"livello": "Centro di costo", "nome": c.nome, "url": url(centro=c.pk)})
    for a in d.aree:
        if chiave in a.nome.casefold() and (a.is_active or d.persone_area(a.pk)):
            out.append({"livello": "Reparto", "nome": a.nome,
                        "url": url(centro=a.centro_di_costo_id or SENZA, area=a.pk)})
    for r in sorted(d.ruoli.values(), key=lambda x: x.nome.casefold()):
        if chiave in r.nome.casefold() or chiave in (r.sigla or "").casefold():
            elenco = d.aree_del_ruolo(r.pk)
            if elenco:
                a = elenco[0][0]
                out.append({"livello": "Ruolo", "nome": _etichetta_ruolo(r),
                            "url": url(centro=a.centro_di_costo_id or SENZA, area=a.pk, ruolo=r.pk)})
    mansioni = {m.pk: m for m in d.mansioni}
    for m in d.mansioni:
        if chiave in m.nome.casefold():
            out.append({"livello": "Mansione", "nome": m.nome, "url": d.url_mansione(m)})
    for v in VoceMacchinaCatalogo.objects.filter(attiva=True, mansione__in=list(mansioni), nome__icontains=testo):
        m = mansioni[v.mansione_id]
        out.append({"livello": "Competenza", "nome": f"{v.nome} ({m.nome})", "url": d.url_mansione(m, competenza=v.pk)})
    return out


def costruisci(params) -> dict:
    """Contesto della pagina per il punto indicato dall'indirizzo."""
    d = Dati.carica()
    ris = _risolvi(d, params)
    s, area, info, m, voce = ris["scelti"], ris["area"], ris["info"], ris["mansione"], ris["voce"]

    colonne = [{"livello": "centro", "titolo": "Centri di costo", "voci": _centri_colonna(d, s)}]
    colonne.append({"livello": "area", "titolo": "Reparti", "attesa": "Scegli un centro di costo",
                    "voci": _aree_colonna(d, s) if s["centro"] is not None else None})
    colonne.append({"livello": "ruolo", "titolo": "Ruoli", "attesa": "Scegli un reparto",
                    "voci": _ruoli_colonna(d, s, area) if s["area"] is not None else None})
    colonne.append({"livello": "mansione", "titolo": "Mansioni", "attesa": "Scegli un ruolo",
                    "voci": _mansioni_colonna(d, s, info) if info is not None else None})
    colonne.append({"livello": "competenza", "titolo": "Competenze", "attesa": "Scegli una mansione",
                    "voci": _competenze_colonna(s, m) if m is not None else None})
    # Da telefono si vede solo la colonna in cui scegliere: si risale con il percorso.
    ultima = max((i for i, c in enumerate(colonne) if c["voci"] is not None), default=0)
    for i, c in enumerate(colonne):
        c["corrente"] = i == ultima

    if voce is not None:
        det = _dettaglio_competenza(d, voce)
    elif m is not None:
        det = _dettaglio_mansione(d, s, m)
    elif info is not None:
        det = _dettaglio_ruolo(d, s, area, info)
    elif s["area"] is not None:
        det = _dettaglio_area(d, s, area)
    elif s["centro"] is not None:
        det = _dettaglio_centro(d, s)
    else:
        det = _dettaglio_radice(d)

    centro = next((c for c in d.centri if c.pk == s["centro"]), None)
    return {
        "colonne": colonne, "briciole": _briciole(d, ris), "dettaglio": det, "scelti": s, "centro_obj": centro,
        "area_obj": area, "ruolo_obj": d.ruoli.get(s["ruolo"]) if s["ruolo"] else None, "mansione_obj": m,
        "voce_obj": voce, "dati": d,
    }
