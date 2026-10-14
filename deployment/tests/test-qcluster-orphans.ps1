#Requires -Version 5.1
# Launcher reale in un processo separato, con manage.py sintetico che resta vivo:
# 1) all'avvio chiude un qcluster residuo dello stesso venv;
# 2) se il launcher viene ucciso, il job object chiude anche il python figlio.
param([Parameter(Mandatory=$true)][string]$VenvPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$testRoot = Join-Path $repo ('.tmp_tests\qcluster orphans ' + [Guid]::NewGuid().ToString('N'))
$envRoot = Join-Path $testRoot 'test'
$app = Join-Path $envRoot 'current\django_app'
New-Item -ItemType Directory -Path $app -Force | Out-Null
$venvLink = Join-Path $envRoot 'venv'
New-Item -ItemType Junction -Path $venvLink -Target $VenvPath | Out-Null
$python = Join-Path $venvLink 'Scripts\python.exe'
$launcher = $null; $orphan = $null; $children = @(); $tag = $null
function Get-Synthetic { @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -match [regex]::Escape($tag) }) }
function Wait-Until([scriptblock]$Cond, [int]$Seconds) {
    $limit = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $limit) { if (& $Cond) { return $true }; Start-Sleep -Milliseconds 500 }
    return $false
}
try {
    $tag = 'synthetic-' + [Guid]::NewGuid().ToString('N')
@"
import time
# $tag
time.sleep(600)
"@ | Set-Content -LiteralPath (Join-Path $app 'manage.py') -Encoding ASCII
    # Residuo: un "qcluster" dello stesso venv senza launcher vivo.
    $orphan = Start-Process -FilePath $python -ArgumentList @('manage.py', 'qcluster', '--settings=config.settings.prod', "--tag=$tag") `
        -WorkingDirectory $app -WindowStyle Hidden -PassThru
    if (-not (Wait-Until { @(Get-Synthetic).Count -ge 1 } 15)) { throw 'Residuo sintetico non partito' }
    $before = @(Get-Synthetic).ProcessId

    $launcher = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $repo 'deployment\start_qcluster.ps1'),
        '-Environment', 'test', '-PortaleRoot', "`"$testRoot`"")
    $log = Join-Path $envRoot 'logs\qcluster.log'
    if (-not (Wait-Until { (Test-Path $log) -and (Select-String -LiteralPath $log -Pattern 'PID processo figlio' -Quiet) } 60)) {
        throw 'Launcher non ha avviato il figlio'
    }
    if (-not (Wait-Until { -not @(Get-Synthetic | Where-Object { $before -contains $_.ProcessId }).Count } 15)) {
        throw 'Residuo non chiuso dal launcher'
    }
    if (-not (Select-String -LiteralPath $log -Pattern 'qcluster residuo' -Quiet)) { throw 'Chiusura residuo non registrata nel log' }
    if (-not (Select-String -LiteralPath $log -Pattern 'job kill-on-close' -Quiet)) { throw 'Job object non attivato' }
    Write-Output 'PASS: residuo dello stesso venv chiuso all avvio.'

    # Il figlio del launcher non ha il tag in riga di comando: si segue l'albero.
    function Get-Tree($id) { $all | Where-Object ParentProcessId -eq $id | ForEach-Object { $_.ProcessId; Get-Tree $_.ProcessId } }
    $children = @()
    $null = Wait-Until { $script:all = @(Get-CimInstance Win32_Process); $script:children = @(Get-Tree $launcher.Id); $script:children.Count -ge 2 } 15
    $children = @($script:children)
    if (-not $children.Count) { throw 'Figlio del launcher non trovato' }
    Stop-Process -Id $launcher.Id -Force
    if (-not (Wait-Until { -not @(Get-Process -Id $children -ErrorAction SilentlyContinue).Count } 15)) {
        throw "Il python figlio sopravvive al launcher: $($children -join ',')"
    }
    Write-Output 'PASS: launcher ucciso, nessun python orfano.'
} finally {
    if ($launcher -and -not $launcher.HasExited) { & taskkill.exe /PID $launcher.Id /T /F 2>&1 | Out-Null }
    if ($children) { Stop-Process -Id $children -Force -ErrorAction SilentlyContinue }
    if ($tag) { Get-Synthetic | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }
    if ((Get-Item -LiteralPath $venvLink).Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($venvLink) }
}
