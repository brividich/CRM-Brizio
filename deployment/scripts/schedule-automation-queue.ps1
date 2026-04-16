<#
.SYNOPSIS
    Registra o aggiorna il Task Scheduler Windows per process_automation_queue.

.DESCRIPTION
    Crea un'attivita pianificata che esegue process_automation_queue ogni minuto
    per ciascun ambiente specificato (test e/o prod).

    L'attivita usa il venv dell'ambiente, i settings prod e un runner PowerShell
    hidden che mantiene il polling silent e continua a scrivere il log in
    <env>\logs\automation_queue.log.

    Per aggiornare un'attivita esistente rieseguire lo script: sovrascrive in
    modo idempotente.

.PARAMETER Environment
    Ambiente target: "test", "prod" oppure "all" (default).
    "all" registra il task per entrambi gli ambienti attivi.

.PARAMETER Unregister
    Se specificato, rimuove i task invece di crearli.

.EXAMPLE
    .\schedule-automation-queue.ps1
    .\schedule-automation-queue.ps1 -Environment prod
    .\schedule-automation-queue.ps1 -Environment all -Unregister
#>

param(
    [ValidateSet("test", "prod", "all")]
    [string]$Environment = "all",

    [switch]$Unregister
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin

$TASK_FOLDER = "\PortaleNovicrom"
$TASK_BASE_NAME = "AutomationQueue"

function Get-TaskName([string]$Env) {
    return "$TASK_FOLDER\${TASK_BASE_NAME}_$($Env.ToUpper())"
}

function Remove-AutomationTask([string]$Env) {
    $shortTaskName = "${TASK_BASE_NAME}_$($Env.ToUpper())"
    $existing = Get-ScheduledTask -TaskPath $TASK_FOLDER -TaskName $shortTaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskPath $TASK_FOLDER -TaskName $shortTaskName -Confirm:$false
        Write-Log ("Task rimosso: {0}" -f (Get-TaskName $Env)) "SUCCESS"
    } else {
        Write-Log ("Task non trovato (gia rimosso?): {0}" -f (Get-TaskName $Env)) "WARN"
    }
}

function Register-AutomationTask([string]$Env) {
    $paths = Get-EnvPaths -Env $Env
    $taskName = Get-TaskName $Env
    $shortTaskName = "${TASK_BASE_NAME}_$($Env.ToUpper())"
    $runnerScript = Join-Path $PSScriptRoot "run-automation-queue-poller.ps1"

    if (-not (Test-Path $paths.Venv)) {
        Write-Log ("Venv non trovato per ambiente {0}: {1} -- task non registrato." -f $Env, $paths.Venv) "WARN"
        return
    }
    if (-not (Test-Path $runnerScript)) {
        Write-Log ("Runner silent non trovato: {0} -- task non registrato." -f $runnerScript) "WARN"
        return
    }

    $pythonExe = Join-Path $paths.Venv "Scripts\python.exe"
    $managepy = Join-Path $paths.DjangoApp "manage.py"
    $logFile = Join-Path $paths.Logs "automation_queue.log"

    if (-not (Test-Path $paths.Logs)) {
        New-Item -ItemType Directory -Path $paths.Logs -Force | Out-Null
    }

    $runnerArguments = @(
        "-NoProfile"
        "-NonInteractive"
        "-WindowStyle Hidden"
        "-ExecutionPolicy Bypass"
        ("-File ""{0}""" -f $runnerScript)
        ("-PythonExe ""{0}""" -f $pythonExe)
        ("-ManagePy ""{0}""" -f $managepy)
        ("-SettingsModule ""{0}""" -f "config.settings.prod")
        ("-LogFile ""{0}""" -f $logFile)
    ) -join " "

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $runnerArguments
    $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 1) -Once -At (Get-Date)
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable:$false

    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    $taskParams = @{
        TaskName = $shortTaskName
        TaskPath = $TASK_FOLDER
        Action = $action
        Trigger = $trigger
        Settings = $settings
        Principal = $principal
        Description = "Portale Novicrom - Processa automation_event_queue ogni minuto ($Env) in modalita silent. Gestito da schedule-automation-queue.ps1."
        Force = $true
    }

    Register-ScheduledTask @taskParams | Out-Null
    Write-Log ("Task registrato: {0}" -f $taskName) "SUCCESS"
    Write-Log ("  Python:    {0}" -f $pythonExe) "INFO"
    Write-Log ("  manage.py: {0}" -f $managepy) "INFO"
    Write-Log ("  Runner:    {0}" -f $runnerScript) "INFO"
    Write-Log ("  Log:       {0}" -f $logFile) "INFO"
    Write-Log "  Intervallo: ogni 1 minuto" "INFO"
}

$targetEnvs = if ($Environment -eq "all") { @("test", "prod") } else { @($Environment) }

Write-LogSeparator
$actionLabel = if ($Unregister) { "RIMOZIONE" } else { "REGISTRAZIONE" }
Write-Log ("TASK SCHEDULER AUTOMATION QUEUE - {0}" -f $actionLabel) "STEP"
Write-LogSeparator

foreach ($env in $targetEnvs) {
    Write-Log ("Ambiente: {0}" -f $env.ToUpper()) "STEP"
    if ($Unregister) {
        Remove-AutomationTask $env
    } else {
        Register-AutomationTask $env
    }
}

Write-LogSeparator
Write-Log "Operazione completata." "SUCCESS"

if (-not $Unregister) {
    Write-Log "" "INFO"
    Write-Log "Per verificare i task registrati:" "INFO"
    Write-Log ("  Get-ScheduledTask -TaskPath {0}" -f $TASK_FOLDER) "INFO"
    Write-Log "Per eseguire manualmente:" "INFO"
    foreach ($env in $targetEnvs) {
        Write-Log ("  Start-ScheduledTask -TaskName {0}" -f (Get-TaskName $env)) "INFO"
    }
}
