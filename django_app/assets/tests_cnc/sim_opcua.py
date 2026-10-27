"""Server OPC UA simulato di una CNC DMG MORI (umati o BasicDataSet) per i test del collector.

Espone gli stessi NodeId stringa che il collector legge (``MODELS`` in ``collector_cnc/collector.py``),
il namespace DMG MORI con la matricola e una cartella allarmi con condition (ActiveState/Id, Message,
Severity, Time, ErrorCode). Ascolta solo su 127.0.0.1, su una porta libera scelta dal sistema.
I valori si cambiano con ``imposta`` tutti insieme, senza cedere il controllo al ciclo asincrono:
il collector non vede mai uno stato a metà.
"""
from __future__ import annotations

import datetime as dt
import socket
from typing import Any

from asyncua import Server, ua

UMATI_URI = "http://opcfoundation.org/UA/MachineTool/"
VT = ua.VariantType

# nome del nodo -> (tipo, valore iniziale)
NODI = {
    "umati": {
        "Channel_1-ChannelState": (VT.Int32, 2),
        "Channel_1-ChannelMode": (VT.Int32, 0),
        "EmergencyStopTriggered": (VT.Boolean, False),
        "Channel_1-CurrentNcProgram": (VT.String, ""),
        "Channel_1-ActiveTool-Name": (VT.String, "T1"),
        "Channel_1-FeedOverride": (VT.Double, 100.0),
        "Light_1-SignalOn": (VT.Boolean, False),
        "Light_2-SignalOn": (VT.Boolean, False),
        "Light_3-SignalOn": (VT.Boolean, True),
        "Light_4-SignalOn": (VT.Boolean, False),
        "Light_1-SignalColor": (VT.Int32, 1),
        "Light_2-SignalColor": (VT.Int32, 4),
        "Light_3-SignalColor": (VT.Int32, 2),
        "Light_4-SignalColor": (VT.Int32, 3),
        "ActiveProgram-CurrentRunTime": (VT.Int64, 0),
        "ActiveProgram-PartCounter": (VT.Int64, 0),
        "Statistics-PartsProducedInLifetime": (VT.Int64, 1000),
        "OperationDuration": (VT.Int64, 5000),
        "PowerOnDuration": (VT.Int64, 9000),
    },
    "bds": {
        "Channel_1-ExecutionState": (VT.Int32, 3),
        "Channel_1-ControllerMode": (VT.Int32, 1),
        "EmergencyStop": (VT.Boolean, False),
        "NumberOfActiveAlarms": (VT.UInt32, 0),
        "Channel_1-CurrentNcProgram": (VT.String, ""),
        "Channel_1-NumberOfActiveTool": (VT.Int32, 1),
        "Channel_1-FeedOverride": (VT.Double, 100.0),
        "LightStatus1": (VT.Int32, 0),
        "LightStatus2": (VT.Int32, 0),
        "LightStatus3": (VT.Int32, 1),
        "LightStatus4": (VT.Int32, 0),
        "LightColor1": (VT.Int32, 1),
        "LightColor2": (VT.Int32, 2),
        "LightColor3": (VT.Int32, 0),
        # LightColor4 assente apposta: il collector deve ignorare i nodi che mancano
        "CurrentRunTime": (VT.Int64, 0),
        "PartCounter": (VT.Int64, 0),
        "PartCounterOverall": (VT.Int64, 2000),
        "OperationTimeOverall": (VT.Int64, 3600 * 100),
        "PowerOnTimeOverall": (VT.Int64, 3600 * 200),
        "VendorServerInfo": (VT.String, "2.1.0"),
    },
}
CARTELLA_ALLARMI = {"umati": "Messages", "bds": "Alarms"}
ORA_MACCHINA = dt.datetime(2026, 1, 15, 8, 30, 0, tzinfo=dt.timezone.utc)


