"""Viste del Pannello di amministrazione — Crea release: pacchetti, terminale e riavvio servizio.

Spacchettamento di ``admin_portale/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import base64
import logging
import os
import shlex
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST


from ..decorators import legacy_admin_required
from ..security import sensitive_admin_operation_required

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CREA RELEASE PACKAGE
# ---------------------------------------------------------------------------

_RELEASE_ENVIRONMENTS = {"test", "prod"}
_RELEASE_TERMINAL_DEFAULT_TIMEOUT = 240
_RELEASE_TERMINAL_MAX_TIMEOUT = 600
_RELEASE_IIS_TASK_FOLDER = r"\PortaleNovicrom"
_RELEASE_IIS_TASK_BASE_NAME = "IISRestart"


def _release_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _normalize_release_environment(value: object) -> str:
    env = str(value or "").strip().lower()
    return env if env in _RELEASE_ENVIRONMENTS else "test"


def _release_deploy_base_dir() -> Path:
    configured = str(os.getenv("PORTAL_DEPLOY_BASE_DIR") or "").strip()
    if configured:
        return Path(configured)

    project_dir = Path(settings.BASE_DIR)
    try:
        resolved = project_dir.resolve()
    except OSError:
        resolved = project_dir

    candidates = [project_dir]
    if resolved != project_dir:
        candidates.append(resolved)

    for candidate in candidates:
        parent = candidate.parent
        if parent.name.lower() == "current":
            return parent.parent.parent
        release_parent = parent.parent
        if release_parent.name.lower() == "releases":
            return release_parent.parent.parent

    return Path("C:/PortaleNovicrom")


def _release_env_root(environment: str) -> Path:
    return _release_deploy_base_dir() / _normalize_release_environment(environment)


def _release_site_name(environment: str) -> str:
    return f"PortaleNovicrom-{_normalize_release_environment(environment).upper()}"


def _release_iis_restart_task_short_name(environment: str) -> str:
    return f"{_RELEASE_IIS_TASK_BASE_NAME}_{_normalize_release_environment(environment).upper()}"


def _release_iis_restart_task_name(environment: str) -> str:
    return rf"{_RELEASE_IIS_TASK_FOLDER}\{_release_iis_restart_task_short_name(environment)}"


def _release_resolve_django_app(environment: str) -> Path | None:
    env_root = _release_env_root(environment)
    candidates = [
        env_root / "current" / "django_app",
        env_root / "django_app",
    ]
    releases_dir = env_root / "releases"
    try:
        if releases_dir.exists():
            releases = sorted(
                (p for p in releases_dir.iterdir() if p.is_dir()),
                key=lambda p: p.name,
                reverse=True,
            )
            candidates.extend(p / "django_app" for p in releases)
    except OSError:
        pass

    for candidate in candidates:
        if (candidate / "manage.py").exists():
            return candidate
    return None


def _release_current_environment() -> str:
    configured = str(os.getenv("ENVIRONMENT") or "").strip().lower()
    if configured in _RELEASE_ENVIRONMENTS:
        return configured

    try:
        project_dir = Path(settings.BASE_DIR).resolve()
    except OSError:
        project_dir = Path(settings.BASE_DIR)
    base = _release_deploy_base_dir()
    for env in ("test", "prod"):
        try:
            project_dir.relative_to(base / env)
            return env
        except ValueError:
            continue
    return "test"


def _release_split_command(command: str) -> list[str]:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.split()
    cleaned = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
            cleaned.append(part[1:-1])
        else:
            cleaned.append(part)
    return cleaned


def _release_command_argv(command: str, venv_python: Path) -> tuple[list[str], bool]:
    stripped = command.strip()
    lower = stripped.lower()
    if lower == "manage.py" or lower.startswith("manage.py "):
        return [str(venv_python), *_release_split_command(stripped)], True
    if lower == "python" or lower.startswith("python ") or lower.startswith("py "):
        parts = _release_split_command(stripped)
        if parts and parts[0].lower() in {"python", "py"}:
            parts = parts[1:]
        return [str(venv_python), *parts], True
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", stripped], False


def _release_terminal_env(environment: str, django_app: Path) -> dict[str, str]:
    env_root = _release_env_root(environment)
    venv_scripts = env_root / "venv" / "Scripts"
    env_vars = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "PYTHONPATH": str(django_app),
        "PORTAL_SKIP_RUNTIME_BOOTSTRAP": "1",
        "PORTAL_ENV_ROOT": str(env_root),
        "STATIC_ROOT": str(env_root / "static"),
        "MEDIA_ROOT": str(env_root / "media"),
    }
    env_vars["PATH"] = f"{venv_scripts};{env_vars.get('PATH', '')}"
    return env_vars


def _release_ops_context() -> dict[str, object]:
    current_env = _release_current_environment()
    base_dir = _release_deploy_base_dir()
    envs = []
    for env in ("test", "prod"):
        env_root = base_dir / env
        django_app = _release_resolve_django_app(env)
        envs.append(
            {
                "value": env,
                "label": env.upper(),
                "site_name": _release_site_name(env),
                "restart_task_name": _release_iis_restart_task_name(env),
                "env_root": str(env_root),
                "django_app": str(django_app) if django_app else "",
                "has_current": bool(django_app),
            }
        )
    return {
        "deploy_base": str(base_dir),
        "current_environment": current_env,
        "environments": envs,
        "terminal_presets": [
            {"label": "Django check", "command": "manage.py check --settings=config.settings.prod"},
            {"label": "Stato migrations", "command": "manage.py showmigrations --settings=config.settings.prod"},
            {"label": "Migrate", "command": "manage.py migrate --settings=config.settings.prod --noinput"},
            {"label": "Allinea schema runtime", "command": "manage.py ensure_legacy_schema --settings=config.settings.prod"},
            {"label": "Collectstatic dry-run", "command": "manage.py collectstatic --dry-run --noinput --clear --settings=config.settings.prod -v 0"},
            {"label": "ACL dry-run", "command": "manage.py bootstrap_acl_v2 --dry-run --settings=config.settings.prod"},
            {"label": "Seed descrizioni pulsanti", "command": "manage.py seed_pulsanti_descrizioni --settings=config.settings.prod"},
            {"label": "Tail waitress log", "command": r'Get-Content "$env:PORTAL_ENV_ROOT\logs\waitress_stdout.log" -Tail 80'},
        ],
        "terminal_timeout_seconds": _RELEASE_TERMINAL_DEFAULT_TIMEOUT,
    }


def _release_access_denied(text: object) -> bool:
    value = str(text or "").lower()
    return any(
        marker in value
        for marker in (
            "winerror 5",
            "access is denied",
            "accesso negato",
            "unauthorizedaccessexception",
            "permission denied",
        )
    )


def _release_process_restart_payload(environment: str, site_name: str, pool_name: str, reason: str) -> dict[str, object] | None:
    if not _helpers._release_schedule_process_restart():
        return None
    message = (
        "Accesso negato al riavvio IIS. Ho schedulato il riavvio del processo Django/Waitress; "
        "HttpPlatformHandler lo riavviera' alla prossima richiesta."
    )
    return {
        "ok": True,
        "service_ok": True,
        "environment": environment,
        "site_name": site_name,
        "pool_name": pool_name,
        "returncode": 0,
        "stdout": message,
        "stderr": "",
        "scheduled": True,
        "fallback_used": True,
        "restart_mode": "django_process",
        "warning": reason,
        "error": "",
    }


def _release_start_iis_restart_task(environment: str) -> tuple[bool, subprocess.CompletedProcess[str]]:
    task_path = _RELEASE_IIS_TASK_FOLDER + "\\"
    task_name = _release_iis_restart_task_short_name(environment)
    full_task_name = _release_iis_restart_task_name(environment)
    ps = f"""
