"""Discovery read-only Printer-MIB (RFC 3805), indipendente da marca e indici."""
import asyncio
import functools

from .snmp import SNMPError, _testo, costruisci_credenziali

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

COLONNE_FACOLTATIVE = {"tipi", "indici_colore", "colori"}

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


def consumabili_in_esaurimento(dati):
    """Consumabili con percentuale nota sotto soglia."""
    return [c for c in (dati or {}).get("consumabili", [])
            if isinstance(c.get("pct"), int) and c["pct"] < SOGLIA_CONSUMABILI_PCT]


def _numero(value):
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
    return {"contatori": contatori, "consumabili": consumabili, "errori": errori}


def leggi_stampante(dispositivo, *, community, port, timeout, version):
    """Colonne Printer-MIB in parallelo, massimo 128 righe e 20s per colonna.

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
        return await asyncio.gather(*[
            asyncio.wait_for(colonna(base), timeout=20)
            for base in COLUMNS.values()
        ], return_exceptions=True)

    tabelle, errori = {}, {}
    for nome, risultato in zip(COLUMNS, asyncio.run(run())):
        if isinstance(risultato, Exception):
            if nome in COLONNE_FACOLTATIVE:
                continue  # tipo/colore arricchiscono, non devono generare avvisi
            errori[nome] = (str(risultato) or "Tempo di lettura superato")[:300]
        else:
            tabelle[nome] = risultato
    return interpreta_stampante(tabelle, errori)
