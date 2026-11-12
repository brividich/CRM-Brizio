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
  patch mancanti per PC con le CVE che correggono, KB, link di download, esito delle installazioni;
  i task di installazione restano nello storico ``WatchGuardTask`` (anche ogni ora con ``run_task``).
  Con ``watchguard.api.msrc`` anche le sostituzioni fra KB dal Security Update Guide di Microsoft
  (``services/patch_kb.py``): quale patch mancante è già compresa in una più recente.

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

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from security.models import (
    SecurityCenterSetting,
    SoftwareInventoryImport,
    SoftwareSourceKind,
    WatchGuardDispositivo,
    WatchGuardPatch,
    WatchGuardTask,
)
from security.services import secret_box, soc_settings
from security.services.patch_kb import kb_da_testo

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
TASK_ERRORI_MAX = 5  # task di fila in errore senza nessuno letto: WatchGuard è giù, il giro si ferma
RIPROVA_SECONDI = 3  # pausa prima del secondo tentativo su 502/503/504 (gateway WatchGuard)
PAGINA = 1000
MAX_PAGINE = 60
NOME_IMPORT = "WatchGuard Endpoint Security (API)"
TASK_PATCH = 6
TASK_GIORNI = 30   # task con un'esecuzione negli ultimi 30 giorni; quelli già letti restano nello storico
TASK_MAX = 300     # task letti per giro (i completi non costano chiamate: si saltano)
TASK_JOB_MAX = 10  # esecuzioni per task (le ultime)
TASK_ORE_STABILE = 24  # un task con tutti gli esiti e l'ultima esecuzione più vecchia di così non si rilegge
VERIFICA_GIORNI = 2    # un task finito più di recente fa rileggere subito patch e software (ricalcolo CVE)


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


def _chi_risponde(resp) -> str:
    """Se a rispondere non è WatchGuard (un proxy, una pagina di errore), lo dice: le risposte dell'API sono JSON."""
    headers = getattr(resp, "headers", None)
    if not hasattr(headers, "get"):
        return ""
    tipo = str(headers.get("Content-Type") or "")
    server = str(headers.get("Server") or "")[:60]
    if not tipo or "json" in tipo.lower():
        return ""
    return (" La risposta non arriva dall'API di WatchGuard"
            + (f" (server «{server}»)" if server else "")
            + ": risponde un proxy o un altro servizio.")


def _errore_rete(exc, cosa: str) -> WatchGuardError:
    """Errore di rete con la causa vera: proxy (ProxyError), certificato (SSLError), tempo o connessione."""
    import requests

    if isinstance(exc, requests.exceptions.ProxyError):
        return WatchGuardError(f"WatchGuard non raggiungibile ({cosa}): il proxy del server ha rifiutato o interrotto la "
                               "connessione (controlla HTTPS_PROXY e le credenziali del proxy).")
    if isinstance(exc, requests.exceptions.SSLError):
        return WatchGuardError(f"WatchGuard non raggiungibile ({cosa}): certificato HTTPS non attendibile; di solito è il "
                               "proxy che ispeziona il traffico HTTPS (serve un'eccezione per *.cloud.watchguard.com).")
    if isinstance(exc, requests.exceptions.Timeout):
        return WatchGuardError(f"WatchGuard non ha risposto in {TIMEOUT} s ({cosa}).")
    return WatchGuardError(f"WatchGuard non raggiungibile ({cosa}, {type(exc).__name__}): controlla la connessione "
                           "a internet del server e il proxy.")


def _json(resp, cosa: str):
    try:
        return resp.json()
    except ValueError as exc:
        raise WatchGuardError(f"Risposta di WatchGuard non leggibile ({cosa}): non è JSON.{_chi_risponde(resp)}",
                              resp.status_code) from exc


