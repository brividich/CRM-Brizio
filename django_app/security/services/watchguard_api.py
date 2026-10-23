"""WatchGuard Endpoint Security (EPDR / Patch Management) letto dall'API di WatchGuard Cloud.

Sola lettura. Credenziali da ``/soc/impostazioni/`` (riquadro «Credenziali API WatchGuard»), cifrate a
riposo in ``SecurityCenterSetting`` (``secret_box``): URL API della regione, ID account, Access ID e
password (meglio quelli «sola lettura») e API Key, tutti dalla pagina «Managed Access» di WatchGuard Cloud.

Tre letture, ognuna con il suo interruttore (sezione «WatchGuard Endpoint Security (API)»):

* **PC e protezione** (``devices`` + ``devicesprotectionstatus`` + ``unmanageddevices``) → ``WatchGuardDispositivo``:
  stato dell'agente, ultima connessione, MAC; i PC in rete senza agente con ``gestito=False``.
* **Software dei PC** (``softwareinventory``) → inventario del SOC come fonte WatchGuard, con la stessa
  procedura dell'export caricato a mano (``software_inventory.run_import``): sostituisce l'export.
* **Patch** (``patchavailability`` + task di tipo 6 ``tasks/…/jobs/…/results``) → ``WatchGuardPatch``:
  patch mancanti per PC con le CVE che correggono, esito delle installazioni.

L'API non documenta la creazione dei task di installazione: le patch si installano dalla console WatchGuard.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from security.models import (
    SecurityCenterSetting,
    SoftwareInventoryImport,
    SoftwareSourceKind,
    WatchGuardDispositivo,
    WatchGuardPatch,
)
from security.services import secret_box, soc_settings

logger = logging.getLogger(__name__)

SETTING = "watchguard.api.credenziali"
PURPOSE = "watchguard-api"
CAMPI = ("url_api", "account_id", "access_id", "password", "api_key")
SEGRETI = ("password", "api_key")
# Solo gli host dell'API di WatchGuard Cloud: le credenziali non partono mai verso altri indirizzi.
URL_API_RE = re.compile(r"^https://api\.[a-z0-9-]+\.cloud\.watchguard\.com$")
# Managed Access mostra anche «API URL (base)» con /rest/ e l'URL di autenticazione con /oauth/token: si accettano.
_URL_INCOLLATO_RE = re.compile(r"^(https://api\.[a-z0-9-]+\.cloud\.watchguard\.com)(/rest|/oauth/token)?/?$")
ACCOUNT_RE = re.compile(r"^(ACC-\d+|WGC-\d-[0-9a-zA-Z]+)$")
BASE = "/rest/endpoint-security/management/api/v1/accounts/{account}"
TIMEOUT = 30
PAGINA = 1000
MAX_PAGINE = 60
NOME_IMPORT = "WatchGuard Endpoint Security (API)"
TASK_PATCH = 6
TASK_GIORNI = 14
TASK_MAX = 20


class WatchGuardError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


# --- Credenziali -------------------------------------------------------------------------------

def credenziali() -> dict:
    setting = SecurityCenterSetting.objects.filter(key=SETTING).first()
    testo = secret_box.decrypt(setting.value, PURPOSE) if setting else ""
    try:
        dati = json.loads(testo) if testo else {}
    except ValueError:
        dati = {}
    return {campo: str(dati.get(campo) or "").strip() for campo in CAMPI}


def configurato() -> bool:
    return all(credenziali().values())


def riepilogo() -> dict:
    """Quello che la pagina può mostrare: mai password e API Key in chiaro."""
    cfg = credenziali()
    return {"url_api": cfg["url_api"], "account_id": cfg["account_id"], "access_id": cfg["access_id"],
            "password": bool(cfg["password"]), "api_key": bool(cfg["api_key"]), "configurato": all(cfg.values())}


def valida(dati: dict) -> list[str]:
    errori = []
    if not URL_API_RE.match(dati.get("url_api", "")):
        errori.append("URL API non valido: è l'«API URL (base)» di Managed Access, come https://api.deu.cloud.watchguard.com/rest/.")
    if not ACCOUNT_RE.match(dati.get("account_id", "")):
        errori.append("ID account non valido: è come ACC-1234567 o WGC-1-123abc456 (pagina My Account).")
    for campo, nome in (("access_id", "Access ID"), ("password", "password"), ("api_key", "API Key")):
        if not dati.get(campo):
            errori.append(f"Manca {nome}.")
    return errori


def salva_credenziali(nuovi: dict, actor=None) -> list[str]:
    """Salva le credenziali; password e API Key vuote = si tengono quelle già salvate."""
    from security.services.configuration import audit_config_change

    attuali = credenziali()
    dati = {campo: str(nuovi.get(campo) or "").strip()[:300] for campo in CAMPI}
    url = dati["url_api"].lower()
    trovato = _URL_INCOLLATO_RE.match(url)
    dati["url_api"] = trovato.group(1) if trovato else url.rstrip("/")
    for campo in SEGRETI:
        dati[campo] = dati[campo] or attuali[campo]
    errori = valida(dati)
    if errori:
        return errori
    setting, _ = SecurityCenterSetting.objects.get_or_create(
        key=SETTING, defaults={"category": "integrazioni", "is_secret": True,
                               "description": "Credenziali API WatchGuard Cloud (cifrate)"})
    setting.value = secret_box.encrypt(json.dumps(dati), PURPOSE)
    setting.is_secret = True
    setting.updated_by = actor if getattr(actor, "pk", None) else None
    setting.save()
    cambiati = [c for c in CAMPI if dati[c] != attuali[c]]
    audit_config_change(actor, "update", setting, field_name="value", old_value="***" if any(attuali.values()) else "",
                        new_value="campi cambiati: " + (", ".join(cambiati) or "nessuno"))
    _TOKEN.clear()
    return []


def cancella_credenziali(actor=None) -> None:
    from security.services.configuration import audit_config_change

    setting = SecurityCenterSetting.objects.filter(key=SETTING).first()
    if setting is None:
        return
    setting.value = ""
    setting.save()
    audit_config_change(actor, "update", setting, field_name="value", old_value="***", new_value="")
    _TOKEN.clear()


# --- Chiamate ----------------------------------------------------------------------------------

_TOKEN: dict = {}


def _token(cfg: dict) -> str:
    import requests

    chiave = (cfg["url_api"], cfg["access_id"])
    salvato = _TOKEN.get(chiave)
    if salvato and salvato[1] - 300 > time.time():
        return salvato[0]
    basic = base64.b64encode(f"{cfg['access_id']}:{cfg['password']}".encode()).decode()
    resp = requests.post(
        cfg["url_api"] + "/oauth/token", timeout=TIMEOUT,
        data={"grant_type": "client_credentials", "scope": "api-access"},
        headers={"Authorization": f"Basic {basic}", "Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code in (400, 401, 403):
        raise WatchGuardError("WatchGuard non ha dato il token: Access ID o password non validi.", resp.status_code)
    if resp.status_code >= 400:
        raise WatchGuardError(f"WatchGuard ha risposto {resp.status_code} alla richiesta del token.", resp.status_code)
    dati = resp.json()
    tok = dati.get("access_token")
    if not tok:
        raise WatchGuardError("WatchGuard non ha restituito il token.")
    _TOKEN[chiave] = (tok, time.time() + int(dati.get("expires_in") or 3600))
    return tok


def get(percorso: str, params: dict | None = None, *, cfg: dict | None = None):
    import requests

    cfg = cfg or credenziali()
    if not all(cfg.values()):
        raise WatchGuardError("Credenziali API WatchGuard non configurate.")
    if not URL_API_RE.match(cfg["url_api"]):
        raise WatchGuardError("URL API WatchGuard non ammesso.")
    url = cfg["url_api"] + BASE.format(account=cfg["account_id"]) + percorso
    resp = requests.get(url, params=params, timeout=TIMEOUT, headers={
        "Authorization": f"Bearer {_token(cfg)}", "WatchGuard-API-Key": cfg["api_key"],
        "Accept": "application/json", "Content-Type": "application/json"})
    if resp.status_code == 401:
        _TOKEN.clear()
        raise WatchGuardError("WatchGuard ha risposto 401: token o API Key non validi.", 401)
    if resp.status_code == 403:
        raise WatchGuardError("WatchGuard ha risposto 403: l'API Key o l'account non hanno accesso a Endpoint Security.", 403)
    if resp.status_code == 404:
        raise WatchGuardError("WatchGuard ha risposto 404: controlla l'ID account.", 404)
    if resp.status_code >= 400:
        raise WatchGuardError(f"WatchGuard ha risposto {resp.status_code}.", resp.status_code)
    return resp.json()


def get_all(percorso: str, params: dict | None = None, *, cfg: dict | None = None) -> list[dict]:
    """Tutte le pagine di una collezione ``{data, total_items}`` con ``$top``/``$skip``."""
    out: list[dict] = []
    for pagina in range(MAX_PAGINE):
        dati = get(percorso, {**(params or {}), "$top": PAGINA, "$skip": pagina * PAGINA, "$count": "true"}, cfg=cfg)
        righe = [r for r in (dati.get("data") if isinstance(dati, dict) else dati) or [] if isinstance(r, dict)]
        out.extend(righe)
        totale = dati.get("total_items") if isinstance(dati, dict) else None
        if len(righe) < PAGINA or (totale is not None and len(out) >= int(totale)):
            break
    return out


def prova() -> dict:
    """Prova di connessione dalla pagina: quanti PC vede l'account."""
    dati = get("/devices", {"$top": 1, "$count": "true"})
    return {"pc": dati.get("total_items") if isinstance(dati, dict) else None}


