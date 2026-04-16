<#
.SYNOPSIS
    Registra un task locale che processa automaticamente la queue automazioni del repo.

.DESCRIPTION
    Crea o aggiorna il task schedulato Windows "Portale Hub Polling Mail"
    usando il `.venv` locale del repository e scrivendo il log in
    `django_app\logs\automation_queue.log`.

    Pensato per ambienti locali o server dove si lavora direttamente dalla
    working copy del repository, senza struttura `C:\PortaleNovicrom\prod|test`.

.PARAMETER TaskName
    Nome del task schedulato. Default: "Portale Hub Polling Mail".

.PARAMETER IntervalMinutes
    Frequenza del polling. Default: 1 minuto.

.PARAMETER SettingsModule
    Settings Django da usare per il comando. Default: config.settings.prod.

.PARAMETER StartNow
    Se specificato, avvia subito il task dopo la registrazione.

.PARAMETER Unregister
    Se specificato, rimuove il task invece di crearlo/aggiornarlo.
#>

param(
    [string]$TaskName = "Portale Hub Polling Mail",
    [ValidateRange(1, 60)]
    [int]$IntervalMinutes = 1,
    [string]$SettingsModule = "config.settings.prod",
    [switch]$StartNow,
    [switch]$Unregister
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$PythonExe = Join-Path $RepoRoot ".venv\\Scripts\\python.exe"
$ManagePy = Join-Path $RepoRoot "django_app\\manage.py"
$RunnerScript = Join-Path $RepoRoot "deployment\\scripts\\run-automation-queue-poller.ps1"
$LogsDir = Join-Path $RepoRoot "django_app\\logs"
$LogFile = Join-Path $LogsDir "automation_queue.log"
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path $PythonExe)) {
    throw "Python del virtualenv non trovato: $PythonExe"
}
if (-not (Test-Path $ManagePy)) {
    throw "manage.py non trovato: $ManagePy"
}
if (-not (Test-Path $RunnerScript)) {
    throw "Runner silent non trovato: $RunnerScript"
}
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

if ($Unregister) {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Task rimosso: $TaskName"
    } else {
        Write-Host "Task non trovato: $TaskName"
    }
    exit 0
}

$runnerArguments = @(
    "-NoProfile"
    "-NonInteractive"
    "-WindowStyle Hidden"
    "-ExecutionPolicy Bypass"
    ('-File "{0}"' -f $RunnerScript)
    ('-PythonExe "{0}"' -f $PythonExe)
    ('-ManagePy "{0}"' -f $ManagePy)
    ('-SettingsModule "{0}"' -f $SettingsModule)
    ('-LogFile "{0}"' -f $LogFile)
) -join " "
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $runnerArguments
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType S4U -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "NOVICROM HUB - Polling locale silent della automation_event_queue dal repository attivo." `
    -Force | Out-Null

Write-Host "Task registrato: $TaskName"
Write-Host "Utente: $CurrentUser"
Write-Host "Python: $PythonExe"
Write-Host "manage.py: $ManagePy"
Write-Host "Runner silent: $RunnerScript"
Write-Host "Log: $LogFile"
Write-Host "Intervallo: ogni $IntervalMinutes minuto/i"

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task avviato subito."
}
