"""Fotografia della macchina per ricostruirla: IIS, task, prerequisiti, versioni, identità.

Solo Windows (altrove la sezione è ``unsupported``). Mai segreti: delle variabili
``.env`` solo i nomi, delle chiavi solo l'impronta, dei certificati solo il
thumbprint. Ogni raccolta è isolata: un comando che fallisce lascia un avviso,
non interrompe il resto.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

from django.conf import settings

from . import manifest as mf

APPCMD = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "inetsrv" / "appcmd.exe"


def _run(args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, f"{exc.__class__.__name__}: {exc}"


def _ps(script: str, timeout: int = 60) -> tuple[int, str]:
    return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def _env_name_suffix(env: str) -> str:
    return env.upper()


def public_hostnames() -> list[str]:
    names = []
    canonical = str(getattr(settings, "HUB_PUBLIC_HOSTNAME", "") or "").strip().lower()
    if canonical:
        names.append(canonical)
    names += [h for h in getattr(settings, "HUB_ALT_HOSTNAMES", []) or [] if h and h not in names]
    return names


def resolve(hostname: str) -> list[str]:
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(hostname, None)})
    except OSError:
        return []


def local_addresses() -> set[str]:
    addrs = {"127.0.0.1", "::1"}
    for name in {socket.gethostname(), socket.getfqdn()}:
        addrs.update(resolve(name))
    return addrs


def spn_check(hostname: str) -> dict:
    code, out = _run(["setspn", "-Q", f"HTTP/{hostname}"], timeout=30)
    found = "Existing SPN found" in out or "SPN esistente trovato" in out
    owner = ""
    if found:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        owner = next((ln for ln in lines if ln.upper().startswith("CN=")), "")
    return {"spn": f"HTTP/{hostname}", "found": found, "owner_dn": owner, "exit": code}


def find_release_zip(build_info: dict) -> Path | None:
    """Zip del pacchetto attivo in shared\\packages, riconosciuto dal commit nel BUILD_INFO interno."""
    commit = (build_info or {}).get("commit")
    if not commit:
        return None
    packages = Path(settings.BASE_DIR).resolve().parents[2] / "shared" / "packages" \
        if len(Path(settings.BASE_DIR).resolve().parents) > 2 else None
    if not packages or not packages.exists():
        return None
    for zp in sorted(packages.glob("portale-novicrom-v*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(zp) as z:
                name = next((n for n in z.namelist() if n.endswith("BUILD_INFO.json") and n.count("/") <= 1), None)
                if name and json.loads(z.read(name).decode("utf-8-sig")).get("commit") == commit:
                    return zp
        except (OSError, zipfile.BadZipFile, ValueError):
            continue
    return None


def collect(env: str, out_dir: Path) -> tuple[dict, list[str]]:
    """Scrive ``host-manifest.json`` + export XML in ``out_dir``; restituisce (dati, avvisi)."""
    from core.build_info import read_build_info

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    build = read_build_info() or {}
    data: dict = {
        "schema_version": 1,
        "env": env,
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "domain": os.environ.get("USERDNSDOMAIN", ""),
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version()},
        "python": {"version": sys.version.split()[0], "executable": sys.executable},
        "paths": {"deploy_base": str(Path(settings.BASE_DIR).resolve().parents[2])
                  if len(Path(settings.BASE_DIR).resolve().parents) > 2 else "",
                  "base_dir": str(settings.BASE_DIR), "media_root": str(settings.MEDIA_ROOT)},
        "release": {k: build.get(k) for k in ("version", "commit", "branch", "built_at", "source", "dirty")},
        "keys": mf.keys_section(),
        "public_hostnames": [],
        "windows_sso": {
            "hostname": getattr(settings, "WINDOWS_SSO_HOSTNAME", ""),
            "service": getattr(settings, "WINDOWS_SSO_SERVICE", ""),
        },
        "ollama_base_url": getattr(settings, "OLLAMA_BASE_URL", ""),
        "unc_paths": [],
    }
    try:
        import pyodbc

        data["odbc_drivers"] = sorted(pyodbc.drivers())
    except Exception as exc:
        warnings.append(f"driver ODBC non letti: {exc}")
    tess = str(getattr(settings, "TESSERACT_CMD", "") or "")
    if tess:
        code, out = _run([tess, "--version"], timeout=20)
        data["tesseract"] = {"cmd": tess, "version": out.splitlines()[0] if out else "", "exit": code}

    for share_setting in ("PROCEDURE_REFRESH_SGI_SHARE_ROOT", "OLLAMA_RAG_SGI_ROOT", "OLLAMA_RAG_SGI_SHARE"):
        value = str(getattr(settings, share_setting, "") or "")
        if value:
            data["unc_paths"].append({"setting": share_setting, "path": value,
                                      "accessible_by_current_user": Path(value).exists()})

    for name in public_hostnames():
        ips = resolve(name)
        data["public_hostnames"].append({
            "name": name, "resolves_to": ips, "points_here": bool(set(ips) & local_addresses()),
            "in_allowed_hosts": name in [h.lower() for h in settings.ALLOWED_HOSTS] or "*" in settings.ALLOWED_HOSTS,
            "in_csrf_trusted_origins": any(name in str(o).lower() for o in getattr(settings, "CSRF_TRUSTED_ORIGINS", [])),
        })

    if platform.system() != "Windows":
        data["windows"] = "unsupported"
        _write(out_dir / "host-manifest.json", data)
        return data, warnings

    site = f"PortaleNovicrom-{_env_name_suffix(env)}"
    (out_dir / "iis").mkdir(exist_ok=True)
    if APPCMD.exists():
        for kind, args in (("site", ["list", "site", site, "/config", "/xml"]),
                           ("apppool", ["list", "apppool", site, "/config", "/xml"])):
            code, out = _run([str(APPCMD)] + args)
            if code == 0:
                (out_dir / "iis" / f"{kind}.xml").write_text(out, encoding="utf-8")
            else:
                warnings.append(f"appcmd {kind}: exit {code}")
        code, out = _run([str(APPCMD), "list", "apppool", site, "/text:processModel.identityType"])
        data["iis_apppool_identity_type"] = out.strip() if code == 0 else ""
        code, out = _run([str(APPCMD), "list", "apppool", site, "/text:processModel.userName"])
        data["iis_apppool_user"] = out.strip() if code == 0 else ""
        code, out = _run([str(APPCMD), "list", "site", site, "/text:bindings"])
        data["iis_bindings"] = out.strip() if code == 0 else ""
    else:
        warnings.append("appcmd.exe non trovato: export IIS saltato")

    code, out = _ps(
        "Get-ChildItem Cert:\\LocalMachine\\My | Select-Object Thumbprint,Subject,NotAfter,"
        "@{n='Dns';e={($_.DnsNameList | ForEach-Object { $_.Unicode }) -join ','}} | ConvertTo-Json -Compress"
    )
    if code == 0 and out.strip():
        try:
            certs = json.loads(out)
            data["certificates"] = certs if isinstance(certs, list) else [certs]
        except ValueError:
            warnings.append("elenco certificati non leggibile")

    (out_dir / "tasks").mkdir(exist_ok=True)
    code, out = _ps(
        "Get-ScheduledTask | Where-Object { $_.TaskName -like 'PortaleNovicrom*' -or $_.TaskPath -like '\\PortaleNovicrom\\*' "
        "-or $_.TaskName -like 'QCluster*' } | Select-Object TaskPath,TaskName,State,"
        "@{n='User';e={$_.Principal.UserId}},@{n='LogonType';e={[string]$_.Principal.LogonType}} | ConvertTo-Json -Compress"
    )
    tasks = []
    if code == 0 and out.strip():
        try:
            parsed = json.loads(out)
            tasks = parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            warnings.append("elenco task non leggibile")
    data["scheduled_tasks"] = tasks
    for t in tasks:
        name = str(t.get("TaskName", ""))
        path = str(t.get("TaskPath", "\\"))
        code, xml = _ps(f"Export-ScheduledTask -TaskPath '{path}' -TaskName '{name}'")
        if code == 0:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{path}{name}".strip("\\"))
            (out_dir / "tasks" / f"{safe}.xml").write_text(xml, encoding="utf-8")

    data["spn"] = [spn_check(h) for h in public_hostnames()]
    if data["windows_sso"]["hostname"] and data["windows_sso"]["hostname"].lower() not in public_hostnames():
        data["spn"].append(spn_check(data["windows_sso"]["hostname"]))

    code, out = _ps("Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion' | "
                    "Select-Object ProductName,DisplayVersion,CurrentBuild,EditionID | ConvertTo-Json -Compress")
    if code == 0 and out.strip():
        try:
            data["windows"] = json.loads(out)
        except ValueError:
            pass
    code, out = _ps("Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\IIS Extensions\\*' -ErrorAction SilentlyContinue | "
                    "Select-Object PSChildName,Version | ConvertTo-Json -Compress")
    if code == 0 and out.strip():
        try:
            data["iis_extensions"] = json.loads(out)
        except ValueError:
            pass

    _write(out_dir / "host-manifest.json", data)
    return data, warnings


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
