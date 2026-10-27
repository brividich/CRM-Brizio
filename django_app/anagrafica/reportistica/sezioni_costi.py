"""Sezioni di report sul costo orario (27/10/2026).

Tre viste dello stesso dato (``CostoOrarioMensile``: RML del cedolino ÷ giorni ÷ ore),
nel perimetro di persone del modello, solo con il permesso HR riservato:

- **Costo orario per persona**: il mese scelto, con RML, divisori e confronto col mese prima;
- **Costo orario ripartito**: per mansione, classificazione (D/I 1T/2T), reparto o area,
  pesando ogni persona con i coefficienti delle sue mansioni;
- **Andamento del costo orario**: mese per mese nel periodo, per tutta l'azienda o per gruppo.

Stessi numeri delle pagine «Costo orario» e «Storico» (``views_coefficienti``).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from report_conformita.registry import TONE_OK, TONE_WARN, Kpi

from .dati import Contesto, filtra_in
from .sezioni import GRUPPO_ORGANICO, INTERO, SCELTA, SI_NO, Importo, Opzione, Risultato, Sezione, _registra
from .sezioni_struttura import _mansioni_di, _per_persona

SENZA = "Senza mansioni"


def _solo_hr(request) -> bool:
    from anagrafica.views import _check_hr_permission

    return bool(_check_hr_permission(request))


def _euro(valore) -> Importo | None:
    return None if valore is None else Importo(Decimal(valore).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _pct(parte, totale) -> Decimal | None:
    return (Decimal(parte) / Decimal(totale) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if totale else None


def _scelte_mesi():
    from anagrafica.models import CostoOrarioMensile

    mesi = CostoOrarioMensile.objects.order_by("-mese").values_list("mese", flat=True).distinct()
    return (("", "Ultimo mese con dati"), *((m.isoformat(), m.strftime("%m/%Y")) for m in mesi))


def _costi(alias: dict[int, int], *, dal: date | None = None, al: date | None = None) -> dict[int, dict]:
    """id canonico → {mese: CostoOrarioMensile}; con più id per la stessa persona vince il primo trovato."""
    from anagrafica.models import CostoOrarioMensile

    qs = CostoOrarioMensile.objects.all()
    if dal:
        qs = qs.filter(mese__gte=dal)
    if al:
        qs = qs.filter(mese__lte=al)
    out: dict[int, dict] = defaultdict(dict)
    for c in filtra_in(qs, "legacy_anagrafica_id", alias):
        out[alias[c.legacy_anagrafica_id]].setdefault(c.mese, c)
    return out


def _mese_scelto(valore: str, costi: dict[int, dict]) -> date | None:
    if valore:
        try:
            return date.fromisoformat(valore)
        except ValueError:
            pass
    return max((m for v in costi.values() for m in v), default=None)


def _stato_di(stati: dict, p) -> dict:
    return next((stati[i] for i in p.tutti_gli_id if i in stati and stati[i]["n"]), None) or stati.get(p.id, {})


def _nota_formula() -> str:
    from anagrafica.services import costo_orario

    giorni, ore = costo_orario.divisori()
    g, h = (f"{x.normalize():f}".replace(".", ",") for x in (giorni, ore))
    return (f"Costo orario = RML del cedolino ÷ giorni ÷ ore al giorno (oggi {g} × {h}; ogni mese tiene i "
            "divisori con cui è stato calcolato). L'ultimo cedolino importato del mese vince; un RML inserito "
            "a mano vince su tutto.")


# ═══════════════════════════════════════════════════════════════════════════
# Costo orario per persona
# ═══════════════════════════════════════════════════════════════════════════

def _costo_orario_persone(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.services import mansioni_coefficienti as coeff

    res = Risultato()
    persone, alias = _per_persona(ctx)
    costi = _costi(alias)
    mese = _mese_scelto(o["mese"], costi)
    if mese is None:
        res.note = ["Nessun costo orario calcolato: servono i cedolini con la voce RML."]
        return res
    stati = coeff.stati(list(alias))
    valori_mese, mancanti, manuali = [], 0, 0
    for pid, p in sorted(persone.items(), key=lambda kv: kv[1].nominativo.casefold()):
        suoi = costi.get(pid, {})
        c = suoi.get(mese)
        st = _stato_di(stati, p)
        base = {"nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto, "area": p.area,
                "classificazione": st.get("classe_principale_label", ""), "mese": mese.strftime("%m/%Y")}
        if c is None:
            if o["mostra_mancanti"] and p.in_forza_al(mese):
                mancanti += 1
                res.riga({**base, "stato": "manca l'RML del mese"}, TONE_WARN)
            continue
        prima = max((m for m in suoi if m < mese), default=None)
        prec = suoi[prima].costo_orario if prima else None
        var = c.costo_orario - prec if prec is not None else None
        valori_mese.append(c.costo_orario)
        manuali += 1 if c.rml_manuale else 0
        res.riga({
            **base, "rml": _euro(c.rml), "giorni": c.divisore_giorni.normalize(), "ore": c.divisore_ore.normalize(),
            "costo_orario": _euro(c.costo_orario), "precedente": _euro(prec), "variazione": _euro(var),
            "variazione_pct": _pct(var, prec) if var is not None else None,
            "origine": "inserito a mano" if c.rml_manuale else "cedolino", "stato": "",
        })
    res.kpis = [Kpi("Persone con costo", len(valori_mese))]
    if valori_mese:
        res.kpis += [Kpi("Costo orario medio", f"{_euro(sum(valori_mese) / len(valori_mese))} €/h".replace(".", ",")),
                     Kpi("Minimo", f"{_euro(min(valori_mese))} €/h".replace(".", ",")),
                     Kpi("Massimo", f"{_euro(max(valori_mese))} €/h".replace(".", ","))]
    if o["mostra_mancanti"]:
        res.kpis.append(Kpi("In forza senza RML", mancanti, TONE_WARN if mancanti else TONE_OK))
    if manuali:
        res.kpis.append(Kpi("RML inserito a mano", manuali))
    res.note = [f"Mese {mese:%m/%Y}. «Variazione» rispetto all'ultimo mese precedente con un costo.", _nota_formula()]
    return res


_registra(Sezione(
    key="costo_orario_persone",
    titolo="Costo orario per persona",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Per persona il costo orario del mese (RML ÷ giorni ÷ ore), con RML, divisori e variazione sul "
                "mese prima. Solo HR.",
    builder=_costo_orario_persone,
    colonne=(("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"),
             ("area", "Area aziendale"), ("classificazione", "Classificazione"), ("mese", "Mese"),
             ("rml", "RML (€)"), ("giorni", "Giorni"), ("ore", "Ore al giorno"), ("costo_orario", "Costo orario (€/h)"),
             ("precedente", "Mese prima (€/h)"), ("variazione", "Variazione (€/h)"), ("variazione_pct", "Variazione (%)"),
             ("origine", "RML da"), ("stato", "Da sistemare")),
    predefinite=("nominativo", "reparto", "classificazione", "rml", "costo_orario", "variazione", "stato"),
    opzioni=(
        Opzione("mese", "Mese", SCELTA, _scelte_mesi, ""),
        Opzione("mostra_mancanti", "Anche chi è in forza senza RML nel mese", SI_NO, predefinito=False),
    ),
    permesso=_solo_hr,
    in_chat=False,
))


# ═══════════════════════════════════════════════════════════════════════════
# Costo orario ripartito sulle mansioni
# ═══════════════════════════════════════════════════════════════════════════

_PER = (("classificazione", "Classificazione (diretto / indiretto)"), ("mansione", "Mansione"),
        ("reparto", "Reparto della persona"), ("area", "Area aziendale della persona"))


def _quote(sue: list) -> list[tuple[object, Decimal]]:
    """(mansione, peso) con pesi che sommano 1: i coefficienti, normalizzati se la somma non torna."""
    contate = [ab for ab in sue if ab.stato == "attiva" and ab.coefficiente is not None]
    somma = sum((ab.coefficiente for ab in contate), Decimal(0))
    if not contate or somma <= 0:
        return [(None, Decimal(1))]
    return [(ab, ab.coefficiente / somma) for ab in contate]


def _costo_orario_ripartito(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.services.mansioni_coefficienti import CLASSIFICAZIONI

    res = Risultato()
    persone, alias = _per_persona(ctx)
    costi = _costi(alias)
    mese = _mese_scelto(o["mese"], costi)
    if mese is None:
        res.note = ["Nessun costo orario calcolato: servono i cedolini con la voce RML."]
        return res
    mansioni = _mansioni_di(alias)
    per = o["per"]
    acc: dict[str, dict] = defaultdict(lambda: {"persone": set(), "fte": Decimal(0), "ora": Decimal(0),
                                                "rml": Decimal(0)})
    n_persone, non_tornano = 0, 0
    for pid, p in persone.items():
        c = costi.get(pid, {}).get(mese)
        if c is None:
            continue
        n_persone += 1
        quote = _quote(mansioni.get(pid, []))
        attive = [ab for ab in mansioni.get(pid, []) if ab.stato == "attiva" and ab.coefficiente is not None]
        if attive and abs(sum(ab.coefficiente for ab in attive) - 1) > Decimal("0.001"):
            non_tornano += 1
        for ab, peso in quote:
            if per == "mansione":
                voce = ab.competenza.nome if ab else SENZA
            elif per == "classificazione":
                voce = (CLASSIFICAZIONI.get(ab.classificazione, "Non classificate") if ab and ab.classificazione
                        else ("Non classificate" if ab else SENZA))
            elif per == "area":
                voce = p.area or "Senza area"
            else:
                voce = p.reparto or "Senza reparto"
            a = acc[voce]
            a["persone"].add(pid)
            a["fte"] += peso
            a["ora"] += c.costo_orario * peso
            a["rml"] += c.rml * peso
    totale_rml = sum((a["rml"] for a in acc.values()), Decimal(0))
    ordine = list(CLASSIFICAZIONI.values()) + ["Non classificate", SENZA]
    for voce, a in sorted(acc.items(), key=lambda kv: (
            (ordine.index(kv[0]) if kv[0] in ordine else -1, "") if per == "classificazione"
            else (-kv[1]["rml"], kv[0].casefold()))):
        res.riga({
            "voce": voce, "persone": len(a["persone"]), "fte": a["fte"].quantize(Decimal("0.01")),
            "costo_medio": _euro(a["ora"] / a["fte"]) if a["fte"] else None, "costo_ora": _euro(a["ora"]),
            "rml": _euro(a["rml"]), "quota": _pct(a["rml"], totale_rml),
        }, TONE_WARN if voce in (SENZA, "Non classificate") else "")
    res.kpis = [Kpi("Persone con costo", n_persone), Kpi("Voci", len(acc)),
                Kpi("RML del mese ripartita", f"{_euro(totale_rml):,} €".replace(",", "X").replace(".", ",")
                    .replace("X", "."))]
    if non_tornano:
        res.kpis.append(Kpi("Coefficienti che non sommano 1", non_tornano, TONE_WARN))
    res.note = [
        f"Mese {mese:%m/%Y}. Ogni persona pesa 1 e si divide sulle sue mansioni secondo i coefficienti "
        "(in lista, attive): «Teste equivalenti» è la somma dei pesi, il costo medio è pesato.",
        "Chi non ha mansioni con coefficiente finisce in «Senza mansioni»; se i coefficienti di una persona "
        "non sommano 1 vengono riproporzionati.",
        _nota_formula(),
    ]
    return res


_registra(Sezione(
    key="costo_orario_ripartito",
    titolo="Costo orario per mansione e classificazione",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Costo orario e RML del mese ripartiti con i coefficienti per classificazione (diretto/indiretto "
                "1T/2T), mansione, reparto o area. Solo HR.",
    builder=_costo_orario_ripartito,
    colonne=(("voce", "Voce"), ("persone", "Persone"), ("fte", "Teste equivalenti"),
             ("costo_medio", "Costo orario medio (€/h)"), ("costo_ora", "Somma costi orari (€/h)"),
             ("rml", "RML ripartita (€)"), ("quota", "Quota RML (%)")),
    predefinite=("voce", "persone", "fte", "costo_medio", "rml", "quota"),
    opzioni=(
        Opzione("per", "Una riga per", SCELTA, _PER, "classificazione"),
        Opzione("mese", "Mese", SCELTA, _scelte_mesi, ""),
    ),
    permesso=_solo_hr,
    in_chat=False,
    nominativa=False,
))


# ═══════════════════════════════════════════════════════════════════════════
# Andamento del costo orario
# ═══════════════════════════════════════════════════════════════════════════

_GRUPPI_ANDAMENTO = (("", "Tutta l'azienda"), ("reparto", "Reparto"), ("area", "Area aziendale"),
                     ("classificazione", "Classificazione prevalente"))


def _costo_orario_andamento(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.services import mansioni_coefficienti as coeff

    res = Risultato()
    persone, alias = _per_persona(ctx)
    dal, al = ctx.date_from.replace(day=1), ctx.date_to
    costi = _costi(alias, dal=dal, al=al)
    per = o["per"]
    stati = coeff.stati(list(alias)) if per == "classificazione" else {}
    serie: dict[str, dict[date, list]] = defaultdict(lambda: defaultdict(list))
    for pid, valori in costi.items():
        p = persone[pid]
        if per == "reparto":
            gruppo = p.reparto or "Senza reparto"
        elif per == "area":
            gruppo = p.area or "Senza area"
        elif per == "classificazione":
            gruppo = _stato_di(stati, p).get("classe_principale_label") or "Non classificate"
        else:
            gruppo = "Tutta l'azienda"
        for m, c in valori.items():
            serie[gruppo][m].append(c)
    mesi = sorted({m for g in serie.values() for m in g})
    if not mesi:
        res.note = [f"Nessun costo orario nel periodo {ctx.periodo_label}."]
        return res
    for gruppo in sorted(serie, key=str.casefold):
        prec = None
        for m in mesi:
            righe = serie[gruppo].get(m)
            if not righe:
                continue
            valori = [c.costo_orario for c in righe]
            media = sum(valori) / len(valori)
            var = media - prec if prec is not None else None
            res.riga({
                "mese": m.strftime("%m/%Y"), "gruppo": gruppo, "persone": len(valori), "media": _euro(media),
                "minimo": _euro(min(valori)), "massimo": _euro(max(valori)),
                "variazione": _euro(var), "variazione_pct": _pct(var, prec) if var is not None else None,
                "rml": _euro(sum(c.rml for c in righe)),
            }, TONE_WARN if var is not None and var > 0 and prec and _pct(var, prec) >= o["soglia"] else "")
            prec = media
    tutte = defaultdict(list)
    for g in serie.values():
        for m, righe in g.items():
            tutte[m].extend(c.costo_orario for c in righe)
    prima, ultima = (sum(tutte[mesi[0]]) / len(tutte[mesi[0]]), sum(tutte[mesi[-1]]) / len(tutte[mesi[-1]]))
    res.kpis = [Kpi("Mesi", len(mesi)),
                Kpi(f"Media {mesi[0]:%m/%Y}", f"{_euro(prima)} €/h".replace(".", ",")),
                Kpi(f"Media {mesi[-1]:%m/%Y}", f"{_euro(ultima)} €/h".replace(".", ","))]
    if len(mesi) > 1:
        var_pct = _pct(ultima - prima, prima)
        res.kpis.append(Kpi("Variazione nel periodo", f"{var_pct:+}%".replace(".", ","),
                            TONE_WARN if var_pct is not None and var_pct >= o["soglia"] else TONE_OK))
    res.note = [
        f"Periodo {ctx.periodo_label}: una riga per mese e gruppo; «Variazione» sulla media del mese prima "
        f"nello stesso gruppo, in arancione gli aumenti dal {o['soglia']}% in su.",
        _nota_formula(),
    ]
    if per == "classificazione":
        res.note.append("La classificazione è quella prevalente di oggi, non quella del mese.")
    return res


_registra(Sezione(
    key="costo_orario_andamento",
    titolo="Andamento del costo orario",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Mese per mese nel periodo: costo orario medio, minimo e massimo, variazione e RML, per tutta "
                "l'azienda, reparto, area o classificazione. Solo HR.",
    builder=_costo_orario_andamento,
    colonne=(("mese", "Mese"), ("gruppo", "Gruppo"), ("persone", "Persone"), ("media", "Media (€/h)"),
             ("minimo", "Minimo (€/h)"), ("massimo", "Massimo (€/h)"), ("variazione", "Variazione (€/h)"),
             ("variazione_pct", "Variazione (%)"), ("rml", "RML totale (€)")),
    predefinite=("mese", "gruppo", "persone", "media", "variazione", "variazione_pct"),
    opzioni=(
        Opzione("per", "Raggruppa i mesi per", SCELTA, _GRUPPI_ANDAMENTO, ""),
        Opzione("soglia", "Evidenzia aumenti mensili da (%)", INTERO, predefinito=3, minimo=1, massimo=100),
    ),
    permesso=_solo_hr,
    in_chat=False,
    nominativa=False,
    usa_periodo=True,
))
