"""Indirizzi IP dal DHCP e dal DNS di Windows Server (sola lettura).

Ogni ora (schedule ``rete_windows_sync``) il server del portale lancia in locale
PowerShell con i moduli RSAT ``DhcpServer`` e ``DnsServer`` e legge:

- dal DHCP (``RETE_DHCP_SERVERS``): gli ambiti IPv4 con l'occupazione
  (``Get-DhcpServerv4Scope`` / ``Get-DhcpServerv4ScopeStatistics``) e i lease,
  prenotazioni comprese (``Get-DhcpServerv4Lease``): IP, MAC, nome, stato, scadenza;
- dal DNS (``RETE_DNS_SERVER``, zone ``RETE_DNS_ZONES``): i record A
  (``Get-DnsServerResourceRecord -RRType A``) con la data di aggiornamento
  (vuota = record statico).

Ne nasce una riga ``IndirizzoRete`` per IP. Per ogni indirizzo senza asset
l'abbinatore unico (MAC, IP, nome) propone l'asset: la conferma si fa dalla
riconciliazione dispositivi IT. Gli indirizzi senza nessuna proposta sono i
dispositivi **non censiti** del registro.

Server DHCP, server DNS e zone si scrivono nella pagina Indirizzi IP (riquadro
«Server DHCP e DNS», solo amministratori del modulo Asset) e stanno in ``SiteConfig``;
le vecchie variabili ``RETE_*`` del ``.env`` valgono solo se nel portale non c'è niente.

Lo script PowerShell è fisso: server e zone gli arrivano come variabili
d'ambiente, mai dentro il testo del comando. L'utente che fa girare il qcluster
deve stare nel gruppo «DHCP Users» del server DHCP (sola lettura); per il DNS di
dominio di solito basta un utente di dominio.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .mac import normalizza_mac

logger = logging.getLogger(__name__)

TIMEOUT_SECONDI = 180
SOGLIA_AMBITO_PIENO = 90  # % di occupazione oltre cui l'ambito va guardato
GIORNI_DNS_VECCHIO = 30   # record dinamico non aggiornato da più giorni e senza lease: rimasto lì
MAX_SEGNALAZIONI_GIRO = 10  # eventi SOC «dispositivo nuovo in rete» al massimo per lettura
_NOME_SERVER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")

SCRIPT_DHCP = r"""
$ErrorActionPreference = 'Stop'
Import-Module DhcpServer -ErrorAction Stop
$server = $env:PN_RETE_SERVER
$scopes = @()
$leases = @()
foreach ($s in @(Get-DhcpServerv4Scope -ComputerName $server)) {
  $id = $s.ScopeId.IPAddressToString
  $st = Get-DhcpServerv4ScopeStatistics -ComputerName $server -ScopeId $s.ScopeId
  $scopes += [pscustomobject]@{
    scope_id = $id; name = [string]$s.Name; mask = $s.SubnetMask.IPAddressToString
    start = $s.StartRange.IPAddressToString; end = $s.EndRange.IPAddressToString; state = [string]$s.State
    lease_hours = [math]::Round($s.LeaseDuration.TotalHours, 1)
    in_use = [int]$st.InUse; free = [int]$st.Free; pct = [double]$st.PercentageInUse
  }
  foreach ($l in @(Get-DhcpServerv4Lease -ComputerName $server -ScopeId $s.ScopeId)) {
    $leases += [pscustomobject]@{
      ip = $l.IPAddress.IPAddressToString; mac = [string]$l.ClientId; host = [string]$l.HostName
      state = [string]$l.AddressState; scope_id = $id
      expiry = $(if ($l.LeaseExpiryTime) { $l.LeaseExpiryTime.ToUniversalTime().ToString('o') } else { $null })
    }
  }
}
[pscustomobject]@{ scopes = $scopes; leases = $leases } | ConvertTo-Json -Depth 4 -Compress
"""

SCRIPT_DNS = r"""
$ErrorActionPreference = 'Stop'
Import-Module DnsServer -ErrorAction Stop
$server = $env:PN_RETE_SERVER
$records = @()
foreach ($zone in ($env:PN_RETE_ZONE -split ',')) {
  $zone = $zone.Trim()
  if (-not $zone) { continue }
  foreach ($r in @(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -RRType A)) {
    $records += [pscustomobject]@{
      name = [string]$r.HostName; zone = $zone; ip = $r.RecordData.IPv4Address.IPAddressToString
      stamp = $(if ($r.Timestamp) { $r.Timestamp.ToUniversalTime().ToString('o') } else { $null })
    }
  }
}
[pscustomobject]@{ records = $records } | ConvertTo-Json -Depth 4 -Compress
"""


class ReteError(RuntimeError):
    pass


def _elenco(valore) -> list[str]:
    return [v.strip() for v in str(valore or "").split(",") if v.strip()]


CONFIG_KEY = "assets.rete_windows.config"


def _dal_portale() -> dict | None:
    from core.models import SiteConfig

    try:
        valore = SiteConfig.objects.filter(chiave=CONFIG_KEY).values_list("valore", flat=True).first()
        dati = json.loads(valore) if valore else None
    except Exception:  # noqa: BLE001 - configurazione illeggibile = come assente
        logger.warning("rete_windows: configurazione nel portale non leggibile", exc_info=True)
        return None
    if not isinstance(dati, dict):
        return None
    return {"dhcp": [str(s) for s in dati.get("dhcp") or []], "dns": str(dati.get("dns") or ""),
            "zone": [str(z) for z in dati.get("zone") or []]}


def config() -> dict:
    """Server e zone in uso: quelli scritti nel portale, altrimenti quelli del .env (compatibilità)."""
    dati = _dal_portale()
    if dati is not None:
        return {**dati, "fonte": "portale"}
    cfg = {
        "dhcp": _elenco(getattr(settings, "RETE_DHCP_SERVERS", "")),
        "dns": str(getattr(settings, "RETE_DNS_SERVER", "") or "").strip(),
        "zone": _elenco(getattr(settings, "RETE_DNS_ZONES", "")),
    }
    return {**cfg, "fonte": "env" if (cfg["dhcp"] or cfg["dns"]) else ""}


def salva_config(dhcp: str, dns: str, zone: str, utente=None) -> list[str]:
    """Salva server e zone scritti nella pagina; ritorna gli errori (niente salvato se ce ne sono)."""
    from core.models import SiteConfig

    dati = {"dhcp": _elenco(dhcp)[:10], "dns": str(dns or "").strip(), "zone": _elenco(zone)[:10]}
    errori = []
    for nome in [*dati["dhcp"], *([dati["dns"]] if dati["dns"] else []), *dati["zone"]]:
        if not _NOME_SERVER.match(nome):
            errori.append(f"«{nome}» non è un nome valido (solo lettere, cifre, punti e trattini).")
    if dati["dns"] and not dati["zone"]:
        errori.append("Con il server DNS servono anche le zone da leggere (es. dominio.local).")
    if errori:
        return errori
    SiteConfig.objects.update_or_create(chiave=CONFIG_KEY, defaults={
        "valore": json.dumps(dati), "descrizione": "Server DHCP/DNS letti per la pagina Indirizzi IP (Asset)"})
    logger.info("rete_windows: configurazione salvata da %s", getattr(utente, "username", "?"))
    return []


def configurato() -> bool:
    cfg = config()
    return bool(cfg["dhcp"] or (cfg["dns"] and cfg["zone"]))


def _valida_nome(nome: str, cosa: str) -> str:
    if not _NOME_SERVER.match(nome or ""):
        raise ReteError(f"{cosa} non valido: «{nome}» (solo lettere, cifre, punti e trattini).")
    return nome


def esegui_powershell(script: str, ambiente: dict) -> dict:
    """Esegue uno degli script fissi e ritorna il JSON prodotto."""
    env = {**os.environ, **ambiente}
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=TIMEOUT_SECONDI, env=env, check=False,
        )
    except FileNotFoundError as exc:
        raise ReteError("PowerShell non trovato: la lettura DHCP/DNS funziona solo sul server Windows del portale.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ReteError(f"PowerShell non ha risposto entro {TIMEOUT_SECONDI} secondi.") from exc
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ReteError(_spiega_errore(err or out))
    try:
        return json.loads(out or "{}")
    except json.JSONDecodeError as exc:
        raise ReteError("Risposta di PowerShell non leggibile (non è JSON).") from exc


def _spiega_errore(testo: str) -> str:
    low = testo.lower()
    if "import-module" in low or "not loaded because no valid module file" in low or "non è stato caricato" in low:
        return ("Mancano i moduli PowerShell DhcpServer/DnsServer sul server del portale: installa gli strumenti RSAT "
                "(Install-WindowsFeature RSAT-DHCP, RSAT-DNS-Server).")
    if ("access" in low and "denied" in low) or "accesso negato" in low:
        return ("Accesso negato dal server DHCP/DNS: l'utente che fa girare il portale e il qcluster deve stare nel gruppo "
                "«DHCP Users» del server DHCP.")
    if "rpc server" in low or "server rpc" in low or "failed to get" in low:
        return "Server DHCP/DNS non raggiungibile: controlla il nome del server e il firewall (RPC)."
    return "Errore di PowerShell: " + " ".join(testo.split())[:300]


def leggi_dhcp(server: str) -> dict:
    data = esegui_powershell(SCRIPT_DHCP, {"PN_RETE_SERVER": _valida_nome(server, "Server DHCP")})
    return {"scopes": _lista(data.get("scopes")), "leases": _lista(data.get("leases"))}


def leggi_dns(server: str, zone: list[str]) -> list[dict]:
    for z in zone:
        _valida_nome(z, "Zona DNS")
    data = esegui_powershell(SCRIPT_DNS, {"PN_RETE_SERVER": _valida_nome(server, "Server DNS"), "PN_RETE_ZONE": ",".join(zone)})
    return _lista(data.get("records"))


def _lista(valore) -> list[dict]:
    # ConvertTo-Json rende un elenco di un solo elemento come oggetto singolo.
    if isinstance(valore, dict):
        valore = [valore]
    return [v for v in valore or [] if isinstance(v, dict)]


def _data(valore):
    d = parse_datetime(str(valore or "")) if valore else None
    if d is None or d.year < 2000:
        return None
    return d if timezone.is_aware(d) else timezone.make_aware(d, dt_timezone.utc)


def _ip(valore) -> str:
    import ipaddress

    try:
        return str(ipaddress.IPv4Address(str(valore or "").strip()))
    except ValueError:
        return ""


def _fqdn(record: dict) -> str:
    nome, zona = str(record.get("name") or "").strip(), str(record.get("zone") or "").strip()
    if not nome or nome == "@":
        return zona
    return nome if nome.endswith("." + zona) or not zona else f"{nome}.{zona}"


def _tipo_da_stato(stato: str) -> str:
    from assets.models import IndirizzoRete

    return IndirizzoRete.TIPO_PRENOTAZIONE if "reservation" in stato.lower() else IndirizzoRete.TIPO_LEASE


# --- Salvataggio ----------------------------------------------------------------------------


def salva_dhcp(server: str, dati: dict, ora=None) -> dict:
    from assets.models import AmbitoDhcp, IndirizzoRete

    ora = ora or timezone.now()
    ambiti = {}
    for s in dati["scopes"]:
        scope_id = _ip(s.get("scope_id"))
        if not scope_id:
            continue
        ambito, _ = AmbitoDhcp.objects.update_or_create(server=server, scope_id=scope_id, defaults={
            "nome": str(s.get("name") or "")[:200], "maschera": str(s.get("mask") or "")[:45],
            "inizio": str(s.get("start") or "")[:45], "fine": str(s.get("end") or "")[:45],
            "stato": str(s.get("state") or "")[:30], "durata_lease_ore": s.get("lease_hours"),
            "in_uso": max(0, int(s.get("in_use") or 0)), "liberi": max(0, int(s.get("free") or 0)),
            "percentuale_uso": round(float(s.get("pct") or 0), 1), "presente": True, "letto_il": ora,
        })
        ambiti[scope_id] = ambito
    AmbitoDhcp.objects.filter(server=server).exclude(scope_id__in=list(ambiti)).update(presente=False)

    visti = set()
    for lease in dati["leases"]:
        ip = _ip(lease.get("ip"))
        if not ip or ip in visti:
            continue
        visti.add(ip)
        stato = str(lease.get("state") or "")[:40]
        riga = IndirizzoRete.objects.filter(ip=ip).first() or IndirizzoRete(ip=ip, prima_vista=ora)
        riga.mac = normalizza_mac(lease.get("mac")) or riga.mac
        riga.nome_dhcp = str(lease.get("host") or "").strip()[:255]
        riga.stato_dhcp = stato
        riga.tipo = _tipo_da_stato(stato)
        riga.scadenza_lease = _data(lease.get("expiry"))
        riga.server_dhcp = server
        riga.ambito = ambiti.get(_ip(lease.get("scope_id")))
        riga.nel_dhcp = True
        riga.ultima_vista = ora
        riga.save()
    spariti = IndirizzoRete.objects.filter(server_dhcp=server, nel_dhcp=True).exclude(ip__in=visti).update(nel_dhcp=False)
    nuovi = ricorda_mac(dati["leases"], ora)
    return {"ambiti": len(ambiti), "indirizzi": len(visti), "spariti": spariti, "mac_nuovi": nuovi}


def ricorda_mac(leases: list[dict], ora=None) -> list[str]:
    """Aggiorna la memoria dei MAC visti nel DHCP; ritorna i MAC mai visti prima."""
    from assets.models import MacRete

    ora = ora or timezone.now()
    per_mac = {}
    for lease in leases:
        mac = normalizza_mac(lease.get("mac"))
        if mac:
            per_mac[mac] = (_ip(lease.get("ip")), str(lease.get("host") or "").strip()[:255])
    noti = {}
    elenco = list(per_mac)
    for i in range(0, len(elenco), 500):  # SQL Server: massimo 2100 parametri per query
        noti.update({m.mac: m for m in MacRete.objects.filter(mac__in=elenco[i:i + 500])})
    nuovi = []
    for mac, (ip, nome) in per_mac.items():
        voce = noti.get(mac)
        if voce is None:
            MacRete.objects.create(mac=mac, prima_vista=ora, ultima_vista=ora, ultimo_ip=ip, ultimo_nome=nome)
            nuovi.append(mac)
        else:
            voce.ultima_vista, voce.ultimo_ip, voce.ultimo_nome = ora, ip or voce.ultimo_ip, nome or voce.ultimo_nome
            voce.save(update_fields=["ultima_vista", "ultimo_ip", "ultimo_nome"])
    return nuovi


def mac_casuale(mac: str) -> bool:
    """MAC «privato» (bit amministrato localmente): telefoni e tablet ne usano uno diverso per ogni rete."""
    try:
        return bool(int(mac[1], 16) & 0x2)
    except (IndexError, ValueError):
        return False


def segnala_nuovi(macs: list[str], ora=None) -> int:
    """Evento SOC «dispositivo sconosciuto nuovo in rete» per i MAC nuovi senza asset né proposta.

    Esclusi i MAC privati dei telefoni (cambiano da soli, non sono un dispositivo nuovo da censire).
    Al massimo ``MAX_SEGNALAZIONI_GIRO`` per giro: oltre è una rete ospiti, non un intruso da inseguire.
    """
    from assets.models import IndirizzoRete, MacRete

    ora = ora or timezone.now()
    mandati = 0
    for mac in macs:
        if mandati >= MAX_SEGNALAZIONI_GIRO:
            logger.info("rete_windows: altri MAC nuovi non segnalati (limite %s per giro)", MAX_SEGNALAZIONI_GIRO)
            break
        if mac_casuale(mac):
            continue
        riga = IndirizzoRete.objects.filter(mac=mac, nel_dhcp=True).select_related("ambito").first()
        if riga is None or riga.asset_id or riga.asset_proposto_id:
            continue
        porta = porta_switch(mac)
        from core.eventi_sicurezza import segnala

        evento = segnala(
            "rete_dispositivo_nuovo", chiave=(mac,), una_volta=True,
            titolo=f"Dispositivo sconosciuto in rete: {riga.nome or mac} ({riga.ip})",
            dettaglio={"ip": riga.ip, "mac": mac, "nome": riga.nome,
                       "ambito": str(riga.ambito) if riga.ambito else "",
                       "switch": porta.dispositivo.nome if porta else "", "porta": porta.porta if porta else ""},
        )
        if evento is not None:
            MacRete.objects.filter(mac=mac).update(segnalato_il=ora)
            mandati += 1
    return mandati


def porta_switch(mac: str):
    """La porta dello switch dove si vede il MAC (prima le porte d'accesso), o None."""
    try:
        from contatori.models import MacPortaSwitch
    except ImportError:  # pragma: no cover - modulo contatori non installato
        return None
    righe = list(MacPortaSwitch.objects.filter(mac=mac).select_related("dispositivo")[:10])
    righe.sort(key=lambda r: (not r.porta_accesso, r.mac_sulla_porta))
    return righe[0] if righe else None


def salva_dns(record: list[dict], ora=None) -> dict:
    from assets.models import IndirizzoRete

    ora = ora or timezone.now()
    per_ip: dict[str, dict] = {}
    for r in record:
        ip = _ip(r.get("ip"))
        nome = _fqdn(r)
        if not ip or not nome or nome.split(".", 1)[0].lower() in {"domaindnszones", "forestdnszones"}:
            continue
        voce = per_ip.setdefault(ip, {"nomi": [], "statico": False, "stamp": None})
        if nome.lower() not in {n.lower() for n in voce["nomi"]}:
            voce["nomi"].append(nome[:255])
        stamp = _data(r.get("stamp"))
        if stamp is None:
            voce["statico"] = True
        elif voce["stamp"] is None or stamp > voce["stamp"]:
            voce["stamp"] = stamp
    for ip, voce in per_ip.items():
        riga = IndirizzoRete.objects.filter(ip=ip).first() or IndirizzoRete(ip=ip, prima_vista=ora, tipo=IndirizzoRete.TIPO_DNS)
        riga.nomi_dns = sorted(voce["nomi"], key=str.lower)[:20]
        riga.dns_statico = voce["statico"]
        riga.dns_aggiornato_il = voce["stamp"]
        riga.nel_dns = True
        if not riga.nel_dhcp:
            riga.tipo = IndirizzoRete.TIPO_DNS
        riga.ultima_vista = ora
        riga.save()
    spariti = IndirizzoRete.objects.filter(nel_dns=True).exclude(ip__in=list(per_ip)).update(nel_dns=False)
    return {"indirizzi": len(per_ip), "spariti": spariti}


def proponi(riga):
    """``(asset | None, motivo)`` per un indirizzo: MAC, IP e nome DHCP, poi gli altri nomi del DNS.

    Un IP fisso ha solo i nomi del DNS (anche più d'uno): si provano tutti, il primo che
    trova un asset (o un'ambiguità) vince. Usata dal giro, dalla pagina e dalla riconciliazione.
    """
    from .identity_match import REASON_NONE, match_hub_asset

    nomi = [n for n in [riga.nome_dhcp, *riga.nomi_dns] if n]
    asset, motivo = match_hub_asset(mac=riga.mac, ip=riga.ip, hostname=nomi[0] if nomi else "")
    for nome in nomi[1:]:
        if asset is not None or motivo != REASON_NONE:
            break
        asset, motivo = match_hub_asset(hostname=nome)
    return asset, motivo


def aggiorna_proposte() -> int:
    """Proposta di asset per gli indirizzi presenti e non ancora collegati."""
    from assets.models import IndirizzoRete

    cambiate = 0
    qs = IndirizzoRete.objects.filter(asset__isnull=True).exclude(nel_dhcp=False, nel_dns=False)
    for riga in qs.iterator():
        asset, motivo = proponi(riga)
        nuovo = (asset.pk if asset else None, motivo)
        if (riga.asset_proposto_id, riga.motivo_proposta) != nuovo:
            riga.asset_proposto_id, riga.motivo_proposta = nuovo
            riga.save(update_fields=["asset_proposto", "motivo_proposta", "aggiornato_il"])
            cambiate += 1
    return cambiate


def sincronizza(ora=None) -> dict:
    """Giro completo: DHCP di ogni server, poi DNS, poi le proposte. Un server che fallisce non ferma gli altri."""
    from assets.models import MacRete

    ora = ora or timezone.now()
    cfg = config()
    esito = {"at": ora.isoformat(), "dhcp": {}, "errori": []}
    # Prima lettura in assoluto: tutti i MAC sono «nuovi», nessuno va segnalato al SOC.
    prima_volta = not MacRete.objects.exists()
    nuovi = []
    for server in cfg["dhcp"]:
        try:
            esito["dhcp"][server] = salva_dhcp(server, leggi_dhcp(server), ora)
            nuovi += esito["dhcp"][server].pop("mac_nuovi", [])
        except ReteError as exc:
            esito["errori"].append(f"DHCP {server}: {exc}")
    if cfg["dns"] and cfg["zone"]:
        try:
            esito["dns"] = salva_dns(leggi_dns(cfg["dns"], cfg["zone"]), ora)
        except ReteError as exc:
            esito["errori"].append(f"DNS {cfg['dns']}: {exc}")
    esito["proposte_cambiate"] = aggiorna_proposte()
    esito["mac_nuovi"] = len(nuovi)
    esito["segnalati_soc"] = 0 if prima_volta else segnala_nuovi(nuovi, ora)
    esito["ok"] = not esito["errori"]
    _salva_esito(esito)
    return esito


ESITO_KEY = "assets.rete_windows.ultimo_giro"


def _salva_esito(esito: dict) -> None:
    from core.models import SiteConfig

    try:
        SiteConfig.objects.update_or_create(chiave=ESITO_KEY, defaults={
            "valore": json.dumps(esito, default=str)[:8000],
            "descrizione": "Esito dell'ultima lettura DHCP/DNS (stato tecnico, si aggiorna da solo)",
        })
    except Exception:  # noqa: BLE001 - l'esito è un'informazione di comodo, il giro è già fatto
        logger.warning("rete_windows: esito non salvato", exc_info=True)


def ultimo_giro() -> dict:
    from core.models import SiteConfig

    try:
        valore = SiteConfig.objects.filter(chiave=ESITO_KEY).values_list("valore", flat=True).first()
        return json.loads(valore) if valore else {}
    except Exception:  # noqa: BLE001 - pagina di stato: mai un errore per questo
        return {}


# --- Lettura per la pagina ----------------------------------------------------------------------

FILTRI = [
    ("tutti", "Tutti"),
    ("non_censiti", "Non censiti"),
    ("da_collegare", "Da collegare"),
    ("collegati", "Collegati a un asset"),
    ("senza_protezione", "Senza antivirus"),
    ("nome_diverso", "Nome DHCP diverso dal DNS"),
    ("dns_vecchi", "Record DNS vecchi"),
    ("prenotazioni", "Prenotazioni"),
    ("spariti", "Non più visti"),
]

# Riquadri numerici in testa alla pagina: (filtro, etichetta, spiegazione, tono). Un clic = quel filtro.
KPI = [
    ("tutti", "Indirizzi attivi", "visti nell'ultima lettura del DHCP o del DNS", ""),
    ("non_censiti", "Non censiti", "nessun asset del registro ha questo MAC, IP o nome", "danger"),
    ("da_collegare", "Da collegare", "c'è un asset proposto: va solo confermato", "warn"),
    ("senza_protezione", "Senza antivirus", "PC in rete senza WatchGuard né Defender", "danger"),
    ("dns_vecchi", "DNS da pulire", f"record dinamici fermi da oltre {GIORNI_DNS_VECCHIO} giorni", "warn"),
]

STATI_AMBITO = {"active": "Attivo", "inactive": "Disattivato"}
FONTI_ANTIVIRUS = ("watchguard", "defender")


def dns_vecchio(riga, ora=None) -> bool:
    """Record DNS dinamico non aggiornato da più di ``GIORNI_DNS_VECCHIO`` giorni e senza lease attivo."""
    if not riga.nel_dns or riga.dns_statico or riga.nel_dhcp or riga.dns_aggiornato_il is None:
        return False
    return riga.dns_aggiornato_il < (ora or timezone.now()) - timedelta(days=GIORNI_DNS_VECCHIO)


def non_censito(riga, ora=None) -> bool:
    """Indirizzo attivo che nessun asset del registro spiega: lease DHCP o IP fisso nel DNS (non un record rimasto)."""
    if riga.asset_id or riga.asset_proposto_id:
        return False
    return riga.nel_dhcp or (riga.nel_dns and not dns_vecchio(riga, ora))


def _filtro(riga, codice, ora):
    if codice == "spariti":
        return not riga.presente
    if not riga.presente:
        return False
    return {
        "tutti": True,
        "non_censiti": non_censito(riga, ora),
        "da_collegare": riga.asset_id is None and riga.asset_proposto_id is not None,
        "collegati": riga.asset_id is not None,
        "senza_protezione": bool(getattr(riga, "senza_protezione", "")),
        "nome_diverso": riga.nome_diverso,
        "dns_vecchi": dns_vecchio(riga, ora),
        "prenotazioni": riga.tipo == riga.TIPO_PRENOTAZIONE,
    }.get(codice, True)


def _chiave_ip(riga):
    return tuple(int(p) for p in riga.ip.split(".")) if riga.ip.count(".") == 3 else (999,)


def _a_blocchi(valori, n=500):
    # SQL Server: massimo 2100 parametri per query.
    valori = list(valori)
    for i in range(0, len(valori), n):
        yield valori[i:i + n]


def _porte_switch(macs) -> dict:
    """{mac: MacPortaSwitch} con la porta più vicina al dispositivo (prima le porte d'accesso)."""
    try:
        from contatori.models import MacPortaSwitch
    except ImportError:  # pragma: no cover - modulo contatori non installato
        return {}
    porte = {}
    for blocco in _a_blocchi(macs):
        for p in MacPortaSwitch.objects.filter(mac__in=blocco).select_related("dispositivo"):
            prima = porte.get(p.mac)
            if prima is None or (not p.porta_accesso, p.mac_sulla_porta) < (not prima.porta_accesso, prima.mac_sulla_porta):
                porte[p.mac] = p
    return porte


def _asset_protetti(pc_ids: set[int], wg_per_asset: dict) -> set[int]:
    """Tra gli asset PC, quelli con un antivirus: WatchGuard con agente o inventario WatchGuard/Defender.

    Senza nessun dato antivirus nel portale (SOC vuoto) non si giudica: tutti «protetti».
    """
    try:
        from security.models import SoftwareInstallation
    except ImportError:  # pragma: no cover - SOC non installato
        return set(pc_ids)
    inventario = SoftwareInstallation.objects.filter(still_detected=True)
    if not any(d.gestito for d in wg_per_asset.values()) and not inventario.filter(source_kind__in=FONTI_ANTIVIRUS).exists():
        return set(pc_ids)
    protetti = {a for a, d in wg_per_asset.items() if d.gestito and a in pc_ids}
    for blocco in _a_blocchi(pc_ids - protetti):
        protetti.update(inventario.filter(hub_asset_id__in=blocco, source_kind__in=FONTI_ANTIVIRUS).order_by()
                        .values_list("hub_asset_id", flat=True).distinct())
    # Un programma visto da più fonti sta in una riga sola: l'antivirus può essere solo in ``fonti``.
    for blocco in _a_blocchi(pc_ids - protetti):
        for asset_id, fonti in inventario.filter(hub_asset_id__in=blocco).values_list("hub_asset_id", "fonti")[:20000]:
            if set(FONTI_ANTIVIRUS) & set(fonti or []):
                protetti.add(asset_id)
    return protetti


def correla(righe) -> None:
    """Aggiunge a ogni riga quello che le altre fonti sanno dello stesso dispositivo, con poche query in blocco.

    - ``switch``: porta dello switch dove si vede il MAC (tabella MAC letta via SNMP);
    - ``wg``: dispositivo WatchGuard con lo stesso MAC, o collegato allo stesso asset, o con lo stesso IP;
    - ``intune``: PC di Intune con lo stesso MAC o collegato allo stesso asset;
    - ``fonti``: chi vede l'indirizzo (pastiglie «Visto da»);
    - ``senza_protezione``: perché il dispositivo è in rete senza antivirus («» = niente da dire).
    """
    from assets.models import Asset, DispositivoIntune

    porte = _porte_switch({r.mac for r in righe if r.mac})
    wg_mac, wg_ip, wg_asset = {}, {}, {}
    try:
        from security.models import WatchGuardDispositivo

        for d in WatchGuardDispositivo.objects.filter(presente=True):
            for m in d.mac.lower().split():
                wg_mac.setdefault(m, d)
            if d.ip:
                wg_ip.setdefault(d.ip, d)
            if d.hub_asset_id and (d.gestito or d.hub_asset_id not in wg_asset):
                wg_asset[d.hub_asset_id] = d
    except ImportError:  # pragma: no cover - SOC non installato
        pass
    intune_mac, intune_asset = {}, {}
    for d in DispositivoIntune.objects.filter(presente=True):
        for m in (normalizza_mac(d.mac_wifi), normalizza_mac(d.mac_ethernet)):
            if m:
                intune_mac.setdefault(m, d)
        if d.asset_id:
            intune_asset.setdefault(d.asset_id, d)

    tipi_pc = {Asset.TYPE_PC, Asset.TYPE_NOTEBOOK, Asset.TYPE_SERVER, Asset.TYPE_VM}
    pc_ids = {r.asset_id for r in righe if r.asset_id and r.presente and r.asset.asset_type in tipi_pc}
    protetti = _asset_protetti(pc_ids, wg_asset) if pc_ids else set()

    for r in righe:
        r.switch = porte.get(r.mac) if r.mac else None
        r.mac_privato = bool(r.mac) and mac_casuale(r.mac)
        wg = wg_mac.get(r.mac) if r.mac else None
        if wg is None and r.asset_id:
            wg = wg_asset.get(r.asset_id)
        if wg is None and r.ip in wg_ip:
            per_ip = wg_ip[r.ip]
            # Un IP dinamico passa da un PC all'altro: vale solo se il MAC non smentisce.
            wg = per_ip if not (r.mac and per_ip.mac.strip()) else None
        r.wg = wg
        r.intune = (intune_mac.get(r.mac) if r.mac else None) or (intune_asset.get(r.asset_id) if r.asset_id else None)
        r.senza_protezione = ""
        if r.presente and wg is not None and not wg.gestito:
            r.senza_protezione = "WatchGuard lo vede in rete senza agente"
        elif r.asset_id in pc_ids and r.asset_id not in protetti:
            r.senza_protezione = "PC del registro senza WatchGuard né Defender"
        r.fonti = [f for f in (
            {"nome": "DHCP", "stato": "ok", "titolo": "Lease o prenotazione nel DHCP"} if r.nel_dhcp else None,
            {"nome": "DNS", "stato": "ok", "titolo": "Record A nel DNS"} if r.nel_dns else None,
            {"nome": "Switch", "stato": "ok", "titolo": f"{r.switch.dispositivo.nome} · porta {r.switch.porta}"} if r.switch else None,
            ({"nome": "WatchGuard", "stato": "ok" if wg.gestito else "ko",
              "titolo": "Agente WatchGuard installato" if wg.gestito else "In rete senza agente WatchGuard"} if wg else None),
            {"nome": "Intune", "stato": "ok", "titolo": f"Gestito da Intune: {r.intune.nome}"} if r.intune else None,
        ) if f]


def rete_dei_dispositivi() -> tuple[dict, dict]:
    """Indirizzi attivi per asset e per nome host corto, con la porta dello switch: per l'elenco Dispositivi del SOC.

    ``({asset_id: [riga]}, {nome_corto: [riga]})``; le righe hanno ``switch`` (o None). Prima i lease DHCP.
    """
    from assets.models import IndirizzoRete

    righe = list(IndirizzoRete.objects.filter(_q_presente()).order_by("-nel_dhcp", "ip"))
    porte = _porte_switch({r.mac for r in righe if r.mac})
    per_asset, per_nome = {}, {}
    for r in righe:
        r.switch = porte.get(r.mac) if r.mac else None
        if r.asset_id:
            per_asset.setdefault(r.asset_id, []).append(r)
        for nome in {IndirizzoRete._corto(n) for n in [r.nome_dhcp, *r.nomi_dns] if n}:
            per_nome.setdefault(nome, []).append(r)
    return per_asset, per_nome


def _q_presente():
    from django.db.models import Q

    return Q(nel_dhcp=True) | Q(nel_dns=True)


def pagina(codice="tutti", q="", ambito_id=None, ora=None) -> dict:
    from assets.models import AmbitoDhcp, IndirizzoRete

    ora = ora or timezone.now()
    righe = list(IndirizzoRete.objects.select_related("asset", "asset_proposto", "ambito"))
    righe.sort(key=_chiave_ip)
    correla(righe)
    for r in righe:
        r.dns_vecchio = dns_vecchio(r, ora)
        r.non_censito = r.presente and non_censito(r, ora)
    conteggi = {c: sum(1 for r in righe if _filtro(r, c, ora)) for c, _label in FILTRI}
    q = (q or "").strip().casefold()

    def cerca(r):
        testi = [r.ip, r.mac, r.nome_dhcp, *r.nomi_dns]
        if r.asset:
            testi += [r.asset.name, r.asset.asset_tag]
        if r.switch:
            testi.append(r.switch.dispositivo.nome)
        return any(q in (t or "").casefold() for t in testi)

    mostrate = [r for r in righe if _filtro(r, codice, ora) and (ambito_id is None or r.ambito_id == ambito_id)
                and (not q or cerca(r))]
    giro = ultimo_giro()
    ambiti = list(AmbitoDhcp.objects.filter(presente=True).order_by("server", "scope_id"))
    for a in ambiti:
        a.attivo = a.stato.lower() == "active"
        a.stato_label = STATI_AMBITO.get(a.stato.lower(), a.stato)
        a.pieno = a.attivo and (a.percentuale_uso or 0) >= SOGLIA_AMBITO_PIENO
    return {
        "righe": mostrate,
        "filtri": [{"code": c, "label": label, "count": conteggi[c], "active": c == codice} for c, label in FILTRI],
        "kpi": [{"code": c, "label": label, "testo": testo, "tono": tono, "count": conteggi[c], "active": c == codice}
                for c, label, testo, tono in KPI],
        "ambiti": ambiti,
        "soglia_ambito": SOGLIA_AMBITO_PIENO,
        "giorni_dns_vecchio": GIORNI_DNS_VECCHIO,
        "ultimo_giro": giro,
        "ultimo_giro_at": _data(giro.get("at")),
        "configurato": configurato(),
        "config": config(),
    }


COLONNE_EXCEL = ["IP", "MAC", "Ambito", "Nome nel DHCP", "Nomi nel DNS", "Tipo", "Switch", "Porta", "VLAN",
                 "Visto da", "Asset", "Codice asset", "Stato", "Ultima volta"]


def righe_excel(righe) -> list[list]:
    """Le righe della pagina (già filtrate e correlate) per l'export Excel."""
    out = []
    for r in righe:
        if r.asset:
            stato = "collegato"
        elif r.asset_proposto:
            stato = f"proposto: {r.asset_proposto.asset_tag} ({r.motivo_proposta})"
        elif getattr(r, "non_censito", False):
            stato = "non censito"
        else:
            stato = ""
        if getattr(r, "senza_protezione", ""):
            stato = f"{stato} · {r.senza_protezione}".strip(" ·")
        sw = getattr(r, "switch", None)
        out.append([
            r.ip, r.mac, str(r.ambito) if r.ambito else "", r.nome_dhcp, ", ".join(r.nomi_dns), r.get_tipo_display(),
            sw.dispositivo.nome if sw else "", sw.porta if sw else "", sw.vlan if sw and sw.vlan else "",
            ", ".join(f["nome"] for f in getattr(r, "fonti", [])),
            r.asset.name if r.asset else "", r.asset.asset_tag if r.asset else "", stato,
            timezone.localtime(r.ultima_vista).strftime("%d/%m/%Y %H:%M") if r.ultima_vista else "",
        ])
    return out