class Client:
    """Una sessione HTTP per giro: credenziali lette una volta, un solo rinnovo del token su 401."""

    def __init__(self, cfg: dict | None = None):
        import requests

        self.cfg = cfg or credenziali()
        if not all(self.cfg.values()):
            raise WatchGuardError("Credenziali API WatchGuard non configurate.")
        if not URL_API_RE.match(self.cfg["url_api"]):
            raise WatchGuardError("URL API WatchGuard non ammesso.")
        # WatchGuard Cloud è su internet: il proxy di HTTPS_PROXY serve (trust_env resta acceso).
        self.http = requests.Session()

    def _token(self, rinnova: bool = False) -> str:
        import requests

        cfg = self.cfg
        chiave = (cfg["url_api"], cfg["access_id"])
        salvato = _TOKEN.get(chiave)
        if not rinnova and salvato and salvato[1] - 300 > time.time():
            return salvato[0]
        _TOKEN.pop(chiave, None)
        basic = base64.b64encode(f"{cfg['access_id']}:{cfg['password']}".encode()).decode()
        try:
            resp = self.http.post(
                cfg["url_api"] + "/oauth/token", timeout=TIMEOUT,
                data={"grant_type": "client_credentials", "scope": "api-access"},
                headers={"Authorization": f"Basic {basic}", "Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
        except requests.exceptions.RequestException as exc:
            raise _errore_rete(exc, "richiesta del token") from exc
        if resp.status_code == 407:
            raise WatchGuardError("Il proxy del server chiede l'autenticazione (407) alla richiesta del token WatchGuard.", 407)
        chi = _chi_risponde(resp)
        if resp.status_code in (400, 401, 403) and not chi:
            raise WatchGuardError("WatchGuard non ha dato il token: Access ID o password non validi.", resp.status_code)
        if resp.status_code >= 400:
            raise WatchGuardError(f"WatchGuard ha risposto {resp.status_code} alla richiesta del token.{chi}", resp.status_code)
        dati = _json(resp, "token")
        tok = dati.get("access_token") if isinstance(dati, dict) else None
        if not tok:
            raise WatchGuardError(f"WatchGuard non ha restituito il token.{chi}")
        try:
            durata = int(dati.get("expires_in") or 3600)
        except (TypeError, ValueError):
            durata = 3600
        _TOKEN[chiave] = (tok, time.time() + durata)
        return tok

    def get(self, percorso: str, params: dict | None = None):
        import requests

        cfg = self.cfg
        url = cfg["url_api"] + BASE.format(account=cfg["account_id"]) + percorso
        rinnovato = riprovato = False
        while True:
            try:
                resp = self.http.get(url, params=params, timeout=TIMEOUT, headers={
                    "Authorization": f"Bearer {self._token(rinnova=rinnovato)}", "WatchGuard-API-Key": cfg["api_key"],
                    "Accept": "application/json", "Content-Type": "application/json"})
            except requests.exceptions.RequestException as exc:
                raise _errore_rete(exc, percorso) from exc
            if resp.status_code == 401 and not rinnovato and not _chi_risponde(resp):
                rinnovato = True  # token scaduto prima del previsto: un solo rinnovo e un solo nuovo tentativo
                continue
            if resp.status_code in (502, 503, 504) and not riprovato:
                riprovato = True  # gateway di WatchGuard momentaneamente giù: un secondo tentativo dopo una pausa
                time.sleep(RIPROVA_SECONDI)
                continue
            break
        chi = _chi_risponde(resp)
        if resp.status_code == 407:
            raise WatchGuardError(f"Il proxy del server chiede l'autenticazione (407) su {percorso}.", 407)
        if chi and resp.status_code >= 400:
            raise WatchGuardError(f"Risposta {resp.status_code} su {percorso}.{chi}", resp.status_code)
        if resp.status_code == 401:
            _TOKEN.pop((cfg["url_api"], cfg["access_id"]), None)
            raise WatchGuardError("WatchGuard ha risposto 401 anche con un token nuovo: API Key non valida.", 401)
        if resp.status_code == 403:
            raise WatchGuardError("WatchGuard ha risposto 403: l'API Key o l'account non hanno accesso a Endpoint Security.", 403)
        if resp.status_code == 404:
            raise WatchGuardError("WatchGuard ha risposto 404: controlla l'ID account.", 404)
        if resp.status_code >= 400:
            raise WatchGuardError(f"WatchGuard ha risposto {resp.status_code} su {percorso}.", resp.status_code)
        return _json(resp, percorso)

    def close(self) -> None:
        try:
            self.http.close()
        except Exception:  # noqa: BLE001 - chiusura best effort
            logger.debug("WatchGuard: chiusura della sessione non riuscita")


def get(percorso: str, params: dict | None = None, *, cfg: dict | None = None, client: Client | None = None):
    if client is not None:
        return client.get(percorso, params)
    c = Client(cfg)
    try:
        return c.get(percorso, params)
    finally:
        c.close()


def get_all(percorso: str, params: dict | None = None, *, cfg: dict | None = None,
            client: Client | None = None) -> list[dict]:
    """Tutte le pagine di una collezione ``{data, total_items}`` con ``$top``/``$skip``.

    Una lettura incompleta (finite le ``MAX_PAGINE`` o meno righe di ``total_items``) è un errore: chi
    chiama non deve segnare spariti o chiusi i record delle pagine non lette.
    """
    out: list[dict] = []
    totale = None
    completa = False
    for pagina in range(MAX_PAGINE):
        dati = get(percorso, {**(params or {}), "$top": PAGINA, "$skip": pagina * PAGINA, "$count": "true"},
                   cfg=cfg, client=client)
        righe = [r for r in (dati.get("data") if isinstance(dati, dict) else dati) or [] if isinstance(r, dict)]
        out.extend(righe)
        valore = dati.get("total_items") if isinstance(dati, dict) else None
        try:
            totale = int(valore) if valore is not None else totale
        except (TypeError, ValueError):
            pass
        if len(righe) < PAGINA or (totale is not None and len(out) >= totale):
            completa = True
            break
    if not completa:
        raise WatchGuardError(f"Lettura troncata di {percorso}: oltre {MAX_PAGINE} pagine da {PAGINA} righe; "
                              "nessun record segnato come sparito o chiuso.")
    if totale is not None and len(out) < totale:
        raise WatchGuardError(f"Lettura troncata di {percorso}: lette {len(out)} righe su {totale}; "
                              "nessun record segnato come sparito o chiuso.")
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

def sincronizza_dispositivi(now=None, *, dispositivi=None, protezione=None, non_gestiti=None, client=None) -> dict:
    from assets.services.mac import normalizza_mac

    now = now or timezone.now()
    if dispositivi is None:
        dispositivi = get_all("/devices", client=client)
    if protezione is None:
        protezione = get_all("/devicesprotectionstatus", client=client)
    if non_gestiti is None:
        non_gestiti = get_all("/unmanageddevices", client=client)
    if not dispositivi and WatchGuardDispositivo.objects.filter(gestito=True, presente=True).exists():
        # Una risposta vuota con PC già letti è quasi sempre un errore dell'API: non si segna sparito nessuno.
        raise WatchGuardError("WatchGuard ha restituito un elenco di PC vuoto: passo saltato, nessun PC segnato come sparito.")
    stato = {str(p.get("device_id")): p for p in protezione if p.get("device_id")}
    asset_di = _Asset()
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
    # I PC visti in questo giro hanno letto_il = now: niente elenco di id nella query (limite di 2100 parametri).
    spariti = WatchGuardDispositivo.objects.filter(presente=True, letto_il__lt=now).update(presente=False)
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
        # Senza versione il programma entra comunque nell'inventario (come lo mostra WatchGuard):
        # resta fuori solo dal confronto con le CVE (cve_impact.Contesto salta le versioni vuote).
        chiave = (host.casefold(), vendor.casefold(), prodotto.casefold(), versione.casefold())
        if chiave in visti:
            continue
        visti.add(chiave)
        preview.valid.append({"host": host[:255], "vendor": vendor[:255], "product": prodotto[:255],
                              "version": versione[:120], "detected_at": _giorno(r.get("installation_date"))})
    return preview


def sincronizza_software(*, righe: list[dict] | None = None, client=None) -> dict:
    from security.services.defender_software import _dopo_import
    from security.services.software_inventory import run_import

    if righe is None:
        righe = get_all("/softwareinventory", client=client)
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


def _url_download(valore) -> str:
    """Link di download manuale della patch: solo https, mai javascript: o altro nella pagina."""
    url = str(valore or "").strip()
    return url[:1000] if url.lower().startswith("https://") else ""


CAMPI_PATCH = ("host", "host_display", "hub_asset", "nome", "programma", "versione", "produttore", "rilasciata_il",
               "criticita", "di_sistema", "disponibilita", "cve", "kb", "download_url", "nome_file",
               "riavvio_automatico", "presente", "vista_il", "chiusa_il")
BLOCCO = 500


def sincronizza_patch(now=None, *, righe: list[dict] | None = None, client=None) -> dict:
    now = now or timezone.now()
    if righe is None:
        righe = get_all("/patchavailability", client=client)
    asset_di = _Asset()
    lette: dict = {}
    for r in righe:
        device_id, patch_id = str(r.get("device_id") or "")[:120], str(r.get("patch_id") or "")[:120]
        if not device_id or not patch_id:
            continue
        host = _host(r.get("host_name"))
        lette[(device_id, patch_id)] = {
            "host": host, "host_display": str(r.get("host_name") or "")[:255], "hub_asset": asset_di(host),
            "nome": str(r.get("patch_name") or patch_id)[:500], "programma": str(r.get("program_name") or "")[:255],
            "versione": str(r.get("program_version") or "")[:120],
            "produttore": str(r.get("vendor_name") or "")[:255], "rilasciata_il": _giorno(r.get("patch_release_date")),
            "criticita": r.get("patch_criticality"), "di_sistema": r.get("patch_type") == 1,
            "disponibilita": r.get("patch_installation_availability"), "cve": _cve_testo(r.get("patch_cve_ids")),
            "kb": kb_da_testo(r.get("patch_name"), r.get("local_filename")),
            "download_url": _url_download(r.get("download_url")), "nome_file": str(r.get("local_filename") or "")[:255],
            "riavvio_automatico": r.get("automatic_reboot") if isinstance(r.get("automatic_reboot"), bool) else None,
            # una patch rivista torna aperta: chiusa_il si azzera come prima con update_or_create
            "presente": True, "vista_il": now, "chiusa_il": None,
        }
    if not lette and WatchGuardPatch.objects.filter(presente=True).exists():
        # Una risposta vuota con patch già aperte è quasi sempre un errore dell'API: non si chiude niente.
        raise WatchGuardError("WatchGuard ha restituito un elenco di patch vuoto: passo saltato, nessuna patch chiusa.")
    # Righe già a DB, per blocchi di PC (mai migliaia di parametri in una query: limite SQL Server 2100).
    esistenti: dict = {}
    pc = sorted({d for d, _ in lette})
    for i in range(0, len(pc), BLOCCO):
        for pk, d, pid in WatchGuardPatch.objects.filter(device_id__in=pc[i:i + BLOCCO]).values_list("pk", "device_id", "patch_id"):
            esistenti[(d, pid)] = pk
    da_creare, da_aggiornare = [], []
    for (device_id, patch_id), campi in lette.items():
        pk = esistenti.get((device_id, patch_id))
        if pk is None:
            da_creare.append(WatchGuardPatch(device_id=device_id, patch_id=patch_id, **campi))
        else:
            da_aggiornare.append(WatchGuardPatch(pk=pk, device_id=device_id, patch_id=patch_id, **campi))
    if da_creare:
        WatchGuardPatch.objects.bulk_create(da_creare, batch_size=BLOCCO)
    if da_aggiornare:
        WatchGuardPatch.objects.bulk_update(da_aggiornare, CAMPI_PATCH, batch_size=BLOCCO)
    # Le patch viste in questo giro hanno vista_il = now: chiuse le altre, senza elenco di id nella query.
    chiuse = WatchGuardPatch.objects.filter(presente=True, vista_il__lt=now).update(presente=False, chiusa_il=now)
    try:
        from security.services.patch_sla import registra_giorno

        registra_giorno(now)
    except Exception:  # noqa: BLE001 - la fotografia dell'andamento non blocca la lettura
        logger.exception("WatchGuard patch: fotografia giornaliera non scritta")
    return {"patch": len(lette), "chiuse": chiuse}


def _primo(d: dict, *chiavi):
    """Primo valore non vuoto fra più nomi di campo (l'API non è documentata su tutti i campi dei task)."""
    for k in chiavi:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _esito(valore):
    try:
        n = int(valore)
    except (TypeError, ValueError):
        return None
    return n if n in WatchGuardPatch.ESITI else None


def _jobs(task_id, client):
    dati = get(f"/tasks/{TASK_PATCH}/{task_id}/jobs", client=client) or []
    righe = dati.get("data") if isinstance(dati, dict) else dati
    righe = [j for j in righe or [] if isinstance(j, dict) and j.get("id") not in (None, "")]
    return sorted(righe, key=lambda j: str(_primo(j, "date", "start_date", "creation_date") or ""))[-TASK_JOB_MAX:]


def _salva_task(t: dict, now, client, asset_di) -> tuple[WatchGuardTask, int]:
    """Legge le esecuzioni di un task e ne salva gli esiti per PC; restituisce (task, esiti salvati)."""
    from security.models import WatchGuardTaskEsito

    task_id = str(t.get("id"))[:120]
    stato = t.get("status") if isinstance(t.get("status"), dict) else {}
    task, _ = WatchGuardTask.objects.get_or_create(task_id=task_id)
    task.nome = str(_primo(t, "name", "task_name", "description") or "")[:500]
    task.creato_il = _quando(_primo(t, "creation_date", "created_date", "date")) or task.creato_il
    task.ultimo_job_il = _quando(stato.get("last_job_date")) or task.ultimo_job_il
    salvati = 0
    for job in _jobs(task_id, client):  # dal più vecchio: l'ultimo esito vince
        job_id = str(job["id"])[:120]
        job_il = _quando(_primo(job, "date", "start_date", "creation_date"))
        for r in get_all(f"/tasks/{TASK_PATCH}/{task_id}/jobs/{job_id}/results", client=client):
            info = r.get("patch_info") if isinstance(r.get("patch_info"), dict) else {}
            host = _host(r.get("host_name"))
            if not host:
                continue
            esito = _esito(info.get("result"))
            patch_nome = str(info.get("patch_name") or "")[:500]
            WatchGuardTaskEsito.objects.update_or_create(
                task=task, job_id=job_id, host=host, patch_nome=patch_nome,
                defaults={"job_il": job_il, "device_id": str(r.get("device_id") or "")[:120],
                          "host_display": str(r.get("host_name") or "")[:255], "hub_asset": asset_di(host),
                          "esito": esito,
                          "esito_il": _quando(info.get("installation_date") or r.get("date")) if esito else None,
                          "letto_il": now})
            salvati += 1
            if esito and patch_nome:
                WatchGuardPatch.objects.filter(host=host, nome=patch_nome).update(
                    esito=esito, esito_il=_quando(info.get("installation_date") or r.get("date")) or now)
    # Conteggi sull'ultimo esito per (PC, patch): un PC riprovato in un'esecuzione successiva conta una volta.
    ultimi: dict = {}
    for host, nome, esito in task.esiti.order_by("job_il", "pk").values_list("host", "patch_nome", "esito"):
        ultimi[(host, nome)] = esito
    task.pc = len({h for h, _ in ultimi})
    task.errori = sum(1 for e in ultimi.values() if e in WatchGuardPatch.ESITI_ERRORE)
    task.in_attesa = sum(1 for e in ultimi.values() if e is None)
    task.riuscite = len(ultimi) - task.errori - task.in_attesa
    vecchio = task.ultimo_job_il is not None and task.ultimo_job_il < now - timedelta(hours=TASK_ORE_STABILE)
    task.completo = bool(ultimi) and task.in_attesa == 0 and vecchio
    task.letto_il = now
    task.save()
    return task, salvati


def sincronizza_task(now=None, *, client=None) -> dict:
    """Task di installazione patch (tipo 6) degli ultimi ``TASK_GIORNI`` giorni → storico ``WatchGuardTask``.

    Si rileggono solo i task nuovi, cambiati (altra esecuzione) o con PC ancora in attesa: quelli
    completi restano come sono, così il giro orario fa poche chiamate anche con molti task.
    """
    now = now or timezone.now()
    dal = now - timedelta(days=TASK_GIORNI)
    tasks = get_all("/tasks", {"$filter": f"41003 Eq {TASK_PATCH}"}, client=client)
    recenti = [t for t in tasks if t.get("id") not in (None, "")
               and (_quando((t.get("status") or {}).get("last_job_date")) or now) > dal]
    recenti.sort(key=lambda t: str((t.get("status") or {}).get("last_job_date") or ""), reverse=True)
    noti = {x.task_id: x for x in WatchGuardTask.objects.filter(task_id__in=[str(t["id"])[:120] for t in recenti][:2000])}
    asset_di = _Asset()
    letti = saltati = esiti = 0
    errori: list[str] = []
    for t in recenti[:TASK_MAX]:
        prima = noti.get(str(t["id"])[:120])
        ultimo = _quando((t.get("status") or {}).get("last_job_date"))
        if prima is not None and prima.completo and (ultimo is None or ultimo == prima.ultimo_job_il):
            saltati += 1
            continue
        try:
            with transaction.atomic():
                _, n = _salva_task(t, now, client, asset_di)
        except WatchGuardError as exc:
            # Un task che WatchGuard non serve (502 su /jobs) non ferma gli altri: resta com'era e si riprova al giro dopo.
            logger.warning("WatchGuard task %s: %s", t.get("id"), exc)
            nome = str(_primo(t, "name", "task_name", "description") or t.get("id"))[:80]
            errori.append(f"«{nome}»: {str(exc)[:160]}")
            if len(errori) >= TASK_ERRORI_MAX and letti == 0:
                raise WatchGuardError(f"I primi {len(errori)} task sono tutti in errore, giro fermato. Primo: {errori[0]}") from exc
            continue
        letti += 1
        esiti += n
    if errori and letti == 0:
        raise WatchGuardError(f"Nessun task letto, {len(errori)} in errore. Primo: {errori[0]}")
    return {"task": len(recenti), "letti": letti, "invariati": saltati, "esiti": esiti,
            "oltre_limite": max(0, len(recenti) - TASK_MAX), "errori": errori[:10], "in_errore": len(errori)}


def task_da_verificare():
    """Task finiti (nessun PC in attesa, almeno un'installazione riuscita) non ancora verificati dopo l'ultima esecuzione."""
    from django.db.models import F, Q

    return WatchGuardTask.objects.filter(in_attesa=0, riuscite__gt=0).filter(
        Q(verifica_il__isnull=True) | Q(ultimo_job_il__gt=F("verifica_il")))


def verifica_task(now=None, *, client=None, software_gia: dict | None = None) -> dict | None:
    """Dopo la fine di un task: patch e software riletti da WatchGuard, così le CVE si ricalcolano subito.

    La lettura del software accoda il ricalcolo degli impatti CVE (``_dopo_import``), che aggiorna gli
    alert e prova la chiusura con prove (``cve_impatto_risolto``): le regole restano quelle, cambia solo
    quando arrivano i dati. Una lettura per giro al massimo; ``software_gia`` = software già letto nel
    giro completo. Il risultato resta sul task (``verifica``) ed è la sua evidenza in pagina.
    """
    now = now or timezone.now()
    tasks = list(task_da_verificare())
    if not tasks:
        return None
    esito: dict
    recenti = [t for t in tasks if t.ultimo_job_il and t.ultimo_job_il >= now - timedelta(days=VERIFICA_GIORNI)]
    if not recenti:
        esito = {"stato": "saltata", "motivo": f"task concluso da più di {VERIFICA_GIORNI} giorni: vale la lettura completa"}
    elif not soc_settings.value("watchguard.api.software"):
        esito = {"stato": "saltata", "motivo": "lettura del software spenta (interruttore «Software dei PC»)"}
    elif software_gia is not None:
        esito = {"stato": "fatta", "software": software_gia, "motivo": "software letto nel giro completo"}
    else:
        ultima = (SoftwareInventoryImport.objects.filter(source_kind=SoftwareSourceKind.WATCHGUARD, original_name=NOME_IMPORT)
                  .order_by("-created_at").values_list("created_at", flat=True).first())
        if ultima and ultima >= max(t.ultimo_job_il for t in recenti) and ultima >= now - timedelta(minutes=50):
            esito = {"stato": "fatta", "motivo": f"software già riletto alle {timezone.localtime(ultima):%H:%M}"}
        else:
            try:
                esito = {"stato": "fatta", "patch": sincronizza_patch(now, client=client),
                         "software": sincronizza_software(client=client)}
            except WatchGuardError as exc:
                esito = {"stato": "errore", "motivo": str(exc)[:300]}
    WatchGuardTask.objects.filter(pk__in=[t.pk for t in tasks]).update(verifica_il=now, verifica=esito)
    return {**esito, "task": len(tasks)}


def run_task() -> dict:
    """Giro orario solo dei task di installazione (interruttore delle patch): esiti vicini a quando si lanciano."""
    if not soc_settings.value("watchguard.api.patch"):
        return {"attivo": False}
    if not configurato():
        return {"ok": False, "motivo": "credenziali API WatchGuard non configurate"}
    try:
        client = Client()
    except WatchGuardError as exc:
        return {"ok": False, "motivo": str(exc)[:300]}
    try:
        out = {"ok": True, "task": sincronizza_task(client=client)}
        verifica = verifica_task(client=client)
        if verifica is not None:
            out["verifica"] = verifica
            out["ok"] = verifica["stato"] != "errore"
        return out
    except WatchGuardError as exc:
        logger.warning("WatchGuard API task: %s", exc)
        return {"ok": False, "motivo": str(exc)[:300]}
    finally:
        client.close()


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
    campi = ("host", "nome", "cve", "disponibilita", "esito", "criticita", "rilasciata_il", "kb", "presente")
    for p in qs.only(*campi):
        for c in p.cve_lista:
            if c in ids:
                out.setdefault((c, p.host), p)
    if out:
        # la patch che corregge la CVE può essere già compresa in una più recente (anche senza CVE, es. fuori ciclo)
        from security.services.patch_kb import comprese

        incluse = comprese(WatchGuardPatch.objects.filter(presente=True, host__in=list({h for _, h in out})[:500]).only(*campi))
        for p in out.values():
            p.compresa = incluse.get(p.pk)
    return out


CVE_STATI = {"corretta": ("Corretta", "low"), "vulnerabile": ("Ancora vulnerabile", "high"),
             "da_verificare": ("Da verificare", "medium"), "fuori": ("Non nel calcolo del SOC", "muted")}


def evidenza_cve(task, esiti) -> dict:
    """Per ogni esito (PC, patch) del task: le CVE che la patch corregge e il loro stato nel calcolo del SOC.

    «Corretta» = l'inventario ha visto il programma aggiornato o disinstallato (``SecurityCveRisoluzione``) dopo l'inizio del task; «Ancora
    vulnerabile» / «Da verificare» = impatto aperto oggi; «Non nel calcolo del SOC» = la CVE non risulta
    sul PC (programma non mappato o versione mai vista vulnerabile). Mette ``e.cve`` su ogni esito.
    """
    from security.models import SecurityCveImpact, SecurityCveRisoluzione

    hosts = sorted({e.host for e in esiti})[:500]
    nomi = sorted({e.patch_nome for e in esiti if e.patch_nome})[:500]
    cve_di: dict = {}
    for host, nome, cve in WatchGuardPatch.objects.filter(host__in=hosts, nome__in=nomi).exclude(cve="").values_list("host", "nome", "cve"):
        cve_di[(host, nome)] = [c for c in cve.split("|") if c]
    tutte = sorted({c for v in cve_di.values() for c in v})[:2000]
    inizio = min((e.job_il for e in esiti if e.job_il), default=task.creato_il or task.ultimo_job_il or timezone.now())
    aperti = {(c, h): o for c, h, o in SecurityCveImpact.objects.filter(
        cve__cve_id__in=tutte, host__in=hosts, outcome__in=(SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY),
    ).values_list("cve__cve_id", "host", "outcome")}
    corrette = set(SecurityCveRisoluzione.objects.filter(
        cve__cve_id__in=tutte, host__in=hosts, risolta_il__gte=inizio - timedelta(days=1),
        come__in=SecurityCveRisoluzione.CORREZIONI,  # aggiornato o disinstallato: «PC assente» non è una correzione
    ).values_list("cve__cve_id", "host"))
    conteggi = dict.fromkeys(CVE_STATI, 0)
    for e in esiti:
        e.cve = []
        for c in cve_di.get((e.host, e.patch_nome), []):
            if (c, e.host) in aperti:
                stato = "vulnerabile" if aperti[(c, e.host)] == SecurityCveImpact.IMPACTS else "da_verificare"
            elif (c, e.host) in corrette:
                stato = "corretta"
            else:
                stato = "fuori"
            conteggi[stato] += 1
            e.cve.append({"id": c, "stato": stato, "label": CVE_STATI[stato][0], "classe": CVE_STATI[stato][1]})
        e.cve.sort(key=lambda x: (list(CVE_STATI).index(x["stato"]) if x["stato"] != "corretta" else -1, x["id"]))
    return {"conteggi": conteggi, "totale": sum(conteggi.values()),
            "stati": [(k, v[0], v[1], conteggi[k]) for k, v in CVE_STATI.items()]}


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
    from security.services.patch_kb import sincronizza_msrc

    attivi["msrc"] = attivi["patch"] and soc_settings.value("watchguard.api.msrc")
    try:
        client = Client()  # una sessione e un token per tutto il giro
    except WatchGuardError as exc:
        return {"ok": False, "motivo": str(exc)[:300]}
    passi = (("dispositivi", lambda: sincronizza_dispositivi(now, client=client)),
             ("software", lambda: sincronizza_software(client=client)),
             ("patch", lambda: sincronizza_patch(now, client=client)),
             ("task", lambda: sincronizza_task(now, client=client)),
             ("msrc", lambda: sincronizza_msrc(now)))
    try:
        for nome, passo in passi:
            if not attivi["patch" if nome == "task" else nome]:
                continue
            try:
                out[nome] = passo()
            except WatchGuardError as exc:
                logger.warning("WatchGuard API %s: %s", nome, exc)
                out[nome] = {"errore": str(exc)[:300]}
                out["ok"] = False
            except Exception as exc:  # noqa: BLE001 - una parte fallita non blocca le altre
                logger.exception("WatchGuard API %s non riuscita", nome)
                out[nome] = {"errore": f"{type(exc).__name__}: {exc}"[:300]}
                out["ok"] = False
        if attivi["patch"] and "errore" not in (out.get("task") or {}):
            software = out.get("software")
            gia = software if attivi["software"] and isinstance(software, dict) and "errore" not in software else None
            try:
                verifica = verifica_task(now, client=client, software_gia=gia)
                if verifica is not None:
                    out["verifica"] = verifica
            except Exception as exc:  # noqa: BLE001 - la verifica è un di più: il giro resta valido
                logger.exception("WatchGuard API: verifica dei task finiti non riuscita")
                out["verifica"] = {"errore": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        client.close()
    return out
