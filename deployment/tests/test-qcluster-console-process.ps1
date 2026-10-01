#Requires -Version 5.1
param([Parameter(Mandatory=$true)][string]$VenvPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$root=Join-Path $repo ('.tmp_tests\console process ' + [Guid]::NewGuid().ToString('N'))
$app=Join-Path $root 'test\current\django_app'
New-Item -ItemType Directory -Path $app -Force | Out-Null
$link=Join-Path $root 'test\venv'
New-Item -ItemType Junction -Path $link -Target $VenvPath | Out-Null
$oldMode=$env:QC_SYNTHETIC_MODE
$oldSettings=$env:DJANGO_SETTINGS_MODULE
$oldBootstrap=$env:PORTAL_SKIP_RUNTIME_BOOTSTRAP
try {
@'
import json, os, sys, time
from pathlib import Path
assert '--settings=config.settings.prod' in sys.argv
assert os.environ['DJANGO_SETTINGS_MODULE'] == 'config.settings.prod'
assert os.environ['PORTAL_SKIP_RUNTIME_BOOTSTRAP'] == '1'
if sys.argv[1] == 'fail':
    sys.exit(7)
if sys.argv[1] != 'automation_health':
    print('synthetic check passed')
    sys.exit(0)
mode = os.environ.get('QC_SYNTHETIC_MODE', 'healthy')
if mode == 'timeout':
    Path('health-probe.pid').write_text(str(os.getpid()))
    time.sleep(30)
if mode == 'malformed':
    print('not JSON')
    sys.exit(0)
bad = mode == 'unhealthy'
print(json.dumps({'worker_alive':not bad, 'unhealthy':bad, 'reason':'synthetic'}))
sys.exit(2 if bad else 0)
'@ | Set-Content -LiteralPath (Join-Path $app 'manage.py') -Encoding ASCII
    . (Join-Path $repo 'deployment\scripts\qcluster-console.ps1') -Environment test -PortaleRoot $root
    Invoke-QCPython @('check')
    $failed=$false
    try { Invoke-QCPython @('fail') } catch { $failed=$true }
    if (-not $failed) { throw 'Nonzero exit was ignored' }
    if ($env:DJANGO_SETTINGS_MODULE -ne $oldSettings -or $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP -ne $oldBootstrap) { throw 'Environment not restored' }
    $env:QC_SYNTHETIC_MODE='healthy'
    Invoke-QCHealth -TimeoutSeconds 10
    foreach ($mode in @('unhealthy','malformed','timeout')) {
        $env:QC_SYNTHETIC_MODE=$mode
        $failed=$false
        try { Invoke-QCHealth -TimeoutSeconds 3 } catch { $failed=$true }
        if (-not $failed) { throw "Health $mode was accepted" }
    }
    $pidFile=Join-Path $app 'health-probe.pid'
    if (Test-Path -LiteralPath $pidFile) {
        $probePid=[int](Get-Content -LiteralPath $pidFile)
        if (Get-Process -Id $probePid -ErrorAction SilentlyContinue) { throw 'Timed-out probe child still running' }
    }
    if (@(Get-ChildItem (Join-Path $root 'test\logs') -Filter '*.tmp').Count) { throw 'Probe output not removed' }
    Write-Output 'PASS: native success/failure, environment restore, healthy/unhealthy/invalid JSON, timeout tree cleanup.'
} finally {
    $env:QC_SYNTHETIC_MODE=$oldMode
    $env:DJANGO_SETTINGS_MODULE=$oldSettings
    $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP=$oldBootstrap
    if ((Get-Item -LiteralPath $link).Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($link) }
}
