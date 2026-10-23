"""Discovery read-only Printer-MIB (RFC 3805), indipendente da marca e indici."""
import asyncio
import functools
from datetime import timedelta

from .snmp import SNMPError, _testo, costruisci_credenziali, descrivi_errore

LIFE_COUNT = "1.3.6.1.2.1.43.10.2.1.4"
COUNTER_UNIT = "1.3.6.1.2.1.43.10.2.1.3"
COLUMNS = {
    "contatori": LIFE_COUNT,
    "unita": COUNTER_UNIT,
    "nomi": "1.3.6.1.2.1.43.11.1.1.6",
    "massimi": "1.3.6.1.2.1.43.11.1.1.8",
    "livelli": "1.3.6.1.2.1.43.11.1.1.9",
    "tipi": "1.3.6.1.2.1.43.11.1.1.5",            # prtMarkerSuppliesType
    "indici_colore": "1.3.6.1.2.1.43.11.1.1.3",   # prtMarkerSuppliesColorantIndex
    "colori": "1.3.6.1.2.1.43.12.1.1.4",          # prtMarkerColorantValue
}

# Altri dati della stampante (RFC 3805 Printer-MIB, RFC 2790 Host-Resources): tutti facoltativi,
# una colonna che non risponde non genera avvisi e non toglie contatori e toner.
COLUMNS_EXTRA = {
    # prtAlertTable: il registro avvisi della stampante (inceppamenti, carta, sportelli, assistenza)
    "avvisi_gravita": "1.3.6.1.2.1.43.18.1.1.2",
    "avvisi_livello": "1.3.6.1.2.1.43.18.1.1.3",
    "avvisi_gruppo": "1.3.6.1.2.1.43.18.1.1.4",
    "avvisi_gruppo_indice": "1.3.6.1.2.1.43.18.1.1.5",
    "avvisi_codice": "1.3.6.1.2.1.43.18.1.1.7",
    "avvisi_testo": "1.3.6.1.2.1.43.18.1.1.8",
    "avvisi_ora": "1.3.6.1.2.1.43.18.1.1.9",
    # prtInputTable: cassetti carta
    "cassetti_max": "1.3.6.1.2.1.43.8.2.1.9",
    "cassetti_livello": "1.3.6.1.2.1.43.8.2.1.10",
    "cassetti_stato": "1.3.6.1.2.1.43.8.2.1.11",
    "cassetti_carta": "1.3.6.1.2.1.43.8.2.1.12",
    "cassetti_nome": "1.3.6.1.2.1.43.8.2.1.13",
    # prtCoverTable: sportelli
    "sportelli_nome": "1.3.6.1.2.1.43.6.1.1.2",
    "sportelli_stato": "1.3.6.1.2.1.43.6.1.1.3",
    # prtConsoleDisplayBufferText: il testo sul display del pannello
    "display": "1.3.6.1.2.1.43.16.5.1.2",
    # hrPrinterStatus / hrPrinterDetectedErrorState
    "stato_stampante": "1.3.6.1.2.1.25.3.5.1.1",
    "errori_rilevati": "1.3.6.1.2.1.25.3.5.1.2",
    # sysUpTime: serve a dire da quanto è aperto un avviso (prtAlertTime è in sysUpTime)
    "uptime": "1.3.6.1.2.1.1.3",
}
COLUMNS_TUTTE = {**COLUMNS, **COLUMNS_EXTRA}

COLONNE_FACOLTATIVE = {"tipi", "indici_colore", "colori", *COLUMNS_EXTRA}
WALK_CONCORRENTI = 8  # la stampante non riceve più di 8 WALK insieme

# Sotto questa percentuale un consumabile porta il dispositivo in "Attenzione".
SOGLIA_CONSUMABILI_PCT = 10

