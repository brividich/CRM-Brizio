"""Backup letti direttamente da Veeam Backup & Replication (REST API, v12 o successive).

Ogni giro del ``security_cycle`` (15 minuti), se acceso da ``/soc/impostazioni/``:

1. accede all'API REST del server Veeam (``/api/oauth2/token``, utente di sola lettura);
2. legge le sessioni di backup create dopo l'ultimo giro riuscito (con 48 ore di
   sovrapposizione: un job lungo finisce dopo essere iniziato) e, per ogni sessione
   conclusa e non ancora salvata, l'esito di ogni macchina (``taskSessions``);
3. salva ogni sessione come ``BackupJobRecord`` + evento ``backup_job``, con lo stesso
   payload del parser delle mail Veeam: Centro backup, regole, rientri e KPI restano
   identici. Una sessione già arrivata per mail (stesso job, stesso orario di inizio
   entro due minuti) non viene ripetuta, e viceversa;
4. legge lo spazio dei repository e apre un alert per ogni repository sotto la soglia di
   spazio libero (chiuso da solo quando lo spazio torna sopra).

Credenziali dal portale: ``/soc/impostazioni/`` › «Credenziali API Veeam» (indirizzo, utente,
password, revisione API, certificato della CA), cifrate a riposo in ``SecurityCenterSetting``
(``secret_box``) come quelle di WatchGuard. Se non ci sono, valgono ancora le vecchie variabili
del ``.env`` (``VEEAM_API_URL``, ``VEEAM_API_USERNAME``, ``VEEAM_API_PASSWORD``,
``VEEAM_API_VERSION``, ``VEEAM_API_CA_BUNDLE``). Senza credenziali il giro registra l'errore e
non fa altro.
"""
from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from datetime import timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.models import BackupJobRecord, SecurityCenterSetting, SecurityEventRecord, SecuritySource, Severity, SourceType
from security.services import secret_box, soc_settings
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

SOURCE_NAME = "Veeam Backup & Replication (API)"
EVENT_REPOSITORY = "backup_repository_space"
DEFAULT_API_VERSION = "1.1-rev0"
TIMEOUT_SECONDS = 30
PAGE_SIZE = 200
MAX_PAGES = 10
MAX_NEW_SESSIONS = 200  # per giro: il primo giro su 30 giorni si completa nei giri successivi
OVERLAP = timedelta(hours=48)
SAME_RUN_TOLERANCE = timedelta(minutes=2)
STATE_CATEGORY = "veeam"
LAST_RUN_KEY = "veeam.ultimo_giro"
LAST_OK_KEY = "veeam.ultimo_ok"
REPOSITORIES_KEY = "veeam.repository"

# Esito della sessione Veeam → stato del Centro backup (come il parser delle mail).
RESULT_MAP = {"success": "completed", "warning": "warning", "failed": "failed"}
FINISHED_STATES = {"stopped"}


class VeeamError(RuntimeError):
    pass


# --- Credenziali (dal portale, cifrate) -----------------------------------------------------

SETTING = "veeam.api.credenziali"
PURPOSE = "veeam-api"
CAMPI = ("url", "username", "password", "version", "ca_pem")


def _dal_portale() -> dict:
    setting = SecurityCenterSetting.objects.filter(key=SETTING).first()
    testo = secret_box.decrypt(setting.value, PURPOSE) if setting and setting.value else ""
    try:
        dati = json.loads(testo) if testo else {}
    except ValueError:
        dati = {}
    return {campo: str(dati.get(campo) or "").strip() for campo in CAMPI}


def credenziali() -> dict:
    """Credenziali in uso: quelle salvate nel portale, altrimenti quelle del .env (compatibilità)."""
    dati = _dal_portale()
    if dati["url"]:
        return {**dati, "ca_path": "", "fonte": "portale"}
    url = str(getattr(settings, "VEEAM_API_URL", "") or "").strip()
    return {
        "url": url,
        "username": str(getattr(settings, "VEEAM_API_USERNAME", "") or "").strip(),
        "password": str(getattr(settings, "VEEAM_API_PASSWORD", "") or ""),
        "version": str(getattr(settings, "VEEAM_API_VERSION", "") or "").strip(),
        "ca_pem": "",
        "ca_path": str(getattr(settings, "VEEAM_API_CA_BUNDLE", "") or "").strip(),
        "fonte": "env" if url else "",
    }


