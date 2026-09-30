#Requires -Version 5.1
<#
.SYNOPSIS
    Avvia il worker django-q2 (qcluster) per NOVICROM HUB.
    Progettato per essere lanciato da Task Scheduler come processo persistente
    con auto-restart on crash.

    IMPORTANTE: questo file e' volutamente in ASCII puro (niente accenti o
    box-drawing). Caratteri non-ASCII salvati con encoding errato (mojibake)
    rompono il parser PowerShell e fanno fallire il task senza log -> non
    reintrodurli.

.DESCRIPTION
    Lo script individua il venv dell'ambiente selezionato, avvia
    'python manage.py qcluster --settings=config.settings.<env>'
    e lo riavvia automaticamente se termina in modo inatteso.

    Registrare in Task Scheduler con:
      - Trigger: "All'avvio" (At startup)  oppure  "Alla connessione utente"
      - Azione: powershell.exe -NonInteractive -ExecutionPolicy Bypass
                -File "C:\PortaleNovicrom\shared\scripts\start_qcluster.ps1"
      - Flag: "Esegui indipendentemente dall'accesso utente"
      - Account: account di servizio o account Windows dell'applicazione

.PARAMETER Environment
    Ambiente target: 'test' oppure 'prod' (default: 'prod').

.PARAMETER PortaleRoot
    Cartella radice degli ambienti. Default: C:\PortaleNovicrom

.PARAMETER RestartDelaySec
    Secondi di attesa prima del restart dopo un'uscita. Default: 5.

.PARAMETER LogFile
    Percorso file di log. Default: <PortaleRoot>\<Environment>\logs\qcluster.log
#>

param(
    [ValidateSet("test", "prod")]
    [string]$Environment = "prod",

    [string]$PortaleRoot = "C:\PortaleNovicrom",

    [int]$RestartDelaySec = 5,

    [string]$LogFile = "",

    [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# -- Percorsi --------------------------------------------------------------
$EnvRoot    = Join-Path $PortaleRoot $Environment
$CurrentDir = Join-Path $EnvRoot "current\django_app"
$VenvPython = Join-Path $EnvRoot "venv\Scripts\python.exe"
$LogsDir    = Join-Path $EnvRoot "logs"
$Settings   = "config.settings.$Environment"

if (-not $LogFile) {
    $LogFile = Join-Path $LogsDir "qcluster.log"
}

# -- Utility log -----------------------------------------------------------
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$Level] $Message"
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch {}
    Write-Host $line
}

# -- Preflight -------------------------------------------------------------
# La cartella log va creata PRIMA dei controlli, cosi' Write-Log puo' loggare
# anche l'eventuale errore di preflight.
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}
if (-not (Test-Path $VenvPython)) {
    Write-Log "Python venv non trovato: $VenvPython" "ERROR"
    exit 1
}
if (-not (Test-Path $CurrentDir)) {
    Write-Log "Cartella django_app non trovata: $CurrentDir" "ERROR"
    exit 1
}

$rootBytes = [Text.Encoding]::UTF8.GetBytes($EnvRoot.ToLowerInvariant())
$rootHash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($rootBytes)).Replace("-", "").Substring(0, 16)
$clusterMutex = [Threading.Mutex]::new($false, "Global\NovicromQCluster_$rootHash")
try { $ownsMutex = $clusterMutex.WaitOne(0) }
catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) { Write-Log "Launcher gia attivo per questo ambiente." "WARN"; $clusterMutex.Dispose(); exit 0 }
try {
Write-Log "=== qcluster START (env=$Environment, pid=$PID) ==="

# -- Loop di restart -------------------------------------------------------
$attempt = 0
while ($true) {
    $attempt++
    Write-Log "Avvio qcluster - tentativo #$attempt"

    try {
        # File redirection is handled by .NET, without PowerShell event callbacks.
        # Blocking WaitForExit + Register-ObjectEvent can fill the child pipes.
        $runStamp = (Get-Date).ToString("yyyyMMdd_HHmmss_fff")
        $stdoutPath = Join-Path $LogsDir "qcluster_${PID}_${runStamp}.out.log"
        $stderrPath = Join-Path $LogsDir "qcluster_${PID}_${runStamp}.err.log"
        $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP = "0"
        $env:DJANGO_SETTINGS_MODULE = $Settings
        $env:PYTHONUNBUFFERED = "1"
        $proc = Start-Process -FilePath $VenvPython `
            -ArgumentList @("manage.py", "qcluster", "--settings=$Settings") `
            -WorkingDirectory $CurrentDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -ErrorAction Stop
        $null = $proc.Handle
        Write-Log "qcluster avviato - PID processo figlio: $($proc.Id)"
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode
        $proc.Dispose()

        Write-Log "qcluster terminato con exit code $exitCode" "WARN"
        if ($Once) { exit $exitCode }
    }
    catch {
        Write-Log "Eccezione durante avvio/attesa qcluster: $_" "ERROR"
        if ($Once) { exit 1 }
    }

    Write-Log "Restart tra $RestartDelaySec secondi..." "WARN"
    Start-Sleep -Seconds $RestartDelaySec
}

}
finally {
    if ($ownsMutex) { $clusterMutex.ReleaseMutex() }
    $clusterMutex.Dispose()
}