# prtMarkerSuppliesTypeTC (RFC 3805), solo le voci viste o comuni.
TIPI_CONSUMABILE = {
    3: "toner", 4: "toner di scarto", 5: "inchiostro", 6: "cartuccia inchiostro",
    7: "nastro", 8: "inchiostro di scarto", 9: "tamburo", 10: "developer", 15: "fusore",
    18: "unità di pulizia", 20: "unità di trasferimento", 21: "cartuccia toner",
    32: "punti metallici",
}
COLORI = {"black": "nero", "cyan": "ciano", "magenta": "magenta", "yellow": "giallo"}

# hrPrinterDetectedErrorState (RFC 2790): bit 0 = bit piu' significativo del primo byte.
ERRORI_STAMPANTE = (
    ("carta in esaurimento", "WARNING"), ("carta esaurita", "WARNING"),
    ("toner in esaurimento", "WARNING"), ("toner esaurito", "ERROR"),
    ("sportello aperto", "ERROR"), ("carta inceppata", "ERROR"),
    ("fuori linea", "ERROR"), ("assistenza richiesta", "ERROR"),
    ("cassetto di alimentazione mancante", "WARNING"), ("vassoio di uscita mancante", "WARNING"),
    ("consumabile mancante", "WARNING"), ("vassoio di uscita quasi pieno", "WARNING"),
    ("vassoio di uscita pieno", "WARNING"), ("cassetto di alimentazione vuoto", "WARNING"),
    ("manutenzione preventiva scaduta", "WARNING"),
)


def decodifica_errori_stampante(raw):
    """Converte la bitmask hrPrinterDetectedErrorState in ``(testo, stato)``.

    ``stato`` e' "OK", "WARNING" o "ERROR" (valori di :class:`StatoSNMP`).
    """
    if raw is None:
        return "", "ERROR"
    data = raw if isinstance(raw, bytes) else str(raw).encode("latin-1", "replace")
    attivi = []
    for bit, (testo, livello) in enumerate(ERRORI_STAMPANTE):
        byte, pos = divmod(bit, 8)
        if byte < len(data) and data[byte] & (0x80 >> pos):
            attivi.append((testo, livello))
    if not attivi:
        return "nessun errore", "OK"
    stato = "ERROR" if any(l == "ERROR" for _, l in attivi) else "WARNING"
    return ", ".join(t for t, _ in attivi), stato


# prtAlertSeverityLevelTC
GRAVITA_AVVISO = {1: "altro", 3: "critico", 4: "avviso", 5: "evento"}
# prtAlertTrainingLevelTC: chi deve intervenire
LIVELLO_AVVISO = {3: "chiunque", 4: "utente formato", 5: "assistenza tecnica", 6: "amministratore"}
# prtAlertGroupTC: la parte della stampante coinvolta
GRUPPO_AVVISO = {
    5: "stampante", 6: "sportello", 8: "cassetto carta", 9: "vassoio di uscita", 10: "motore di stampa",
    11: "consumabili", 12: "colori", 13: "percorso carta", 14: "canale", 15: "interprete",
    16: "display", 17: "spie", 18: "avvisi", 30: "finitore", 31: "consumabili finitore", 33: "finitore",
}
# prtAlertCodeTC (RFC 3805): le voci che una persona sa cosa vogliono dire
CODICE_AVVISO = {
    3: "sportello aperto", 4: "sportello chiuso", 5: "blocco aperto", 6: "blocco chiuso",
    7: "configurazione cambiata", 8: "carta inceppata", 9: "componente mancante",
    10: "componente a fine vita", 11: "componente esaurito", 12: "quasi vuoto", 13: "vuoto",
    14: "quasi pieno", 15: "pieno", 16: "vicino al limite", 17: "al limite", 18: "aperto", 19: "chiuso",
    20: "acceso", 21: "spento", 22: "fuori linea", 23: "risparmio energetico", 24: "in riscaldamento",
    25: "componente aggiunto", 26: "componente rimosso", 29: "guasto recuperabile", 30: "guasto non recuperabile",
    31: "errore di memoria recuperabile", 32: "errore di memoria non recuperabile", 33: "guasto motore",
    34: "memoria esaurita", 35: "temperatura troppo bassa", 36: "temperatura troppo alta",
    501: "sportello aperto", 502: "sportello chiuso", 503: "accensione", 504: "spegnimento",
    505: "riavvio da rete", 506: "riavvio manuale", 507: "pronta a stampare",
    801: "cassetto mancante", 802: "formato carta cambiato", 807: "carta in esaurimento", 808: "carta esaurita",
    809: "inserimento manuale richiesto", 901: "vassoio di uscita mancante", 902: "vassoio di uscita quasi pieno",
    903: "vassoio di uscita pieno", 1001: "fusore troppo freddo", 1002: "fusore troppo caldo",
    1005: "regolazione qualità di stampa", 1101: "toner esaurito", 1102: "inchiostro esaurito",
    1104: "toner in esaurimento", 1105: "inchiostro in esaurimento", 1107: "contenitore toner di scarto quasi pieno",
    1109: "contenitore toner di scarto pieno", 1111: "tamburo a fine vita", 1112: "tamburo esaurito",
    1113: "developer in esaurimento", 1114: "developer esaurito", 1115: "cartuccia toner mancante",
    1301: "cassetto del percorso carta mancante", 1304: "fronte-retro non possibile con questa carta",
}
# Codici che non sono problemi: eventi di normale funzionamento
CODICI_INFORMATIVI = {4, 6, 7, 19, 20, 23, 24, 25, 502, 503, 505, 506, 507, 802}
# prtCoverStatusTC
STATO_SPORTELLO = {1: "altro", 3: "aperto", 4: "chiuso", 5: "blocco aperto", 6: "blocco chiuso"}
SPORTELLO_APERTO = {3, 5}
# hrPrinterStatus
STATO_STAMPANTE = {1: "altro", 2: "sconosciuto", 3: "pronta", 4: "in stampa", 5: "in riscaldamento"}