def _ca_file(pem: str) -> str:
    """Il certificato della CA incollato nel portale, su un file temporaneo (``requests`` vuole un percorso)."""
    pem = pem.strip() + "\n"
    path =Path(tempfile.gettempdir()) / f"pn_veeam_ca_{hashlib.sha256(pem.encode()).hexdigest()[:16]}.pem"
    if not path.exists():
        path.write_text(pem, encoding="ascii")
    return str(path)


def _config() -> dict:
    cfg = credenziali()
    verify = _ca_file(cfg["ca_pem"]) if cfg["ca_pem"] else (cfg["ca_path"] or True)
    return {
        "url": cfg["url"].rstrip("/"),
        "username": cfg["username"],
        "password": cfg["password"],
        "version": cfg["version"] or DEFAULT_API_VERSION,
        "verify": verify,
    }


def configured() -> bool:
    cfg = credenziali()
    return bool(cfg["url"] and cfg["username"] and cfg["password"])


def riepilogo() -> dict:
    """Quello che la pagina Impostazioni può mostrare: mai la password in chiaro."""
    cfg = credenziali()
    return {"url": cfg["url"], "username": cfg["username"], "version": cfg["version"], "password": bool(cfg["password"]),
            "ca": bool(cfg["ca_pem"] or cfg["ca_path"]), "fonte": cfg["fonte"],
            "configurato": bool(cfg["url"] and cfg["username"] and cfg["password"])}


def valida(dati: dict) -> list[str]:
    errori = []
    if not dati["url"].lower().startswith("https://") or len(dati["url"]) < 12:
        errori.append("Indirizzo non valido: è https://<server Veeam>:9419 (l'API di Veeam risponde solo in HTTPS).")
    if not dati["username"]:
        errori.append("Manca l'utente (es. DOMINIO\\utente con il solo ruolo «Veeam Backup Viewer»).")
    if not dati["password"]:
        errori.append("Manca la password.")
    if dati["ca_pem"] and "BEGIN CERTIFICATE" not in dati["ca_pem"]:
        errori.append("Il certificato della CA va incollato in formato PEM (-----BEGIN CERTIFICATE----- …).")
    return errori


def salva_credenziali(nuovi: dict, actor=None, togli_ca: bool = False) -> list[str]:
    """Salva le credenziali; password e certificato vuoti = si tengono quelli già salvati."""
    from security.services.configuration import audit_config_change

    attuali = _dal_portale()
    dati = {campo: str(nuovi.get(campo) or "").strip()[:8000 if campo == "ca_pem" else 300] for campo in CAMPI}
    dati["url"] = dati["url"].rstrip("/")
    dati["password"] = dati["password"] or attuali["password"]
    dati["ca_pem"] = "" if togli_ca else (dati["ca_pem"] or attuali["ca_pem"])
    errori = valida(dati)
    if errori:
        return errori
    setting, _ = SecurityCenterSetting.objects.get_or_create(
        key=SETTING, defaults={"category": "integrazioni", "is_secret": True,
                               "description": "Credenziali API Veeam Backup & Replication (cifrate)"})
    setting.value = secret_box.encrypt(json.dumps(dati), PURPOSE)
    setting.is_secret = True
    setting.updated_by = actor if getattr(actor, "pk", None) else None
    setting.save()
    cambiati = [c for c in CAMPI if dati[c] != attuali[c]]
    audit_config_change(actor, "update", setting, field_name="value", old_value="***" if any(attuali.values()) else "",
                        new_value="campi cambiati: " + (", ".join(cambiati) or "nessuno"))
    return []


