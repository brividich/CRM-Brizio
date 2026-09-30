#Requires -Version 5.1
param([Parameter(Mandatory=$true)][string]$VenvPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$testRoot = Join-Path $repo ('.tmp_tests\qcluster launcher ' + [Guid]::NewGuid().ToString('N'))
$envRoot = Join-Path $testRoot 'test'
$app = Join-Path $envRoot 'current\django_app'
New-Item -ItemType Directory -Path $app -Force | Out-Null
# The venv is read-only during the probe; only synthetic manage.py is executed.
$venvLink = Join-Path $envRoot 'venv'
New-Item -ItemType Junction -Path $venvLink -Target $VenvPath | Out-Null
try {
@'
import os
import sys
assert sys.argv[1:] == ['qcluster', '--settings=config.settings.prod'], sys.argv
assert os.environ['DJANGO_SETTINGS_MODULE'] == 'config.settings.prod'
assert os.environ['PORTAL_SKIP_RUNTIME_BOOTSTRAP'] == '0'
for n in range(4000):
    print('synthetic output ' + 'x' * 160)
    print('synthetic error ' + 'x' * 160, file=sys.stderr)
sys.exit(7)
'@ | Set-Content -LiteralPath (Join-Path $app 'manage.py') -Encoding ASCII
& (Join-Path $repo 'deployment\start_qcluster.ps1') -Environment test -PortaleRoot $testRoot -Once
if ($LASTEXITCODE -ne 7) { throw "Expected synthetic exit 7, got $LASTEXITCODE" }
$logs = @(Get-ChildItem -LiteralPath (Join-Path $envRoot 'logs') -Filter 'qcluster_*.log')
if ($logs.Count -ne 2 -or ($logs | Measure-Object Length -Sum).Sum -lt 1MB) { throw 'Output incomplete or blocked' }
Write-Output 'PASS: actual launcher, path with spaces, deployed TEST settings, >1 MB output, preserved exit 7.'
} finally {
    # Non-recursive removal of this synthetic junction, never its target.
    if ((Get-Item -LiteralPath $venvLink).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        [IO.Directory]::Delete($venvLink)
    }
}
