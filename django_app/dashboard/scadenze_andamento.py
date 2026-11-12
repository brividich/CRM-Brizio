"""Vista «Andamento» dello scadenzario: numeri delle fotografie giornaliere
(``scadenzario.FotoScadenze``, schedule ``scadenzario_foto_giornaliera``).

Grafico a linee in SVG costruito qui (niente librerie JS): due serie con la
stessa unità (numero di scadenze), un solo asse, etichette dirette a fine linea.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from .scadenze_providers import PROVIDERS, SOURCE_LABELS

GIORNI = 365
_W, _H = 960, 280
_ML, _MR, _MT, _MB = 44, 120, 16, 30
_MESI_BREVI = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")


def _n(v: float) -> str:
    """Coordinata SVG come testo con il punto: il template la localizzerebbe con la virgola."""
    return f"{v:.1f}"


def _passo(massimo: int) -> int:
    """Passo «tondo» (1, 2, 5 × 10^k) per circa quattro tacche."""
    grezzo = max(1, massimo) / 4
    esp = 10 ** math.floor(math.log10(grezzo))
    for m in (1, 2, 5, 10):
        if grezzo <= m * esp:
            return max(1, int(m * esp))
    return max(1, int(10 * esp))


def _valore_al(serie: dict[date, int], giorno: date):
    """Il valore dell'ultima fotografia non successiva al giorno (None se non c'è)."""
    date_ok = [d for d in serie if d <= giorno]
    return serie[max(date_ok)] if date_ok else None


def andamento(oggi: date) -> dict:
    from scadenzario.models import FotoScadenze

    righe = list(FotoScadenze.objects.filter(data__gte=oggi - timedelta(days=GIORNI)).order_by("data"))
    if not righe:
        return {"vuoto": True}

    scadute: dict[date, int] = defaultdict(int)
    entro30: dict[date, int] = defaultdict(int)
    per_fonte: dict[str, dict[date, int]] = defaultdict(dict)
    for r in righe:
        scadute[r.data] += r.scadute
        entro30[r.data] += r.entro_30
        per_fonte[r.fonte][r.data] = r.scadute
    date_ord = sorted(scadute)
    prima, ultima = date_ord[0], date_ord[-1]

    massimo = max(max(scadute.values()), max(entro30.values()), 1)
    passo = _passo(massimo)
    ymax = passo * math.ceil(massimo / passo)
    larg = _W - _ML - _MR
    alt = _H - _MT - _MB
    span = max(1, (ultima - prima).days)

    def x(d: date) -> float:
        if prima == ultima:
            return _ML + larg / 2
        return _ML + (d - prima).days / span * larg

    def y(v: int) -> float:
        return _MT + alt - v / ymax * alt

    def serie(valori: dict[date, int], codice: str, nome: str) -> dict:
        punti = [{"x": _n(x(d)), "y": _n(y(valori[d])), "v": valori[d],
                  "titolo": f"{d:%d/%m/%Y} · {nome}: {valori[d]}"} for d in date_ord]
        path = " ".join(("M" if i == 0 else "L") + f"{p['x']},{p['y']}" for i, p in enumerate(punti))
        ultimo = punti[-1]
        return {"codice": codice, "nome": nome, "punti": punti, "path": path,
                "etichetta_x": float(ultimo["x"]) + 10, "etichetta_y": float(ultimo["y"]) + 4, "ultimo": ultimo["v"]}

    s1 = serie(scadute, "scadute", "Scadute")
    s2 = serie(entro30, "entro30", "Entro 30 giorni")
    # Etichette dirette che non si sovrappongono.
    if abs(s1["etichetta_y"] - s2["etichetta_y"]) < 14:
        if s1["etichetta_y"] <= s2["etichetta_y"]:
            s2["etichetta_y"] = s1["etichetta_y"] + 14
        else:
            s1["etichetta_y"] = s2["etichetta_y"] + 14

    for s_ in (s1, s2):
        s_["etichetta_x"], s_["etichetta_y"] = _n(s_["etichetta_x"]), _n(s_["etichetta_y"])
    tacche = [{"v": v, "y": _n(y(v))} for v in range(0, ymax + 1, passo)]
    mesi = []
    d = date(prima.year, prima.month, 1)
    while d <= ultima:
        if d >= prima:
            mesi.append({"x": _n(x(d)), "nome": f"{_MESI_BREVI[d.month - 1]}{' ' + str(d.year) if d.month == 1 else ''}"})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)

    tabella = []
    for fonte in PROVIDERS:
        valori = per_fonte.get(fonte)
        if not valori:
            continue
        oggi_v = _valore_al(valori, ultima)
        v30 = _valore_al(valori, ultima - timedelta(days=30))
        v90 = _valore_al(valori, ultima - timedelta(days=90))
        if not any((oggi_v, v30, v90)):
            continue
        tabella.append({"fonte": fonte, "etichetta": SOURCE_LABELS.get(fonte, fonte), "oggi": oggi_v,
                        "v30": v30, "v90": v90,
                        "delta30": (oggi_v - v30) if v30 is not None and oggi_v is not None else None})
    tabella.sort(key=lambda r: -(r["oggi"] or 0))

    tot30 = _valore_al(dict(scadute), ultima - timedelta(days=30))
    return {
        "vuoto": False, "prima": prima, "ultima": ultima, "n_foto": len(date_ord),
        "w": str(_W), "h": str(_H), "ml": str(_ML), "ml_testo": str(_ML - 8), "x_fine": str(_W - _MR),
        "y_base": _n(_MT + alt), "y_mesi": _n(_MT + alt + 18),
        "serie": [s1, s2], "tacche": tacche, "mesi": mesi, "tabella": tabella,
        "scadute_oggi": scadute[ultima], "entro30_oggi": entro30[ultima],
        "delta30": (scadute[ultima] - tot30) if tot30 is not None else None,
    }