def cancella_credenziali(actor=None) -> None:
    from security.services.configuration import audit_config_change

    setting = SecurityCenterSetting.objects.filter(key=SETTING).first()
    if setting is None or not setting.value:
        return
    setting.value = ""
    setting.save()
    audit_config_change(actor, "update", setting, field_name="value", old_value="***", new_value="")


def _check_config(cfg: dict) -> None:
    if not (cfg["url"] and cfg["username"] and cfg["password"]):
        raise VeeamError("Credenziali API Veeam mancanti: inseriscile in Impostazioni › «Credenziali API Veeam».")
    if not cfg["url"].lower().startswith("https://"):
        raise VeeamError("L'indirizzo di Veeam deve iniziare con https:// (l'API di Veeam risponde solo in HTTPS, porta 9419).")


class VeeamClient:
    """Sessione autenticata verso l'API REST di Veeam (solo letture)."""

    def __init__(self, cfg: dict | None = None):
        import requests

        self.cfg = cfg or _config()
        _check_config(self.cfg)
        self.http = requests.Session()
        self.http.verify = self.cfg["verify"]
        self.http.headers.update({"x-api-version": self.cfg["version"], "Accept": "application/json"})
        self._login()

    def _login(self) -> None:
        import requests

        try:
            resp = self.http.post(
                f"{self.cfg['url']}/api/oauth2/token", timeout=TIMEOUT_SECONDS,
                data={"grant_type": "password", "username": self.cfg["username"], "password": self.cfg["password"]},
            )
        except requests.exceptions.SSLError as exc:
            raise VeeamError("Certificato del server Veeam non attendibile: incolla il certificato della CA nelle credenziali API Veeam.") from exc
        except requests.exceptions.RequestException as exc:
            raise VeeamError(f"Server Veeam non raggiungibile ({type(exc).__name__}): controlla indirizzo e porta 9419.") from exc
        if resp.status_code in (400, 401, 403):
            raise VeeamError(f"Veeam ha rifiutato l'accesso ({resp.status_code}): controlla utente e password dell'API.")
        if resp.status_code >= 400:
            raise VeeamError(f"Veeam ha risposto {resp.status_code} all'accesso (versione API {self.cfg['version']}).")
        token = (resp.json() or {}).get("access_token")
        if not token:
            raise VeeamError("Veeam non ha restituito il token di accesso.")
        self.http.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, params: dict | None = None) -> dict:
        import requests

        try:
            resp = self.http.get(f"{self.cfg['url']}{path}", params=params, timeout=TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as exc:
            raise VeeamError(f"Lettura da Veeam non riuscita ({type(exc).__name__}) su {path}.") from exc
        if resp.status_code in (401, 403):
            raise VeeamError(f"Veeam ha risposto {resp.status_code} su {path}: l'utente dell'API non ha i permessi di lettura.")
        if resp.status_code >= 400:
            raise VeeamError(f"Veeam ha risposto {resp.status_code} su {path}.")
        return resp.json() or {}

    def get_all(self, path: str, params: dict | None = None) -> list[dict]:
        out: list[dict] = []
        params = dict(params or {})
        for page in range(MAX_PAGES):
            data = self.get(path, {**params, "skip": page * PAGE_SIZE, "limit": PAGE_SIZE})
            rows = [row for row in data.get("data") or [] if isinstance(row, dict)]
            out.extend(rows)
            total = (data.get("pagination") or {}).get("total")
            if len(rows) < PAGE_SIZE or (isinstance(total, int) and len(out) >= total):
                break
        return out

    def close(self) -> None:
        try:
            self.http.post(f"{self.cfg['url']}/api/oauth2/logout", timeout=TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - il token scade comunque da solo
            logger.debug("Veeam: logout non riuscito: %s", exc)


def veeam_source():
    source, _ = SecuritySource.objects.get_or_create(
        name=SOURCE_NAME, defaults={"source_type": SourceType.API, "vendor": "veeam"},
    )
    return source


# --- Sessioni di backup ------------------------------------------------------------------


def _dt(value) -> datetime | None:
    parsed = parse_datetime(str(value or "")) if value else None
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    # Al secondo, come gli orari delle mail: serve per riconoscere la stessa esecuzione.
    return parsed.replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    return timezone.localtime(value).isoformat() if value else None


def _hms(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _gb_text(size_bytes) -> str:
    try:
        return f"{float(size_bytes) / 1024 ** 3:.2f} GB"
    except (TypeError, ValueError):
        return ""


def is_backup_session(session: dict) -> bool:
    """Sessioni di backup (job, copie, agent): fuori manutenzioni, ripristini, infrastruttura."""
    kind = str(session.get("sessionType") or "").lower()
    return "backup" in kind and "restore" not in kind and "configuration" not in kind


def is_finished(session: dict) -> bool:
    return str(session.get("state") or "").lower() in FINISHED_STATES and bool(session.get("endTime"))


def _status(result: dict) -> str:
    result = result or {}
    if result.get("isCanceled"):
        return "warning"
    return RESULT_MAP.get(str(result.get("result") or "").lower(), "unknown")


def _task_object(task: dict) -> dict:
    """Riga ``objects`` come quella del parser delle mail (letta da ``backup_center.device_runs``)."""
    progress = task.get("progress") or {}
    start, end = _dt(task.get("creationTime")), _dt(task.get("endTime"))
    duration = progress.get("duration")
    if not duration and start and end:
        duration = _hms((end - start).total_seconds())
    return {
        "name": str(task.get("name") or "").strip()[:255],
        "status": _status(task.get("result") or {}),
        "start": _iso(start) or "",
        "end": _iso(end) or "",
        "size": _gb_text(progress.get("processedSize")),
        "read": _gb_text(progress.get("readSize")),
        "transferred": _gb_text(progress.get("transferredSize")),
        "duration": str(duration or ""),
        "details": str((task.get("result") or {}).get("message") or "")[:200],
    }


def session_payload(session: dict, tasks: list[dict]) -> dict:
    start, end = _dt(session.get("creationTime")), _dt(session.get("endTime"))
    result = session.get("result") or {}
    status = _status(result)
    objects = [row for row in (_task_object(t) for t in tasks) if row["name"]]
    transferred = sum(_gb_value(t, "transferredSize") for t in tasks) if tasks else None
    counts = {key: sum(1 for row in objects if row["status"] == key) for key in ("completed", "warning", "failed")}
    session_id = str(session.get("id") or "")
    return {
        "source": "veeam_api",
        "vendor": "veeam",
        "job_name": str(session.get("name") or "").strip()[:255] or "unknown",
        "status": status,
        "start_time": _iso(start),
        "end_time": _iso(end),
        "duration_seconds": int((end - start).total_seconds()) if start and end else None,
        "transferred_size_gb": round(transferred, 3) if transferred is not None else None,
        "objects_processed": len(objects),
        "objects_total": len(objects),
        "objects_ok": counts["completed"],
        "objects_warning": counts["warning"],
        "objects_error": counts["failed"],
        "objects": objects,
        "protected_items": counts["completed"] + counts["warning"],
        "device_name": "",
        "veeam_session_id": session_id,
        "veeam_job_id": str(session.get("jobId") or ""),
        "veeam_session_type": str(session.get("sessionType") or ""),
        "message": str(result.get("message") or "")[:300],
        "canceled": bool(result.get("isCanceled")),
        "dedup_hash": make_hash("veeam_api", session_id),
        "parse_warnings": [],
    }


def _gb_value(task: dict, key: str) -> float:
    try:
        return float((task.get("progress") or {}).get(key) or 0) / 1024 ** 3
    except (TypeError, ValueError):
        return 0.0


def same_run_exists(job_name: str, started_at: datetime | None, *, from_api: bool) -> bool:
    """Un'esecuzione Veeam dello stesso job e orario c'è già dall'altra strada (mail o API).

    Senza questo controllo, con API e mail accese insieme, ogni backup conterebbe due volte
    nei KPI. Niente ricerche dentro il JSON (lente e fragili su SQL Server): si filtra per job
    e orario, poi si guarda il payload in Python.
    """
    if not job_name or started_at is None:
        return False
    candidates = BackupJobRecord.objects.filter(
        job_name=job_name,
        started_at__gte=started_at - SAME_RUN_TOLERANCE,
        started_at__lte=started_at + SAME_RUN_TOLERANCE,
    ).values_list("payload", flat=True)
    for payload in candidates:
        payload = payload or {}
        if payload.get("vendor") != "veeam":
            continue
        if (payload.get("source") == "veeam_api") != from_api:
            return True
    return False


def record_sessions(client: VeeamClient, sessions: list[dict]) -> dict:
    from security.parsers.base import ParsedRecord
    from security.services.parser_engine import _persist_record

    source = veeam_source()
    saved = already = skipped_mail = 0
    for session in sessions:
        if saved >= MAX_NEW_SESSIONS:
            break
        if not (is_backup_session(session) and is_finished(session) and session.get("id")):
            continue
        dedup = make_hash(source.pk, make_hash("veeam_api", str(session["id"])))
        if BackupJobRecord.objects.filter(source=source, dedup_hash=dedup).exists():
            already += 1
            continue
        name = str(session.get("name") or "").strip()[:255]
        if same_run_exists(name, _dt(session.get("creationTime")), from_api=True):
            skipped_mail += 1
            continue
        tasks = client.get_all(f"/api/v1/sessions/{session['id']}/taskSessions")
        _persist_record(source, None, ParsedRecord(record_type="backup_job", payload=session_payload(session, tasks)))
        saved += 1
    return {"salvate": saved, "gia_presenti": already, "gia_da_mail": skipped_mail}


def fetch_sessions(client: VeeamClient, since: datetime) -> list[dict]:
    since_iso = since.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return client.get_all("/api/v1/sessions", {
        "createdAfterFilter": since_iso, "orderColumn": "CreationTime", "orderAsc": "true",
    })


# --- Repository ---------------------------------------------------------------------------


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def repository_rows(states: list[dict]) -> list[dict]:
    rows = []
    for item in states:
        capacity, free = _float(item.get("capacityGB")), _float(item.get("freeGB"))
        rows.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or "").strip()[:255] or "Repository",
            "host": str(item.get("hostName") or "")[:255],
            "path": str(item.get("path") or "")[:500],
            "type": str(item.get("type") or ""),
            "capacity_gb": round(capacity, 1) if capacity is not None else None,
            "free_gb": round(free, 1) if free is not None else None,
            "free_pct": round(100 * free / capacity, 1) if capacity and free is not None else None,
        })
    return sorted(rows, key=lambda r: (r["free_pct"] is None, r["free_pct"] if r["free_pct"] is not None else 0))


