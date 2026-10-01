#Requires -Version 5.1
# No live Task Scheduler, SQL, SMTP or worker operations.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$root=Join-Path $repo ('.tmp_tests\console ' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root -Force | Out-Null
. (Join-Path $repo 'deployment\scripts\qcluster-console.ps1') -Environment test -PortaleRoot $root
function Assert-QCAdmin {}
function Confirm-QC { param($Message); if ($global:QCFixture.Cancel) { throw 'cancelled' } }
function Read-Host { param($Prompt); '0' }
function Start-Sleep { param($Seconds) }
function Get-ScheduledTask {
    param($TaskPath,$TaskName)
    if ($TaskName -like 'QClusterWatchdog_*') { return [pscustomobject]@{State='Ready'} }
    [pscustomobject]@{
        State=$global:QCFixture.State
        Actions=@([pscustomobject]@{Execute='powershell.exe';Arguments=$global:QCFixture.Action})
        Principal=[pscustomobject]@{UserId='SYNTHETIC\service';LogonType='ServiceAccount'}
    }
}
function Disable-ScheduledTask { param($TaskPath,$TaskName); $global:QCFixture.State='Disabled'; $global:QCFixture.Mutations++ }
function Stop-ScheduledTask { param($TaskPath,$TaskName); $global:QCFixture.Mutations++ }
function Enable-ScheduledTask { param($TaskPath,$TaskName); $global:QCFixture.State='Ready'; $global:QCFixture.Mutations++ }
function Start-ScheduledTask { param($TaskPath,$TaskName); $global:QCFixture.Starts += $TaskName }
function Export-ScheduledTask { param($TaskPath,$TaskName); '<Task>Synthetic</Task>' }
function Get-CimInstance { param($ClassName,$Filter,$OperationTimeoutSec); $global:QCFixture.Processes }
function Invoke-QCPython {
    param([string[]]$Arguments,[int[]]$AllowedCodes=@(0))
    $global:QCFixture.Commands += ,$Arguments
    if ($Arguments[0] -eq $global:QCFixture.FailCommand) { throw 'synthetic command failed' }
}
function Invoke-QCHealth { param($TimeoutSeconds); Invoke-QCPython @('automation_health') }
function Assert-True($Value,$Message) { if (-not $Value) { throw "FAIL: $Message" } }
function Assert-Fails([scriptblock]$Action,[string]$Message) {
    $failed=$false
    try { & $Action } catch { $failed=$true }
    Assert-True $failed $Message
}
function Reset-Case {
    $script:QC.Environment='test'; $script:QC.Root=$root
    $script:QC.Prepared=$false; $script:QC.Verified=$false
    $script:QC.LauncherUpdated=$false; $script:QC.WatchdogInstalled=$false; $script:QC.Previewed=$false
    $global:QCFixture=@{State='Running';Cancel=$false;Mutations=0;Commands=@();Starts=@();Processes=@();FailCommand=''}
    foreach ($relative in @('venv\Scripts\python.exe','current\django_app\manage.py','current\BUILD_INFO.json','config\.env',
        'current\deployment\start_qcluster.ps1','current\deployment\watch_qcluster.ps1',
        'current\django_app\automazioni\migrations\0027_clusterheartbeat_clusterwatchdogstate.py')) {
        $file=Get-QCPath $relative
        New-Item -ItemType Directory -Path (Split-Path $file -Parent) -Force | Out-Null
        'synthetic' | Set-Content -LiteralPath $file
    }
    $launcher=Join-Path $root 'shared\scripts\start_qcluster.ps1'
    New-Item -ItemType Directory -Path (Split-Path $launcher -Parent) -Force | Out-Null
    'previous synthetic launcher' | Set-Content -LiteralPath $launcher
    $global:QCFixture.Action='-NoProfile -File "'+$launcher+'" -Environment test -PortaleRoot "'+$root+'"'
    $installer=Get-QCPath 'current\deployment\scripts\install-qcluster-watchdog.ps1'
    New-Item -ItemType Directory -Path (Split-Path $installer -Parent) -Force | Out-Null
    'param($Environment,$PortaleRoot)' | Set-Content -LiteralPath $installer
}

Reset-Case
Assert-QCPreflight
Assert-True ($global:QCFixture.Mutations -eq 0) 'Preflight read-only'
Assert-True ((Get-QCLauncher) -like '*console *') 'Quoted paths supported'

Reset-Case
$global:QCFixture.Action=$global:QCFixture.Action.Replace('-Environment test','-Environment prod')
Assert-Fails { Assert-QCPreflight } 'Wrong environment rejected'

