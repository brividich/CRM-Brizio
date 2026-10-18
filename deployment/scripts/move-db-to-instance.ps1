# move-db-to-instance.ps1
# Sposta un database da un'istanza SQL Server a un'altra (BUILD_SPEC S1.3) con
# backup verificato, restore verificato, login e utenti orfani, DBCC CHECKDB,
# aggiornamento facoltativo del .env e messa OFFLINE (non cancellazione) del DB
# di origine. Generico: riusabile per DLM/CNGAUGE solo con -AllowExternalDatabase.
#
# Esempi:
#   # dry-run (nessuna modifica, mostra piano e controlli)
#   .\move-db-to-instance.ps1 -Database PortaleNovicrom_TEST -SourceInstance .\SQLEXPRESS -TargetInstance .\HUB2025 -WhatIf
#   # prova su TEST con manutenzione, .env e origine offline
#   .\move-db-to-instance.ps1 -Database PortaleNovicrom_TEST -SourceInstance .\SQLEXPRESS -TargetInstance .\HUB2025 `
#       -Environment test -NewDbHost "PCLOGSYS\HUB2025" -UpdateEnv -SetSourceOffline -Logins "IIS APPPOOL\PortaleNovicrom-TEST"
#
# In produzione lo esegue solo Brizio, in finestra di manutenzione, DOPO audit_archive --run.
# Rollback: ripristinare il .env salvato (config\.env.bak-<ts>) e ALTER DATABASE [db] SET ONLINE sull'origine.

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory)][string]$Database,
    [Parameter(Mandatory)][string]$SourceInstance,
    [Parameter(Mandatory)][string]$TargetInstance,
    [string]$TargetDatabase = "",
    [ValidateSet("", "test", "prod")][string]$Environment = "",
    [string]$NewDbHost = "",
    [switch]$UpdateEnv,
    [switch]$SetSourceOffline,
    [string[]]$Logins = @(),
    [string]$StagingDir = "C:\PortaleNovicrom\shared\backup-staging\move",
    [string]$TargetDataDir = "",
    [switch]$SkipCheckDb,
    [switch]$IgnoreCrossDatabaseReferences,
    [switch]$AllowExternalDatabase,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"
. "$PSScriptRoot\_sqllib.ps1"

$dryRun = [bool]$WhatIfPreference
if (-not $TargetDatabase) { $TargetDatabase = $Database }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$workDir = "C:\PortaleNovicrom\shared\sql2025"
if (-not (Test-Path (Split-Path $workDir -Parent))) { $workDir = Join-Path $env:TEMP "pn-sql2025" }
New-Item -ItemType Directory -Force -Path $workDir -WhatIf:$false | Out-Null
$transcript = Join-Path $workDir "move-$Database-$stamp.log"
$wi = $WhatIfPreference; $WhatIfPreference = $false; Start-Transcript -Path $transcript -Append | Out-Null; $WhatIfPreference = $wi

$report = [ordered]@{
    database = $Database; target_database = $TargetDatabase; source = $SourceInstance; target = $TargetInstance
    started_at = (Get-Date).ToString("o"); dry_run = $dryRun; steps = @(); warnings = @(); orphans = @(); result = "running"
}
$clock = [Diagnostics.Stopwatch]::StartNew()
function Step([string]$Name, [scriptblock]$Body) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Write-Log $Name "STEP"
    & $Body
    $report.steps += [ordered]@{ step = $Name; seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
}
function Warn([string]$Message) { Write-Log $Message "WARN"; $report.warnings += $Message }

$paths = $null
$maintenanceStarted = $false
$qclusterTask = $null; $watchdogTask = $null; $watchdogWasEnabled = $false; $appPool = $null