def record_repositories(rows: list[dict], threshold_pct: int) -> int:
    """Un evento per repository solo quando passa sotto la soglia o torna sopra."""
    source = veeam_source()
    created = 0
    for row in rows:
        if not row["id"] or row["free_pct"] is None:
            continue
        low = row["free_pct"] < threshold_pct
        dedup = make_hash(source.pk, EVENT_REPOSITORY, row["id"])
        prev = (SecurityEventRecord.objects.filter(source=source, event_type=EVENT_REPOSITORY, dedup_hash=dedup)
                .order_by("-occurred_at", "-id").values_list("payload", flat=True).first())
        if prev is None and not low:
            continue  # mai stato sotto soglia: nessun evento da registrare
        if prev is not None and bool(prev.get("sotto_soglia")) == low:
            continue
        payload = {**row, "soglia_pct": threshold_pct, "sotto_soglia": low, "repository": row["name"]}
        SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_REPOSITORY, severity=Severity.WARNING if low else Severity.INFO,
            occurred_at=timezone.now(), fingerprint=dedup, dedup_hash=dedup, payload=payload,
        )
        created += 1
    return created


# --- Giro ---------------------------------------------------------------------------------


def _save_state(key: str, value) -> None:
    # Stato tecnico del giro, non una scelta di configurazione: niente audit delle impostazioni.
    SecurityCenterSetting.objects.update_or_create(
        key=key,
        defaults={"value": value, "value_type": "json" if isinstance(value, (dict, list)) else "string",
                  "category": STATE_CATEGORY},
    )


