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
from datetime import timedelta
from decimal import Decimal, InvalidOperation, Overflow
import re
from time import perf_counter

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from . import errori_snmp, soc
from .models import (
    CONTATORI,
    DispositivoSNMP,
    Fattura,
    ImpostazioniSNMP,
    LetturaContatori,
    LetturaConsumabile,
    LetturaMensileContatori,
    Macchina,
    ProfiloSNMP,
    RilevazioneSNMP,
    RigaFattura,
    SondaSNMP,
    StatoSNMP,
    ValoreSNMP,
)

CAMPI = [c[0] for c in CONTATORI]

# Allineato al cron di contatori_letture_mensili_recupero (automazioni/schedules.py).
GIORNI_RECUPERO_MENSILE = 7

# Raggruppamenti usati nelle analisi
BN = ("a4_bn", "a3_bn")


def trova_asset_snmp(*, seriale="", host=None):
    """Trova un Asset HUB univoco per seriale, poi per IP (endpoint o collegamenti SOC).

    Restituisce ``(asset, motivo)``. In caso di nessun match o ambiguità non
    sceglie arbitrariamente: ``asset`` resta ``None`` e il motivo spiega perché.
    Stesso algoritmo del SOC: ``assets.services.identity_match``.
    """
    from assets.services.identity_match import match_hub_asset

    return match_hub_asset(serial=seriale, ip=host or "")
COL = ("a4_col", "a3_col")
A4 = ("a4_bn", "a4_col")
A3 = ("a3_bn", "a3_col")


def _somma(lettura, campi):
    return sum(getattr(lettura, c) for c in campi)


def _macchine_per_contratto(contratto, trimestre):
    """MFC del contratto: le attive e le dismesse che hanno una lettura nel trimestre.

    Una macchina dismessa senza lettura non e' «lettura mancante»: non e' piu' in pool.
    """
    from django.db.models import Q
    return list(Macchina.objects.filter(contratto=contratto).filter(
        Q(attiva=True) | Q(letture__trimestre=trimestre)).distinct())


# --- Trimestri ----------------------------------------------------------------

_TRIMESTRE_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def trimestre_di(data):
    return f"{data.year}-Q{(data.month - 1) // 3 + 1}"


def trimestre_corrente():
    return trimestre_di(timezone.localdate())


def trimestre_valido(valore):
    return bool(_TRIMESTRE_RE.match(valore or ""))


def opzioni_trimestri(indietro=8, extra=()):
    """Trimestre corrente, i precedenti `indietro` e quelli gia' presenti a DB.

    Ordinati dal piu' recente; usati come scelte nei form (niente testo libero).
    """
    anno, q = map(int, _TRIMESTRE_RE.match(trimestre_corrente()).groups())
    valori = set()
    for _ in range(indietro + 1):
        valori.add(f"{anno}-Q{q}")
        q -= 1
        if q == 0:
            anno, q = anno - 1, 4
    valori |= {t for t in trimestri_disponibili() if trimestre_valido(t)}
    valori |= {t for t in extra if trimestre_valido(t)}
    return sorted(valori, reverse=True)


def contratti_attivi():
    """[(contratto, descrizione)] delle MFC attive, per precompilare le fatture."""
    reparti = defaultdict(list)
    for contratto, reparto in (Macchina.objects.filter(attiva=True).exclude(contratto="")
                               .order_by("contratto", "reparto").values_list("contratto", "reparto")):
        reparti[contratto].append(reparto)
    return [(c, " + ".join(r)) for c, r in sorted(reparti.items())]


# Contatori confrontati: (etichetta, campo della riga fattura, campi interni sommati).
_CONFRONTO_FORMATO = tuple((etichetta, campo, (campo,)) for campo, etichetta in CONTATORI)
# Fattura «solo totali» (Copylab): il totale fatturato vale A4 + A3 della macchina.
_CONFRONTO_TOTALI = (("BN totale", "a4_bn", ("a4_bn", "a3_bn")),
                     ("COL totale", "a4_col", ("a4_col", "a3_col")))
_GRAVITA = {"ok": 0, "warn": 1, "danger": 2}


def riconcilia(trimestre):
    """
    Ritorna (righe, riepilogo) per un trimestre.
    Ogni riga = un'unita' di fatturazione x un contatore, con scarto ed esito.
    `riepilogo["gruppi"]` raccoglie le stesse righe per fattura e contratto, con le
    macchine del contratto e la data della loro lettura interna.
    """
    fatture = Fattura.objects.filter(trimestre=trimestre).prefetch_related("righe")
    righe_out, gruppi = [], []
    anomalie = 0

    for fattura in fatture:
        totali = fattura.dettaglio == Fattura.Dettaglio.TOTALI
        confronto = _CONFRONTO_TOTALI if totali else _CONFRONTO_FORMATO
        for rf in fattura.righe.all():
            macchine = _macchine_per_contratto(rf.contratto, trimestre)
            # letture interne del trimestre per le macchine di questo contratto
            letture = {l.macchina_id: l for l in LetturaContatori.objects.filter(
                trimestre=trimestre, macchina__in=macchine)}
            pool = len(macchine) > 1
            mancanti = [m for m in macchine if m.id not in letture]
            completo = bool(macchine) and not mancanti
            righe_gruppo = []
            for etichetta, campo, campi_interni in confronto:
                forn = getattr(rf, campo)
                per_macchina = [(m, sum(getattr(letture[m.id], c) for c in campi_interni))
                                for m in macchine if m.id in letture]
                ns = sum(v for _, v in per_macchina) if completo else None
                if not macchine:
                    scarto, esito, livello = None, "nessuna MFC con questo contratto", "warn"
                elif ns is None:
                    scarto, esito, livello = None, "lettura interna mancante", "warn"
                else:
                    scarto = ns - forn
                    if scarto < 0:
                        esito, livello = "Da controllare: fornitore > interno", "danger"
                        anomalie += 1
                    elif scarto == 0:
                        esito, livello = "OK esatto", "ok"
                    else:
                        esito, livello = "OK (stampe nel ritardo)", "ok"
                righe_gruppo.append({
                    "contratto": rf.contratto,
                    "descrizione": rf.descrizione,
                    "pool": pool,
                    "contatore": etichetta,
                    "fornitore": forn,
                    "ns": ns,
                    "scarto": scarto,
                    "esito": esito,
                    "livello": livello,
                    "mancanti": mancanti,
                    "per_macchina": per_macchina if pool else [],
                })
            righe_out += righe_gruppo
            gruppi.append({
                "fattura": fattura,
                "contratto": rf.contratto,
                "descrizione": rf.descrizione,
                "pool": pool,
                "totali": totali,
                "macchine": [{
                    "macchina": m,
                    "lettura": letture.get(m.id),
                    # giorni tra la chiusura del fornitore e la lettura interna
                    "giorni": (letture[m.id].data - fattura.periodo_al).days if m.id in letture else None,
                } for m in macchine],
                "mancanti": mancanti,
                "righe": righe_gruppo,
                "livello": max((r["livello"] for r in righe_gruppo), key=_GRAVITA.get, default="ok"),
                "copie_in_eccesso": -sum(r["scarto"] for r in righe_gruppo
                                       if r["scarto"] is not None and r["scarto"] < 0),
            })

    riepilogo = {
        "trimestre": trimestre,
        "contatori": len(righe_out),
        "anomalie": anomalie,
        "ok": anomalie == 0 and len(righe_out) > 0,
        "fatture": [f.numero for f in fatture],
        "letture_mancanti": len({m.id for r in righe_out for m in r["mancanti"]}),
        "gruppi": gruppi,
        "contratti": len(gruppi),
        "contratti_ok": sum(1 for g in gruppi if g["livello"] == "ok"),
        "contratti_danger": sum(1 for g in gruppi if g["livello"] == "danger"),
    }
    return righe_out, riepilogo


def controllo_monotonia():
    """
    Per ogni macchina x contatore, verifica che le letture non scendano mai nel
    tempo. Ritorna la lista dei cali rilevati.
    """
    problemi = []
    # Una query sola per tutte le letture, raggruppate qui (prima: una query per macchina).
    per_macchina = defaultdict(list)
    for lettura in LetturaContatori.objects.order_by("macchina_id", "trimestre"):
        per_macchina[lettura.macchina_id].append(lettura)
    for macchina in Macchina.objects.all():
        letture = per_macchina.get(macchina.pk, [])
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
    # Una query sola: l'ultima per trimestre (poi data) di ogni macchina vince.
    ultime = {}
    for l in LetturaContatori.objects.filter(macchina__attiva=True).order_by("trimestre", "data"):
        ultime[l.macchina_id] = l
    for m in Macchina.objects.filter(attiva=True):
        ultima = ultime.get(m.pk)
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
    letture = defaultdict(list)
    for lettura in LetturaContatori.objects.filter(macchina__attiva=True).order_by("macchina_id", "trimestre"):
        letture[lettura.macchina_id].append(lettura)
    return {m: letture[m.pk] for m in Macchina.objects.filter(attiva=True) if letture.get(m.pk)}


def andamento_trimestri():
    """
    Totali cumulati della flotta per trimestre (somma di tutte le macchine).
    Ritorna lista ordinata: [{trimestre, a4_bn, a3_bn, a4_col, a3_col,
    bn, col, a4, a3, totale}].
    """
    agg = defaultdict(lambda: defaultdict(int))
    presenti, attese = defaultdict(set), defaultdict(set)
    flotta = _letture_ordinate_per_macchina()
    ultimo = max((letture[-1].trimestre for letture in flotta.values()), default="")
    for m, letture in flotta.items():
        for l in letture:
            row = agg[l.trimestre]
            for c in CAMPI:
                row[c] += getattr(l, c)
            presenti[l.trimestre].add(m.pk)
        t = letture[0].trimestre
        while t <= ultimo:
            attese[t].add(m.pk)
            t = trimestre_successivo(t)
    out = []
    for trim in sorted(agg):
        r = agg[trim]
        bn = r["a4_bn"] + r["a3_bn"]
        col = r["a4_col"] + r["a3_col"]
        a4 = r["a4_bn"] + r["a4_col"]
        a3 = r["a3_bn"] + r["a3_col"]
        # Una MFC senza lettura nel trimestre abbassa il totale: va segnalato.
        out.append({"trimestre": trim, **r, "bn": bn, "col": col,
                    "a4": a4, "a3": a3, "totale": bn + col,
                    "macchine": len(presenti[trim]), "attese": len(attese[trim]),
                    "parziale": len(presenti[trim]) < len(attese[trim])})
    return out