try {
    Write-LogSeparator
    Write-Log "Spostamento DB [$Database] $SourceInstance → $TargetInstance [$TargetDatabase]$(if ($dryRun) { ' [WhatIf]' })" "STEP"
    Assert-HubDatabaseName -Database $Database -AllowExternal:$AllowExternalDatabase
    Assert-HubDatabaseName -Database $TargetDatabase -AllowExternal:$AllowExternalDatabase
    if (-not $dryRun -and $Environment) { Assert-Admin }   # servizi IIS/task e .env protetto
    if ($UpdateEnv -and (-not $Environment -or -not $NewDbHost)) { throw "-UpdateEnv richiede -Environment e -NewDbHost." }
    if ($Environment) { Assert-ValidEnvironment $Environment; $paths = Get-EnvPaths $Environment }

    # ── 0. Preflight ─────────────────────────────────────────────────────────
    $src = $null; $tgt = $null; $db = $null
    Step "Preflight" {
        $script:src = Get-SqlInstanceInfo -Instance $SourceInstance
        $script:tgt = Get-SqlInstanceInfo -Instance $TargetInstance
        Write-Log "Origine: $($src.Edition) $($src.ProductVersion) · $($src.Collation)" "INFO"
        Write-Log "Destinazione: $($tgt.Edition) $($tgt.ProductVersion) · $($tgt.Collation)" "INFO"
        if ($tgt.Major -lt $src.Major) { throw "Versione di destinazione ($($tgt.ProductVersion)) inferiore all'origine: un backup non si ripristina su una versione più vecchia." }
        if ($tgt.Collation -ne $src.Collation) { Warn "Collation di server diverse ($($src.Collation) / $($tgt.Collation)): tempdb e confronti tra tabelle temporanee possono comportarsi diversamente." }
        $script:db = Get-SqlDatabaseInfo -Instance $SourceInstance -Database $Database
        if (-not $db) { throw "Database [$Database] non trovato su $SourceInstance." }
        Write-Log "DB origine: stato $($db.State), recovery $($db.RecoveryModel), compat $($db.CompatibilityLevel), $($db.AllocatedMB) MB allocati, owner $($db.Owner)" "INFO"
        $existing = Get-SqlDatabaseInfo -Instance $TargetInstance -Database $TargetDatabase
        if ($existing) {
            if ($existing.State -eq "ONLINE" -and $db.State -eq "OFFLINE") {
                Write-Log "[$TargetDatabase] è già ONLINE sulla destinazione e l'origine è OFFLINE: spostamento già eseguito." "SUCCESS"
                $report.result = "already_moved"; return
            }
            throw "Esiste già [$TargetDatabase] su $TargetInstance (stato $($existing.State)): rifiuto di sovrascriverlo."
        }
        if ($db.State -ne "ONLINE") { throw "Il DB di origine non è ONLINE (stato $($db.State))." }
        if (($SourceInstance -ieq $TargetInstance) -and ($Database -ieq $TargetDatabase)) { throw "Origine e destinazione coincidono." }

        # Riferimenti ad altri database (nomi a tre parti, sinonimi): si romperebbero sulla nuova istanza.
        $xdb = Invoke-SqlQuery -Instance $SourceInstance -Database $Database -Query @"
SELECT DISTINCT OBJECT_SCHEMA_NAME(referencing_id) + '.' + OBJECT_NAME(referencing_id), referenced_database_name
FROM sys.sql_expression_dependencies
WHERE referenced_database_name IS NOT NULL AND referenced_database_name <> DB_NAME()
UNION ALL
SELECT SCHEMA_NAME(schema_id) + '.' + name, PARSENAME(base_object_name, 3)
FROM sys.synonyms WHERE PARSENAME(base_object_name, 3) IS NOT NULL AND PARSENAME(base_object_name, 3) <> DB_NAME()
"@
        foreach ($r in $xdb) { Warn "Riferimento a un altro database: $($r[0]) → [$($r[1])]" }
        if ($xdb.Count -gt 0 -and -not $IgnoreCrossDatabaseReferences) {
            throw "Il DB contiene $($xdb.Count) riferimenti ad altri database: risolverli o usare -IgnoreCrossDatabaseReferences consapevolmente."
        }

        $staging = $StagingDir
        if (-not $dryRun) {
            New-Item -ItemType Directory -Force -Path $staging | Out-Null
            # i servizi SQL (account virtuali NT Service\MSSQL$<istanza>) scrivono e leggono il .bak
            foreach ($inst in @($SourceInstance, $TargetInstance) | Select-Object -Unique) {
                $parts = $inst -split "\\", 2
                $svc = if ($parts.Count -eq 2 -and $parts[1]) { "NT Service\MSSQL`$$($parts[1])" } else { "NT Service\MSSQLSERVER" }
                & icacls.exe $staging /grant "$($svc):(OI)(CI)M" /Q | Out-Null
                if ($LASTEXITCODE -ne 0) { Warn "icacls: permesso a $svc su $staging non assegnato (exit $LASTEXITCODE)." }
            }
        }
        $freeStaging = Get-FreeSpaceMB $staging
        if ($freeStaging -ne $null -and $freeStaging -lt [int64]($db.AllocatedMB * 1.1)) { throw "Spazio insufficiente in $staging ($freeStaging MB liberi, servono ~$([int64]($db.AllocatedMB * 1.1)) MB)." }
        $dataDir = if ($TargetDataDir) { $TargetDataDir } else { $tgt.DefaultDataPath }
        $freeData = Get-FreeSpaceMB $dataDir
        if ($freeData -ne $null -and $freeData -lt [int64]($db.AllocatedMB * 1.1)) { throw "Spazio insufficiente in $dataDir ($freeData MB liberi)." }
        $limit = if ($tgt.Edition -match "Express") { if ($tgt.Major -ge 17) { 51200 } else { 10240 } } else { 0 }
        if ($limit -and $db.AllocatedMB -gt $limit * 0.85) { Warn "Il DB ($($db.AllocatedMB) MB) supera l'85% del limite dell'edizione di destinazione ($limit MB)." }
        Write-Log "Preflight OK (staging libero $freeStaging MB, dati destinazione liberi $freeData MB)." "SUCCESS"
    }
    if ($report.result -eq "already_moved") { return }

    if (-not $dryRun -and -not $Force) {
        if (-not $PSCmdlet.ShouldContinue("Spostare [$Database] da $SourceInstance a $TargetInstance$(if ($Environment) { " con portale $Environment in manutenzione" })?", "Conferma")) {
            throw "Annullato dall'operatore."
        }
    }

    # ── 1. Manutenzione: pool IIS e qcluster fermi ──────────────────────────
    if ($Environment) {
        Step "Manutenzione: stop pool IIS e qcluster ($Environment)" {
            $script:appPool = "PortaleNovicrom-$($Environment.ToUpper())"
            $script:qclusterTask = Get-ScheduledTask -TaskPath "\PortaleNovicrom\" -TaskName "QCluster_$($Environment.ToUpper())" -ErrorAction SilentlyContinue
            $script:watchdogTask = Get-ScheduledTask -TaskPath "\PortaleNovicrom\" -TaskName "QClusterWatchdog_$($Environment.ToUpper())" -ErrorAction SilentlyContinue
            if ($PSCmdlet.ShouldProcess($Environment, "Stop pool IIS $appPool, watchdog e qcluster")) {
                $script:maintenanceStarted = $true
                if ($watchdogTask) {
                    $script:watchdogWasEnabled = $watchdogTask.State -ne "Disabled"
                    Disable-ScheduledTask -InputObject $watchdogTask | Out-Null   # altrimenti riavvia il qcluster
                }
                Stop-IISAppPool -AppPoolName $appPool
                if ($qclusterTask) { Stop-ScheduledTask -InputObject $qclusterTask }
                # residui qcluster del venv dell'ambiente (i figli possono sopravvivere al launcher)
                $venvPython = Join-Path $paths.Venv "Scripts\python.exe"
                Start-Sleep -Seconds 3
                Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
                    Where-Object { $_.ExecutablePath -eq $venvPython -and $_.CommandLine -match '\bqcluster\b' } |
                    ForEach-Object { & "$env:SystemRoot\System32\taskkill.exe" /PID $_.ProcessId /T /F 2>&1 | Out-Null; Write-Log "Chiuso qcluster residuo PID $($_.ProcessId)" "WARN" }
            }
        }
    }

    # ── 2. Backup verificato ────────────────────────────────────────────────
    $bak = Join-Path $StagingDir "$($Database -replace '[^A-Za-z0-9_-]', '_')_MOVE_$stamp.bak"
    Step "Backup FULL WITH CHECKSUM + RESTORE VERIFYONLY" {
        if ($PSCmdlet.ShouldProcess($bak, "BACKUP DATABASE [$Database] (COPY_ONLY, CHECKSUM)")) {
            Invoke-SqlNonQuery -Instance $SourceInstance -Statement "BACKUP DATABASE $(ConvertTo-SqlName $Database) TO DISK = $(ConvertTo-SqlLiteral $bak) WITH COPY_ONLY, CHECKSUM, INIT, FORMAT, STATS = 10" | Out-Null
            Invoke-SqlNonQuery -Instance $SourceInstance -Statement "RESTORE VERIFYONLY FROM DISK = $(ConvertTo-SqlLiteral $bak) WITH CHECKSUM" | Out-Null
            $report.backup_file = $bak
            $report.backup_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $bak).Hash.ToLowerInvariant()
            Write-Log "Backup verificato: $bak ($([int]((Get-Item $bak).Length / 1MB)) MB)" "SUCCESS"
        }
    }

    # ── 3. Restore sulla destinazione ───────────────────────────────────────
    Step "Restore su $TargetInstance (compatibility level invariato)" {
        if ($dryRun) { Write-Log "WhatIf: RESTORE DATABASE [$TargetDatabase] WITH MOVE, CHECKSUM, RECOVERY (mai REPLACE)" "INFO"; return }
        $files = Invoke-SqlQuery -Instance $TargetInstance -Query "RESTORE FILELISTONLY FROM DISK = $(ConvertTo-SqlLiteral $bak)"
        $dataDir = if ($TargetDataDir) { $TargetDataDir } else { $tgt.DefaultDataPath }
        $logDir = if ($TargetDataDir) { $TargetDataDir } else { $tgt.DefaultLogPath }
        $safe = $TargetDatabase -replace '[^A-Za-z0-9_-]', '_'
        $moves = @(); $n = 0
        foreach ($f in $files) {
            $logical = $f[0]; $type = $f[2]   # LogicalName, PhysicalName, Type (D/L/F)
            $n++
            $ext = if ($type -eq "L") { "_log$n.ldf" } elseif ($n -eq 1) { ".mdf" } else { "_$n.ndf" }
            $dir = if ($type -eq "L") { $logDir } else { $dataDir }
            $phys = Join-Path $dir "$safe$ext"
            if (Test-Path $phys) { throw "File di destinazione già esistente: $phys" }
            $moves += "MOVE $(ConvertTo-SqlLiteral $logical) TO $(ConvertTo-SqlLiteral $phys)"
        }
        Invoke-SqlNonQuery -Instance $TargetInstance -Statement "RESTORE DATABASE $(ConvertTo-SqlName $TargetDatabase) FROM DISK = $(ConvertTo-SqlLiteral $bak) WITH $($moves -join ', '), CHECKSUM, RECOVERY, STATS = 10" | Out-Null
        $after = Get-SqlDatabaseInfo -Instance $TargetInstance -Database $TargetDatabase
        if ($after.CompatibilityLevel -ne $db.CompatibilityLevel) {
            Invoke-SqlNonQuery -Instance $TargetInstance -Statement "ALTER DATABASE $(ConvertTo-SqlName $TargetDatabase) SET COMPATIBILITY_LEVEL = $($db.CompatibilityLevel)" | Out-Null
        }
        if ($after.RecoveryModel -ne $db.RecoveryModel) {
            Invoke-SqlNonQuery -Instance $TargetInstance -Statement "ALTER DATABASE $(ConvertTo-SqlName $TargetDatabase) SET RECOVERY $($db.RecoveryModel)" | Out-Null
        }
        $after = Get-SqlDatabaseInfo -Instance $TargetInstance -Database $TargetDatabase
        $report.target_db = $after
        Write-Log "Restore OK: compat $($after.CompatibilityLevel), recovery $($after.RecoveryModel)." "SUCCESS"
    }

    # ── 4. Login e utenti orfani ────────────────────────────────────────────
    Step "Login e utenti orfani" {
        if ($dryRun) { Write-Log "WhatIf: CREATE LOGIN FROM WINDOWS per: $(@($Logins) -join ', ') e rimappatura orfani" "INFO"; return }
        foreach ($login in $Logins) {
            $lit = ConvertTo-SqlLiteral $login
            Invoke-SqlNonQuery -Instance $TargetInstance -Statement "IF SUSER_ID($lit) IS NULL CREATE LOGIN $(ConvertTo-SqlName $login) FROM WINDOWS" | Out-Null
            Write-Log "Login presente: $login" "INFO"
        }
        # utenti Windows senza login: il login Windows ha lo stesso SID → crearlo li riaggancia
        $orphans = Invoke-SqlQuery -Instance $TargetInstance -Database $TargetDatabase -Query @"
SELECT dp.name, dp.type FROM sys.database_principals dp
LEFT JOIN sys.server_principals sp ON sp.sid = dp.sid
WHERE dp.type IN ('U','G','S') AND dp.sid IS NOT NULL AND sp.sid IS NULL
  AND dp.name NOT IN ('guest','INFORMATION_SCHEMA','sys','dbo') AND dp.authentication_type <> 0
"@
        foreach ($o in $orphans) {
            $name = $o[0]; $type = $o[1]
            try {
                if ($type -in @("U", "G")) {
                    Invoke-SqlNonQuery -Instance $TargetInstance -Statement "IF SUSER_ID($(ConvertTo-SqlLiteral $name)) IS NULL CREATE LOGIN $(ConvertTo-SqlName $name) FROM WINDOWS" | Out-Null
                } else {
                    Invoke-SqlNonQuery -Instance $TargetInstance -Database $TargetDatabase -Statement "ALTER USER $(ConvertTo-SqlName $name) WITH LOGIN = $(ConvertTo-SqlName $name)" | Out-Null
                }
                Write-Log "Utente riagganciato: $name" "INFO"
            } catch {
                Warn "Utente orfano non risolto: $name ($type) — $($_.Exception.Message)"
                $report.orphans += $name
            }
        }
        # owner come in origine, se il login esiste
        if ($db.Owner) {
            try {
                Invoke-SqlNonQuery -Instance $TargetInstance -Statement "IF SUSER_ID($(ConvertTo-SqlLiteral $db.Owner)) IS NOT NULL ALTER AUTHORIZATION ON DATABASE::$(ConvertTo-SqlName $TargetDatabase) TO $(ConvertTo-SqlName $db.Owner)" | Out-Null
            } catch { Warn "Owner del DB non impostato a $($db.Owner): $($_.Exception.Message)" }
        }
    }

    # ── 5. Integrità ────────────────────────────────────────────────────────
    if (-not $SkipCheckDb) {
        Step "DBCC CHECKDB" {
            if ($dryRun) { Write-Log "WhatIf: DBCC CHECKDB WITH NO_INFOMSGS" "INFO"; return }
            Invoke-SqlNonQuery -Instance $TargetInstance -Statement "DBCC CHECKDB ($(ConvertTo-SqlName $TargetDatabase)) WITH NO_INFOMSGS, ALL_ERRORMSGS" | Out-Null
            Write-Log "CHECKDB senza errori." "SUCCESS"
        }
    }

    # ── 6. .env dell'ambiente ───────────────────────────────────────────────
    if ($UpdateEnv) {
        Step "Aggiornamento DB_HOST nel .env persistente" {
            $envFile = Join-Path $paths.Config ".env"
            if (-not (Test-Path $envFile)) { throw ".env persistente non trovato: $envFile" }
            if ($PSCmdlet.ShouldProcess($envFile, "DB_HOST=$NewDbHost (copia di sicurezza .env.bak-$stamp)")) {
                $backupEnv = "$envFile.bak-$stamp"
                Copy-Item -LiteralPath $envFile -Destination $backupEnv
                $lines = [IO.File]::ReadAllLines($envFile)
                $found = $false
                for ($i = 0; $i -lt $lines.Count; $i++) {
                    if ($lines[$i] -match '^\s*DB_HOST\s*=') { $lines[$i] = "DB_HOST=$NewDbHost"; $found = $true }
                }
                if (-not $found) { $lines += "DB_HOST=$NewDbHost" }
                if ($TargetDatabase -ne $Database) {
                    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^\s*DB_NAME\s*=') { $lines[$i] = "DB_NAME=$TargetDatabase" } }
                }
                [IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding $false))
                $report.env_backup = $backupEnv
                Write-Log "DB_HOST aggiornato; copia del precedente: $backupEnv. Il deploy successivo deve usare -AllowEnvDrift se l'attivo diverge." "SUCCESS"
                $active = Join-Path $paths.DjangoApp ".env"
                if (Test-Path $active) {
                    Copy-Item -LiteralPath $envFile -Destination $active -Force
                    Write-Log "Copiato anche nel .env attivo della release corrente." "INFO"
                }
            }
        }
    }

    # ── 7. Riavvio e verifica ───────────────────────────────────────────────
    if ($Environment -and $maintenanceStarted) {
        Step "Riavvio portale e smoke test" {
            Start-IISAppPool -AppPoolName $appPool
            if ($qclusterTask) { Start-ScheduledTask -InputObject $qclusterTask }
            if ($watchdogTask -and $watchdogWasEnabled) { Enable-ScheduledTask -InputObject $watchdogTask | Out-Null }
            $script:maintenanceStarted = $false
            & "$PSScriptRoot\smoke-test.ps1" -Environment $Environment -WaitSeconds 10
            if ($LASTEXITCODE -ne 0) { throw "smoke-test fallito (exit $LASTEXITCODE): valutare il rollback (vedi intestazione dello script)." }
        }
    }

    # ── 8. Origine OFFLINE (mai cancellata) ─────────────────────────────────
    if ($SetSourceOffline) {
        Step "DB di origine OFFLINE (conservato 30 giorni per rollback)" {
            if ($PSCmdlet.ShouldProcess("$SourceInstance [$Database]", "ALTER DATABASE SET OFFLINE")) {
                Invoke-SqlNonQuery -Instance $SourceInstance -Statement "ALTER DATABASE $(ConvertTo-SqlName $Database) SET OFFLINE WITH ROLLBACK IMMEDIATE" | Out-Null
                Write-Log "[$Database] OFFLINE su $SourceInstance. Rollback: ALTER DATABASE [$Database] SET ONLINE$(if ($report.Contains('env_backup')) { " + ripristino di $($report.env_backup)" })." "SUCCESS"
            }
        }
    }

    $report.result = if ($dryRun) { "dry_run" } else { "ok" }
    Write-Log "Completato in $([math]::Round($clock.Elapsed.TotalMinutes, 1)) minuti." "SUCCESS"
} catch {
    $report.result = "failed"
    $report.error = "$_"
    Write-Log "$_" "ERROR"
    if ($maintenanceStarted) {
        Write-Log "Errore durante la manutenzione: riavvio del portale sulla configurazione PRECEDENTE (origine ancora ONLINE)." "WARN"
        try {
            if ($report.Contains("env_backup")) { Copy-Item -LiteralPath $report.env_backup -Destination (Join-Path $paths.Config ".env") -Force }
            Start-IISAppPool -AppPoolName $appPool
            if ($qclusterTask) { Start-ScheduledTask -InputObject $qclusterTask }
            if ($watchdogTask -and $watchdogWasEnabled) { Enable-ScheduledTask -InputObject $watchdogTask | Out-Null }
        } catch { Write-Log "Ripristino automatico non riuscito: $_ — intervenire a mano." "ERROR" }
    }
} finally {
    $report.finished_at = (Get-Date).ToString("o")
    $report.total_seconds = [math]::Round($clock.Elapsed.TotalSeconds, 1)
    $reportPath = Join-Path $workDir "move-$Database-$stamp.json"
    $report | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding UTF8 -WhatIf:$false
    Write-Log "Report: $reportPath · Log: $transcript" "INFO"
    $WhatIfPreference = $false; Stop-Transcript | Out-Null
}
if ($report.result -eq "failed") { exit 1 }
exit 0