$taskPath = '{task_path}'
$taskName = '{task_name}'
$task = Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {{
    Write-Output "Task restart IIS non configurato: {full_task_name}"
    exit 3
}}
Start-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction Stop
Write-Output "Task restart IIS avviato: {full_task_name}"
"""
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=_release_creationflags(),
    )
    return proc.returncode == 0, proc


@legacy_admin_required
def crea_release(request):

    repo_root = Path(settings.BASE_DIR).parent
    script_path = repo_root / "deployment" / "scripts" / "package-release.ps1"
    package_timeout_seconds = 900
    package_timeout_minutes = package_timeout_seconds // 60

    # Directory pacchetti: shared/packages se esiste, altrimenti releases/ nella repo
    shared_packages = Path("C:/PortaleNovicrom/shared/packages")
    releases_dir = repo_root / "releases"

    def _list_packages():
        pkgs = []
        for pkg_dir in [shared_packages, releases_dir]:
            if pkg_dir.exists():
                for f in sorted(pkg_dir.glob("portale-novicrom-*.zip"), reverse=True)[:10]:
                    pkgs.append({
                        "name": f.name,
                        "path": str(f),
                        "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    })
        return pkgs

    result = None
    if request.method == "POST":
        if not script_path.exists():
            result = {"ok": False, "error": f"Script non trovato: {script_path}"}
        else:
            try:
                proc = subprocess.run(
                    ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=package_timeout_seconds,
                    cwd=str(script_path.parent),
                )
                stdout = proc.stdout.strip()
                stderr = proc.stderr.strip()
                ok = proc.returncode == 0
                zip_path = None
                for line in reversed(stdout.splitlines()):
                    line = line.strip()
                    if line.endswith(".zip") and Path(line).exists():
                        zip_path = line
                        break
                result = {
                    "ok": ok,
                    "stdout": stdout,
                    "stderr": stderr,
                    "zip_path": zip_path,
                    "zip_name": Path(zip_path).name if zip_path else None,
                    "zip_size_mb": round(Path(zip_path).stat().st_size / (1024 * 1024), 1) if zip_path else None,
                }
                if ok and zip_path:
                    _helpers._audit_safe(request, "crea_release", "admin_portale", {"zip": zip_path})
            except subprocess.TimeoutExpired as exc:
                result = {
                    "ok": False,
                    "error": f"Timeout: lo script ha impiegato troppo tempo (>{package_timeout_minutes} min)",
                    "stdout": (exc.stdout or "").strip(),
                    "stderr": (exc.stderr or "").strip(),
                }
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}

    return render(request, "admin_portale/pages/crea_release.html", {
        "packages": _list_packages(),
        "result": result,
        "script_path": str(script_path),
        "script_exists": script_path.exists(),
        "app_version": getattr(settings, "APP_VERSION", ""),
        "package_timeout_minutes": package_timeout_minutes,
        "release_ops": _release_ops_context(),
    })


@legacy_admin_required
@require_GET
def download_release_package(request):
    from django.http import FileResponse, Http404

    pkg_path = request.GET.get("path", "").strip()
    if not pkg_path:
        raise Http404
    f = Path(pkg_path)
    # Sicurezza: accetta solo zip con il prefisso atteso
    if not f.exists() or not f.suffix == ".zip" or not f.name.startswith("portale-novicrom-"):
        raise Http404
    return FileResponse(open(f, "rb"), as_attachment=True, filename=f.name)


@sensitive_admin_operation_required("release_restart_service")
@csrf_protect
@require_POST
def api_release_restart_service(request):
    payload = _helpers._post_or_json_payload(request)
    environment = _normalize_release_environment(payload.get("environment"))
    site_name = _release_site_name(environment)
    pool_name = site_name

    try:
        task_started, task_proc = _release_start_iis_restart_task(environment)
    except subprocess.TimeoutExpired as exc:
        task_started = False
        task_proc = subprocess.CompletedProcess(
            args=[],
            returncode=124,
            stdout=(exc.stdout or ""),
            stderr=(exc.stderr or "Timeout avvio task restart IIS."),
        )
    except Exception as exc:
        if _release_access_denied(exc):
            fallback_payload = _release_process_restart_payload(environment, site_name, pool_name, str(exc))
            if fallback_payload:
                _helpers._audit_safe(
                    request,
                    "release_restart_process_fallback",
                    "admin_portale",
                    {
                        "environment": environment,
                        "site_name": site_name,
                        "reason": str(exc),
                        "source": "scheduled_task",
                    },
                )
                return JsonResponse(fallback_payload, status=200)
        task_started = False
        task_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=str(exc))

    task_stdout = (task_proc.stdout or "").strip()
    task_stderr = (task_proc.stderr or "").strip()
    task_output = "\n".join(part for part in (task_stdout, task_stderr) if part)
    if task_started:
        _helpers._audit_safe(
            request,
            "release_restart_scheduled_task",
            "admin_portale",
            {
                "environment": environment,
                "site_name": site_name,
                "task_name": _release_iis_restart_task_name(environment),
            },
        )
        return JsonResponse(
            {
                "ok": True,
                "service_ok": True,
                "environment": environment,
                "site_name": site_name,
                "pool_name": pool_name,
                "task_name": _release_iis_restart_task_name(environment),
                "returncode": task_proc.returncode,
                "stdout": task_stdout,
                "stderr": task_stderr,
                "scheduled": True,
                "restart_mode": "scheduled_task",
                "error": "",
            },
            status=200,
        )
    if _release_access_denied(task_output):
        fallback_payload = _release_process_restart_payload(environment, site_name, pool_name, task_output)
        if fallback_payload:
            _helpers._audit_safe(
                request,
                "release_restart_process_fallback",
                "admin_portale",
                {
                    "environment": environment,
                    "site_name": site_name,
                    "returncode": task_proc.returncode,
                    "reason": task_output,
                    "source": "scheduled_task",
                },
            )
            return JsonResponse(fallback_payload, status=200)

    restart_script = f"""
