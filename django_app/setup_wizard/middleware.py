"""
SetupRequiredMiddleware — negli ambienti che richiedono il setup,
intercetta ogni richiesta e reindirizza al wizard di configurazione
se il file .env non è ancora stato configurato.

Il check è puramente file-based (legge .env direttamente) in modo che
il middleware funzioni anche prima che il database sia disponibile.
"""
from pathlib import Path

from django.conf import settings
from django.shortcuts import redirect

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Prefissi esenti dal redirect al wizard (sempre raggiungibili)
_SETUP_EXEMPT = (
    "/setup/",
    "/static/",
    "/media/",
    "/favicon",
    "/admin/",
    "/health",
    "/version",
)


def _setup_needed() -> bool:
    """Ritorna True se il wizard non è ancora stato completato."""
    if not _ENV_PATH.exists():
        return True
    for raw in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("SETUP_COMPLETED="):
            val = line.split("=", 1)[1].strip().strip("'\"")
            return val not in ("1", "true", "yes")
    return True


class SetupRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if any(path.startswith(p) for p in _SETUP_EXEMPT):
            return self.get_response(request)
        if not getattr(settings, "SETUP_WIZARD_REQUIRED", True):
            return self.get_response(request)
        if _setup_needed():
            return redirect("/setup/")
        return self.get_response(request)