def trimestre_successivo(trimestre):
    anno, q = map(int, _TRIMESTRE_RE.match(trimestre).groups())
    return f"{anno + 1}-Q1" if q == 4 else f"{anno}-Q{q + 1}"


def consumo_per_trimestre():
    """
    Copie effettivamente prodotte per trimestre = differenza tra le letture di due
    trimestri CONSECUTIVI di ogni macchina, sommata sulla flotta.

    - Coppia con un trimestre mancante in mezzo: le copie coprono piu' trimestri e
      non si attribuiscono a nessuno (la macchina manca in entrambi).
    - Contatore sceso (refuso o azzeramento): quel contatore conta 0 nel trimestre
      e finisce in `anomalie`; gli altri della stessa macchina restano.
    Ogni riga dice quante MFC hanno contribuito (`macchine`) su quante ne erano
    attese (`attese`): `parziale` se ne manca qualcuna, `in_corso` per il trimestre
    corrente. Ritorna (per_trimestre, anomalie).
    """
    delta_trim = defaultdict(lambda: defaultdict(int))
    contributi, attese = defaultdict(set), defaultdict(set)
    anomalie = 0
    flotta = _letture_ordinate_per_macchina()
    ultimo = max((letture[-1].trimestre for letture in flotta.values()), default="")
    for m, letture in flotta.items():
        per_trim = {l.trimestre: l for l in letture}
        # Una MFC attiva e' attesa in ogni trimestre dopo la sua prima lettura.
        t = trimestre_successivo(letture[0].trimestre)
        while t <= ultimo:
            attese[t].add(m.pk)
            t = trimestre_successivo(t)
        for curr in letture[1:]:
            prec = per_trim.get(trimestre_precedente(curr.trimestre))
            if prec is None:
                continue
            contributi[curr.trimestre].add(m.pk)
            for c in CAMPI:
                d = getattr(curr, c) - getattr(prec, c)
                if d < 0:  # calo di un contatore: conta 0, gli altri restano validi
                    anomalie += 1
                    d = 0
                delta_trim[curr.trimestre][c] += d
    corrente = trimestre_corrente()
    out = []
    for trim in sorted(set(attese) | set(delta_trim)):
        r = delta_trim[trim]
        bn = r["a4_bn"] + r["a3_bn"]
        col = r["a4_col"] + r["a3_col"]
        out.append({"trimestre": trim, "bn": bn, "col": col,
                    "totale": bn + col, "a4_bn": r["a4_bn"], "a3_bn": r["a3_bn"],
                    "a4_col": r["a4_col"], "a3_col": r["a3_col"],
                    "macchine": len(contributi[trim]), "attese": len(attese[trim]),
                    "parziale": len(contributi[trim]) < len(attese[trim]),
                    "in_corso": trim >= corrente})
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
    Ripartizione BN/Colore e A4/A3 sui totali cumulati della flotta: per ogni MFC
    attiva l'ultima lettura disponibile (un trimestre con poche letture non deve
    falsare il mix). Ritorna percentuali intere che sommano ~100.
    """
    ultime = [letture[-1] for letture in _letture_ordinate_per_macchina().values()]
    if not ultime:
        return {"bn": 0, "col": 0, "a4": 0, "a3": 0, "totale": 0}
    r = {c: sum(getattr(l, c) for l in ultime) for c in CAMPI}
    totale = sum(r.values())
    tot = totale or 1
    return {
        "trimestre": max(l.trimestre for l in ultime),
        "totale": totale,
        "macchine": len(ultime),
        "bn_pct": round(100 * (r["a4_bn"] + r["a3_bn"]) / tot),
        "col_pct": round(100 * (r["a4_col"] + r["a3_col"]) / tot),
        "a4_pct": round(100 * (r["a4_bn"] + r["a4_col"]) / tot),
        "a3_pct": round(100 * (r["a3_bn"] + r["a3_col"]) / tot),
    }


def abbina_discovery(trovati):
    """Incrocia i dispositivi trovati in rete con l'anagrafica Macchine.

    L'abbinamento e' sulla MATRICOLA (numero di serie letto via SNMP): e' l'unico
    identificatore stabile — l'IP puo' essere cambiato, ed e' proprio quello che
    vogliamo scoprire.

    Stato per riga:
      "ok"         gia' in anagrafica, IP coincidente
      "ip_diverso" gia' in anagrafica ma con IP differente (o mancante) -> da correggere
      "nuova"      risponde in rete ma non e' in anagrafica
    """
    per_matricola = {
        (m.matricola or "").strip().upper(): m
        for m in Macchina.objects.select_related("asset")
        if (m.matricola or "").strip()
    }
    righe = []
    for dev in trovati:
        matricola = (dev.get("matricola") or "").strip().upper()
        macchina = per_matricola.get(matricola) if matricola else None
        if macchina is None:
            stato = "nuova"
        elif macchina.host and str(macchina.host) == dev["host"]:
            stato = "ok"
        else:
            stato = "ip_diverso"
        righe.append({**dev, "macchina": macchina, "stato": stato})
    # prima le anomalie: sono quelle su cui devi agire
    ordine = {"ip_diverso": 0, "nuova": 1, "ok": 2}
    righe.sort(key=lambda r: (ordine[r["stato"]], r["host"]))
    return righe


# --- Centrale SNMP ---------------------------------------------------------

def _tempo_ms(inizio):
    return max(0, round((perf_counter() - inizio) * 1000))


def _ticks(valore):
    """puresnmp (PyWrapper) restituisce i TimeTicks come timedelta: tornano centesimi."""
    if isinstance(valore, timedelta):
        return round(valore.total_seconds() * 100)
    return valore


def _intero_grezzo(valore):
    valore = _ticks(valore)
    try:
        return int(valore)
    except (TypeError, ValueError):
        try:
            return int(str(valore).strip())
        except (TypeError, ValueError):
            return None


def _numero_sonda(sonda, valore):
    try:
        numero = Decimal(str(_ticks(valore)).strip())
        if not numero.is_finite():
            return None
        if sonda.tipo_valore == SondaSNMP.TipoValore.TIMETICKS:
            numero /= Decimal("100")
        numero *= sonda.fattore
        if not numero.is_finite() or abs(numero) >= Decimal("1e24"):
            return None
        return numero
    except (InvalidOperation, Overflow, TypeError, ValueError):
        return None


MAX_OID_RICONOSCIMENTO = 20


def oid_riconoscimento_attivi():
    """OID di riconoscimento dei profili attivi, da leggere con GET se il device non ha profilo."""
    return list(dict.fromkeys(
        ProfiloSNMP.objects.filter(attivo=True).exclude(oid_riconoscimento="")
        .order_by("pk").values_list("oid_riconoscimento", flat=True)[:MAX_OID_RICONOSCIMENTO]
    ))


def trova_profilo_snmp(*, sys_object_id="", sys_description="", valori_riconoscimento=None):
    """Restituisce il profilo attivo piu specifico compatibile con l'identita'.

    Un profilo il cui ``oid_riconoscimento`` ha risposto con un valore prevale su
    prefisso e pattern: serve per apparati con sysObjectID generico.
    """
    object_id = str(sys_object_id or "").strip().lstrip(".")
    description = str(sys_description or "")
    risposte = {
        oid for oid, valore in (valori_riconoscimento or {}).items()
        if valore is not None and str(valore).strip() not in ("", "b''")
    }
    if risposte:
        sondati = [
            p for p in ProfiloSNMP.objects.filter(attivo=True, oid_riconoscimento__in=risposte)
            .order_by("pk")
        ]
        if len(sondati) == 1:
            return sondati[0]
    candidati = []
    for profilo in ProfiloSNMP.objects.filter(attivo=True):
        prefix = (profilo.sys_object_id_prefix or "").strip().lstrip(".")
        prefix_match = bool(prefix) and (
            object_id == prefix or object_id.startswith(prefix + ".")
        )
        pattern_match = False
        if profilo.sys_descr_pattern:
            try:
                pattern_match = bool(re.search(
                    profilo.sys_descr_pattern, description, re.IGNORECASE,
                ))
            except re.error:
                continue
        if not prefix_match and not pattern_match:
            continue
        candidati.append((len(prefix) if prefix_match else 0, pattern_match, profilo))
    if not candidati:
        return None
    candidati.sort(key=lambda item: (item[0], item[1], item[2].pk), reverse=True)
    migliore = candidati[0]
    # Un PEN condiviso da famiglie diverse senza sysDescr discriminante non va
    # assegnato a caso (es. HP stampanti vs Aruba rete).
    if not migliore[1]:
        pari = [c for c in candidati if c[0] == migliore[0] and not c[1]]
        if len(pari) > 1:
            return None
    return migliore[2]


_CAMPI_SOGLIA = ("soglia_warning_min", "soglia_warning_max", "soglia_critica_min", "soglia_critica_max")


def _soglie_colonna(colonna):
    """Soglie ed etichette dei valori: viaggiano dalla colonna del profilo alla sonda."""
    return {**{campo: getattr(colonna, campo) for campo in _CAMPI_SOGLIA},
            "etichette": colonna.etichette}


def applica_profilo_dispositivo(dispositivo, profilo, *, sovrascrivi=False):
    """Associa un profilo e materializza le sue colonne come sonde riutilizzabili."""
    dispositivo.profilo_snmp = profilo
    campi = ["profilo_snmp", "aggiornato_il"]
    if not dispositivo.produttore:
        dispositivo.produttore = profilo.produttore
        campi.append("produttore")
    categoria = {
        ProfiloSNMP.Categoria.STAMPANTE: DispositivoSNMP.Categoria.STAMPANTE,
        ProfiloSNMP.Categoria.FIREWALL: DispositivoSNMP.Categoria.FIREWALL,
        ProfiloSNMP.Categoria.RETE: DispositivoSNMP.Categoria.RETE,
        ProfiloSNMP.Categoria.SERVER: DispositivoSNMP.Categoria.SERVER,
        ProfiloSNMP.Categoria.STORAGE: DispositivoSNMP.Categoria.STORAGE,
        ProfiloSNMP.Categoria.UPS: DispositivoSNMP.Categoria.UPS,
        ProfiloSNMP.Categoria.AMBIENTE: DispositivoSNMP.Categoria.AMBIENTE,
        ProfiloSNMP.Categoria.TVCC_NVR: DispositivoSNMP.Categoria.TVCC_NVR,
        ProfiloSNMP.Categoria.TVCC_TELECAMERA: DispositivoSNMP.Categoria.TVCC_TELECAMERA,
        ProfiloSNMP.Categoria.GENERICO: DispositivoSNMP.Categoria.ALTRO,
    }[profilo.categoria]
    # Un profilo generico non dice che apparato sia: il tipo scelto dall'utente resta.
    generico = profilo.categoria == ProfiloSNMP.Categoria.GENERICO
    if dispositivo.categoria != categoria and not (generico and dispositivo.categoria):
        dispositivo.categoria = categoria
        campi.append("categoria")
    if sovrascrivi or not dispositivo.versione:
        dispositivo.versione = profilo.versione
        campi.append("versione")
    if profilo.porta and (sovrascrivi or not dispositivo.porta):
        dispositivo.porta = profilo.porta
        campi.append("porta")
    if profilo.timeout and (sovrascrivi or not dispositivo.timeout):
        dispositivo.timeout = profilo.timeout
        campi.append("timeout")
    dispositivo.save(update_fields=list(dict.fromkeys(campi)))

    # Le sonde manuali restano intatte. Eliminiamo solo quelle generate da un
    # profilo precedente, altrimenti un cambio produttore lascerebbe OID non
    # pertinenti che trasformano ogni polling successivo in un falso warning.
    dispositivo.sonde.filter(
        profilo_colonna__isnull=False,
    ).exclude(profilo_colonna__profilo=profilo).delete()

    create_count = 0
    update_count = 0
    for colonna in profilo.colonne.filter(attiva=True):
        defaults = {
            "nome": colonna.nome,
            "profilo_colonna": colonna,
            "tipo_valore": colonna.tipo_valore,
            "modalita": colonna.modalita,
            "aggregazione": colonna.aggregazione,
            "unita": colonna.unita,
            "fattore": colonna.fattore,
            "ordine": colonna.ordine,
            "attiva": True,
            **_soglie_colonna(colonna),
        }
        _, created = SondaSNMP.objects.update_or_create(
            dispositivo=dispositivo, oid=colonna.oid,
            defaults=defaults if sovrascrivi else {**defaults, "nome": colonna.nome},
        )
        create_count += int(created)
        update_count += int(not created)
    return create_count, update_count


def _parametri_snmp(oggetto, cfg):
    community = getattr(oggetto, "community_salvata", None)
    profilo = getattr(oggetto, "profilo_snmp", None)
    porta = (getattr(oggetto, "snmp_porta", None)
             or getattr(oggetto, "porta", None)
             or (community.porta if community else None)
             or (profilo.porta if profilo else None) or cfg.port)
    versione = (getattr(oggetto, "snmp_versione", "")
                or getattr(oggetto, "versione", "")
                or (community.versione if community else "")
                or (profilo.versione if profilo else "") or cfg.version)
    timeout = (getattr(oggetto, "snmp_timeout", None)
               or getattr(oggetto, "timeout", None)
               or (profilo.timeout if profilo else None) or cfg.timeout)
    return porta, timeout, versione


def _community_snmp(oggetto, cfg):
    community = getattr(oggetto, "community_salvata", None)
    if community is not None:
        from .credential_crypto import decifra
        from .snmp import SNMPError
        if not community.attiva:
            raise SNMPError("Community salvata disattivata: aggiorna la configurazione dell'apparato.")
        try:
            return decifra(community.segreto_cifrato)
        except ValueError as e:
            raise SNMPError("Community salvata non decifrabile: aggiorna il catalogo.") from e
    return (
        getattr(oggetto, "snmp_community", "")
        or getattr(oggetto, "community", "")
        or cfg.community
    )


def _leggi_contatori_profilo(macchina, cfg):
    from .snmp import OID_CONTROLLO_MFC, PRT_LIFECOUNT, PRT_SERIAL, SNMPError, leggi_specifiche, \
        verifica_lettura_mfc

    colonne = list(macchina.profilo_snmp.colonne.filter(
        attiva=True,
    ).exclude(contatore_mfc=""))
    mappa = {c.contatore_mfc: c for c in colonne}
    mancanti = [chiave for chiave, _ in CONTATORI if chiave not in mappa]
    if mancanti:
        raise SNMPError(
            f"profilo '{macchina.profilo_snmp}' incompleto per letture MFC: "
            f"mancano {', '.join(mancanti)}. Le colonne standard restano monitorabili."
        )
    porta, timeout, versione = _parametri_snmp(macchina, cfg)
    specifiche = [{
        "oid": c.oid, "modalita": c.modalita, "aggregazione": c.aggregazione,
    } for c in colonne]
    # In coda: matricola e pagine totali si leggono dopo i contatori.
    specifiche += [{"oid": oid, "modalita": "GET", "aggregazione": "PRIMO"}
                   for oid in OID_CONTROLLO_MFC]
    valori, errori = leggi_specifiche(
        macchina.host, specifiche, community=_community_snmp(macchina, cfg), port=porta,
        timeout=timeout, version=versione,
    )
    out = {}
    for chiave, colonna in mappa.items():
        if colonna.oid not in valori:
            raise SNMPError(errori.get(colonna.oid) or f"OID {colonna.oid} senza risposta")
        numero = _intero_grezzo(valori[colonna.oid])
        if numero is None or numero < 0:
            raise SNMPError(f"contatore {chiave} non numerico o negativo")
        out[chiave] = int(Decimal(numero) * colonna.fattore)
    verifica_lettura_mfc(macchina, out, seriale=valori.get(PRT_SERIAL),
                         pagine_totali=_intero_grezzo(valori.get(PRT_LIFECOUNT)))
    return out


def _lettura_piu_recente(macchina):
    """(descrizione, lettura) dell'ultima lettura salvata, trimestrale o mensile."""
    trimestrale = macchina.letture.order_by("-data", "-trimestre").first()
    mensile = macchina.letture_mensili.order_by("-rilevata_il").first()
    candidati = []
    if trimestrale is not None:
        candidati.append((trimestrale.data, 0, f"lettura {trimestrale.trimestre} del "
                          f"{trimestrale.data:%d/%m/%Y} ({trimestrale.get_fonte_display().lower()})",
                          trimestrale))
    if mensile is not None:
        quando = timezone.localtime(mensile.rilevata_il)
        candidati.append((quando.date(), 1, f"lettura mensile del {quando:%d/%m/%Y %H:%M}", mensile))
    if not candidati:
        return None, None
    _, _, descrizione, lettura = max(candidati, key=lambda c: (c[0], c[1]))
    return descrizione, lettura


