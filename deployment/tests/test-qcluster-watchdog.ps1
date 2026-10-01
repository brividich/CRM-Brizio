#Requires -Version 5.1
# Synthetic orchestration tests: no real tasks, DB, email or process termination.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$target = Join-Path $repo 'deployment\watch_qcluster.ps1'
$testRoot = Join-Path $repo ('.tmp_tests\qwatch-' + [Guid]::NewGuid().ToString('N'))
$global:QWatchTest = @{}
function Get-ScheduledTask { param($TaskName, $TaskPath); [pscustomobject]@{State=$global:QWatchTest.State} }
function Get-ScheduledTaskInfo { param($TaskName, $TaskPath); [pscustomobject]@{LastRunTime=$global:QWatchTest.LastRun} }
function Start-ScheduledTask { param($TaskName, $TaskPath); $global:QWatchTest.Starts++ }
function Get-CimInstance { param($ClassName, $Filter, $OperationTimeoutSec); $global:QWatchTest.Processes }
function Write-EventLog { param($LogName, $Source, $EventId, $EntryType, $Message); $global:QWatchTest.Events += $EventId }
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError)
    $global:QWatchTest.Probes++
    $global:QWatchTest.Arguments = $ArgumentList
    $global:QWatchTest.Health | ConvertTo-Json | Set-Content -LiteralPath $RedirectStandardOutput
    'synthetic stderr' | Set-Content -LiteralPath $RedirectStandardError
    $process = [pscustomobject]@{ Handle=1; ExitCode=$global:QWatchTest.ExitCode }
    $process | Add-Member ScriptMethod WaitForExit { param($timeout); return -not $global:QWatchTest.Timeout }
    $process | Add-Member ScriptMethod Kill { $global:QWatchTest.Killed=$true }
    $process | Add-Member ScriptMethod Dispose {}
    return $process
}
function Reset-Case {
    $global:QWatchTest = @{
        State='Running'; LastRun=(Get-Date).AddHours(-1); Starts=0; Probes=0; Arguments=@(); Processes=@();
        Events=@(); ExitCode=2; Timeout=$false; Killed=$false;
        Health=@{ worker_alive=$false; unhealthy=$true; queued=0; reason='worker_unavailable'; notification='sent' }
    }
}
function Assert-True($value, $message) { if (-not $value) { throw "FAIL: $message" } }
function Invoke-Case { & $target -PortaleRoot $testRoot -ProbeTimeoutSec 1; return $LASTEXITCODE }

Reset-Case
$global:QWatchTest.State='Ready'
$code=Invoke-Case
Assert-True ($code -eq 2 -and $global:QWatchTest.Starts -eq 1) 'Stopped worker restarts once'
Assert-True ($global:QWatchTest.Arguments -contains '--settings=config.settings.prod') 'Deployed settings are prod'
Assert-True ($global:QWatchTest.Arguments -contains '--notify') 'Notifications independent of worker'

Reset-Case
$code=Invoke-Case
Assert-True ($code -eq 2 -and $global:QWatchTest.Starts -eq 0) 'Hung running task must not be duplicated'

Reset-Case
$global:QWatchTest.State='Ready'
$global:QWatchTest.Processes=@([pscustomobject]@{ExecutablePath=(Join-Path $testRoot 'prod\venv\Scripts\python.exe'); CommandLine='python.exe manage.py qcluster'})
$code=Invoke-Case
Assert-True ($code -eq 3 -and $global:QWatchTest.Starts -eq 0) 'Orphan process blocks restart'

Reset-Case
$global:QWatchTest.State='Ready'
$global:QWatchTest.Processes=@([pscustomobject]@{ExecutablePath=$null; CommandLine=$null})
$code=Invoke-Case
Assert-True ($code -eq 3 -and $global:QWatchTest.Starts -eq 0) 'Unknown process ownership blocks restart'

Reset-Case
$global:QWatchTest.State='Ready'
$global:QWatchTest.Health.worker_alive=$true
$global:QWatchTest.Health.unhealthy=$false
$global:QWatchTest.ExitCode=0
$code=Invoke-Case
Assert-True ($code -eq 0 -and $global:QWatchTest.Starts -eq 0) 'Live manual worker is preserved'
Assert-True ($global:QWatchTest.Events -contains 4105) 'Notified recovery is recorded in Event Log'

Reset-Case
$global:QWatchTest.Timeout=$true
$code=Invoke-Case
Assert-True ($code -eq 3 -and $global:QWatchTest.Killed -and $global:QWatchTest.Starts -eq 0) 'Probe timeout kills only the probe'

Reset-Case
$global:QWatchTest.ExitCode=1
$code=Invoke-Case
Assert-True ($code -eq 3 -and $global:QWatchTest.Starts -eq 0) 'DB or command failure does not restart workers'

Reset-Case
$global:QWatchTest.Health.notification='no_recipients'
$code=Invoke-Case
Assert-True ($code -eq 3 -and $global:QWatchTest.Events -contains 4104) 'Undeliverable email produces local alarm'

Reset-Case
$global:QWatchTest.LastRun=Get-Date
$code=Invoke-Case
Assert-True ($code -eq 0 -and $global:QWatchTest.Arguments -notcontains '--notify') 'Startup grace suppresses early alarm'

Reset-Case
$global:QWatchTest.State='Disabled'
$code=Invoke-Case
Assert-True ($code -eq 2 -and $global:QWatchTest.Probes -eq 0) 'Disabled task is respected'

Reset-Case
& $target -PortaleRoot $testRoot -MaintenanceMinutes 1
$code=Invoke-Case
Assert-True ($code -eq 0 -and $global:QWatchTest.Probes -eq 0) 'Maintenance skips probe and restart'
& $target -PortaleRoot $testRoot -Resume
Assert-True ($global:QWatchTest.Probes -eq 1) 'Resume performs health probe'

Reset-Case
$global:QWatchTest.State='Ready'
$restartFile = Join-Path $testRoot 'prod\logs\qcluster-watchdog-restarts.json'
@([DateTimeOffset]::UtcNow.ToString('o'), [DateTimeOffset]::UtcNow.ToString('o'), [DateTimeOffset]::UtcNow.ToString('o')) | ConvertTo-Json | Set-Content -LiteralPath $restartFile
$code=Invoke-Case
Assert-True ($code -eq 3 -and $global:QWatchTest.Starts -eq 0) 'Restart storm is capped'
Assert-True (@(Get-ChildItem (Join-Path $testRoot 'prod\logs') -Filter '*.tmp').Count -eq 0) 'Probe output cleaned'

Reset-Case
$logFile = Join-Path $testRoot 'prod\logs\qcluster-watchdog.log'
Move-Item -LiteralPath $logFile -Destination "$logFile.synthetic-backup"
New-Item -ItemType Directory -Path $logFile | Out-Null
$code=Invoke-Case
Assert-True ($code -eq 2 -and $global:QWatchTest.Events -contains 4104) 'Unwritable log does not suppress Windows event'
Write-Output 'PASS: 13 synthetic watchdog scenarios and cleanup.'
