#Requires -Version 5.1
# Test del tool di ripristino (BUILD_SPEC R3 §5.5), senza toccare il sistema:
# funzioni di _restorelib.ps1 (ripresa da state.json, rifiuto del downgrade SQL, rifiuto
# dei DB fuori piano, prerequisiti senza hash o con hash diverso, report) e restore-host.ps1
# in -WhatIf su un target sintetico (nessuna modifica, nessun segreto nel transcript).
#   .\test-restore-host.ps1 -Python C:\Dev\Portale Novicrom\.venv\Scripts\python.exe
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [string]$WorkDir = "$env:SystemDrive\Temp"     # percorso lungo: i percorsi 8.3 di %TEMP% confondono PS 5.1
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scripts = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. (Join-Path $scripts '_lib.ps1')
. (Join-Path $scripts '_sqllib.ps1')
. (Join-Path $scripts '_restorelib.ps1')
$failures = 0
function Check([string]$Name, [scriptblock]$Body) {
    try { & $Body; Write-Host "OK   $Name" -ForegroundColor Green }
    catch { $script:failures++; Write-Host "FAIL $Name — $_" -ForegroundColor Red }
}
function Expect-Throw([scriptblock]$Body, [string]$Like) {
    try { & $Body } catch { if ("$_" -like "*$Like*") { return }; throw "eccezione inattesa: $_" }
    throw "nessuna eccezione (attesa: $Like)"
}