Start-Sleep -Seconds 2
Import-Module WebAdministration -ErrorAction Stop
$siteName = '{site_name}'
$poolName = '{pool_name}'
$hadError = $false

$site = Get-Website -Name $siteName -ErrorAction SilentlyContinue
$pool = Get-WebAppPool -Name $poolName -ErrorAction SilentlyContinue

if (-not $pool) {{
    Write-Output "App Pool non trovato: $poolName"
    $hadError = $true
}} else {{
    Stop-WebAppPool -Name $poolName -ErrorAction SilentlyContinue
    Start-WebAppPool -Name $poolName -ErrorAction Stop
    Write-Output "App Pool riavviato: $poolName"
}}

if (-not $site) {{
    Write-Output "Sito IIS non trovato: $siteName"
    $hadError = $true
}} else {{
    Stop-Website -Name $siteName -ErrorAction SilentlyContinue
    Start-Website -Name $siteName -ErrorAction Stop
    Write-Output "Sito riavviato: $siteName"
}}

if ($hadError) {{ exit 2 }}
"""
    encoded_restart = base64.b64encode(restart_script.encode("utf-16le")).decode("ascii")
    ps = f"""
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-EncodedCommand',
    '{encoded_restart}'
)
Write-Output "Riavvio schedulato per {site_name}. La pagina potrebbe perdere connessione per qualche secondo."
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=_release_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": "Timeout durante il riavvio del servizio.",
                "stdout": (exc.stdout or "").strip(),
                "stderr": (exc.stderr or "").strip(),
            },
            status=504,
        )
    except Exception as exc:
        if _release_access_denied(exc):
            fallback_payload = _release_process_restart_payload(environment, site_name, pool_name, str(exc))
            if fallback_payload:
                _helpers._audit_safe(
                    request,
                    "release_restart_process_fallback",
                    "admin_portale",
                    {
                        "environment": environment,
                        "site_name": site_name,
                        "reason": str(exc),
                    },
                )
                return JsonResponse(fallback_payload, status=200)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    ok = proc.returncode == 0
    combined_output = "\n".join(part for part in (stdout, stderr) if part)
    if not ok and _release_access_denied(combined_output):
        fallback_payload = _release_process_restart_payload(environment, site_name, pool_name, combined_output)
        if fallback_payload:
            _helpers._audit_safe(
                request,
                "release_restart_process_fallback",
                "admin_portale",
                {
                    "environment": environment,
                    "site_name": site_name,
                    "returncode": proc.returncode,
                    "reason": combined_output,
                },
            )
            return JsonResponse(fallback_payload, status=200)

    _helpers._audit_safe(
        request,
        "release_restart_service",
        "admin_portale",
        {
            "environment": environment,
            "site_name": site_name,
            "returncode": proc.returncode,
            "ok": ok,
        },
    )
    return JsonResponse(
        {
            "ok": True,
            "service_ok": ok,
            "environment": environment,
            "site_name": site_name,
            "pool_name": pool_name,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "scheduled": ok,
            "error": "" if ok else (stderr or stdout or f"PowerShell ha restituito codice {proc.returncode}."),
        },
        status=200,
    )


