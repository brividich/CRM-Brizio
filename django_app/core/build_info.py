"""Provenienza del codice in esecuzione.

Due sorgenti distinte, che rispondono a due domande diverse:

- ``read_build_info()`` legge ``BUILD_INFO.json``, scritto da ``package-release.ps1``
  alla radice del pacchetto. Risponde a "da quale commit nasce il codice deployato?".
  Assente = non stiamo girando da un pacchetto (sviluppo locale).
- ``get_dev_git_state()`` interroga git nel working tree. Risponde a "quanto lavoro
  esiste qui che non arrivera' mai in produzione?". Solo per il badge di sviluppo:
  non deve mai girare in produzione ne' sollevare eccezioni.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

BUILD_INFO_FILENAME = "BUILD_INFO.json"

_DEV_GIT_CACHE_KEY = "core:dev_git_state:v1"
_DEV_GIT_CACHE_TTL = 60
_GIT_TIMEOUT_SECONDS = 5

# Soglia oltre la quale il badge diventa rosso (per entrambi i contatori).
DEV_GIT_ALERT_THRESHOLD = 5


def _repo_root() -> Path:
    """Radice del repository / del pacchetto: il livello sopra ``django_app/``."""
    return Path(settings.BASE_DIR).resolve().parent


def release_branch() -> str:
    return str(getattr(settings, "RELEASE_BRANCH", "release/prod") or "release/prod").strip()


# ── BUILD_INFO.json ──────────────────────────────────────────────────────────


def build_info_path() -> Path:
    return _repo_root() / BUILD_INFO_FILENAME


def read_build_info() -> dict | None:
    """Legge BUILD_INFO.json dalla radice del pacchetto.

    Ritorna ``None`` se il file non esiste (sviluppo locale: nessun pacchetto).
    Se esiste ma non e' leggibile/valido, ritorna ``{"malformed": True, ...}``:
    un pacchetto con un manifest rotto e' un'anomalia da mostrare, non da nascondere.
    """
    path = build_info_path()
    try:
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"malformed": True, "path": str(path), "has_drift": True}

    if not isinstance(raw, dict):
        return {"malformed": True, "path": str(path), "has_drift": True}

    dirty = bool(raw.get("dirty"))
    dirty_files = raw.get("dirty_files")
    if not isinstance(dirty_files, list):
        dirty_files = []

    # Pacchetti costruiti prima di questo campo non lo hanno: None != 0.
    # "Non lo so" non deve diventare "va tutto bene".
    delta = raw.get("delta_vs_export_branch")
    try:
        delta = int(delta) if delta is not None else None
    except (TypeError, ValueError):
        delta = None

    return {
        "malformed": False,
        "path": str(path),
        "source": str(raw.get("source") or "") or None,
        "commit": raw.get("commit") or None,
        "commit_short": raw.get("commit_short") or None,
        "branch": raw.get("branch") or None,
        "version": raw.get("version") or None,
        "built_at": raw.get("built_at") or None,
        "built_by": raw.get("built_by") or None,
        "dirty": dirty,
        "dirty_files": [str(f) for f in dirty_files],
        "dirty_count": len(dirty_files),
        "delta_vs_export_branch": delta,
        "has_drift": bool(dirty or (delta or 0) > 0),
    }


# ── Stato git del working tree (solo sviluppo) ───────────────────────────────


def _git(repo_root: Path, *args: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def app_for_path(path: str) -> str:
    """Raggruppa un path del repo per app Django (o area top-level)."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if not parts:
        return "(root)"
    if len(parts) == 1:
        return "(root)"
    if parts[0] == "django_app":
        return parts[1] if len(parts) > 2 else "(django_app)"
    return parts[0]


def parse_porcelain(output: str) -> list[dict]:
    """Parsing di ``git status --porcelain`` (v1)."""
    files: list[dict] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:].strip()
        # Rinomina/copia: "R  vecchio -> nuovo" — ci interessa la destinazione.
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        path = path.strip('"')
        if not path:
            continue
        files.append({"status": status.strip() or "?", "path": path, "app": app_for_path(path)})
    return files


def _collect_dev_git_state() -> dict | None:
    repo_root = _repo_root()
    if not (repo_root / ".git").exists():
        return None

    status_out = _git(repo_root, "status", "--porcelain")
    if status_out is None:
        return None
    files = parse_porcelain(status_out)

    branch_out = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    branch = (branch_out or "").strip() or "?"
    detached = branch == "HEAD"

    target = release_branch()
    ahead: int | None = None
    if not detached:
        ahead_out = _git(repo_root, "rev-list", "--count", f"{target}..HEAD")
        if ahead_out is not None:
            try:
                ahead = int(ahead_out.strip())
            except ValueError:
                ahead = None

    groups: dict[str, int] = {}
    for entry in files:
        groups[entry["app"]] = groups.get(entry["app"], 0) + 1

    return {
        "branch": branch,
        "detached": detached,
        "release_branch": target,
        "dirty_count": len(files),
        "dirty_files": files,
        "dirty_groups": sorted(groups.items(), key=lambda kv: (-kv[1], kv[0])),
        "ahead_count": ahead,
        "alert": (
            len(files) > DEV_GIT_ALERT_THRESHOLD
            or (ahead is not None and ahead > DEV_GIT_ALERT_THRESHOLD)
        ),
    }


def get_dev_git_state() -> dict | None:
    """Stato git del working tree, in cache 60s. Non solleva MAI.

    Se git non c'e', non risponde o il repo non e' un repo: ``None`` e il badge
    semplicemente non compare. Un badge diagnostico non puo' rompere una pagina.
    """
    try:
        cached = cache.get(_DEV_GIT_CACHE_KEY)
        if cached is not None:
            return cached or None
    except Exception:
        pass

    try:
        state = _collect_dev_git_state()
    except Exception:
        logger.debug("dev git badge: raccolta stato fallita", exc_info=True)
        state = None

    try:
        # Si mette in cache anche il fallimento ({}), per non ritentare a ogni request.
        cache.set(_DEV_GIT_CACHE_KEY, state or {}, _DEV_GIT_CACHE_TTL)
    except Exception:
        pass
    return state
