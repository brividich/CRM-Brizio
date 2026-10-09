"""Catalogo degli errori SNMP: codice stabile, causa probabile e azione correttiva.

Unico punto usato da wizard, schede, Centrale e job notturni. I messaggi tecnici
restano quelli di :func:`contatori.snmp.descrivi_errore` (gia' in italiano e senza
segreti); qui si aggiunge il codice e il «cosa fare», anche partendo dal testo
gia' salvato in ``snmp_ultimo_errore``.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass

from .snmp import SNMPError

DNS_TIMEOUT = 3  # secondi: la risoluzione non deve bloccare la richiesta web
VALORE_MASSIMO = 10 ** 12  # oltre, un contatore e' certamente un valore sballato


@dataclass(frozen=True)
class VoceErrore:
    codice: str
    titolo: str
    azione: str


CATALOGO = {v.codice: v for v in (
    VoceErrore("SNMP-001", "Indirizzo non valido",
               "Inserisci un IPv4 (es. 192.0.2.10) o un nome host risolvibile, senza http:// né spazi."),
    VoceErrore("SNMP-002", "Nome host non risolto",
               "Verifica il nome nel DNS aziendale oppure usa direttamente l'indirizzo IP."),
    VoceErrore("SNMP-003", "Nessuna risposta",
               "Cause: dispositivo spento, IP errato, SNMP disattivato, firewall o VLAN che bloccano "
               "UDP 161. Con v1/v2c anche una community errata produce un timeout: molti apparati "
               "scartano in silenzio le richieste non autorizzate."),
    VoceErrore("SNMP-004", "Credenziali SNMPv3 rifiutate",
               "Controlla utente, protocollo e chiave di autenticazione (e di cifratura, se usata): "
               "devono coincidere con quelli configurati sull'apparato."),
    VoceErrore("SNMP-005", "OID non esposto dal dispositivo",
               "Il dispositivo risponde ma non conosce questo OID: il profilo non è adatto al modello. "
               "Scegli un altro profilo o disattiva la colonna."),
    VoceErrore("SNMP-006", "Valore letto non valido",
               "Il valore non è un numero plausibile per un contatore: verifica che l'OID del profilo "
               "sia quello giusto per questo modello."),
    VoceErrore("SNMP-007", "Richiesta rifiutata per permessi",
               "La community è giusta ma non ha accesso in lettura, oppure l'IP del portale non è tra "
               "i gestori ammessi o l'apparato accetta solo SNMPv3."),
    VoceErrore("SNMP-008", "Credenziali SNMP non configurate",
               "Seleziona una community dal catalogo o inseriscila: il portale non usa più una "
               "community predefinita."),
    VoceErrore("SNMP-000", "Errore SNMP",
               "Riprova; se si ripete controlla il dettaglio e la configurazione dell'apparato."),
)}

# (codice, frammenti del testo prodotto da descrivi_errore o dalla libreria), in ordine
_REGOLE = (
    ("SNMP-008", ("community snmp non configurata", "credenziali snmp non configurate")),
    # Prima dei permessi v3: il testo del codice 16 cita anche «snmpv3 only».
    ("SNMP-007", ("codice 16", "authorizationerror", "codice 6)", "noaccess")),
    ("SNMP-004", ("snmpv3", "unknown user", "wrong message digest", "unable to decrypt",
                  "authenticationerror", "decryptionerror")),
    ("SNMP-005", ("nosuchname", "nosuchobject", "nosuchinstance", "non esiste su questo apparato")),
    ("SNMP-003", ("nessuna risposta", "timeout", "tempo complessivo")),
    ("SNMP-006", ("non numeric", "valore letto non valido")),
)


class ErroreSNMPCatalogato(SNMPError):
    """SNMPError con codice di catalogo: ``str()`` e' il messaggio per l'utente."""

    def __init__(self, codice, messaggio):
        self.codice = codice
        self.voce = CATALOGO[codice]
        super().__init__(messaggio)


def classifica(testo) -> VoceErrore:
    minuscolo = str(testo or "").lower()
    trovato = re.search(r"\[(SNMP-\d{3})\]", str(testo or ""))
    if trovato and trovato.group(1) in CATALOGO:
        return CATALOGO[trovato.group(1)]
    for codice, frammenti in _REGOLE:
        if any(f in minuscolo for f in frammenti):
            return CATALOGO[codice]
    return CATALOGO["SNMP-000"]


def da_eccezione(exc, *, oid=None, host=None, porta=None, timeout=None) -> dict:
    """{codice, titolo, messaggio, azione} per un'eccezione di lettura SNMP."""
    from .snmp import descrivi_errore
    if isinstance(exc, ErroreSNMPCatalogato):
        voce, messaggio = exc.voce, str(exc)
    else:
        messaggio = descrivi_errore(exc, oid)
        voce = classifica(messaggio)
        if voce.codice == "SNMP-003" and host:
            messaggio = f"Nessuna risposta da {host}:{porta or 161} in {timeout or 3} s."
    return {"codice": voce.codice, "titolo": voce.titolo, "messaggio": messaggio[:500],
            "azione": voce.azione}