def _ordine(indice):
    return tuple(int(p) if p.isdigit() else 0 for p in str(indice).split("."))


def _sottounita(stato):
    """prtSubUnitStatusTC: (testo, problema). Bit 0-2 disponibilità, 3 avviso, 4 avviso critico, 5 fuori linea."""
    if stato is None or stato < 0:
        return "", False
    parti = []
    if stato & 7 == 5:
        parti.append("guasto")
    elif stato & 7 == 4:
        parti.append("non disponibile")
    if stato & 16:
        parti.append("avviso critico")
    elif stato & 8:
        parti.append("avviso")
    if stato & 32:
        parti.append("fuori linea")
    return ", ".join(parti), bool(stato & (16 | 32)) or stato & 7 == 5


def _avvisi(tabelle):
    uptime = _numero(next(iter(tabelle.get("uptime", {}).values()), None))
    out = []
    indici = set(tabelle.get("avvisi_codice", {})) | set(tabelle.get("avvisi_testo", {}))
    for indice in sorted(indici, key=_ordine):
        codice = _numero(tabelle.get("avvisi_codice", {}).get(indice))
        gravita = _numero(tabelle.get("avvisi_gravita", {}).get(indice))
        gruppo = _numero(tabelle.get("avvisi_gruppo", {}).get(indice))
        testo = _testo(tabelle.get("avvisi_testo", {}).get(indice)).strip()
        ora = _numero(tabelle.get("avvisi_ora", {}).get(indice))
        da_secondi = (uptime - ora) // 100 if uptime is not None and ora is not None and 0 <= ora <= uptime else None
        descrizione = CODICE_AVVISO.get(codice, "")
        out.append({
            "indice": indice, "codice": codice,
            "testo": testo or descrizione.capitalize() or f"Avviso {codice or '?'}",
            "descrizione": descrizione, "gravita": GRAVITA_AVVISO.get(gravita, "altro"),
            "critico": gravita == 3, "informativo": codice in CODICI_INFORMATIVI or gravita == 5,
            "gruppo": GRUPPO_AVVISO.get(gruppo, ""),
            "gruppo_indice": _numero(tabelle.get("avvisi_gruppo_indice", {}).get(indice)),
            "chi": LIVELLO_AVVISO.get(_numero(tabelle.get("avvisi_livello", {}).get(indice)), ""),
            "da_secondi": da_secondi,
        })
    return out


