"""Driver OPC UA per le CNC DMG MORI (IoTconnector / box MDC, CELOS X), in sola lettura.

Gestisce i due modelli dati trovati in officina:
  - umati / OPC UA for Machine Tools (es. DM16, DM17)
  - DMG MORI BasicDataSet (es. DM6, DM9, DM10, DM11, DM12, DM13, DM15)

Legge valori e sfoglia l'albero: niente scritture, niente metodi OPC UA (nemmeno il refresh delle
condition: gli allarmi si leggono a polling), niente sottoscrizioni. Il client ``asyncua`` e ogni nodo che ne deriva
passano da ``ProxySolaLettura`` con le whitelist ``CLIENT_AMMESSI`` e ``NODO_AMMESSI``.
Lo stato (intervalli, allarmi aperti, database) resta in ``collector.Machine``: qui solo letture.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from asyncua import Client, ua
from asyncua.common.node import Node

from .base import ProxySolaLettura

NOME_DRIVER = "opcua"
CONNECT_TIMEOUT = 8      # s
LETTURA_TIMEOUT = 10     # s - ogni lettura di gruppo
DISCONNECT_TIMEOUT = 5   # s
SESSION_TIMEOUT_MS = 60000

UMATI_URI = "http://opcfoundation.org/UA/MachineTool/"
DMG_MACHINE_URI = "DMGMORI.com/Machines/"

# Whitelist: quello che il collector usa davvero, niente di più.
CLIENT_AMMESSI = frozenset({"connect", "disconnect", "get_namespace_array", "get_node",
                            "read_attributes", "read_values"})
NODO_AMMESSI = frozenset({"nodeid", "read_browse_name", "get_children", "read_value"})

# ----------------------------------------------------------------------------
# Mappe dei due modelli dati -> segnali comuni
# ----------------------------------------------------------------------------
MODELS: dict[str, dict[str, Any]] = {
    "umati": {
        "fast": {
            "exec": "Channel_1-ChannelState",
            "mode": "Channel_1-ChannelMode",
            "estop": "EmergencyStopTriggered",
            "program": "Channel_1-CurrentNcProgram",
            "tool": "Channel_1-ActiveTool-Name",
            "feed_ovr": "Channel_1-FeedOverride",
            "light1": "Light_1-SignalOn",
            "light2": "Light_2-SignalOn",
            "light3": "Light_3-SignalOn",
            "light4": "Light_4-SignalOn",
        },
        "static": {
            "color1": "Light_1-SignalColor",
            "color2": "Light_2-SignalColor",
            "color3": "Light_3-SignalColor",
            "color4": "Light_4-SignalColor",
        },
        "counters": {
            "run_time": "ActiveProgram-CurrentRunTime",
            "part_counter": "ActiveProgram-PartCounter",
            "parts_overall": "Statistics-PartsProducedInLifetime",
            "operation_time": "OperationDuration",   # probabilmente ore
            "power_on_time": "PowerOnDuration",      # probabilmente ore
        },
        "alarm_folder": "Messages",
        # OperationDuration: da verificare sulla macchina (letto come ore). Fattore per avere ore;
        # se il valore non torna col display, l'unita' si cambia dal portale (Macchine collegate > Modifica).
        "hours_factor": 1.0,
        # ChannelState: 0 Active, 1 Interrupted, 2 Reset
        "exec_map": {0: "RUNNING", 1: "INTERRUPTED", 2: "IDLE"},
        # ChannelMode: 0 Automatic, 1 MdaMdi, 2 JogManual, ...
        "mode_map": {0: "AUTO", 1: "MDI", 2: "MANUAL"},
        "color_map": {0: "off", 1: "red", 2: "green", 3: "blue", 4: "yellow",
                      5: "purple", 6: "cyan", 7: "white"},
    },
    "bds": {
        "fast": {
            "exec": "Channel_1-ExecutionState",
            "mode": "Channel_1-ControllerMode",
            "estop": "EmergencyStop",
            "n_alarms": "NumberOfActiveAlarms",
            "program": "Channel_1-CurrentNcProgram",
            "tool": "Channel_1-NumberOfActiveTool",
            "feed_ovr": "Channel_1-FeedOverride",
            "light1": "LightStatus1",
            "light2": "LightStatus2",
            "light3": "LightStatus3",
            "light4": "LightStatus4",
        },
        "static": {
            "color1": "LightColor1",
            "color2": "LightColor2",
            "color3": "LightColor3",
            "color4": "LightColor4",
        },
        "counters": {
            "run_time": "CurrentRunTime",
            "part_counter": "PartCounter",
            "parts_overall": "PartCounterOverall",
            "operation_time": "OperationTimeOverall",  # secondi
            "power_on_time": "PowerOnTimeOverall",     # secondi
        },
        "alarm_folder": "Alarms",
        # OperationTimeOverall in secondi: /3600 per avere ore
        "hours_factor": 1 / 3600,
        # ExecutionStateType: 0 Undefined, 1 Running, 2 Interrupted, 3 Idle
        "exec_map": {1: "RUNNING", 2: "INTERRUPTED", 3: "IDLE"},
        # ControllerModeType: 0 Undefined, 1 Automatic, 2 MdaMdi, 3 JogManual
        "mode_map": {1: "AUTO", 2: "MDI", 3: "MANUAL"},
        "color_map": {0: "green", 1: "red", 2: "yellow", 3: "blue",
                      4: "orange", 5: "white"},
    },
}
LUCI = ("light1", "light2", "light3", "light4")

log = logging.getLogger("collector")


def text(v: Any) -> str:
    """LocalizedText / altro -> str"""
    if v is None:
        return ""
    return getattr(v, "Text", None) or (str(v) if not hasattr(v, "Text") else "")


def _valore(dv: Any) -> Any:
    """Valore di un DataValue, None se assente o con stato non buono."""
    return dv.Value.Value if (dv.Value is not None and dv.StatusCode.is_good()) else None


def _avvolgi_nodi(esito: Any) -> Any:
    """I nodi restituiti dal client o da un nodo restano dietro la whitelist dei nodi."""
    if isinstance(esito, Node):
        return ProxySolaLettura(esito, NODO_AMMESSI, NOME_DRIVER, _avvolgi_nodi)
    if isinstance(esito, list) and esito and all(isinstance(x, Node) for x in esito):
        return [ProxySolaLettura(x, NODO_AMMESSI, NOME_DRIVER, _avvolgi_nodi) for x in esito]
    return esito


def client_sola_lettura(url: str, timeout: float = CONNECT_TIMEOUT, username: str | None = None,
                        password: str | None = None) -> Any:
    """Client ``asyncua`` già configurato e chiuso nel proxy: da qui in poi solo letture."""
    client = Client(url, timeout=timeout)
    client.session_timeout = SESSION_TIMEOUT_MS
    if username:
        client.set_user(username)
        client.set_password(password or "")
    return ProxySolaLettura(client, CLIENT_AMMESSI, NOME_DRIVER, _avvolgi_nodi)


@contextlib.asynccontextmanager
async def sessione(url: str, username: str | None, password: str | None, nome: str) -> AsyncIterator[Any]:
    """Sessione OPC UA aperta per tutto il blocco; la disconnessione è tentata sempre all'uscita."""
    client = client_sola_lettura(url, CONNECT_TIMEOUT, username, password)
    await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT + 2)
    try:
        yield client
    finally:
        try:
            await asyncio.wait_for(client.disconnect(), DISCONNECT_TIMEOUT)
        except Exception as e:  # noqa: BLE001 - la sessione si chiude comunque lato server
            log.debug("%s: disconnessione non pulita: %s", nome, e)