def porta_libera() -> int:
    """Una porta TCP libera su 127.0.0.1."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class CncSimulata:
    """Server OPC UA di una CNC finta: ``await avvia()``, ``await imposta(...)``, ``await ferma()``."""

    def __init__(self, modello: str, porta: int | None = None, matricola: str = "11111111111") -> None:
        self.modello = modello
        self.porta = porta or porta_libera()
        self.matricola = matricola
        self.valori: dict[str, Any] = {nome: v for nome, (_t, v) in NODI[modello].items()}
        self.condizioni: dict[str, dict[str, Any]] = {}   # codice -> stato della condition
        self.server: Server | None = None
        self._nodi: dict[str, ua.NodeId] = {}
        self._tipi: dict[str, ua.VariantType] = {}

    @property
    def url(self) -> str:
        return f"opc.tcp://127.0.0.1:{self.porta}"

    async def avvia(self) -> None:
        server = Server()
        await server.init()
        server.set_endpoint(self.url + "/")
        server.set_server_name("CNC simulata")
        if self.modello == "umati":
            await server.register_namespace(UMATI_URI)
        ns = await server.register_namespace(f"http://DMGMORI.com/Machines/{self.matricola}/")
        oggetti = server.nodes.objects
        self._nodi, self._tipi = {}, {}
        for nome, (tipo, _iniziale) in NODI[self.modello].items():
            nodo = await oggetti.add_variable(ua.NodeId(nome, ns), ua.QualifiedName(nome, ns),
                                              ua.Variant(self.valori[nome], tipo))
            self._nodi[nome], self._tipi[nome] = nodo.nodeid, tipo
        cartella = await oggetti.add_folder(ua.NodeId(CARTELLA_ALLARMI[self.modello], ns),
                                            ua.QualifiedName(CARTELLA_ALLARMI[self.modello], ns))
        for codice, c in self.condizioni.items():
            await self._crea_condizione(cartella, ns, codice, c)
        self._ns, self._cartella = ns, cartella
        await server.start()
        self.server = server

    async def _crea_condizione(self, cartella: Any, ns: int, codice: str, c: dict[str, Any]) -> None:
        base = f"{CARTELLA_ALLARMI[self.modello]}/{codice}"
        cond = await cartella.add_object(ua.NodeId(base, ns), ua.QualifiedName(f"Cond_{codice}", ns))
        attivo = await cond.add_variable(ua.NodeId(base + "/ActiveState", ns), ua.QualifiedName("ActiveState", 0),
                                         ua.Variant(ua.LocalizedText("Active" if c["attivo"] else "Inactive"),
                                                    VT.LocalizedText))
        await attivo.add_variable(ua.NodeId(base + "/ActiveState/Id", ns), ua.QualifiedName("Id", 0),
                                  ua.Variant(c["attivo"], VT.Boolean))
        await cond.add_variable(ua.NodeId(base + "/Message", ns), ua.QualifiedName("Message", 0),
                                ua.Variant(ua.LocalizedText(c["testo"]), VT.LocalizedText))
        await cond.add_variable(ua.NodeId(base + "/Severity", ns), ua.QualifiedName("Severity", 0),
                                ua.Variant(c["severita"], VT.UInt16))
        await cond.add_variable(ua.NodeId(base + "/Time", ns), ua.QualifiedName("Time", 0),
                                ua.Variant(ORA_MACCHINA, VT.DateTime))
        await cond.add_variable(ua.NodeId(base + "/ErrorCode", ns), ua.QualifiedName("ErrorCode", 0),
                                ua.Variant(codice, VT.String))
        self._nodi[f"cond:{codice}"] = ua.NodeId(base + "/ActiveState/Id", ns)

    async def aggiungi_condizione(self, codice: str, testo: str, severita: int, attivo: bool = False) -> None:
        """Condition nella cartella allarmi (anche a server avviato)."""
        self.condizioni[codice] = {"testo": testo, "severita": severita, "attivo": attivo}
        if self.server is not None:
            await self._crea_condizione(self._cartella, self._ns, codice, self.condizioni[codice])

    async def imposta(self, **valori: Any) -> None:
        """Cambia più nodi in un colpo; ``cond_<codice>=True/False`` accende o spegne una condition."""
        assert self.server is not None
        for nome, valore in valori.items():
            if nome.startswith("cond_"):
                codice = nome[5:]
                self.condizioni[codice]["attivo"] = valore
                await self.server.write_attribute_value(
                    self._nodi[f"cond:{codice}"], ua.DataValue(ua.Variant(valore, VT.Boolean)))
                continue
            self.valori[nome] = valore
            await self.server.write_attribute_value(
                self._nodi[nome], ua.DataValue(ua.Variant(valore, self._tipi[nome])))

    async def ferma(self) -> None:
        if self.server is not None:
            await self.server.stop()
            self.server = None