# --- Utilità -----------------------------------------------------------------------------------

def _quando(valore):
    if not valore:
        return None
    dt = parse_datetime(str(valore))
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


def _giorno(valore):
    return parse_date(str(valore)[:10]) if valore else None


class _Asset:
    """Collegamento host → asset (stessa regola dell'inventario), una query per host."""

    def __init__(self):
        self._cache = {}

    def __call__(self, host):
        from security.services.software_inventory import _link_assets

        if host not in self._cache:
            self._cache[host] = _link_assets(host)[1] if host else None
        return self._cache[host]


def _host(valore):
    from security.services.software_inventory import normalize_host

    return normalize_host(valore)


# --- PC e protezione ---------------------------------------------------------------------------

def sincronizza_dispositivi(now=None, *, dispositivi=None, protezione=None, non_gestiti=None) -> dict:
    from assets.services.mac import normalizza_mac

    now = now or timezone.now()
    if dispositivi is None:
        dispositivi = get_all("/devices")
    if protezione is None:
        protezione = get_all("/devicesprotectionstatus")
    if non_gestiti is None:
        non_gestiti = get_all("/unmanageddevices")
    stato = {str(p.get("device_id")): p for p in protezione if p.get("device_id")}
    asset_di = _Asset()
    visti = set()
    for d in dispositivi:
        device_id = str(d.get("device_id") or "")
        if not device_id:
            continue
        p = stato.get(device_id, {})
        host = _host(d.get("host_name"))
        macs = [m for m in (normalizza_mac(x) for x in d.get("mac_addresses") or []) if m]
        motore = p.get("protection_engine_update_status")
        WatchGuardDispositivo.objects.update_or_create(device_id=device_id, defaults={
            "gestito": True, "host": host, "host_display": str(d.get("host_name") or "")[:255],
            "hub_asset": asset_di(host), "ip": str(d.get("ip_address") or "")[:64], "mac": " ".join(macs)[:400],
            "sistema": str(d.get("operating_system") or "")[:200], "agente": str(d.get("agent_version") or "")[:60],
            "protezione": p.get("accumulated_protection_status"),
            "motore_aggiornato": None if motore in (None, 0) else motore != 1,
            "riavvio_richiesto": bool(d.get("reboot_requested") or p.get("reboot_requested")),
            "isolato": (d.get("isolation_state") or 0) in (1, 2),
            "ultima_connessione": _quando(d.get("last_connection") or p.get("last_connection_date")),
            "presente": True, "letto_il": now,
        })
        visti.add(device_id)
    for u in non_gestiti:
        device_id = "unmanaged:" + str(u.get("device_id") or u.get("mac_address") or u.get("ip_address") or "")
        if device_id == "unmanaged:":
            continue
        host = _host(u.get("host_name"))
        WatchGuardDispositivo.objects.update_or_create(device_id=device_id[:120], defaults={
            "gestito": False, "host": host, "host_display": str(u.get("host_name") or "")[:255],
            "hub_asset": asset_di(host), "ip": str(u.get("ip_address") or "")[:64],
            "mac": normalizza_mac(u.get("mac_address")), "sonda": str(u.get("probe_name") or "")[:255],
            "produttore_scheda": str(u.get("network_interface_controller_vendor") or "")[:255],
            "ultima_connessione": _quando(u.get("last_seen_datetime")), "presente": True, "letto_il": now,
        })
        visti.add(device_id[:120])
    spariti = WatchGuardDispositivo.objects.filter(presente=True).exclude(device_id__in=visti).update(presente=False)
    return {"pc": len(dispositivi), "senza_agente": len(non_gestiti), "spariti": spariti}


