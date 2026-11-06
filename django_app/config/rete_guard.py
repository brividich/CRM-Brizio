"""Blocco delle connessioni di rete uscenti per il profilo ``copia_anonima``.

Ferma ogni connessione Python verso host non locali: SMTP, Graph, webhook, SNMP, syslog. Il
driver ODBC e' nativo e non passa da qui: il database resta raggiungibile. Come per
``readonly_guard``, l'installazione e' un gesto esplicito: importare il modulo non cambia nulla.
"""
from __future__ import annotations

import ipaddress
import socket

_LOCALI = {"localhost"}
_originali: dict = {}


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


def _controlla(indirizzo) -> None:
    # I socket AF_UNIX hanno come indirizzo una stringa: restano sulla macchina.
    if isinstance(indirizzo, (tuple, list)) and indirizzo and not host_locale(indirizzo[0]):
        raise ReteBloccata(f"Copia di prova: connessione verso {indirizzo[0]} bloccata.")


def install() -> None:
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
