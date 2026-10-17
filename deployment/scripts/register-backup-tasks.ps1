# register-backup-tasks.ps1
# Registra (o aggiorna, idempotente) i task pianificati del motore di backup verificabile
# (BUILD_SPEC R1 §3.4) per un ambiente. I task chiamano il python della release attiva
# tramite la junction "current" e scrivono il log in <env>\logs\backup-<tipo>.log.
#
#   .\register-backup-tasks.ps1 -Environment prod -Credential (Get-Credential 'CNOVICROM\svc-hub') -WhatIf
#   .\register-backup-tasks.ps1 -Environment prod -Credential $cred -AuditArchiveDir \\nas\hub-archivi
#   .\register-backup-tasks.ps1 -Environment prod -GmsaAccount 'CNOVICROM\gmsa-hub$'     # futura VM
#
# Task (cartella \PortaleNovicrom\):
#   PortaleNovicrom-Backup-<ENV>-FULL       ogni giorno 02:00   hub_backup --type full
#   PortaleNovicrom-Backup-<ENV>-LOG        ogni ora al minuto 05 nella finestra (-LogWindow, default 07-21)
#   PortaleNovicrom-Backup-<ENV>-FILES      ogni giorno 02:30   hub_backup --type files
#   PortaleNovicrom-Backup-<ENV>-HOST       ogni giorno 03:00   hub_backup --type host
#   PortaleNovicrom-Backup-<ENV>-RETENTION  ogni giorno 05:00   hub_backup --type retention --apply
#   PortaleNovicrom-Backup-<ENV>-DRILL      domenica 04:00      hub_restore_drill (con -IncludeDrill, blocco R2)
#   PortaleNovicrom-Backup-<ENV>-AUDIT      domenica 05:30      audit_archive --run (con -AuditArchiveDir)
#   PortaleNovicrom-Backup-<ENV>-AUDIT-BUSINESS  ogni 4 settimane, domenica 06:00, audit_archive --category business (con -IncludeBusinessArchive, solo dopo S1)
#
# Account: serve l'accesso di rete alla share dei backup, quindi logon con password
# (-Credential) o gMSA (-GmsaAccount). S4U non ha credenziali di rete: rifiutato.
# Il vecchio task del wizard (PortaleNovicrom-Backup-<ENV>, backup_portale) viene
# DISABILITATO (non cancellato) per non fare due FULL alle 02:00; -KeepLegacyTask lo lascia.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory)][ValidateSet("test", "prod")][string]$Environment,
    [PSCredential]$Credential,
    [string]$GmsaAccount = "",
    [ValidatePattern('^\d{1,2}-\d{1,2}$')][string]$LogWindow = "07-21",
    [string]$SettingsModule = "config.settings.prod",
    [string]$AuditArchiveDir = "",
    [string]$SqlServiceAccount = "",
    [switch]$IncludeDrill,
    [switch]$IncludeBusinessArchive,
    [switch]$KeepLegacyTask
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

$dryRun = [bool]$WhatIfPreference
if (-not $dryRun) { Assert-Admin }
Assert-ValidEnvironment -Env $Environment
$paths = Get-EnvPaths -Env $Environment
$envUpper = $Environment.ToUpperInvariant()
$taskPath = "\PortaleNovicrom\"

$start, $end = $LogWindow.Split("-") | ForEach-Object { [int]$_ }
if ($start -lt 0 -or $end -gt 24 -or $start -ge $end) { throw "LogWindow non valida: $LogWindow" }

function Get-TaskDefinitions {
    $defs = @(
        @{ Kind = "FULL";      Args = "hub_backup --type full --env $Environment";  At = "02:00"; Schedule = "Daily" },
        @{ Kind = "LOG";       Args = "hub_backup --type log --env $Environment";   At = ("{0:D2}:05" -f $start); Schedule = "Hourly" },
        @{ Kind = "FILES";     Args = "hub_backup --type files --env $Environment"; At = "02:30"; Schedule = "Daily" },
        @{ Kind = "HOST";      Args = "hub_backup --type host --env $Environment";  At = "03:00"; Schedule = "Daily" },
        @{ Kind = "RETENTION"; Args = "hub_backup --type retention --apply --env $Environment"; At = "05:00"; Schedule = "Daily" }
    )
    if ($IncludeDrill) {
        $defs += @{ Kind = "DRILL"; Args = "hub_restore_drill --env $Environment"; At = "04:00"; Schedule = "Weekly" }
    }
    if ($AuditArchiveDir) {
        $defs += @{ Kind = "AUDIT"; Args = "audit_archive --run --archive-dir `"$AuditArchiveDir`" --max-minutes 60 --checkpoint"; At = "05:30"; Schedule = "Weekly" }
        if ($IncludeBusinessArchive) {
            $defs += @{ Kind = "AUDIT-BUSINESS"; Args = "audit_archive --run --category business --older-than-months 60 --archive-dir `"$AuditArchiveDir`" --max-minutes 120"; At = "06:00"; Schedule = "Monthly" }
        }
    } elseif ($IncludeBusinessArchive) {
        throw "-IncludeBusinessArchive richiede -AuditArchiveDir."
    }
    return $defs
}

