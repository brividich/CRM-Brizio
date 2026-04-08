from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path


def default_env_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def load_env_file_values(dotenv_path: Path | None = None) -> dict[str, str]:
    path = dotenv_path or default_env_path()
    values: dict[str, str] = {}
    try:
        if not path.exists():
            return values
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'").strip('"')
    except Exception:
        return {}
    return values


def load_dotenv_into_environ(dotenv_path: Path | None = None, *, preserve_existing: bool = True) -> None:
    for key, value in load_env_file_values(dotenv_path).items():
        if preserve_existing:
            os.environ.setdefault(key, value)
        else:
            os.environ[key] = value


def get_first_env_value(*keys: str, default: str = "") -> str:
    for key in keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return default


def resolve_env_value(*keys: str, dotenv_values: Mapping[str, str] | None = None) -> tuple[str, str]:
    file_values = dict(dotenv_values or load_env_file_values())
    for key in keys:
        process_value = os.getenv(key)
        file_value = file_values.get(key)

        process_text = str(process_value or "").strip()
        file_text = str(file_value or "").strip()

        if process_text and (file_value is None or process_text != file_text):
            return process_text, "process_env"
        if file_text:
            return file_text, "dotenv"
    return "", "missing"


def update_env_file_values(
    updates: Mapping[str, object],
    dotenv_path: Path | None = None,
    *,
    apply_to_process: bool = True,
    delete_keys: Iterable[str] | None = None,
) -> dict[str, str]:
    path = dotenv_path or default_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []

    line_indexes: dict[str, int] = {}
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key and key not in line_indexes:
            line_indexes[key] = index

    normalized_updates = {
        str(key).strip(): "" if value is None else str(value)
        for key, value in updates.items()
        if str(key).strip()
    }
    normalized_delete_keys = [str(key).strip() for key in (delete_keys or []) if str(key).strip()]

    for key, value in normalized_updates.items():
        rendered = f"{key}={value}"
        if key in line_indexes:
            lines[line_indexes[key]] = rendered
        else:
            if lines and lines[-1].strip():
                lines.append("")
            line_indexes[key] = len(lines)
            lines.append(rendered)

    if normalized_delete_keys:
        delete_set = set(normalized_delete_keys)
        filtered_lines: list[str] = []
        for raw_line in lines:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in delete_set:
                    continue
            filtered_lines.append(raw_line)
        lines = filtered_lines

    output = "\n".join(lines)
    if output and not output.endswith("\n"):
        output += "\n"
    path.write_text(output, encoding="utf-8")

    if apply_to_process:
        for key, value in normalized_updates.items():
            os.environ[key] = value
        for key in normalized_delete_keys:
            os.environ.pop(key, None)

    return load_env_file_values(path)
