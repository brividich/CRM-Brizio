"""
backup_portale — Management command per il backup automatico del portale.

Esegue:
  1. Backup database (SQLite copia file / SQL Server via sqlcmd BACKUP DATABASE)
  2. Configurazione: solo i NOMI delle variabili .env (audit M10). Il .env
     completo (chiave Fernet, password DB, secret Graph) viene copiato solo in
     BACKUP_ENV_DIR, una destinazione separata dai dati.
  3. pip freeze (snapshot dipendenze)
  4. media/ e le radici private cifrate (opzionale, --include-media)

Salva in: BACKUP_DIR/<YYYYMMDD_HHMMSS>/
Mantiene gli ultimi BACKUP_RETENTION backup, elimina i più vecchi.

Configurazione via .env:
  BACKUP_DIR        path assoluto della directory radice dei backup
                    (default: BASE_DIR/../backups)
  BACKUP_RETENTION  numero di backup da conservare (default: 10)
  BACKUP_ENV_DIR    cartella SEPARATA (altra share/ACL) dove copiare il .env
                    completo; vuota = .env non copiato

Uso:
  python manage.py backup_portale
  python manage.py backup_portale --include-media
  python manage.py backup_portale --retention 5

Pianificazione automatica (Windows Task Scheduler — configurata dal wizard):
  Task: PortaleNovicrom-Backup-PROD / PortaleNovicrom-Backup-TEST
  Ora:  02:00 ogni giorno
"""
import shutil
import subprocess
import sys
from pathlib import Path
import re

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

TIMESTAMP_DIR_RE = re.compile(r"^\d{8}_\d{6}$")


