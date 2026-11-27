"""Statistica di processo (SPC) delle quote CMM: un solo posto per le formule.

Le usano analisi delle quote, scheda P/N, report, Quote CMM e catalogo; ``static/produzione/js/spc.js`` è la stessa
cosa per Analisi quote (che ricalcola nel browser coi filtri) e ``tests_spc.py`` controlla che diano gli stessi
numeri. Solo Python standard: le serie sono corte (al massimo qualche centinaio di pezzi).

Regole principali:
- σ di breve periodo = media delle escursioni mobili / 1,128 (carta I-MR): dà **Cp e Cpk**, la capacità della
  macchina; la σ di tutti i pezzi dà **Pp e Ppk**, quello che il processo ha fatto davvero nel tempo.
- Quote con solo limite superiore (forma, posizione: nominale 0, limite inferiore 0) non sono normali: indice col
  metodo dei percentili (ISO 22514-2) su una Weibull, Ppk = (LS − mediana) / (P99,865 − mediana).
- Un solo giudizio (``verdetto``): l'indice (il peggiore fra Cpk e Ppk) contro 1,33 e 1,00; sotto 25 pezzi «pochi
  dati». L'intervallo di confidenza al 95% (Bissell) si mostra come informazione, non decide.
- Una sola finestra di riferimento (``FINESTRA`` pezzi, impostabile) e un solo «da guardare» (``da_guardare``).
- Limiti di controllo = media ± 3σ di breve periodo; regole di Nelson 1-8 e EWMA (λ 0,2) per gli spostamenti piccoli.
"""
from __future__ import annotations

import math

D2 = 1.128                 # costante d2 per escursioni mobili di 2 punti
CAPACE = 1.33
AL_LIMITE = 1.0
MIN_CAPACITA = 5           # punti minimi per un indice
POCHI_DATI = 25            # sotto: indice mostrato ma verdetto «pochi dati»
P_ALTO = 0.99865           # ±3σ della normale
EWMA_LAMBDA = 0.2
EWMA_L = 3.0
FINESTRA = 30              # pezzi su cui si calcolano gli indici di riferimento (Impostazioni: FINESTRE)
FINESTRE = (30, 50, 100)
TOLLERANZA_AL_LIMITE = 0.80   # una misura oltre l'80% della tolleranza è «al limite»


# --- base -------------------------------------------------------------------------------------------------

def media(xs):
    return sum(xs) / len(xs) if xs else None


