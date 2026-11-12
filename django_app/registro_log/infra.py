"""ESXi / vCenter e iLO / iDRAC in sola lettura: com'è messa l'infrastruttura, adesso.

Lettura ``registro_infra`` (ogni ora). Per ogni apparato si tiene solo l'ultima
fotografia (``ApparatoInfra.stato``) e l'elenco dei problemi trovati: nessuno storico,
nessun peso sul database. Le versioni (ESXi, vCenter, firmware dei controller) entrano
nell'inventario software del SOC, così passano dal calcolo delle CVE come il software
dei PC. Gli accessi a questi apparati arrivano invece dal syslog, nell'archivio.

Utente consigliato: ruolo «Sola lettura» su vCenter/ESXi, ruolo «ReadOnly» (o «Login»)
sul controller iLO/iDRAC. Password cifrate nel database (``security.services.secret_box``).
"""
from __future__ import annotations

import logging
import ssl
import time
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

TIMEOUT = 20
# Un giro schedulato deve stare sotto il timeout del worker (120 s): gli apparati che non
# entrano nel budget si leggono al giro dopo, partendo da quelli letti da più tempo.
BUDGET_GIRO_SECONDI = 90
BUDGET_APPARATO_SECONDI = 40
MINIMO_PER_APPARATO_SECONDI = 10
SNAPSHOT_VECCHIO_GIORNI = 3
DATASTORE_LIBERO_MIN_PCT = 15
SOURCE_KIND = "registro_infra"


SCOPO_CIFRATURA = "registro_log.infra"


def cifra(password: str) -> str:
    from security.services.secret_box import encrypt

    return encrypt(password, SCOPO_CIFRATURA)


def decifra(valore: str) -> str:
    from security.services.secret_box import decrypt

    return decrypt(valore, SCOPO_CIFRATURA)


def _problema(tono: str, testo: str) -> dict:
    return {"tono": tono, "testo": testo}


class TempoScaduto(RuntimeError):
    """Il tempo concesso alla lettura dell'apparato è finito."""


def _restante(scadenza: float | None) -> float:
    if scadenza is None:
        return float(TIMEOUT)
    resta = scadenza - time.monotonic()
    if resta <= 0:
        raise TempoScaduto("tempo concesso alla lettura esaurito: si riprova al prossimo giro.")
    return resta


# ── VMware (pyvmomi) ─────────────────────────────────────────────────────────