# --- Software ----------------------------------------------------------------------------------

def anteprima_software(righe: list[dict]):
    from security.services.software_inventory import RowPreview

    preview = RowPreview(total=len(righe))
    visti = set()
    for i, r in enumerate(righe, start=1):
        if r.get("is_patch"):
            preview.skipped.append((i, "aggiornamento, non programma"))
            continue
        host, prodotto = str(r.get("host_name") or "").strip(), str(r.get("name") or "").strip()
        versione, vendor = str(r.get("version") or "").strip(), str(r.get("publisher") or "").strip()
        if not host or not prodotto:
            preview.skipped.append((i, "nome PC o prodotto vuoto"))
            continue
        if not versione:
            preview.skipped.append((i, "versione vuota (non confrontabile con i range CVE)"))
            continue
        chiave = (host.casefold(), vendor.casefold(), prodotto.casefold(), versione.casefold())
        if chiave in visti:
            continue
        visti.add(chiave)
        preview.valid.append({"host": host[:255], "vendor": vendor[:255], "product": prodotto[:255],
                              "version": versione[:120], "detected_at": _giorno(r.get("installation_date"))})
    return preview


def sincronizza_software(*, righe: list[dict] | None = None) -> dict:
    from security.services.defender_software import _dopo_import
    from security.services.software_inventory import run_import

    if righe is None:
        righe = get_all("/softwareinventory")
    preview = anteprima_software(righe)
    if not preview.valid:
        # Una lettura vuota non deve segnare «non più rilevato» tutto il software WatchGuard.
        return {"righe": len(righe), "importate": 0, "saltato": "nessuna riga valida"}
    impronta = hashlib.sha256(json.dumps(preview.valid, sort_keys=True, default=str).encode()).hexdigest()
    item = SoftwareInventoryImport.objects.create(
        source_kind=SoftwareSourceKind.WATCHGUARD, original_name=NOME_IMPORT, file_sha256=impronta,
        inventory_date=timezone.localdate(),
    )
    run_import(item, preview)
    try:
        _dopo_import()
    except Exception:  # noqa: BLE001 - l'import è fatto; i passi successivi hanno il loro job orario
        logger.exception("WatchGuard software: passi dopo l'import non riusciti")
    return {"righe": item.rows_total, "importate": item.rows_imported, "nuove": item.rows_new,
            "pc": item.hosts_count, "non_piu_rilevate": item.rows_marked_missing}