@sensitive_admin_operation_required("release_terminal_command")
@csrf_protect
@require_POST
def api_release_terminal_command(request):
    payload = _helpers._post_or_json_payload(request)
    environment = _normalize_release_environment(payload.get("environment"))
    command = str(payload.get("command") or "").strip()
    if not command:
        return JsonResponse({"ok": False, "error": "Comando mancante."}, status=400)

    timeout_seconds = _helpers._int_or_none(payload.get("timeout_seconds")) or _RELEASE_TERMINAL_DEFAULT_TIMEOUT
    timeout_seconds = max(5, min(timeout_seconds, _RELEASE_TERMINAL_MAX_TIMEOUT))
    env_root = _release_env_root(environment)
    django_app = _release_resolve_django_app(environment)
    if not django_app:
        return JsonResponse(
            {
                "ok": False,
                "error": f"Release corrente non trovata per {environment.upper()}: manca current\\django_app.",
                "environment": environment,
                "env_root": str(env_root),
            },
            status=400,
        )

    venv_python = env_root / "venv" / "Scripts" / "python.exe"
    argv, needs_venv = _release_command_argv(command, venv_python)
    if needs_venv and not venv_python.exists():
        return JsonResponse(
            {
                "ok": False,
                "error": f"Virtualenv non trovato: {venv_python}",
                "environment": environment,
                "env_root": str(env_root),
            },
            status=400,
        )

    try:
        proc = subprocess.run(
            argv,
            cwd=str(django_app),
            env=_release_terminal_env(environment, django_app),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=_release_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        _helpers._audit_safe(
            request,
            "release_terminal_timeout",
            "admin_portale",
            {"environment": environment, "command": command, "timeout_seconds": timeout_seconds},
        )
        return JsonResponse(
            {
                "ok": False,
                "error": f"Timeout: comando oltre {timeout_seconds} secondi.",
                "stdout": (exc.stdout or "").strip(),
                "stderr": (exc.stderr or "").strip(),
                "environment": environment,
                "cwd": str(django_app),
            },
            status=504,
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    ok = proc.returncode == 0
    _helpers._audit_safe(
        request,
        "release_terminal_command",
        "admin_portale",
        {
            "environment": environment,
            "command": command,
            "returncode": proc.returncode,
            "ok": ok,
        },
    )
    return JsonResponse(
        {
            "ok": True,
            "command_ok": ok,
            "environment": environment,
            "cwd": str(django_app),
            "argv": argv,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "error": "" if ok else (stderr or stdout or f"Comando terminato con codice {proc.returncode}."),
        },
        status=200,
    )