def dev_std(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def sigma_breve(xs):
    """σ di breve periodo dalle escursioni mobili fra pezzi consecutivi (MR̄ / d2)."""
    if len(xs) < 2:
        return 0.0
    mr = [abs(xs[i] - xs[i - 1]) for i in range(1, len(xs))]
    return (sum(mr) / len(mr)) / D2


def unilaterale(nominale, lsl, usl):
    return abs(nominale or 0) < 1e-12 and abs(lsl) < 1e-12 and usl > 0


def phi(z):
    """Funzione di ripartizione della normale standard."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# --- Weibull per le quote di forma e posizione ------------------------------------------------------------

def weibull(xs):
    """Stima di massima verosimiglianza (forma k, scala λ) per valori positivi; ``None`` se non si può.
    I valori a zero (misura sotto la risoluzione) diventano metà del più piccolo positivo."""
    pos = [x for x in xs if x > 0]
    if len(pos) < MIN_CAPACITA or len(set(pos)) < 3:
        return None
    minimo = min(pos) / 2
    v = [x if x > 0 else minimo for x in xs]
    ln = [math.log(x) for x in v]
    mln = sum(ln) / len(ln)

    def f(k):
        xk = [x ** k for x in v]
        return sum(a * b for a, b in zip(xk, ln)) / sum(xk) - 1 / k - mln

    lo, hi = 0.05, 60.0
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(80):                       # bisezione: f cresce con k
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    k = (lo + hi) / 2
    lam = (sum(x ** k for x in v) / len(v)) ** (1 / k)
    return {"k": k, "lam": lam}


def weibull_quantile(w, p):
    return w["lam"] * (-math.log(1 - p)) ** (1 / w["k"])


# --- capacità ---------------------------------------------------------------------------------------------

def intervallo_cpk(cpk, n, z=1.96):
    """Intervallo di confidenza approssimato (Bissell) di un Cpk stimato su ``n`` pezzi."""
    if cpk is None or n < 2:
        return None, None
    se = math.sqrt(1 / (9 * n) + cpk ** 2 / (2 * (n - 1)))
    return cpk - z * se, cpk + z * se


def verdetto(indice, n):
    """L'unico giudizio di capacità del modulo: «capace» (indice ≥ 1,33), «al limite» (≥ 1,00), «non capace»;
    «pochi dati» sotto 25 pezzi. ``indice`` = il peggiore fra Cpk e Ppk."""
    if indice is None:
        return None
    if n < POCHI_DATI:
        return "pochi dati"
    return "capace" if indice >= CAPACE else ("al limite" if indice >= AL_LIMITE else "non capace")


SOTTO_OBIETTIVO = ("al limite", "non capace")


def da_guardare(fuori_ultimo, deriva, verdetto_) -> bool:
    """L'unica regola di «quota da guardare»: fuori nell'ultimo report, in deriva o sotto l'obiettivo di capacità."""
    return bool(fuori_ultimo or deriva or verdetto_ in SOTTO_OBIETTIVO)


def capacita(xs, lsl, usl, nominale=None):
    """Media, σ (totale e di breve periodo), Cp/Cpk, Pp/Ppk, intervallo del Cpk e verdetto di una serie dal più
    vecchio. ``metodo`` = «normale» o «percentili» (quote di forma e posizione)."""
    n = len(xs)
    out = {"n": n, "media": media(xs), "sd": dev_std(xs), "sigma_breve": sigma_breve(xs), "cp": None, "cpk": None,
           "pp": None, "ppk": None, "cpk_basso": None, "cpk_alto": None, "metodo": "normale", "verdetto": None,
           "indice": None}
    banda = usl - lsl
    if n < MIN_CAPACITA or banda <= 0:
        return out
    m, sd, sb = out["media"], out["sd"], out["sigma_breve"] or out["sd"]
    if unilaterale(nominale, lsl, usl):
        w = weibull(xs)
        if w:
            x50, xa = weibull_quantile(w, 0.5), weibull_quantile(w, P_ALTO)
            if xa > x50:
                out.update(metodo="percentili", ppk=(usl - x50) / (xa - x50), weibull=w)
                # Cpk: stessa distribuzione con la dispersione di breve periodo (rapporto σ breve / σ totale)
                r = (sb / sd) if sd > 0 else 1.0
                out["cpk"] = (usl - x50) / ((xa - x50) * r) if r > 0 else out["ppk"]
        if out["ppk"] is None and sd > 0:
            out["ppk"] = (usl - m) / (3 * sd)
            out["cpk"] = (usl - m) / (3 * sb) if sb > 0 else None
    else:
        if sb > 0:
            out["cp"] = banda / (6 * sb)
            out["cpk"] = min(usl - m, m - lsl) / (3 * sb)
        if sd > 0:
            out["pp"] = banda / (6 * sd)
            out["ppk"] = min(usl - m, m - lsl) / (3 * sd)
    # indice per classifiche e conteggi: il peggiore fra Cpk e Ppk (un processo che si sposta non è capace)
    valori = [v for v in (out["cpk"], out["ppk"]) if v is not None]
    out["indice"] = min(valori) if valori else None
    out["cpk_basso"], out["cpk_alto"] = intervallo_cpk(out["indice"], n)
    out["verdetto"] = verdetto(out["indice"], n)
    return out


# --- carta di controllo -----------------------------------------------------------------------------------

BASE_MIN = 15              # pezzi minimi della base congelata dei limiti di controllo


def base_controllo(n):
    """Quanti pezzi (i primi) fanno la base congelata dei limiti di controllo: la prima metà, almeno 15; con meno di
    25 pezzi tutti. Così uno spostamento recente non allarga i limiti che dovrebbero rivelarlo."""
    return n if n < POCHI_DATI else max(BASE_MIN, n // 2)


def _base(xs, base):
    """I pezzi di base: i primi ``base`` se bastano e hanno dispersione, altrimenti tutti."""
    if base and 2 <= base < len(xs) and sigma_breve(xs[:base]) > 0:
        return xs[:base]
    return xs


def limiti_controllo(xs, base=None):
    """Carta dei singoli: centro, LCS e LCI (media ± 3σ di breve periodo), e LCS delle escursioni mobili. Con ``base``
    i limiti vengono dai primi ``base`` pezzi (base congelata) e valgono per tutta la serie."""
    if len(xs) < 2:
        return None
    b = _base(xs, base)
    m, sb = media(b), sigma_breve(b)
    return {"centro": m, "lcs": m + 3 * sb, "lci": m - 3 * sb, "sigma": sb, "mr_lcs": 3.267 * sb * D2, "base": len(b)}


def tratto_tolleranza(limiti, eps=1e-6):
    """``limiti`` = [(limite inferiore, limite superiore)] dal più vecchio: indice del primo punto del tratto finale
    che ha la tolleranza dell'ultima misura (0 = non è mai cambiata)."""
    if not limiti:
        return 0
    l0, u0 = limiti[-1]
    i = len(limiti)
    while i > 0 and abs(limiti[i - 1][0] - l0) <= eps and abs(limiti[i - 1][1] - u0) <= eps:
        i -= 1
    return i


def stato_processo(deriva_, cambi, segnali_, n):
    """Una sola lettura del processo dai rivelatori: «deriva», «spostato» (la media è cambiata), «segnali»,
    «pochi» (meno di 25 pezzi), «stabile»."""
    if deriva_:
        return "deriva"
    if cambi:
        return "spostato"
    if segnali_:
        return "segnali"
    return "pochi" if n < POCHI_DATI else "stabile"


def _finestre(flag_fine, lung):
    """Unisce le finestre [i-lung+1, i] segnalate in tratti continui."""
    tratti = []
    for i in flag_fine:
        da = max(0, i - lung + 1)
        if tratti and da <= tratti[-1][1] + 1:
            tratti[-1][1] = i
        else:
            tratti.append([da, i])
    return tratti


def ewma(xs, centro, sigma, lam=EWMA_LAMBDA, L=EWMA_L):
    """Valori EWMA e allarmi (indici fuori dai limiti, con il verso)."""
    z, valori, allarmi = centro, [], []
    for i, x in enumerate(xs):
        z = lam * x + (1 - lam) * z
        valori.append(z)
        lim = L * sigma * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * (i + 1))))
        if sigma > 0 and abs(z - centro) > lim:
            allarmi.append((i, z > centro))
    return valori, allarmi


