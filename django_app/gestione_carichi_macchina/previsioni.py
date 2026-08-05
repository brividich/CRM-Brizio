"""Predizioni data-driven per Gestione Carichi Macchina (AI predittiva, Fase 1: durata/ore).

La predizione la fa un modello sui DATI (statistico, spiegabile e validabile), NON l'LLM.
Funzioni pure: ricevono indici precalcolati, nessuna query qui dentro (testabili in isolamento).
Gli indici si costruiscono da DB con `costruisci_indici()`.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import ceil

from django.utils import timezone

FONTE_CICLO = "ciclo"      # tempo di ciclo x pezzi (alta confidenza)
FONTE_STORICO = "storico"  # media storica famiglia x macchina (media)
FONTE_FAMIGLIA = "famiglia"  # media storica della famiglia su qualunque macchina (bassa)
FONTE_NESSUNA = "nessuno"

# Pesi di default per lo scoring pesato del suggerimento macchina (Fase 2b).
# freq = affinita' storica (segnale principale); recency = quanto e' recente quella
# storia; carico = quanto la macchina e' libera ORA. Somma 1.0, tutti i termini in [0,1].
PESI_SUGGERIMENTO_DEFAULT = {"freq": 0.5, "recency": 0.2, "carico": 0.3}
# Stati che escludono una macchina dal suggerimento (non puo' prendere lavoro ora).
_STATI_NON_DISPONIBILI = {"guasto", "manutenzione"}


def prevedi_ore(
    *,
    qta: int | None,
    macchina_id: int | None,
    famiglia_id: int | None,
    ciclo_tempi: dict[tuple[int, int], int],
    affinita_ore: dict[tuple[int, int], float],
    famiglia_ore: dict[int, float] | None = None,
) -> tuple[float | None, str, str]:
    """Predice le ore di un lavoro. Ritorna (ore, fonte, confidenza).

    Priorita':
    1) tempo di ciclo (cent/cad) x pezzi, se esiste l'operazione per (famiglia, macchina);
    2) media storica delle ore per (macchina, famiglia);
    3) media storica della famiglia (qualunque macchina);
    altrimenti (None, 'nessuno', 'assente').
    """
    famiglia_ore = famiglia_ore or {}

    if qta and famiglia_id and macchina_id:
        t = ciclo_tempi.get((famiglia_id, macchina_id))
        if t:
            return round(qta * t / 100.0, 1), FONTE_CICLO, "alta"

    if macchina_id and famiglia_id:
        om = affinita_ore.get((macchina_id, famiglia_id))
        if om:
            return round(float(om), 1), FONTE_STORICO, "media"

    if famiglia_id:
        fo = famiglia_ore.get(famiglia_id)
        if fo:
            return round(float(fo), 1), FONTE_FAMIGLIA, "bassa"

    return None, FONTE_NESSUNA, "assente"


def costruisci_indici() -> tuple[dict, dict, dict]:
    """Costruisce gli indici di predizione dal DB: (ciclo_tempi, affinita_ore, famiglia_ore)."""
    from collections import defaultdict

    from .models import MacchinaFamigliaAffinita, Operazione

    ciclo_tempi: dict[tuple[int, int], int] = {}
    for op in (
        Operazione.objects.filter(
            macchina_preferita__isnull=False, tempo_cent_cad__isnull=False,
            ciclo__famiglia__isnull=False,
        ).select_related("ciclo")
    ):
        ciclo_tempi[(op.ciclo.famiglia_id, op.macchina_preferita_id)] = op.tempo_cent_cad

    affinita_ore: dict[tuple[int, int], float] = {}
    fam_acc: dict[int, list] = defaultdict(list)
    for a in MacchinaFamigliaAffinita.objects.filter(ore_medie__isnull=False):
        val = float(a.ore_medie)
        affinita_ore[(a.macchina_id, a.famiglia_id)] = val
        fam_acc[a.famiglia_id].append(val)

    famiglia_ore = {fid: round(sum(v) / len(v), 1) for fid, v in fam_acc.items() if v}
    return ciclo_tempi, affinita_ore, famiglia_ore


# --- Fase 2: macchina piu' probabile per una famiglia/pezzo ----------------
def prevedi_macchina(
    famiglia_id: int | None,
    freq_per_famiglia: dict[int, list],
    *,
    fase: str | None = None,
    freq_per_famiglia_fase: dict[tuple[int, str], list] | None = None,
    freq_fase_globale: dict[str, list] | None = None,
    recency_per_coppia: dict[tuple[int, int], float] | None = None,
    carico_per_macchina: dict[int, float] | None = None,
    stato_per_macchina: dict[int, str] | None = None,
    pesi: dict[str, float] | None = None,
    categoria_per_macchina: dict[int, str] | None = None,
    pesi_per_categoria: dict[str, dict[str, float]] | None = None,
) -> list[dict]:
    """Predice su quali macchine conviene lavorare una certa famiglia.

    freq_per_famiglia: dict[famiglia_id] -> [(macchina_id, occorrenze), ...].

    Modalita' **storica** (default, retro-compatibile): senza segnali aggiuntivi
    ordina per sola frequenza storica e ritorna [{macchina_id, occorrenze, prob}].

    Modalita' **pesata** (se passi almeno uno tra recency/carico/stato): combina in
    uno score esplicabile la frequenza storica (`prob`), la *recency* di quella storia
    e quanto la macchina e' **libera ORA** (1 - saturazione); le macchine in
    guasto/manutenzione sono **escluse** (non possono prendere lavoro). Aggiunge a ogni
    voce `score`, `componenti` (freq/recency/carico_libero), `saturazione` e `stato`.

    `pesi_per_categoria`/`categoria_per_macchina`: profili di pesi diversi per CATEGORIA
    di macchina (es. i torni possono voler privilegiare il carico, le 5 assi la recency),
    in aggiunta al singolo override `pesi`. Il peso applicato a ciascuna macchina candidata
    e' `PESI_SUGGERIMENTO_DEFAULT` sovrascritto prima da `pesi` (globale alla chiamata) poi
    dal profilo della SUA categoria, se presente — nessun impatto se non passati (retro-
    compatibile).

    `freq_fase_globale`: fallback COLD-START. Se la famiglia non ha ALCUNO storico proprio
    (ne' per fase ne' generale) ma e' nota la fase, si ricade sulla frequenza aggregata di
    quella fase su TUTTE le famiglie (quali macchine fanno tipicamente quella lavorazione)
    invece di restituire una lista vuota. Le voci risultanti da questo fallback portano
    `fallback_globale=True` (sempre presente, anche False altrimenti) cosi' l'UI puo'
    segnalare che e' un suggerimento piu' debole, non specifico della famiglia.

    Tutti i termini sono in [0,1]; nessun LLM, ranking deterministico e spiegabile.
    """
    # Affinita' per FASE (sgr/fin/rip/ass) quando disponibile: le fasi sono lavorazioni
    # diverse, quindi la macchina giusta per la sgrossatura puo' non esserlo per la finitura.
    # Si usa la frequenza per (famiglia, fase) se presente, altrimenti si ricade sulla
    # frequenza per sola famiglia (retro-compatibile), infine sulla fase GLOBALE (cold-start).
    items = None
    if fase and freq_per_famiglia_fase:
        items = freq_per_famiglia_fase.get((famiglia_id, fase))
    if not items:
        items = freq_per_famiglia.get(famiglia_id) or []
    fallback_globale = False
    if not items and fase and freq_fase_globale:
        items = freq_fase_globale.get(fase) or []
        fallback_globale = bool(items)
    tot = sum(o for _m, o in items)
    base = [
        {"macchina_id": m, "occorrenze": o, "prob": round(o / tot, 3) if tot else 0.0,
         "fallback_globale": fallback_globale}
        for m, o in items
    ]

    pesato = (
        recency_per_coppia is not None
        or carico_per_macchina is not None
        or stato_per_macchina is not None
    )
    if not pesato:
        base.sort(key=lambda x: (x["occorrenze"], x["macchina_id"]), reverse=True)
        return base

    w_base = {**PESI_SUGGERIMENTO_DEFAULT, **(pesi or {})}
    cat_per_m = categoria_per_macchina or {}
    profili_cat = pesi_per_categoria or {}
    rec = recency_per_coppia or {}
    car = carico_per_macchina or {}
    sta = stato_per_macchina or {}
    out: list[dict] = []
    for it in base:
        m = it["macchina_id"]
        stato = sta.get(m, "attiva")
        if stato in _STATI_NON_DISPONIBILI:
            continue  # vincolo rigido: macchina non disponibile ORA
        w = {**w_base, **(profili_cat.get(cat_per_m.get(m)) or {})}
        s_freq = it["prob"]
        s_rec = float(rec.get((m, famiglia_id), 0.0))
        sat = float(car.get(m, 0.0))
        s_load = max(0.0, 1.0 - sat)  # libera=1, satura/oltre capacita'=0
        score = w["freq"] * s_freq + w["recency"] * s_rec + w["carico"] * s_load
        out.append(
            {
                **it,
                "score": round(score, 3),
                "componenti": {
                    "freq": round(s_freq, 3),
                    "recency": round(s_rec, 3),
                    "carico_libero": round(s_load, 3),
                },
                "saturazione": round(sat, 3),
                "stato": stato,
            }
        )
    out.sort(key=lambda x: (x["score"], x["occorrenze"], x["macchina_id"]), reverse=True)
    return out


def costruisci_indice_macchine() -> dict[int, list]:
    """Indice frequenza: famiglia_id -> [(macchina_id, occorrenze), ...] (da affinita')."""
    from collections import defaultdict

    from .models import MacchinaFamigliaAffinita

    freq: dict[int, list] = defaultdict(list)
    for a in MacchinaFamigliaAffinita.objects.all():
        freq[a.famiglia_id].append((a.macchina_id, a.occorrenze))
    return dict(freq)


def costruisci_indice_macchine_fase() -> dict[tuple[int, str], list]:
    """Frequenza per (famiglia, fase): (famiglia_id, fase) -> [(macchina_id, occ), ...].

    Derivata dallo storico delle `Pianificazione` (che porta gia' famiglia + fase), quindi
    senza migrazioni: cattura che sgrossatura/finitura/ripresa/assemblaggio vanno su macchine
    diverse anche per la stessa famiglia.

    Solo lavori COMPLETATI: una pianificazione ancora aperta (pianificata/in corso) non deve
    auto-rinforzare il proprio stesso suggerimento prima di essere mai stata eseguita
    (altrimenti un'assegnazione manuale sbagliata verrebbe ri-suggerita, feedback loop).
    """
    from collections import defaultdict

    from .models import Pianificazione

    acc: dict[tuple[int, str], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    qs = (
        Pianificazione.objects.filter(
            famiglia_id__isnull=False, stato=Pianificazione.STATO_COMPLETATA
        )
        .exclude(fase="")
        .only("macchina_id", "famiglia_id", "fase")
    )
    for p in qs:
        acc[(p.famiglia_id, p.fase)][p.macchina_id] += 1
    return {
        key: sorted(macs.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
        for key, macs in acc.items()
    }


def costruisci_indice_macchine_fase_globale() -> dict[str, list]:
    """Frequenza per SOLA fase (fase -> [(macchina_id, occ), ...]), aggregata su TUTTE le
    famiglie e solo lavori COMPLETATI (stessa regola anti-feedback-loop di
    `costruisci_indice_macchine_fase`).

    Fallback cold-start per `prevedi_macchina`: una famiglia SENZA storico proprio (mai
    lavorata) eredita quali macchine fanno tipicamente quella lavorazione in generale,
    invece di restare senza alcun suggerimento.
    """
    from collections import defaultdict

    from .models import Pianificazione

    acc: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    qs = (
        Pianificazione.objects.filter(stato=Pianificazione.STATO_COMPLETATA)
        .exclude(fase="")
        .only("macchina_id", "fase")
    )
    for p in qs:
        acc[p.fase][p.macchina_id] += 1
    return {
        fase: sorted(macs.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
        for fase, macs in acc.items()
    }


def costruisci_indice_recency(oggi: date | None = None, *, mezza_vita_giorni: int = 180) -> dict[tuple[int, int], float]:
    """Recency score [0,1] per coppia (macchina, famiglia) da `ultima_data`.

    Decadimento esponenziale con mezza vita `mezza_vita_giorni`: storia di oggi -> ~1,
    storia di una mezza-vita fa -> 0.5, molto vecchia -> verso 0. Coppie senza data
    semplicemente non compaiono (recency 0 a valle).
    """
    from .models import MacchinaFamigliaAffinita

    oggi = oggi or timezone.localdate()
    out: dict[tuple[int, int], float] = {}
    qs = MacchinaFamigliaAffinita.objects.filter(ultima_data__isnull=False).only(
        "macchina_id", "famiglia_id", "ultima_data"
    )
    for a in qs:
        giorni = max(0, (oggi - a.ultima_data).days)
        out[(a.macchina_id, a.famiglia_id)] = 0.5 ** (giorni / mezza_vita_giorni)
    return out


def finestra_carico_per_ore(
    ore_medie: float | None, *, ore_giorno: float = 8.0, minimo: int = 7, massimo: int = 30
) -> int:
    """Dimensiona in giorni la finestra di saturazione sulla durata TIPICA del lavoro da
    assegnare, invece di una finestra fissa: 14gg fissi sovrastimano la saturazione per un
    lavoro di 1 giorno (rumore su una macchina quasi libera) e la sottostimano per uno di
    2 mesi (non vede l'impegno reale oltre la finestra). Ritorna un intero in
    [`minimo`, `massimo`]; senza una stima (`ore_medie` assente/0) usa il default storico 14gg.
    """
    if not ore_medie:
        return 14
    giorni = ceil(float(ore_medie) / ore_giorno)
    return max(minimo, min(massimo, giorni))


def costruisci_indice_carico(giorni: int = 14, *, oggi: date | None = None) -> dict[int, float]:
    """Saturazione attuale per macchina (frazione: 1.0 = piena) sulla finestra `giorni`.

    Usa le ore gia' pianificate (carico confermato) sulla finestra a partire da `oggi`,
    cosi' un suggerimento non manda lavoro su una macchina gia' satura.
    """
    from .models import Macchina, Pianificazione
    from .saturazione import calcola_saturazione

    oggi = oggi or timezone.localdate()
    finestra = [oggi + timedelta(days=i) for i in range(max(1, giorni))]
    macchine = list(Macchina.objects.filter(attivo=True))
    pians = list(
        Pianificazione.objects.filter(data__range=(finestra[0], finestra[-1])).only("macchina_id", "ore")
    )
    sat = calcola_saturazione(macchine, pians, finestra)
    return {mid: (v["perc"] / 100.0) for mid, v in sat["per_macchina"].items()}


def costruisci_indice_stato() -> dict[int, str]:
    """Stato di pianificazione per macchina (attiva/guasto/manutenzione)."""
    from .models import Macchina

    return {m.id: m.stato_pianificazione for m in Macchina.objects.all().only("id", "stato_pianificazione")}


# --- Fase 3: rischio ritardo commessa --------------------------------------
def _fine_lavorativa(inizio: date, durata_gg: int) -> date:
    """Data di fine contando `durata_gg` giorni lavorativi a partire da inizio (inclusivo)."""
    giorni: list[date] = []
    d = inizio
    while len(giorni) < max(1, durata_gg):
        if d.weekday() < 5:
            giorni.append(d)
        d += timedelta(days=1)
    return giorni[-1]


def _gg_lavorativi_tra(a: date, b: date) -> int:
    """Giorni lavorativi tra a e b (esclusa a, inclusa b), con segno (negativo se b<a)."""
    if a == b:
        return 0
    lo, hi = (a, b) if a < b else (b, a)
    cnt = 0
    d = lo
    while d < hi:
        d += timedelta(days=1)
        if d.weekday() < 5:
            cnt += 1
    return cnt if a < b else -cnt


def rischio_ritardo(*, data_inizio, ore_previste, ore_giorno, data_consegna) -> dict:
    """Stima se un lavoro finisce entro la consegna.

    Ritorna {valutabile, fine_prevista, in_ritardo, giorni_margine}.
    giorni_margine > 0 = margine (giorni lavorativi prima della consegna); < 0 = ritardo.
    """
    if not (data_inizio and data_consegna and ore_previste):
        return {"valutabile": False}
    ogg = float(ore_giorno) or 8.0
    durata_gg = max(1, ceil(float(ore_previste) / ogg))
    fine = _fine_lavorativa(data_inizio, durata_gg)
    return {
        "valutabile": True,
        "fine_prevista": fine,
        "in_ritardo": fine > data_consegna,
        "giorni_margine": _gg_lavorativi_tra(fine, data_consegna),
    }


# --- Fase 4: previsione carico / colli di bottiglia ------------------------
def carico_settimanale(start: date, n_settimane: int, *, indici=None) -> list[dict]:
    """Carico previsto per le prossime `n_settimane`, per reparto e totale.

    Usa le ore REALI dove ci sono, altrimenti la durata STIMATA (Fase 1), così il carico
    futuro e' realistico. Ritorna [{settimana, totale, per_reparto}] con perc di saturazione;
    un reparto con perc>100 e' un collo di bottiglia.
    """
    from types import SimpleNamespace

    from .models import Macchina, Pianificazione
    from .saturazione import calcola_saturazione

    ciclo_tempi, affinita_ore, famiglia_ore = indici or costruisci_indici()
    macchine = list(Macchina.objects.filter(attivo=True))
    out: list[dict] = []
    for w in range(n_settimane):
        ws = start + timedelta(days=7 * w)
        giorni = [ws + timedelta(days=i) for i in range(7)]
        pians = list(
            Pianificazione.objects.filter(data__range=(giorni[0], giorni[-1]))
            .only("macchina_id", "ore", "qta", "famiglia_id")
        )
        stub = []
        for p in pians:
            ore = float(p.ore) if p.ore else None
            if ore is None:
                ore, _f, _c = prevedi_ore(
                    qta=p.qta, macchina_id=p.macchina_id, famiglia_id=p.famiglia_id,
                    ciclo_tempi=ciclo_tempi, affinita_ore=affinita_ore, famiglia_ore=famiglia_ore,
                )
            stub.append(SimpleNamespace(macchina_id=p.macchina_id, ore=ore or 0))
        sat = calcola_saturazione(macchine, stub, giorni)
        out.append({"settimana": ws, "totale": sat["totale"], "per_reparto": sat["per_reparto"]})
    return out