def testo_con_codice(exc_o_testo, oid=None) -> str:
    """Testo da salvare in ``snmp_ultimo_errore``: «[SNMP-00x] dettaglio», max 500."""
    if isinstance(exc_o_testo, BaseException):
        err = da_eccezione(exc_o_testo, oid=oid)
        codice, messaggio = err["codice"], err["messaggio"]
    else:
        messaggio = str(exc_o_testo or "")
        codice = classifica(messaggio).codice
    if messaggio.startswith(f"[{codice}]"):
        return messaggio[:500]
    return f"[{codice}] {messaggio}"[:500]


_NOME_HOST_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$")


def valida_host(valore, *, timeout=DNS_TIMEOUT) -> str:
    """IPv4/IPv6 normalizzato; un nome host viene risolto (IPv4 preferito).

    Solleva ErroreSNMPCatalogato SNMP-001 (formato) o SNMP-002 (DNS).
    """
    testo = str(valore or "").strip()
    try:
        return _indirizzo_ammesso(ipaddress.ip_address(testo))
    except ValueError:
        pass
    if not _NOME_HOST_RE.fullmatch(testo) or testo.replace(".", "").isdigit():
        raise ErroreSNMPCatalogato(
            "SNMP-001", "Indirizzo non valido: inserisci un IPv4 o un nome risolvibile.")
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        risposte = pool.submit(socket.getaddrinfo, testo, 161, 0, socket.SOCK_DGRAM).result(timeout=timeout)
    except (OSError, FuturesTimeout) as e:
        raise ErroreSNMPCatalogato(
            "SNMP-002", f"Il nome {testo} non si risolve: verifica il DNS o usa l'IP.") from e
    finally:
        pool.shutdown(wait=False)
    indirizzi = sorted({r[4][0] for r in risposte}, key=lambda ip: ":" in ip)  # IPv4 prima
    if not indirizzi:
        raise ErroreSNMPCatalogato(
            "SNMP-002", f"Il nome {testo} non si risolve: verifica il DNS o usa l'IP.")
    return _indirizzo_ammesso(ipaddress.ip_address(indirizzi[0]))


def _indirizzo_ammesso(ip) -> str:
    """Solo indirizzi di apparati: niente loopback, link-local, multicast o riservati.

    Evita che il test di connessione diventi una sonda verso il server stesso o
    verso indirizzi speciali (e che una credenziale venga inviata li').
    """
    if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        raise ErroreSNMPCatalogato(
            "SNMP-001", f"Indirizzo non valido: {ip} è un indirizzo speciale (loopback, link-local, "
                        "multicast o riservato), non quello di un apparato.")
    return str(ip)


def valore_numerico(valore, nome) -> int:
    """Intero >= 0 plausibile per un contatore, altrimenti SNMP-006."""
    grezzo = valore.decode("latin-1", "replace") if isinstance(valore, bytes) else valore
    try:
        numero = int(str(grezzo).strip())
    except (TypeError, ValueError):
        numero = None
    if numero is None or numero < 0 or numero > VALORE_MASSIMO:
        mostrato = str(grezzo)[:40] if grezzo is not None else "vuoto"
        raise ErroreSNMPCatalogato(
            "SNMP-006", f"Valore letto non valido per il contatore {nome}: «{mostrato}».")
    return numero
