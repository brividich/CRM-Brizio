"""
Lettura contatori via SNMP (puresnmp). Importazione lazy: la web-app parte anche
se puresnmp non e' installato; l'errore emerge solo al momento della lettura.

La mappa numero-contatore -> categoria (A4 BN, A3 BN, A4 COL, A3 COL) va
determinata una volta per modello con lo script `discover` e messa in COUNTER_MAP
o, in produzione, su un modello dedicato. Qui e' un dizionario semplice.
"""
import asyncio
import functools
import re
from time import monotonic

# Two specification passes plus printer discovery must fit the 110s job limit.
SPECIFICATION_BUDGET = 30.0
WALK_BUDGET = 10.0
MAX_WALK_ROWS = 256

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


# Discovery di rete: OID standard per identificare il dispositivo.
SYS_DESCR = "1.3.6.1.2.1.1.1.0"              # descrizione (contiene il modello)
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"          # identificatore enterprise/modello
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"             # centesimi di secondo dall'avvio
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"            # referente configurato sul device
SYS_NAME = "1.3.6.1.2.1.1.5.0"               # nome host della stampante
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"           # posizione configurata sul device
PRT_SERIAL = "1.3.6.1.2.1.43.5.1.1.17.1"     # Printer-MIB: numero di serie (= matricola)

SYSTEM_OIDS = (
    SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_CONTACT, SYS_NAME, SYS_LOCATION,
    PRT_SERIAL,
)
_OID_RE = re.compile(r"^\d+(?:\.\d+)+$")

# Cap di sicurezza: una scansione parte da una richiesta web, non deve poter
# esplodere su un range enorme.
MAX_HOST_SCAN = 512


class SNMPError(RuntimeError):
    pass


def _testo(valore):
    if isinstance(valore, bytes):
        return valore.decode("latin-1", "replace").strip()
    return str(valore).strip() if valore is not None else ""


def leggi_oids(host, oids, community="novicromprinter", port=161, timeout=3,
               version="v1", *, max_duration=SPECIFICATION_BUDGET):
    """Legge una lista esplicita di OID con sole operazioni GET.

    Ritorna ``(valori, errori)`` indicizzati per OID. Un errore su una sonda non
    interrompe le altre; se nessun OID risponde viene sollevato :class:`SNMPError`.
    """
    if not host:
        raise SNMPError("host non impostato")
    richiesti = list(dict.fromkeys(str(oid).strip() for oid in oids))
    non_validi = [oid for oid in richiesti if not _OID_RE.fullmatch(oid)]
    if non_validi:
        raise SNMPError(f"OID non valido: {non_validi[0]}")

    try:
        from puresnmp import Client, V1, V2C, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = V1(community) if version == "v1" else V2C(community)

    async def _run():
        sender = functools.partial(send_udp, timeout=timeout)
        client = PyWrapper(Client(str(host), cred, port=port, sender=sender))
        valori, errori = {}, {}
        deadline = monotonic() + max_duration
        for oid in richiesti:
            remaining = deadline - monotonic()
            if remaining <= 0:
                errori[oid] = 'Tempo complessivo di lettura SNMP superato'
                continue
            try:
                valori[oid] = await asyncio.wait_for(client.get(oid), timeout=remaining)
            except asyncio.TimeoutError:
                errori[oid] = 'Tempo complessivo di lettura SNMP superato'
            except Exception as exc:  # ogni OID resta indipendente
                errori[oid] = str(exc)[:500]
        return valori, errori

    try:
        valori, errori = asyncio.run(_run())
    except Exception as e:
        raise SNMPError(f"{host}: {e}") from e
    if not valori:
        dettaglio = next(iter(errori.values()), "nessuna risposta")
        raise SNMPError(f"{host}: {dettaglio}")
    return valori, errori


def leggi_colonna(host, oid, community="novicromprinter", port=161, timeout=3,
                   version="v1", *, max_duration=WALK_BUDGET):
    """Esegue un WALK read-only e restituisce i valori della colonna MIB."""
    if not host:
        raise SNMPError("host non impostato")
    oid = str(oid).strip()
    if not _OID_RE.fullmatch(oid):
        raise SNMPError(f"OID non valido: {oid}")
    try:
        from puresnmp import Client, V1, V2C, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = V1(community) if version == "v1" else V2C(community)

    async def _run():
        sender = functools.partial(send_udp, timeout=timeout)
        client = PyWrapper(Client(str(host), cred, port=port, sender=sender))
        valori = []
        async for vb in client.walk(oid):
            if len(valori) >= MAX_WALK_ROWS:
                raise SNMPError('Colonna SNMP oltre il limite di 256 righe')
            valori.append(vb.value)
        return valori

    async def _bounded():
        return await asyncio.wait_for(_run(), timeout=max_duration)

    try:
        valori = asyncio.run(_bounded())
    except asyncio.TimeoutError as e:
        raise SNMPError('Tempo complessivo del WALK SNMP superato') from e
    except Exception as e:
        raise SNMPError(f"{host}: {e}") from e
    if not valori:
        raise SNMPError(f"{host}: colonna {oid} senza valori")
    return valori


def aggrega_colonna(valori, aggregazione="PRIMO"):
    """Riduce una colonna WALK a un valore singolo secondo il profilo."""
    if not valori:
        raise SNMPError("colonna senza valori")
    if aggregazione == "PRIMO":
        return valori[0]
    try:
        numeri = [int(str(v).strip()) for v in valori]
    except (TypeError, ValueError) as exc:
        raise SNMPError("la colonna contiene valori non numerici") from exc
    if aggregazione == "MASSIMO":
        return max(numeri)
    if aggregazione == "MINIMO":
        return min(numeri)
    if aggregazione == "SOMMA":
        return sum(numeri)
    raise SNMPError(f"aggregazione non supportata: {aggregazione}")


