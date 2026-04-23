<#
.SYNOPSIS
    Registra il task schedulato elevato per il riavvio IIS da portale.

.DESCRIPTION
    Crea o aggiorna \PortaleNovicrom\IISRestart_TEST/PROD come task on-demand
    eseguito da SYSTEM. Il task richiama restart-iis-env.ps1 e concede
    all'identita IIS AppPool dell'ambiente il diritto di lettura/esecuzione
    sul task, cosi /admin-portale/crea-release/ puo avviarlo automaticamente.
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
$TASK_BASE_NAME = "IISRestart"

function Get-RestartTaskShortName([string]$Env) {
    return "${TASK_BASE_NAME}_$($Env.ToUpperInvariant())"
}

function Get-RestartTaskName([string]$Env) {
    return "$TASK_FOLDER\$(Get-RestartTaskShortName $Env)"
}

function Grant-TaskStartPermission {
    param(
        [string]$TaskPath,
        [string]$TaskName,
        [string]$Account
    )

    try {
        $sid = (New-Object System.Security.Principal.NTAccount($Account)).Translate([System.Security.Principal.SecurityIdentifier]).Value
        $ace = "(A;;GRGX;;;$sid)"

        $service = New-Object -ComObject "Schedule.Service"
        $service.Connect()
        $folder = $service.GetFolder($TaskPath)

        foreach ($target in @($folder, $folder.GetTask($TaskName))) {
            $sddl = $target.GetSecurityDescriptor(0xF)
            if ($sddl -like "*$sid*") {
                continue
            }
            if ($sddl -match "S:") {
                $newSddl = $sddl -replace "S:", "$ace`S:"
            } else {
                $newSddl = "$sddl$ace"
            }
            $target.SetSecurityDescriptor($newSddl, 0)
        }

        Write-Log ("  Permesso avvio task concesso a {0}" -f $Account) "SUCCESS"
    } catch {
        Write-Log ("  Permesso avvio task non impostato per {0}: {1}" -f $Account, $_) "WARN"
    }
}

function Remove-RestartTask([string]$Env) {
    $shortTaskName = Get-RestartTaskShortName $Env
    $existing = Get-ScheduledTask -TaskPath $TASK_FOLDER -TaskName $shortTaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskPath $TASK_FOLDER -TaskName $shortTaskName -Confirm:$false
        Write-Log ("Task rimosso: {0}" -f (Get-RestartTaskName $Env)) "SUCCESS"
    } else {
        Write-Log ("Task non trovato: {0}" -f (Get-RestartTaskName $Env)) "WARN"
    }
}

function Register-RestartTask([string]$Env) {
    $paths = Get-EnvPaths -Env $Env
    $shortTaskName = Get-RestartTaskShortName $Env
    $taskName = Get-RestartTaskName $Env
    $runnerScript = Join-Path $PSScriptRoot "restart-iis-env.ps1"
    $envUpper = $Env.ToUpperInvariant()
    $appPoolName = "PortaleNovicrom-$envUpper"
    $appPoolIdentity = "IIS AppPool\$appPoolName"

    if (-not (Test-Path $runnerScript)) {
        Write-Log ("Runner restart IIS non trovato: {0}" -f $runnerScript) "WARN"
        return
    }

    if (-not (Test-Path $paths.Logs)) {
        New-Item -ItemType Directory -Path $paths.Logs -Force | Out-Null
    }

    $runnerArguments = @(
        "-NoProfile"
        "-NonInteractive"
        "-WindowStyle Hidden"
        "-ExecutionPolicy Bypass"
        ("-File ""{0}""" -f $runnerScript)
        ("-Environment ""{0}""" -f $Env)
    ) -join " "

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $runnerArguments
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable:$false `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $shortTaskName `
        -TaskPath $TASK_FOLDER `
        -Action $action `
        -Settings $settings `
        -Principal $principal `
        -Description "NOVICROM HUB - Restart IIS on-demand per $envUpper, avviabile dal portale Crea Release." `
        -Force | Out-Null

    Write-Log ("Task registrato: {0}" -f $taskName) "SUCCESS"
    Write-Log ("  Runner: {0}" -f $runnerScript) "INFO"
    Write-Log ("  Log:    {0}" -f (Join-Path $paths.Logs "iis_restart_helper.log")) "INFO"
    Grant-TaskStartPermission -TaskPath $TASK_FOLDER -TaskName $shortTaskName -Account $appPoolIdentity
}

$targetEnvs = if ($Environment -eq "all") { @("test", "prod") } else { @($Environment) }

Write-LogSeparator
$actionLabel = if ($Unregister) { "RIMOZIONE" } else { "REGISTRAZIONE" }
Write-Log ("TASK SCHEDULER IIS RESTART HELPER - {0}" -f $actionLabel) "STEP"
Write-LogSeparator

foreach ($env in $targetEnvs) {
    Write-Log ("Ambiente: {0}" -f $env.ToUpperInvariant()) "STEP"
    if ($Unregister) {
        Remove-RestartTask $env
    } else {
        Register-RestartTask $env
    }
}

Write-LogSeparator
Write-Log "Operazione completata." "SUCCESS"