def _get_state(key: str, default=None):
    from security.services.configuration import get_setting

    return get_setting(key, default)


def _since(now: datetime) -> datetime:
    last_ok = parse_datetime(str(_get_state(LAST_OK_KEY, "") or ""))
    if last_ok is None:
        return now - timedelta(days=soc_settings.value("veeam.primo_giro_giorni"))
    return last_ok - OVERLAP


def run(now: datetime | None = None) -> dict:
    """Giro completo. Non solleva: l'esito finisce in ``veeam.ultimo_giro``."""
    if not soc_settings.value("veeam.api.attivo"):
        return {"attivo": False}
    now = now or timezone.now()
    esito = {"attivo": True, "at": now.isoformat()}
    client = None
    try:
        client = VeeamClient()
        sessions = fetch_sessions(client, _since(now))
        esito.update({"ok": True, "sessioni_lette": len(sessions), **record_sessions(client, sessions)})
        rows = repository_rows(client.get_all("/api/v1/backupInfrastructure/repositories/states"))
        _save_state(REPOSITORIES_KEY, {"at": now.isoformat(), "rows": rows})
        esito["repository"] = len(rows)
        if soc_settings.value("veeam.repository.alert"):
            esito["eventi_repository"] = record_repositories(rows, soc_settings.value("veeam.repository.soglia_pct"))
        _save_state(LAST_OK_KEY, now.isoformat())
        if esito.get("salvate") or esito.get("eventi_repository"):
            from security.services.rule_engine import evaluate_security_rules

            evaluate_security_rules()
    except Exception as exc:  # noqa: BLE001 - il ciclo SOC prosegue con gli altri passi
        logger.warning("Veeam: giro non riuscito: %s", exc)
        esito.update({"ok": False, "errore": str(exc)[:300]})
    finally:
        if client is not None:
            client.close()
    _save_state(LAST_RUN_KEY, esito)
    return esito


