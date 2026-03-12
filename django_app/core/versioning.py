from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

MODULE_VERSION_LABELS: tuple[tuple[str, str], ...] = (
    ("core", "Core"),
    ("dashboard", "Dashboard"),
    ("assenze", "Assenze"),
    ("anomalie", "Anomalie"),
    ("assets", "Assets"),
    ("tasks", "Tasks"),
    ("admin_portale", "Admin"),
    ("notizie", "Notizie"),
)

_CHANGELOG_HEADER_RE = re.compile(r"^##\s+(?P<version>[^\-]+?)\s*-\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$")


def _changelog_path() -> Path:
    return Path(getattr(settings, "BASE_DIR", Path(__file__).resolve().parents[1])) / "CHANGELOG.md"


def get_app_version() -> str:
    return str(getattr(settings, "APP_VERSION", "") or "").strip()


def get_module_versions() -> list[dict[str, object]]:
    app_version = get_app_version()
    configured = getattr(settings, "MODULE_VERSIONS", {}) or {}
    versions: list[dict[str, object]] = []
    for code, label in MODULE_VERSION_LABELS:
        value = str(configured.get(code) or app_version).strip() or app_version
        versions.append(
            {
                "code": code,
                "label": label,
                "version": value,
                "is_overridden": bool(value and app_version and value != app_version),
            }
        )
    return versions


def _clean_changelog_line(value: str) -> str:
    text = value.strip()
    if text.startswith("- "):
        text = text[2:].strip()
    return text.replace("**", "").strip()


@lru_cache(maxsize=8)
def _load_changelog_entries(path_str: str, mtime_ns: int) -> list[dict[str, object]]:
    path = Path(path_str)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw_line in lines:
        line = raw_line.strip()
        match = _CHANGELOG_HEADER_RE.match(line)
        if match:
            if current:
                entries.append(current)
            current = {
                "version": match.group("version").strip(),
                "date": match.group("date").strip(),
                "items": [],
            }
            continue
        if current and line.startswith("- "):
            current["items"].append(_clean_changelog_line(line))
    if current:
        entries.append(current)
    return entries


def get_changelog_entries(limit: int = 3) -> list[dict[str, object]]:
    path = _changelog_path()
    try:
        stat = path.stat()
    except OSError:
        return []
    entries = _load_changelog_entries(str(path), int(stat.st_mtime_ns))
    return entries[: max(0, int(limit or 0))]


def get_current_release() -> dict[str, object]:
    entries = get_changelog_entries(limit=1)
    if entries:
        return entries[0]
    return {"version": get_app_version(), "date": "", "items": []}