function New-BackupTrigger($def) {
    $at = [datetime]::ParseExact($def.At, "HH:mm", $null)
    switch ($def.Schedule) {
        "Daily"  { return New-ScheduledTaskTrigger -Daily -At $at }
        "Weekly" { return New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $at }
        "Hourly" {
            $t = New-ScheduledTaskTrigger -Daily -At $at
            $rep = (New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval (New-TimeSpan -Hours 1) `
                    -RepetitionDuration (New-TimeSpan -Hours ($end - $start - 1) -Minutes 1)).Repetition
            $t.Repetition = $rep
            return $t
        }
        "Monthly" {
            # New-ScheduledTaskTrigger non ha un trigger mensile: ogni 4 settimane (domenica).
            # Il comando è idempotente: se nulla supera i 60 mesi non fa niente.
            return New-ScheduledTaskTrigger -Weekly -WeeksInterval 4 -DaysOfWeek Sunday -At $at
        }
    }
}

Write-LogSeparator
Write-Log "Task di backup per $envUpper (finestra log $LogWindow)$(if ($dryRun) { ' [WhatIf]' })" "STEP"

# ── account ───────────────────────────────────────────────────────────────────
if (-not $Credential -and -not $GmsaAccount -and -not $dryRun) {
    throw "Serve un account con accesso di rete alla share dei backup: -Credential (logon con password) o -GmsaAccount."
}
$principalDesc = if ($GmsaAccount) { "gMSA $GmsaAccount" } elseif ($Credential) { $Credential.UserName } else { "(da indicare)" }
Write-Log "Account dei task: $principalDesc" "INFO"

$python = Join-Path $paths.Venv "Scripts\python.exe"
$workDir = $paths.DjangoApp
if (-not $dryRun -and -not (Test-Path $python)) { throw "Python del venv non trovato: $python" }

# ── staging: il servizio SQL deve poterci scrivere i .bak ────────────────────
$staging = "C:\PortaleNovicrom\shared\backup-staging"
if (-not $SqlServiceAccount) {
    $envFile = Join-Path $paths.Config ".env"
    $dbHost = ""
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) { if ($line -match '^\s*DB_HOST\s*=\s*(.+)$') { $dbHost = $Matches[1].Trim() } }
    }
    $instance = if ($dbHost -match '\\([^\\,]+)') { $Matches[1] } else { "" }
    $SqlServiceAccount = if ($instance) { "NT Service\MSSQL`$$instance" } else { "NT Service\MSSQLSERVER" }
}
if ($PSCmdlet.ShouldProcess($staging, "Cartella di staging + permesso Modify a $SqlServiceAccount")) {
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    & icacls.exe $staging /grant "$($SqlServiceAccount):(OI)(CI)M" /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Log "icacls su $staging non riuscito (exit $LASTEXITCODE): concedere a mano Modify a $SqlServiceAccount." "WARN" }
}

# ── task ──────────────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $paths.Logs -WhatIf:$false -ErrorAction SilentlyContinue | Out-Null
$settingsSet = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
$registered = @()
foreach ($def in Get-TaskDefinitions) {
    $name = "PortaleNovicrom-Backup-$envUpper-$($def.Kind)"
    $logFile = Join-Path $paths.Logs ("backup-" + $def.Kind.ToLowerInvariant() + ".log")
    $cmdLine = "/c `"`"$python`" manage.py $($def.Args) --settings=$SettingsModule >> `"$logFile`" 2>&1`""
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdLine -WorkingDirectory $workDir
    $trigger = New-BackupTrigger $def
    Write-Log ("{0,-42} {1,-7} {2}  →  {3}" -f $name, $def.Schedule, $def.At, $def.Args) "INFO"
    if (-not $PSCmdlet.ShouldProcess($name, "Register-ScheduledTask (aggiorna se esiste)")) { continue }
    $common = @{ TaskPath = $taskPath; TaskName = $name; Action = $action; Trigger = $trigger; Settings = $settingsSet; Force = $true
                 Description = "NOVICROM HUB - backup verificabile ($($def.Kind)), registrato da register-backup-tasks.ps1" }
    if ($GmsaAccount) {
        $principal = New-ScheduledTaskPrincipal -UserId $GmsaAccount -LogonType Password -RunLevel Highest
        Register-ScheduledTask @common -Principal $principal | Out-Null
    } else {
        Register-ScheduledTask @common -User $Credential.UserName -Password $Credential.GetNetworkCredential().Password -RunLevel Highest | Out-Null
    }
    $registered += $name
}

# ── vecchio task del wizard ───────────────────────────────────────────────────
$legacy = Get-ScheduledTask -TaskName "PortaleNovicrom-Backup-$envUpper" -ErrorAction SilentlyContinue
if ($legacy -and -not $KeepLegacyTask) {
    if ($PSCmdlet.ShouldProcess($legacy.TaskName, "Disabilita il vecchio task backup_portale (non cancellato)")) {
        Disable-ScheduledTask -InputObject $legacy | Out-Null
        Write-Log "Vecchio task $($legacy.TaskName) disabilitato (riattivabile con Enable-ScheduledTask)." "WARN"
    }
}

Write-LogSeparator
if ($dryRun) {
    Write-Log "WhatIf: nessun task registrato." "SUCCESS"
} else {
    Write-Log "Registrati/aggiornati $($registered.Count) task. Verifica: manage.py hub_backup_doctor --env $Environment" "SUCCESS"
}
