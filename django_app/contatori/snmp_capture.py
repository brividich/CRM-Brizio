"""Cattura read-only di un walk SNMP completo in formato ``.snmprec`` (snmpsim).

Serve solo a verificare gli OID dei preset su apparati reali: il polling di
produzione non deve mai percorrere l'intero albero. Uniche PDU inviate:
GETNEXT (v1) e GETBULK (v2c/v3). Il segreto non entra mai nei file prodotti.

Formato snmprec: ``oid|tag|valore`` una riga per OID, ordinato. Tag BER:
universali come numero (2 Integer, 4 OctetString, 5 Null, 6 OID), applicativi
come 64+tag (64 IpAddress, 65 Counter32, 66 Gauge32, 67 TimeTicks, 68 Opaque,
70 Counter64). Il suffisso ``x`` indica un valore codificato in esadecimale.
"""
import asyncio
import functools
import ipaddress
import re
from dataclasses import dataclass, field
from time import monotonic

# Sottoalberi mai salvati, nemmeno nel walk grezzo: credenziali e configurazione
# di accesso SNMP, argomenti dei processi (possono contenere password),
# account utente di Windows (LanManager).
DROP_ALWAYS = (
    "1.3.6.1.6.3.12",          # SNMP-TARGET-MIB (destinatari e parametri)
    "1.3.6.1.6.3.15",          # SNMP-USER-BASED-SM-MIB (utenti v3)
    "1.3.6.1.6.3.16",          # SNMP-VIEW-BASED-ACM-MIB
    "1.3.6.1.6.3.18",          # SNMP-COMMUNITY-MIB
    "1.3.6.1.2.1.25.4.2.1.5",  # hrSWRunParameters
    "1.3.6.1.4.1.77.1.2.25",   # LanMgr svUserTable
)

# Ulteriori sottoalberi esclusi dalle fixture da versionare: traffico,
# processi e comandi non servono ai preset e rivelano l'infrastruttura.
DROP_SANITIZE = (
    "1.3.6.1.2.1.4.21",        # ipRouteTable
    "1.3.6.1.2.1.4.24",        # ipForward / inetCidrRoute
    "1.3.6.1.2.1.6.13",        # tcpConnTable
    "1.3.6.1.2.1.6.19",        # tcpConnectionTable
    "1.3.6.1.2.1.6.20",        # tcpListenerTable
    "1.3.6.1.2.1.7.5",         # udpTable
    "1.3.6.1.2.1.7.7",         # udpEndpointTable
    "1.3.6.1.2.1.25.4",        # hrSWRun
    "1.3.6.1.2.1.25.5",        # hrSWRunPerf
    "1.3.6.1.4.1.77",          # LanManager
    "1.3.6.1.4.1.2021.2",      # UCD prTable (comandi)
    "1.3.6.1.4.1.2021.8",      # UCD extTable (comandi)
    "1.3.6.1.4.1.8072.1.3",    # NET-SNMP-EXTEND (comandi)
)

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"

# Colonne testuali che riportano nomi interni (host, porte, persone):
# nelle fixture diventano pseudonimi stabili.
PSEUDONYM_COLUMNS = {
    "1.3.6.1.2.1.31.1.1.1.18": "alias",        # ifAlias
    "1.0.8802.1.1.2.1.3.3": "lldp-local",      # lldpLocSysName
    "1.0.8802.1.1.2.1.4.1.1.9": "neighbor",    # lldpRemSysName
    "1.3.6.1.2.1.43.5.1.1.16": "printer",      # prtGeneralPrinterName
}

# Colonne che contengono MAC anche quando i byte risultano stampabili.
MAC_COLUMNS = (
    "1.3.6.1.2.1.2.2.1.6",     # ifPhysAddress
    "1.3.6.1.2.1.4.22.1.2",    # ipNetToMediaPhysAddress
    "1.3.6.1.2.1.4.35.1.4",    # ipNetToPhysicalPhysAddress
    "1.3.6.1.2.1.17.1.1",      # dot1dBaseBridgeAddress
    "1.3.6.1.2.1.17.4.3.1.1",  # dot1dTpFdbAddress
)
# Tabelle indicizzate per MAC (ultimi 6 componenti dell'OID).
MAC_INDEXED = ("1.3.6.1.2.1.17.4.3.1", "1.3.6.1.2.1.17.7.1.2.2.1")
# Tabelle IP-MIB / LLDP con un IPv4 negli ultimi 4 componenti dell'indice.
IP_INDEXED = (
    "1.3.6.1.2.1.4.20.1", "1.3.6.1.2.1.4.22.1", "1.3.6.1.2.1.4.34.1",
    "1.3.6.1.2.1.4.35.1", "1.0.8802.1.1.2.1.4.2.1",
)

