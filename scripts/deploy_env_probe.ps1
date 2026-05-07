<#
.SYNOPSIS
    deploy_env_probe.ps1 - Probe configurazione runtime per NOVICROM HUB.

.DESCRIPTION
    Carica le variabili dal web.config (httpPlatform/environmentVariables)
    quando presente, le applica al processo corrente, poi esegue un probe
    Django (settings.DATABASES, DEBUG, SECRET_KEY, log dir).

    Mai stampa o scrive valori segreti. Per i nomi sensibili noti riporta
    soltanto <set len=N> o <missing>.

    Compatibile Windows PowerShell 5.1+.

.PARAMETER ProjectRoot
    Root del repo (deve contenere django_app\manage.py).

.PARAMETER SettingsModule
    Modulo settings Django, default config.settings.prod.

.PARAMETER PythonExe
    Eseguibile Python (default 'python' nel PATH).

.PARAMETER WebConfigPath
    Path esplicito a web.config. Se non passato lo script cerca in
    <ProjectRoot>\web.config e <ProjectRoot>\django_app\web.config.

.PARAMETER RequireProd
    Se presente, blocca quando DEBUG=True, SECRET_KEY placeholder o len<32.

.PARAMETER ReportPath
    File di log opzionale: lo script appenderà righe redatte (UTF-8).

.EXAMPLE
    .\deploy_env_probe.ps1 -ProjectRoot 'C:\Dev\Portale Novicrom'

.EXAMPLE
    .\deploy_env_probe.ps1 -ProjectRoot C:\inetpub\novicrom -RequireProd -ReportPath C:\logs\probe.log

.NOTES
    Version: 1.0.0
    Security: i nomi sensibili (SECRET_KEY, *_PASSWORD, *_TOKEN, *_SECRET,
              API_KEY, *PRIVATE*) non sono mai loggati in chiaro.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $false)]
    [string]$SettingsModule = 'config.settings.prod',

    [Parameter(Mandatory = $false)]
    [string]$PythonExe = 'python',

    [Parameter(Mandatory = $false)]
    [string]$WebConfigPath,

    [Parameter(Mandatory = $false)]
    [switch]$RequireProd,

    [Parameter(Mandatory = $false)]
    [string]$ReportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptVersion = '1.0.0'

# Pattern per riconoscere nomi sensibili (case-insensitive, sub-string match)
$SensitivePatterns = @(
    'SECRET_KEY',
    'DJANGO_SECRET_KEY',
    'PASSWORD',
    'CLIENT_SECRET',
    'TOKEN',
    'API_KEY',
    'GRAPH_CLIENT_SECRET',
    'PRIVATE'
)

function Write-ProbeLog {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Message
    )
    Write-Host $Message
    if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
        try {
            Add-Content -Path $ReportPath -Value $Message -Encoding utf8
        } catch {
            Write-Host "[PROBE][WARN] Report append failed: $($_.Exception.Message)"
        }
    }
}

function Test-IsSensitiveName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    $upper = $Name.ToUpperInvariant()
    foreach ($p in $SensitivePatterns) {
        if ($upper.Contains($p)) {
            return $true
        }
    }
    return $false
}

function Format-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [AllowEmptyString()]
        [string]$Value
    )

    $isSensitive = Test-IsSensitiveName -Name $Name
    if ($null -eq $Value -or $Value.Length -eq 0) {
        return '<missing>'
    }

    if ($isSensitive) {
        return "<set len=$($Value.Length)>"
    }

    # Per i non-sensibili limitiamo a 120 char e rimuoviamo newline
    $safe = ($Value -replace "[\r\n]+", ' ')
    if ($safe.Length -gt 120) {
        $safe = $safe.Substring(0, 120) + '...'
    }
    return $safe
}

# ---------------------------------------------------------------------------
# Validazione input
# ---------------------------------------------------------------------------

