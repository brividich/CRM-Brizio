"""Ricevitore syslog (UDP e TCP) per ESXi, switch, firewall, NAS e server Linux.

Accetta solo i messaggi che arrivano dagli indirizzi scritti nelle fonti: gli altri si
contano (la pagina Fonti li mostra come «indirizzi non configurati») ma non si archiviano.
Un apparato che manda troppi messaggi al secondo viene limitato: i messaggi scartati si
contano e diventano un'interruzione «Troppi messaggi», così la verifica sa che mancano.

Va in ascolto solo sulla rete interna: aprire la porta nel firewall di Windows del server
solo per gli indirizzi degli apparati.
"""
from __future__ import annotations

import logging
import queue
import socket
import socketserver
import threading
import time
from collections import Counter
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_MESSAGGIO = 65535
MAX_AL_SECONDO = 500  # per indirizzo: oltre, si scarta e si conta


class Limitatore:
    """Secchiello di gettoni per indirizzo."""

    def __init__(self, al_secondo: int = MAX_AL_SECONDO):
        self.al_secondo = al_secondo
        self._stato: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def passa(self, ip: str) -> bool:
        ora = time.monotonic()
        with self._lock:
            gettoni, prima = self._stato.get(ip, (float(self.al_secondo), ora))
            gettoni = min(float(self.al_secondo), gettoni + (ora - prima) * self.al_secondo)
            if gettoni < 1:
                self._stato[ip] = (gettoni, ora)
                return False
            self._stato[ip] = (gettoni - 1, ora)
            return True


class Ricevitore:
    """Mette in ``coda`` le tuple ``("syslog", fonte_id, raw, ip, ricevuto)``."""

    def __init__(self, indirizzo: str, porta: int, tcp: bool, coda: queue.Queue, fonte_per_ip):
        self.indirizzo, self.porta, self.tcp = indirizzo or "0.0.0.0", int(porta), bool(tcp)
        self.coda = coda
        self.fonte_per_ip = fonte_per_ip  # callable ip -> fonte_id | None
        self.limitatore = Limitatore()
        self.scartati: Counter = Counter()
        self.sconosciuti: Counter = Counter()
        self._lock = threading.Lock()
        self._udp: socket.socket | None = None
        self._tcp: socketserver.ThreadingTCPServer | None = None
        self.in_ascolto = ""

    # -- ingresso comune ---------------------------------------------------------------
    def ricevi(self, raw: bytes, ip: str, ricevuto: datetime | None = None) -> bool:
        raw = raw.strip(b"\x00\r\n")
        if not raw:
            return False
        fonte_id = self.fonte_per_ip(ip)
        if fonte_id is None:
            with self._lock:
                self.sconosciuti[ip] += 1
            return False
        if not self.limitatore.passa(ip):
            with self._lock:
                self.scartati[ip] += 1
            return False
        try:
            self.coda.put(("syslog", fonte_id, raw[:MAX_MESSAGGIO], ip, ricevuto or timezone.now()), timeout=2)
        except queue.Full:
            with self._lock:
                self.scartati[ip] += 1
            return False
        return True

    def preleva_contatori(self) -> tuple[Counter, Counter]:
        with self._lock:
            scartati, sconosciuti = self.scartati, self.sconosciuti
            self.scartati, self.sconosciuti = Counter(), Counter()
        return scartati, sconosciuti

    # -- UDP --------------------------------------------------------------------------
    def _ciclo_udp(self):
        while self._udp is not None:
            try:
                dati, (ip, _porta) = self._udp.recvfrom(MAX_MESSAGGIO)
            except OSError:
                if self._udp is None:
                    return
                continue
            self.ricevi(dati, ip)

    # -- TCP (righe separate da a capo, oppure «lunghezza spazio messaggio», RFC 6587) --
    def _gestore_tcp(self):
        ricevitore = self

        class Gestore(socketserver.StreamRequestHandler):
            timeout = 300

            def handle(self):
                ip = self.client_address[0]
                if ricevitore.fonte_per_ip(ip) is None:
                    with ricevitore._lock:
                        ricevitore.sconosciuti[ip] += 1
                    return
                buffer = b""
                while True:
                    try:
                        blocco = self.request.recv(65536)
                    except OSError:
                        return
                    if not blocco:
                        return
                    buffer += blocco
                    while buffer:
                        primo = buffer.split(b" ", 1)[0]
                        if primo.isdigit() and b" " in buffer:
                            lung = int(primo)
                            inizio = len(primo) + 1
                            if len(buffer) < inizio + lung:
                                break
                            ricevitore.ricevi(buffer[inizio:inizio + lung], ip)
                            buffer = buffer[inizio + lung:]
                            continue
                        if b"\n" not in buffer:
                            if len(buffer) > MAX_MESSAGGIO:
                                ricevitore.ricevi(buffer, ip)
                                buffer = b""
                            break
                        riga, buffer = buffer.split(b"\n", 1)
                        ricevitore.ricevi(riga, ip)

        return Gestore

    def avvia(self) -> str:
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        self._udp.bind((self.indirizzo, self.porta))
        threading.Thread(target=self._ciclo_udp, name="syslog-udp", daemon=True).start()
        parti = [f"UDP {self.indirizzo}:{self.porta}"]
        if self.tcp:
            socketserver.ThreadingTCPServer.allow_reuse_address = True
            socketserver.ThreadingTCPServer.daemon_threads = True
            self._tcp = socketserver.ThreadingTCPServer((self.indirizzo, self.porta), self._gestore_tcp())
            threading.Thread(target=self._tcp.serve_forever, name="syslog-tcp", daemon=True).start()
            parti.append(f"TCP {self.indirizzo}:{self.porta}")
        self.in_ascolto = " e ".join(parti)
        return self.in_ascolto

    def ferma(self):
        udp, self._udp = self._udp, None
        if udp is not None:
            udp.close()
        if self._tcp is not None:
            self._tcp.shutdown()
            self._tcp.server_close()
            self._tcp = None
        self.in_ascolto = ""
