#Requires -Version 5.1
<# Independent minute watchdog. Run under the worker service account.
   Exit: 0 healthy/maintenance/grace; 2 unhealthy; 3 probe/task/notification failure.
   No queue replay and no forced termination of a running worker.
#>
param(
    [ValidateSet('test', 'prod')][string]$Environment = 'prod',
    [string]$PortaleRoot = 'C:\PortaleNovicrom',
    [ValidateRange(1, 90)][int]$ProbeTimeoutSec = 45,
    [ValidateRange(0, 1440)][int]$MaintenanceMinutes = 0,
    [switch]$Resume
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$envRoot = Join-Path $PortaleRoot $Environment
$logs = Join-Path $envRoot 'logs'
$maintenance = Join-Path $logs 'qcluster-maintenance-until.txt'
$taskName = 'QCluster_' + $Environment.ToUpperInvariant()
$taskPath = '\PortaleNovicrom\'
$source = 'NovicromQCluster'
New-Item -ItemType Directory -Path $logs -Force | Out-Null

function Write-WatchEvent([string]$Message, [int]$Id = 4100, [string]$Type = 'Information') {
    $path = Join-Path $logs 'qcluster-watchdog.log'
    try {
        if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 5MB) {
            Move-Item -LiteralPath $path -Destination "$path.1" -Force
        }
        Add-Content -LiteralPath $path -Value "[$([DateTime]::UtcNow.ToString('o'))] [$Environment] $Message" -Encoding UTF8
    } catch {
        # A full disk or an unwritable log must not suppress the Windows event.
        Write-Warning 'Log watchdog su file non disponibile.'
        $Id = 4104
        $Type = 'Error'
        $Message = 'Log watchdog su file non disponibile. ' + $Message
    }
    if ($Id -ne 4100) {
        try { Write-EventLog -LogName Application -Source $source -EventId $Id -EntryType $Type -Message "[$Environment] $Message" }
        catch { Write-Warning 'Event Log non disponibile; consultare qcluster-watchdog.log.' }
    }
}

if ($MaintenanceMinutes -gt 0) {
    [DateTime]::UtcNow.AddMinutes($MaintenanceMinutes).ToString('o') | Set-Content -LiteralPath $maintenance -Encoding ASCII
    Write-WatchEvent "Manutenzione per $MaintenanceMinutes minuti." 4103 Warning
    exit 0
}
if ($Resume -and (Test-Path -LiteralPath $maintenance)) { Remove-Item -LiteralPath $maintenance }