# --- Patch -------------------------------------------------------------------------------------

def _cve_testo(ids) -> str:
    puliti = sorted({str(c).strip().upper() for c in ids or [] if str(c).strip().upper().startswith("CVE-")})
    return ("|" + "|".join(puliti) + "|") if puliti else ""


def sincronizza_patch(now=None, *, righe: list[dict] | None = None) -> dict:
    now = now or timezone.now()
    if righe is None:
        righe = get_all("/patchavailability")
    asset_di = _Asset()
    visti = set()
    for r in righe:
        device_id, patch_id = str(r.get("device_id") or ""), str(r.get("patch_id") or "")
        if not device_id or not patch_id:
            continue
        host = _host(r.get("host_name"))
        obj, _ = WatchGuardPatch.objects.update_or_create(device_id=device_id[:120], patch_id=patch_id[:120], defaults={
            "host": host, "host_display": str(r.get("host_name") or "")[:255], "hub_asset": asset_di(host),
            "nome": str(r.get("patch_name") or patch_id)[:500], "programma": str(r.get("program_name") or "")[:255],
            "versione": str(r.get("program_version") or "")[:120],
            "produttore": str(r.get("vendor_name") or "")[:255], "rilasciata_il": _giorno(r.get("patch_release_date")),
            "criticita": r.get("patch_criticality"), "di_sistema": r.get("patch_type") == 1,
            "disponibilita": r.get("patch_installation_availability"), "cve": _cve_testo(r.get("patch_cve_ids")),
            "presente": True, "vista_il": now, "chiusa_il": None,
        })
        visti.add(obj.pk)
    chiuse = WatchGuardPatch.objects.filter(presente=True).exclude(pk__in=visti).update(presente=False, chiusa_il=now)
    return {"patch": len(visti), "chiuse": chiuse}


