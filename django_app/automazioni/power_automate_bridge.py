from __future__ import annotations

from functools import lru_cache
import importlib
from pathlib import Path
import sys
from typing import Any


APP_DIR = Path(__file__).resolve().parents[1] / "powerautomate-to-django-automations" / "app"


def _ensure_converter_app_path() -> None:
    if not APP_DIR.exists():
        raise RuntimeError(
            "Cartella converter Power Automate non trovata in "
            f"`{APP_DIR}`. Verifica lo spostamento sotto `django_app/`."
        )
    app_dir = str(APP_DIR)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)


@lru_cache(maxsize=1)
def _conversion_service_module():
    _ensure_converter_app_path()
    importlib.invalidate_caches()
    return importlib.import_module("conversion_service")


def analyze_power_automate_flow_upload(
    filename: str,
    payload: bytes,
    *,
    target_context: dict[str, Any] | None = None,
    approval_template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _conversion_service_module().analyze_flow_upload(
        filename,
        payload,
        target_context=target_context,
        approval_template=approval_template,
    )


def apply_power_automate_recommended_remediation(record: dict[str, Any]) -> dict[str, Any]:
    return _conversion_service_module().apply_recommended_remediation(record)