_PRINTABLE = re.compile(r"^[\x20-\x7e]*$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")

# Nomi leggibili per il file .txt: prefisso -> nome MIB. Il match più lungo
# vince e il resto dell'OID resta come indice. Non serve un compilatore MIB.
MIB_NAMES = {
    "1.3.6.1.2.1.1.1": "sysDescr", "1.3.6.1.2.1.1.2": "sysObjectID",
    "1.3.6.1.2.1.1.3": "sysUpTime", "1.3.6.1.2.1.1.4": "sysContact",
    "1.3.6.1.2.1.1.5": "sysName", "1.3.6.1.2.1.1.6": "sysLocation",
    "1.3.6.1.2.1.1.7": "sysServices", "1.3.6.1.2.1.1.9": "sysORTable",
    "1.3.6.1.2.1.2.1": "ifNumber",
    "1.3.6.1.2.1.2.2.1.1": "ifIndex", "1.3.6.1.2.1.2.2.1.2": "ifDescr",
    "1.3.6.1.2.1.2.2.1.3": "ifType", "1.3.6.1.2.1.2.2.1.4": "ifMtu",
    "1.3.6.1.2.1.2.2.1.5": "ifSpeed", "1.3.6.1.2.1.2.2.1.6": "ifPhysAddress",
    "1.3.6.1.2.1.2.2.1.7": "ifAdminStatus", "1.3.6.1.2.1.2.2.1.8": "ifOperStatus",
    "1.3.6.1.2.1.2.2.1.9": "ifLastChange", "1.3.6.1.2.1.2.2.1.10": "ifInOctets",
    "1.3.6.1.2.1.2.2.1.14": "ifInErrors", "1.3.6.1.2.1.2.2.1.16": "ifOutOctets",
    "1.3.6.1.2.1.2.2.1.20": "ifOutErrors", "1.3.6.1.2.1.2.2": "ifTable",
    "1.3.6.1.2.1.4.20.1": "ipAddrEntry", "1.3.6.1.2.1.4.22.1": "ipNetToMediaEntry",
    "1.3.6.1.2.1.4.34.1": "ipAddressEntry", "1.3.6.1.2.1.4.35.1": "ipNetToPhysicalEntry",
    "1.3.6.1.2.1.4": "ip", "1.3.6.1.2.1.5": "icmp", "1.3.6.1.2.1.6": "tcp",
    "1.3.6.1.2.1.7": "udp", "1.3.6.1.2.1.11": "snmp",
    "1.3.6.1.2.1.17.1.1": "dot1dBaseBridgeAddress",
    "1.3.6.1.2.1.17.1.4.1.2": "dot1dBasePortIfIndex",
    "1.3.6.1.2.1.17.4.3.1": "dot1dTpFdbEntry", "1.3.6.1.2.1.17.7.1.2.2.1": "dot1qTpFdbEntry",
    "1.3.6.1.2.1.17.7.1.4.3.1.1": "dot1qVlanStaticName",
    "1.3.6.1.2.1.17.7.1.4.5.1.1": "dot1qPvid", "1.3.6.1.2.1.17": "bridge",
    "1.3.6.1.2.1.25.1": "hrSystem", "1.3.6.1.2.1.25.2.2": "hrMemorySize",
    "1.3.6.1.2.1.25.2.3.1.2": "hrStorageType", "1.3.6.1.2.1.25.2.3.1.3": "hrStorageDescr",
    "1.3.6.1.2.1.25.2.3.1.4": "hrStorageAllocationUnits",
    "1.3.6.1.2.1.25.2.3.1.5": "hrStorageSize", "1.3.6.1.2.1.25.2.3.1.6": "hrStorageUsed",
    "1.3.6.1.2.1.25.3.2.1.2": "hrDeviceType", "1.3.6.1.2.1.25.3.2.1.3": "hrDeviceDescr",
    "1.3.6.1.2.1.25.3.2.1.5": "hrDeviceStatus", "1.3.6.1.2.1.25.3.3.1.2": "hrProcessorLoad",
    "1.3.6.1.2.1.25.3.5.1.1": "hrPrinterStatus",
    "1.3.6.1.2.1.25.3.5.1.2": "hrPrinterDetectedErrorState",
    "1.3.6.1.2.1.25.6.3.1.2": "hrSWInstalledName", "1.3.6.1.2.1.25": "hostResources",
    "1.3.6.1.2.1.31.1.1.1.1": "ifName", "1.3.6.1.2.1.31.1.1.1.6": "ifHCInOctets",
    "1.3.6.1.2.1.31.1.1.1.10": "ifHCOutOctets", "1.3.6.1.2.1.31.1.1.1.15": "ifHighSpeed",
    "1.3.6.1.2.1.31.1.1.1.18": "ifAlias", "1.3.6.1.2.1.31": "ifMIB",
    "1.3.6.1.2.1.33.1.1": "upsIdent", "1.3.6.1.2.1.33.1.2": "upsBattery",
    "1.3.6.1.2.1.33.1.3": "upsInput", "1.3.6.1.2.1.33.1.4": "upsOutput",
    "1.3.6.1.2.1.33": "upsMIB",
    "1.3.6.1.2.1.43.5.1.1.16": "prtGeneralPrinterName",
    "1.3.6.1.2.1.43.5.1.1.17": "prtGeneralSerialNumber",
    "1.3.6.1.2.1.43.6.1.1.3": "prtCoverStatus", "1.3.6.1.2.1.43.8.2.1": "prtInputEntry",
    "1.3.6.1.2.1.43.10.2.1.3": "prtMarkerCounterUnit",
    "1.3.6.1.2.1.43.10.2.1.4": "prtMarkerLifeCount",
    "1.3.6.1.2.1.43.11.1.1.5": "prtMarkerSuppliesType",
    "1.3.6.1.2.1.43.11.1.1.6": "prtMarkerSuppliesDescription",
    "1.3.6.1.2.1.43.11.1.1.7": "prtMarkerSuppliesSupplyUnit",
    "1.3.6.1.2.1.43.11.1.1.8": "prtMarkerSuppliesMaxCapacity",
    "1.3.6.1.2.1.43.11.1.1.9": "prtMarkerSuppliesLevel",
    "1.3.6.1.2.1.43.12.1.1.4": "prtMarkerColorantValue",
    "1.3.6.1.2.1.43.16.5.1.2": "prtConsoleDisplayBufferText",
    "1.3.6.1.2.1.43.18.1.1": "prtAlertEntry", "1.3.6.1.2.1.43": "printmib",
    "1.3.6.1.2.1.47.1.1.1.1.2": "entPhysicalDescr", "1.3.6.1.2.1.47.1.1.1.1.4": "entPhysicalContainedIn",
    "1.3.6.1.2.1.47.1.1.1.1.5": "entPhysicalClass", "1.3.6.1.2.1.47.1.1.1.1.7": "entPhysicalName",
    "1.3.6.1.2.1.47.1.1.1.1.8": "entPhysicalHardwareRev",
    "1.3.6.1.2.1.47.1.1.1.1.9": "entPhysicalFirmwareRev",
    "1.3.6.1.2.1.47.1.1.1.1.10": "entPhysicalSoftwareRev",
    "1.3.6.1.2.1.47.1.1.1.1.11": "entPhysicalSerialNum",
    "1.3.6.1.2.1.47.1.1.1.1.12": "entPhysicalMfgName",
    "1.3.6.1.2.1.47.1.1.1.1.13": "entPhysicalModelName", "1.3.6.1.2.1.47": "entityMIB",
    "1.3.6.1.2.1.99": "entitySensorMIB", "1.3.6.1.2.1.105": "powerEthernetMIB",
    "1.0.8802.1.1.2.1.3": "lldpLocalSystemData", "1.0.8802.1.1.2.1.4.1.1": "lldpRemEntry",
    "1.0.8802.1.1.2.1.4.2.1": "lldpRemManAddrEntry", "1.0.8802.1.1.2": "lldpMIB",
    "1.2.840.10006.300.43": "ieee8023adLag",
    "1.3.6.1.6.3": "snmpModules",
    "1.3.6.1.4.1.9": "enterprises.cisco", "1.3.6.1.4.1.9.6.1.101": "enterprises.ciscoSB",
    "1.3.6.1.4.1.11": "enterprises.hp", "1.3.6.1.4.1.11.2.14.11.5": "enterprises.hpSwitch",
    "1.3.6.1.4.1.232": "enterprises.compaq(iLO)", "1.3.6.1.4.1.311": "enterprises.microsoft",
    "1.3.6.1.4.1.318": "enterprises.apc", "1.3.6.1.4.1.534": "enterprises.eaton",
    "1.3.6.1.4.1.674": "enterprises.dell", "1.3.6.1.4.1.1602": "enterprises.canon",
    "1.3.6.1.4.1.2021": "enterprises.ucdavis", "1.3.6.1.4.1.3097": "enterprises.watchguard",
    "1.3.6.1.4.1.6574": "enterprises.synology", "1.3.6.1.4.1.6876": "enterprises.vmware",
    "1.3.6.1.4.1.8072": "enterprises.netSnmp", "1.3.6.1.4.1.14823": "enterprises.aruba",
    "1.3.6.1.4.1.47196": "enterprises.arubaCX",
}
_MIB_PREFIXES = sorted(MIB_NAMES, key=lambda p: len(p.split(".")), reverse=True)


