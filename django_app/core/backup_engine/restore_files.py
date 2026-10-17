"""Ricostruzione di media e radici private dallo store content-addressed (BUILD_SPEC R3 §5.3 fase 4).

Solo libreria standard + ``cryptography``: si esegue come script su una macchina nuova
prima che il portale sia configurato::

    python restore_files.py <BACKUP_TARGET>\\<env> --index <set>\\files\\index.json [--env-file <.env>] [--samples 5]
                            [--map "C:\\vecchio=D:\\nuovo"] [--dry-run]

Ogni file viene copiato dall'oggetto ``_objects/<aa>/<sha256>`` e verificato con SHA-256.
I file privati restano cifrati come sono; con ``--env-file`` si decifrano in memoria N
campioni per radice privata con ``DOCUMENT_ENCRYPTION_KEY`` (nessuna scrittura in chiaro).
Uscita: JSON con conteggi ed esito; exit 0 = ok, 1 = avvisi, 2 = errori.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
from pathlib import Path

MAGIC = b"NCENC1\n"   # formato di core/encrypted_storage.py


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _env_value(env_file: Path, key: str) -> str:
    for raw in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith(key + "=") or line.startswith(key + " ="):
            return line.split("=", 1)[1].strip().strip("'").strip('"')
    return ""


def _map_path(path: str, mapping: list[tuple[str, str]]) -> Path:
    for old, new in mapping:
        if path.lower().startswith(old.lower()):
            return Path(new + path[len(old):])
    return Path(path)


def restore(env_root: Path, index: dict, *, mapping=None, dry_run=False, env_file: Path | None = None,
            samples: int = 5, seed: int | None = None) -> dict:
    mapping = mapping or []
    objects = Path(env_root) / "_objects"
    report = {"roots": {}, "files": 0, "bytes": 0, "errors": [], "decrypt": {}}
    fernet = None
    if env_file:
        key = _env_value(env_file, "DOCUMENT_ENCRYPTION_KEY")
        if key:
            from cryptography.fernet import Fernet

            fernet = Fernet(key.encode())
    rng = random.Random(seed)
    for label, root in sorted(index.items()):
        dest_root = _map_path(root["path"], mapping)
        entries = root.get("files") or {}
        done = 0
        for rel, e in entries.items():
            src = objects / e["sha256"][:2] / e["sha256"]
            dst = dest_root / rel
            try:
                if not src.exists():
                    raise FileNotFoundError(f"oggetto mancante {e['sha256'][:12]}")
                if not dry_run:
                    if not (dst.exists() and dst.stat().st_size == e["size"] and _sha256(dst) == e["sha256"]):
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        tmp = dst.with_name(dst.name + ".restoretmp")
                        shutil.copyfile(src, tmp)
                        if _sha256(tmp) != e["sha256"]:
                            tmp.unlink(missing_ok=True)
                            raise ValueError("hash diverso dopo la copia")
                        os.replace(tmp, dst)
                        os.utime(dst, (e["mtime"], e["mtime"]))
                done += 1
                report["bytes"] += e["size"]
            except (OSError, ValueError) as exc:
                report["errors"].append(f"{label}/{rel}: {exc}")
        report["roots"][label] = {"path": str(dest_root), "files": len(entries), "restored": done}
        report["files"] += done
        if label != "media" and entries and fernet is not None and samples > 0:
            picked = rng.sample(list(entries.items()), min(samples, len(entries)))
            res = {"checked": 0, "encrypted": 0, "decrypted": 0, "errors": []}
            for rel, e in picked:
                data = (objects / e["sha256"][:2] / e["sha256"]).read_bytes()
                res["checked"] += 1
                if data.startswith(MAGIC):
                    res["encrypted"] += 1
                    try:
                        fernet.decrypt(data[len(MAGIC):])
                        res["decrypted"] += 1
                    except Exception as exc:
                        res["errors"].append(f"{rel}: {exc.__class__.__name__}")
            report["decrypt"][label] = res
    decrypt_errors = sum(len(r["errors"]) for r in report["decrypt"].values())
    report["status"] = "failed" if report["errors"] or decrypt_errors else ("warning" if fernet is None else "ok")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ricostruzione dei file dallo store dei backup NOVICROM HUB")
    ap.add_argument("env_root")
    ap.add_argument("--index", required=True, help="Percorso di files/index.json (assoluto o relativo a env_root)")
    ap.add_argument("--env-file", default="")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--map", action="append", default=[], help="VECCHIO=NUOVO per spostare una radice")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    idx = Path(args.index)
    if not idx.is_absolute():
        idx = Path(args.env_root) / idx
    mapping = [tuple(m.split("=", 1)) for m in args.map if "=" in m]
    report = restore(Path(args.env_root), json.loads(idx.read_text(encoding="utf-8-sig")), mapping=mapping,
                     dry_run=args.dry_run, env_file=Path(args.env_file) if args.env_file else None, samples=args.samples)
    report["errors"] = report["errors"][:100]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"ok": 0, "warning": 1}.get(report["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