def incoerenze_lettura(macchina, valori):
    """Contatori piu' bassi dell'ultima lettura salvata: [testo]. Un contatore non scende.

    Si confronta solo con l'ultima lettura (non con il massimo storico): dopo un
    azzeramento confermato a mano le letture ripartono da quella.
    """
    descrizione, ultima = _lettura_piu_recente(macchina)
    if ultima is None:
        return []
    return [f"{etichetta} {valori[campo]} più basso della {descrizione}: {getattr(ultima, campo)}"
            for campo, etichetta in CONTATORI
            if campo in valori and valori[campo] < getattr(ultima, campo)]


def _segna_errore_snmp(macchina, testo):
    macchina.snmp_stato = StatoSNMP.ERROR
    macchina.snmp_ultimo_errore = testo[:500]
    macchina.save(update_fields=["snmp_stato", "snmp_ultimo_errore"])


def verifica_progressione(macchina, valori):
    """Solleva SNMPError (e lo segna sulla MFC) se la lettura scende sotto l'ultima salvata."""
    from .snmp import SNMPError

    incoerenze = incoerenze_lettura(macchina, valori)
    if incoerenze:
        testo = ("Lettura scartata, contatori più bassi dell'ultima lettura salvata ("
                 + "; ".join(incoerenze) + "). Correggi la lettura sbagliata oppure "
                 "verifica IP e profilo della MFC.")
        _segna_errore_snmp(macchina, testo)
        raise SNMPError(testo)


def interroga_macchina(macchina):
    """Legge una MFC, aggiorna la salute SNMP e ritorna i quattro contatori.

    Non salva una :class:`LetturaContatori`: il chiamante decide se si tratta di
    un semplice test o della rilevazione trimestrale ufficiale.
    """
    from .snmp import SNMPError, leggi_macchina

    cfg = ImpostazioniSNMP.get_solo()
    inizio = perf_counter()
    try:
        if macchina.profilo_snmp_id:
            valori = _leggi_contatori_profilo(macchina, cfg)
        else:
            porta, timeout, versione = _parametri_snmp(macchina, cfg)
            valori = leggi_macchina(
                macchina, community=_community_snmp(macchina, cfg), port=porta,
                timeout=timeout, version=versione,
            )
    except SNMPError as exc:
        macchina.snmp_stato = StatoSNMP.ERROR
        macchina.snmp_ultimo_controllo = timezone.now()
        macchina.snmp_tempo_risposta_ms = _tempo_ms(inizio)
        macchina.snmp_ultimo_errore = errori_snmp.testo_con_codice(exc)
        macchina.save(update_fields=[
            "snmp_stato", "snmp_ultimo_controllo", "snmp_tempo_risposta_ms",
            "snmp_ultimo_errore",
        ])
        raise
    macchina.snmp_stato = StatoSNMP.OK
    macchina.snmp_ultimo_controllo = timezone.now()
    macchina.snmp_tempo_risposta_ms = _tempo_ms(inizio)
    macchina.snmp_ultimo_errore = ""
    macchina.save(update_fields=[
        "snmp_stato", "snmp_ultimo_controllo", "snmp_tempo_risposta_ms",
        "snmp_ultimo_errore",
    ])
    return valori


