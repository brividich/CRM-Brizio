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


NESSUNA_RISPOSTA = (
    "nessuna risposta dall'apparato entro il tempo massimo. Cause possibili: apparato "
    "spento o irraggiungibile; servizio SNMP disattivato; community o versione SNMP "
    "errata (molti apparati scartano in silenzio le richieste non autorizzate); "
    "IP del portale non tra i gestori ammessi; porta UDP 161 bloccata dal firewall"
)

# error-status RFC 3416 -> (nome, spiegazione e cosa fare)
_ERRORI_PDU = {
    1: ("tooBig", "risposta troppo grande per un singolo pacchetto: riduci gli OID "
                  "letti insieme"),
    2: ("noSuchName", "l'OID{oid} non esiste su questo apparato: il profilo usa un OID "
                      "che il modello non espone. Disattiva la colonna o assegna un "
                      "profilo adatto al modello"),
    5: ("genErr", "l'agente SNMP dell'apparato non e' riuscito a calcolare il valore"
                  "{oid}: riprova; se si ripete disattiva la colonna"),
    6: ("noAccess", "la community/utente non ha accesso all'OID{oid}: la vista SNMP "
                    "configurata sull'apparato non include questo ramo"),
    13: ("resourceUnavailable", "l'apparato non ha risorse libere per rispondere: "
                                "riprova piu' tardi"),
    16: ("authorizationError", "l'apparato riceve la richiesta ma la rifiuta. Non e' un "
                               "problema di OID. Controlla: la community deve essere "
                               "identica a quella dell'apparato (maiuscole comprese) e "
                               "avere permesso di lettura (su HPE Aruba: operator o "
                               "manager); l'apparato non deve accettare solo SNMPv3 "
                               "(Aruba: 'snmpv3 only' - in quel caso imposta v3 nel "
                               "portale); l'IP del portale deve essere tra i gestori "
                               "ammessi (Aruba: 'ip authorized-managers')"),
}

# Report SNMPv3 (USM) e altri messaggi della libreria -> spiegazione
_ERRORI_TESTO = (
    ("unknown user", "utente SNMPv3 sconosciuto all'apparato: controlla il nome utente"),
    ("wrong message digest", "autenticazione SNMPv3 fallita: chiave o protocollo "
                             "(MD5/SHA) diversi da quelli dell'apparato"),
    ("unable to decrypt", "cifratura SNMPv3 errata: chiave o protocollo (DES/AES) "
                          "diversi da quelli dell'apparato"),
    ("not in time window", "SNMPv3 fuori finestra temporale: riprova la lettura"),
    ("unknown engine-id", "engine-id SNMPv3 non riconosciuto: riprova la lettura"),
    ("unsupported security level", "livello di sicurezza SNMPv3 non accettato "
                                   "dall'apparato: allinea autenticazione e cifratura"),
    ("mismatching community", "l'apparato ha risposto con una community diversa"),
)


def descrivi_errore(exc, oid=None):
    """Traduce un'eccezione puresnmp/rete in un messaggio italiano azionabile.

    Il testo non contiene mai la community ne' le chiavi v3.
    """
    if isinstance(exc, SNMPError):
        return str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return NESSUNA_RISPOSTA
    nome_classe = type(exc).__name__
    stato = getattr(exc, "error_status", None)
    if isinstance(stato, int) and stato:
        offending = str(getattr(exc, "offending_oid", "") or oid or "").lstrip(".")
        nome, spiegazione = _ERRORI_PDU.get(
            stato, (nome_classe, "errore restituito dall'apparato{oid}"))
        dettaglio = spiegazione.format(oid=f" {offending}" if offending else "")
        return f"{dettaglio} (errore SNMP {nome}, codice {stato})"
    if nome_classe == "Timeout":
        return NESSUNA_RISPOSTA
    testo = str(exc)
    minuscolo = testo.lower()
    for chiave, spiegazione in _ERRORI_TESTO:
        if chiave in minuscolo:
            return spiegazione
    if nome_classe == "AuthenticationError":
        return _ERRORI_TESTO[1][1]
    if nome_classe == "DecryptionError":
        return _ERRORI_TESTO[2][1]
    if isinstance(exc, ConnectionResetError):
        return ("l'apparato ha rifiutato la connessione sulla porta UDP 161: "
                "il servizio SNMP non e' attivo")
    if isinstance(exc, OSError):
        return f"errore di rete verso l'apparato: {testo or nome_classe}"
    return testo or nome_classe


V3_AUTH = ("md5", "sha1")
V3_PRIV = ("des", "aes")


def segreto_v3(utente, auth="", auth_key="", priv="", priv_key=""):
    """Serializza le credenziali SNMPv3 nel "segreto" unico (poi cifrato dal chiamante)."""
    import json
    if not utente:
        raise SNMPError("SNMPv3 richiede un utente")
    if auth and auth not in V3_AUTH:
        raise SNMPError(f"Protocollo di autenticazione SNMPv3 non valido: {auth}")
    if priv and priv not in V3_PRIV:
        raise SNMPError(f"Protocollo di cifratura SNMPv3 non valido: {priv}")
    if priv and not auth:
        raise SNMPError("SNMPv3 con cifratura richiede anche l'autenticazione")
    if (auth and not auth_key) or (priv and not priv_key):
        raise SNMPError("Chiave SNMPv3 mancante")
    return json.dumps({"u": utente, "a": auth, "ak": auth_key, "p": priv, "pk": priv_key})


