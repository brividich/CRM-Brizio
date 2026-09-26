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
from decimal import Decimal, InvalidOperation, Overflow
from time import perf_counter

from django.db import transaction
from django.utils import timezone
from .models import (
    CONTATORI,
    DispositivoSNMP,
    Fattura,
    ImpostazioniSNMP,
    LetturaContatori,
    Macchina,
    RilevazioneSNMP,
    RigaFattura,
    SondaSNMP,
    StatoSNMP,
    ValoreSNMP,
)

CAMPI = [c[0] for c in CONTATORI]

# Raggruppamenti usati nelle analisi
BN = ("a4_bn", "a3_bn")


def trova_asset_snmp(*, seriale="", host=None):
    """Trova un Asset HUB univoco per seriale, poi per endpoint IP.

    Restituisce ``(asset, motivo)``. In caso di nessun match o ambiguità non
    sceglie arbitrariamente: ``asset`` resta ``None`` e il motivo spiega perché.
    """
    from assets.models import Asset

    seriale = (seriale or "").strip()
    if seriale:
        candidati = list(Asset.objects.filter(serial_number__iexact=seriale)[:2])
        if len(candidati) == 1:
            return candidati[0], "seriale"
        if len(candidati) > 1:
            return None, "seriale ambiguo"
    if host:
        candidati = list(
            Asset.objects.filter(endpoints__ip=str(host)).distinct()[:2]
        )
        if len(candidati) == 1:
            return candidati[0], "indirizzo IP"
        if len(candidati) > 1:
            return None, "indirizzo IP ambiguo"
    return None, "nessuna corrispondenza"
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


def _intero_grezzo(valore):
    try:
        return int(valore)
    except (TypeError, ValueError):
        try:
            return int(str(valore).strip())
        except (TypeError, ValueError):
            return None


def _numero_sonda(sonda, valore):
    try:
        numero = Decimal(str(valore).strip())
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


def interroga_macchina(macchina):
    """Legge una MFC, aggiorna la salute SNMP e ritorna i quattro contatori.

    Non salva una :class:`LetturaContatori`: il chiamante decide se si tratta di
    un semplice test o della rilevazione trimestrale ufficiale.
    """
    from .snmp import SNMPError, leggi_macchina

    cfg = ImpostazioniSNMP.get_solo()
    inizio = perf_counter()
    try:
        valori = leggi_macchina(
            macchina, community=cfg.community, port=cfg.port,
            timeout=cfg.timeout, version=cfg.version,
        )
    except SNMPError as exc:
        macchina.snmp_stato = StatoSNMP.ERROR
        macchina.snmp_ultimo_controllo = timezone.now()
        macchina.snmp_tempo_risposta_ms = _tempo_ms(inizio)
        macchina.snmp_ultimo_errore = str(exc)[:500]
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
        SYS_DESCR,
        SYS_NAME,
        SYS_OBJECT_ID,
        SYS_UPTIME,
        SYSTEM_OIDS,
        _testo,
        leggi_oids,
    )

    cfg = ImpostazioniSNMP.get_solo()
    sonde = list(dispositivo.sonde.filter(attiva=True))
    oids = [*SYSTEM_OIDS, *(sonda.oid for sonda in sonde)]
    porta = dispositivo.porta or cfg.port
    versione = dispositivo.versione or cfg.version
    inizio = perf_counter()
    adesso = timezone.now()

    try:
        valori, errori = leggi_oids(
            dispositivo.host, oids, community=cfg.community, port=porta,
            timeout=cfg.timeout, version=versione,
        )
    except SNMPError as exc:
        durata = _tempo_ms(inizio)
        rilevazione = RilevazioneSNMP.objects.create(
            dispositivo=dispositivo, rilevata_il=adesso,
            stato=StatoSNMP.ERROR, tempo_risposta_ms=durata,
            errore=str(exc)[:500],
        )
        dispositivo.snmp_stato = StatoSNMP.ERROR
        dispositivo.snmp_ultimo_controllo = adesso
        dispositivo.snmp_tempo_risposta_ms = durata
        dispositivo.snmp_ultimo_errore = str(exc)[:500]
        dispositivo.save(update_fields=[
            "snmp_stato", "snmp_ultimo_controllo", "snmp_tempo_risposta_ms",
            "snmp_ultimo_errore", "aggiornato_il",
        ])
        return rilevazione

    durata = _tempo_ms(inizio)
    sys_name = _testo(valori.get(SYS_NAME))
    sys_description = _testo(valori.get(SYS_DESCR))
    sys_object_id = _testo(valori.get(SYS_OBJECT_ID))
    uptime_ticks = _intero_grezzo(valori.get(SYS_UPTIME))
    uptime_seconds = max(0, uptime_ticks // 100) if uptime_ticks is not None else None

    esiti = []
    ha_warning = False
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
    dispositivo.save(update_fields=[
        "snmp_stato", "snmp_ultimo_controllo", "snmp_tempo_risposta_ms",
        "snmp_ultimo_errore", "sys_name", "sys_description", "sys_object_id",
        "sys_uptime_seconds", "aggiornato_il",
    ])
    return rilevazione


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
