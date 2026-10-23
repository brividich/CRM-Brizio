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
    return {"ambiti": len(ambiti), "indirizzi": len(visti), "spariti": spariti}


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


def aggiorna_proposte() -> int:
    """Proposta di asset per gli indirizzi presenti e non ancora collegati."""
    from assets.models import IndirizzoRete

    from .identity_match import match_hub_asset

    cambiate = 0
    qs = IndirizzoRete.objects.filter(asset__isnull=True).exclude(nel_dhcp=False, nel_dns=False)
    for riga in qs.iterator():
        asset, motivo = match_hub_asset(mac=riga.mac, ip=riga.ip, hostname=riga.nome)
        nuovo = (asset.pk if asset else None, motivo)
        if (riga.asset_proposto_id, riga.motivo_proposta) != nuovo:
            riga.asset_proposto_id, riga.motivo_proposta = nuovo
            riga.save(update_fields=["asset_proposto", "motivo_proposta", "aggiornato_il"])
            cambiate += 1
    return cambiate


def sincronizza(ora=None) -> dict:
    """Giro completo: DHCP di ogni server, poi DNS, poi le proposte. Un server che fallisce non ferma gli altri."""
    ora = ora or timezone.now()
    cfg = config()
    esito = {"at": ora.isoformat(), "dhcp": {}, "errori": []}
    for server in cfg["dhcp"]:
        try:
            esito["dhcp"][server] = salva_dhcp(server, leggi_dhcp(server), ora)
        except ReteError as exc:
            esito["errori"].append(f"DHCP {server}: {exc}")
    if cfg["dns"] and cfg["zone"]:
        try:
            esito["dns"] = salva_dns(leggi_dns(cfg["dns"], cfg["zone"]), ora)
        except ReteError as exc:
            esito["errori"].append(f"DNS {cfg['dns']}: {exc}")
    esito["proposte_cambiate"] = aggiorna_proposte()
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
    ("nome_diverso", "Nome DHCP diverso dal DNS"),
    ("dns_vecchi", "Record DNS vecchi"),
    ("prenotazioni", "Prenotazioni"),
    ("spariti", "Non più visti"),
]


def dns_vecchio(riga, ora=None) -> bool:
    """Record DNS dinamico non aggiornato da più di ``GIORNI_DNS_VECCHIO`` giorni e senza lease attivo."""
    if not riga.nel_dns or riga.dns_statico or riga.nel_dhcp or riga.dns_aggiornato_il is None:
        return False
    return riga.dns_aggiornato_il < (ora or timezone.now()) - timedelta(days=GIORNI_DNS_VECCHIO)


def _filtro(riga, codice, ora):
    if codice == "spariti":
        return not riga.presente
    if not riga.presente:
        return False
    return {
        "tutti": True,
        "non_censiti": riga.asset_id is None and riga.asset_proposto_id is None and riga.nel_dhcp,
        "da_collegare": riga.asset_id is None and riga.asset_proposto_id is not None,
        "collegati": riga.asset_id is not None,
        "nome_diverso": riga.nome_diverso,
        "dns_vecchi": dns_vecchio(riga, ora),
        "prenotazioni": riga.tipo == riga.TIPO_PRENOTAZIONE,
    }.get(codice, True)


def pagina(codice="tutti", q="", ambito_id=None, ora=None) -> dict:
    from assets.models import AmbitoDhcp, IndirizzoRete

    ora = ora or timezone.now()
    righe = list(IndirizzoRete.objects.select_related("asset", "asset_proposto", "ambito").order_by("ip"))
    righe.sort(key=lambda r: tuple(int(p) for p in r.ip.split(".")) if r.ip.count(".") == 3 else (999,))
    conteggi = {c: sum(1 for r in righe if _filtro(r, c, ora)) for c, _label in FILTRI}
    q = (q or "").strip().casefold()
    mostrate = [
        r for r in righe
        if _filtro(r, codice, ora)
        and (ambito_id is None or r.ambito_id == ambito_id)
        and (not q or q in r.ip or q in r.mac or q in r.nome_dhcp.casefold() or any(q in n.casefold() for n in r.nomi_dns)
             or (r.asset and q in r.asset.name.casefold()))
    ]
    for r in mostrate:
        r.dns_vecchio = dns_vecchio(r, ora)
    giro = ultimo_giro()
    ambiti = list(AmbitoDhcp.objects.filter(presente=True).order_by("server", "scope_id"))
    for a in ambiti:
        a.pieno = (a.percentuale_uso or 0) >= SOGLIA_AMBITO_PIENO
    return {
        "righe": mostrate,
        "filtri": [{"code": c, "label": label, "count": conteggi[c], "active": c == codice} for c, label in FILTRI],
        "ambiti": ambiti,
        "soglia_ambito": SOGLIA_AMBITO_PIENO,
        "giorni_dns_vecchio": GIORNI_DNS_VECCHIO,
        "ultimo_giro": giro,
        "ultimo_giro_at": _data(giro.get("at")),
        "configurato": configurato(),
        "config": config(),
    }
