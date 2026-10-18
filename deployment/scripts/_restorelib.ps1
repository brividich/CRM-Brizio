# _restorelib.ps1 - Funzioni del tool di ripristino (restore-host.ps1), separate per poterle testare.
# Da includere con: . "$PSScriptRoot\_restorelib.ps1" (dopo _lib.ps1 e _sqllib.ps1).
# Nessuna funzione qui scrive segreti su disco o a video.

Set-StrictMode -Version Latest

$RESTORE_PHASES = @(
    @{ Id = 0;  Key = "preflight";   Title = "Preflight" },
    @{ Id = 1;  Key = "prereqs";     Title = "Prerequisiti" },
    @{ Id = 2;  Key = "sql";         Title = "SQL Server e database" },
    @{ Id = 3;  Key = "secrets";     Title = "Segreti (Recovery Kit)" },
    @{ Id = 4;  Key = "files";       Title = "File (media e radici private)" },
    @{ Id = 5;  Key = "release";     Title = "Release" },
    @{ Id = 6;  Key = "iis";         Title = "IIS" },
    @{ Id = 7;  Key = "tasks";       Title = "Task pianificati" },
    @{ Id = 8;  Key = "entra";       Title = "Connector Entra" },
    @{ Id = 9;  Key = "network";     Title = "Identità e rete" },
    @{ Id = 10; Key = "verify";      Title = "Verifica" },
    @{ Id = 11; Key = "report";      Title = "Report" }
)

# ── stato e ripresa ──────────────────────────────────────────────────────────

function New-RestoreState([hashtable]$Params) {
    return [ordered]@{
        schema_version = 1
        started_at     = (Get-Date).ToString("o")
        params         = $Params
        phases         = [ordered]@{}
        manual_actions = @()
        diffs          = @()
    }
}

function Read-RestoreState([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    $json = Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $state = [ordered]@{ schema_version = $json.schema_version; started_at = $json.started_at; params = @{};
                         phases = [ordered]@{}; manual_actions = @($json.manual_actions); diffs = @($json.diffs) }
    foreach ($p in $json.params.PSObject.Properties) { $state.params[$p.Name] = $p.Value }
    if ($json.PSObject.Properties["restored_dbs"]) { $state["restored_dbs"] = @($json.restored_dbs) }
    foreach ($p in $json.phases.PSObject.Properties) {
        $v = $p.Value
        $get = { param($name) if ($v.PSObject.Properties[$name]) { $v.$name } else { $null } }
        $state.phases[$p.Name] = [ordered]@{ status = (& $get "status"); started_at = (& $get "started_at");
                                             finished_at = (& $get "finished_at"); seconds = (& $get "seconds");
                                             notes = @(& $get "notes") }
    }
    return $state
}

function Save-RestoreState($State, [string]$Path) {
    $dir = Split-Path $Path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir -WhatIf:$false | Out-Null }
    $tmp = "$Path.tmp"
    ($State | ConvertTo-Json -Depth 8) | Set-Content -Path $tmp -Encoding UTF8 -WhatIf:$false
    # [IO.File] invece di Move-Item: con i percorsi brevi 8.3 il provider di PS 5.1 fallisce
    [System.IO.File]::Copy($tmp, $Path, $true)
    [System.IO.File]::Delete($tmp)
}

function Get-PendingPhases($State, [string[]]$SkipPhase, [switch]$Resume) {
    $out = @()
    foreach ($ph in $RESTORE_PHASES) {
        if ($SkipPhase -contains $ph.Key -or $SkipPhase -contains [string]$ph.Id) { continue }
        if ($Resume -and $State.phases.Contains($ph.Key) -and $State.phases[$ph.Key].status -in @("ok", "skipped")) { continue }
        $out += $ph
    }
    return $out
}

# ── piano e versioni ─────────────────────────────────────────────────────────

function Get-SqlMajorFromVersion([string]$ProductVersion) {
    if (-not $ProductVersion) { return 0 }
    return [int]($ProductVersion.Split(".")[0])
}

function Assert-SqlVersionCompatible([string]$SourceVersion, [int]$TargetMajor) {
    # 2022 = 16, 2025 = 17: un backup non si ripristina mai su una versione più vecchia.
    $src = Get-SqlMajorFromVersion $SourceVersion
    if ($TargetMajor -lt $src) {
        throw "Versione SQL di destinazione ($TargetMajor) inferiore a quella del backup ($src, $SourceVersion): ripristino impossibile. Usare -SqlMajorVersion 2025."
    }
}

function ConvertTo-SqlMajor([int]$Year) {
    switch ($Year) { 2019 { 15 } 2022 { 16 } 2025 { 17 } default { throw "Versione SQL non gestita: $Year" } }
}

function Get-PlanDatabaseNames($Plan) {
    return @($Plan.databases.PSObject.Properties | ForEach-Object { $_.Name })
}

function Assert-DatabaseInPlan($Plan, [string]$Database) {
    if ((Get-PlanDatabaseNames $Plan) -notcontains $Database) {
        throw "Il database '$Database' non è nel piano di ripristino: rifiuto di toccarlo."
    }
}

function Get-LatestSetDir([string]$EnvRoot, [string]$Kind) {
    Get-ChildItem -Path $EnvRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^\d{8}_\d{6}_$Kind$" -and (Test-Path (Join-Path $_.FullName "manifest.json")) } |
        Sort-Object Name | Select-Object -Last 1
}

# ── prerequisiti (lock) ──────────────────────────────────────────────────────

