<#
.SYNOPSIS
    Riavvia sito e App Pool IIS per un ambiente NOVICROM HUB.

.DESCRIPTION
    Runner pensato per Task Scheduler. Viene eseguito come SYSTEM dal task
    registrato da register-iis-restart-helper.ps1, cosi il portale web puo
    richiedere il riavvio senza dare privilegi amministrativi all'App Pool.
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test", "prod")]
    [string]$Environment
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-ValidEnvironment -Env $Environment

$paths = Get-EnvPaths -Env $Environment
$envUpper = $Environment.ToUpperInvariant()
$siteName = "PortaleNovicrom-$envUpper"
$appPoolName = "PortaleNovicrom-$envUpper"
$logFile = Join-Path $paths.Logs "iis_restart_helper.log"

if (-not (Test-Path $paths.Logs)) {
    New-Item -ItemType Directory -Path $paths.Logs -Force | Out-Null
}

function Write-HelperLog {
    param([string]$Message, [string]$Level = "INFO")
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Output $line
}

try {
    Write-HelperLog "Restart richiesto per $Environment ($siteName / $appPoolName)" "STEP"
    Import-Module WebAdministration -ErrorAction Stop

    $pool = Get-WebAppPool -Name $appPoolName -ErrorAction SilentlyContinue
    if (-not $pool) {
        throw "App Pool non trovato: $appPoolName"
    }

    $site = Get-Website -Name $siteName -ErrorAction SilentlyContinue
    if (-not $site) {
        throw "Sito IIS non trovato: $siteName"
    }

    try {
        Stop-Website -Name $siteName -ErrorAction SilentlyContinue
        Write-HelperLog "Sito fermato: $siteName" "INFO"
    } catch {
        Write-HelperLog "Stop sito non riuscito/non necessario: $_" "WARN"
    }

    $poolState = (Get-WebAppPoolState -Name $appPoolName -ErrorAction SilentlyContinue).Value
    if ($poolState -eq "Started") {
        Restart-WebAppPool -Name $appPoolName -ErrorAction Stop
        Write-HelperLog "App Pool riciclato: $appPoolName" "SUCCESS"
    } else {
        Start-WebAppPool -Name $appPoolName -ErrorAction Stop
        Write-HelperLog "App Pool avviato: $appPoolName" "SUCCESS"
    }

    Start-Website -Name $siteName -ErrorAction Stop
    Write-HelperLog "Sito avviato: $siteName" "SUCCESS"
    Write-HelperLog "Restart completato." "SUCCESS"
    exit 0
} catch {
    Write-HelperLog "Restart fallito: $_" "ERROR"
    exit 1
}
