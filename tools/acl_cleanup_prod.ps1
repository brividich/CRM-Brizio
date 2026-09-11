<#
.SYNOPSIS
    Bonifica ACL in produzione: dry-run, revisione, applicazione con backup.

.DESCRIPTION
    Riattiva i binding ACL per-route conservando gli accessi esistenti. Il comando
    Django fa il lavoro; questo script lo incornicia con le sicurezze che servono
    su un ambiente vivo: backup delle tabelle prima di scrivere, report prima e
    dopo, e la verifica dei casi campione a valle.

    Il default e' -DryRun: senza -Apply non tocca nulla.

    Ordine consigliato:
      1. .\tools\acl_cleanup_prod.ps1                      # report, non scrive
      2. leggere il JSON e discutere i grant di grandfathering
      3. .\tools\acl_cleanup_prod.ps1 -Apply               # backup + scrittura
      4. verificare i casi campione (parametro -Verify)

.PARAMETER Apply
    Scrive davvero. Senza questo flag il comando gira in sola lettura.

.PARAMETER SyncLegacy
    Riallinea i grant canonici a False il cui permesso legacy e' invece concesso:
    sono le spunte fatte in "Gestione Accessi" che non hanno mai avuto effetto.
    Additivo (concede, non revoca), ma va deciso: non e' incluso per default.

.PARAMETER Verify
    Coppie "utente=path" su cui lanciare acl_diagnose a fine corsa.
    Es: -Verify "mario.rossi@example.local=/assets/impostazioni/"

.EXAMPLE
    .\tools\acl_cleanup_prod.ps1 -Verify "nome.cognome@costruzioninovicrom.it=/assets/impostazioni/"

.EXAMPLE
    .\tools\acl_cleanup_prod.ps1 -Apply -SyncLegacy