class Command(BaseCommand):
    help = "Backup automatico database, config e file del portale"

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-media",
            action="store_true",
            default=False,
            help="Include il backup della directory media/ (può essere voluminoso)",
        )
        parser.add_argument(
            "--retention",
            type=int,
            default=None,
            help="Numero di backup da mantenere (sovrascrive BACKUP_RETENTION)",
        )

    def handle(self, *args, **options):
        ts = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        configured_retention = int(getattr(settings, "BACKUP_RETENTION", 10) or 10)
        retention = options["retention"] if options["retention"] is not None else configured_retention
        if retention < 1:
            self.stdout.write(
                self.style.WARNING(
                    f"  Retention non valida ({retention}), uso fallback=1"
                )
            )
            retention = 1

        # ── Directory radice backup ──────────────────────────────────────────
        backup_root = Path(
            getattr(settings, "BACKUP_DIR", "") or (settings.BASE_DIR.parent / "backups")
        )
        backup_dir = backup_root / ts
        backup_dir.mkdir(parents=True, exist_ok=True)

        log_file = backup_dir / "backup.log"
        errors   = []

        def log(msg, level="INFO"):
            icon = {"OK": "✓", "WARN": "⚠", "ERR": "✗"}.get(level, " ")
            line = f"  {icon} {msg}"
            self.stdout.write(line)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timezone.localtime():%H:%M:%S}] [{level}] {msg}\n")

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\nBackup Portale Novicrom — {ts}")
        )
        self.stdout.write(f"  Directory: {backup_dir}")

        # ── 1. Database ──────────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_LABEL("\n[1/4] Database"))
        self._backup_database(backup_dir, ts, log, errors)

        # ── 2. Configurazione ────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_LABEL("\n[2/4] File di configurazione"))
        self._backup_config(backup_dir, log, errors)

        # ── 3. pip freeze ────────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_LABEL("\n[3/4] pip freeze"))
        self._backup_pip_freeze(backup_dir, log, errors)

        # ── 4. Media (opzionale) ─────────────────────────────────────────────
        if options["include_media"]:
            self.stdout.write(self.style.MIGRATE_LABEL("\n[4/4] Media"))
            self._backup_media(backup_dir, log, errors)
        else:
            self.stdout.write("  [4/4] Media saltato (usa --include-media per includerlo)")

        # ── Pulizia backup vecchi ────────────────────────────────────────────
        self._cleanup_old_backups(backup_root, retention, log)

        # ── Risultato ────────────────────────────────────────────────────────
        self.stdout.write("\n" + "─" * 52)
        if errors:
            self.stdout.write(
                self.style.WARNING(f"  Completato con {len(errors)} avvisi:")
            )
            for e in errors:
                self.stdout.write(f"    · {e}")
        else:
            self.stdout.write(self.style.SUCCESS("  Backup completato senza errori."))
        self.stdout.write(f"  Log: {log_file}\n")

    # ── Backup database ───────────────────────────────────────────────────────

    def _backup_database(self, backup_dir, ts, log, errors):
        db_conf = settings.DATABASES.get("default", {})
        engine  = db_conf.get("ENGINE", "")

        if "sqlite" in engine:
            src = Path(db_conf.get("NAME", ""))
            if src.exists():
                dst = backup_dir / f"db_{ts}.sqlite3"
                shutil.copy2(src, dst)
                log(f"SQLite copiato → {dst.name}", "OK")
            else:
                log(f"File SQLite non trovato: {src}", "WARN")
                errors.append("SQLite non trovato")

        elif "mssql" in engine or "sql_server" in engine.lower():
            db_name = db_conf.get("NAME", "")
            db_host = db_conf.get("HOST", "localhost")
            bak     = backup_dir / f"{db_name}_{ts}.bak"
            db_bracket = db_name.replace("]", "]]")
            bak_escaped = str(bak).replace("'", "''")
            sql = (
                f"BACKUP DATABASE [{db_bracket}] "
                f"TO DISK = N'{bak_escaped}' "
                f"WITH FORMAT, INIT, SKIP, STATS=10;"
            )
            sqlcmd = self._find_sqlcmd()
            try:
                r = subprocess.run(
                    [sqlcmd, "-S", db_host, "-E", "-Q", sql],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120,
                )
                if r.returncode == 0:
                    log(f"SQL Server → {bak.name}", "OK")
                else:
                    msg = (r.stderr or r.stdout)[:200].strip()
                    log(f"sqlcmd returncode={r.returncode}: {msg}", "WARN")
                    errors.append("DB SQL Server warning")
            except FileNotFoundError:
                log("sqlcmd non trovato — backup DB saltato", "WARN")
                errors.append("sqlcmd mancante")
            except subprocess.TimeoutExpired:
                log("Timeout backup DB (>120s)", "WARN")
                errors.append("DB timeout")
        else:
            log(f"Engine '{engine}' non supportato per backup automatico", "WARN")

    # ── Backup config ─────────────────────────────────────────────────────────

    def _backup_config(self, backup_dir, log, errors):
        """SEC (audit M10): la chiave di cifratura non sta accanto ai dati cifrati.

        Nel backup finisce solo l'elenco dei nomi delle variabili; il .env completo
        va in ``BACKUP_ENV_DIR`` (destinazione separata) se configurata.
        """
        import os

        config_dst = backup_dir / "config"
        config_dst.mkdir(exist_ok=True)
        name = ".env"
        source = None
        # Cerca prima vicino a BASE_DIR, poi in config/ al livello superiore
        for candidate in [
            settings.BASE_DIR / name,
            settings.BASE_DIR.parent / "config" / name,
        ]:
            if candidate.exists():
                source = candidate
                break
        if source is None:
            log(f"{name} non trovato (non critico)", "WARN")
            return

        keys = []
        for raw in source.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                keys.append(line.split("=", 1)[0].strip())
        (config_dst / "env_keys.txt").write_text("\n".join(keys) + "\n", encoding="utf-8")
        log(f"{len(keys)} nomi variabili .env → config/env_keys.txt (valori esclusi)", "OK")

        env_dir = str(getattr(settings, "BACKUP_ENV_DIR", "") or os.environ.get("BACKUP_ENV_DIR", "")).strip()
        if not env_dir:
            log("BACKUP_ENV_DIR non configurata: .env completo NON copiato (salvarlo a parte)", "WARN")
            return
        target_dir = Path(env_dir) / backup_dir.name
        try:
            if Path(env_dir).resolve() == backup_dir.parent.resolve():
                log("BACKUP_ENV_DIR coincide con BACKUP_DIR: .env non copiato", "WARN")
                errors.append("BACKUP_ENV_DIR non separata")
                return
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_dir / name)
            log(f"{name} → {target_dir}", "OK")
        except Exception as exc:
            log(f"Copia .env in BACKUP_ENV_DIR fallita: {exc}", "WARN")
            errors.append(".env separato")

    # ── pip freeze ────────────────────────────────────────────────────────────

    def _backup_pip_freeze(self, backup_dir, log, errors):
        freeze_file = backup_dir / "pip_freeze.txt"
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )
            freeze_file.write_text(r.stdout, encoding="utf-8")
            count = len(r.stdout.splitlines())
            log(f"{count} pacchetti → pip_freeze.txt", "OK")
        except Exception as e:
            log(f"pip freeze fallito: {e}", "WARN")
            errors.append("pip freeze")

    # ── Backup media ──────────────────────────────────────────────────────────

    def _backup_media(self, backup_dir, log, errors):
        media_src = Path(settings.MEDIA_ROOT)
        if not media_src.exists():
            log(f"MEDIA_ROOT non trovato: {media_src}", "WARN")
            return
        media_dst = backup_dir / "media"
        try:
            shutil.copytree(str(media_src), str(media_dst), dirs_exist_ok=True)
            log(f"media/ copiato → {media_dst}", "OK")
        except Exception as e:
            log(f"Media backup fallito: {e}", "WARN")
            errors.append("media")
        self._backup_private_roots(backup_dir, log, errors)

    def _backup_private_roots(self, backup_dir, log, errors):
        """Radici private (referti, DPI, ticket, task, SDS...): restano cifrate (audit M10)."""
        roots: dict[str, Path] = {}
        for setting_name in dir(settings):
            if not (setting_name.endswith("_PRIVATE_ROOT") or setting_name == "PRIVATE_ATTACHMENTS_ROOT"):
                continue
            value = getattr(settings, setting_name, None)
            if not value:
                continue
            path = Path(value)
            if path.exists():
                roots.setdefault(str(path.resolve()).lower(), path)
        for index, path in enumerate(sorted(roots.values(), key=str)):
            dst = backup_dir / "media_private" / (f"{index:02d}_" + path.name)
            try:
                shutil.copytree(str(path), str(dst), dirs_exist_ok=True)
                log(f"{path} → {dst}", "OK")
            except Exception as e:
                log(f"Backup radice privata {path} fallito: {e}", "WARN")
                errors.append(f"media_private {path.name}")

    # ── Pulizia backup vecchi ─────────────────────────────────────────────────

    def _cleanup_old_backups(self, backup_root, retention, log):
        try:
            dirs = sorted(
                [
                    d
                    for d in backup_root.iterdir()
                    if d.is_dir() and TIMESTAMP_DIR_RE.match(d.name)
                ],
                key=lambda d: d.name,
                reverse=True,
            )
            for old in dirs[retention:]:
                shutil.rmtree(old, ignore_errors=True)
                log(f"Eliminato backup vecchio: {old.name}", "INFO")
        except Exception as e:
            log(f"Pulizia backup fallita: {e}", "WARN")

    # ── Utility ───────────────────────────────────────────────────────────────

    def _find_sqlcmd(self):
        for candidate in [
            r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\160\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\150\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\140\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\130\Tools\Binn\SQLCMD.EXE",
        ]:
            if Path(candidate).exists():
                return candidate
        return "sqlcmd"  # fallback al PATH