def costruisci_credenziali(segreto, version):
    """Unico punto che crea le credenziali puresnmp: V1, V2C o V3.

    Per v3 ``segreto`` e' il JSON prodotto da :func:`segreto_v3`. I messaggi
    d'errore non contengono mai chiavi.
    """
    try:
        from puresnmp import V1, V2C
        from puresnmp.credentials import V3, Auth, Priv
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e
    if version == "v1":
        return V1(segreto)
    if version != "v3":
        return V2C(segreto)
    import importlib.util
    import json
    try:
        d = json.loads(segreto)
        utente = d["u"]
    except (ValueError, KeyError, TypeError) as e:
        raise SNMPError("Credenziali SNMPv3 non valide: aggiorna il catalogo") from e
    auth = Auth(d.get("ak", "").encode(), d["a"]) if d.get("a") else None
    priv = None
    if d.get("p"):
        if auth is None:
            raise SNMPError("SNMPv3 con cifratura richiede anche l'autenticazione")
        if importlib.util.find_spec(f"puresnmp_plugins.priv.{d['p']}") is None:
            raise SNMPError(f"Cifratura SNMPv3 '{d['p']}' non disponibile: "
                            "installare puresnmp-crypto")
        priv = Priv(d.get("pk", "").encode(), d["p"])
    return V3(utente, auth=auth, priv=priv)


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
        from puresnmp import Client, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = costruisci_credenziali(community, version)

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
            except Exception as exc:  # ogni OID resta indipendente
                errori[oid] = descrivi_errore(exc, oid)[:500]
        return valori, errori

    try:
        valori, errori = asyncio.run(_run())
    except Exception as e:
        raise SNMPError(f"{host}: {descrivi_errore(e)}") from e
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
        from puresnmp import Client, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = costruisci_credenziali(community, version)

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
        raise SNMPError(f"Tempo complessivo del WALK SNMP superato: {NESSUNA_RISPOSTA}") from e
    except SNMPError:
        raise
    except Exception as e:
        raise SNMPError(f"{host}: {descrivi_errore(e, oid)}") from e
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
    if aggregazione == "MEDIA":
        return round(sum(numeri) / len(numeri), 2)
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


def hosts_rete(rete):
    """Valida la dimensione prima di enumerare gli indirizzi."""
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
    return [str(h) for h in net.hosts()]


def scansiona_rete(rete, community="novicromprinter", port=161, timeout=2,
                   version="v1", concurrency=32, *, communities=None, max_duration=20):
    return scansiona_hosts(hosts_rete(rete), community=community, port=port,
                           timeout=timeout, version=version, concurrency=concurrency,
                           communities=communities, max_duration=max_duration)


def scansiona_hosts(hosts, community="novicromprinter", port=161, timeout=2,
                    version="v1", concurrency=32, *, communities=None, max_duration=20):
    """Sonda un elenco limitato di IP, preservando risultati parziali."""
    import ipaddress

    if not hosts or len(hosts) > MAX_HOST_SCAN:
        raise SNMPError("Elenco host vuoto o troppo ampio.")
    try:
        host_list = list(dict.fromkeys(str(ipaddress.ip_address(h)) for h in hosts))
    except ValueError as e:
        raise SNMPError("Indirizzo host non valido.") from e
    candidates = list(communities if communities is not None else [community])
    if not candidates or len(candidates) > 8 or any(
            not c or len(c) > (1000 if version == "v3" else 60) for c in candidates):
        raise SNMPError("Inserisci da 1 a 8 community, massimo 60 caratteri ciascuna.")
    if version not in ("v1", "v2c", "v3"):
        raise SNMPError("Versione SNMP non valida.")
    if timeout <= 0 or max_duration <= 0:
        raise SNMPError("Il timeout deve essere positivo.")
    try:
        from puresnmp import Client, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    result = EsitoDiscovery()
    result.totali = len(host_list)

    async def _sonda(host, sem):
        async with sem:
            for index, candidate in enumerate(candidates, 1):
                cred = costruisci_credenziali(candidate, version)
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
        from puresnmp import Client, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = costruisci_credenziali(community, version)

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
        raise SNMPError(f"{host}: {descrivi_errore(e)}") from e


def _consumabili_raw(host, community, port, timeout, version):
    """Legge prtMarkerSuppliesTable -> lista ordinata di (nome, livello, max)."""
    try:
        from puresnmp import Client, PyWrapper
        from puresnmp.transport import send_udp
    except ImportError as e:
        raise SNMPError("puresnmp non installato (pip install puresnmp)") from e

    cred = costruisci_credenziali(community, version)

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
        raise SNMPError(f"{host}: {descrivi_errore(e)}") from e


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
