"""
Logica di business: riconciliazione fattura vs letture interne e controllo
monotonìa. Nessuna dipendenza da SNMP qui.

Due controlli indipendenti:
  1) DIREZIONE  — la lettura interna (fatta con qualche giorno di ritardo) deve
     essere >= a quella del fornitore. Scarto negativo = il fornitore conta piu'
     copie di quante la macchina mostri fisicamente -> "stampa segnata in piu'".
  2) MONOTONIA  — un contatore non puo' scendere da un trimestre al successivo.
     Un calo = refuso interno o reset da verificare.
"""
from collections import defaultdict
from django.utils import timezone
from .models import Macchina, LetturaContatori, Fattura, RigaFattura, CONTATORI

CAMPI = [c[0] for c in CONTATORI]

# Raggruppamenti usati nelle analisi
BN = ("a4_bn", "a3_bn")
COL = ("a4_col", "a3_col")
A4 = ("a4_bn", "a4_col")
A3 = ("a3_bn", "a3_col")


def _somma(lettura, campi):
    return sum(getattr(lettura, c) for c in campi)


def _macchine_per_contratto(contratto):
    return list(Macchina.objects.filter(contratto=contratto))


def riconcilia(trimestre):
    """
    Ritorna (righe, riepilogo) per un trimestre.
    Ogni riga = un'unita' di fatturazione x un contatore, con scarto ed esito.
    """
    fatture = Fattura.objects.filter(trimestre=trimestre).prefetch_related("righe")
    righe_out = []
    anomalie = 0

    for fattura in fatture:
        for rf in fattura.righe.all():
            macchine = _macchine_per_contratto(rf.contratto)
            # letture interne del trimestre per le macchine di questo contratto
            letture = {l.macchina_id: l for l in LetturaContatori.objects.filter(
                trimestre=trimestre, macchina__in=macchine)}
            pool = len(macchine) > 1
            for campo, etichetta in CONTATORI:
                forn = getattr(rf, campo)
                if letture and len(letture) == len(macchine):
                    ns = sum(getattr(letture[m.id], campo) for m in macchine)
                    ns_disp = ns
                else:
                    ns = None
                    ns_disp = None
                if ns is None:
                    scarto, esito, livello = None, "lettura interna mancante", "warn"
                else:
                    scarto = ns - forn
                    if scarto < 0:
                        esito, livello = "⚠ CONTROLLARE (fornitore > macchina)", "danger"
                        anomalie += 1
                    elif scarto == 0:
                        esito, livello = "OK esatto", "ok"
                    else:
                        esito, livello = "OK (stampe nel ritardo)", "ok"
                righe_out.append({
                    "contratto": rf.contratto,
                    "descrizione": rf.descrizione,
                    "pool": pool,
                    "contatore": etichetta,
                    "fornitore": forn,
                    "ns": ns_disp,
                    "scarto": scarto,
                    "esito": esito,
                    "livello": livello,
                })

    riepilogo = {
        "trimestre": trimestre,
        "contatori": len(righe_out),
        "anomalie": anomalie,
        "ok": anomalie == 0 and len(righe_out) > 0,
        "fatture": [f.numero for f in fatture],
    }
    return righe_out, riepilogo


def controllo_monotonia():
    """
    Per ogni macchina x contatore, verifica che le letture non scendano mai nel
    tempo. Ritorna la lista dei cali rilevati.
    """
    problemi = []
    for macchina in Macchina.objects.all():
        letture = list(macchina.letture.order_by("trimestre"))
        if len(letture) < 2:
            continue
        for campo, etichetta in CONTATORI:
            prec = None
            for l in letture:
                val = getattr(l, campo)
                if prec is not None and val < prec[1]:
                    problemi.append({
                        "macchina": str(macchina),
                        "matricola": macchina.matricola,
                        "contatore": etichetta,
                        "da_trim": prec[0],
                        "da_val": prec[1],
                        "a_trim": l.trimestre,
                        "a_val": val,
                    })
                prec = (l.trimestre, val)
    return problemi


def storico_macchina(macchina):
    """Serie temporale dei 4 contatori per i grafici / tabella storico."""
    letture = list(macchina.letture.order_by("trimestre"))
    return {
        "trimestri": [l.trimestre for l in letture],
        "serie": {etichetta: [getattr(l, campo) for l in letture]
                  for campo, etichetta in CONTATORI},
        "letture": letture,
    }


def trimestri_disponibili():
    q = set(Fattura.objects.values_list("trimestre", flat=True))
    q |= set(LetturaContatori.objects.values_list("trimestre", flat=True))
    return sorted(q, reverse=True)


# --- Ultima rilevazione per macchina ---------------------------------------

SOGLIA_STALE_GIORNI = 100  # oltre ~un trimestre senza letture = "da aggiornare"


