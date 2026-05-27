<#
.SYNOPSIS
    Protegge i file .env runtime di un ambiente Portale Novicrom.

.DESCRIPTION
    Rimuove l'ereditarieta NTFS dai file .env sensibili e concede accesso solo a:
    - SYSTEM
    - Administrators locali
    - identita IIS AppPool dell'ambiente

    Il file persistente ENV\config\.env resta scrivibile dall'AppPool per le
    pagine admin che salvano configurazioni runtime. Le copie dentro le release
    sono solo leggibili dall'AppPool.
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test", "prod")]
    [string]$Environment,

    [ValidateSet("Read", "Modify")]
    [string]$ConfigEnvAppPoolRights = "Modify",

    [string[]]$AdditionalEnvPath = @(),

    [switch]$AllReleases,

    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin
Assert-ValidEnvironment -Env $Environment

$paths = Get-EnvPaths -Env $Environment
$envUpper = $Environment.ToUpperInvariant()
$appPoolName = "PortaleNovicrom-$envUpper"
$appPoolIdentity = "IIS AppPool\$appPoolName"

function Write-SecureEnvLog {
    param([string]$Message, [string]$Level = "INFO")
    if (-not $Quiet) {
        Write-Log $Message $Level
    }
}

function Invoke-Icacls {
    param([string[]]$Arguments)
    & icacls.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Protect-ConfigDirectory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        Write-SecureEnvLog "Cartella config non trovata: $Path" "WARN"
        return
    }

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    Invoke-Icacls @(
        $resolved,
        "/inheritance:r",
        "/grant:r", "*S-1-5-18:(OI)(CI)(F)",
        "/grant:r", "*S-1-5-32-544:(OI)(CI)(F)",
        "/grant:r", "${appPoolIdentity}:(OI)(CI)(RX)",
        "/remove:g", "*S-1-1-0",
        "/remove:g", "*S-1-5-11",
        "/remove:g", "*S-1-5-32-545",
        "/C",
        "/Q"
    )
    Write-SecureEnvLog "ACL config protetta: $resolved" "SUCCESS"
}

function Protect-EnvFile {
    param(
        [string]$Path,
        [ValidateSet("Read", "Modify")]
        [string]$AppPoolRights
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-SecureEnvLog "File .env non trovato: $Path" "WARN"
        return
    }

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $rights = if ($AppPoolRights -eq "Modify") { "M" } else { "R" }
    Invoke-Icacls @(
        $resolved,
        "/inheritance:r",
        "/grant:r", "*S-1-5-18:(F)",
        "/grant:r", "*S-1-5-32-544:(F)",
        "/grant:r", "${appPoolIdentity}:($rights)",
        "/remove:g", "*S-1-1-0",
        "/remove:g", "*S-1-5-11",
        "/remove:g", "*S-1-5-32-545",
        "/C",
        "/Q"
    )
    Write-SecureEnvLog "ACL .env protetta ($AppPoolRights): $resolved" "SUCCESS"
}

Protect-ConfigDirectory -Path $paths.Config
Protect-EnvFile -Path (Join-Path $paths.Config ".env") -AppPoolRights $ConfigEnvAppPoolRights

$releaseEnvPaths = @()
$currentEnv = Join-Path $paths.Current "django_app\.env"
if (Test-Path -LiteralPath $currentEnv -PathType Leaf) {
    $releaseEnvPaths += $currentEnv
}

foreach ($extra in $AdditionalEnvPath) {
    if ($extra) {
        $releaseEnvPaths += $extra
    }
}

if ($AllReleases -and (Test-Path -LiteralPath $paths.Releases -PathType Container)) {
    Get-ChildItem -LiteralPath $paths.Releases -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $candidate = Join-Path $_.FullName "django_app\.env"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $releaseEnvPaths += $candidate
        }
    }
}

$seen = @{}
foreach ($envPath in $releaseEnvPaths) {
    $key = $envPath.ToLowerInvariant()
    if ($seen.ContainsKey($key)) {
        continue
    }
    $seen[$key] = $true
    Protect-EnvFile -Path $envPath -AppPoolRights "Read"
}

Write-SecureEnvLog "Hardening .env completato per $Environment." "SUCCESS"
