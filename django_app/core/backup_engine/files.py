"""Backup incrementale content-addressed di MEDIA_ROOT e delle radici private.

Gli oggetti stanno in ``<target>/<env>/_objects/<sha[:2]>/<sha>`` (condivisi fra i
set: un file invariato non si ricopia), ogni set ha il suo ``files/index.json``
(radice → percorso relativo → sha256, size, mtime). I file privati restano
**cifrati come sono**: il backup non li decifra mai.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from .transfer import copy_verified, sha256_file


def private_roots() -> dict[str, Path]:
    """Tutte le radici private dichiarate in settings, deduplicate per percorso risolto.

    Chiave = etichetta stabile (nomi dei setting che puntano allo stesso percorso).
    Una radice contenuta in un'altra già inclusa viene scartata (sarebbe copiata due volte).
    """
    per_path: dict[str, tuple[Path, list[str]]] = {}
    for name in sorted(dir(settings)):
        if not (name.endswith("_PRIVATE_ROOT") or name == "PRIVATE_ATTACHMENTS_ROOT"):
            continue
        value = getattr(settings, name, None)
        if not value:
            continue
        path = Path(value)
        key = os.path.normcase(str(path.resolve()))
        per_path.setdefault(key, (path, []))[1].append(name)
    keys = sorted(per_path)
    kept = [k for k in keys if not any(k != o and k.startswith(o.rstrip("\\/") + os.sep) for o in keys)]
    return {"+".join(per_path[k][1]).lower(): per_path[k][0] for k in kept}


def file_roots() -> dict[str, Path]:
    roots = {"media": Path(settings.MEDIA_ROOT)}
    media_key = os.path.normcase(str(Path(settings.MEDIA_ROOT).resolve()))
    for label, path in private_roots().items():
        key = os.path.normcase(str(path.resolve()))
        if key.startswith(media_key.rstrip("\\/") + os.sep) or key == media_key:
            continue   # già dentro media
        roots[label] = path
    return roots


def object_path(objects_root: Path, sha: str) -> Path:
    return Path(objects_root) / sha[:2] / sha


@dataclass
class FilesResult:
    index: dict = field(default_factory=dict)
    files: int = 0
    new_objects: int = 0
    new_bytes: int = 0
    total_bytes: int = 0
    errors: list[str] = field(default_factory=list)


def backup_files(objects_root: Path, previous_index: dict | None = None, roots: dict[str, Path] | None = None,
                 dry_run: bool = False) -> FilesResult:
    """Copia gli oggetti nuovi e restituisce l'indice del set."""
    roots = roots if roots is not None else file_roots()
    previous_index = previous_index or {}
    res = FilesResult()
    for label, root in sorted(roots.items()):
        entries: dict[str, dict] = {}
        res.index[label] = {"path": str(root), "files": entries}
        if not Path(root).exists():
            continue
        prev_files = (previous_index.get(label) or {}).get("files", {})
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                full = Path(dirpath) / fname
                rel = full.relative_to(root).as_posix()
                try:
                    st = full.stat()
                    prev = prev_files.get(rel)
                    if prev and prev.get("size") == st.st_size and prev.get("mtime") == int(st.st_mtime) \
                            and object_path(objects_root, prev["sha256"]).exists():
                        sha = prev["sha256"]
                    else:
                        sha = sha256_file(full)
                    dst = object_path(objects_root, sha)
                    if not dst.exists():
                        if not dry_run:
                            copy_verified(full, dst, expected_sha256=sha)
                        res.new_objects += 1
                        res.new_bytes += st.st_size
                    entries[rel] = {"sha256": sha, "size": st.st_size, "mtime": int(st.st_mtime)}
                    res.files += 1
                    res.total_bytes += st.st_size
                except Exception as exc:  # un file illeggibile non ferma il backup
                    res.errors.append(f"{label}/{rel}: {exc.__class__.__name__}: {exc}")
    return res


def referenced_objects(indexes: list[dict]) -> set[str]:
    refs: set[str] = set()
    for index in indexes:
        for root in index.values():
            for entry in (root.get("files") or {}).values():
                refs.add(entry["sha256"])
    return refs


def load_index(set_dir: Path) -> dict:
    p = Path(set_dir) / "files" / "index.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
