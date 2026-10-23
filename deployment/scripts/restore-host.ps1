# restore-host.ps1
# Reinstallazione di NOVICROM HUB su una macchina nuova dai backup verificati (BUILD_SPEC R3 §5.3).
# Headless, riprendibile (-Resume), ogni fase idempotente e cronometrata; report finale con RTO.
#
#   .\restore-host.ps1 -BackupTarget \\nas\hub-backup -RecoveryKit D:\kit\prod.hubkit `
#       -PublicHostname hub.costruzioninovicrom.it -AltHostnames hub.cnovicrom.local -WhatIf
#   .\restore-host.ps1 -BackupTarget \\nas\hub-backup -RecoveryKit D:\kit\prod.hubkit `
#       -PublicHostname hub.costruzioninovicrom.it -AppPoolIdentity 'CNOVICROM\gmsa-hub$' -TaskGmsa 'CNOVICROM\gmsa-hub$'
#   .\restore-host.ps1 ... -Resume                    # riprende dalla prima fase non completata
#   .\restore-host.ps1 -BackupTarget \\nas\hub-backup -CachePrereqsOnly   # prepara la cache degli installer sul NAS
#
# Fasi: 0 preflight · 1 prerequisiti · 2 SQL · 3 segreti · 4 file · 5 release · 6 IIS · 7 task ·
#       8 connector Entra · 9 identità e rete · 10 verifica · 11 report.
# Stato: C:\PortaleNovicrom\shared\recovery\state.json. Il DNS non viene mai modificato; gli SPN solo con -ApplySpn.
# Le password (passphrase del kit, account) si chiedono in modo interattivo e non finiscono nel transcript.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("test", "prod")][string]$Environment = "prod",
    [Parameter(Mandatory)][string]$BackupTarget,
    [string]$PlanFile = "",
    [string]$TargetTime = "",
    [string]$RecoveryKit = "",
    [string]$PublicHostname = "",
    [string[]]$AltHostnames = @(),
    [string]$AppPoolIdentity = "ApplicationPoolIdentity",
    [PSCredential]$AppPoolCredential,
    [PSCredential]$TaskCredential,
    [string]$TaskGmsa = "",
    [string]$SqlInstance = ".\SQLEXPRESS",
    [ValidateSet(2022, 2025)][int]$SqlMajorVersion = 2025,
    [int]$SqlTcpPort = 14330,
    [string]$EntraTenantId = "",
    [string]$EntraConnectorClientId = "",
    [switch]$SkipEntra,
    [switch]$ApplySpn,
    [string[]]$SkipPhase = @(),
    [switch]$Resume,
    [switch]$CachePrereqsOnly,
    [string]$BootstrapPython = "",       # python già presente da usare per piano/kit/file (default: quello installato dai prerequisiti)
    [string]$EngineDir = "",             # cartella con restore_plan.py/recovery_kit.py/restore_files.py (default: repo)
    [string]$LockPath = "",              # prereqs.lock.json (default: repo, poi <BackupTarget>\_prereqs)
    # Uso dal SetupWizard: una riga JSON su stdin con kit_passphrase, task_user, task_password,
    # pool_password. I segreti non passano mai sulla riga di comando né finiscono nel transcript.
    [switch]$SecretsFromStdin,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# output in UTF-8: il SetupWizard lo legge per la barra di avanzamento
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
. "$PSScriptRoot\_lib.ps1"
. "$PSScriptRoot\_sqllib.ps1"
. "$PSScriptRoot\_restorelib.ps1"

