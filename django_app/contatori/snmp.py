"""
Lettura contatori via SNMP (puresnmp). Importazione lazy: la web-app parte anche
se puresnmp non e' installato; l'errore emerge solo al momento della lettura.

La mappa numero-contatore -> categoria (A4 BN, A3 BN, A4 COL, A3 COL) va
determinata una volta per modello con lo script `discover` e messa in COUNTER_MAP
o, in produzione, su un modello dedicato. Qui e' un dizionario semplice.
"""
import asyncio
import functools

CANON_BASE = "1.3.6.1.4.1.1602.1.11.1.3.1"  # tabella contatori Canon
# Printer-MIB standard: prtMarkerSuppliesTable (toner, tamburi, fusore, ...)
SUPPLIES_DESC = "1.3.6.1.2.1.43.11.1.1.6"   # descrizione consumabile
SUPPLIES_MAX = "1.3.6.1.2.1.43.11.1.1.8"    # capacita' massima
SUPPLIES_LEVEL = "1.3.6.1.2.1.43.11.1.1.9"  # livello attuale

# Numero contatore Canon per categoria, per modello.
#   113 = Total Black/Small (A4 BN)   112 = Total Black/Large (A3 BN)
#   123 = Total Color/Small (A4 COL)  122 = Total Color/Large (A3 COL)
# Confermato via discover su iR-ADV C5840i (LOGISTICA, 10.0.0.212). Gli altri due
# modelli seguono lo stesso schema iR-ADV Gen3; confermare on-site con discover.
COUNTER_MAP = {
    "iR-ADV C5535i":    {"a4_bn": 113, "a3_bn": 112, "a4_col": 123, "a3_col": 122},
    "iR-ADV DX C5840i": {"a4_bn": 113, "a3_bn": 112, "a4_col": 123, "a3_col": 122},
    "iR-ADV DX C3822i": {"a4_bn": 113, "a3_bn": 112, "a4_col": 123, "a3_col": 122},
}


class SNMPError(RuntimeError):
    pass


def _tabella(host, community, port, timeout, version):
    try:
        from puresnmp import Client, V1, V2C, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = V1(community) if version == "v1" else V2C(community)

    async def _run():
        sender = functools.partial(send_udp, timeout=timeout)
        client = PyWrapper(Client(host, cred, port=port, sender=sender))
        # colonna .4 = valore; l'ultimo componente dell'OID e' gia' il numero
        # contatore -> mappa {numero_contatore: valore}
        out = {}
        async for vb in client.walk(CANON_BASE + ".4"):
            num = str(vb.oid).split(".")[-1]
            try:
                out[int(num)] = int(vb.value)
            except (TypeError, ValueError):
                pass
        return out

    try:
        return asyncio.run(_run())
    except SNMPError:
        raise
    except Exception as e:
        raise SNMPError(f"{host}: {e}") from e


def _consumabili_raw(host, community, port, timeout, version):
    """Legge prtMarkerSuppliesTable -> lista ordinata di (nome, livello, max)."""
    try:
        from puresnmp import Client, V1, V2C, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = V1(community) if version == "v1" else V2C(community)

    async def _run():
        sender = functools.partial(send_udp, timeout=timeout)
        client = PyWrapper(Client(host, cred, port=port, sender=sender))

        async def col(base):
            out = {}
            async for vb in client.walk(base):
                idx = str(vb.oid)[len(base) + 1:]  # es. "1.1"
                out[idx] = vb.value
            return out

        desc = await col(SUPPLIES_DESC)
        mx = await col(SUPPLIES_MAX)
        lvl = await col(SUPPLIES_LEVEL)
        righe = []
        for idx in desc:
            nome = desc[idx]
            if isinstance(nome, bytes):
                nome = nome.decode("latin-1", "replace")
            righe.append((idx, nome, lvl.get(idx), mx.get(idx)))
        righe.sort(key=lambda r: [int(p) for p in r[0].split(".") if p.isdigit()])
        return righe

    try:
        return asyncio.run(_run())
    except SNMPError:
        raise
    except Exception as e:
        raise SNMPError(f"{host}: {e}") from e


def leggi_consumabili(macchina, community="novicromprinter", port=161, timeout=3, version="v1"):
    """
    Ritorna la lista dei consumabili con livello in %:
      [{"nome", "pct" (int|None), "nota"}]
    pct None quando il livello non e' misurabile (valori speciali -2/-3 del MIB).
    Solleva SNMPError su problemi di rete/configurazione.
    """
    if not macchina.host:
        raise SNMPError("host non impostato")
    righe = _consumabili_raw(macchina.host, community, port, timeout, version)
    if not righe:
        raise SNMPError("nessun consumabile letto (SNMP off o host irraggiungibile)")
    out = []
    for _idx, nome, livello, massimo in righe:
        pct, nota = None, ""
        try:
            livello = int(livello)
            massimo = int(massimo)
        except (TypeError, ValueError):
            livello = massimo = None
        if livello is None or massimo is None:
            nota = "n/d"
        elif livello == -3:
            nota = "presente"        # residuo non quantificato
        elif livello < 0 or massimo <= 0:
            nota = "n/d"
        else:
            pct = round(100 * livello / massimo)
        out.append({"nome": nome, "pct": pct, "nota": nota})
    return out


def leggi_macchina(macchina, community="novicromprinter", port=161, timeout=3, version="v1"):
    """Ritorna dict {a4_bn, a3_bn, a4_col, a3_col} oppure solleva SNMPError.

    version: "v1" (default, come richiesto dalle Canon) o "v2c".
    """
    if not macchina.host:
        raise SNMPError("host non impostato")
    cmap = COUNTER_MAP.get(macchina.modello)
    if not cmap:
        raise SNMPError(f"nessuna counter_map per modello '{macchina.modello}'")
    tabella = _tabella(macchina.host, community, port, timeout, version)
    if not tabella:
        raise SNMPError("nessun contatore letto (SNMP off o host irraggiungibile)")
    out = {}
    mancanti = []
    for cat, num in cmap.items():
        if num in tabella:
            out[cat] = tabella[num]
        else:
            mancanti.append(num)
    if mancanti:
        raise SNMPError(f"contatori assenti nella macchina: {mancanti}")
    return out
