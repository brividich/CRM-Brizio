"""Recovery Kit: archivio cifrato con il ``.env`` completo (e il ``.pfx`` del binding HTTPS).

Senza il kit i documenti privati non si aprono: ``DOCUMENT_ENCRYPTION_KEY`` sta nel
``.env`` e non è nei backup dei dati (audit M10). Il kit si custodisce fuori dal server
(share segreti, Vaultwarden, C2 cifrato) e la passphrase in busta sigillata in Direzione.

Formato (versione 1)::

    b"HUBKIT1\\n" + <header JSON> + b"\\n" + AES-256-GCM(payload JSON)

- chiave = scrypt(passphrase, salt, n=2^17, r=8, p=1) → 32 byte;
- l'header (KDF, salt, nonce, impronte SHA-256 delle chiavi, data, ambiente) è dato
  autenticato (AAD): modificarlo rende il kit illeggibile;
- il payload contiene i file in base64 e, se c'è, la password casuale del ``.pfx``.

Il modulo usa solo la libreria standard e ``cryptography``: si esegue anche come
script (``python recovery_kit.py verify|import ...``) su una macchina dove Django non
è ancora configurato. La passphrase non passa mai sulla riga di comando.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

MAGIC = b"HUBKIT1\n"
VERSION = 1
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
MIN_WORDS = 5
MIN_CHARS = 20


class KitError(ValueError):
    pass


def check_passphrase(passphrase: str) -> None:
    words = [w for w in re.split(r"[\s\-_.]+", passphrase or "") if w]
    if len(words) < MIN_WORDS or len(passphrase) < MIN_CHARS:
        raise KitError(f"Passphrase troppo debole: servono almeno {MIN_WORDS} parole e {MIN_CHARS} caratteri.")


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def parse_env(data: bytes) -> dict[str, str]:
    """Stesse regole di ``config.env_config.load_env_file_values``."""
    values: dict[str, str] = {}
    for raw in data.decode("utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _sha(value: str | bytes | None) -> str | None:
    if not value:
        return None
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fingerprints_from_env(env_bytes: bytes) -> dict:
    values = parse_env(env_bytes)
    return {
        "document_encryption_key_sha256": _sha(values.get("DOCUMENT_ENCRYPTION_KEY")),
        "secret_key_sha256": _sha(values.get("SECRET_KEY")),
        "env_sha256": _sha(env_bytes),
    }


def build_kit(env_bytes: bytes, passphrase: str, *, env_name: str = "", pfx_bytes: bytes | None = None,
              pfx_password: str | None = None, pfx_thumbprint: str | None = None,
              n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    check_passphrase(passphrase)
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    header = {
        "magic": "HUBKIT", "version": VERSION, "cipher": "AES-256-GCM",
        "kdf": {"name": "scrypt", "n": n, "r": r, "p": p, "salt": base64.b64encode(salt).decode()},
        "nonce": base64.b64encode(nonce).decode(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "env": env_name, "host": socket.gethostname(),
        "fingerprints": fingerprints_from_env(env_bytes),
        "contains": [".env"] + (["cert.pfx"] if pfx_bytes else []),
    }
    payload = {"files": {".env": base64.b64encode(env_bytes).decode()}}
    if pfx_bytes:
        payload["files"]["cert.pfx"] = base64.b64encode(pfx_bytes).decode()
        payload["pfx_password"] = pfx_password
        payload["pfx_thumbprint"] = pfx_thumbprint
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = _derive(passphrase, salt, n, r, p)
    ct = AESGCM(key).encrypt(nonce, json.dumps(payload).encode("utf-8"), header_bytes)
    return MAGIC + header_bytes + b"\n" + ct


def read_header(kit: bytes) -> tuple[dict, bytes, bytes]:
    if not kit.startswith(MAGIC):
        raise KitError("Non è un Recovery Kit (intestazione HUBKIT1 assente).")
    rest = kit[len(MAGIC):]
    nl = rest.find(b"\n")
    if nl < 0:
        raise KitError("Recovery Kit troncato.")
    header_bytes, ct = rest[:nl], rest[nl + 1:]
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except ValueError as exc:
        raise KitError("Intestazione del kit illeggibile.") from exc
    if header.get("version") != VERSION:
        raise KitError(f"Versione del kit non supportata: {header.get('version')}")
    return header, header_bytes, ct


def open_kit(kit: bytes, passphrase: str) -> tuple[dict, dict]:
    """Decifra in memoria. Restituisce (header, payload con i file in bytes)."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    header, header_bytes, ct = read_header(kit)
    kdf = header["kdf"]
    key = _derive(passphrase, base64.b64decode(kdf["salt"]), int(kdf["n"]), int(kdf["r"]), int(kdf["p"]))
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(header["nonce"]), ct, header_bytes)
    except InvalidTag as exc:
        raise KitError("Passphrase errata oppure kit manomesso (verifica di integrità fallita).") from exc
    payload = json.loads(plain.decode("utf-8"))
    payload["files"] = {k: base64.b64decode(v) for k, v in payload.get("files", {}).items()}
    actual = fingerprints_from_env(payload["files"].get(".env", b""))
    if actual != header["fingerprints"]:
        raise KitError("Le impronte dell'intestazione non corrispondono al contenuto del kit.")
    return header, payload


