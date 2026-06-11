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

    [string]$LogFile = ""
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

Write-Log "=== qcluster START (env=$Environment, pid=$PID) ==="

# -- Loop di restart -------------------------------------------------------
$attempt = 0
while ($true) {
    $attempt++
    Write-Log "Avvio qcluster - tentativo #$attempt"

    try {
        $psi = [System.Diagnostics.ProcessStartInfo]::new()
        $psi.FileName               = $VenvPython
        $psi.Arguments              = "manage.py qcluster --settings=$Settings"
        $psi.WorkingDirectory       = $CurrentDir
        $psi.UseShellExecute        = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError  = $true
        $psi.EnvironmentVariables["PORTAL_SKIP_RUNTIME_BOOTSTRAP"] = "0"
        $psi.EnvironmentVariables["DJANGO_SETTINGS_MODULE"] = $Settings

        $proc = [System.Diagnostics.Process]::new()
        $proc.StartInfo = $psi

        # Scrivi stdout/stderr su file in background
        $stdoutAction = {
            param($sender, $e)
            if ($e.Data) {
                $ts   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                $line = "[$ts] [OUT] $($e.Data)"
                Add-Content -Path $Event.MessageData -Value $line -Encoding UTF8
            }
        }
        $stderrAction = {
            param($sender, $e)
            if ($e.Data) {
                $ts   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                $line = "[$ts] [ERR] $($e.Data)"
                Add-Content -Path $Event.MessageData -Value $line -Encoding UTF8
            }
        }

        Register-ObjectEvent -InputObject $proc -EventName "OutputDataReceived" `
            -Action $stdoutAction -MessageData $LogFile | Out-Null
        Register-ObjectEvent -InputObject $proc -EventName "ErrorDataReceived" `
            -Action $stderrAction -MessageData $LogFile | Out-Null

        $proc.Start() | Out-Null
        $proc.BeginOutputReadLine()
        $proc.BeginErrorReadLine()

        Write-Log "qcluster avviato - PID processo figlio: $($proc.Id)"
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode

        Get-EventSubscriber | Where-Object { $_.SourceObject -eq $proc } | Unregister-Event
        $proc.Dispose()

        Write-Log "qcluster terminato con exit code $exitCode" "WARN"
    }
    catch {
        Write-Log "Eccezione durante avvio/attesa qcluster: $_" "ERROR"
    }

    Write-Log "Restart tra $RestartDelaySec secondi..." "WARN"
    Start-Sleep -Seconds $RestartDelaySec
}