def sincronizza_task(now=None) -> dict:
    """Esito delle installazioni di patch (task di tipo 6) degli ultimi ``TASK_GIORNI`` giorni."""
    now = now or timezone.now()
    dal = now - timedelta(days=TASK_GIORNI)
    tasks = get_all("/tasks", {"$filter": f"41003 Eq {TASK_PATCH}"})
    recenti = [t for t in tasks if (_quando((t.get("status") or {}).get("last_job_date")) or dal) > dal][:TASK_MAX]
    aggiornate = 0
    for t in recenti:
        jobs = get(f"/tasks/{TASK_PATCH}/{t.get('id')}/jobs") or []
        jobs = sorted((j for j in jobs if isinstance(j, dict)), key=lambda j: str(j.get("date") or ""), reverse=True)[:3]
        for job in reversed(jobs):  # dal più vecchio: l'ultimo esito vince
            for r in get_all(f"/tasks/{TASK_PATCH}/{t.get('id')}/jobs/{job.get('id')}/results"):
                info = r.get("patch_info") or {}
                if not info.get("patch_name") or not info.get("result"):
                    continue
                quando = _quando(info.get("installation_date") or r.get("date")) or now
                aggiornate += WatchGuardPatch.objects.filter(
                    host=_host(r.get("host_name")), nome=str(info["patch_name"])[:500],
                ).update(esito=info["result"], esito_il=quando)
    return {"task": len(recenti), "patch_aggiornate": aggiornate}


# --- Lettura per pannelli ----------------------------------------------------------------------

def patch_per_cve(cve_id: str, hosts=None) -> dict:
    """{host: [patch aperte che correggono la CVE]} (solo patch ancora mancanti)."""
    qs = WatchGuardPatch.objects.filter(presente=True, cve__contains=f"|{cve_id}|")
    if hosts is not None:
        qs = qs.filter(host__in=list(hosts)[:500])
    out: dict = {}
    for p in qs.order_by("nome"):
        out.setdefault(p.host, []).append(p)
    return out


def patch_aperte_per_cve(cve_ids, hosts=None) -> dict:
    """{(cve_id, host): patch} per molte CVE insieme (una query, filtro in Python)."""
    ids = set(cve_ids)
    if not ids:
        return {}
    qs = WatchGuardPatch.objects.filter(presente=True).exclude(cve="")
    if hosts is not None:
        qs = qs.filter(host__in=list(hosts)[:500])
    out = {}
    for p in qs.only("host", "nome", "cve", "disponibilita", "esito", "criticita", "rilasciata_il"):
        for c in p.cve_lista:
            if c in ids:
                out.setdefault((c, p.host), p)
    return out


# --- Task --------------------------------------------------------------------------------------

def run() -> dict:
    """Task pianificato: ogni parte gira solo con il suo interruttore; mai un'eccezione verso la coda."""
    attivi = {k: soc_settings.value(f"watchguard.api.{k}") for k in ("dispositivi", "software", "patch")}
    if not any(attivi.values()):
        return {"attivo": False}
    if not configurato():
        return {"ok": False, "motivo": "credenziali API WatchGuard non configurate"}
    now = timezone.now()
    out = {"ok": True}
    passi = (("dispositivi", sincronizza_dispositivi), ("software", sincronizza_software),
             ("patch", sincronizza_patch), ("task", sincronizza_task))
    for nome, passo in passi:
        if not attivi["patch" if nome == "task" else nome]:
            continue
        try:
            out[nome] = passo(now) if nome != "software" else passo()
        except WatchGuardError as exc:
            logger.warning("WatchGuard API %s: %s", nome, exc)
            out[nome] = {"errore": str(exc)[:300]}
            out["ok"] = False
        except Exception as exc:  # noqa: BLE001 - una parte fallita non blocca le altre
            logger.exception("WatchGuard API %s non riuscita", nome)
            out[nome] = {"errore": f"{type(exc).__name__}"}
            out["ok"] = False
    return out
