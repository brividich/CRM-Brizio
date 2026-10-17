#Requires -Version 5.1
# Test degli script SQL di S1 (install-sql2025-instance.ps1, move-db-to-instance.ps1, _sqllib.ps1).
#   .\test-sql-scripts.ps1                         # solo controlli senza SQL Server (parsing, guardie)
#   .\test-sql-scripts.ps1 -SqlInstance .\SQLEXPRESS
#       + giro completo su un DB sintetico: crea PN_SQLTEST_SRC, lo "sposta" in PN_SQLTEST_DST
#         sulla stessa istanza (backup verificato, restore, CHECKDB, origine OFFLINE), verifica
#         dati e compatibility level, poi elimina entrambi. Nessun dato reale coinvolto.
param([string]$SqlInstance = "")
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scripts = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts'
. (Join-Path $scripts '_lib.ps1')
. (Join-Path $scripts '_sqllib.ps1')
$failures = 0
function Check([string]$Name, [scriptblock]$Body) {
    try { & $Body; Write-Host "OK   $Name" -ForegroundColor Green }
    catch { $script:failures++; Write-Host "FAIL $Name — $_" -ForegroundColor Red }
}
function Expect-Throw([scriptblock]$Body, [string]$Like) {
    try { & $Body } catch { if ("$_" -like "*$Like*") { return }; throw "eccezione inattesa: $_" }
    throw "nessuna eccezione (attesa: $Like)"
}

Check "parsing degli script" {
    foreach ($f in 'install-sql2025-instance.ps1', 'move-db-to-instance.ps1', '_sqllib.ps1') {
        $tokens = $null; $errs = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $scripts $f), [ref]$tokens, [ref]$errs)
        if (@($errs).Count) { throw "${f}: $($errs[0].Message)" }
    }
}
Check "rifiuto DB di sistema" { Expect-Throw { Assert-HubDatabaseName -Database 'master' } 'sistema' }
Check "rifiuto DLM/CNGAUGE senza consenso" {
    Expect-Throw { Assert-HubDatabaseName -Database 'DLM' } 'non è dell'
    Expect-Throw { Assert-HubDatabaseName -Database 'cngauge' } 'non è dell'
    Assert-HubDatabaseName -Database 'CNGAUGE' -AllowExternal
    Assert-HubDatabaseName -Database 'PortaleNovicrom_PROD'
}
Check "spazio libero: UNC non determinabile, locale sì" {
    if ($null -ne (Get-FreeSpaceMB '\\server\share\x')) { throw 'UNC deve restituire null' }
    if ((Get-FreeSpaceMB "$env:SystemDrive\cartella-che-non-esiste") -le 0) { throw 'spazio locale non letto' }
}
Check "nomi SQL quotati" {
    if ((ConvertTo-SqlName 'a]b') -ne '[a]]b]') { throw 'ConvertTo-SqlName' }
    if ((ConvertTo-SqlLiteral "o'k") -ne "N'o''k'") { throw 'ConvertTo-SqlLiteral' }
}
Check "install rifiuta nomi istanza riservati" {
    $out = & (Join-Path $scripts 'install-sql2025-instance.ps1') -InstanceName 'SQLEXPRESS' -WhatIf *>&1 | Out-String
    if ($LASTEXITCODE -ne 1 -or $out -notmatch 'riservato') { throw "exit $LASTEXITCODE" }
}
Check "move rifiuta CNGAUGE anche in WhatIf" {
    $out = & (Join-Path $scripts 'move-db-to-instance.ps1') -Database 'CNGAUGE' -SourceInstance '.\A' -TargetInstance '.\B' -WhatIf *>&1 | Out-String
    if ($LASTEXITCODE -ne 1 -or $out -notmatch "non è dell'HUB") { throw "exit $LASTEXITCODE" }
}

if ($SqlInstance) {
    $src = 'PN_SQLTEST_SRC'; $dst = 'PN_SQLTEST_DST'
    $cleanup = {
        foreach ($d in $src, $dst) {
            try {
                $info = Get-SqlDatabaseInfo -Instance $SqlInstance -Database $d
                if ($info) {
                    if ($info.State -eq 'OFFLINE') { Invoke-SqlNonQuery -Instance $SqlInstance -Statement "ALTER DATABASE [$d] SET ONLINE" | Out-Null }
                    Invoke-SqlNonQuery -Instance $SqlInstance -Statement "ALTER DATABASE [$d] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$d]" | Out-Null
                }
            } catch { Write-Host "pulizia ${d}: $_" -ForegroundColor Yellow }
        }
    }
    & $cleanup
    try {
        Check "giro completo di spostamento su DB sintetico" {
            Invoke-SqlNonQuery -Instance $SqlInstance -Statement "CREATE DATABASE [$src]; ALTER DATABASE [$src] SET COMPATIBILITY_LEVEL = 130" | Out-Null
            Invoke-SqlNonQuery -Instance $SqlInstance -Database $src -Statement "CREATE TABLE t (id INT PRIMARY KEY, v NVARCHAR(50)); INSERT INTO t VALUES (1, N'uno'), (2, N'due');" | Out-Null
            $staging = Join-Path $env:TEMP 'pn-sqltest-staging'
            & (Join-Path $scripts 'move-db-to-instance.ps1') -Database $src -SourceInstance $SqlInstance -TargetInstance $SqlInstance `
                -TargetDatabase $dst -StagingDir $staging -SetSourceOffline -Force -Confirm:$false | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "move exit $LASTEXITCODE" }
            $n = (Invoke-SqlQuery -Instance $SqlInstance -Database $dst -Query 'SELECT COUNT(*) FROM t')[0][0]
            if ($n -ne '2') { throw "righe copiate: $n" }
            $d = Get-SqlDatabaseInfo -Instance $SqlInstance -Database $dst
            if ($d.CompatibilityLevel -ne 130) { throw "compatibility level cambiato: $($d.CompatibilityLevel)" }
            if ((Get-SqlDatabaseInfo -Instance $SqlInstance -Database $src).State -ne 'OFFLINE') { throw 'origine non OFFLINE' }
            # idempotenza: rilanciato riconosce lo spostamento già fatto
            & (Join-Path $scripts 'move-db-to-instance.ps1') -Database $src -SourceInstance $SqlInstance -TargetInstance $SqlInstance `
                -TargetDatabase $dst -StagingDir $staging -Force -Confirm:$false | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "secondo giro exit $LASTEXITCODE" }
            Get-ChildItem $staging -Filter "$($src)_MOVE_*.bak" -ErrorAction SilentlyContinue | Remove-Item -Force
        }
    } finally { & $cleanup }
}

if ($failures) { Write-Host "$failures test falliti" -ForegroundColor Red; exit 1 }
Write-Host "Tutti i test superati" -ForegroundColor Green
exit 0