Write-ProbeLog "[PROBE] deploy_env_probe.ps1 v$ScriptVersion"

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    Write-ProbeLog "[PROBE][FAIL] ProjectRoot not found: $ProjectRoot"
    exit 1
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

$managePy = Join-Path $ProjectRoot 'django_app\manage.py'
if (-not (Test-Path -LiteralPath $managePy)) {
    Write-ProbeLog "[PROBE][FAIL] manage.py not found at $managePy"
    exit 1
}

Write-ProbeLog "[PROBE] ProjectRoot: $ProjectRoot"
Write-ProbeLog "[PROBE] SettingsModule: $SettingsModule"
Write-ProbeLog "[PROBE] PythonExe: $PythonExe"
Write-ProbeLog "[PROBE] RequireProd: $([bool]$RequireProd)"

# ---------------------------------------------------------------------------
# Locate web.config
# ---------------------------------------------------------------------------

$resolvedWebConfig = $null
if (-not [string]::IsNullOrWhiteSpace($WebConfigPath)) {
    if (Test-Path -LiteralPath $WebConfigPath) {
        $resolvedWebConfig = (Resolve-Path -LiteralPath $WebConfigPath).Path
    } else {
        Write-ProbeLog "[PROBE][WARN] WebConfigPath provided but not found: $WebConfigPath"
    }
} else {
    $candidates = @(
        (Join-Path $ProjectRoot 'web.config'),
        (Join-Path $ProjectRoot 'django_app\web.config')
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) {
            $resolvedWebConfig = (Resolve-Path -LiteralPath $c).Path
            break
        }
    }
}

if ($null -eq $resolvedWebConfig) {
    Write-ProbeLog "[PROBE][WARN] web.config not found - IIS env override NOT applied. Continuing with current process env."
} else {
    Write-ProbeLog "[PROBE] web.config: $resolvedWebConfig"
    try {
        [xml]$xml = Get-Content -LiteralPath $resolvedWebConfig -Raw -Encoding UTF8
        $envNodes = $xml.SelectNodes('/configuration/system.webServer/httpPlatform/environmentVariables/environmentVariable')
        if ($null -ne $envNodes -and $envNodes.Count -gt 0) {
            Write-ProbeLog "[PROBE] Applying $($envNodes.Count) environment variable(s) from web.config:"
            foreach ($node in $envNodes) {
                $name = [string]$node.GetAttribute('name')
                $value = [string]$node.GetAttribute('value')
                if ([string]::IsNullOrWhiteSpace($name)) { continue }
                # Applica al processo corrente
                Set-Item -Path "env:$name" -Value $value
                $display = Format-EnvValue -Name $name -Value $value
                Write-ProbeLog "[PROBE]   $name = $display"
            }
        } else {
            Write-ProbeLog "[PROBE] web.config parsed but no environmentVariable nodes present."
        }
    } catch {
        Write-ProbeLog "[PROBE][WARN] Failed to parse web.config: $($_.Exception.Message)"
    }
}

# Garantisci che DJANGO_SETTINGS_MODULE sia coerente.
Set-Item -Path 'env:DJANGO_SETTINGS_MODULE' -Value $SettingsModule
Write-ProbeLog "[PROBE] DJANGO_SETTINGS_MODULE set to $SettingsModule"

# ---------------------------------------------------------------------------
# Probe Django via script Python temporaneo
# ---------------------------------------------------------------------------

$djangoAppPath = (Join-Path $ProjectRoot 'django_app')

$probePy = @'
import json
import os
import sys

import django
django.setup()

from django.conf import settings  # noqa: E402

db = settings.DATABASES.get("default", {})

def safe_name(n):
    if not n:
        return "<empty>"
    s = str(n)
    if "\\" in s or "/" in s:
        return os.path.basename(s) or s
    return s

secret_key = str(getattr(settings, "SECRET_KEY", "") or "")
log_dir = str(getattr(settings, "DJANGO_LOG_DIR", "") or os.environ.get("DJANGO_LOG_DIR", ""))

