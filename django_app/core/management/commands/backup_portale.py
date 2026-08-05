"""
backup_portale — Management command per il backup automatico del portale.

Esegue:
  1. Backup database (SQLite copia file / SQL Server via sqlcmd BACKUP DATABASE)
  2. File di configurazione (.env)
  3. pip freeze (snapshot dipendenze)
  4. media/ (opzionale, --include-media)

Salva in: BACKUP_DIR/<YYYYMMDD_HHMMSS>/
Mantiene gli ultimi BACKUP_RETENTION backup, elimina i più vecchi.

Configurazione via .env:
  BACKUP_DIR        path assoluto della directory radice dei backup
                    (default: BASE_DIR/../backups)
  BACKUP_RETENTION  numero di backup da conservare (default: 10)

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
        config_dst = backup_dir / "config"
        config_dst.mkdir(exist_ok=True)
        for name in (".env",):
            # Cerca prima vicino a BASE_DIR, poi in config/ al livello superiore
            for candidate in [
                settings.BASE_DIR / name,
                settings.BASE_DIR.parent / "config" / name,
            ]:
                if candidate.exists():
                    shutil.copy2(candidate, config_dst / name)
                    log(f"{name} → config/{name}", "OK")
                    break
            else:
                log(f"{name} non trovato (non critico)", "WARN")

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
