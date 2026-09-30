"""Discovery read-only Printer-MIB (RFC 3805), indipendente da marca e indici."""
import asyncio
import functools

from .snmp import SNMPError, _testo

LIFE_COUNT = "1.3.6.1.2.1.43.10.2.1.4"
COUNTER_UNIT = "1.3.6.1.2.1.43.10.2.1.3"
COLUMNS = {
    "contatori": LIFE_COUNT,
    "unita": COUNTER_UNIT,
    "nomi": "1.3.6.1.2.1.43.11.1.1.6",
    "massimi": "1.3.6.1.2.1.43.11.1.1.8",
    "livelli": "1.3.6.1.2.1.43.11.1.1.9",
}


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
        consumabili.append({
            "indice": indice, "nome": _testo(nome), "pct": pct,
            "nota": nota, "livello": livello, "massimo": massimo,
        })
    return {"contatori": contatori, "consumabili": consumabili, "errori": errori}


def leggi_stampante(dispositivo, *, community, port, timeout, version):
    """Cinque colonne in parallelo, massimo 128 righe e 20s per colonna.

    Un errore su toner non nasconde i contatori (e viceversa). Il limite totale
    dei WALK concorrenti lascia tempo al job del polling (110s).
    """
    try:
        from puresnmp import Client, PyWrapper, V1, V2C
        from puresnmp.transport import send_udp
    except ImportError as exc:
        raise SNMPError("puresnmp non installato") from exc

    async def colonna(base):
        cred = V1(community) if version == "v1" else V2C(community)
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
            errori[nome] = (str(risultato) or "Tempo di lettura superato")[:300]
        else:
            tabelle[nome] = risultato
    return interpreta_stampante(tabelle, errori)