$dryRun = [bool]$WhatIfPreference
# con -File (SetupWizard) la lista arriva come stringa unica "a,b"
$AltHostnames = @($AltHostnames | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$repoRoot =Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$engineDir = if ($EngineDir) { $EngineDir } else { Join-Path $repoRoot "django_app\core\backup_engine" }
$envRoot = Join-Path $BackupTarget $Environment
$cacheDir = Join-Path $BackupTarget "_prereqs"
$lockPath = $LockPath
if (-not $lockPath) {
    $lockPath = Join-Path $repoRoot "deployment\recovery\prereqs.lock.json"
    if (-not (Test-Path $lockPath)) { $lockPath = Join-Path $cacheDir "prereqs.lock.json" }   # copia lasciata da -CachePrereqsOnly
}

# Segreti dal SetupWizard (stdin): diventano SecureString/PSCredential e non vengono mai scritti.
$script:stdinSecrets = $null
if ($SecretsFromStdin) {
    $line = [Console]::In.ReadLine()
    if ($line) {
        $obj = $line | ConvertFrom-Json
        $line = $null
        $toSecure = { param($v) if ($v) { ConvertTo-SecureString -String ([string]$v) -AsPlainText -Force } else { $null } }
        $script:stdinSecrets = @{ kit = (& $toSecure $obj.kit_passphrase) }
        if ($obj.PSObject.Properties["task_user"] -and $obj.task_user -and $obj.task_password) {
            $TaskCredential = New-Object PSCredential ([string]$obj.task_user), (& $toSecure $obj.task_password)
        }
        if ($obj.PSObject.Properties["pool_password"] -and $obj.pool_password -and $AppPoolIdentity -notin @("ApplicationPoolIdentity") -and -not $AppPoolIdentity.EndsWith('$')) {
            $AppPoolCredential = New-Object PSCredential $AppPoolIdentity, (& $toSecure $obj.pool_password)
        }
        $obj = $null
    }
}
$paths = Get-EnvPaths -Env $Environment
$stateDir = Join-Path $DEPLOY_BASE "shared\recovery"
$statePath = Join-Path $stateDir "state.json"
$planPath = Join-Path $stateDir "restore-plan.json"
$appPool = "PortaleNovicrom-$($Environment.ToUpper())"
$poolLogin = if ($AppPoolIdentity -eq "ApplicationPoolIdentity") { "IIS APPPOOL\$appPool" } else { $AppPoolIdentity }

if (-not $dryRun) { Assert-Admin }
New-Item -ItemType Directory -Force -Path $stateDir -WhatIf:$false | Out-Null
$transcript = Join-Path $stateDir ("restore-" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
$wi = $WhatIfPreference; $WhatIfPreference = $false
Start-Transcript -Path $transcript -Append | Out-Null
# moduli caricati prima del WhatIf: altrimenti l'autocaricamento stampa «Imposta alias» a decine
foreach ($m in "CimCmdlets", "NetTCPIP", "ScheduledTasks") { Import-Module $m -ErrorAction SilentlyContinue }
$WhatIfPreference = $wi

$state = if ($Resume) { Read-RestoreState $statePath } else { $null }
if (-not $state) {
    $state = New-RestoreState @{ Environment = $Environment; BackupTarget = $BackupTarget; PublicHostname = $PublicHostname
                                 AppPoolIdentity = $AppPoolIdentity; SqlInstance = $SqlInstance; SqlMajorVersion = $SqlMajorVersion
                                 TargetTime = $TargetTime }
}
$plan = $null
$hostManifest = $null
$facts = @{}

function Add-Manual([string]$Text) { if ($state.manual_actions -notcontains $Text) { $state.manual_actions += $Text } }
function Add-Diff([string]$Text) { if ($state.diffs -notcontains $Text) { $state.diffs += $Text } }

function Get-Python {
    if ($BootstrapPython) { return $BootstrapPython }
    $minor = $facts.python_minor
    # prima il venv dell'ambiente (ha cryptography dai requirements), poi il Python di sistema
    foreach ($c in @((Join-Path $paths.Venv "Scripts\python.exe"), "C:\Python$($minor -replace '\.', '')\python.exe")) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return "py -$minor" }
    throw "Python $minor non trovato: completare la fase prerequisiti."
}

function Invoke-PyScript([string]$Script, [string[]]$PyArgs, [string]$StdIn = $null) {
    $python = Get-Python
    $exe, $pre = if ($python -like "py *") { "py", @($python.Split(" ")[1]) } else { $python, @() }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = (@($pre) + @("-I", "`"$Script`"") + ($PyArgs | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } })) -join " "
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.RedirectStandardInput = $true
    $psi.UseShellExecute = $false
    $p = [System.Diagnostics.Process]::Start($psi)
    if ($null -ne $StdIn) { $p.StandardInput.WriteLine($StdIn) }
    $p.StandardInput.Close()
    $out = $p.StandardOutput.ReadToEnd(); $err = $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    return @{ ExitCode = $p.ExitCode; Out = $out; Err = $err }
}

function Load-HostFacts {
    $hostSet = Get-LatestSetDir $envRoot "host"
    if ($hostSet) {
        $hm = Join-Path $hostSet.FullName "host\host-manifest.json"
        if (Test-Path $hm) { $script:hostManifest = Get-Content $hm -Raw -Encoding UTF8 | ConvertFrom-Json }
    }
    $pyVersion = if ($hostManifest -and $hostManifest.python) { [string]$hostManifest.python.version } else { "3.13.0" }
    $facts.python_minor = ($pyVersion.Split(".")[0..1] -join ".")
    $facts.host_extensions = if ($hostManifest -and $hostManifest.PSObject.Properties["iis_extensions"]) { ($hostManifest.iis_extensions | ConvertTo-Json -Compress) } else { "" }
    $facts.sql_missing = -not (Get-Service -Name ("MSSQL`$" + ($SqlInstance -split "\\")[-1]) -ErrorAction SilentlyContinue)
    $facts.entra_connector = -not $SkipEntra
}

function Load-Plan {
    if ($PlanFile) { Copy-Item $PlanFile $planPath -Force -WhatIf:$false }
    if (Test-Path $planPath) { $script:plan = Get-Content $planPath -Raw -Encoding UTF8 | ConvertFrom-Json; return }
    $planArgs = @($envRoot, "--out", $planPath)
    if ($TargetTime) { $planArgs += @("--target-time", $TargetTime) }
    $r = Invoke-PyScript (Join-Path $engineDir "restore_plan.py") $planArgs
    if ($r.ExitCode -ne 0) { throw "Piano di ripristino non costruibile: $($r.Err.Trim())" }
    if ($r.Err) { $r.Err.Trim().Split("`n") | ForEach-Object { Write-Log $_ "WARN" } }
    $script:plan = Get-Content $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Invoke-Phase($Phase, [scriptblock]$Body) {
    $key = $Phase.Key
    Write-LogSeparator
    Write-Log "Fase $($Phase.Id) · $($Phase.Title)$(if ($dryRun) { ' [WhatIf]' })" "STEP"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $entry = [ordered]@{ status = "running"; started_at = (Get-Date).ToString("o"); finished_at = $null; seconds = 0; notes = @() }
    $state.phases[$key] = $entry
    try {
        $notes = & $Body
        $entry.notes = @($notes | Where-Object { $_ })
        foreach ($n in $entry.notes) { Write-Log "  $n" "INFO" }
        $entry.status = if ($dryRun) { "whatif" } else { "ok" }
    } catch {
        $entry.status = "failed"
        $entry.notes = @($entry.notes) + @("$_")
        throw
    } finally {
        $entry.seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        $entry.finished_at = (Get-Date).ToString("o")
        if (-not $dryRun) { Save-RestoreState $state $statePath }
    }
    Write-Log "Fase $($Phase.Id) completata in $($entry.seconds) s." "SUCCESS"
}

# ═════════════════════════════════════════════════════════════════════════════
$phaseBodies = @{}

$phaseBodies["preflight"] = {
    $notes = @()
    $os = Get-CimInstance Win32_OperatingSystem
    $isServer = $os.ProductType -ne 1
    $notes += "$($os.Caption) build $($os.BuildNumber) ($(if ($isServer) { 'server' } else { 'client' }))"
    $notes += "Dominio: $env:USERDNSDOMAIN"
    if (-not (Test-Path $envRoot)) { throw "Target dei backup non raggiungibile: $envRoot" }
    Load-HostFacts
    if (-not $hostManifest) { Add-Manual "Nessuna fotografia della macchina (set HOST) nel target: verificare a mano IIS e task." }
    $full = Get-LatestSetDir $envRoot "full"
    if (-not $full) { throw "Nessun backup FULL in $envRoot." }
    $fm = Get-Content (Join-Path $full.FullName "manifest.json") -Raw | ConvertFrom-Json
    $dbMB = if ($fm.PSObject.Properties["databases"] -and $fm.databases) { [int](($fm.databases | Measure-Object -Property allocated_mb -Sum).Sum) } else { 0 }
    $filesSet = Get-LatestSetDir $envRoot "files"
    $filesMB = 0
    if ($filesSet) { $filesMB = [int](((Get-Content (Join-Path $filesSet.FullName "manifest.json") -Raw | ConvertFrom-Json).files.total_bytes) / 1MB) }
    $needMB = [int](3 * ($dbMB + $filesMB))
    $freeMB = Get-FreeSpaceMB $env:SystemDrive
    $notes += "Spazio: servono ~$needMB MB (3 × DB $dbMB MB + file $filesMB MB), liberi $freeMB MB"
    if ($freeMB -ne $null -and $freeMB -lt $needMB) { throw "Spazio su disco insufficiente: liberi $freeMB MB, servono ~$needMB MB." }
    $internet = Test-NetConnection -ComputerName "www.python.org" -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue
    $notes += "Internet: $(if ($internet) { 'sì' } else { 'no (si useranno solo gli installer in cache)' })"
    $facts.internet = $internet
    foreach ($port in 80, 443) {
        $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($busy) { $notes += "Porta $port già in ascolto (PID $(($busy | Select-Object -First 1).OwningProcess))" }
    }
    $notes += "Python del backup: $($facts.python_minor) · SQL di destinazione: $SqlMajorVersion · identità del pool: $AppPoolIdentity"
    if (-not $dryRun -and -not $Force -and -not $Resume) {
        $notes | ForEach-Object { Write-Log $_ "INFO" }
        if (-not $PSCmdlet.ShouldContinue("Ricostruire NOVICROM HUB ($Environment) su $env:COMPUTERNAME dai backup in ${envRoot}?", "Conferma")) {
            throw "Annullato dall'operatore."
        }
    }
    $notes
}

$phaseBodies["prereqs"] = {
    $notes = @()
    if (-not $hostManifest) { Load-HostFacts }
    $os = Get-CimInstance Win32_OperatingSystem
    $features = @("Web-Server", "Web-Static-Content", "Web-Default-Doc", "Web-Http-Errors", "Web-Http-Logging",
                  "Web-Filtering", "Web-Mgmt-Console", "Web-Mgmt-Tools")
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($dryRun -and -not $isAdmin) {
        $notes += "WhatIf senza privilegi: verifica delle funzionalità IIS saltata"
    } elseif ($os.ProductType -ne 1) {
        $missing = @(Get-WindowsFeature -Name $features | Where-Object { -not $_.Installed } | ForEach-Object Name)
        if ($missing -and $PSCmdlet.ShouldProcess(($missing -join ", "), "Install-WindowsFeature")) { Install-WindowsFeature -Name $missing | Out-Null }
        $notes += "IIS (Windows Server): " + $(if ($missing) { "installate $($missing -join ', ')" } else { "già presente" })
    } else {
        $clientFeatures = @("IIS-WebServerRole", "IIS-WebServer", "IIS-StaticContent", "IIS-DefaultDocument", "IIS-HttpErrors",
                            "IIS-HttpLogging", "IIS-RequestFiltering", "IIS-ManagementConsole")
        $missing = @($clientFeatures | Where-Object { (Get-WindowsOptionalFeature -Online -FeatureName $_).State -ne "Enabled" })
        if ($missing -and $PSCmdlet.ShouldProcess(($missing -join ", "), "Enable-WindowsOptionalFeature")) {
            Enable-WindowsOptionalFeature -Online -FeatureName $missing -All -NoRestart | Out-Null
        }
        $notes += "IIS (Windows client): " + $(if ($missing) { "abilitate $($missing -join ', ')" } else { "già presente" })
    }
    $lock = Get-Content $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($item in $lock.items) {
        if (-not (Test-PrereqWanted $item $facts)) { continue }
        $present = $false
        try { $present = [bool](Invoke-Expression ([string]$item.check)) } catch { }
        if ($present) { $notes += "$($item.name): già presente"; continue }
        if ($item.name -like "sql-server-*") { $notes += "$($item.name): gestito nella fase SQL"; continue }
        if ($item.name -like "entra-*") { $notes += "$($item.name): gestito nella fase Entra"; continue }
        if (-not $PSCmdlet.ShouldProcess($item.name, "Installazione silent (hash verificato dal lock)")) { $notes += "$($item.name): da installare"; continue }
        $inst = Get-VerifiedInstaller $item $cacheDir -NoDownload:(-not $facts.internet)
        $code = Invoke-SilentInstall $item $inst $cacheDir
        $notes += "$($item.name) $($item.version): installato (exit $code)"
        if ($code -in 3010, 1641) { Add-Manual "Riavvio richiesto dopo $($item.name): riavviare e rilanciare con -Resume." }
    }
    foreach ($m in $lock.manual) {
        if ($m.name -eq "tesseract-ocr" -and $hostManifest -and $hostManifest.PSObject.Properties["tesseract"]) {
            Add-Manual "Installare Tesseract $($hostManifest.tesseract.version) in $($hostManifest.tesseract.cmd)."
        }
    }
    # venv dell'ambiente con i requirements (serve cryptography per kit e file, prima della release)
    if (-not (Test-Path (Join-Path $paths.Venv "Scripts\python.exe"))) {
        if ($PSCmdlet.ShouldProcess($paths.Venv, "setup-environment.ps1 (venv + requirements)")) {
            & "$PSScriptRoot\setup-environment.ps1" -Environment $Environment -PythonPath (Get-Python) `
                -RequirementsPath (Join-Path $repoRoot "django_app\requirements.txt")
            $notes += "ambiente $Environment preparato (venv + requirements)"
        }
    }
    if (-not $dryRun) { Load-Plan; $notes += "Piano di ripristino: FULL $($plan.full_set_id), ultimo log $($plan.last_log_set_id), punto $($plan.restore_point)" }
    $notes
}

$phaseBodies["sql"] = {
    $notes = @()
    if (-not $plan) { if ($dryRun -and -not (Test-Path $planPath)) { return @("WhatIf: il piano si calcola dopo i prerequisiti") }; Load-Plan }
    $targetMajor = ConvertTo-SqlMajor $SqlMajorVersion
    Assert-SqlVersionCompatible ([string]$plan.sql.product_version) $targetMajor
    $instName = ($SqlInstance -split "\\")[-1]
    if (-not (Get-Service -Name "MSSQL`$$instName" -ErrorAction SilentlyContinue)) {
        $lock = Get-Content $lockPath -Raw | ConvertFrom-Json
        $boot = $lock.items | Where-Object name -like "sql-server-$SqlMajorVersion-*" | Select-Object -First 1
        if (-not $boot) { throw "Nessun installer SQL $SqlMajorVersion nel lock." }
        if ($PSCmdlet.ShouldProcess("SQL Server $SqlMajorVersion Express ($instName)", "Download supporti + installazione silent")) {
            $bootExe = Get-VerifiedInstaller $boot $cacheDir -NoDownload:(-not $facts.internet)
            $media = Join-Path $cacheDir "sql$SqlMajorVersion-media"
            if (-not (Get-ChildItem $media -Filter "SQLEXPR*.exe" -ErrorAction SilentlyContinue)) { Invoke-SilentInstall $boot $bootExe $cacheDir | Out-Null }
            $pkg = Get-ChildItem $media -Filter "SQLEXPR*.exe" | Select-Object -First 1
            $auth = if ($plan.sql -and $hostManifest) { "windows" } else { "windows" }
            & "$PSScriptRoot\install-sql2025-instance.ps1" -InstanceName $instName -InstallerPath $pkg.FullName `
                -Collation ([string]$plan.sql.collation) -AuthMode $auth -TcpPort $SqlTcpPort
            if ($LASTEXITCODE -notin 0, 3010) { throw "Installazione SQL fallita (exit $LASTEXITCODE)." }
        }
        $notes += "Istanza $SqlInstance installata (collation $($plan.sql.collation))"
    } else {
        $info = Get-SqlInstanceInfo -Instance $SqlInstance
        if ($info.Major -lt (Get-SqlMajorFromVersion ([string]$plan.sql.product_version))) {
            throw "L'istanza $SqlInstance è $($info.ProductVersion): più vecchia del backup ($($plan.sql.product_version))."
        }
        if ($info.Collation -ne $plan.sql.collation) { Add-Diff "Collation dell'istanza $($info.Collation) diversa dal backup ($($plan.sql.collation))." }
        $notes += "Istanza esistente $SqlInstance ($($info.ProductVersion))"
    }
    if ($dryRun) {
        foreach ($db in (Get-PlanDatabaseNames $plan)) { $notes += "WhatIf: RESTORE $db (FULL + $(@($plan.databases.$db.logs).Count) log$(if ($plan.stopat) { ", STOPAT $($plan.stopat)" }))" }
        return $notes
    }
    $tgt = Get-SqlInstanceInfo -Instance $SqlInstance
    $staging = Join-Path $DEPLOY_BASE "shared\backup-staging\restore"
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    & icacls.exe $staging /grant "NT Service\MSSQL`$$($instName):(OI)(CI)M" /Q | Out-Null
    foreach ($db in (Get-PlanDatabaseNames $plan)) {
        Assert-DatabaseInPlan $plan $db
        Assert-HubDatabaseName -Database $db -AllowExternal   # DLM/CNGAUGE ammessi solo perché sono nel piano
        $entry = $plan.databases.$db
        $existing = Get-SqlDatabaseInfo -Instance $SqlInstance -Database $db
        if (-not $state.Contains("restored_dbs")) { $state["restored_dbs"] = @() }
        if ($existing) {
            if (@($state["restored_dbs"]) -contains $db) { $notes += "$db già ripristinato in un passaggio precedente"; continue }
            throw "Il database [$db] esiste già su ${SqlInstance}: rifiuto di sovrascriverlo (eliminarlo a mano se è un tentativo precedente)."
        }
        $copy = { param($rel, $sha) $src = Join-Path $envRoot $rel; $dst = Join-Path $staging (Split-Path $rel -Leaf)
                  Copy-Item -LiteralPath $src -Destination $dst -Force
                  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $dst).Hash.ToLowerInvariant() -ne $sha) { throw "Hash diverso per $rel" }
                  $dst }
        $bak = & $copy $entry.full.path $entry.full.sha256
        $files = Invoke-SqlQuery -Instance $SqlInstance -Query "RESTORE FILELISTONLY FROM DISK = $(ConvertTo-SqlLiteral $bak)"
        $safe = $db -replace '[^A-Za-z0-9_-]', '_'
        $moves = @(); $i = 0
        foreach ($f in $files) {
            $i++
            $ext = if ($f[2] -eq "L") { "_log.ldf" } elseif ($i -eq 1) { ".mdf" } else { "_$i.ndf" }
            $dir = if ($f[2] -eq "L") { $tgt.DefaultLogPath } else { $tgt.DefaultDataPath }
            $moves += "MOVE $(ConvertTo-SqlLiteral $f[0]) TO $(ConvertTo-SqlLiteral (Join-Path $dir "$safe$ext"))"
        }
        Invoke-SqlNonQuery -Instance $SqlInstance -Statement "RESTORE DATABASE $(ConvertTo-SqlName $db) FROM DISK = $(ConvertTo-SqlLiteral $bak) WITH $($moves -join ', '), NORECOVERY, CHECKSUM, STATS = 10" | Out-Null
        Remove-Item -LiteralPath $bak -Force
        $logs = @($entry.logs)
        for ($k = 0; $k -lt $logs.Count; $k++) {
            $trn = & $copy $logs[$k].path $logs[$k].sha256
            $stop = if ($k -eq $logs.Count - 1 -and $plan.stopat) { ", STOPAT = $(ConvertTo-SqlLiteral $plan.stopat)" } else { "" }
            Invoke-SqlNonQuery -Instance $SqlInstance -Statement "RESTORE LOG $(ConvertTo-SqlName $db) FROM DISK = $(ConvertTo-SqlLiteral $trn) WITH NORECOVERY, CHECKSUM$stop" | Out-Null
            Remove-Item -LiteralPath $trn -Force
        }
        Invoke-SqlNonQuery -Instance $SqlInstance -Statement "RESTORE DATABASE $(ConvertTo-SqlName $db) WITH RECOVERY" | Out-Null
        $notes += "ripristinato $db (FULL $($entry.full.path.Split('/')[0]) + $($logs.Count) log)"
        $state["restored_dbs"] = @($state["restored_dbs"]) + $db
        Save-RestoreState $state $statePath
    }
    # login dell'identità del pool e utenti orfani (i login Windows con lo stesso SID si riagganciano da soli)
    Invoke-SqlNonQuery -Instance $SqlInstance -Statement "IF SUSER_ID($(ConvertTo-SqlLiteral $poolLogin)) IS NULL CREATE LOGIN $(ConvertTo-SqlName $poolLogin) FROM WINDOWS" | Out-Null
    foreach ($db in (Get-PlanDatabaseNames $plan)) {
        $orph = Invoke-SqlQuery -Instance $SqlInstance -Database $db -Query @"
SELECT dp.name, dp.type FROM sys.database_principals dp LEFT JOIN sys.server_principals sp ON sp.sid = dp.sid
WHERE dp.type IN ('U','G','S') AND dp.sid IS NOT NULL AND sp.sid IS NULL AND dp.name NOT IN ('guest','INFORMATION_SCHEMA','sys','dbo') AND dp.authentication_type <> 0
"@
        foreach ($o in $orph) {
            try {
                if ($o[1] -in "U", "G") { Invoke-SqlNonQuery -Instance $SqlInstance -Statement "IF SUSER_ID($(ConvertTo-SqlLiteral $o[0])) IS NULL CREATE LOGIN $(ConvertTo-SqlName $o[0]) FROM WINDOWS" | Out-Null }
                else { Invoke-SqlNonQuery -Instance $SqlInstance -Database $db -Statement "ALTER USER $(ConvertTo-SqlName $o[0]) WITH LOGIN = $(ConvertTo-SqlName $o[0])" | Out-Null }
            } catch { Add-Manual "Utente orfano in [$db]: $($o[0]) ($($o[1])) — creare il login o rimapparlo." }
        }
        # l'identità del pool deve poter usare il DB dell'HUB
        if ($db -eq ($plan.databases.PSObject.Properties | Select-Object -First 1).Name) {
            Invoke-SqlNonQuery -Instance $SqlInstance -Database $db -Statement @"
IF USER_ID($(ConvertTo-SqlLiteral $poolLogin)) IS NULL CREATE USER $(ConvertTo-SqlName $poolLogin) FOR LOGIN $(ConvertTo-SqlName $poolLogin);
ALTER ROLE db_owner ADD MEMBER $(ConvertTo-SqlName $poolLogin);
"@ | Out-Null
        }
    }
    $notes
}

$phaseBodies["secrets"] = {
    if (-not $RecoveryKit) {
        if ($dryRun) { return @("WhatIf: Recovery Kit non indicato: nel ripristino reale è obbligatorio") }
        throw "Indicare -RecoveryKit (file .hubkit)."
    }
    if (-not $plan) { Load-Plan }
    if ($dryRun) { return @("WhatIf: import del Recovery Kit in $($paths.Config)\.env con verifica delle impronte del piano") }
    $secure = if ($script:stdinSecrets -and $script:stdinSecrets.kit) { $script:stdinSecrets.kit } else { Read-Host -AsSecureString "Passphrase del Recovery Kit" }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    New-Item -ItemType Directory -Force -Path $paths.Config | Out-Null
    $pfx = Join-Path $stateDir "binding.pfx"
    $r = Invoke-PyScript (Join-Path $engineDir "recovery_kit.py") @("import", $RecoveryKit, "--env-dest", (Join-Path $paths.Config ".env"),
                                                                    "--pfx-dest", $pfx, "--plan", $planPath, "--force", "--passphrase-stdin") $plain
    $plain = $null
    $lines = $r.Out -split "`r?`n"
    foreach ($l in $lines) { if ($l -match '^PFX_PASSWORD=(.*)$') { $script:pfxPassword = $Matches[1] } elseif ($l -match '^PFX_THUMBPRINT=(.*)$') { $script:pfxThumb = $Matches[1] } }
    $visible = ($lines | Where-Object { $_ -and $_ -notmatch '^PFX_' }) -join " "
    if ($r.ExitCode -eq 3) { throw "Impronte delle chiavi diverse dal backup: $visible — questo kit non apre i documenti. Fermato." }
    if ($r.ExitCode -ne 0) { throw "Import del Recovery Kit fallito (exit $($r.ExitCode)): $visible $($r.Err.Trim())" }
    @($visible, $(if (Test-Path $pfx) { "certificato HTTPS estratto (thumbprint $script:pfxThumb)" } else { "nessun certificato nel kit" }))
}

$phaseBodies["files"] = {
    if (-not $plan) { Load-Plan }
    if (-not $plan.files_index) { Add-Manual "Nessun backup dei file nel target."; return @("nessun backup dei file") }
    $pyArgs = @($envRoot, "--index", $plan.files_index)
    $envFile = Join-Path $paths.Config ".env"
    if (Test-Path $envFile) { $pyArgs += @("--env-file", $envFile) } else { Add-Manual "Campioni dei documenti cifrati non verificati: .env assente durante la fase file." }
    if ($dryRun) { $pyArgs += "--dry-run" }
    if (-not (Test-Path (Join-Path $envRoot $plan.files_index))) { throw "Indice dei file non trovato: $($plan.files_index)" }
    if ($dryRun) {
        try { $null = Get-Python } catch { return @("WhatIf: Python non ancora installato (lo installa la fase 1): verifica dei file rimandata") }
    }
    $r = Invoke-PyScript (Join-Path $engineDir "restore_files.py") $pyArgs
    $rep = $null
    try { $rep = $r.Out | ConvertFrom-Json } catch { }
    if (-not $rep) { throw "Ricostruzione dei file non riuscita: $($r.Err.Trim())" }
    if ($r.ExitCode -eq 2) { throw "Ricostruzione dei file con errori: $(@($rep.errors) | Select-Object -First 5)" }
    $notes = @("$($rep.files) file ripristinati e verificati ($([int]($rep.bytes / 1MB)) MB)")
    foreach ($p in $rep.decrypt.PSObject.Properties) { $notes += "$($p.Name): $($p.Value.decrypted)/$($p.Value.encrypted) campioni cifrati aperti" }
    if (-not $dryRun) {
        foreach ($root in $rep.roots.PSObject.Properties) {
            if (Test-Path $root.Value.path) { & icacls.exe $root.Value.path /grant "$($poolLogin):(OI)(CI)M" /Q | Out-Null }
        }
    }
    $notes
}

$phaseBodies["release"] = {
    if (-not $plan) { Load-Plan }
    $zipRel = [string]$plan.release.zip
    if (-not $zipRel) { throw "Il piano non indica lo zip della release (versione $($plan.release.version), commit $($plan.release.commit)): recuperarlo e usare deploy-release.ps1 a mano." }
    $zip = Join-Path $envRoot $zipRel
    if ($dryRun) { return @("WhatIf: setup-environment + deploy-release.ps1 -PackagePath $zip -AutoActivate") }
    $pkgDir = Join-Path $DEPLOY_BASE "shared\packages"
    New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null
    $local = Join-Path $pkgDir (Split-Path $zip -Leaf)
    Copy-Item $zip $local -Force
    # deploy-release.ps1 ricicla il pool IIS: su una macchina nuova deve già esistere (la fase IIS viene dopo)
    Import-Module WebAdministration
    if (-not (Test-Path "IIS:\AppPools\$appPool")) {
        & "$PSScriptRoot\configure-iis-site.ps1" -Environment $Environment -Hostname $PublicHostname
    }
    $out = & "$PSScriptRoot\deploy-release.ps1" -Environment $Environment -PackagePath $local -AutoActivate -AllowEnvDrift *>&1 | Out-String
    $out | Set-Content (Join-Path $stateDir "deploy-release.log") -Encoding UTF8
    $notes = @("release $($plan.release.version) ($($plan.release.commit)) attivata")
    if ($out -match "Applying ") { Add-Diff "Il deploy ha applicato migrazioni: DB e codice non erano allineati (vedi deploy-release.log)." }
    $notes
}

$phaseBodies["iis"] = {
    if ($dryRun) { return @("WhatIf: configure-iis-site.ps1 -Hostname $PublicHostname, identità $AppPoolIdentity, certificato e binding HTTPS") }
    & "$PSScriptRoot\configure-iis-site.ps1" -Environment $Environment -Hostname $PublicHostname
    Import-Module WebAdministration
    # il web.config del portale definisce <handlers>: su un IIS nuovo la sezione è bloccata (errore 500.19)
    & "$env:windir\system32\inetsrv\appcmd.exe" unlock config -section:system.webServer/handlers | Out-Null
    $poolPath = "IIS:\AppPools\$appPool"
    # il gruppo locale IIS_IUSRS è per macchina: l'identità di dominio del pool deve esserci, altrimenti Python non scrive in logs
    if ($AppPoolIdentity -notin @("ApplicationPoolIdentity") -and $AppPoolIdentity -match '\\') {
        if (-not (Get-LocalGroupMember -Group IIS_IUSRS -ErrorAction SilentlyContinue | Where-Object { $_.Name -ieq $AppPoolIdentity.TrimEnd('$') })) {
            Add-LocalGroupMember -Group IIS_IUSRS -Member $AppPoolIdentity.TrimEnd('$') -ErrorAction SilentlyContinue
        }
    }
    # il processo web resta acceso: senza questo IIS lo spegne dopo 20 minuti e il primo accesso è lento (10-15 s)
    Set-ItemProperty $poolPath -Name processModel.idleTimeout -Value ([TimeSpan]::Zero)
    if ($AppPoolIdentity -eq "ApplicationPoolIdentity") {
        Set-ItemProperty $poolPath -Name processModel.identityType -Value 4
    } elseif ($AppPoolIdentity.EndsWith('$')) {
        Set-ItemProperty $poolPath -Name processModel -Value @{ identityType = 3; userName = $AppPoolIdentity; password = "" }
    } else {
        if (-not $AppPoolCredential) { $AppPoolCredential = Get-Credential -UserName $AppPoolIdentity -Message "Password dell'identità del pool" }
        Set-ItemProperty $poolPath -Name processModel -Value @{ identityType = 3; userName = $AppPoolIdentity; password = $AppPoolCredential.GetNetworkCredential().Password }
    }
    $notes = @("pool $appPool con identità $AppPoolIdentity")
    $pfx = Join-Path $stateDir "binding.pfx"
    if ((Test-Path $pfx) -and $script:pfxPassword) {
        $pw = ConvertTo-SecureString -String $script:pfxPassword -AsPlainText -Force
        $cert = Import-PfxCertificate -FilePath $pfx -CertStoreLocation Cert:\LocalMachine\My -Password $pw -Exportable
        Remove-Item -LiteralPath $pfx -Force
        $site = "PortaleNovicrom-$($Environment.ToUpper())"
        foreach ($name in @($PublicHostname) + $AltHostnames | Where-Object { $_ }) {
            if (-not (Get-WebBinding -Name $site -Protocol https -HostHeader $name -ErrorAction SilentlyContinue)) {
                New-WebBinding -Name $site -Protocol https -Port 443 -HostHeader $name -SslFlags 1
            }
            (Get-WebBinding -Name $site -Protocol https -HostHeader $name).AddSslCertificate($cert.Thumbprint, "My")
            if ($cert.DnsNameList.Unicode -notcontains $name) { Add-Diff "Il certificato $($cert.Thumbprint) non copre $name." }
        }
        $notes += "certificato $($cert.Thumbprint) importato e associato a $(@($PublicHostname) + $AltHostnames -join ', ')"
    } else {
        Add-Manual "Nessun certificato HTTPS nel kit: importarlo e associarlo al sito per $PublicHostname."
    }
    if ($hostManifest -and $hostManifest.PSObject.Properties["iis_bindings"]) {
        $now = (& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list site "PortaleNovicrom-$($Environment.ToUpper())" /text:bindings)
        if ($now -ne $hostManifest.iis_bindings) { Add-Diff "Binding IIS: prima '$($hostManifest.iis_bindings)', ora '$now'." }
    }
    & "$PSScriptRoot\secure-env-acl.ps1" -Environment $Environment -Quiet
    $notes
}

$phaseBodies["tasks"] = {
    if ($dryRun) { return @("WhatIf: task backup (con DRILL), qcluster + watchdog, coda automazioni, helper IIS, polling mail") }
    if (-not $TaskCredential -and -not $TaskGmsa) { $TaskCredential = Get-Credential -Message "Account dei task pianificati (accesso di rete alla share dei backup)" }
    $taskArgs = if ($TaskGmsa) { @{ GmsaAccount = $TaskGmsa } } else { @{ Credential = $TaskCredential } }
    & "$PSScriptRoot\register-backup-tasks.ps1" -Environment $Environment -IncludeDrill @taskArgs
    # worker qcluster (stessa definizione del wizard, mai interattivo)
    $scriptPath = Join-Path $DEPLOY_BASE "shared\scripts\start_qcluster.ps1"
    New-Item -ItemType Directory -Force -Path (Split-Path $scriptPath) | Out-Null
    # gli script del qcluster vengono dalla release appena attivata (dal repo solo se assente)
    $qSrc = Join-Path $paths.Current "deployment"
    if (-not (Test-Path (Join-Path $qSrc "start_qcluster.ps1"))) { $qSrc = Join-Path $repoRoot "deployment" }
    Copy-Item (Join-Path $qSrc "start_qcluster.ps1") $scriptPath -Force
    Copy-Item (Join-Path $qSrc "watch_qcluster.ps1") (Join-Path (Split-Path $scriptPath) "watch_qcluster.ps1") -Force
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`" -Environment $Environment"
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $common = @{ TaskPath = "\PortaleNovicrom\"; TaskName = "QCluster_$($Environment.ToUpper())"; Action = $action
                 Trigger = (New-ScheduledTaskTrigger -AtStartup); Settings = $settings; Force = $true }
    if ($TaskGmsa) { Register-ScheduledTask @common -Principal (New-ScheduledTaskPrincipal -UserId $TaskGmsa -LogonType Password -RunLevel Highest) | Out-Null }
    else { Register-ScheduledTask @common -User $TaskCredential.UserName -Password $TaskCredential.GetNetworkCredential().Password -RunLevel Highest | Out-Null }
    if ($TaskCredential) { & "$PSScriptRoot\install-qcluster-watchdog.ps1" -Environment $Environment -Credential $TaskCredential }
    else { Add-Manual "Watchdog del qcluster: installarlo con install-qcluster-watchdog.ps1 (richiede un account con password)." }
    # collector CNC integrato: stesso account del qcluster (serve solo con la modalita' "Sul server del portale")
    $cncManual = "Collector CNC: Setup Wizard > Collector CNC > Installa task (o install-collector-cnc-task.ps1)."
    if ($TaskCredential) {
        try { & "$PSScriptRoot\install-collector-cnc-task.ps1" -Environment $Environment -PortaleRoot $DEPLOY_BASE -Credential $TaskCredential | Out-Null }
        catch { Add-Manual "$cncManual Non riuscito qui: $_" }
    } else { Add-Manual $cncManual }
    & "$PSScriptRoot\schedule-automation-queue.ps1" -Environment $Environment
    & "$PSScriptRoot\register-iis-restart-helper.ps1" -Environment $Environment
    $notes = @("task di backup, qcluster, coda automazioni e helper IIS registrati")
    if ($hostManifest -and $hostManifest.PSObject.Properties["scheduled_tasks"]) {
        $now = @(Get-ScheduledTask | ForEach-Object TaskName)
        foreach ($t in $hostManifest.scheduled_tasks) {
            if ($now -notcontains $t.TaskName) { Add-Diff "Task presente sulla macchina d'origine ma non qui: $($t.TaskName) (es. polling mail: register-local-polling-mail.ps1)." }
        }
    }
    $notes
}

$phaseBodies["entra"] = {
    if ($SkipEntra) { return @("saltata (-SkipEntra)") }
    if ($dryRun) { return @("WhatIf: installazione connector Entra (hash dal lock) e registrazione per Application Proxy") }
    $lock = Get-Content $lockPath -Raw | ConvertFrom-Json
    $item = $lock.items | Where-Object name -eq "entra-private-network-connector"
    $notes = @()
    if (-not (Get-Service -Name "WAPCsvc" -ErrorAction SilentlyContinue)) {
        try {
            $inst = Get-VerifiedInstaller $item $cacheDir -NoDownload:(-not $facts.internet)
            Invoke-SilentInstall $item $inst $cacheDir | Out-Null
            $notes += "connector installato"
        } catch {
            Add-Manual "Connector Entra: installazione automatica non riuscita ($_). Scaricarlo dall'interfaccia Entra (Global Secure Access → Connectors) e installarlo."
            return $notes + "installazione non riuscita"
        }
    }
    $module = "C:\Program Files\Microsoft Entra private network connector\Modules\"
    $msal = Get-Module -ListAvailable -Name MSAL.PS
    if ($EntraTenantId -and $EntraConnectorClientId -and $msal) {
        try {
            Import-Module MSAL.PS
            $tok = Get-MsalToken -ClientId $EntraConnectorClientId -TenantId $EntraTenantId -Interactive `
                -Scopes "https://proxy.cloudwebappproxy.net/registerapp/user_impersonation"
            $secure = ConvertTo-SecureString -String $tok.AccessToken -AsPlainText -Force
            $tok = $null
            & "C:\Program Files\Microsoft Entra private network connector\RegisterConnector.ps1" -modulePath $module `
                -moduleName "MicrosoftEntraPrivateNetworkConnectorPSModule" -Authenticationmode Token -Token $secure `
                -TenantId $EntraTenantId -Feature ApplicationProxy
            $notes += "connector registrato nel tenant"
        } catch {
            Add-Manual "Registrazione del connector non riuscita: completarla dall'installer interattivo."
        }
    } else {
        Add-Manual "Registrare il connector Entra: rilanciare l'installer senza REGISTERCONNECTOR=false (accesso interattivo con MFA), oppure passare -EntraTenantId e -EntraConnectorClientId con il modulo MSAL.PS installato."
    }
    Add-Manual "Entra: assegnare il connector al connector group dell'app pubblicata; l'URL interno dell'app deve essere https://$PublicHostname/ (solo /approval-actions/* è pubblicato)."
    $notes
}

$phaseBodies["network"] = {
    $notes = @()
    $names = @($PublicHostname) + $AltHostnames | Where-Object { $_ }
    $local = @((Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress)
    foreach ($n in $names) {
        $spn = & setspn.exe -Q "HTTP/$n" 2>&1 | Out-String
        $found = $spn -match "Existing SPN found|SPN esistente trovato"
        $account = if ($AppPoolIdentity -eq "ApplicationPoolIdentity") { $env:COMPUTERNAME + "$" } else { $AppPoolIdentity }
        if (-not $found) {
            $cmd = "setspn -S HTTP/$n $account"
            if ($ApplySpn -and $PSCmdlet.ShouldProcess("HTTP/$n", $cmd)) { & setspn.exe -S "HTTP/$n" $account | Out-Null; $notes += "SPN HTTP/$n creato su $account" }
            else { Add-Manual "Windows SSO: creare l'SPN con: $cmd" }
        } else { $notes += "SPN HTTP/$n presente" }
        try {
            $ips = @(Resolve-DnsName $n -Type A -ErrorAction Stop | Where-Object { $_.Type -eq "A" } | ForEach-Object IPAddress)
            if (-not ($ips | Where-Object { $local -contains $_ })) { Add-Manual "DNS: $n punta a $($ips -join ', '); aggiornare i record interni verso $($local -join ', ') (lo script non modifica il DNS)." }
            else { $notes += "DNS $n → questa macchina" }
        } catch { Add-Manual "DNS: $n non risolve; creare il record interno verso $($local -join ', ')." }
    }
    if ($hostManifest -and $hostManifest.PSObject.Properties["unc_paths"]) {
        foreach ($u in $hostManifest.unc_paths) {
            $ok = Test-Path $u.path
            if (-not $ok) { Add-Manual "Share $($u.path) ($($u.setting)) non raggiungibile: concedere l'accesso a $poolLogin / account dei task." }
            else { $notes += "share $($u.setting) raggiungibile" }
        }
    }
    foreach ($port in 80, 443) {
        $rule = "NOVICROM HUB HTTP $port"
        if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue) -and $PSCmdlet.ShouldProcess($rule, "Regola firewall in ingresso (Domain)")) {
            New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Domain | Out-Null
            $notes += "regola firewall $port"
        }
    }
    $notes
}

$phaseBodies["verify"] = {
    if ($dryRun) { return @("WhatIf: smoke-test, readyz, hub_recovery_selfcheck, hub_backup_doctor, primo hub_backup --type full") }
    $notes = @()
    & "$PSScriptRoot\smoke-test.ps1" -Environment $Environment -WaitSeconds 15
    $notes += "smoke-test: exit $LASTEXITCODE"
    if ($LASTEXITCODE -ne 0) { Add-Manual "smoke-test non superato: vedere il log di smoke-test." }
    $py = Join-Path $paths.Venv "Scripts\python.exe"
    Push-Location $paths.DjangoApp
    try {
        $sc = & $py manage.py hub_recovery_selfcheck --plan $planPath --settings=config.settings.prod 2>&1 | Out-String
        $notes += ($sc.Trim() -split "`r?`n")
        if ($LASTEXITCODE -ne 0) { Add-Manual "hub_recovery_selfcheck con errori: vedere il report." }
        & $py manage.py hub_backup_doctor --offline --no-exit-code --settings=config.settings.prod | Out-File (Join-Path $stateDir "doctor.txt") -Encoding UTF8
        & $py manage.py hub_backup --type full --no-exit-code --settings=config.settings.prod | Out-File (Join-Path $stateDir "primo-backup.txt") -Encoding UTF8
        $notes += "doctor e primo backup FULL eseguiti (doctor.txt, primo-backup.txt)"
    } finally { Pop-Location }
    Add-Manual "Prova manuale: accesso con un utente tecnico e apertura di un allegato privato da una scheda."
    $notes
}

$phaseBodies["report"] = {
    if ($dryRun) { return @("WhatIf: recovery-report-<data>.html/.json in $stateDir") }
    $r = Write-RestoreReport $state $stateDir
    @("report: $($r.Html)", "RTO totale: $($r.RtoMinutes) minuti")
}

# ═════════════════════════════════════════════════════════════════════════════
$exitCode = 0
try {
    if ($CachePrereqsOnly) {
        Write-Log "Preparazione della cache degli installer in $cacheDir" "STEP"
        $lock = Get-Content $lockPath -Raw | ConvertFrom-Json
        foreach ($item in $lock.items) {
            if (-not $item.PSObject.Properties["sha256"]) { Write-Log "$($item.name): senza hash nel lock, saltato" "WARN"; continue }
            if ($PSCmdlet.ShouldProcess($item.name, "Download verificato in cache")) {
                $f = Get-VerifiedInstaller $item $cacheDir
                Write-Log "$($item.name): ok ($f)" "SUCCESS"
            }
        }
        # copia del lock accanto agli installer: il SetupWizard (exe) non contiene deployment\recovery
        if ($PSCmdlet.ShouldProcess((Join-Path $cacheDir "prereqs.lock.json"), "Copia del lock")) {
            Copy-Item -LiteralPath $lockPath -Destination (Join-Path $cacheDir "prereqs.lock.json") -Force
        }
        return
    }
    if (-not $PublicHostname -and -not ($SkipPhase -contains "iis")) { throw "Indicare -PublicHostname (es. hub.costruzioninovicrom.it)." }
    Load-HostFacts
    foreach ($ph in (Get-PendingPhases $state $SkipPhase -Resume:$Resume)) {
        Invoke-Phase $ph $phaseBodies[$ph.Key]
    }
    foreach ($s in $SkipPhase) { if (-not $state.phases.Contains($s)) { $state.phases[$s] = [ordered]@{ status = "skipped"; notes = @("saltata con -SkipPhase") } } }
    if (-not $dryRun) { Save-RestoreState $state $statePath }
    Write-LogSeparator
    Write-Log "Ripristino completato. Azioni manuali rimaste: $(@($state.manual_actions).Count)." "SUCCESS"
    @($state.manual_actions) | ForEach-Object { Write-Log "  · $_" "WARN" }
} catch {
    Write-Log "$_" "ERROR"
    Write-Log "Stato salvato in ${statePath}: correggere e rilanciare con -Resume." "WARN"
    $exitCode = 1
} finally {
    $WhatIfPreference = $false
    Stop-Transcript | Out-Null
}
exit $exitCode
