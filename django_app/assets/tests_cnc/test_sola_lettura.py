"""Garanzia di sola lettura: whitelist dei proxy e controllo statico del package ``drivers``."""
from __future__ import annotations

import asyncio
import io
import re
import tokenize
import unittest
from pathlib import Path

from asyncua import Client
from asyncua.common.node import Node

from assets.collector_cnc import vietati
from assets.collector_cnc.drivers import opcua
from assets.collector_cnc.drivers.base import ProxySolaLettura, spia

DRIVERS = Path(opcua.__file__).resolve().parent
PAROLA = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def nomi_nel_sorgente(path: Path) -> set[str]:
    """Identificatori e parole dentro stringhe e commenti di un file Python."""
    nomi: set[str] = set()
    with path.open("rb") as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.NAME:
                nomi.add(tok.string)
            elif tok.type in (tokenize.STRING, tokenize.COMMENT):
                nomi.update(PAROLA.findall(tok.string))
    return nomi


class ControlloStaticoTests(unittest.TestCase):
    """Nel package drivers non compare nessun nome di funzione di scrittura (``vietati.py``)."""

    def test_nessun_nome_vietato_nei_driver(self) -> None:
        file = sorted(DRIVERS.glob("*.py"))
        self.assertTrue(file)
        trovati = {f"{p.name}: {n}" for p in file for n in nomi_nel_sorgente(p) if vietati.vietato(n)}
        self.assertEqual(trovati, set())

    def test_il_controllo_riconosce_i_nomi_vietati(self) -> None:
        sorgente = "client.write_value(1)\n# cnc_wrparam\nx = 'pmc_wrpmcrng'\nlsv2.send_file()\n"
        nomi = set()
        for tok in tokenize.tokenize(io.BytesIO(sorgente.encode()).readline):
            if tok.type == tokenize.NAME:
                nomi.add(tok.string)
            elif tok.type in (tokenize.STRING, tokenize.COMMENT):
                nomi.update(PAROLA.findall(tok.string))
        self.assertTrue({"write_value", "cnc_wrparam", "pmc_wrpmcrng", "send_file"} <= {n for n in nomi if vietati.vietato(n)})

    def test_whitelist_senza_nomi_vietati(self) -> None:
        for nome in opcua.CLIENT_AMMESSI | opcua.NODO_AMMESSI:
            self.assertFalse(vietati.vietato(nome), nome)


class _Finto:
    valore = 7

    def leggi(self) -> int:
        return 1

    def scrivi(self) -> int:
        return 2


class ProxyTests(unittest.TestCase):
    def test_solo_nomi_ammessi(self) -> None:
        p = ProxySolaLettura(_Finto(), frozenset({"leggi", "valore"}), "finto")
        self.assertEqual(p.leggi(), 1)
        self.assertEqual(p.valore, 7)
        with self.assertRaises(PermissionError):
            p.scrivi()
        with self.assertRaises(PermissionError):
            p.__dict__  # noqa: B018 - anche gli attributi interni passano dalla whitelist
        with self.assertRaises(PermissionError):
            p.valore = 3
        with self.assertRaises(PermissionError):
            del p.valore

    def test_spia_registra_gli_accessi(self) -> None:
        p = ProxySolaLettura(_Finto(), frozenset({"leggi"}), "finto")
        with spia() as registro:
            p.leggi()
            with self.assertRaises(PermissionError):
                p.scrivi()
        p.leggi()
        self.assertEqual(registro, [("finto", "leggi")])


class OpcUaWhitelistTests(unittest.TestCase):
    """Client e nodi OPC UA: le scritture, i metodi e le sottoscrizioni sollevano PermissionError."""

    def test_client(self) -> None:
        client = opcua.client_sola_lettura("opc.tcp://127.0.0.1:4840", username="lettore", password="pw-sintetica")
        for nome in ("write_values", "create_subscription", "delete_nodes", "set_user", "uaclient",
                     "load_data_type_definitions", "connect_socket"):
            with self.subTest(nome=nome), self.assertRaises(PermissionError):
                getattr(client, nome)
        with self.assertRaises(PermissionError):
            client.session_timeout = 1

    def test_nodi_derivati(self) -> None:
        client = opcua.client_sola_lettura("opc.tcp://127.0.0.1:4840")
        nodo = client.get_node("ns=2;s=Channel_1-ChannelState")
        self.assertIsInstance(nodo, ProxySolaLettura)
        self.assertEqual(nodo.nodeid.to_string(), "ns=2;s=Channel_1-ChannelState")
        for nome in ("write_value", "write_attribute", "set_value", "call_method", "delete", "add_variable",
                     "set_writable", "write_params", "add_reference"):
            with self.subTest(nome=nome), self.assertRaises(PermissionError):
                getattr(nodo, nome)

    def test_figli_restano_dietro_la_whitelist(self) -> None:
        """I nodi restituiti da get_children (anche in una coroutine) sono avvolti a loro volta."""
        vero = Client("opc.tcp://127.0.0.1:4840")
        figlio = Node(vero.uaclient, "ns=2;s=figlio")

        class _NodoFinto:
            async def get_children(self) -> list[Node]:
                return [figlio]

        p = ProxySolaLettura(_NodoFinto(), opcua.NODO_AMMESSI, "opcua", opcua._avvolgi_nodi)
        figli = asyncio.run(p.get_children())
        self.assertIsInstance(figli[0], ProxySolaLettura)
        with self.assertRaises(PermissionError):
            figli[0].write_value  # noqa: B018