@transaction.atomic
def interroga_dispositivo(dispositivo):
    """Interroga identita' e sonde di un dispositivo e storicizza l'esito."""
    from .snmp import (
        SNMPError,
        PRT_SERIAL,
        SYS_DESCR,
        SYS_NAME,
        SYS_OBJECT_ID,
        SYS_UPTIME,
        SYSTEM_OIDS,
        _testo,
        leggi_specifiche,
    )

    cfg = ImpostazioniSNMP.get_solo()
    sonde = list(dispositivo.sonde.filter(attiva=True))
    # Solo finche' il device non ha profilo: OID di riconoscimento dei profili.
    probe_oids = [] if dispositivo.profilo_snmp_id else [
        oid for oid in oid_riconoscimento_attivi() if oid not in SYSTEM_OIDS
    ]
    specifiche = [
        {"oid": oid, "modalita": "GET", "aggregazione": "PRIMO"}
        for oid in (*SYSTEM_OIDS, *probe_oids)
    ] + [
        {
            "oid": sonda.oid, "modalita": sonda.modalita,
            "aggregazione": sonda.aggregazione,
        }
        for sonda in sonde
    ]
    porta, timeout, versione = _parametri_snmp(dispositivo, cfg)
    inizio = perf_counter()
    adesso = timezone.now()

    try:
        valori, errori = leggi_specifiche(
            dispositivo.host, specifiche, community=_community_snmp(dispositivo, cfg), port=porta,
            timeout=timeout, version=versione,
        )
    except SNMPError as exc:
        durata = _tempo_ms(inizio)
        rilevazione = RilevazioneSNMP.objects.create(
            dispositivo=dispositivo, rilevata_il=adesso,
            stato=StatoSNMP.ERROR, tempo_risposta_ms=durata,
            errore=errori_snmp.testo_con_codice(exc),
        )
        dispositivo.snmp_stato = StatoSNMP.ERROR
        dispositivo.snmp_ultimo_controllo = adesso
        dispositivo.snmp_tempo_risposta_ms = durata
        dispositivo.snmp_ultimo_errore = errori_snmp.testo_con_codice(exc)
        dispositivo.save(update_fields=[
            "snmp_stato", "snmp_ultimo_controllo", "snmp_tempo_risposta_ms",
            "snmp_ultimo_errore", "aggiornato_il",
        ])
        soc.valuta(dispositivo)
        return rilevazione

    sys_name = _testo(valori.get(SYS_NAME))
    sys_description = _testo(valori.get(SYS_DESCR))
    sys_object_id = _testo(valori.get(SYS_OBJECT_ID))
    seriale = _testo(valori.get(PRT_SERIAL))
    uptime_ticks = _intero_grezzo(valori.get(SYS_UPTIME))
    uptime_seconds = max(0, uptime_ticks // 100) if uptime_ticks is not None else None

    # Riconosce e configura prima di salvare i valori: il primo polling deve
    # gia' leggere le sonde appena create. Mantiene la versione che ha risposto.
    if not dispositivo.profilo_snmp_id:
        profilo = trova_profilo_snmp(
            sys_object_id=sys_object_id, sys_description=sys_description,
            valori_riconoscimento={oid: valori.get(oid) for oid in probe_oids if oid in valori},
        )
        if profilo is not None:
            if not dispositivo.versione:
                dispositivo.versione = versione
                dispositivo.save(update_fields=["versione"])
            applica_profilo_dispositivo(dispositivo, profilo)
    if dispositivo.profilo_snmp_id:
        # Ripara anche apparati gia' configurati con profilo ma privi di sonde.
        # Non sovrascrive sonde personalizzate o disattivate dall'operatore.
        for colonna in dispositivo.profilo_snmp.colonne.filter(attiva=True):
            dispositivo.sonde.get_or_create(oid=colonna.oid, defaults={
                "nome": colonna.nome, "profilo_colonna": colonna,
                "tipo_valore": colonna.tipo_valore, "modalita": colonna.modalita,
                "aggregazione": colonna.aggregazione, "unita": colonna.unita,
                "fattore": colonna.fattore, "ordine": colonna.ordine,
                **_soglie_colonna(colonna),
            })
    nuove_sonde = list(dispositivo.sonde.filter(attiva=True).exclude(
        pk__in=[s.pk for s in sonde],
    ))
    if nuove_sonde:
        try:
            nuovi_valori, nuovi_errori = leggi_specifiche(
                dispositivo.host, [{
                    "oid": s.oid, "modalita": s.modalita,
                    "aggregazione": s.aggregazione,
                } for s in nuove_sonde],
                community=_community_snmp(dispositivo, cfg), port=porta,
                timeout=timeout, version=versione,
            )
            valori.update(nuovi_valori)
            errori.update(nuovi_errori)
        except SNMPError as exc:
            errori.update({s.oid: errori_snmp.testo_con_codice(exc) for s in nuove_sonde})
        sonde.extend(nuove_sonde)

    stampante = (
        dispositivo.categoria == DispositivoSNMP.Categoria.STAMPANTE
        or (dispositivo.profilo_snmp_id and
            dispositivo.profilo_snmp.categoria == ProfiloSNMP.Categoria.STAMPANTE)
        or (not dispositivo.profilo_snmp_id and bool(re.search(
            r"\b(printer|TASKalfa|ECOSYS|LaserJet|imageRUNNER)\b",
            sys_description, re.IGNORECASE,
        )))
    )
    dati_stampante = {}
    if stampante:
        from .printer_snmp import leggi_stampante

        try:
            dati_stampante = leggi_stampante(
                dispositivo, community=_community_snmp(dispositivo, cfg),
                port=porta, timeout=timeout, version=versione,
            )
        except SNMPError as exc:
            dati_stampante = {"contatori": [], "consumabili": [],
                              "errori": {"lettura": errori_snmp.testo_con_codice(exc)}}
        if dispositivo.categoria != DispositivoSNMP.Categoria.STAMPANTE:
            dispositivo.categoria = DispositivoSNMP.Categoria.STAMPANTE
            dispositivo.save(update_fields=["categoria"])

    durata = _tempo_ms(inizio)

    esiti = []
    from .printer_snmp import consumabili_in_esaurimento

    ha_warning = bool(stampante and (
        dati_stampante.get("errori") or not dati_stampante.get("contatori")
        or not dati_stampante.get("consumabili")
        or consumabili_in_esaurimento(dati_stampante)
    ))
    ha_critico = False
    for sonda in sonde:
        if sonda.oid not in valori:
            ha_warning = True
            esiti.append({
                "sonda": sonda, "numero": None, "testo": "",
                "stato": StatoSNMP.ERROR,
                "errore": (errori.get(sonda.oid) or "OID senza risposta")[:500],
            })
            continue
        grezzo = valori[sonda.oid]
        if sonda.tipo_valore == SondaSNMP.TipoValore.ERRORI_STAMPANTE:
            from .printer_snmp import decodifica_errori_stampante

            testo, stato = decodifica_errori_stampante(grezzo)
            ha_warning = ha_warning or stato == StatoSNMP.WARNING
            ha_critico = ha_critico or stato == StatoSNMP.ERROR
            esiti.append({
                "sonda": sonda, "numero": None, "testo": testo,
                "stato": stato, "errore": "",
            })
            continue
        if sonda.tipo_valore == SondaSNMP.TipoValore.MAC:
            from assets.services.mac import normalizza_mac

            mac = normalizza_mac(grezzo)
            ha_warning = ha_warning or not mac
            esiti.append({
                "sonda": sonda, "numero": None, "testo": mac,
                "stato": StatoSNMP.OK if mac else StatoSNMP.ERROR,
                "errore": "" if mac else "Valore non riconosciuto come MAC",
            })
            continue
        if sonda.tipo_valore == SondaSNMP.TipoValore.TESTO:
            esiti.append({
                "sonda": sonda, "numero": None, "testo": _testo(grezzo),
                "stato": StatoSNMP.OK, "errore": "",
            })
            continue
        numero = _numero_sonda(sonda, grezzo)
        if numero is None:
            ha_warning = True
            esiti.append({
                "sonda": sonda, "numero": None, "testo": _testo(grezzo),
                "stato": StatoSNMP.ERROR,
                "errore": "Valore non numerico"[:500],
            })
            continue
        stato = sonda.stato_per_valore(numero)
        ha_warning = ha_warning or stato == StatoSNMP.WARNING
        ha_critico = ha_critico or stato == StatoSNMP.ERROR
        esiti.append({
            "sonda": sonda, "numero": numero, "testo": "",
            "stato": stato, "errore": "",
        })

    stato_generale = (
        StatoSNMP.ERROR if ha_critico else
        # Gli OID di sistema opzionali non determinano lo stato: molti device
        # non espongono contact/location. Contano le sonde configurate.
        StatoSNMP.WARNING if ha_warning else
        StatoSNMP.OK
    )
    rilevazione = RilevazioneSNMP.objects.create(
        dispositivo=dispositivo, rilevata_il=adesso, stato=stato_generale,
        tempo_risposta_ms=durata, sys_name=sys_name,
        sys_description=sys_description, sys_object_id=sys_object_id,
        sys_uptime_seconds=uptime_seconds,
        dati_stampante=dati_stampante,
    )
    ValoreSNMP.objects.bulk_create([
        ValoreSNMP(
            rilevazione=rilevazione, sonda=e["sonda"],
            valore_numero=e["numero"], valore_testo=e["testo"],
            stato=e["stato"], errore=e["errore"],
        )
        for e in esiti
    ])

    dispositivo.snmp_stato = stato_generale
    dispositivo.snmp_ultimo_controllo = adesso
    dispositivo.snmp_tempo_risposta_ms = durata
    dispositivo.snmp_ultimo_errore = ""
    dispositivo.sys_name = sys_name
    dispositivo.sys_description = sys_description
    dispositivo.sys_object_id = sys_object_id
    dispositivo.sys_uptime_seconds = uptime_seconds
    update_fields = [
        "snmp_stato", "snmp_ultimo_controllo", "snmp_tempo_risposta_ms",
        "snmp_ultimo_errore", "sys_name", "sys_description", "sys_object_id",
        "sys_uptime_seconds", "aggiornato_il",
    ]
    if seriale and not dispositivo.matricola:
        dispositivo.matricola = seriale
        update_fields.append("matricola")
    from . import firmware

    versione_fw, fonte_fw = firmware.estrai(sys_description, esiti)
    update_fields += firmware.registra(dispositivo, versione_fw, fonte_fw, adesso)
    if versione_fw:
        transaction.on_commit(lambda: firmware.invia_al_soc(dispositivo))
    if not dispositivo.verificato:
        # Prima lettura riuscita di una bozza o di un dispositivo creato senza test.
        dispositivo.verificato = True
        update_fields.append("verificato")
    dispositivo.save(update_fields=[
        *update_fields,
    ])
    soc.valuta(dispositivo)
    return rilevazione


def leggi_mensile_macchina(macchina, *, mese=None):
    """Conserva la prima lettura riuscita del mese; i retry non sovrascrivono dati."""
    mese_corrente = timezone.localdate().replace(day=1)
    mese = mese or mese_corrente
    precedente = LetturaMensileContatori.objects.filter(macchina=macchina, mese=mese).first()
    if precedente is not None:
        return precedente, False
    if mese != mese_corrente:
        raise ValueError("Non è possibile ricostruire via SNMP una lettura di un mese passato o futuro.")
    valori = interroga_macchina(macchina)
    verifica_progressione(macchina, valori)
    rilevata_il = timezone.now()
    if timezone.localdate(rilevata_il).replace(day=1) != mese:
        raise ValueError("Il mese è cambiato durante la lettura: ripetere nel mese corrente.")
    return LetturaMensileContatori.objects.get_or_create(
        macchina=macchina, mese=mese,
        defaults={**valori, "rilevata_il": rilevata_il},
    )


def salva_letture_trimestrali_snmp(oggi=None):
    """Lettura SNMP del trimestre corrente di tutte le MFC attive con IP.

    Unico punto usato da «Leggi MFC ora» e da ``manage.py leggi_contatori``. Non
    sovrascrive letture manuali o da fattura; scarta matricola diversa, somma oltre
    le pagine totali (``interroga_macchina``) e contatori sotto l'ultima lettura.
    """
    from .snmp import SNMPError

    oggi = oggi or timezone.localdate()
    trimestre = trimestre_lettura_snmp(oggi)
    presenti = {l.macchina_id: l for l in LetturaContatori.objects.filter(trimestre=trimestre)}
    esito = {"trimestre": trimestre, "lette": 0, "manuali": [], "incoerenti": [], "errori": []}
    for m in Macchina.objects.filter(attiva=True).exclude(host__isnull=True).order_by("reparto"):
        esistente = presenti.get(m.id)
        if esistente and esistente.fonte != LetturaContatori.Fonte.SNMP:
            esito["manuali"].append(m.reparto)
            continue
        try:
            valori = interroga_macchina(m)
        except SNMPError as e:
            esito["errori"].append(f"{m.reparto} ({e})")
            continue
        try:
            verifica_progressione(m, valori)
        except SNMPError:
            esito["incoerenti"].append(m.reparto)
            continue
        with transaction.atomic():
            # La lettura SNMP dura secondi: nel frattempo qualcuno puo' aver salvato a mano.
            esistente = (LetturaContatori.objects.select_for_update()
                         .filter(macchina=m, trimestre=trimestre).first())
            if esistente and esistente.fonte != LetturaContatori.Fonte.SNMP:
                esito["manuali"].append(m.reparto)
                continue
            LetturaContatori.objects.update_or_create(
                macchina=m, trimestre=trimestre,
                defaults={**valori, "data": oggi, "fonte": LetturaContatori.Fonte.SNMP})
        esito["lette"] += 1
    return esito


def trimestre_lettura_snmp(oggi):
    """Trimestre a cui va una lettura SNMP fatta il giorno `oggi`.

    Nei primi ``GIORNI_RECUPERO_MENSILE`` giorni di un trimestre i contatori sono la
    chiusura del precedente (stessa regola delle letture mensili proposte): salvarli
    nel trimestre appena iniziato darebbe al nuovo trimestre una lettura di inizio
    periodo e lascerebbe senza chiusura quello appena finito.
    """
    trimestre = trimestre_di(oggi)
    if oggi.month in (1, 4, 7, 10) and oggi.day <= GIORNI_RECUPERO_MENSILE:
        return trimestre_precedente(trimestre)
    return trimestre


def centrale_snmp_riepilogo():
    """KPI compatti della centrale, inclusi MFC e dispositivi generici."""
    mfc = Macchina.objects.filter(attiva=True)
    dispositivi = DispositivoSNMP.objects.filter(attivo=True)
    stati = list(mfc.values_list("snmp_stato", flat=True))
    stati += list(dispositivi.values_list("snmp_stato", flat=True))
    totale = len(stati)
    configurati = mfc.exclude(host__isnull=True).count() + dispositivi.count()
    return {
        "totale": totale,
        "configurati": configurati,
        "ok": stati.count(StatoSNMP.OK),
        "warning": stati.count(StatoSNMP.WARNING),
        "errori": stati.count(StatoSNMP.ERROR),
        "mai": stati.count(StatoSNMP.MAI),
        "sonde": SondaSNMP.objects.filter(attiva=True, dispositivo__attivo=True).count(),
    }


# --- Cruscotto operativo ------------------------------------------------------

# --- Stato flotta e schede info -----------------------------------------------

# Un apparato non interrogato da piu' di N giorni non e' "operativo": il dato e' vecchio.
SNMP_NON_INTERROGATO_GIORNI = 3

# Categorie esclusive dei riquadri della Centrale, nell'ordine in cui si valutano:
# l'errore prevale, poi il dato vecchio, poi lo stato dell'ultimo controllo.
FLOTTA = {
    "errore": "In errore",
    "non_interrogati": f"Non interrogati da oltre {SNMP_NON_INTERROGATO_GIORNI} giorni",
    "attenzione": "In attenzione",
    "ok": "Operativi",
}


def filtra_flotta(qs, chiave, ora=None):
    """Restringe MFC o dispositivi SNMP alla categoria `chiave` di FLOTTA.

    Stessa funzione per il conteggio del riquadro e per la lista filtrata,
    cosi' i due numeri coincidono sempre.
    """
    from django.db.models import Q
    soglia = (ora or timezone.now()) - timedelta(days=SNMP_NON_INTERROGATO_GIORNI)
    vecchio = (Q(snmp_ultimo_controllo__isnull=True) | Q(snmp_ultimo_controllo__lt=soglia)
               | Q(snmp_stato=StatoSNMP.MAI))
    if chiave == "errore":
        return qs.filter(snmp_stato=StatoSNMP.ERROR)
    qs = qs.exclude(snmp_stato=StatoSNMP.ERROR)
    if chiave == "non_interrogati":
        return qs.filter(vecchio)
    qs = qs.exclude(vecchio)
    if chiave == "ok":
        return qs.filter(snmp_stato=StatoSNMP.OK)
    return qs.filter(snmp_stato=StatoSNMP.WARNING)  # attenzione


def flotta_monitorata():
    """(MFC, dispositivi) monitorati via SNMP: attivi e, per le MFC, con IP."""
    return (Macchina.objects.filter(attiva=True, host__isnull=False),
            DispositivoSNMP.objects.filter(attivo=True))


def stato_flotta(ora=None):
    """Conteggi esclusivi della flotta per i riquadri della Centrale."""
    mfc, dispositivi = flotta_monitorata()
    out = {chiave: filtra_flotta(mfc, chiave, ora).count() + filtra_flotta(dispositivi, chiave, ora).count()
           for chiave in FLOTTA}
    out["totale"] = sum(out[k] for k in FLOTTA)
    out["giorni"] = SNMP_NON_INTERROGATO_GIORNI
    return out


def ultimi_errori_snmp(limite=6):
    """Apparati attualmente in errore con la causa registrata, i piu' recenti prima."""
    from django.urls import reverse
    mfc, dispositivi = flotta_monitorata()
    righe = [{"nome": m.reparto, "tipo": "MFC", "quando": m.snmp_ultimo_controllo,
              "errore": m.snmp_ultimo_errore or "Errore senza dettaglio registrato.",
              "url": reverse("contatori:macchina", args=[m.pk])}
             for m in mfc.filter(snmp_stato=StatoSNMP.ERROR).order_by("-snmp_ultimo_controllo")[:limite]]
    righe += [{"nome": d.nome, "tipo": d.get_categoria_display(), "quando": d.snmp_ultimo_controllo,
               "errore": d.snmp_ultimo_errore or "Errore senza dettaglio registrato.",
               "url": reverse("contatori:snmp_dispositivo", args=[d.pk])}
              for d in dispositivi.filter(snmp_stato=StatoSNMP.ERROR).order_by("-snmp_ultimo_controllo")[:limite]]
    # Senza data di controllo in fondo: (False, 0) < (True, datetime).
    righe.sort(key=lambda r: (r["quando"] is not None, r["quando"] or 0), reverse=True)
    return righe[:limite]


def fatture_da_riconciliare(ultimi=4):
    """Trimestri recenti con fattura caricata la cui riconciliazione non torna."""
    # order_by() vuoto: il Meta.ordering di Fattura romperebbe il DISTINCT su SQL Server.
    trimestri = sorted(set(Fattura.objects.order_by().values_list("trimestre", flat=True)), reverse=True)
    out = []
    for trimestre in trimestri[:ultimi]:
        riepilogo = riconcilia(trimestre)[1]
        if riepilogo["anomalie"] or riepilogo["letture_mancanti"] or not riepilogo["contatori"]:
            out.append(riepilogo)
    return out


def info_snmp(oggetto):
    """Parametri SNMP effettivi di una MFC o di un dispositivo, senza segreti."""
    cfg = ImpostazioniSNMP.get_solo()
    porta, timeout, versione = _parametri_snmp(oggetto, cfg)
    community = getattr(oggetto, "community_salvata", None)
    if community is not None:
        credenziali = f"Catalogo: {community.nome}" + ("" if community.attiva else " (disattivata)")
    elif getattr(oggetto, "snmp_community", "") or getattr(oggetto, "community", ""):
        credenziali = "Community dedicata dell'apparato"
    else:
        credenziali = "Community globale"
    etichette = dict(ProfiloSNMP.Versione.choices)
    return {"porta": porta, "timeout": timeout, "versione": etichette.get(versione, versione),
            "credenziali": credenziali}


def trimestre_precedente(trimestre):
    anno, q = map(int, _TRIMESTRE_RE.match(trimestre).groups())
    return f"{anno - 1}-Q4" if q == 1 else f"{anno}-Q{q - 1}"


def cruscotto_operativo(oggi=None):
    """KPI e attivita' in sospeso della Centrale, ognuna con il link per risolverla.

    Solo dati gia' a DB: nessuna interrogazione SNMP all'apertura della pagina.
    """
    from django.urls import reverse

    oggi = oggi or timezone.localdate()
    trim = trimestre_di(oggi)
    prec = trimestre_precedente(trim)
    attive = list(Macchina.objects.filter(attiva=True).order_by("reparto"))
    con_lettura = set(LetturaContatori.objects.filter(trimestre=trim, macchina__in=attive)
                      .values_list("macchina_id", flat=True))
    senza_lettura = [m for m in attive if m.id not in con_lettura]
    non_raggiungibili = [m for m in attive if m.host and m.snmp_stato == StatoSNMP.ERROR]
    dispositivi = DispositivoSNMP.objects.filter(attivo=True)
    disp_errore = dispositivi.filter(snmp_stato=StatoSNMP.ERROR).count()
    disp_attenzione = dispositivi.filter(snmp_stato=StatoSNMP.WARNING).count()

    fattura_prec = Fattura.objects.filter(trimestre=prec).exists()
    riconc = riconcilia(prec)[1] if fattura_prec else None
    letture_prec = LetturaContatori.objects.filter(trimestre=prec).exists()

    # Raccolta il giorno 1 alle 00:00, poi recupero ogni 15 minuti fino al giorno 7.
    mese = oggi.replace(day=1)
    lette = set(LetturaMensileContatori.objects.filter(mese=mese).values_list("macchina_id", flat=True))
    mensili_mancanti = [m for m in attive if m.host and m.id not in lette]

    consumo, _ = consumo_per_trimestre()
    # Solo trimestri chiusi: il corrente ha poche letture e falserebbe il confronto.
    chiusi = [r for r in consumo if not r["in_corso"]]
    ultimo = chiusi[-1] if chiusi else None
    precedente = chiusi[-2] if len(chiusi) > 1 else None
    variazione = None
    if (ultimo and precedente and precedente["totale"]
            and not ultimo["parziale"] and not precedente["parziale"]):
        variazione = round((ultimo["totale"] - precedente["totale"]) * 100 / precedente["totale"])
    cali = controllo_monotonia()

    def nomi(macchine, n=4):
        testo = ", ".join(m.reparto for m in macchine[:n])
        return testo + (f" e altre {len(macchine) - n}" if len(macchine) > n else "")

    da_fare = []
    if senza_lettura:
        da_fare.append({"livello": "warn", "titolo": f"{len(senza_lettura)} MFC senza lettura {trim}",
                        "dettaglio": nomi(senza_lettura), "azione": "Inserisci lettura", "scrittura": True,
                        "url": f"{reverse('contatori:importa_lettura')}?macchina={senza_lettura[0].pk}&trimestre={trim}"})
    if letture_prec and not fattura_prec:
        da_fare.append({"livello": "warn", "titolo": f"Fattura {prec} non caricata",
                        "dettaglio": "Senza fattura la riconciliazione del trimestre non parte.",
                        "azione": "Inserisci fattura", "scrittura": True, "url": f"{reverse('contatori:fattura_nuova')}?trimestre={prec}"})
    if riconc and (riconc["anomalie"] or riconc["letture_mancanti"]):
        parti = []
        if riconc["anomalie"]:
            parti.append(f"{riconc['anomalie']} contatori fatturati in eccesso")
        if riconc["letture_mancanti"]:
            parti.append(f"{riconc['letture_mancanti']} letture interne mancanti")
        da_fare.append({"livello": "danger" if riconc["anomalie"] else "warn",
                        "titolo": f"Riconciliazione {prec} da verificare", "dettaglio": ", ".join(parti),
                        "azione": "Apri riconciliazione", "url": reverse("contatori:riconciliazione_trim", args=[prec])})
    if cali:
        da_fare.append({"livello": "danger",
                        "titolo": "1 calo di lettura" if len(cali) == 1 else f"{len(cali)} cali di lettura",
                        "dettaglio": "Un contatore è sceso tra due trimestri: refuso o azzeramento.",
                        "azione": "Vedi elenco", "url": "#cali"})
    if non_raggiungibili:
        da_fare.append({"livello": "danger", "titolo": f"{len(non_raggiungibili)} MFC non raggiungibili",
                        "dettaglio": nomi(non_raggiungibili), "azione": "Verifica stampanti",
                        "url": reverse("contatori:macchine")})
    proposte = proposte_letture_trimestrali(prec)
    pronte = [p for p in proposte if not p["incoerente"]]
    if proposte:
        dettaglio = "Ricavate dalle letture SNMP mensili: controlla e conferma."
        if len(pronte) < len(proposte):
            dettaglio += f" {len(proposte) - len(pronte)} incoerenti con i trimestri vicini vanno inserite a mano."
        da_fare.append({"livello": "warn",
                        "titolo": ((f"1 lettura {prec} pronta dalle mensili" if len(pronte) == 1
                                    else f"{len(pronte)} letture {prec} pronte dalle mensili") if pronte
                                   else f"Letture {prec} dalle mensili da verificare"),
                        "dettaglio": dettaglio,
                        "azione": "Controlla e conferma", "scrittura": True,
                        "url": f"{reverse('contatori:letture_proposte')}?trimestre={prec}"})
    stati_cons = stato_consumabili([m for m in attive if m.host])
    da_ordinare = [m for m in attive if stati_cons.get(m.id) and stati_cons[m.id]["critici"]]
    if da_ordinare:
        dettagli = []
        for m in da_ordinare[:4]:
            v = min(stati_cons[m.id]["critici"], key=lambda x: x["pct"])
            dettagli.append(f"{m.reparto} ({v['nome']} {v['pct']}%)")
        da_fare.append({"livello": "warn", "titolo": f"{len(da_ordinare)} MFC con consumabili da ordinare",
                        "dettaglio": ", ".join(dettagli) + (f" e altre {len(da_ordinare) - 4}" if len(da_ordinare) > 4 else ""),
                        "azione": "Vedi consumabili", "url": reverse("contatori:consumabili")})
    if mensili_mancanti and oggi.day > GIORNI_RECUPERO_MENSILE:
        da_fare.append({"livello": "warn", "titolo": f"{len(mensili_mancanti)} letture mensili saltate",
                        "dettaglio": f"{oggi:%m/%Y}: {nomi(mensili_mancanti)}. Nessuna risposta dal giorno 1 al "
                                     f"{GIORNI_RECUPERO_MENSILE}: controlla che siano accese e in rete.",
                        "azione": "Verifica stampanti", "url": reverse("contatori:macchine")})
    elif mensili_mancanti and oggi.day >= 2:  # il giorno 1 la raccolta e' in corso
        da_fare.append({"livello": "warn", "titolo": f"{len(mensili_mancanti)} letture mensili in attesa",
                        "dettaglio": f"{oggi:%m/%Y}: {nomi(mensili_mancanti)}. Spente o non raggiungibili: "
                                     f"il portale riprova ogni 15 minuti fino al giorno {GIORNI_RECUPERO_MENSILE}.",
                        "azione": "Verifica stampanti", "url": reverse("contatori:macchine")})
    if disp_errore or disp_attenzione:
        da_fare.append({"livello": "danger" if disp_errore else "warn",
                        "titolo": f"{disp_errore + disp_attenzione} dispositivi SNMP da verificare",
                        "dettaglio": f"{disp_errore} in errore, {disp_attenzione} in attenzione.",
                        "azione": "Apri monitor",
                        "url": reverse("contatori:snmp_centrale") + ("?stato=ERROR" if disp_errore else "?stato=WARNING")})
    da_fare.sort(key=lambda x: x["livello"] != "danger")

    return {
        "trimestre": trim, "trimestre_prec": prec,
        "mfc_attive": len(attive), "letture_fatte": len(con_lettura),
        "senza_lettura_ids": {m.id for m in senza_lettura},
        "raggiungibili": sum(1 for m in attive if m.host and m.snmp_stato == StatoSNMP.OK),
        "con_host": sum(1 for m in attive if m.host),
        "consumo_ultimo": ultimo, "consumo_precedente": precedente, "variazione": variazione,
        "riconciliazione": riconc, "fattura_prec": fattura_prec,
        "cali": cali, "da_fare": da_fare,
        "proposte_pronte": len(pronte), "proposte_totali": len(proposte),
        "consumabili_critici": len(da_ordinare),
    }


def produzione_macchina(macchina, ultimi=8):
    """Copie prodotte per trimestre (differenza tra letture consecutive) di una MFC.

    [{trimestre, bn, col, totale, calo, manca, altezza}] sugli ultimi `ultimi`
    trimestri; `calo` = un contatore e' sceso (refuso o azzeramento), `manca` = il
    trimestre precedente non ha lettura: in entrambi i casi il valore non e'
    calcolabile. `altezza` = % della barra piu' alta.
    """
    letture = list(macchina.letture.order_by("trimestre"))
    righe = []
    for prec, curr in zip(letture, letture[1:]):
        delta = {c: getattr(curr, c) - getattr(prec, c) for c in CAMPI}
        calo = any(v < 0 for v in delta.values())
        # Trimestri non consecutivi: le copie coprono anche quello mancante.
        manca = "" if prec.trimestre == trimestre_precedente(curr.trimestre) \
            else trimestre_precedente(curr.trimestre)
        vuota = calo or bool(manca)
        bn = 0 if vuota else delta["a4_bn"] + delta["a3_bn"]
        col = 0 if vuota else delta["a4_col"] + delta["a3_col"]
        righe.append({"trimestre": curr.trimestre, "bn": bn, "col": col,
                      "totale": bn + col, "calo": calo, "manca": manca})
    righe = righe[-ultimi:]
    massimo = max((r["totale"] for r in righe), default=0) or 1
    for r in righe:
        # Stringa con il punto: finisce in uno style inline, indipendente dal locale.
        r["altezza"] = f"{r['totale'] * 100 / massimo:.1f}"
    return righe


# --- Consumabili: storico e stima -------------------------------------------

SOGLIA_CONSUMABILE_PCT = 15          # sotto questa soglia il consumabile va ordinato
_FINESTRA_STIMA_GIORNI = 60          # storico usato per il ritmo di consumo


def leggi_consumabili_macchina(macchina):
    """Legge i consumabili via SNMP con i parametri dell'MFC. Ritorna (lista, errore)."""
    from .snmp import SNMPError, leggi_consumabili
    cfg = ImpostazioniSNMP.get_solo()
    try:
        porta, timeout, versione = _parametri_snmp(macchina, cfg)
        return leggi_consumabili(macchina, community=_community_snmp(macchina, cfg), port=porta,
                                 timeout=timeout, version=versione), None
    except SNMPError as e:
        return None, errori_snmp.testo_con_codice(e)


def salva_consumabili(macchina, consumabili, quando=None):
    """Salva una lettura (una riga per consumabile). Senza consumabili non salva nulla."""
    quando = quando or timezone.now()
    righe = [LetturaConsumabile(macchina=macchina, nome=(c.get("nome") or "Consumabile")[:120],
                                pct=c["pct"] if type(c.get("pct")) is int and 0 <= c["pct"] <= 100 else None,
                                rilevata_il=quando)
             for c in (consumabili or [])[:30]]
    LetturaConsumabile.objects.bulk_create(righe)
    return len(righe)


def _stima_giorni(storico, ora):
    """Giorni al 0% dal ritmo di consumo dopo l'ultima sostituzione (pct risalito).

    `storico` = [(rilevata_il, pct)] crescente nel tempo, ultimo = valore attuale.
    None se il ritmo non e' stimabile (meno di 2 giorni di dati o nessun consumo).
    """
    validi = [(t, p) for t, p in storico if p is not None]
    if len(validi) < 2:
        return None
    # Ultima sostituzione: dopo l'ultimo punto in cui il livello e' risalito.
    inizio = 0
    for i in range(1, len(validi)):
        if validi[i][1] > validi[i - 1][1]:
            inizio = i
    tratto = validi[inizio:]
    (t0, p0), (t1, p1) = tratto[0], tratto[-1]
    giorni = (t1 - t0).total_seconds() / 86400
    if giorni < 2 or p0 <= p1:
        return None
    return max(0, round(p1 / ((p0 - p1) / giorni)))


def stato_consumabili(macchine, ora=None):
    """Ultimo livello salvato per ogni consumabile delle MFC, con stima giorni residui.

    {macchina_id: {"rilevata_il", "voci": [{nome, pct, giorni, critico}], "critici", "peggiore"}}
    Solo dati a DB: nessuna interrogazione SNMP.
    """
    from datetime import timedelta
    ora = ora or timezone.now()
    ids = [m.pk for m in macchine]
    storico = defaultdict(lambda: defaultdict(list))
    ultima = {}
    for macchina_id, nome, pct, quando in (
            LetturaConsumabile.objects.filter(macchina_id__in=ids,
                                              rilevata_il__gte=ora - timedelta(days=_FINESTRA_STIMA_GIORNI))
            .order_by("rilevata_il").values_list("macchina_id", "nome", "pct", "rilevata_il")):
        storico[macchina_id][nome].append((quando, pct))
        ultima[macchina_id] = max(ultima.get(macchina_id, quando), quando)
    out = {}
    for macchina_id, per_nome in storico.items():
        quando = ultima[macchina_id]
        voci = []
        for nome, serie in sorted(per_nome.items()):
            if serie[-1][0] != quando:
                continue  # consumabile non presente nell'ultima lettura (es. sostituito il modello)
            pct = serie[-1][1]
            voci.append({"nome": nome, "pct": pct, "giorni": _stima_giorni(serie, ora),
                         "critico": pct is not None and pct <= SOGLIA_CONSUMABILE_PCT})
        misurabili = [v for v in voci if v["pct"] is not None]
        out[macchina_id] = {
            "rilevata_il": quando, "voci": voci,
            "critici": [v for v in voci if v["critico"]],
            "peggiore": min(misurabili, key=lambda v: v["pct"]) if misurabili else None,
        }
    return out


# --- Letture trimestrali proposte dalle mensili -------------------------------

def limiti_trimestre(trimestre):
    """(primo giorno, primo giorno del trimestre successivo) di "AAAA-Qn"."""
    from datetime import date
    anno, q = map(int, _TRIMESTRE_RE.match(trimestre).groups())
    inizio = date(anno, 3 * q - 2, 1)
    fine = date(anno + 1, 1, 1) if q == 4 else date(anno, 3 * q + 1, 1)
    return inizio, fine


def proposte_letture_trimestrali(trimestre):
    """Per le MFC attive senza lettura del trimestre propone la lettura mensile SNMP
    di chiusura: quella del mese successivo, presa entro il giorno
    ``GIORNI_RECUPERO_MENSILE``. Una lettura di un altro mese non e' la chiusura del
    trimestre (mancherebbero o avanzerebbero copie): niente proposta, si inserisce a mano.

    Una proposta piu' bassa della lettura del trimestre precedente o piu' alta di
    quella del successivo e' marcata `incoerente` e non si conferma. Nessuna
    scrittura: le proposte vanno confermate.
    """
    from datetime import datetime, time, timedelta
    _, chiusura = limiti_trimestre(trimestre)
    limite = timezone.make_aware(datetime.combine(chiusura + timedelta(days=GIORNI_RECUPERO_MENSILE), time(0, 0)))
    attive = list(Macchina.objects.filter(attiva=True).order_by("reparto"))
    gia_lette = set(LetturaContatori.objects.filter(trimestre=trimestre).values_list("macchina_id", flat=True))
    mancanti = [m for m in attive if m.id not in gia_lette]
    chiusure = {l.macchina_id: l for l in LetturaMensileContatori.objects.filter(
        macchina__in=mancanti, mese=chiusura, rilevata_il__lt=limite)}
    proposte = []
    for m in mancanti:
        scelta = chiusure.get(m.id)
        if scelta is None:
            continue
        prima = m.letture.filter(trimestre__lt=trimestre).order_by("-trimestre").first()
        dopo = m.letture.filter(trimestre__gt=trimestre).order_by("trimestre").first()
        motivo = ""
        if prima and any(getattr(scelta, c) < getattr(prima, c) for c in CAMPI):
            motivo = f"Più bassa del {prima.trimestre}"
        elif dopo and any(getattr(scelta, c) > getattr(dopo, c) for c in CAMPI):
            motivo = f"Più alta del {dopo.trimestre}"
        proposte.append({"macchina": m, "mensile": scelta, "incoerente": bool(motivo), "motivo": motivo,
                         "precedente": prima,
                         "delta": scelta.totale - prima.totale if prima else None})
    return proposte


def conferma_proposta(proposta, trimestre):
    """Crea la lettura trimestrale dalla mensile proposta (fonte SNMP, data reale)."""
    mensile = proposta["mensile"]
    lettura, creata = LetturaContatori.objects.get_or_create(
        macchina=proposta["macchina"], trimestre=trimestre,
        defaults={**{c: getattr(mensile, c) for c in CAMPI},
                  "data": timezone.localtime(mensile.rilevata_il).date(),
                  "fonte": LetturaContatori.Fonte.SNMP,
                  "note": f"Da lettura mensile del {mensile.mese:%m/%Y}"})
    return lettura, creata


def licenze_asset_apparati():
    """Licenze software degli asset collegati ad apparati attivi (MFC e dispositivi SNMP).

    Ritorna ``scadute``/``in_scadenza`` (numero di licenze attive degli asset collegati). Gli apparati
    senza asset sono in ``integrazione.quadro_integrazione``. Query a numero fisso.
    """
    from assets.services.software_licenze import expiring_for_assets

    ids = set(Macchina.objects.filter(attiva=True, asset__isnull=False).values_list("asset_id", flat=True))
    ids |= set(DispositivoSNMP.objects.filter(attivo=True, asset__isnull=False).values_list("asset_id", flat=True))
    conteggi = expiring_for_assets(ids)
    return {
        "scadute": sum(s for s, _ in conteggi.values()),
        "in_scadenza": sum(i for _, i in conteggi.values()),
    }


# --- Gestione dati: registro letture, storico MFC, archivio fatture ------------

def ultimi_trimestri(n, fino_a=None):
    """Gli ultimi `n` trimestri fino a `fino_a` (compreso, default il corrente), crescenti."""
    t = fino_a or trimestre_corrente()
    out = []
    for _ in range(max(1, n)):
        out.append(t)
        t = trimestre_precedente(t)
    return out[::-1]


def _cali(lettura, precedente):
    """Etichette dei contatori scesi rispetto alla lettura precedente."""
    if precedente is None:
        return []
    return [etichetta for campo, etichetta in CONTATORI
            if getattr(lettura, campo) < getattr(precedente, campo)]


def registro_letture(trimestri=8, *, dismesse=False, oggi=None):
    """Matrice MFC x trimestri per vedere e completare le letture.

    Ogni cella: la lettura (con le copie rispetto al trimestre precedente, se c'e')
    oppure lo stato della mancanza: `mancante` dal primo trimestre letto in poi,
    `in_corso` per il trimestre corrente. I cali sono confrontati con la lettura
    precedente qualunque sia il trimestre.
    """
    oggi = oggi or timezone.localdate()
    corrente = trimestre_di(oggi)
    colonne = ultimi_trimestri(trimestri, corrente)
    macchine = Macchina.objects.all() if dismesse else Macchina.objects.filter(attiva=True)
    macchine = list(macchine.order_by("-attiva", "reparto", "matricola"))
    per_macchina = defaultdict(list)
    for l in LetturaContatori.objects.filter(macchina__in=macchine).order_by("trimestre"):
        per_macchina[l.macchina_id].append(l)
    righe, mancanti, cali = [], 0, 0
    for m in macchine:
        letture = per_macchina.get(m.pk, [])
        per_trim = {l.trimestre: l for l in letture}
        prima = letture[0].trimestre if letture else corrente
        celle = []
        for t in colonne:
            l = per_trim.get(t)
            if l is not None:
                precedente = next((x for x in reversed(letture) if x.trimestre < t), None)
                consecutiva = per_trim.get(trimestre_precedente(t))
                scesi = _cali(l, precedente)
                cali += bool(scesi)
                celle.append({"trimestre": t, "lettura": l, "cali": scesi,
                              "copie": (l.totale - consecutiva.totale
                                        if consecutiva is not None and not scesi else None)})
            elif t == corrente:
                celle.append({"trimestre": t, "stato": "in_corso"})
            elif m.attiva and t >= prima:
                mancanti += 1
                celle.append({"trimestre": t, "stato": "mancante"})
            else:
                celle.append({"trimestre": t, "stato": "vuota"})
        righe.append({"macchina": m, "celle": celle, "letture": len(letture)})
    return {"trimestri": colonne, "righe": righe, "mancanti": mancanti, "cali": cali,
            "corrente": corrente}


def righe_letture_macchina(macchina, letture=None):
    """Letture trimestrali della MFC dalla piu' recente, con copie, cali e lacune.

    Tra due letture non consecutive compare una riga `manca` per ogni trimestre
    senza lettura: le copie della lettura successiva non sono calcolabili.
    `letture` (gia' ordinate per trimestre) evita la query quando si mostrano piu' MFC.
    """
    letture = list(macchina.letture.order_by("trimestre")) if letture is None else letture
    righe = []
    for i, l in enumerate(letture):
        prec = letture[i - 1] if i else None
        if prec is not None:
            t = trimestre_successivo(prec.trimestre)
            while t < l.trimestre:
                righe.append({"trimestre": t, "lettura": None})
                t = trimestre_successivo(t)
        scesi = _cali(l, prec)
        consecutiva = prec is not None and prec.trimestre == trimestre_precedente(l.trimestre)
        righe.append({"trimestre": l.trimestre, "lettura": l, "cali": scesi,
                      "copie": l.totale - prec.totale if consecutiva and not scesi else None})
    return righe[::-1]


def righe_mensili_macchina(macchina, ultimi=24):
    """Ultime letture mensili con le copie del mese (rispetto al mese precedente letto)."""
    mensili = list(macchina.letture_mensili.order_by("-mese")[:ultimi + 1])[::-1]
    righe = []
    for i, l in enumerate(mensili):
        prec = mensili[i - 1] if i else None
        consecutivo = prec is not None and (
            (prec.mese.year * 12 + prec.mese.month) + 1 == l.mese.year * 12 + l.mese.month)
        scesi = _cali(l, prec)
        righe.append({"lettura": l, "cali": scesi,
                      "copie": l.totale - prec.totale if consecutivo and not scesi else None})
    return righe[::-1][:ultimi]


def elenco_letture_gestione(tipo="trimestrali", *, macchina_id=None, anno=None, solo_cali=False):
    """Letture in elenco piatto (dalla piu' recente) per la pagina «Gestisci letture».

    `tipo`: "trimestrali" o "mensili". Ogni riga: macchina, lettura, periodo
    ("2026-Q3" / "10/2026"), cali rispetto alla lettura precedente della stessa MFC.
    """
    mensili = tipo == "mensili"
    qs = (LetturaMensileContatori if mensili else LetturaContatori).objects.select_related("macchina")
    if macchina_id:
        qs = qs.filter(macchina_id=macchina_id)
    ordine = "mese" if mensili else "trimestre"
    per_macchina = {}
    for l in qs.order_by("macchina_id", ordine):
        per_macchina.setdefault(l.macchina_id, []).append(l)
    righe = []
    for letture in per_macchina.values():
        for i, l in enumerate(letture):
            anno_l = l.mese.year if mensili else int(l.trimestre[:4])
            if anno and anno_l != anno:
                continue
            cali = _cali(l, letture[i - 1] if i else None)
            if solo_cali and not cali:
                continue
            righe.append({"macchina": l.macchina, "lettura": l, "cali": cali,
                          "periodo": f"{l.mese:%m/%Y}" if mensili else l.trimestre,
                          "chiave": l.mese.isoformat() if mensili else l.trimestre})
    righe.sort(key=lambda r: (r["chiave"], r["macchina"].reparto), reverse=True)
    return righe


def anni_letture():
    """Anni con almeno una lettura trimestrale o mensile, dal piu' recente."""
    anni = {int(t[:4]) for t in LetturaContatori.objects.values_list("trimestre", flat=True).distinct()
            if t[:4].isdigit()}
    anni.update(d.year for d in LetturaMensileContatori.objects.dates("mese", "year"))
    return sorted(anni, reverse=True)


def fatture_macchina(macchina, ultimi=6):
    """Esito della riconciliazione del contratto della MFC negli ultimi trimestri fatturati."""
    if not macchina.contratto:
        return []
    trimestri = list(RigaFattura.objects.filter(contratto=macchina.contratto)
                     .values_list("fattura__trimestre", flat=True).distinct()
                     .order_by("-fattura__trimestre")[:ultimi])
    out = []
    for t in trimestri:
        for gruppo in riconcilia(t)[1]["gruppi"]:
            if gruppo["contratto"] == macchina.contratto:
                out.append({"trimestre": t, **gruppo})
    return out


def archivio_fatture():
    """Fatture per trimestre, con l'esito della riconciliazione e i trimestri scoperti.

    [{trimestre, fatture: [Fattura], righe, riepilogo, letture}] dal piu' recente.
    Un trimestre con letture interne ma senza fattura compare con `fatture` vuoto
    (dal primo trimestre fatturato in poi: prima non c'era il confronto).
    """
    fatture = defaultdict(list)
    for f in Fattura.objects.prefetch_related("righe").order_by("-trimestre", "-periodo_al", "numero"):
        fatture[f.trimestre].append(f)
    # .order_by() vuoto: con l'ordering del Meta SQL Server rifiuta il GROUP BY (errore 8127).
    letture = dict(LetturaContatori.objects.order_by().values("trimestre").annotate(n=Count("id"))
                   .values_list("trimestre", "n"))
    primo = min(fatture, default=None)
    trimestri = set(fatture) | {t for t in letture if primo and t >= primo}
    corrente = trimestre_corrente()
    out = []
    for t in sorted(trimestri, reverse=True):
        riepilogo = riconcilia(t)[1] if fatture.get(t) else None
        out.append({"trimestre": t, "fatture": fatture.get(t, []), "letture": letture.get(t, 0),
                    "riepilogo": riepilogo, "in_corso": t >= corrente})
    return out


def disponibilita_dispositivo(dispositivo, ora=None):
    """Quota di interrogazioni riuscite nelle ultime 24 ore e 7 giorni (dallo storico salvato).

    {"24h": {"totale", "ok", "errori", "pct"}, "7g": {...}}; `pct` None senza rilevazioni.
    Lo stato «attenzione» (soglia superata) conta come riuscito: l'apparato ha risposto.
    """
    ora = ora or timezone.now()
    out = {}
    for chiave, giorni in (("24h", 1), ("7g", 7)):
        stati = list(dispositivo.rilevazioni.filter(rilevata_il__gte=ora - timedelta(days=giorni))
                     .values_list("stato", flat=True))
        errori = sum(1 for s in stati if s == StatoSNMP.ERROR)
        out[chiave] = {"totale": len(stati), "errori": errori, "ok": len(stati) - errori,
                       "pct": round(100 * (len(stati) - errori) / len(stati), 1) if stati else None}
    return out


def disponibilita_flotta(dispositivi_ids, ora=None, ore=24):
    """{dispositivo_id: % di interrogazioni con risposta nelle ultime `ore`} con una query sola.

    Dispositivi senza interrogazioni nel periodo assenti dal risultato.
    """
    ora = ora or timezone.now()
    conteggi = defaultdict(lambda: [0, 0])  # [totale, errori]
    # .order_by() vuoto: il GROUP BY con l'ordering del Meta fallisce su SQL Server (8127).
    for pk, stato, n in (RilevazioneSNMP.objects.order_by()
                         .filter(dispositivo_id__in=list(dispositivi_ids), rilevata_il__gte=ora - timedelta(hours=ore))
                         .values("dispositivo_id", "stato").annotate(n=Count("id"))
                         .values_list("dispositivo_id", "stato", "n")):
        conteggi[pk][0] += n
        if stato == StatoSNMP.ERROR:
            conteggi[pk][1] += n
    return {pk: round(100 * (tot - err) / tot, 1) for pk, (tot, err) in conteggi.items() if tot}