def _cassetti(tabelle):
    out = []
    indici = set(tabelle.get("cassetti_nome", {})) | set(tabelle.get("cassetti_livello", {}))
    for indice in sorted(indici, key=_ordine):
        livello = _numero(tabelle.get("cassetti_livello", {}).get(indice))
        massimo = _numero(tabelle.get("cassetti_max", {}).get(indice))
        pct, nota = None, ""
        if livello == 0:
            pct, nota = 0, "vuoto"
        elif livello == -3:
            nota = "carta presente"
        elif livello is not None and livello > 0 and massimo and massimo > 0 and livello <= massimo:
            pct = round(100 * livello / massimo)
        else:
            nota = "livello non comunicato"
        stato, problema = _sottounita(_numero(tabelle.get("cassetti_stato", {}).get(indice)))
        nome = _testo(tabelle.get("cassetti_nome", {}).get(indice)).strip() or "Cassetto " + indice.split(".")[-1]
        out.append({
            "indice": indice, "nome": nome, "carta": _testo(tabelle.get("cassetti_carta", {}).get(indice)).strip(),
            "pct": pct, "nota": nota, "capacita": massimo if massimo and massimo > 0 else None,
            "stato": stato, "problema": bool(problema or livello == 0),
        })
    return out


def _sportelli(tabelle):
    out = []
    for indice in sorted(tabelle.get("sportelli_stato", {}), key=_ordine):
        stato = _numero(tabelle["sportelli_stato"][indice])
        nome = _testo(tabelle.get("sportelli_nome", {}).get(indice)).strip() or "Sportello " + indice.split(".")[-1]
        out.append({"indice": indice, "nome": nome, "stato": STATO_SPORTELLO.get(stato, "sconosciuto"),
                    "aperto": stato in SPORTELLO_APERTO})
    return out


def _stato(tabelle):
    """Stato operativo, errori rilevati (bitmask) e testo del display."""
    stato = _numero(next(iter(tabelle.get("stato_stampante", {}).values()), None))
    errori_raw = next(iter(tabelle.get("errori_rilevati", {}).values()), None)
    testo, livello = decodifica_errori_stampante(errori_raw) if errori_raw is not None else ("", "")
    if testo == "nessun errore":
        testo, livello = "", ""
    righe = [_testo(v).strip() for _k, v in sorted(tabelle.get("display", {}).items(), key=lambda kv: _ordine(kv[0]))]
    return {"stato": STATO_STAMPANTE.get(stato, ""), "segnalazioni": testo, "segnalazioni_livello": livello,
            "display": [r for r in righe if r]}


def problemi_stampante(dati):
    """Cose da sistemare secondo una lettura: [(testo, livello)], livello "WARNING" o "ERROR"."""
    dati = dati or {}
    out = []
    for a in dati.get("avvisi", []):
        if not a.get("informativo"):
            out.append((a["testo"], "ERROR" if a.get("critico") else "WARNING"))
    stato = dati.get("stato") or {}
    if stato.get("segnalazioni") and not out:
        # Gli errori rilevati ripetono gli avvisi (es. «carta inceppata» e «Paper jam in tray 2»): solo se mancano.
        out.append((stato["segnalazioni"].capitalize(), stato.get("segnalazioni_livello") or "WARNING"))
    for s in dati.get("sportelli", []):
        if s.get("aperto"):
            out.append((f"{s['nome']}: {s['stato']}", "ERROR"))
    for c in dati.get("cassetti", []):
        if c.get("problema"):
            out.append((f"{c['nome']}: {'vuoto' if c.get('pct') == 0 else (c['stato'] or c['nota'])}", "WARNING"))
    return out


def consumabili_in_esaurimento(dati):
    """Consumabili con percentuale nota sotto soglia."""
    return [c for c in (dati or {}).get("consumabili", [])
            if isinstance(c.get("pct"), int) and c["pct"] < SOGLIA_CONSUMABILI_PCT]