class CaptureError(RuntimeError):
    pass


@dataclass
class Record:
    oid: str
    tag: str      # "2", "4", "4x", "64", ...
    value: str    # gia' codificato per snmprec

    @property
    def key(self):
        return tuple(int(p) for p in self.oid.split("."))


@dataclass
class CaptureResult:
    records: list = field(default_factory=list)
    requests: int = 0
    dropped: int = 0
    redacted: int = 0
    unknown_types: int = 0
    complete: bool = True
    stop_reason: str = ""
    duration: float = 0.0


def in_subtree(oid, roots):
    return any(oid == r or oid.startswith(r + ".") for r in roots)


def mib_name(oid):
    for prefix in _MIB_PREFIXES:
        if oid == prefix or oid.startswith(prefix + "."):
            rest = oid[len(prefix) + 1:]
            return f"{MIB_NAMES[prefix]}.{rest}" if rest else MIB_NAMES[prefix]
    return ""


def encode_value(value):
    """Converte un valore x690/puresnmp in ``(tag, valore)`` snmprec.

    Restituisce ``None`` per tipi sconosciuti o sentinelle (noSuch*/endOfMib).
    """
    from x690.util import TypeClass

    cls = getattr(value, "TYPECLASS", None)
    tag = getattr(value, "TAG", None)
    if tag is None or cls not in (TypeClass.UNIVERSAL, TypeClass.APPLICATION):
        return None
    number = tag if cls == TypeClass.UNIVERSAL else 0x40 | tag
    raw = value.value
    if number in (4, 0x44):  # OctetString, Opaque
        data = raw if isinstance(raw, bytes) else str(raw).encode()
        text = data.decode("ascii", "replace")
        if number == 4 and _PRINTABLE.fullmatch(text) and "|" not in text:
            return "4", text
        return f"{number}x", data.hex()
    if number in (2, 0x41, 0x42, 0x43, 0x46):
        return str(number), str(int(raw))
    if number == 6:
        return "6", str(raw).lstrip(".")
    if number == 0x40:
        return "64", str(raw)
    if number == 5:
        return "5", ""
    return None