def leggi_vsphere(app, scadenza: float | None = None) -> tuple[dict, list[dict]]:
    try:
        from pyVim.connect import Disconnect, SmartConnect
        from pyVmomi import vim
    except ImportError as exc:  # pragma: no cover - dipende dall'installazione
        raise RuntimeError("Manca la libreria pyvmomi: pip install -r requirements.txt nel venv del portale.") from exc
    ctx = ssl.create_default_context()
    if not app.verifica_certificato:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    # ``httpConnectionTimeout`` è il timeout di ogni richiesta SOAP (pyvmomi 8);
    # ``connectionPoolTimeout`` riguarda solo le connessioni inattive del pool.
    attesa = max(1, int(min(TIMEOUT, _restante(scadenza))))
    try:
        si = SmartConnect(host=app.indirizzo, user=app.utente, pwd=decifra(app.password_cifrata), port=app.porta,
                          sslContext=ctx, httpConnectionTimeout=attesa, connectionPoolTimeout=TIMEOUT)
    except TimeoutError as exc:  # socket.timeout è un alias di TimeoutError
        raise RuntimeError(f"{app.indirizzo}:{app.porta}: nessuna risposta entro {attesa} s (apparato spento, "
                           "indirizzo o porta errati, firewall).") from exc
    except ssl.SSLError as exc:
        raise RuntimeError(f"{app.indirizzo}:{app.porta}: errore del certificato o della connessione TLS ({exc}). "
                           "Con un certificato autofirmato togliere «Verifica certificato».") from exc
    except ConnectionError as exc:
        raise RuntimeError(f"{app.indirizzo}:{app.porta}: connessione non riuscita ({exc.__class__.__name__}).") from exc
    try:
        content = si.RetrieveContent()
        about = content.about
        stato: dict = {"prodotto": about.fullName, "versione": about.version, "build": about.build,
                       "tipo": "vCenter" if about.apiType == "VirtualCenter" else "ESXi", "host": [], "datastore": [],
                       "vm": 0, "vm_accese": 0, "snapshot_vecchi": []}
        problemi: list[dict] = []

        def oggetti(tipo):
            view = content.viewManager.CreateContainerView(content.rootFolder, [tipo], True)
            try:
                return list(view.view)
            finally:
                view.Destroy()

        for h in oggetti(vim.HostSystem):
            _restante(scadenza)
            prodotto = h.config.product if h.config else None
            servizi = {s.key: s.running for s in (h.configManager.serviceSystem.serviceInfo.service if h.configManager.serviceSystem else [])}
            ntp = list(h.config.dateTimeInfo.ntpConfig.server or []) if h.config and h.config.dateTimeInfo else []
            lockdown = str(getattr(h.config, "lockdownMode", "") or "") if h.config else ""
            riga = {
                "nome": h.name, "versione": getattr(prodotto, "version", ""), "build": getattr(prodotto, "build", ""),
                "connessione": str(h.runtime.connectionState), "manutenzione": bool(h.runtime.inMaintenanceMode),
                "stato": str(h.summary.overallStatus), "ssh": bool(servizi.get("TSM-SSH")), "shell": bool(servizi.get("TSM")),
                "ntp": ntp, "lockdown": lockdown,
            }
            stato["host"].append(riga)
            if riga["connessione"] != "connected":
                problemi.append(_problema("critical", f"{h.name}: host non connesso ({riga['connessione']})."))
            if riga["stato"] in ("red", "yellow"):
                problemi.append(_problema("critical" if riga["stato"] == "red" else "warning",
                                          f"{h.name}: allarmi attivi sull'host (stato {'rosso' if riga['stato'] == 'red' else 'giallo'})."))
            if riga["ssh"]:
                problemi.append(_problema("warning", f"{h.name}: SSH acceso. Tenerlo spento quando non serve."))
            if riga["shell"]:
                problemi.append(_problema("warning", f"{h.name}: ESXi Shell accesa."))
            if not ntp:
                problemi.append(_problema("warning", f"{h.name}: nessun server NTP (orologio non sincronizzato, i log perdono valore)."))
            if stato["tipo"] == "vCenter" and lockdown in ("", "lockdownDisabled"):
                problemi.append(_problema("info", f"{h.name}: modalità lockdown disattivata (accesso diretto all'host senza vCenter)."))
        for d in oggetti(vim.Datastore):
            cap, libero = int(d.summary.capacity or 0), int(d.summary.freeSpace or 0)
            pct = round(libero * 100 / cap, 1) if cap else None
            stato["datastore"].append({"nome": d.name, "gb": round(cap / 1024 ** 3), "libero_pct": pct})
            if pct is not None and pct < DATASTORE_LIBERO_MIN_PCT:
                problemi.append(_problema("warning", f"Datastore {d.name}: solo il {pct}% libero."))
        limite = timezone.now() - timedelta(days=SNAPSHOT_VECCHIO_GIORNI)

        def snapshot(lista, vm_nome):
            for s in lista or []:
                if s.createTime and s.createTime < limite:
                    stato["snapshot_vecchi"].append({"vm": vm_nome, "nome": s.name, "del": s.createTime.date().isoformat()})
                snapshot(s.childSnapshotList, vm_nome)

        for vm in oggetti(vim.VirtualMachine):
            _restante(scadenza)
            stato["vm"] += 1
            if str(vm.runtime.powerState) == "poweredOn":
                stato["vm_accese"] += 1
            if vm.snapshot:
                snapshot(vm.snapshot.rootSnapshotList, vm.name)
        if stato["snapshot_vecchi"]:
            problemi.append(_problema("warning", f"{len(stato['snapshot_vecchi'])} snapshot più vecchi di {SNAPSHOT_VECCHIO_GIORNI} "
                                      "giorni: rallentano le VM e riempiono i datastore."))
        return stato, problemi
    finally:
        Disconnect(si)


# ── Redfish (iLO, iDRAC e altri BMC) ─────────────────────────────────────────


def _chi_risponde(resp) -> str:
    """Se a rispondere non è il controller (un proxy, IIS, un altro servizio), lo dice: Redfish risponde in JSON."""
    headers = getattr(resp, "headers", None)
    if not hasattr(headers, "get"):
        return ""
    tipo = str(headers.get("Content-Type") or "")
    server = str(headers.get("Server") or "")[:60]
    if not tipo or "json" in tipo.lower():
        return ""
    return (" La risposta non arriva da Redfish"
            + (f" (server «{server}»)" if server else "")
            + ": a quell'indirizzo risponde un altro servizio o un proxy.")