out = {
    "engine": db.get("ENGINE", ""),
    "name": safe_name(db.get("NAME", "")),
    "host": db.get("HOST", "") or "<empty>",
    "user_set": bool(str(db.get("USER", "")).strip()),
    "debug": bool(getattr(settings, "DEBUG", False)),
    "secret_key_len": len(secret_key),
    "secret_key_placeholder": secret_key.lower() in ("", "changeme", "change_me", "change-me-in-dev"),
    "log_dir": log_dir,
    "settings_module": os.environ.get("DJANGO_SETTINGS_MODULE", ""),
    "allowed_hosts_count": len(getattr(settings, "ALLOWED_HOSTS", []) or []),
}
sys.stdout.write("PROBE_JSON:" + json.dumps(out) + "\n")
sys.stdout.flush()
'@

$tempPy = [System.IO.Path]::GetTempFileName()
# GetTempFileName crea .tmp, rinominiamo a .py
$tempPyRenamed = [System.IO.Path]::ChangeExtension($tempPy, '.py')
try {
    Move-Item -LiteralPath $tempPy -Destination $tempPyRenamed -Force
    $tempPy = $tempPyRenamed
} catch {
    # Se rename fallisce, usa il file .tmp comunque
    $tempPyRenamed = $tempPy
}

# Out-File default e' UTF-16 BOM: forziamo utf8.
$probePy | Out-File -FilePath $tempPy -Encoding utf8 -Force

$probeJson = $null
$probeRaw = ''
$exitCode = 0

# Defense-in-depth: prima di logging, applica redaction su pattern che
# assomigliano a segreti (PWD=..., SECRET=..., TOKEN=..., Bearer ..., etc).
# Anche se lo script Python interno non stampa segreti, traceback o errori
# di driver DB possono includere connection string o env values.
function Get-RedactedRawOutput {
    param([string]$Raw)
    if ([string]::IsNullOrEmpty($Raw)) { return $Raw }
    $patterns = @(
        '(?i)(password|pwd|secret|token|api[_-]?key|client[_-]?secret|private[_-]?key)\s*[:=]\s*[^\s;,"'']+',
        '(?i)Bearer\s+[A-Za-z0-9._\-]+',
        '(?i)Authorization\s*[:=]\s*[^\s]+'
    )
    $out = $Raw
    foreach ($p in $patterns) {
        $out = [regex]::Replace($out, $p, '<redacted>')
    }
    return $out
}

# Salva PYTHONPATH originale per ripristino
$prevPythonPath = $env:PYTHONPATH

try {
    # Path a django_app deve essere prima nel PYTHONPATH
    $env:PYTHONPATH = $djangoAppPath
    Push-Location $djangoAppPath
    try {
        # NOTE PS 5.1: con $ErrorActionPreference='Stop' la redirezione 2>&1
        # da exe native (Python emette log INFO su stderr) genera ErrorRecord
        # NativeCommandError che fa terminare lo script. Sospendiamo Stop
        # solo per la chiamata, controlliamo $LASTEXITCODE e ripristiniamo.
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $probeRaw = & $PythonExe $tempPy 2>&1 | Out-String
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevEAP
        }
    } finally {
        Pop-Location
    }
} finally {
    if (Test-Path -LiteralPath $tempPy) {
        try { Remove-Item -LiteralPath $tempPy -Force -ErrorAction SilentlyContinue } catch { }
    }
    # Ripristina PYTHONPATH per non sporcare la sessione padre
    $env:PYTHONPATH = $prevPythonPath
}

if ($exitCode -ne 0) {
    Write-ProbeLog "[PROBE][FAIL] Django probe exited with code $exitCode"
    Write-ProbeLog "[PROBE] Raw output (first 2KB, redacted):"
    $hint = Get-RedactedRawOutput -Raw $probeRaw
    if ($hint.Length -gt 2048) { $hint = $hint.Substring(0, 2048) + '...' }
    Write-ProbeLog $hint
    exit 1
}