def _numero(value):
    if isinstance(value, timedelta):  # puresnmp restituisce i TimeTicks come timedelta
        return round(value.total_seconds() * 100)
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return None


def interpreta_stampante(tabelle, errori):
    """Allinea per indice completo: mai sommare motori o indovinare i colori."""
    contatori, consumabili = [], []
    for indice, raw in tabelle.get("contatori", {}).items():
        valore = _numero(raw)
        if valore is None or valore < 0:
            continue
        unita = _numero(tabelle.get("unita", {}).get(indice))
        contatori.append({
            "indice": indice, "valore": valore,
            "unita": {7: "impressioni", 8: "fogli"}.get(unita, "unità dichiarate dal dispositivo"),
        })
    for indice, nome in tabelle.get("nomi", {}).items():
        livello = _numero(tabelle.get("livelli", {}).get(indice))
        massimo = _numero(tabelle.get("massimi", {}).get(indice))
        pct = None
        nota = "Livello non comunicato"
        if livello == -3:
            nota = "Presente; quantità non comunicata"
        elif livello is not None and livello >= 0 and massimo is not None and massimo > 0:
            if livello <= massimo:
                pct = round(100 * livello / massimo)
                nota = ""
            else:
                nota = "Valore fuori intervallo dichiarato"
        # Il colore e' indicizzato per dispositivo: "1.<colorantIndex>".
        indice_colore = _numero(tabelle.get("indici_colore", {}).get(indice))
        dispositivo = indice.split(".")[0]
        colore = _testo(tabelle.get("colori", {}).get(f"{dispositivo}.{indice_colore}")) if indice_colore else ""
        consumabili.append({
            "indice": indice, "nome": _testo(nome), "pct": pct,
            "nota": nota, "livello": livello, "massimo": massimo,
            "tipo": TIPI_CONSUMABILE.get(_numero(tabelle.get("tipi", {}).get(indice)), ""),
            "colore": COLORI.get(colore.lower(), colore),
        })
    dati = {"contatori": contatori, "consumabili": consumabili, "errori": errori}
    if any(k in tabelle for k in COLUMNS_EXTRA):
        dati.update({"avvisi": _avvisi(tabelle), "cassetti": _cassetti(tabelle),
                     "sportelli": _sportelli(tabelle), "stato": _stato(tabelle)})
    return dati


def leggi_stampante(dispositivo, *, community, port, timeout, version):
    """Colonne Printer-MIB in parallelo (al massimo 8 insieme), massimo 128 righe e 20s per colonna.

    Un errore su toner non nasconde i contatori (e viceversa). Il limite totale
    dei WALK concorrenti lascia tempo al job del polling (110s).
    """
    try:
        from puresnmp import Client, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as exc:
        raise SNMPError("puresnmp non installato") from exc

    async def colonna(base):
        cred = costruisci_credenziali(community, version)
        client = PyWrapper(Client(
            str(dispositivo.host), cred, port=port,
            sender=functools.partial(send_udp, timeout=timeout),
        ))
        righe = {}
        async for vb in client.walk(base):
            oid = str(vb.oid).lstrip(".")
            if not oid.startswith(base + "."):
                break
            if len(righe) >= 128:
                raise SNMPError("Tabella oltre il limite di 128 righe")
            righe[oid[len(base) + 1:]] = vb.value
        return righe

    async def run():
        limite = asyncio.Semaphore(WALK_CONCORRENTI)

        async def una(base):
            async with limite:
                return await asyncio.wait_for(colonna(base), timeout=20)

        return await asyncio.gather(*[una(base) for base in COLUMNS_TUTTE.values()], return_exceptions=True)

    tabelle, errori = {}, {}
    for nome, risultato in zip(COLUMNS_TUTTE, asyncio.run(run())):
        if isinstance(risultato, Exception):
            if nome in COLONNE_FACOLTATIVE:
                continue  # tipo/colore arricchiscono, non devono generare avvisi
            errori[nome] = descrivi_errore(risultato)[:300]
        else:
            tabelle[nome] = risultato
    return interpreta_stampante(tabelle, errori)
