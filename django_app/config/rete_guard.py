"""Blocco delle connessioni di rete uscenti per il profilo ``copia_anonima`` e per l'ambiente di test.

Ferma ogni connessione Python verso host non locali: SMTP, Graph, webhook, SNMP, syslog.
L'ambiente di test (``config/ambiente_test.py``) lascia aperti solo i server del login. Il
driver ODBC e' nativo e non passa da qui: il database resta raggiungibile. Come per
``readonly_guard``, l'installazione e' un gesto esplicito: importare il modulo non cambia nulla.
"""
from __future__ import annotations

import ipaddress
import socket

_LOCALI = {"localhost"}
_originali: dict = {}
_consentiti: set[str] = set()


class ReteBloccata(OSError):
    """Tentativo di connessione verso l'esterno da una copia di prova."""


def host_locale(host) -> bool:
    testo = host.decode("ascii", "ignore") if isinstance(host, (bytes, bytearray)) else str(host or "")
    testo = testo.split("%", 1)[0].strip().lower()
    if testo in _LOCALI:
        return True
    try:
        return ipaddress.ip_address(testo).is_loopback
    except ValueError:
        return False


def _chiave(host) -> str:
    testo = host.decode("ascii", "ignore") if isinstance(host, (bytes, bytearray)) else str(host or "")
    return testo.split("%", 1)[0].strip().lower()


def _controlla(indirizzo) -> None:
    # I socket AF_UNIX hanno come indirizzo una stringa: restano sulla macchina.
    if not isinstance(indirizzo, (tuple, list)) or not indirizzo:
        return
    if host_locale(indirizzo[0]) or _chiave(indirizzo[0]) in _consentiti:
        return
    raise ReteBloccata(f"Copia di prova: connessione verso {indirizzo[0]} bloccata.")


def consenti(host) -> None:
    """Aggiunge agli ammessi gli host indicati e gli indirizzi a cui si risolvono adesso.

    Le librerie risolvono il nome prima di connettersi: al socket arriva l'indirizzo IP,
    quindi servono entrambi. Un nome che non si risolve resta ammesso solo come nome.
    """
    for nome in host or ():
        nome = _chiave(nome)
        if not nome:
            continue
        _consentiti.add(nome)
        try:
            for info in socket.getaddrinfo(nome, None):
                _consentiti.add(_chiave(info[4][0]))
        except OSError:
            pass


def install(consentiti=()) -> None:
    """Blocca le connessioni uscenti; ``consentiti`` = host che restano raggiungibili."""
    consenti(consentiti)
    if _originali:
        return
    _originali.update(connect=socket.socket.connect, connect_ex=socket.socket.connect_ex, sendto=socket.socket.sendto)

    def connect(self, indirizzo):
        _controlla(indirizzo)
        return _originali["connect"](self, indirizzo)

    def connect_ex(self, indirizzo):
        _controlla(indirizzo)
        return _originali["connect_ex"](self, indirizzo)

    def sendto(self, dati, *resto):
        _controlla(resto[-1])
        return _originali["sendto"](self, dati, *resto)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto


def uninstall() -> None:
    for nome, funzione in _originali.items():
        setattr(socket.socket, nome, funzione)
    _originali.clear()
    _consentiti.clear()