def to_bytes(record):
    if record.tag.endswith("x"):
        return bytes.fromhex(record.value)
    if record.tag == "4":
        return record.value.encode("ascii", "replace")
    return None


def render_snmprec(records):
    return "".join(f"{r.oid}|{r.tag}|{r.value}\n" for r in sorted(records, key=lambda r: r.key))


def parse_snmprec(text):
    records = []
    for numero, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) != 3 or not re.fullmatch(r"\d+(?:\.\d+)+", parts[0]):
            raise CaptureError(f"Riga snmprec non valida ({numero})")
        records.append(Record(*parts))
    return records


_TYPE_NAMES = {"2": "INTEGER", "4": "STRING", "4x": "HEX", "5": "NULL", "6": "OID",
               "64": "IpAddress", "65": "Counter32", "66": "Gauge32", "67": "TimeTicks",
               "68x": "Opaque", "70": "Counter64"}


def render_text(records, header_lines=()):
    out = [f"# {line}" for line in header_lines]
    for r in sorted(records, key=lambda r: r.key):
        value = r.value
        if r.tag.endswith("x"):
            data = bytes.fromhex(r.value)
            value = ":".join(f"{b:02x}" for b in data) if len(data) <= 32 else r.value
        name = mib_name(r.oid)
        label = f"{name} ({r.oid})" if name else r.oid
        out.append(f"{label} = {_TYPE_NAMES.get(r.tag, r.tag)}: {value}")
    return "\n".join(out) + "\n"