def _errore_rete(exc, base: str) -> RuntimeError:
    """Messaggio leggibile per gli errori di rete verso il controller, con l'indirizzo contattato."""
    import requests

    if isinstance(exc, requests.exceptions.ProxyError):
        return RuntimeError(f"{base}: la richiesta è passata da un proxy che l'ha rifiutata. Il controller è in rete "
                            "interna e va raggiunto direttamente, senza proxy.")
    if isinstance(exc, requests.exceptions.SSLError):
        return RuntimeError(f"{base}: errore del certificato o della connessione TLS. "
                            "Con un certificato autofirmato togliere «Verifica certificato».")
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return RuntimeError(f"{base}: nessuna risposta alla connessione (apparato spento, indirizzo o porta errati, firewall).")
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return RuntimeError(f"{base}: il controller ha accettato la connessione ma non ha risposto in tempo.")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return RuntimeError(f"{base}: connessione non riuscita (rifiutata o interrotta).")
    return RuntimeError(f"{base}: {exc.__class__.__name__}: {exc}")


def leggi_redfish(app, scadenza: float | None = None) -> tuple[dict, list[dict]]:
    import requests

    base = f"https://{app.indirizzo}:{app.porta}"
    sess = requests.Session()
    # Il controller è in rete interna: niente HTTPS_PROXY/HTTP_PROXY dell'ambiente.
    sess.trust_env = False
    sess.auth = (app.utente, decifra(app.password_cifrata))
    sess.verify = bool(app.verifica_certificato)
    sess.headers["Accept"] = "application/json"
    if not app.verifica_certificato:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(percorso):
        attesa = min(TIMEOUT, _restante(scadenza))
        try:
            r = sess.get(base + percorso, timeout=attesa)
        except requests.exceptions.RequestException as exc:
            raise _errore_rete(exc, base) from exc
        if r.status_code == 401:
            raise RuntimeError(f"Utente o password rifiutati dal controller ({base}).{_chi_risponde(r)}")
        if r.status_code >= 400:
            raise RuntimeError(f"{base}{percorso}: il controller ha risposto {r.status_code}.{_chi_risponde(r)}")
        try:
            return r.json()
        except ValueError as exc:
            raise RuntimeError(f"{base}{percorso}: risposta non JSON.{_chi_risponde(r)}") from exc

    radice = get("/redfish/v1/")
    stato: dict = {"produttore": radice.get("Vendor") or "", "prodotto": radice.get("Product") or "", "sistemi": []}
    problemi: list[dict] = []
    manager = {}
    membri = (get("/redfish/v1/Managers").get("Members") or [])
    if membri:
        manager = get(membri[0]["@odata.id"])
    stato["controller"] = manager.get("Model") or stato["prodotto"]
    stato["firmware"] = manager.get("FirmwareVersion") or ""
    for m in (get("/redfish/v1/Systems").get("Members") or [])[:4]:
        s = get(m["@odata.id"])
        salute = (s.get("Status") or {})
        riga = {
            "modello": s.get("Model") or "", "seriale": s.get("SerialNumber") or "", "bios": s.get("BiosVersion") or "",
            "alimentazione": s.get("PowerState") or "", "salute": salute.get("HealthRollup") or salute.get("Health") or "",
            "nome": s.get("HostName") or s.get("Name") or "",
        }
        stato["sistemi"].append(riga)
        if riga["salute"] and riga["salute"] != "OK":
            problemi.append(_problema("critical" if riga["salute"] == "Critical" else "warning",
                                      f"{riga['modello'] or app.nome}: salute dell'hardware «{riga['salute']}» (dischi, alimentatori, "
                                      "ventole o memoria: vedere il registro del controller)."))
        if riga["alimentazione"] and riga["alimentazione"] != "On":
            problemi.append(_problema("info", f"{riga['modello'] or app.nome}: server spento."))
    return stato, problemi


# ── Inventario software del SOC (per le CVE) ─────────────────────────────────


def _prodotti(app) -> list[tuple[str, str, str]]:
    """(produttore, prodotto, versione) da mandare all'inventario."""
    s = app.stato or {}
    out = []
    if app.tipo == app.TIPO_VSPHERE:
        if s.get("tipo") == "vCenter" and s.get("versione"):
            out.append(("VMware", "vCenter Server", f"{s['versione']} build {s.get('build', '')}".strip()))
        for h in s.get("host") or []:
            if h.get("versione"):
                out.append(("VMware", "ESXi", f"{h['versione']} build {h.get('build', '')}".strip()))
    elif s.get("firmware"):
        produttore = s.get("produttore") or ""
        out.append((produttore, f"{s.get('controller') or s.get('prodotto') or 'BMC'} firmware", s["firmware"]))
    return out