# Estrai la riga PROBE_JSON:...
$probeLine = $null
foreach ($line in ($probeRaw -split "`n")) {
    $trim = $line.Trim()
    if ($trim.StartsWith('PROBE_JSON:')) {
        $probeLine = $trim.Substring('PROBE_JSON:'.Length)
        break
    }
}

if ($null -eq $probeLine) {
    Write-ProbeLog "[PROBE][FAIL] PROBE_JSON marker not found in Django output."
    Write-ProbeLog "[PROBE] Raw output (first 2KB, redacted):"
    $hint = Get-RedactedRawOutput -Raw $probeRaw
    if ($hint.Length -gt 2048) { $hint = $hint.Substring(0, 2048) + '...' }
    Write-ProbeLog $hint
    exit 1
}

try {
    $probeJson = $probeLine | ConvertFrom-Json
} catch {
    Write-ProbeLog "[PROBE][FAIL] Unable to parse PROBE_JSON: $($_.Exception.Message)"
    exit 1
}

# ---------------------------------------------------------------------------
# Validazioni
# ---------------------------------------------------------------------------

$failures = @()
$warnings = @()

# Engine
if ([string]::IsNullOrWhiteSpace([string]$probeJson.engine)) {
    $failures += 'DATABASES.default.ENGINE is empty'
}

# DEBUG / placeholder solo in prod
if ($RequireProd) {
    if ($probeJson.debug) {
        $failures += 'DEBUG=True is forbidden in prod'
    }
    if ($probeJson.secret_key_placeholder) {
        $failures += 'SECRET_KEY is a placeholder/empty value'
    }
    if ([int]$probeJson.secret_key_len -lt 32) {
        $failures += "SECRET_KEY too short (len=$($probeJson.secret_key_len), required >=32)"
    }
}

# log_dir
$logDir = [string]$probeJson.log_dir
if ([string]::IsNullOrWhiteSpace($logDir)) {
    $warnings += 'DJANGO_LOG_DIR is empty (deploy_guard may create one)'
} elseif (-not (Test-Path -LiteralPath $logDir)) {
    $warnings += "DJANGO_LOG_DIR does not exist: $logDir"
}

# ---------------------------------------------------------------------------
# Output redatto
# ---------------------------------------------------------------------------

Write-ProbeLog ''
Write-ProbeLog '[PROBE] === Django runtime probe ==='

$summary = [PSCustomObject]@{
    settings_module        = [string]$probeJson.settings_module
    db_engine              = [string]$probeJson.engine
    db_name                = [string]$probeJson.name
    db_host                = [string]$probeJson.host
    db_user_set            = [bool]$probeJson.user_set
    debug                  = [bool]$probeJson.debug
    secret_key_len         = [int]$probeJson.secret_key_len
    secret_key_placeholder = [bool]$probeJson.secret_key_placeholder
    log_dir                = $logDir
    allowed_hosts_count    = [int]$probeJson.allowed_hosts_count
}

$tableText = ($summary | Format-List | Out-String).Trim()
Write-ProbeLog $tableText

if ($warnings.Count -gt 0) {
    Write-ProbeLog ''
    Write-ProbeLog '[PROBE][WARN] Warnings:'
    foreach ($w in $warnings) {
        Write-ProbeLog "  - $w"
    }
}

if ($failures.Count -gt 0) {
    Write-ProbeLog ''
    Write-ProbeLog '[PROBE][FAIL] Validation failures:'
    foreach ($f in $failures) {
        Write-ProbeLog "  - $f"
    }
    Write-ProbeLog '[PROBE] RESULT: FAIL'
    exit 1
}

Write-ProbeLog ''
Write-ProbeLog '[PROBE] RESULT: OK'
exit 0