#>
param(
    [switch]$Apply,
    [switch]$SyncLegacy,
    [string]$Settings = "config.settings.prod",
    [string]$SourcePath = "",
    [string]$PythonExe = "",
    [string]$OutputDir = "",
    [string[]]$Verify = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $SourcePath) {
    $SourcePath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $SourcePath = (Resolve-Path $SourcePath).Path
}
if (-not $PythonExe) {
    # In sviluppo il venv sta dentro il repo; in produzione il repo e'
    # <root>\current e il venv gli sta ACCANTO, in <root>env (convenzione usata
    # da tutti gli script prod del progetto). Senza questo, si ripiega sul Python
    # di sistema, che non ha Django, e l'errore che arriva parla dei settings.
    $candidates = @(
        (Join-Path $SourcePath ".venv\Scripts\python.exe"),
        (Join-Path (Split-Path -Parent $SourcePath) "venv\Scripts\python.exe"),
        "C:\PortaleNovicrom\prodenv\Scripts\python.exe"
    )
    $PythonExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $PythonExe) {
        throw ("Nessun Python di progetto trovato. Cercato in:`n  " +
               ($candidates -join "`n  ") +
               "`nPassa il percorso con -PythonExe.")
    }
}
if (-not $OutputDir) {
    # Fuori dal repo di proposito: report e backup dentro il checkout
    # sporcherebbero il working tree, e il pre-flight del packager si blocca
    # su un tree sporco.
    $base = if ($env:TEMP) { $env:TEMP } else { $SourcePath }
    $OutputDir = Join-Path $base ("acl-cleanup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$manage = Join-Path $SourcePath "django_app\manage.py"
if (-not (Test-Path $manage)) { throw "manage.py non trovato in $SourcePath" }

# I settings devono caricarsi PRIMA di qualunque altra cosa: quando falliscono,
# Django elenca solo i comandi built-in e l'errore che arriva e' un fuorviante
# "Unknown command: acl_cleanup". Meglio dire cosa manca davvero.
# Le sonde scrivono su stderr quando falliscono, ed e' proprio il caso che ci
# interessa: senza abbassare ErrorActionPreference qui, PowerShell solleverebbe
# sulla prima riga di stderr e il messaggio utile non verrebbe mai composto.
$probe = $null
$diag = $null
try {
    $ErrorActionPreference = "Continue"
    $probe = & $PythonExe $manage help acl_cleanup "--settings=$Settings" 2>&1
    $probeExit = $LASTEXITCODE
    if ($probeExit -ne 0 -or ($probe -join "`n") -match "Unknown command") {
        # "help <comando>" dice solo "Unknown command"; la ragione vera sta nella
        # nota che Django stampa in coda a "help" senza argomenti.
        $diag = & $PythonExe $manage help "--settings=$Settings" 2>&1
    }
} finally {
    $ErrorActionPreference = "Stop"
}
if ($diag -ne $null) {
    $detail = ($diag | Where-Object { $_ -match "error:|ImproperlyConfigured|not properly configured" }) -join " "
    if (-not $detail) { $detail = ($probe -join " ") }
    if ($detail -match "No module named 'django'|Couldn't import Django") {
        throw ("Il Python usato non ha Django: $PythonExe`n" +
               "In produzione serve il venv del deploy (di norma <root>env\Scripts\python.exe). " +
               "Passalo con -PythonExe. Dettaglio: $detail")
    }
    throw ("Il comando acl_cleanup non e' disponibile con --settings=$Settings. " +
           "Quasi sempre significa che quei settings non si caricano su questa macchina " +
           "(manca il config\.env dell'ambiente). Dettaglio: $detail")
}

$reportBefore = Join-Path $OutputDir "report-prima.json"
$backupDir = Join-Path $OutputDir "backup"

Write-Host "== acl_cleanup ==" -ForegroundColor Cyan
Write-Host "Sorgente : $SourcePath"
Write-Host "Settings : $Settings"
Write-Host "Output   : $OutputDir"
Write-Host ""

# ── 1. Ricognizione (mai scrive) ───────────────────────────────────────────
Write-Host "1) Dry-run: cosa cambierebbe" -ForegroundColor Yellow
& $PythonExe $manage acl_cleanup --report $reportBefore --settings=$Settings
if ($LASTEXITCODE -ne 0) { throw "acl_cleanup (dry-run) fallito con codice $LASTEXITCODE" }

$report = Get-Content $reportBefore -Raw | ConvertFrom-Json
$grandfathered = @($report.role_grants_to_create).Count
$userGrants = @($report.user_grants_to_create).Count
$divergenze = @($report.legacy_divergences).Count
Write-Host ""
Write-Host "   binding da riattivare : $(@($report.bindings_to_activate).Count)"
Write-Host "   grant conservativi    : $grandfathered ruolo + $userGrants utente"
Write-Host "   spunte legacy ignorate: $divergenze"
Write-Host ""

if (-not $Apply) {
    Write-Host "Sola lettura: nessuna modifica scritta." -ForegroundColor Green
    Write-Host "Report: $reportBefore"
    Write-Host "Per applicare: riesegui con -Apply (aggiungi -SyncLegacy se vuoi anche il riallineamento)."
    return
}

# ── 2. Applicazione, con backup delle tabelle ──────────────────────────────
Write-Host "2) Applicazione (backup in $backupDir)" -ForegroundColor Yellow
$applyArgs = @($manage, "acl_cleanup", "--apply", "--backup-dir", $backupDir,
               "--report", (Join-Path $OutputDir "report-applicato.json"), "--settings=$Settings")
if ($SyncLegacy) { $applyArgs += "--sync-legacy" }
& $PythonExe @applyArgs
if ($LASTEXITCODE -ne 0) { throw "acl_cleanup --apply fallito con codice $LASTEXITCODE" }

# ── 3. Verifica: la seconda corsa deve essere a vuoto ──────────────────────
Write-Host ""
Write-Host "3) Controllo di idempotenza" -ForegroundColor Yellow
$reportAfter = Join-Path $OutputDir "report-dopo.json"
& $PythonExe $manage acl_cleanup --report $reportAfter --settings=$Settings | Out-Null
$after = Get-Content $reportAfter -Raw | ConvertFrom-Json
$residui = @($after.bindings_to_activate).Count
if ($residui -gt 0) {
    Write-Warning "Restano $residui binding non attivati: leggere $reportAfter."
} else {
    Write-Host "   nessun binding residuo." -ForegroundColor Green
}

# ── 4. Casi campione ───────────────────────────────────────────────────────
if ($Verify.Count -gt 0) {
    Write-Host ""
    Write-Host "4) Diagnosi dei casi campione" -ForegroundColor Yellow
    foreach ($case in $Verify) {
        $parts = $case.Split("=", 2)
        if ($parts.Count -ne 2) {
            Write-Warning "Formato non valido (serve utente=path): $case"
            continue
        }
        Write-Host "   -- $($parts[0]) su $($parts[1])"
        & $PythonExe $manage acl_diagnose --user $parts[0] --path $parts[1] --settings=$Settings
    }
}

Write-Host ""
Write-Host "Fatto. Backup e report in $OutputDir" -ForegroundColor Green
Write-Host "Per tornare indietro: i JSON in $backupDir contengono le righe come erano prima."
