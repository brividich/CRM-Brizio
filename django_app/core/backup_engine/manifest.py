"""Manifest dei backup set: costruzione, validazione (schema v1), lettura e scrittura.

Il manifest non contiene mai valori di segreti: solo **nomi** delle variabili
``.env`` e **impronte** SHA-256 delle chiavi. Percorsi degli artefatti relativi
alla cartella del set.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import timezone

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"


class ManifestError(ValueError):
    pass


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads((Path(__file__).with_name("manifest.schema.json")).read_text(encoding="utf-8-sig"))


_TYPES = {
    "object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
    "boolean": bool, "null": type(None),
}


def _check(value, sch: dict, where: str, errors: list[str]) -> None:
    import re

    types = sch.get("type")
    if types:
        allowed = types if isinstance(types, list) else [types]
        ok = any(isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
                 for t in allowed)
        if not ok:
            errors.append(f"{where}: tipo {type(value).__name__}, atteso {allowed}")
            return
    if "enum" in sch and value not in sch["enum"]:
        errors.append(f"{where}: valore {value!r} non ammesso")
    if "pattern" in sch and isinstance(value, str) and not re.match(sch["pattern"], value):
        errors.append(f"{where}: {value!r} non rispetta {sch['pattern']}")
    if isinstance(value, dict):
        for key in sch.get("required", []):
            if key not in value:
                errors.append(f"{where}.{key}: obbligatorio")
        for key, sub in (sch.get("properties") or {}).items():
            if key in value:
                _check(value[key], sub, f"{where}.{key}", errors)
    if isinstance(value, list) and "items" in sch:
        for i, item in enumerate(value):
            _check(item, sch["items"], f"{where}[{i}]", errors)


def validate(data: dict) -> None:
    errors: list[str] = []
    _check(data, schema(), "manifest", errors)
    if errors:
        raise ManifestError("; ".join(errors[:10]))


def fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def env_var_names() -> list[str]:
    """Nomi (mai valori) delle variabili del .env runtime."""
    candidates = [Path(settings.BASE_DIR) / ".env", Path(settings.BASE_DIR).parent / "config" / ".env"]
    for path in candidates:
        if path.exists():
            names = []
            for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    names.append(line.split("=", 1)[0].strip())
            return sorted(set(names))
    return []


def keys_section() -> dict:
    return {
        "document_encryption_key_sha256": fingerprint(getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "")),
        "secret_key_sha256": fingerprint(getattr(settings, "SECRET_KEY", "")),
        "env_var_names": env_var_names(),
    }


def app_section(migrations: dict | None = None) -> dict:
    from core.build_info import read_build_info

    info = read_build_info() or {}
    version = str(info.get("version") or getattr(settings, "APP_VERSION", "") or "")
    if not version:
        try:
            from config.app_version import DEFAULT_APP_VERSION

            version = DEFAULT_APP_VERSION
        except Exception:
            version = "sconosciuta"
    return {
        "version": version,
        "commit": info.get("commit"),
        "branch": info.get("branch"),
        "package": info.get("package") or info.get("zip"),
        "migrations": migrations or {},
    }


def new_manifest(set_id: str, kind: str, env: str) -> dict:
    import socket

    return {
        "schema_version": SCHEMA_VERSION,
        "set_id": set_id,
        "type": kind,
        "env": env,
        "status": "ok",
        "created_at": timezone.localtime().isoformat(),
        "host": socket.gethostname(),
        "app": {"version": "", "commit": None, "branch": None, "migrations": {}},
        "sql": None,
        "databases": [],
        "artifacts": [],
        "chain": None,
        "files": None,
        "keys": {},
        "row_counts": {},
        "host_manifest_ref": None,
        "release_ref": None,
        "duration_s": 0.0,
        "warnings": [],
    }


def dumps(data: dict) -> bytes:
    validate(data)
    return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def load(set_dir: Path) -> dict:
    p = Path(set_dir) / MANIFEST_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"{p}: illeggibile ({exc})") from exc
    validate(data)
    return data