# Task Scheduler ignores concurrent runs; this mutex also covers manual probes.
$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($envRoot).ToLowerInvariant()))).Replace('-', '').Substring(0, 16)
$mutex = [Threading.Mutex]::new($false, "Global\NovicromQWatch_$hash")
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { exit 0 }
    if (Test-Path -LiteralPath $maintenance) {
        $until = [DateTimeOffset]::Parse((Get-Content -LiteralPath $maintenance -Raw).Trim())
        if ($until -gt [DateTimeOffset]::UtcNow) { Write-WatchEvent "Manutenzione attiva fino a $($until.ToString('o'))."; exit 0 }
        Remove-Item -LiteralPath $maintenance
    }
    $worker = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath
    if ($worker.State -eq 'Disabled') {
        Write-WatchEvent 'Task worker disabilitato: ripristino automatico sospeso.' 4103 Warning
        exit 2
    }
    # A stopped launcher may leave a live cluster behind. Probe BEFORE starting it.
    $python = Join-Path $envRoot 'venv\Scripts\python.exe'
    $app = Join-Path $envRoot 'current\django_app'
    $info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath $taskPath
    $grace = $worker.State -eq 'Running' -and $info.LastRunTime -gt (Get-Date).AddMinutes(-3)
    $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP = '1'
    # Both deployed environments use prod settings; config.settings.test is SQLite QA.
    $env:DJANGO_SETTINGS_MODULE = 'config.settings.prod'
    $env:MONITORING_ENVIRONMENT = $Environment
    $arguments = @('manage.py', 'automation_health', '--settings=config.settings.prod', '--no-color')
    if (-not $grace) { $arguments += '--notify' }
    $stdout = Join-Path $logs "qwatch_$PID.out.tmp"
    $stderr = Join-Path $logs "qwatch_$PID.err.tmp"
    try {
        $probe = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $app `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $null = $probe.Handle
        try {
            if (-not $probe.WaitForExit($ProbeTimeoutSec * 1000)) {
                $probe.Kill()
                $null = $probe.WaitForExit(5000)
                throw 'probe_timeout'
            }
            $exitCode = $probe.ExitCode
        } finally { $probe.Dispose() }
        if ($exitCode -notin @(0, 2)) { throw 'probe_failed' }
        $health = Get-Content -LiteralPath $stdout -Raw | ConvertFrom-Json
        if ($null -eq $health.worker_alive -or $null -eq $health.unhealthy) { throw 'invalid_probe' }
    } finally {
        # Do not retain Django/driver tracebacks (may contain runtime details).
        Remove-Item -LiteralPath $stdout, $stderr -ErrorAction SilentlyContinue
    }
    if ($grace) { Write-WatchEvent 'Avvio worker: tolleranza iniziale di tre minuti.'; exit 0 }
    if ($health.unhealthy) {
        Write-WatchEvent "Allarme qcluster: $($health.reason); coda=$($health.queued)." 4101 Error
        if ($worker.State -eq 'Ready' -and -not $health.worker_alive) {
            # Re-read after the probe: another operator may have disabled/started it.
            $current = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath
            if ($current.State -eq 'Ready') {
                if (Test-Path -LiteralPath $maintenance) {
                    $until = [DateTimeOffset]::Parse((Get-Content -LiteralPath $maintenance -Raw).Trim())
                    if ($until -gt [DateTimeOffset]::UtcNow) { Write-WatchEvent 'Manutenzione richiesta durante il controllo: riavvio sospeso.'; exit 0 }
                }
                $processes = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe'" -OperationTimeoutSec 10)
                $uncertain = @($processes | Where-Object { -not $_.ExecutablePath -or -not $_.CommandLine })
                $orphans = @($processes | Where-Object { $_.ExecutablePath -eq $python -and $_.CommandLine -match '\bqcluster\b' })
                if ($uncertain.Count -or $orphans.Count) {
                    Write-WatchEvent 'Riavvio sospeso: processi Python non verificabili o qcluster residuo presente.' 4104 Error
                    exit 3
                }
                $restartFile = Join-Path $logs 'qcluster-watchdog-restarts.json'
                $recent = @()
                if (Test-Path -LiteralPath $restartFile) {
                    $recent = @(Get-Content -LiteralPath $restartFile -Raw | ConvertFrom-Json | Where-Object {
                        [DateTimeOffset]::Parse($_) -gt [DateTimeOffset]::UtcNow.AddMinutes(-30)
                    })
                }
                if ($recent.Count -ge 3) {
                    Write-WatchEvent 'Limite di tre riavvii in 30 minuti raggiunto: intervento richiesto.' 4104 Error
                    exit 3
                }
                $recent += [DateTimeOffset]::UtcNow.ToString('o')
                ConvertTo-Json -InputObject @($recent) | Set-Content -LiteralPath $restartFile -Encoding ASCII
                Start-ScheduledTask -TaskName $taskName -TaskPath $taskPath
                Write-WatchEvent 'Richiesto avvio del task worker fermo; verifica al prossimo ciclo.' 4102 Warning
            }
        }
    } else {
        Write-WatchEvent "OK; coda=$($health.queued)."
        if ($health.notification -eq 'sent') {
            Write-WatchEvent 'Qcluster ripristinato; email di ripristino inviata.' 4105 Information
        }
        if ($worker.State -ne 'Running') {
            Write-WatchEvent 'Heartbeat presente ma task worker non Running: verificare cluster avviati manualmente.' 4103 Warning
        }
    }
    if ($health.notification -in @('failed', 'no_recipients', 'disabled')) {
        Write-WatchEvent "Email watchdog non inviata: $($health.notification)." 4104 Error
        exit 3
    }
    if ($health.unhealthy) { exit 2 }
    exit 0
} catch {
    Write-WatchEvent 'Controllo watchdog fallito o scaduto: verificare task, Python, migrazioni, DB e configurazione. Nessun riavvio forzato.' 4104 Error
    exit 3
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