$tmp = Join-Path $WorkDir ("pn-restore-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    Check "ripresa: salta le fasi già completate" {
        $state = New-RestoreState @{ Environment = 'prod' }
        $state.phases['preflight'] = [ordered]@{ status = 'ok'; notes = @() }
        $state.phases['prereqs'] = [ordered]@{ status = 'ok'; notes = @() }
        $state.phases['sql'] = [ordered]@{ status = 'failed'; notes = @() }
        $p = Join-Path $tmp 'state.json'
        Save-RestoreState $state $p
        $back = Read-RestoreState $p
        $pending = @(Get-PendingPhases $back @() -Resume)
        if ($pending[0].Key -ne 'sql') { throw "prima fase da fare: $($pending[0].Key)" }
        if ((@(Get-PendingPhases $back @('entra', '9'))).Key -contains 'entra') { throw '-SkipPhase non rispettato' }
        if ((@(Get-PendingPhases $back @())).Count -ne 12) { throw 'senza -Resume devono esserci tutte le fasi' }
    }
    Check "rifiuto del downgrade di SQL Server" {
        Expect-Throw { Assert-SqlVersionCompatible '17.0.1000.7' (ConvertTo-SqlMajor 2022) } 'inferiore'
        Assert-SqlVersionCompatible '16.0.4135.4' (ConvertTo-SqlMajor 2025)
        Assert-SqlVersionCompatible '17.0.1000.7' (ConvertTo-SqlMajor 2025)
    }
    Check "rifiuto dei database fuori dal piano" {
        $plan = '{"databases":{"PortaleNovicrom_PROD":{}}}' | ConvertFrom-Json
        Assert-DatabaseInPlan $plan 'PortaleNovicrom_PROD'
        Expect-Throw { Assert-DatabaseInPlan $plan 'CNGAUGE' } 'non è nel piano'
    }
    Check "prerequisiti: senza hash nessun download; cache con hash diverso ignorata" {
        $noHash = '{"name":"x","url_resolved":"https://example.invalid/x.exe"}' | ConvertFrom-Json
        Expect-Throw { Get-VerifiedInstaller $noHash $tmp } 'non ha un hash'
        $f = Join-Path $tmp 'fake.exe'; Set-Content -Path $f -Value 'contenuto' -Encoding ASCII
        $good = (Get-FileHash -Algorithm SHA256 $f).Hash.ToLowerInvariant()
        $item = [pscustomobject]@{ name = 'fake'; sha256 = $good; file_name = 'fake.exe'; url_resolved = 'https://example.invalid/fake.exe' }
        if ((Get-VerifiedInstaller $item $tmp -NoDownload) -ne $f) { throw 'la cache valida non è stata usata' }
        $item.sha256 = ('0' * 64)
        Expect-Throw { Get-VerifiedInstaller $item $tmp -NoDownload } 'download non è consentito'
    }
    Check "prerequisiti: filtro per Python e funzioni" {
        $facts = @{ python_minor = '3.13'; sql_missing = $false; entra_connector = $true; host_extensions = 'rewrite' }
        $py313 = [pscustomobject]@{ when = 'python_minor=3.13' }; $py311 = [pscustomobject]@{ when = 'python_minor=3.11' }
        if (-not (Test-PrereqWanted $py313 $facts) -or (Test-PrereqWanted $py311 $facts)) { throw 'filtro Python' }
        if (Test-PrereqWanted ([pscustomobject]@{ when = 'sql_missing' }) $facts) { throw 'filtro SQL' }
    }
    Check "report HTML e JSON con RTO" {
        $state = New-RestoreState @{ Environment = 'prod' }
        $state.started_at = (Get-Date).AddMinutes(-42).ToString('o')
        $state.phases['verify'] = [ordered]@{ status = 'ok'; started_at = $null; finished_at = (Get-Date).ToString('o'); seconds = 5; notes = @('<script>') }
        $state.manual_actions = @('Aggiornare il DNS')
        $r = Write-RestoreReport $state $tmp
        if ($r.RtoMinutes -lt 41) { throw "RTO $($r.RtoMinutes)" }
        $html = Get-Content $r.Html -Raw
        if ($html -match '<script>') { throw 'note non codificate in HTML' }
        if ($html -notmatch 'Aggiornare il DNS') { throw 'azioni manuali assenti' }
    }

    # target sintetico: FULL + LOG + FILES + HOST con manifest
    $envRoot = Join-Path $tmp 'target\prod'
    function New-Set([string]$Id, [hashtable]$Extra) {
        $d = Join-Path $envRoot $Id; New-Item -ItemType Directory -Force -Path $d | Out-Null
        $m = @{ schema_version = 1; set_id = $Id; type = $Id.Split('_')[-1]; env = 'prod'; status = 'ok';
                app = @{ version = '1.6.2'; commit = 'abc'; migrations = @{ core = '0090_x' } }; artifacts = @(); warnings = @();
                keys = @{ document_encryption_key_sha256 = ('k' * 64); secret_key_sha256 = ('s' * 64) }; duration_s = 1 }
        foreach ($k in $Extra.Keys) { $m[$k] = $Extra[$k] }
        ($m | ConvertTo-Json -Depth 8) | Set-Content (Join-Path $d 'manifest.json') -Encoding UTF8
    }
    New-Set '20261016_020000_full' @{ sql = @{ product_version = '17.0.1000.7'; collation = 'Latin1_General_CI_AS' };
        databases = @(@{ name = 'PortaleNovicrom_PROD'; allocated_mb = 10 });
        artifacts = @(@{ path = 'db/P_FULL.bak'; sha256 = ('a' * 64); size = 1; kind = 'full'; database = 'PortaleNovicrom_PROD'; verify_status = 'ok'; lsn = @{ first = 1; last = 100 } }) }
    New-Set '20261016_100500_log' @{ chain = @{ full_set_id = '20261016_020000_full'; databases = @{ PortaleNovicrom_PROD = @{ first_lsn = '90'; last_lsn = '200' } } };
        artifacts = @(@{ path = 'db/P_LOG.trn'; sha256 = ('b' * 64); size = 1; kind = 'log'; database = 'PortaleNovicrom_PROD'; verify_status = 'ok' }) }
    New-Set '20261016_023000_files' @{ files = @{ total_bytes = 1024 } }
    $idxDir = Join-Path $envRoot '20261016_023000_files\files'; New-Item -ItemType Directory -Force -Path $idxDir | Out-Null
    [IO.File]::WriteAllText((Join-Path $idxDir 'index.json'), '{"media":{"path":"C:\\PortaleNovicrom\\prod\\media","files":{}}}')
    New-Set '20261016_030000_host' @{ release_ref = '_releases/portale-novicrom-v1.6.2-x.zip' }
    $hostDir = Join-Path $envRoot '20261016_030000_host\host'; New-Item -ItemType Directory -Force -Path $hostDir | Out-Null
    '{"python":{"version":"3.13.1"},"scheduled_tasks":[],"unc_paths":[]}' | Set-Content (Join-Path $hostDir 'host-manifest.json') -Encoding UTF8
    $planFile = Join-Path $tmp 'restore-plan.json'
    & $Python -I (Join-Path $repo 'django_app\core\backup_engine\restore_plan.py') $envRoot --out $planFile | Out-Null

    Check "piano dal target sintetico" {
        $plan = Get-Content $planFile -Raw | ConvertFrom-Json
        if ($plan.full_set_id -ne '20261016_020000_full' -or $plan.last_log_set_id -ne '20261016_100500_log') { throw 'piano errato' }
    }
    Check "restore-host -WhatIf: tutte le fasi, nessuna modifica, nessun segreto" {
        $before = @(Get-ChildItem 'C:\PortaleNovicrom\shared\recovery' -Filter 'state.json' -ErrorAction SilentlyContinue).Count
        $out = & (Join-Path $scripts 'restore-host.ps1') -BackupTarget (Join-Path $tmp 'target') -PlanFile $planFile `
            -RecoveryKit (Join-Path $tmp 'kit.hubkit') -PublicHostname 'hub.example.test' -SkipEntra -BootstrapPython $Python -WhatIf *>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE`n$out" }
        foreach ($n in 0..11) { if ($out -notmatch "Fase $n ·") { throw "fase $n non eseguita" } }
        if ($out -notmatch 'RESTORE PortaleNovicrom_PROD \(FULL \+ 1 log\)') { throw 'restore del DB non pianificato' }
        if ($out -match 'PFX_PASSWORD|passphrase:') { throw 'possibile segreto a video' }
        $after = @(Get-ChildItem 'C:\PortaleNovicrom\shared\recovery' -Filter 'state.json' -ErrorAction SilentlyContinue).Count
        if ($after -ne $before) { throw 'in WhatIf è stato scritto state.json' }
    }
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
if ($failures) { Write-Host "$failures test falliti" -ForegroundColor Red; exit 1 }
Write-Host 'Tutti i test superati' -ForegroundColor Green
exit 0