function Test-PrereqWanted($Item, [hashtable]$Facts) {
    $when = [string]$Item.when
    if ($when -eq "always") { return $true }
    if ($when -like "python_minor=*") { return $Facts.python_minor -eq $when.Split("=")[1] }
    if ($when -like "host_manifest_has=*") { return [bool]$Facts.host_extensions -and ($Facts.host_extensions -match $when.Split("=")[1]) }
    if ($when -eq "sql_missing") { return [bool]$Facts.sql_missing }
    if ($when -eq "entra_connector") { return [bool]$Facts.entra_connector }
    return $false
}

function Get-VerifiedInstaller($Item, [string]$CacheDir, [switch]$NoDownload) {
    <# Installer dalla cache (o scaricato da url_resolved) SOLO se l'SHA-256 coincide col lock. #>
    if (-not ($Item.PSObject.Properties["sha256"]) -or -not $Item.sha256) {
        throw "Il prerequisito '$($Item.name)' non ha un hash nel lock: non viene scaricato (rilanciare update-prereqs-lock.ps1)."
    }
    $expected = ([string]$Item.sha256).ToLowerInvariant()
    $cached = if ($CacheDir -and $Item.PSObject.Properties["file_name"]) { Join-Path $CacheDir $Item.file_name } else { "" }
    if ($cached -and (Test-Path $cached)) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $cached).Hash.ToLowerInvariant() -eq $expected) { return $cached }
        Write-Log "Cache di '$($Item.name)' con hash diverso: ignorata." "WARN"
    }
    if ($NoDownload) { throw "'$($Item.name)' non è nella cache e il download non è consentito." }
    $url = [string]$Item.url_resolved
    if ($url -notmatch '^https://') { throw "URL non https per '$($Item.name)': $url" }
    $tmp = Join-Path $env:TEMP ("pn-prereq-" + [guid]::NewGuid().ToString("N"))
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $tmp).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Remove-Item -LiteralPath $tmp -Force
        throw "Hash di '$($Item.name)' diverso dal lock (atteso $($expected.Substring(0,16))…, scaricato $($actual.Substring(0,16))…): il file è cambiato alla fonte. Aggiornare il lock."
    }
    if ($cached) {
        try { New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null; Copy-Item -LiteralPath $tmp -Destination $cached -Force } catch { }
    }
    return $tmp
}

function Invoke-SilentInstall($Item, [string]$Installer, [string]$CacheDir) {
    $instArgs = ([string]$Item.silent_args).Replace("{cache}", $CacheDir)
    if ($Item.kind -eq "msi") {
        $p = Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$Installer`" $instArgs" -Wait -PassThru
    } else {
        $p = Start-Process -FilePath $Installer -ArgumentList $instArgs -Wait -PassThru
    }
    if ($p.ExitCode -notin @(0, 3010, 1641)) { throw "Installazione di '$($Item.name)' fallita (exit $($p.ExitCode))." }
    return $p.ExitCode
}

# ── report ───────────────────────────────────────────────────────────────────

function ConvertTo-HtmlSafe([string]$Text) {
    return [System.Net.WebUtility]::HtmlEncode([string]$Text)
}

function Write-RestoreReport($State, [string]$OutDir) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $json = Join-Path $OutDir "recovery-report-$stamp.json"
    $html = Join-Path $OutDir "recovery-report-$stamp.html"
    $start = [datetime]$State.started_at
    $verifyEnd = if ($State.phases.Contains("verify") -and $State.phases["verify"].finished_at) { [datetime]$State.phases["verify"].finished_at } else { Get-Date }
    $rto = [int]($verifyEnd - $start).TotalMinutes
    $State["rto_minutes"] = $rto
    ($State | ConvertTo-Json -Depth 8) | Set-Content -Path $json -Encoding UTF8 -WhatIf:$false
    $rows = foreach ($ph in $RESTORE_PHASES) {
        if (-not $State.phases.Contains($ph.Key)) { continue }
        $p = $State.phases[$ph.Key]
        "<tr><td>$($ph.Id)</td><td>$(ConvertTo-HtmlSafe $ph.Title)</td><td class='$($p.status)'>$($p.status)</td><td>$($p.seconds)</td><td>$((@($p.notes) | ForEach-Object { ConvertTo-HtmlSafe $_ }) -join '<br>')</td></tr>"
    }
    $manual = (@($State.manual_actions) | ForEach-Object { "<li>$(ConvertTo-HtmlSafe $_)</li>" }) -join ""
    $diffs = (@($State.diffs) | ForEach-Object { "<li>$(ConvertTo-HtmlSafe $_)</li>" }) -join ""
    @"
<!doctype html><html lang="it"><head><meta charset="utf-8"><title>Report ripristino NOVICROM HUB</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1a202c}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #d7e0ea;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f2f5f8}
.ok{color:#276749;font-weight:700}.failed{color:#c53030;font-weight:700}.warning{color:#b7791f;font-weight:700}.skipped{color:#718096}</style></head>
<body><h1>Ripristino NOVICROM HUB</h1>
<p>Ambiente <b>$(ConvertTo-HtmlSafe $State.params.Environment)</b> · macchina <b>$env:COMPUTERNAME</b> · inizio $start · <b>RTO $rto minuti</b></p>
<table><tr><th>#</th><th>Fase</th><th>Esito</th><th>Secondi</th><th>Note</th></tr>$($rows -join '')</table>
<h2>Azioni manuali rimaste</h2><ul>$manual</ul>
<h2>Differenze rispetto alla macchina d'origine</h2><ul>$diffs</ul>
<p>Archiviare questo report come evidenza della prova di disaster recovery.</p></body></html>
"@ | Set-Content -Path $html -Encoding UTF8 -WhatIf:$false
    return @{ Json = $json; Html = $html; RtoMinutes = $rto }
}
