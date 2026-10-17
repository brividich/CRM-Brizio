"""Recovery Kit del portale (BUILD_SPEC R3 §5.1).

  manage.py hub_recovery_kit export --out \\\\share-segreti\\hub\\prod-20261017.hubkit [--pfx-thumbprint <T>]
  manage.py hub_recovery_kit verify <file.hubkit>
  manage.py hub_recovery_kit import <file.hubkit> --to prod [--force]

La passphrase (almeno 5 parole) si chiede in modo interattivo, mai sulla riga di
comando; ``--passphrase-stdin`` la legge da stdin (uso da script). ``verify`` decifra
in memoria e non scrive nulla. ``export`` aggiorna ``<LOG_DIR>/recovery-kit.json``
(data e impronte, mai valori): il monitoraggio segnala «kit non allineato» quando
.env o chiavi cambiano dopo l'esportazione. Su una macchina nuova, senza Django
configurato, si usa lo stesso modulo come script: ``python core/backup_engine/recovery_kit.py``.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.backup_engine import manifest as mf
from core.backup_engine import recovery_kit as rk
from core.backup_engine.doctor import RECOVERY_KIT_STATUS, env_file_sha256


def _env_path() -> Path:
    for candidate in (Path(settings.BASE_DIR).parent / "config" / ".env", Path(settings.BASE_DIR) / ".env"):
        if candidate.exists():
            return candidate
    raise CommandError("File .env non trovato (config\\.env o django_app\\.env).")


def _export_pfx(thumbprint: str) -> tuple[bytes, str]:
    """Esporta il certificato del binding HTTPS con una password casuale (che finisce nel kit)."""
    if not thumbprint.isalnum():
        raise CommandError("Thumbprint non valido.")
    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cert.pfx"
        script = (
            "$p = ConvertTo-SecureString -String $env:HUBKIT_PFX_PW -Force -AsPlainText; "
            f"Export-PfxCertificate -Cert 'Cert:\\LocalMachine\\My\\{thumbprint}' -FilePath '{out}' -Password $p | Out-Null"
        )
        env = dict(os.environ, HUBKIT_PFX_PW=password)   # mai sulla riga di comando
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, env=env, timeout=60)
        if proc.returncode != 0 or not out.exists():
            raise CommandError(f"Esportazione del certificato non riuscita: {(proc.stderr or proc.stdout).strip()[:300]}")
        return out.read_bytes(), password


class Command(BaseCommand):
    help = "Esporta, verifica o importa il Recovery Kit cifrato (.env + certificato HTTPS)."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="cmd", required=True)
        e = sub.add_parser("export")
        e.add_argument("--out", required=True)
        e.add_argument("--pfx-thumbprint", default="")
        e.add_argument("--passphrase-stdin", action="store_true")
        e.add_argument("--env", default="")
        v = sub.add_parser("verify")
        v.add_argument("kit")
        v.add_argument("--passphrase-stdin", action="store_true")
        i = sub.add_parser("import")
        i.add_argument("kit")
        i.add_argument("--to", required=True, choices=["test", "prod"])
        i.add_argument("--force", action="store_true")
        i.add_argument("--passphrase-stdin", action="store_true")

    def handle(self, *args, **opts):
        try:
            return getattr(self, f"_{opts['cmd']}")(opts)
        except rk.KitError as exc:
            raise CommandError(str(exc)) from exc

    def _passphrase(self, opts, confirm=False) -> str:
        return rk._read_passphrase(opts["passphrase_stdin"], confirm=confirm)

    def _export(self, opts):
        out = Path(opts["out"])
        if out.exists():
            raise CommandError(f"{out} esiste già: scegli un altro nome (i kit non si sovrascrivono).")
        env_bytes = _env_path().read_bytes()
        pfx, pfx_pw = (None, None)
        if opts["pfx_thumbprint"]:
            pfx, pfx_pw = _export_pfx(opts["pfx_thumbprint"])
        passphrase = self._passphrase(opts, confirm=not opts["passphrase_stdin"])
        rk.check_passphrase(passphrase)
        from core.backup_engine.config import default_env_name

        env_name = opts["env"] or default_env_name()
        kit = rk.build_kit(env_bytes, passphrase, env_name=env_name, pfx_bytes=pfx, pfx_password=pfx_pw,
                           pfx_thumbprint=opts["pfx_thumbprint"] or None)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(kit)
        rk.open_kit(out.read_bytes(), passphrase)      # rilettura: il file scritto si apre
        header, _hb, _ct = rk.read_header(kit)
        state = {"exported_at": timezone.now().isoformat(), "file_name": out.name, "env": env_name,
                 "contains": header["contains"], **header["fingerprints"]}
        status_path = Path(settings.LOG_DIR) / RECOVERY_KIT_STATUS
        status_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Recovery Kit scritto in {out} ({', '.join(header['contains'])}). Copiarlo nelle altre collocazioni "
            "(Vaultwarden, C2 cifrato) e verificarlo con: manage.py hub_recovery_kit verify <file>."))

    def _verify(self, opts):
        header, payload = rk.open_kit(Path(opts["kit"]).read_bytes(), self._passphrase(opts))
        current = mf.keys_section()
        diff = rk.compare_fingerprints(header, current)
        env_now = env_file_sha256()
        env_same = env_now == header["fingerprints"].get("env_sha256")
        self.stdout.write(f"Kit del {header['created_at']} · ambiente {header.get('env') or '?'} · macchina "
                          f"{header.get('host')} · contiene {', '.join(header.get('contains', []))}")
        if diff:
            raise CommandError(f"Il kit NON corrisponde all'ambiente corrente: {', '.join(diff)} diverse.")
        self.stdout.write(self.style.SUCCESS("Chiavi del kit uguali a quelle in uso: i documenti si aprono."))
        if not env_same:
            self.stdout.write(self.style.WARNING("Il .env è cambiato dopo l'esportazione: rigenerare il kit."))

    def _import(self, opts):
        header, payload = rk.open_kit(Path(opts["kit"]).read_bytes(), self._passphrase(opts))
        dest = Path(r"C:\PortaleNovicrom") / opts["to"] / "config" / ".env"
        backup = rk.write_env(payload["files"][".env"], dest, force=opts["force"])
        self.stdout.write(self.style.SUCCESS(f".env scritto in {dest}" + (f" (precedente: {backup})" if backup else "")))
        acl = Path(settings.BASE_DIR).parent / "deployment" / "scripts" / "secure-env-acl.ps1"
        if acl.exists() and os.name == "nt":
            proc = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(acl),
                                   "-Environment", opts["to"], "-Quiet"], capture_output=True, text=True, timeout=120)
            msg = "ACL del .env applicate." if proc.returncode == 0 else "secure-env-acl.ps1 non riuscito: applicare a mano."
            self.stdout.write(msg)
