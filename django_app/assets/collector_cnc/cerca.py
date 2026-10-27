"""
cerca.py - Cerca in una rete i server OPC UA delle CNC DMG MORI (IoTconnector), in sola lettura.

Prima prova ogni indirizzo della rete sulla porta OPC UA (connessione TCP con attesa breve), poi
sugli indirizzi che rispondono apre una sessione OPC UA e legge solo l'array dei namespace: da li'
la matricola (namespace DMG MORI, come nel collector) e il modello dati (umati o BasicDataSet).
Niente scritture e niente metodi. Prima l'accesso anonimo, poi le credenziali gia' salvate nel portale.

Lo usa la pagina Macchine collegate («Cerca le macchine in rete»): rete al massimo /24, solo IPv4 interni.
"""
import asyncio
import ipaddress
import logging

try:
    from .drivers.opcua import CONNECT_TIMEOUT, DMG_MACHINE_URI, UMATI_URI, client_sola_lettura   # dentro il portale
except ImportError:
    from drivers.opcua import CONNECT_TIMEOUT, DMG_MACHINE_URI, UMATI_URI, client_sola_lettura    # sul PC dell'officina

TCP_TIMEOUT = 1.0        # s - attesa della porta aperta
MAX_TCP = 128            # prove TCP in parallelo
MAX_OPCUA = 12           # sessioni OPC UA in parallelo
MAX_INDIRIZZI = 256      # al massimo una /24

log = logging.getLogger("collector.cerca")


def indirizzi(rete):
    """Gli host di una rete IPv4 interna (al massimo /24); ValueError con il motivo."""
    try:
        net = ipaddress.ip_network(str(rete or "").strip(), strict=False)
    except ValueError:
        raise ValueError("Rete non valida: scrivila come 192.168.23.0/24.") from None
    if net.version != 4 or not net.is_private:
        raise ValueError("Solo reti IPv4 interne (es. 192.168.23.0/24).")
    if net.num_addresses > MAX_INDIRIZZI:
        raise ValueError("Rete troppo grande: al massimo 256 indirizzi (/24).")
    return [str(h) for h in (list(net.hosts()) or [net.network_address])]


async def _porta_aperta(ip, porta, sem):
    async with sem:
        try:
            _lettore, scrittore = await asyncio.wait_for(asyncio.open_connection(ip, porta), TCP_TIMEOUT)
        except (OSError, asyncio.TimeoutError):
            return False
        scrittore.close()
        try:
            await scrittore.wait_closed()
        except OSError:
            pass
        return True


def _accesso_negato(errore):
    nome = type(errore).__name__
    return "Identity" in nome or "UserAccessDenied" in nome


async def _leggi_server(ip, porta, credenziali, sem):
    """``{"ip", "porta", "dmg", "matricola", "modello", "credenziali", "errore"}`` di un server che risponde.

    ``credenziali``: ``[(utente, password, chiave)]`` da provare dopo l'accesso anonimo; in uscita
    ``credenziali`` e' la chiave di quelle che hanno funzionato (None = anonimo).
    ``errore``: "" | "accesso" (servono utente e password) | testo breve dell'errore OPC UA.
    """
    esito = {"ip": ip, "porta": porta, "dmg": False, "matricola": "", "modello": "", "credenziali": None, "errore": ""}
    async with sem:
        for cred in [None, *credenziali]:
            client = client_sola_lettura(f"opc.tcp://{ip}:{porta}", CONNECT_TIMEOUT,
                                         cred[0] if cred else None, cred[1] if cred else None)
            try:
                await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT + 2)
            except Exception as e:  # noqa: BLE001 - qualunque errore = server non leggibile, lo si dice nell'esito
                if _accesso_negato(e):
                    esito["errore"] = "accesso"
                    continue
                esito["errore"] = f"non risponde come server OPC UA ({type(e).__name__})"
                return esito
            try:
                nsarr = await asyncio.wait_for(client.get_namespace_array(), CONNECT_TIMEOUT)
            except Exception as e:  # noqa: BLE001 - sessione aperta ma namespace non letti
                esito["errore"] = f"namespace non letti ({type(e).__name__})"
                return esito
            finally:
                try:
                    await asyncio.wait_for(client.disconnect(), 5)
                except Exception as e:  # noqa: BLE001 - la sessione si chiude comunque lato server
                    log.debug("%s: disconnessione non pulita: %s", ip, e)
            esito["errore"] = ""
            esito["credenziali"] = cred[2] if cred else None
            dmg = next((u for u in nsarr if DMG_MACHINE_URI in u), None)
            if dmg:
                esito["dmg"] = True
                esito["matricola"] = dmg.rstrip("/").split("/")[-1][:60]
                esito["modello"] = "umati" if UMATI_URI in nsarr else "bds"
            return esito
    return esito


async def cerca(rete, porta=4840, credenziali=()):
    """I server OPC UA della rete, in ordine di indirizzo (vedi ``_leggi_server``)."""
    host = indirizzi(rete)
    sem_tcp = asyncio.Semaphore(MAX_TCP)
    aperte = await asyncio.gather(*(_porta_aperta(ip, porta, sem_tcp) for ip in host))
    sem_opcua = asyncio.Semaphore(MAX_OPCUA)
    trovati = [ip for ip, aperta in zip(host, aperte, strict=True) if aperta]
    return list(await asyncio.gather(*(_leggi_server(ip, porta, list(credenziali), sem_opcua) for ip in trovati)))