def _sincronizza_inventario(app) -> None:
    from security.models import SoftwareInstallation
    from security.services.software_inventory import installation_key, normalize_product, normalize_vendor
    from security.services.versioning import normalize as normalize_version

    host = str(app.indirizzo or "").strip().lower()
    now, oggi = timezone.now(), timezone.localdate()
    tenute = []
    with transaction.atomic():
        for produttore, prodotto, versione in _prodotti(app):
            vendor = normalize_vendor(produttore)
            product = normalize_product(prodotto, version=versione)
            key = installation_key(SOURCE_KIND, host, vendor, product, versione)
            riga, creata = SoftwareInstallation.objects.get_or_create(dedup_key=key, defaults={
                "source_kind": SOURCE_KIND, "host": host, "host_display": app.nome[:255],
                "vendor_raw": produttore[:255], "product_raw": prodotto[:255], "vendor": vendor, "product": product,
                "version_raw": versione[:120], "version_norm": normalize_version(versione), "detected_at": now,
                "seen_at": now, "last_seen_at": now, "last_inventory_date": oggi, "still_detected": True,
            })
            if not creata:
                SoftwareInstallation.objects.filter(pk=riga.pk).update(last_seen_at=now, last_inventory_date=oggi,
                                                                       still_detected=True, host_display=app.nome[:255])
            tenute.append(riga.pk)
        SoftwareInstallation.objects.filter(source_kind=SOURCE_KIND, host=host, still_detected=True).exclude(
            pk__in=tenute).update(still_detected=False)


def leggi(app, scadenza: float | None = None) -> None:
    """Legge un apparato e salva la fotografia. Gli errori finiscono in ``errore``, non risalgono.

    ``scadenza`` (istante di ``time.monotonic()``): oltre quel momento la lettura si ferma;
    di serie ``BUDGET_APPARATO_SECONDI`` da adesso.
    """
    from .models import ApparatoInfra

    ora = timezone.now()
    if scadenza is None:
        scadenza = time.monotonic() + BUDGET_APPARATO_SECONDI
    try:
        lettore = leggi_vsphere if app.tipo == ApparatoInfra.TIPO_VSPHERE else leggi_redfish
        stato, problemi = lettore(app, scadenza=scadenza)
    except Exception as exc:  # noqa: BLE001 - errore dell'apparato: si mostra nella pagina
        logger.warning("Registro accessi: lettura di %s non riuscita: %s", app.nome, exc)
        ApparatoInfra.objects.filter(pk=app.pk).update(errore=f"{type(exc).__name__}: {exc}"[:500], letto_il=ora)
        return
    ApparatoInfra.objects.filter(pk=app.pk).update(stato=stato, problemi=problemi, errore="", letto_il=ora)
    app.stato, app.problemi = stato, problemi
    try:
        _sincronizza_inventario(app)
    except Exception as exc:  # noqa: BLE001 - l'inventario è un di più: la fotografia resta
        logger.warning("Registro accessi: inventario di %s non aggiornato: %s", app.nome, exc)


def aggiorna() -> dict:
    from .models import ApparatoInfra

    # Prima i mai letti e quelli letti da più tempo: chi resta fuori dal budget passa avanti al giro dopo.
    apparati = list(ApparatoInfra.objects.filter(attivo=True).order_by(F("letto_il").asc(nulls_first=True), "pk"))
    if not apparati:
        return {"attivo": False, "skipped": "Nessun apparato ESXi, vCenter, iLO o iDRAC configurato."}
    fine_giro = time.monotonic() + BUDGET_GIRO_SECONDI
    letti, rimandati = [], []
    for app in apparati:
        resta = fine_giro - time.monotonic()
        if resta < MINIMO_PER_APPARATO_SECONDI:
            rimandati.append(app.nome)
            continue
        leggi(app, scadenza=time.monotonic() + min(BUDGET_APPARATO_SECONDI, resta))
        letti.append(app.pk)
    errori = list(ApparatoInfra.objects.filter(pk__in=letti).exclude(errore="").values_list("nome", "errore"))
    esito = {"apparati": len(apparati), "letti": len(letti),
             "problemi": sum(len(a.problemi or []) for a in ApparatoInfra.objects.filter(attivo=True)),
             **({"errori": [f"{n}: {e}" for n, e in errori]} if errori else {})}
    if rimandati:
        esito["rimandati"] = [f"{n}: lettura rimandata al prossimo giro (tempo del giro esaurito)." for n in rimandati]
    return esito