def leggi_specifiche(host, specifiche, community="novicromprinter", port=161,
                     timeout=3, version="v1"):
    """Legge specifiche GET/WALK e ritorna ``(valori, errori)`` per OID."""
    specifiche = list(specifiche)
    deadline = monotonic() + SPECIFICATION_BUDGET
    get_oids = [s["oid"] for s in specifiche if s.get("modalita", "GET") == "GET"]
    valori, errori = ({}, {})
    if get_oids:
        try:
            valori, errori = leggi_oids(
                host, get_oids, community=community, port=port,
                timeout=timeout, version=version,
                max_duration=max(0, deadline - monotonic()),
            )
        except SNMPError as exc:
            errori.update({oid: str(exc) for oid in get_oids})
    for spec in specifiche:
        if spec.get("modalita", "GET") != "WALK":
            continue
        oid = spec["oid"]
        remaining = deadline - monotonic()
        if remaining <= 0:
            errori[oid] = 'Tempo complessivo di lettura SNMP superato'
            continue
        try:
            colonna = leggi_colonna(
                host, oid, community=community, port=port,
                timeout=timeout, version=version,
                max_duration=min(WALK_BUDGET, remaining),
            )
            valori[oid] = aggrega_colonna(colonna, spec.get("aggregazione", "PRIMO"))
        except SNMPError as exc:
            errori[oid] = str(exc)
    if not valori:
        dettaglio = next(iter(errori.values()), "nessuna risposta")
        raise SNMPError(f"{host}: {dettaglio}")
    return valori, errori


class EsitoDiscovery(list):
    """Lista compatibile con i chiamanti storici, con copertura della scansione."""

    def __init__(self):
        super().__init__()
        self.completati = 0
        self.totali = 0
        self.incompleta = False


def scansiona_rete(rete, community="novicromprinter", port=161, timeout=2,
                   version="v1", concurrency=32, *, communities=None, max_duration=20):
    """GET limitati nel tempo; conserva host trovati anche senza OID opzionali.

    communities e' una lista ordinata, massimo otto community read-only.
    Nei risultati compare solo la posizione della community, mai il segreto.
    """
    import ipaddress

    try:
        net = ipaddress.ip_network(str(rete).strip(), strict=False)
    except ValueError as e:
        raise SNMPError("Rete non valida: usa una notazione tipo 10.0.0.0/24") from e
    # Controllare prima di materializzare hosts(): anche un /0 deve fallire subito.
    host_count = net.num_addresses - (2 if net.version == 4 and net.prefixlen < 31
                                      else 1 if net.version == 6 and net.prefixlen < 127 else 0)
    if host_count > MAX_HOST_SCAN:
        raise SNMPError(f"Range troppo ampio: massimo {MAX_HOST_SCAN} host. Restringi la maschera.")
    candidates = list(communities if communities is not None else [community])
    if not candidates or len(candidates) > 8 or any(not c or len(c) > 60 for c in candidates):
        raise SNMPError("Inserisci da 1 a 8 community, massimo 60 caratteri ciascuna.")
    if version not in ("v1", "v2c"):
        raise SNMPError("Versione SNMP non valida.")
    if timeout <= 0 or max_duration <= 0:
        raise SNMPError("Il timeout deve essere positivo.")
    host_list = [str(h) for h in net.hosts()]
    try:
        from puresnmp import Client, V1, V2C, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    result = EsitoDiscovery()
    result.totali = len(host_list)

    async def _sonda(host, sem):
        async with sem:
            for index, candidate in enumerate(candidates, 1):
                cred = V1(candidate) if version == "v1" else V2C(candidate)
                sender = functools.partial(send_udp, timeout=timeout)
                client = PyWrapper(Client(host, cred, port=port, sender=sender))
                try:
                    descr = await asyncio.wait_for(client.get(SYS_DESCR), timeout=timeout)
                except Exception:
                    continue
                trovato = {"host": host, "descr": _testo(descr), "nome": "",
                           "matricola": "", "community_index": index}
                result.append(trovato)
                for oid, chiave in ((SYS_NAME, "nome"), (PRT_SERIAL, "matricola")):
                    try:
                        trovato[chiave] = _testo(await asyncio.wait_for(client.get(oid), timeout=timeout))
                    except Exception:
                        pass
                break
            result.completati += 1

    async def _run():
        sem = asyncio.Semaphore(max(1, min(64, int(concurrency))))
        tasks = [asyncio.create_task(_sonda(h, sem)) for h in host_list]
        try:
            _, pending = await asyncio.wait(tasks, timeout=max_duration)
            result.incompleta = bool(pending)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        if any(isinstance(item, Exception) for item in outcomes):
            raise SNMPError("Errore interno nella scansione SNMP; controllare i parametri.")
        result.sort(key=lambda row: ipaddress.ip_address(row["host"]))
        return result

    try:
        return asyncio.run(_run())
    except SNMPError:
        raise
    except Exception as e:
        raise SNMPError("Scansione SNMP fallita; controllare rete e parametri.") from e


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
        noti = ", ".join(sorted(COUNTER_MAP))
        raise SNMPError(
            f"modello '{macchina.modello}' senza counter_map: imposta il modello esatto "
            f"nella scheda macchina (mappati: {noti}). Se la macchina e' un altro modello, "
            f"verifica prima i numeri contatore con `manage.py snmp_discover`."
        )
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