def redact_secret(records, secrets):
    """Sostituisce ogni valore che contiene un segreto usato per la cattura."""
    secrets = [s.encode() for s in secrets if s]
    count = 0
    for r in records:
        data = to_bytes(r)
        if data is not None and any(s in data for s in secrets):
            r.tag, r.value = "4", "***REDACTED***"
            count += 1
    return count


class Sanitizer:
    """Pseudonimizza IP, MAC, email e nomi in modo stabile e coerente.

    Lo stesso IP/MAC reale diventa sempre lo stesso valore sintetico, sia nei
    valori sia negli indici delle tabelle, cosi' le relazioni restano valide.
    """

    def __init__(self):
        self.ips = {}
        self.macs = {}
        self.names = {}

    def ip(self, real):
        if real not in self.ips:
            n = len(self.ips) + 1
            # Blocchi di documentazione RFC 5737: mai instradabili.
            net = ("192.0.2", "198.51.100", "203.0.113")[(n - 1) // 254 % 3]
            self.ips[real] = f"{net}.{(n - 1) % 254 + 1}"
        return self.ips[real]

    def mac(self, real):
        if real not in self.macs:
            n = len(self.macs) + 1
            # Prefisso localmente amministrato: non appartiene a nessun vendor.
            self.macs[real] = bytes([0x02, 0x00, 0x00, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])
        return self.macs[real]

    def name(self, kind, real):
        key = (kind, real)
        if key not in self.names:
            self.names[key] = f"{kind}-{sum(1 for k in self.names if k[0] == kind) + 1}"
        return self.names[key]

    def _text(self, text):
        text = _EMAIL.sub("utente@example.invalid", text)

        def _sub_ip(match):
            parts = [int(p) for p in match.groups()]
            if any(p > 255 for p in parts):
                return match.group(0)
            real = ".".join(map(str, parts))
            # Lascia indirizzi non di host (maschere, 0.0.0.0, loopback).
            if parts[0] in (0, 127, 255) or real.startswith("255."):
                return real
            return self.ip(real)
        return _IPV4.sub(_sub_ip, text)

    def _oid(self, oid):
        parts = oid.split(".")
        if in_subtree(oid, MAC_INDEXED) and len(parts) >= 6:
            real = bytes(int(p) for p in parts[-6:] if int(p) < 256)
            if len(real) == 6:
                parts[-6:] = [str(b) for b in self.mac(real)]
        if in_subtree(oid, IP_INDEXED) and len(parts) >= 4:
            tail = parts[-4:]
            if all(int(p) < 256 for p in tail) and int(tail[0]) not in (0, 127, 255):
                parts[-4:] = self.ip(".".join(tail)).split(".")
        return ".".join(parts)

    def apply(self, records, drop=DROP_SANITIZE):
        out = []
        hostnames = []
        for r in records:
            if r.oid == SYS_NAME and r.tag == "4" and r.value:
                hostnames.append(r.value)
        for r in records:
            if in_subtree(r.oid, drop):
                continue
            # IPv6 negli indici (tipo 2, lunghezza 16): non pseudonimizzati, esclusi.
            table = next((t for t in IP_INDEXED if in_subtree(r.oid, (t,))), None)
            if table and ".2.16." in r.oid[len(table):]:
                continue
            rec = Record(self._oid(r.oid), r.tag, r.value)
            data = to_bytes(rec)
            if rec.oid == SYS_CONTACT:
                rec.tag, rec.value = "4", "contatto-sintetico" if r.value else ""
            elif rec.oid == SYS_LOCATION:
                rec.tag, rec.value = "4", "sede-sintetica" if r.value else ""
            elif rec.oid == SYS_NAME:
                rec.tag, rec.value = "4", "device-1" if r.value else ""
            elif rec.tag == "64":
                rec.value = self.ip(rec.value)
            elif data is not None and len(data) == 6 and (
                    rec.tag.endswith("x") or in_subtree(rec.oid, MAC_COLUMNS)):
                rec.tag, rec.value = "4x", self.mac(data).hex()
            elif rec.tag == "4":
                column = next((c for c in PSEUDONYM_COLUMNS if in_subtree(rec.oid, (c,))), None)
                if column and rec.value:
                    rec.value = self.name(PSEUDONYM_COLUMNS[column], rec.value)
                else:
                    text = rec.value
                    for host in hostnames:
                        text = text.replace(host, "device-1")
                    rec.value = self._text(text)
            out.append(rec)
        return out


def build_credentials(*, version, community="", v3_user="", v3_auth="", v3_auth_key="",
                      v3_priv="", v3_priv_key=""):
    from puresnmp import V1, V2C
    from puresnmp.credentials import V3, Auth, Priv

    if version == "v1":
        return V1(community)
    if version == "v2c":
        return V2C(community)
    if version != "v3":
        raise CaptureError("Versione SNMP non valida.")
    if not v3_user:
        raise CaptureError("SNMPv3 richiede un utente.")
    auth = Auth(v3_auth_key.encode(), v3_auth) if v3_auth else None
    if v3_priv and not auth:
        raise CaptureError("SNMPv3 authPriv richiede anche l'autenticazione.")
    if v3_priv:
        import importlib.util
        if importlib.util.find_spec(f"puresnmp_plugins.priv.{v3_priv}") is None:
            raise CaptureError(
                f"Cifratura SNMPv3 '{v3_priv}' non disponibile: installare il pacchetto "
                "puresnmp-crypto (dipendenza non ancora approvata)."
            )
    priv = Priv(v3_priv_key.encode(), v3_priv) if v3_priv else None
    return V3(v3_user, auth=auth, priv=priv)


def _start_oid(root):
    # In BER un OID con un solo arco non e' codificabile: "1" parte da "1.0".
    return root if "." in root else f"{root}.0"


async def walk_async(client, *, root="1", version="v2c", max_repetitions=25,
                     max_rows=200_000, max_duration=900.0, drop=DROP_ALWAYS):
    """Percorre il sottoalbero ``root`` con GETBULK (v2c/v3) o GETNEXT (v1)."""
    from puresnmp.exc import NoSuchOID, Timeout, TooBig
    from x690.types import ObjectIdentifier

    result = CaptureResult()
    started = monotonic()
    current = _start_oid(root)
    last_key = ()
    bulk = max(1, int(max_repetitions))
    while True:
        if monotonic() - started > max_duration:
            result.complete, result.stop_reason = False, "durata massima raggiunta"
            break
        try:
            result.requests += 1
            if version == "v1":
                items = [(vb.oid, vb.value) for vb in
                         await client.multigetnext([ObjectIdentifier(current)])]
            else:
                bulk_result = await client.bulkget([], [ObjectIdentifier(current)],
                                                   max_list_size=bulk)
                items = list(bulk_result.listing.items())
        except TooBig:
            if bulk == 1:
                result.complete, result.stop_reason = False, "risposta troppo grande"
                break
            bulk = max(1, bulk // 2)
            continue
        except NoSuchOID:
            # SNMPv1: noSuchName dopo l'ultimo OID = fine della vista MIB.
            break
        except Timeout:
            result.complete, result.stop_reason = False, "timeout dell'apparato"
            break
        if not items:
            break
        leaving = False
        for oid, value in items:
            oid_text = str(oid).lstrip(".")
            if not in_subtree(oid_text, (root,)):
                leaving = True
                break
            key = tuple(int(p) for p in oid_text.split("."))
            if key <= last_key:
                result.complete, result.stop_reason = False, "OID non crescente (agente difettoso)"
                leaving = True
                break
            last_key = key
            if in_subtree(oid_text, drop):
                result.dropped += 1
                continue
            encoded = encode_value(value)
            if encoded is None:
                result.unknown_types += 1
                continue
            result.records.append(Record(oid_text, *encoded))
            if len(result.records) >= max_rows:
                result.complete, result.stop_reason = False, f"limite di {max_rows} righe"
                leaving = True
                break
        if leaving:
            break
        current = ".".join(map(str, last_key))
    result.duration = monotonic() - started
    return result


def capture(host, credentials, *, port=161, timeout=3, retries=2, **walk_options):
    """Esegue il walk e restituisce un :class:`CaptureResult` (solo lettura)."""
    from puresnmp import Client
    from puresnmp.transport import send_udp

    try:
        ipaddress.ip_address(str(host))
    except ValueError as exc:
        raise CaptureError("Host non valido: indicare un indirizzo IP.") from exc
    sender = functools.partial(send_udp, timeout=timeout, retries=max(1, retries + 1))
    client = Client(str(host), credentials, port=port, sender=sender)
    try:
        return asyncio.run(walk_async(client, **walk_options))
    except CaptureError:
        raise
    except Exception as exc:  # il messaggio della libreria non contiene il segreto
        raise CaptureError(f"Cattura fallita: {type(exc).__name__}") from exc