def prova(hours: int = 24) -> dict:
    """Accesso + letture senza salvare nulla (comando ``veeam_api --prova``)."""
    client = VeeamClient()
    try:
        sessions = fetch_sessions(client, timezone.now() - timedelta(hours=hours))
        backup = [s for s in sessions if is_backup_session(s)]
        rows = repository_rows(client.get_all("/api/v1/backupInfrastructure/repositories/states"))
    finally:
        client.close()
    return {
        "sessioni": len(sessions),
        "sessioni_backup": len(backup),
        "concluse": sum(1 for s in backup if is_finished(s)),
        "job": sorted({str(s.get("name") or "") for s in backup}),
        "repository": rows,
    }


def last_run() -> dict:
    value = _get_state(LAST_RUN_KEY, {})
    return value if isinstance(value, dict) else {}


def panel() -> dict:
    """Riquadro «Lettura diretta da Veeam» della pagina Backup."""
    stored = _get_state(REPOSITORIES_KEY, {})
    stored = stored if isinstance(stored, dict) else {}
    threshold = soc_settings.value("veeam.repository.soglia_pct")
    rows = [{**row, "low": row.get("free_pct") is not None and row["free_pct"] < threshold}
            for row in stored.get("rows") or [] if isinstance(row, dict)]
    giro = last_run()
    return {
        "attivo": soc_settings.value("veeam.api.attivo"),
        "configurato": configured(),
        "ultimo_giro": giro,
        "ultimo_giro_at": parse_datetime(str(giro.get("at") or "")) if giro.get("at") else None,
        "repository": rows,
        "repository_at": parse_datetime(str(stored.get("at") or "")) if stored.get("at") else None,
        "soglia_pct": threshold,
    }