Reset-Case
$global:QCFixture.Action=$global:QCFixture.Action.Replace($root,'C:\WrongRoot')
Assert-Fails { Assert-QCPreflight } 'Wrong root rejected'

Reset-Case
$global:QCFixture.Cancel=$true
Assert-Fails { Start-QCPreparation } 'Cancellation respected'
Assert-True ($global:QCFixture.Mutations -eq 0) 'Cancellation has no task mutation'

Reset-Case
$global:QCFixture.Processes=@([pscustomobject]@{ExecutablePath=$null;CommandLine=$null;ProcessId=123})
Assert-Fails { Get-QCWorkerProcesses } 'Unknown processes block operation'

Reset-Case
$global:QCFixture.Processes=@([pscustomobject]@{ExecutablePath=(Get-QCPath 'venv\Scripts\python.exe');CommandLine='python manage.py qcluster';ProcessId=123})
Assert-Fails { Start-QCPreparation } 'Orphan blocks readiness'
Assert-True (-not $script:QC.Prepared) 'Failed preparation not completed'

Reset-Case
Start-QCPreparation
Assert-True ($script:QC.Prepared -and $global:QCFixture.State -eq 'Disabled') 'Preparation complete'
Assert-True (Test-Path (Get-QCPath 'logs\qcluster-maintenance-until.txt')) 'Maintenance marker created'
Assert-True (@(Get-ChildItem (Get-QCPath 'logs\qcluster-deploy-backups') -Filter worker-task.xml -Recurse).Count -gt 0) 'Task backup exists'

Reset-Case
Assert-Fails { Invoke-QCVerification } 'No migration without preparation'
Assert-True ($global:QCFixture.Commands.Count -eq 0) 'No command before preparation'

Reset-Case
Start-QCPreparation
$global:QCFixture.FailCommand='apply_sql_triggers'
Assert-Fails { Invoke-QCVerification } 'Pipeline stops on failed command'
Assert-True ($global:QCFixture.Commands.Count -eq 2 -and -not $script:QC.Verified) 'No subsequent commands or green status'

Reset-Case
Start-QCPreparation
Invoke-QCVerification
Update-QCLauncher
Install-QCWatchdog
Assert-True ($script:QC.Verified -and $script:QC.LauncherUpdated -and $script:QC.WatchdogInstalled) 'Post-deploy ready'
Assert-True ((Get-FileHash (Get-QCLauncher)).Hash -eq (Get-FileHash (Get-QCPath 'current\deployment\start_qcluster.ps1')).Hash) 'Real launcher copied'
Start-QCWorker
Assert-True ($global:QCFixture.Starts -contains 'QCluster_TEST' -and $global:QCFixture.Starts -contains 'QClusterWatchdog_TEST') 'Worker and watchdog started'
Assert-True (-not (Test-Path (Get-QCPath 'logs\qcluster-maintenance-until.txt'))) 'Maintenance cleared after start'

Reset-Case
Start-QCPreparation
Assert-Fails { Start-QCWorker } 'Cannot skip post-deploy prerequisites'
Assert-True ($global:QCFixture.Starts.Count -eq 0) 'No premature start'

Reset-Case
Start-QCPreparation
Invoke-QCVerification
Assert-Fails { Invoke-QCRecovery -Apply } 'Apply requires preview'
Invoke-QCRecovery
$global:QCFixture.FailCommand='merge_assenze_flows'
$before=$global:QCFixture.Commands.Count
Assert-Fails { Invoke-QCRecovery -Apply } 'Failed merge does not recover broker'
Assert-True ($global:QCFixture.Commands.Count -eq ($before+1)) 'Recovery stops after first failure'

Reset-Case
Start-QCPreparation
Invoke-QCVerification
Update-QCLauncher
Install-QCWatchdog
$global:QCFixture.FailCommand='automation_health'
Assert-Fails { Start-QCWorker } 'Unhealthy restart never reports success'
Assert-True ($global:QCFixture.Starts -contains 'QClusterWatchdog_TEST') 'Watchdog resumed to report unhealthy worker'
Assert-True (-not (Test-Path (Get-QCPath 'logs\qcluster-maintenance-until.txt'))) 'No silent pause after failed health'

Reset-Case
Start-QCMenu
Assert-True ($global:QCFixture.Mutations -eq 0) 'Exiting menu does not change tasks'

Reset-Case
Start-QCPreparation
Invoke-QCVerification
'other synthetic release' | Set-Content -LiteralPath (Get-QCPath 'current\BUILD_INFO.json')
Assert-Fails { Update-QCLauncher } 'Changing current after validation invalidates the workflow'
Write-Output 'PASS: 15 console scenarios; no real tasks, DB or email touched.'