class DriverOpcUa:
    """Letture di una sessione OPC UA aperta: modello dati, nodi, segnali, contatori, allarmi."""

    def __init__(self, client: Any, nome: str, ns: int, data_model: str, found_serial: str) -> None:
        self.client = client
        self.nome = nome
        self.ns = ns
        self.data_model = data_model
        self.spec: dict[str, Any] = MODELS[data_model]
        self.found_serial = found_serial
        self.alarm_nodes: dict[str, dict[str, Any]] = {}   # nodeid condition -> nodi figli (per sessione)

    @classmethod
    async def rileva(cls, client: Any, nome: str) -> DriverOpcUa:
        """Riconosce il modello dati dal namespace DMG MORI; RuntimeError se non è una DMG."""
        nsarr = await client.get_namespace_array()
        ns = next((i for i, u in enumerate(nsarr) if DMG_MACHINE_URI in u), None)
        if ns is None:
            raise RuntimeError("namespace DMG MORI non trovato")
        data_model = "umati" if UMATI_URI in nsarr else "bds"
        return cls(client, nome, ns, data_model, nsarr[ns].rstrip("/").split("/")[-1])

    def node(self, s: str) -> Any:
        return self.client.get_node(ua.NodeId(s, self.ns))

    async def resolve(self, group: dict[str, str]) -> dict[str, Any]:
        """Verifica dei nodi: scarta quelli che su questa macchina non esistono."""
        names = list(group)
        nodes = [self.node(group[n]) for n in names]
        dvs = await self.client.read_attributes(nodes)
        ok = {}
        for n, nd, dv in zip(names, nodes, dvs, strict=True):
            if dv.StatusCode.value == ua.StatusCodes.BadNodeIdUnknown:
                log.info("%s: nodo %s assente, ignorato", self.nome, group[n])
            else:
                ok[n] = nd
        return ok

    async def server_version(self) -> str:
        """Versione del server (solo BasicDataSet, solo informativa)."""
        if self.data_model != "bds":
            return ""
        try:
            return str(await self.node("VendorServerInfo").read_value())
        except Exception as e:  # noqa: BLE001 - la versione del server è solo informativa
            log.debug("%s: versione del server non letta: %s", self.nome, e)
            return ""

    async def colors(self, static: dict[str, Any]) -> dict[str, str]:
        """Colori del semaforo (configurazione statica): light1..4 -> nome colore."""
        if not static:
            return {}
        out = {}
        dvs = await self.client.read_attributes(list(static.values()))
        for k, dv in zip(static, dvs, strict=True):
            c = _valore(dv)
            out["light" + k[-1]] = self.spec["color_map"].get(c, str(c))
        return out

    async def read_fast(self, fast: dict[str, Any]) -> list[tuple[str, Any]]:
        """Segnali veloci in una sola chiamata: ``[(segnale, valore)]`` nell'ordine della mappa."""
        dvs = await asyncio.wait_for(self.client.read_attributes(list(fast.values())), LETTURA_TIMEOUT)
        out = []
        for name, dv in zip(fast, dvs, strict=True):
            val = _valore(dv)
            if name in LUCI and self.data_model == "bds":
                val = {0: False, 1: True, 2: "blink"}.get(val, val)
            out.append((name, val))
        return out

    async def read_counters(self, counters: dict[str, Any]) -> dict[str, Any]:
        dvs = await asyncio.wait_for(self.client.read_attributes(list(counters.values())), LETTURA_TIMEOUT)
        return {k: _valore(dv) for k, dv in zip(counters, dvs, strict=True)}

    async def describe_condition(self, cond: Any) -> dict[str, Any]:
        """Una volta per condition: trova i nodi figli che ci servono."""
        info: dict[str, Any] = {"node": cond, "active": None, "message": None, "severity": None,
                                "time": None, "code": None}
        bn = (await cond.read_browse_name()).Name
        info["name"] = bn
        for ch in await cond.get_children():
            n = (await ch.read_browse_name()).Name
            if n == "ActiveState":
                for sub in await ch.get_children():
                    if (await sub.read_browse_name()).Name == "Id":
                        info["active"] = sub
            elif n == "Message":
                info["message"] = ch
            elif n == "Severity":
                info["severity"] = ch
            elif n == "Time":
                info["time"] = ch
            elif n in ("ErrorCode", "NativeAlarmId"):
                info["code"] = ch
        return info

    async def conditions(self, folder: Any) -> list[tuple[str, dict[str, Any], bool]] | None:
        """Condition della cartella allarmi con il loro stato attivo; None se non c'è niente da valutare."""
        try:
            children = await folder.get_children()
        except Exception as e:  # noqa: BLE001 - cartella allarmi non leggibile: si riprova al giro dopo
            log.debug("%s: allarmi non letti: %s", self.nome, e)
            return None
        for ch in children:
            key = ch.nodeid.to_string()
            if key not in self.alarm_nodes:
                try:
                    self.alarm_nodes[key] = await self.describe_condition(ch)
                except Exception as e:  # noqa: BLE001 - condition non descrivibile: ignorata
                    log.debug("%s: condition %s ignorata: %s", self.nome, key, e)
                    self.alarm_nodes[key] = {"active": None}
        conds = [(k, i) for k, i in self.alarm_nodes.items() if i.get("active") is not None]
        if not conds:
            return None
        dvs = await asyncio.wait_for(self.client.read_attributes([i["active"] for _, i in conds]), LETTURA_TIMEOUT)
        return [(key, info, bool(_valore(dv))) for (key, info), dv in zip(conds, dvs, strict=True)]

    async def condition_details(self, info: dict[str, Any]) -> dict[str, Any]:
        """Messaggio, severità, ora e codice di una condition appena comparsa."""
        campi = [k for k in ("message", "severity", "time", "code") if info.get(k)]
        if not campi:
            return {}
        return dict(zip(campi, await self.client.read_values([info[k] for k in campi]), strict=True))