TESTI_REGOLE = {
    1: ("Oltre 3σ", "misura anomala anche se in tolleranza: verificare il pezzo"),
    2: ("9 punti dallo stesso lato", "la media si è spostata: piazzamento, utensile o correttore"),
    3: ("6 punti in salita o discesa", "tendenza costante: usura o deriva termica"),
    4: ("14 punti a zig-zag", "due cause che si alternano: due mandrini, due pallet, due operatori"),
    5: ("2 su 3 oltre 2σ", "spostamento in arrivo"),
    6: ("4 su 5 oltre 1σ", "piccolo spostamento della media"),
    7: ("15 punti vicini alla media", "variabilità più bassa del solito: controllare misura o limiti"),
    8: ("8 punti lontani dalla media", "due popolazioni mescolate: due macchine o due lotti"),
    "ewma": ("Spostamento (EWMA)", "piccolo spostamento persistente, visto prima che diventi deriva"),
}


def segnali(xs, base=None):
    """Regole di Nelson 1-8 sulla carta dei singoli (centro = media, σ di breve periodo; con ``base`` quelle dei primi
    ``base`` pezzi, come ``limiti_controllo``) ed EWMA rispetto alla prima metà della serie.
    ``[{"regola", "da", "a", "sopra"?}]`` con gli indici della serie."""
    n = len(xs)
    if n < 9:
        return []
    b = _base(xs, base)
    m, s = media(b), sigma_breve(b)
    if s <= 0:
        return []
    z = [(x - m) / s for x in xs]
    out = []
    out += [{"regola": 1, "da": i, "a": i, "sopra": z[i] > 0} for i in range(n) if abs(z[i]) > 3]

    def corse(cond_lato, lung, regola):
        i = 0
        while i < n:
            lato = cond_lato(i)
            if lato is None:
                i += 1
                continue
            j = i
            while j + 1 < n and cond_lato(j + 1) == lato:
                j += 1
            if j - i + 1 >= lung:
                out.append({"regola": regola, "da": i, "a": j, "sopra": lato})
            i = j + 1

    corse(lambda i: (z[i] > 0) if z[i] != 0 else None, 9, 2)
    # 3: 6 punti di fila in salita o discesa
    i = 0
    while i < n - 1:
        if xs[i + 1] == xs[i]:
            i += 1
            continue
        su = xs[i + 1] > xs[i]
        j = i
        while j + 1 < n and ((xs[j + 1] > xs[j]) if su else (xs[j + 1] < xs[j])):
            j += 1
        if j - i + 1 >= 6:
            out.append({"regola": 3, "da": i, "a": j, "sopra": su})
        i = max(j, i + 1)
    # 4: 14 punti che si alternano su e giù
    segni = [1 if xs[k + 1] > xs[k] else (-1 if xs[k + 1] < xs[k] else 0) for k in range(n - 1)]
    k = 0
    while k < len(segni):
        j = k
        while j + 1 < len(segni) and segni[j] != 0 and segni[j + 1] == -segni[j]:
            j += 1
        if j - k + 2 >= 14:
            out.append({"regola": 4, "da": k, "a": j + 1})
        k = j + 1
    # 5 e 6: k su m oltre 2σ / 1σ dallo stesso lato
    for regola, quanti, finestra, soglia in ((5, 2, 3, 2.0), (6, 4, 5, 1.0)):
        for lato in (True, False):
            fine = [i for i in range(finestra - 1, n)
                    if sum(1 for t in range(i - finestra + 1, i + 1) if (z[t] > soglia if lato else z[t] < -soglia)) >= quanti]
            out += [{"regola": regola, "da": a, "a": b, "sopra": lato} for a, b in _finestre(fine, finestra)]
    # 7: 15 di fila entro 1σ; 8: 8 di fila tutti oltre 1σ (da una parte o dall'altra)
    corse(lambda i: True if abs(z[i]) < 1 else None, 15, 7)
    corse(lambda i: True if abs(z[i]) > 1 else None, 8, 8)
    for s_ in out:
        if s_["regola"] in (7, 8):
            s_.pop("sopra", None)
    # EWMA rispetto alla prima metà (il «prima»): tratti di allarme
    base = xs[: max(9, n // 2)]
    _v, allarmi = ewma(xs, media(base), sigma_breve(base) or s)
    for lato in (True, False):
        idx = [i for i, l in allarmi if l == lato]
        for a, b in _finestre(idx, 1):
            if b - a + 1 >= 3:
                out.append({"regola": "ewma", "da": a, "a": b, "sopra": lato})
    out.sort(key=lambda g: (g["da"], str(g["regola"])))
    return out


# --- rischio, cambi, deriva -------------------------------------------------------------------------------

def rischio_prossimo(xs, lsl, usl, nominale=None, pendenza_x=0.0):
    """Probabilità che il prossimo pezzo esca: livello attuale = EWMA della serie (più la pendenza della deriva,
    in unità della quota), dispersione = σ di breve periodo; per forma e posizione la coda della Weibull."""
    if len(xs) < MIN_CAPACITA:
        return None
    sb = sigma_breve(xs) or dev_std(xs)
    valori, _a = ewma(xs, xs[0], sb)
    livello = valori[-1] + (pendenza_x or 0.0)
    if unilaterale(nominale, lsl, usl):
        w = weibull(xs)
        if w:
            # Weibull spostata sul livello attuale: scala proporzionale al rapporto livello / media
            m = media(xs) or 0
            scala = w["lam"] * (livello / m if m > 0 and livello > 0 else 1)
            return math.exp(-(usl / scala) ** w["k"]) if scala > 0 else None
        return 1 - phi((usl - livello) / sb) if sb > 0 else (1.0 if livello > usl else 0.0)
    if sb <= 0:
        return 1.0 if (livello > usl or livello < lsl) else 0.0
    return phi((lsl - livello) / sb) + 1 - phi((usl - livello) / sb)


def punti_cambio(xs, max_cambi=3, min_seg=6):
    """Dove è cambiata la media (segmentazione binaria, penalità tipo BIC sulla σ di breve periodo); conta solo uno
    spostamento di almeno 1σ. ``[{"indice": primo pezzo dopo il cambio, "prima", "dopo"}]``."""
    n = len(xs)
    sb = sigma_breve(xs)
    if n < 2 * min_seg or sb <= 0:
        return []
    pen = 3 * sb ** 2 * math.log(n)

    def costo(a, b):
        seg = xs[a:b]
        m = sum(seg) / len(seg)
        return sum((x - m) ** 2 for x in seg)

    tagli = []
    segmenti = [(0, n)]
    while segmenti and len(tagli) < max_cambi:
        migliore = None
        for a, b in segmenti:
            if b - a < 2 * min_seg:
                continue
            tot = costo(a, b)
            for t in range(a + min_seg, b - min_seg + 1):
                guadagno = tot - costo(a, t) - costo(t, b)
                if migliore is None or guadagno > migliore[0]:
                    migliore = (guadagno, a, t, b)
        if not migliore or migliore[0] <= pen:
            break
        _g, a, t, b = migliore
        m1, m2 = media(xs[a:t]), media(xs[t:b])
        segmenti.remove((a, b))
        if abs(m2 - m1) >= sb:
            tagli.append(t)
            segmenti += [(a, t), (t, b)]
    tagli.sort()
    out, bordi = [], [0] + tagli + [n]
    for i, t in enumerate(tagli):
        out.append({"indice": t, "prima": media(xs[bordi[i]:t]), "dopo": media(xs[t:bordi[i + 2]])})
    return out


def pezzi_al_limite(b, se_b, fine, massimo=200):
    """Forchetta dei pezzi al limite (±1 in tolleranza usata): pendenza più ripida (b + 1,96·errore) = prima,
    più lenta = dopo; ``None`` per «dopo» se con la pendenza lenta non ci arriva entro ``massimo`` pezzi."""
    if not b:
        return None, None
    verso = 1 if b > 0 else -1
    limite = verso

    def pezzi(pend):
        if pend * verso <= 0:
            return None
        p = max(0, int(math.ceil((limite - fine) / pend)))
        return p if p <= massimo else None

    return pezzi(b + 1.96 * se_b * verso), pezzi(b - 1.96 * se_b * verso)


def usata(x, nominale, lsl, usl):
    """Tolleranza usata: 0 = ideale, ±1 = limite. Unilaterali: rilevato / limite superiore; le altre dal centro."""
    if unilaterale(nominale, lsl, usl):
        return x / usl
    banda = usl - lsl
    return (x - (usl + lsl) / 2) / (banda / 2) if banda > 0 else None


def deriva(us, ultimi=20):
    """Tendenza degli ultimi ``ultimi`` valori di tolleranza usata (0 = ideale, ±1 = limite).

    In deriva se la retta sale (o scende) di almeno il 20% della tolleranza in quei pezzi, l'ultimo punto della
    retta è oltre metà tolleranza nella stessa direzione e, al ritmo attuale, il limite arriva entro 50 pezzi.
    ``{"pendenza": per pezzo, "pezzi": quanti pezzi al limite (0 se già oltre), "verso": "sup"|"inf",
    "pezzi_min"/"pezzi_max": forchetta al 95% (``None`` = oltre 200 pezzi), "n", "my", "mx": la retta}``."""
    v = [u for u in us if u is not None][-ultimi:]
    n = len(v)
    if n < 10:
        return None
    mx = (n - 1) / 2
    my = sum(v) / n
    den = sum((i - mx) ** 2 for i in range(n))
    b = sum((i - mx) * (u - my) for i, u in enumerate(v)) / den
    fine = my + b * (n - 1 - mx)
    if abs(b * n) < 0.2 or b * fine <= 0 or abs(fine) < 0.5:
        return None
    limite = 1 if b > 0 else -1
    pezzi = max(0, int(math.ceil((limite - fine) / b)))
    if pezzi > 50:
        return None
    res = sum((u - (my + b * (i - mx))) ** 2 for i, u in enumerate(v))
    se_b = math.sqrt(res / (n - 2) / den) if n > 2 else 0.0
    prima, dopo = pezzi_al_limite(b, se_b, fine)
    return {"pendenza": b, "pezzi": pezzi, "verso": "sup" if b > 0 else "inf", "pezzi_min": prima, "pezzi_max": dopo,
            "n": n, "my": my, "mx": mx}


def chiave_seriale(sn) -> str:
    """S/N confrontabile: solo lettere e cifre, maiuscolo."""
    return "".join(c for c in str(sn or "").upper() if c.isascii() and c.isalnum())


def ultima_per_seriale(seriali) -> list[int]:
    """Indici da tenere con «ultima misura per S/N»: per ogni S/N l'ultimo della lista (gli altri sono rimisure)."""
    ultimo: dict[str, int] = {}
    for i, sn in enumerate(seriali):
        ultimo[chiave_seriale(sn) or f"#{i}"] = i
    return sorted(ultimo.values())


# --- confronti --------------------------------------------------------------------------------------------

def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** 0.5
    sb_ = sum((y - mb) ** 2 for y in b) ** 0.5
    if sa == 0 or sb_ == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb_)


def famiglie(serie, soglia=0.7, min_comuni=15):
    """Quote che si muovono insieme. ``serie`` = {id quota: {id report: valore}}. Coppie con |r| ≥ ``soglia`` su
    almeno ``min_comuni`` report in comune; famiglie per componenti connesse. ``({id: n famiglia}, {id: [(altro, r)]})``."""
    ids = sorted(serie)
    padre = {i: i for i in ids}

    def radice(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    legami: dict = {i: [] for i in ids}
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = serie[ids[x]], serie[ids[y]]
            comuni = sorted(set(a) & set(b))
            if len(comuni) < min_comuni:
                continue
            r = pearson([a[k] for k in comuni], [b[k] for k in comuni])
            if r is not None and abs(r) >= soglia:
                legami[ids[x]].append((ids[y], r))
                legami[ids[y]].append((ids[x], r))
                padre[radice(ids[x])] = radice(ids[y])
    gruppi: dict = {}
    for i in ids:
        if legami[i]:
            gruppi.setdefault(radice(i), []).append(i)
    numero = {}
    for n, (_r, membri) in enumerate(sorted(gruppi.items(), key=lambda kv: kv[1][0]), start=1):
        for m in membri:
            numero[m] = n
    return numero, {i: sorted(v, key=lambda t: -abs(t[1])) for i, v in legami.items() if v}


def _gammq(a, x):
    """Gamma incompleta regolarizzata superiore Q(a, x) (serie / frazione continua)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:
        ap, s, d = a, 1 / a, 1 / a
        for _ in range(500):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-12:
                break
        return 1 - s * math.exp(-x + a * math.log(x) - gln)
    b, c, d = x + 1 - a, 1e300, 1 / (x + 1 - a)
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        h *= d * c
        if abs(d * c - 1) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def kruskal(gruppi, min_per_gruppo=5):
    """Test di Kruskal-Wallis fra gruppi (es. OP): ``{"h", "p", "k"}`` o ``None`` con meno di 2 gruppi validi.
    p < 0,05 = almeno un gruppo è diverso dagli altri, non è solo rumore."""
    validi = {k: v for k, v in gruppi.items() if len(v) >= min_per_gruppo}
    if len(validi) < 2:
        return None
    tutti = sorted((x, k) for k, v in validi.items() for x in v)
    N = len(tutti)
    rank, i, ties = {}, 0, 0.0
    somma = {k: 0.0 for k in validi}
    while i < N:
        j = i
        while j + 1 < N and tutti[j + 1][0] == tutti[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        t = j - i + 1
        ties += t ** 3 - t
        for q in range(i, j + 1):
            somma[tutti[q][1]] += r
        i = j + 1
    h = 12 / (N * (N + 1)) * sum(somma[k] ** 2 / len(v) for k, v in validi.items()) - 3 * (N + 1)
    corr = 1 - ties / (N ** 3 - N) if N > 1 else 1
    if corr > 0:
        h /= corr
    k = len(validi)
    return {"h": h, "p": _gammq((k - 1) / 2, h / 2), "k": k}


def ripetibilita(differenze, banda):
    """Ripetibilità della misura dalle coppie di misure dello stesso pezzo senza lavorazioni in mezzo:
    σ = √(Σd² / 2m); % della tolleranza consumata dalla misura = 6σ / tolleranza. Servono almeno 5 coppie."""
    m = len(differenze)
    if m < 5 or banda <= 0:
        return None
    s = math.sqrt(sum(d * d for d in differenze) / (2 * m))
    return {"coppie": m, "sigma": s, "pct": 6 * s / banda * 100}
