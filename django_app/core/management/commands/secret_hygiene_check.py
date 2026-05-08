from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "change_me",
    "change-me",
    "change_me_from_env",
    "<change_me>",
    "password",
    "example",
    "example.local",
}

CONFIG_PATH_SUFFIXES = (
    ".env",
    ".env.example",
    ".ini",
    ".ini.example",
    ".cfg",
    ".conf",
    ".toml",
    ".yaml",
    ".yml",
    ".properties",
    ".ps1",
    ".bat",
    ".cmd",
)

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "staticfiles",
}

BINARY_EXTENSIONS = {
    ".7z",
    ".bmp",
    ".dll",
    ".doc",
    ".docx",
    ".exe",
    ".gif",
    ".ico",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".png",
    ".pyd",
    ".pyc",
    ".rar",
    ".sqlite3",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}

SENSITIVE_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env($|\.)", re.IGNORECASE),
    re.compile(r"(^|/)config\.ini$", re.IGNORECASE),
    re.compile(r"(^|/)DIPENDENTI\.csv$", re.IGNORECASE),
    re.compile(r"(^|/)(db\.sqlite3|utenti\.db)$", re.IGNORECASE),
    re.compile(r"\.(pem|key|pfx|p12|jks|keystore)$", re.IGNORECASE),
]

TOKEN_PATTERNS = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9_]{30,}\b")),
    ("github_fine_grained_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY-----")),
]

ASSIGNMENT_PATTERN = re.compile(
    r"^\s*(?P<key>[A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|CLIENT_SECRET)[A-Z0-9_]*)\s*[:=]\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)

GRAPH_EXAMPLE_ID_PATTERN = re.compile(
    r"^\s*(?P<key>GRAPH_[A-Z0-9_]*ID[A-Z0-9_]*)\s*=\s*(?P<value>[0-9a-f][0-9a-f-]{30,})\s*$",
    re.IGNORECASE,
)

INTERNAL_VALUE_PATTERN = re.compile(
    r"(costruzioninovicrom\.it|cnovicrom\.local|novicrom\.local)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    path: str
    line: int | None
    detail: str


def _repo_root() -> Path:
    return Path(settings.BASE_DIR).resolve().parent


def _run_git(repo_root: Path, args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def _iter_git_files(repo_root: Path, include_untracked: bool) -> list[str]:
    files = _run_git(repo_root, ["ls-files"])
    if include_untracked:
        files.extend(_run_git(repo_root, ["ls-files", "--others", "--exclude-standard"]))
    return sorted(set(files))


def _is_example_env(path: str) -> bool:
    return path.lower().endswith(".env.example")


def _is_sensitive_path(path: str) -> bool:
    if _is_example_env(path):
        return False
    return any(pattern.search(path) for pattern in SENSITIVE_PATH_PATTERNS)


def _should_skip_content(path: str) -> bool:
    parts = Path(path).parts
    if any(part in SKIP_DIRS for part in parts):
        return True
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def _normalize_value(raw_value: str) -> str:
    value = raw_value.strip().strip("'").strip('"')
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    return value


def _is_placeholder_value(value: str) -> bool:
    normalized = _normalize_value(value)
    lowered = normalized.lower()
    if lowered in PLACEHOLDER_VALUES:
        return True
    if lowered.startswith("change_me") or lowered.startswith("changeme"):
        return True
    if normalized.startswith("<") and normalized.endswith(">"):
        return True
    if "example." in lowered or lowered.endswith("@example.local"):
        return True
    if "${" in normalized or "{{" in normalized or "}}" in normalized:
        return True
    return False


def _is_assignment_candidate(path: str) -> bool:
    path_lower = path.lower()
    return path_lower.endswith(CONFIG_PATH_SUFFIXES)


def _scan_content(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    is_example = path.lower().endswith((".example", ".env.example", ".ini.example"))
    scan_assignments = _is_assignment_candidate(path)

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if "hygiene: skip" in line or "hygiene:skip" in line:
            continue
        for rule, pattern in TOKEN_PATTERNS:
            if pattern.search(line):
                findings.append(Finding("HIGH", rule, path, line_number, "pattern secret ad alta confidenza"))

        assignment = ASSIGNMENT_PATTERN.match(line) if scan_assignments else None
        if assignment and not stripped.startswith(("#", ";")):
            key = assignment.group("key").upper()
            value = _normalize_value(assignment.group("value"))
            if len(value) >= 16 and not _is_placeholder_value(value):
                findings.append(Finding("HIGH", "sensitive_assignment", path, line_number, f"{key} contiene un valore non placeholder"))

        if is_example and not stripped.startswith(("#", ";")) and INTERNAL_VALUE_PATTERN.search(line):
            findings.append(Finding("MEDIUM", "internal_value_in_example", path, line_number, "valore aziendale/interno in file example"))

        graph_match = GRAPH_EXAMPLE_ID_PATTERN.match(line)
        if is_example and graph_match and not _is_placeholder_value(graph_match.group("value")):
            findings.append(Finding("MEDIUM", "graph_id_in_example", path, line_number, f"{graph_match.group('key')} deve restare placeholder"))

    return findings


def scan_repo(repo_root: Path, *, include_untracked: bool = False, max_bytes: int = 2_000_000) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in _iter_git_files(repo_root, include_untracked):
        normalized_path = relative_path.replace("\\", "/")
        full_path = repo_root / normalized_path
        if _is_sensitive_path(normalized_path):
            findings.append(Finding("HIGH", "sensitive_file_tracked", normalized_path, None, "file sensibile presente tra i file Git"))
            continue
        if _should_skip_content(normalized_path):
            continue
        try:
            if full_path.stat().st_size > max_bytes:
                continue
            text = full_path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        findings.extend(_scan_content(normalized_path, text))
    return findings


class Command(BaseCommand):
    help = "Scansiona i file Git alla ricerca di path sensibili e segreti hardcoded."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-untracked",
            action="store_true",
            help="Include anche file non versionati ma non ignorati da .gitignore.",
        )
        parser.add_argument(
            "--fail-on-medium",
            action="store_true",
            help="Ritorna errore anche per finding MEDIUM.",
        )
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Formato output (default: text).",
        )
        parser.add_argument(
            "--max-bytes",
            type=int,
            default=2_000_000,
            help="Dimensione massima per file testuale da leggere.",
        )

    def handle(self, *args, **options):
        repo_root = _repo_root()
        findings = scan_repo(
            repo_root,
            include_untracked=bool(options["include_untracked"]),
            max_bytes=int(options["max_bytes"]),
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps({"findings": [asdict(item) for item in findings]}, indent=2))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING("Secret hygiene check"))
            if not findings:
                self.stdout.write(self.style.SUCCESS("OK: nessun possibile segreto rilevato nei file Git analizzati."))
            else:
                for item in findings:
                    location = item.path if item.line is None else f"{item.path}:{item.line}"
                    style = self.style.ERROR if item.severity == "HIGH" else self.style.WARNING
                    self.stdout.write(style(f"[{item.severity}] {item.rule} {location} - {item.detail}"))

        high_count = sum(1 for item in findings if item.severity == "HIGH")
        medium_count = sum(1 for item in findings if item.severity == "MEDIUM")
        should_fail = high_count > 0 or (bool(options["fail_on_medium"]) and medium_count > 0)
        if should_fail:
            raise CommandError(f"Secret hygiene check failed: high={high_count}, medium={medium_count}")
