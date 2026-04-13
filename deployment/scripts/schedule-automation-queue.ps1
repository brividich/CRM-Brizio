<#
.SYNOPSIS
    Registra (o aggiorna) il Task Scheduler Windows per process_automation_queue.

.DESCRIPTION
    Crea un'attività pianificata che esegue process_automation_queue ogni minuto
    per ciascun ambiente specificato (test e/o prod).

    L'attività usa il venv dell'ambiente e il settings prod (come da convenzione
    wizard/deploy). Il log viene scritto in <env>\logs\automation_queue.log.

    Per aggiornare un'attività esistente rieseguire lo script: sovrascrive silenziosamente.

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

$TASK_FOLDER    = "\PortaleNovicrom"
$TASK_BASE_NAME = "AutomationQueue"

function Get-TaskName([string]$Env) {
    return "$TASK_FOLDER\${TASK_BASE_NAME}_$($Env.ToUpper())"
}

function Remove-AutomationTask([string]$Env) {
    $taskName = Get-TaskName $Env
    $existing = Get-ScheduledTask -TaskPath $TASK_FOLDER -TaskName "${TASK_BASE_NAME}_$($Env.ToUpper())" -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Log "Task rimosso: $taskName" "SUCCESS"
    } else {
        Write-Log "Task non trovato (già rimosso?): $taskName" "WARN"
    }
}

function Register-AutomationTask([string]$Env) {
    $paths    = Get-EnvPaths -Env $Env
    $taskName = Get-TaskName $Env

    if (-not (Test-Path $paths.Venv)) {
        Write-Log "Venv non trovato per ambiente '$Env': $($paths.Venv) — task non registrato." "WARN"
        return
    }

    $pythonExe  = "$($paths.Venv)\Scripts\python.exe"
    $managepy   = "$($paths.DjangoApp)\..\django_app\manage.py"

    # manage.py canonico: DjangoApp = <env>\current\django_app
    $managepy = "$($paths.DjangoApp)\manage.py"
    $logFile  = "$($paths.Logs)\automation_queue.log"

    # Crea la cartella logs se non esiste
    if (-not (Test-Path $paths.Logs)) {
        New-Item -ItemType Directory -Path $paths.Logs -Force | Out-Null
    }

    # Il wrapper cmd redirige stdout+stderr al log e aggiunge timestamp riga
    # Viene usato cmd /c per compatibilità con il runner di Task Scheduler
    $cmdAction = "cmd /c `"(`"$pythonExe`" `"$managepy`" process_automation_queue --settings=config.settings.prod >> `"$logFile`" 2>&1)`""

    $action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"(`"$pythonExe`" `"$managepy`" process_automation_queue --settings=config.settings.prod >> `"$logFile`" 2>&1)`""
    $trigger   = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 1) -Once -At (Get-Date)
    $settings  = New-ScheduledTaskSettingsSet `
                    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
                    -MultipleInstances IgnoreNew `
                    -StartWhenAvailable `
                    -RunOnlyIfNetworkAvailable:$false

    # Esegui come SYSTEM per evitare dipendenza da utente interattivo
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    $taskParams = @{
        TaskName    = "${TASK_BASE_NAME}_$($Env.ToUpper())"
        TaskPath    = $TASK_FOLDER
        Action      = $action
        Trigger     = $trigger
        Settings    = $settings
        Principal   = $principal
        Description = "Portale Novicrom — Processa automation_event_queue ogni minuto ($Env). Gestito da schedule-automation-queue.ps1."
        Force       = $true
    }

    Register-ScheduledTask @taskParams | Out-Null
    Write-Log "Task registrato: $taskName" "SUCCESS"
    Write-Log "  Python:    $pythonExe" "INFO"
    Write-Log "  manage.py: $managepy" "INFO"
    Write-Log "  Log:       $logFile" "INFO"
    Write-Log "  Intervallo: ogni 1 minuto" "INFO"
}

# ---------------------------------------------------------------------------
# Risolvi ambienti target
# ---------------------------------------------------------------------------
$targetEnvs = if ($Environment -eq "all") { @("test", "prod") } else { @($Environment) }

Write-LogSeparator
$action = if ($Unregister) { "RIMOZIONE" } else { "REGISTRAZIONE" }
Write-Log "TASK SCHEDULER AUTOMATION QUEUE — $action" "STEP"
Write-LogSeparator

foreach ($env in $targetEnvs) {
    Write-Log "Ambiente: $($env.ToUpper())" "STEP"
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
    Write-Log "  Get-ScheduledTask -TaskPath '$TASK_FOLDER'" "INFO"
    Write-Log "Per eseguire manualmente:" "INFO"
    foreach ($env in $targetEnvs) {
        Write-Log "  Start-ScheduledTask -TaskName '$(Get-TaskName $env)'" "INFO"
    }
}
