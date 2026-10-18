"""Controlli non distruttivi del motore di backup, riusati da hub_backup_doctor e dal monitoraggio."""
from __future__ import annotations

import platform
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import host_manifest, status
from .config import BackupConfig

OK, WARN, CRIT, INFO = "ok", "warning", "critical", "info"
EXPECTED_TASKS = ("FULL", "LOG", "FILES", "HOST", "RETENTION")


def _check(name: str, level: str, message: str, **details) -> dict:
    return {"check": name, "level": level, "message": message, **({"details": details} if details else {})}


def _writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def _age_hours(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return (now - dt).total_seconds() / 3600


def freshness(cfg: BackupConfig, now: datetime | None = None) -> list[dict]:
    now = now or timezone.now()
    last = status.read(cfg).get("last", {})
    out = []
    full_age = _age_hours((last.get("full") or {}).get("last_ok_at"), now)
    if full_age is None:
        out.append(_check("backup_full", CRIT, "Nessun backup FULL riuscito registrato."))
    else:
        lvl = OK if full_age <= 26 else WARN if full_age <= 50 else CRIT
        out.append(_check("backup_full", lvl, f"Ultimo FULL riuscito {full_age:.1f} h fa.", age_hours=round(full_age, 1)))
    for kind, limit in (("files", 50), ("host", 24 * 8)):
        age = _age_hours((last.get(kind) or {}).get("last_ok_at"), now)
        if age is None:
            out.append(_check(f"backup_{kind}", WARN, f"Nessun backup {kind.upper()} riuscito registrato."))
        else:
            out.append(_check(f"backup_{kind}", OK if age <= limit else WARN, f"Ultimo {kind.upper()} {age:.1f} h fa."))
    log = last.get("log") or {}
    if log:
        age = _age_hours(log.get("last_ok_at"), now)
        local_hour = timezone.localtime(now).hour
        if log.get("status") == "failed" and "catena" in str(log.get("error", "")):
            out.append(_check("backup_log", CRIT, "Catena dei log interrotta: serve un nuovo FULL."))
        elif cfg.in_log_window(local_hour) and (age is None or age > 2):
            out.append(_check("backup_log", WARN, f"Nessun backup del log riuscito nelle ultime 2 ore ({age or 0:.1f} h)."))
        else:
            out.append(_check("backup_log", OK, "Backup del log regolare." if age is not None else "Log non ancora attivo."))
    return out


def scheduled_tasks(env: str) -> dict[str, bool]:
    if platform.system() != "Windows":
        return {}
    names = [f"PortaleNovicrom-Backup-{env.upper()}-{k}" for k in EXPECTED_TASKS]
    script = "; ".join(
        f"if (Get-ScheduledTask -TaskName '{n}' -ErrorAction SilentlyContinue) {{ '{n}=1' }} else {{ '{n}=0' }}"
        for n in names
    )
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    found = {}
    for line in (p.stdout or "").splitlines():
        if "=" in line:
            k, v = line.strip().rsplit("=", 1)
            found[k] = v == "1"
    return found


def run_checks(cfg: BackupConfig, *, with_tasks: bool = True, with_network: bool = True) -> list[dict]:
    checks: list[dict] = []
    for w in cfg.warnings:
        checks.append(_check("config", WARN, w))
    ok, err = _writable(cfg.env_root)
    checks.append(_check("target", OK if ok else CRIT, f"Target {cfg.env_root} scrivibile." if ok else f"Target non scrivibile: {err}"))
    ok, err = _writable(cfg.staging)
    checks.append(_check("staging", OK if ok else CRIT, f"Staging {cfg.staging} scrivibile." if ok else f"Staging non scrivibile: {err}"))
    if cfg.target_secondary:
        ok, err = _writable(cfg.target_secondary / cfg.env)
        checks.append(_check("target_secondary", OK if ok else WARN,
                             "Destinazione secondaria scrivibile." if ok else f"Destinazione secondaria: {err}"))
    else:
        checks.append(_check("target_secondary", INFO, "Nessuna destinazione secondaria (copia fuori sede via Hyper Backup)."))
    if not cfg.env_dir:
        checks.append(_check("env_dir", WARN, "BACKUP_ENV_DIR non configurata: il .env completo va custodito nel Recovery Kit."))
    else:
        checks.append(_check("env_dir", OK if Path(cfg.env_dir).exists() else WARN,
                             f"BACKUP_ENV_DIR {'raggiungibile' if Path(cfg.env_dir).exists() else 'NON raggiungibile'}."))
    try:
        from core.db_diagnostics import server_capacity

        cap = server_capacity()
        if cap.get("supported"):
            rec = str(cap.get("recovery_model", "")).upper()
            checks.append(_check("recovery_model", OK if rec == "FULL" else WARN,
                                 f"Recovery model {rec}." + ("" if rec == "FULL" else
                                 " Backup del log impossibile: RPO = intervallo tra i FULL (24 h).")))
            if cap.get("level") in ("warning", "critical"):
                checks.append(_check("db_capacity", WARN if cap["level"] == "warning" else CRIT,
                                     f"DB al {cap['used_pct']}% del limite dell'edizione ({cap['limit_mb']} MB)."))
    except Exception as exc:
        checks.append(_check("recovery_model", WARN, f"Lettura recovery model non riuscita: {exc.__class__.__name__}"))
    checks += freshness(cfg)
    checks.append(drill_check())
    checks.append(recovery_kit_check(cfg))
    if with_tasks:
        tasks = scheduled_tasks(cfg.env)
        if tasks:
            missing = [k for k, v in tasks.items() if not v]
            checks.append(_check("scheduled_tasks", OK if not missing else WARN,
                                 "Task di backup registrati." if not missing else f"Task mancanti: {', '.join(missing)}"))
    if with_network:
        names = host_manifest.public_hostnames()
        if not names:
            checks.append(_check("hostnames", WARN, "HUB_PUBLIC_HOSTNAME non configurato."))
        local = host_manifest.local_addresses() if names else set()
        allowed = [h.lower() for h in settings.ALLOWED_HOSTS]
        origins = [str(o).lower() for o in getattr(settings, "CSRF_TRUSTED_ORIGINS", [])]
        for n in names:
            problems = []
            if n not in allowed and "*" not in allowed:
                problems.append("manca in ALLOWED_HOSTS")
            if not any(n in o for o in origins):
                problems.append("manca in CSRF_TRUSTED_ORIGINS")
            ips = host_manifest.resolve(n)
            if not ips:
                problems.append("non risolve nel DNS")
            elif not set(ips) & local:
                problems.append(f"il DNS punta a {', '.join(ips)}, non a questa macchina")
            if platform.system() == "Windows":
                spn = host_manifest.spn_check(n)
                if not spn["found"]:
                    problems.append(f"SPN HTTP/{n} assente (suggerito: setspn -S HTTP/{n} <identità del pool>)")
            checks.append(_check(f"hostname:{n}", OK if not problems else WARN,
                                 "OK" if not problems else "; ".join(problems)))
    return checks


# ── Controlli per il monitoraggio (R2) ───────────────────────────────────────

RECOVERY_KIT_STATUS = "recovery-kit.json"


def env_file_sha256() -> str | None:
    """Impronta del .env persistente (o di quello attivo): cambia a ogni modifica del file."""
    import hashlib

    for candidate in (Path(settings.BASE_DIR).parent / "config" / ".env", Path(settings.BASE_DIR) / ".env"):
        if candidate.exists():
            return hashlib.sha256(candidate.read_bytes()).hexdigest()
    return None


def recovery_kit_check(cfg: BackupConfig) -> dict:
    """Il Recovery Kit è allineato al .env e alle chiavi correnti?

    ``hub_recovery_kit export`` (R3) scrive ``<LOG_DIR>/recovery-kit.json`` con data e
    impronte (mai valori). Qui si confrontano con l'ambiente attuale."""
    import json as _json

    from . import manifest as mf

    path = cfg.status_dir / RECOVERY_KIT_STATUS
    if not path.exists():
        return _check("recovery_kit", WARN, "Nessun Recovery Kit registrato (manage.py hub_recovery_kit export).")
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _check("recovery_kit", WARN, "Stato del Recovery Kit illeggibile.")
    keys = mf.keys_section()
    mismatch = []
    if data.get("document_encryption_key_sha256") != keys.get("document_encryption_key_sha256"):
        mismatch.append("DOCUMENT_ENCRYPTION_KEY")
    if data.get("secret_key_sha256") != keys.get("secret_key_sha256"):
        mismatch.append("SECRET_KEY")
    env_sha = env_file_sha256()
    if env_sha and data.get("env_sha256") and data["env_sha256"] != env_sha:
        mismatch.append(".env")
    age = _age_hours(data.get("exported_at"), timezone.now())
    age_days = int(age / 24) if age is not None else None
    if mismatch:
        return _check("recovery_kit", WARN,
                      f"Kit non allineato ({', '.join(mismatch)} cambiati dopo l'esportazione): rigenerarlo.",
                      age_days=age_days)
    return _check("recovery_kit", OK,
                  f"Recovery Kit allineato (esportato {age_days if age_days is not None else '?'} giorni fa).",
                  age_days=age_days)


def drill_check(now: datetime | None = None) -> dict:
    now = now or timezone.now()
    try:
        from monitoring.models import RestoreDrill

        last_ok = RestoreDrill.objects.filter(status__in=("ok", "warning")).order_by("-started_at").first()
        last = RestoreDrill.objects.order_by("-started_at").first()
    except Exception:
        return _check("restore_drill", WARN, "Prove di ripristino non leggibili.")
    if last_ok is None:
        return _check("restore_drill", WARN, "Nessuna prova di ripristino riuscita.")
    days = (now - last_ok.started_at).total_seconds() / 86400
    level = OK if days < 8 else WARN if days < 35 else CRIT
    msg = f"Ultima prova riuscita {int(days)} giorni fa, RTO DB {last_ok.rto_seconds or '?'} s."
    if last and last.pk != last_ok.pk and last.status == "failed":
        level = WARN if level == OK else level
        msg += f" L'ultima prova ({timezone.localtime(last.started_at):%d/%m %H:%M}) è FALLITA: {last.error[:120]}"
    return _check("restore_drill", level, msg, days=round(days, 1), rto_seconds=last_ok.rto_seconds)


def log_check(cfg: BackupConfig, now: datetime | None = None) -> dict:
    """Backup del log: nella finestra ultimo OK < 2 h; fuori finestra ignorato; catena spezzata = critico."""
    now = now or timezone.now()
    try:
        from core.db_diagnostics import server_capacity

        rec = str(server_capacity().get("recovery_model") or "").upper()
    except Exception:
        rec = ""
    if rec and rec != "FULL":
        return _check("backup_log", INFO, f"Recovery model {rec}: backup del log non previsto.")
    for c in freshness(cfg, now):
        if c["check"] == "backup_log":
            return c
    if rec == "FULL":
        return _check("backup_log", WARN, "Recovery FULL ma nessun backup del log registrato.")
    return _check("backup_log", INFO, "Backup del log non attivo.")
