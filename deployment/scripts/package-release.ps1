<#
.SYNOPSIS
    Crea un pacchetto release (.zip) del progetto Portale Novicrom.
    Da eseguire sul PC di sviluppo prima di ogni deploy.

.DESCRIPTION
    - Legge la versione dal file VERSION (single source of truth)
    - Fallback legacy: config/app_version.py, poi config/settings/base.py
    - Crea uno zip con timestamp: portale-novicrom-vX.Y.Z-YYYYMMDD_HHmmss.zip
    - Esclude file non necessari per la produzione
    - Salva lo zip in shared\packages\ (se esiste) o nella directory corrente

.PARAMETER SourcePath
    Root del progetto Django. Default: directory padre di questo script (repo root).

.PARAMETER OutputDir
    Directory dove salvare lo zip. Default: C:\PortaleNovicrom\shared\packages\ o .\releases\

.PARAMETER VersionOverride
    Forza una versione specifica invece di leggerla dal codice (es. "0.8.6")

.EXAMPLE
    .\package-release.ps1
    .\package-release.ps1 -OutputDir "D:\Releases"
    .\package-release.ps1 -VersionOverride "0.8.6"
#>

param(
    [string]$SourcePath = "",
    [string]$OutputDir  = "",
    [string]$VersionOverride = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

# ---------------------------------------------------------------------------
# Risolvi SourcePath (root del repository)
# ---------------------------------------------------------------------------
if (-not $SourcePath) {
    # Lo script è in deployment\scripts\, la root repo è due livelli su
    $SourcePath = (Resolve-Path "$PSScriptRoot\..\.." -ErrorAction SilentlyContinue).Path
    if (-not $SourcePath) {
        Write-Log "Impossibile determinare la root del progetto. Specifica -SourcePath." "ERROR"
        exit 1
    }
}
Write-Log "Source path: $SourcePath" "INFO"

# ---------------------------------------------------------------------------
# Risolvi OutputDir
# ---------------------------------------------------------------------------
if (-not $OutputDir) {
    $sharedPackages = "C:\PortaleNovicrom\shared\packages"
    if (Test-Path $sharedPackages) {
        $OutputDir = $sharedPackages
    } else {
        $OutputDir = "$SourcePath\releases"
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
}
Write-Log "Output dir: $OutputDir" "INFO"

# ---------------------------------------------------------------------------
# Legge versione (single source of truth: VERSION)
# ---------------------------------------------------------------------------
$version = $VersionOverride
if (-not $version) {
    $versionFile = "$SourcePath\VERSION"
    if (Test-Path $versionFile) {
        try {
            $firstLine = (Get-Content -Path $versionFile -Encoding UTF8 | Select-Object -First 1)
            if ($firstLine) {
                $version = $firstLine.Trim()
            }
        } catch {
            Write-Log "Impossibile leggere VERSION ($($_.Exception.Message))." "WARN"
        }
    }
}
if (-not $version) {
    $appVersionFile = "$SourcePath\django_app\config\app_version.py"
    if (Test-Path $appVersionFile) {
        $match = Select-String -Path $appVersionFile -Pattern 'DEFAULT_APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
        if ($match) {
            $version = $match.Matches[0].Groups[1].Value
        }
    }
}
if (-not $version) {
    $settingsFile = "$SourcePath\django_app\config\settings\base.py"
    if (Test-Path $settingsFile) {
        $match = Select-String -Path $settingsFile -Pattern 'APP_VERSION\s*=\s*env\([^,]+,\s*"([^"]+)"' | Select-Object -First 1
        if ($match) {
            $version = $match.Matches[0].Groups[1].Value
        }
    }
}
if (-not $version) {
    $version = "unknown"
    Write-Log "Versione non rilevata automaticamente: uso fallback 'unknown'." "WARN"
}
Write-Log "Versione: $version" "INFO"

# ---------------------------------------------------------------------------
# Timestamp e nome file
# ---------------------------------------------------------------------------
$timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$zipName    = "portale-novicrom-v$version-$timestamp.zip"
$zipPath    = "$OutputDir\$zipName"

Write-LogSeparator
Write-Log "CREAZIONE PACCHETTO RELEASE" "STEP"
Write-Log "File: $zipPath" "INFO"
Write-LogSeparator

# ---------------------------------------------------------------------------
# Directory temporanea per raccogliere i file
# ---------------------------------------------------------------------------
$tempRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "Temp"
} else {
    [System.IO.Path]::GetTempPath().TrimEnd('\')
}
$tempDir = Join-Path $tempRoot "portale-novicrom-pkg-$timestamp"
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# ---------------------------------------------------------------------------
# Pattern di esclusione — separati per tipo (directory vs file)
# ---------------------------------------------------------------------------
# DIRECTORY da escludere (passate a robocopy con /XD)
$excludeDirs = @(
    ".git",           # repository git
    ".venv",          # virtual environment Python
    "venv",           # virtual environment alternativo
    "node_modules",   # dipendenze JS
    "__pycache__",    # cache Python
    "logs",           # log applicazione
    "media",          # media locale
    "dist",           # build output
    "build",          # build output
    "htmlcov",        # coverage HTML
    "releases",       # pacchetti release
    ".mypy_cache",    # cache mypy
    ".pytest_cache",  # cache pytest
    "*.egg-info"      # metadata pacchetti Python (directory)
)

# FILE da escludere (passati a robocopy con /XF)
$excludeFiles = @(
    ".env",           # NON includere .env — va gestito separatamente sul server
    "config.ini",     # idem
    "db.sqlite3",
    "*.sqlite3",
    "*.pyc",
    "*.pyo",
    "DIPENDENTI.csv", # file sensibile
    "*.exe",
    "*.db"
)

# ---------------------------------------------------------------------------
# Copia selettiva con robocopy
# ---------------------------------------------------------------------------
Write-Log "Copia file sorgenti in temp dir..." "STEP"

# Robocopy copia tutto tranne le directory/file esclusi
# /R:0 /W:0 = nessun retry (evita hang su file bloccati)
$robocopyArgs = @(
    $SourcePath,
    $tempDir,
    "/E",           # subdirectory incluse
    "/NFL",         # no file list
    "/NDL",         # no dir list
    "/NJH",         # no job header
    "/NJS",         # no job summary
    "/R:0",         # nessun retry
    "/W:0"          # nessun attesa tra retry
)
foreach ($ex in $excludeDirs) {
    $robocopyArgs += "/XD"
    $robocopyArgs += $ex
}
foreach ($ef in $excludeFiles) {
    $robocopyArgs += "/XF"
    $robocopyArgs += $ef
}

& robocopy @robocopyArgs | Out-Null
# Robocopy exit code ≤ 7 = success (bit mask)
if ($LASTEXITCODE -gt 7) {
    Write-Log "Robocopy fallito con exit code $LASTEXITCODE" "ERROR"
    exit 1
}

# Rimozione manuale di __pycache__ rimasti
Get-ChildItem $tempDir -Filter "__pycache__" -Recurse -Directory | Remove-Item -Recurse -Force
Get-ChildItem $tempDir -Filter "*.pyc"        -Recurse            | Remove-Item -Force
Get-ChildItem $tempDir -Filter "*.pyo"        -Recurse            | Remove-Item -Force

# Rimozione directory logs dentro django_app (se presenti)
$logsInApp = "$tempDir\django_app\logs"
if (Test-Path $logsInApp) { Remove-Item $logsInApp -Recurse -Force }

Write-Log "File copiati nella temp dir." "SUCCESS"

# ---------------------------------------------------------------------------
# Crea zip
# ---------------------------------------------------------------------------
Write-Log "Compressione in $zipPath..." "STEP"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$tempDir\*" -DestinationPath $zipPath -CompressionLevel Optimal
Write-Log "Zip creato." "SUCCESS"

# ---------------------------------------------------------------------------
# Pulizia temp
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $tempDir) {
    try {
        Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Log "Pulizia temp non completata: $($_.Exception.Message)" "WARN"
    }
}

# ---------------------------------------------------------------------------
# Riepilogo
# ---------------------------------------------------------------------------
$zipInfo = Get-Item $zipPath
$sizeMB  = [math]::Round($zipInfo.Length / 1MB, 2)

Write-LogSeparator
Write-Log "Pacchetto creato con successo!" "SUCCESS"
Write-Log "  File:      $zipPath" "INFO"
Write-Log "  Versione:  $version" "INFO"
Write-Log "  Dimensione: ${sizeMB} MB" "INFO"
Write-Log "" "INFO"
Write-Log "PROSSIMO: copia il file sul server e lancia:" "STEP"
Write-Log "  .\deploy-release.ps1 -Environment test -PackagePath '$zipPath'" "INFO"
Write-LogSeparator

# Restituisce il percorso per uso da altri script
Write-Output $zipPath