def ultime_rilevazioni(oggi=None):
    """
    Per ogni macchina attiva ritorna l'ultima lettura (su tutti i trimestri) con
    lo stato: 'aggiornata' | 'da_aggiornare' | 'mai'.
    { macchina_id: {"lettura", "giorni_fa", "stato", "livello"} }
    """
    oggi = oggi or timezone.now().date()
    out = {}
    for m in Macchina.objects.filter(attiva=True):
        ultima = m.letture.order_by("-trimestre", "-data").first()
        if ultima is None:
            out[m.id] = {"lettura": None, "giorni_fa": None,
                         "stato": "mai", "livello": "warn"}
            continue
        giorni = (oggi - ultima.data).days
        if giorni <= SOGLIA_STALE_GIORNI:
            stato, livello = "aggiornata", "ok"
        else:
            stato, livello = "da_aggiornare", "warn"
        out[m.id] = {"lettura": ultima, "giorni_fa": giorni,
                     "stato": stato, "livello": livello}
    return out


# --- Analisi ----------------------------------------------------------------

def _letture_ordinate_per_macchina():
    """{ macchina: [letture ordinate per trimestre] } solo macchine attive."""
    per_macchina = {}
    for m in Macchina.objects.filter(attiva=True):
        letture = list(m.letture.order_by("trimestre"))
        if letture:
            per_macchina[m] = letture
    return per_macchina


def andamento_trimestri():
    """
    Totali cumulati della flotta per trimestre (somma di tutte le macchine).
    Ritorna lista ordinata: [{trimestre, a4_bn, a3_bn, a4_col, a3_col,
    bn, col, a4, a3, totale}].
    """
    agg = defaultdict(lambda: defaultdict(int))
    for l in LetturaContatori.objects.filter(macchina__attiva=True):
        row = agg[l.trimestre]
        for c in CAMPI:
            row[c] += getattr(l, c)
    out = []
    for trim in sorted(agg):
        r = agg[trim]
        bn = r["a4_bn"] + r["a3_bn"]
        col = r["a4_col"] + r["a3_col"]
        a4 = r["a4_bn"] + r["a4_col"]
        a3 = r["a3_bn"] + r["a3_col"]
        out.append({"trimestre": trim, **r, "bn": bn, "col": col,
                    "a4": a4, "a3": a3, "totale": bn + col})
    return out


def consumo_per_trimestre():
    """
    Copie effettivamente prodotte per trimestre = differenza tra letture
    consecutive di ogni macchina, sommata sulla flotta. I cali (refusi di
    monotonìa) vengono azzerati e conteggiati a parte.
    Ritorna (per_trimestre, anomalie) dove per_trimestre =
    [{trimestre, bn, col, totale}] etichettato col trimestre di arrivo.
    """
    delta_trim = defaultdict(lambda: defaultdict(int))
    anomalie = 0
    for _m, letture in _letture_ordinate_per_macchina().items():
        for prec, curr in zip(letture, letture[1:]):
            for c in CAMPI:
                d = getattr(curr, c) - getattr(prec, c)
                if d < 0:
                    anomalie += 1
                    d = 0
                delta_trim[curr.trimestre][c] += d
    out = []
    for trim in sorted(delta_trim):
        r = delta_trim[trim]
        bn = r["a4_bn"] + r["a3_bn"]
        col = r["a4_col"] + r["a3_col"]
        out.append({"trimestre": trim, "bn": bn, "col": col,
                    "totale": bn + col, "a4_bn": r["a4_bn"], "a3_bn": r["a3_bn"],
                    "a4_col": r["a4_col"], "a3_col": r["a3_col"]})
    return out, anomalie


def classifica_reparti():
    """
    Consumo totale (somma dei delta su tutti i trimestri) per reparto, con quota
    colore. Ordinato per volume decrescente.
    [{reparto, matricola, bn, col, totale, quota_col}]
    """
    out = []
    for m, letture in _letture_ordinate_per_macchina().items():
        bn = col = 0
        for prec, curr in zip(letture, letture[1:]):
            for c in BN:
                bn += max(0, getattr(curr, c) - getattr(prec, c))
            for c in COL:
                col += max(0, getattr(curr, c) - getattr(prec, c))
        tot = bn + col
        out.append({"reparto": m.reparto, "matricola": m.matricola,
                    "bn": bn, "col": col, "totale": tot,
                    "quota_col": round(100 * col / tot) if tot else 0})
    out.sort(key=lambda r: r["totale"], reverse=True)
    return out


def ripartizione():
    """
    Ripartizione BN/Colore e A4/A3 sui totali cumulati dell'ultimo trimestre
    disponibile. Ritorna percentuali intere che sommano ~100.
    """
    and_ = andamento_trimestri()
    if not and_:
        return {"bn": 0, "col": 0, "a4": 0, "a3": 0, "totale": 0}
    u = and_[-1]
    tot = u["totale"] or 1
    return {
        "trimestre": u["trimestre"],
        "totale": u["totale"],
        "bn_pct": round(100 * u["bn"] / tot),
        "col_pct": round(100 * u["col"] / tot),
        "a4_pct": round(100 * u["a4"] / tot),
        "a3_pct": round(100 * u["a3"] / tot),
    }