def compare_fingerprints(header: dict, expected: dict) -> list[str]:
    """Differenze fra le impronte del kit e quelle attese (piano di ripristino o ambiente corrente)."""
    diff = []
    fp = header.get("fingerprints", {})
    for key, label in (("document_encryption_key_sha256", "DOCUMENT_ENCRYPTION_KEY"), ("secret_key_sha256", "SECRET_KEY")):
        if expected.get(key) and fp.get(key) != expected.get(key):
            diff.append(label)
    return diff


def write_env(env_bytes: bytes, dest: Path, *, force: bool = False) -> Path | None:
    """Scrive il .env (con copia del precedente). Restituisce il percorso della copia, se fatta."""
    dest = Path(dest)
    backup = None
    if dest.exists():
        if not force:
            raise KitError(f"{dest} esiste già: usare --force (verrà salvata una copia).")
        backup = dest.with_name(dest.name + ".bak-" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        dest.replace(backup)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(env_bytes)
    os.replace(tmp, dest)
    return backup


def _read_passphrase(from_stdin: bool, confirm: bool = False) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Passphrase del Recovery Kit: ")
    if confirm and getpass.getpass("Ripeti la passphrase: ") != first:
        raise KitError("Le due passphrase non coincidono.")
    return first


def main(argv: list[str] | None = None) -> int:
    """CLI senza Django: usata da restore-host.ps1 su una macchina nuova."""
    ap = argparse.ArgumentParser(description="Recovery Kit NOVICROM HUB (senza Django)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="Decifra in memoria e confronta le impronte.")
    v.add_argument("kit")
    v.add_argument("--plan", help="restore-plan.json: impronte attese")
    v.add_argument("--passphrase-stdin", action="store_true")
    i = sub.add_parser("import", help="Scrive il .env (e il .pfx) dal kit.")
    i.add_argument("kit")
    i.add_argument("--env-dest", required=True)
    i.add_argument("--pfx-dest", default="")
    i.add_argument("--plan", help="restore-plan.json: se le impronte non coincidono, si ferma")
    i.add_argument("--force", action="store_true")
    i.add_argument("--passphrase-stdin", action="store_true")
    args = ap.parse_args(argv)
    try:
        kit = Path(args.kit).read_bytes()
        header, payload = open_kit(kit, _read_passphrase(args.passphrase_stdin))
        expected = {}
        if args.plan:
            expected = json.loads(Path(args.plan).read_text(encoding="utf-8")).get("expected_keys", {})
        diff = compare_fingerprints(header, expected)
        if diff:
            print(f"ERRORE: impronte diverse dal piano per {', '.join(diff)}: questo kit non apre i documenti del backup.")
            return 3
        if args.cmd == "verify":
            print(f"OK: kit del {header['created_at']} (ambiente {header.get('env') or '?'}, macchina {header.get('host')}), "
                  f"contiene {', '.join(header.get('contains', []))}.")
            return 0
        backup = write_env(payload["files"][".env"], Path(args.env_dest), force=args.force)
        print(f"OK: .env scritto in {args.env_dest}" + (f" (precedente salvato in {backup})" if backup else ""))
        if args.pfx_dest and "cert.pfx" in payload["files"]:
            Path(args.pfx_dest).write_bytes(payload["files"]["cert.pfx"])
            # la password del pfx va solo su stdout di questo processo, letto da restore-host.ps1
            print("PFX_PASSWORD=" + str(payload.get("pfx_password") or ""))
            print("PFX_THUMBPRINT=" + str(payload.get("pfx_thumbprint") or ""))
        return 0
    except (KitError, OSError, ValueError) as exc:
        print(f"ERRORE: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
