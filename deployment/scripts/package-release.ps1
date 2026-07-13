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
    [string]$VersionOverride = "",
    # Branch da impacchettare. Di DEFAULT si impacchetta la linea di release, NON
    # la cartella di lavoro: quest'ultima puo' essere su un branch qualsiasi e avere
    # modifiche non committate (e' gia' successo di spedire in prod la versione sbagliata).
    [string]$Branch = "release/prod",
    # Vecchio comportamento: impacchetta la cartella di lavoro cosi' com'e' (WIP incluso).
    [switch]$FromWorkingTree,
    # -WithTests passa -WithTests al release_guard per eseguire la test suite.
    # Di default i test sono saltati. Specificare per release con validazione completa.
    [switch]$WithTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

function Test-IsExcludedByWizardBundleRules {
    param(
        [string]$BaseDir,
        [System.IO.FileInfo]$File,
        [string[]]$ExcludeDirNames,
        [string[]]$ExcludeFilePatterns
    )

    $normalizedBaseDir = [System.IO.Path]::GetFullPath($BaseDir).TrimEnd('\', '/')
    $normalizedFilePath = [System.IO.Path]::GetFullPath($File.FullName)
    if ($normalizedFilePath.StartsWith($normalizedBaseDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relativePath = $normalizedFilePath.Substring($normalizedBaseDir.Length).TrimStart('\', '/')
    } else {
        $relativePath = $File.Name
    }
    $pathSegments = $relativePath -split '[\\/]'

    if ($pathSegments.Count -gt 1) {
        $lastDirectoryIndex = $pathSegments.Count - 2
        foreach ($segment in $pathSegments[0..$lastDirectoryIndex]) {
            if ($ExcludeDirNames -contains $segment) {
                return $true
            }
        }
    }

    foreach ($pattern in $ExcludeFilePatterns) {
        if ($File.Name -like $pattern) {
            return $true
        }
    }

    return $false
}

function Resolve-SetupWizardBuildPython {
    param([string]$RootPath)

    foreach ($candidate in @(
        (Join-Path $RootPath ".venv\Scripts\python.exe"),
        (Join-Path $RootPath "venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }

    return $null
}

function Get-SetupWizardNewestTrigger {
    param([string]$RootPath)

    $bundleRulesPath = Join-Path $RootPath "deployment\setup_wizard_bundle_rules.json"
    if (-not (Test-Path -LiteralPath $bundleRulesPath)) {
        throw "setup_wizard_bundle_rules.json non trovato: $bundleRulesPath"
    }

    $triggerFiles = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
    foreach ($path in @(
        (Join-Path $RootPath "VERSION"),
        (Join-Path $RootPath "deployment\setup_wizard.py"),
        (Join-Path $RootPath "deployment\SetupWizard.spec"),
        $bundleRulesPath
    )) {
        if (Test-Path -LiteralPath $path) {
            $triggerFiles.Add((Get-Item -LiteralPath $path))
        }
    }

    foreach ($directory in @(
        (Join-Path $RootPath "deployment\scripts"),
        (Join-Path $RootPath "deployment\config")
    )) {
        if (Test-Path -LiteralPath $directory) {
            foreach ($file in (Get-ChildItem -LiteralPath $directory -File -Recurse -ErrorAction SilentlyContinue)) {
                $triggerFiles.Add($file)
            }
        }
    }

    # django_app/ escluso intenzionalmente dai trigger del wizard:
    # gli aggiornamenti applicativi usano il pacchetto zip + deploy-release.ps1,
    # non richiedono la rebuild del wizard (riservato alle installazioni fresh).

    if ($triggerFiles.Count -eq 0) {
        throw "Nessun trigger valido trovato per SetupWizard.exe"
    }

    return $triggerFiles | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
}

function Invoke-SetupWizardRebuildIfNeeded {
    param([string]$RootPath)

    $wizardExePath = Join-Path $RootPath "deployment\dist\SetupWizard.exe"
    $newestTrigger = Get-SetupWizardNewestTrigger -RootPath $RootPath
    $wizardFreshnessGrace = [TimeSpan]::FromMinutes(2)
    $shouldBuild = $false

    if (-not (Test-Path -LiteralPath $wizardExePath)) {
        Write-Log "SetupWizard.exe mancante: avvio build automatica." "WARN"
        $shouldBuild = $true
    } else {
        $wizardExeInfo = Get-Item -LiteralPath $wizardExePath
        $wizardStaleness = $newestTrigger.LastWriteTimeUtc - $wizardExeInfo.LastWriteTimeUtc
        if ($wizardStaleness -gt $wizardFreshnessGrace) {
            Write-Log (
                "SetupWizard.exe obsoleto rispetto a $($newestTrigger.FullName) " +
                "(exe=$($wizardExeInfo.LastWriteTimeUtc.ToString('u')), trigger=$($newestTrigger.LastWriteTimeUtc.ToString('u')))."
            ) "WARN"
            $shouldBuild = $true
        } else {
            Write-Log "SetupWizard.exe gia allineato ai trigger del bundle." "INFO"
        }
    }

    if (-not $shouldBuild) {
        return
    }

    $pythonExe = Resolve-SetupWizardBuildPython -RootPath $RootPath
    if (-not $pythonExe) {
        Write-Log "Python non trovato: impossibile rigenerare SetupWizard.exe." "ERROR"
        exit 1
    }

    $deploymentDir = Join-Path $RootPath "deployment"
    Write-Log "Rigenerazione automatica di SetupWizard.exe..." "STEP"
    Push-Location $deploymentDir
    try {
        $pyInstallerBootstrapDir = Join-Path $RootPath "deployment\pyinstaller_bootstrap"
        if (-not (Test-Path -LiteralPath $pyInstallerBootstrapDir)) {
            Write-Log "Bootstrap PyInstaller non trovato: $pyInstallerBootstrapDir" "ERROR"
            exit 1
        }

        # On some Windows 11 workstations, Python 3.13's platform.system()
        # stalls inside a Win32_Processor WMI lookup. PyInstaller imports
        # platform during startup. Inject a local sitecustomize so parent and
        # child interpreters all fall back to environment variables instead.
        $previousPythonPath = $env:PYTHONPATH
        try {
            if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
                $env:PYTHONPATH = $pyInstallerBootstrapDir
            } else {
                $env:PYTHONPATH = "$pyInstallerBootstrapDir;$previousPythonPath"
            }
            & $pythonExe -m PyInstaller SetupWizard.spec --noconfirm
        } finally {
            if ($null -eq $previousPythonPath) {
                Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
            } else {
                $env:PYTHONPATH = $previousPythonPath
            }
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Build di SetupWizard.exe fallita con exit code $LASTEXITCODE." "ERROR"
            exit 1
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $wizardExePath)) {
        Write-Log "Build completata ma SetupWizard.exe non e stato generato." "ERROR"
        exit 1
    }

    $rebuiltWizard = Get-Item -LiteralPath $wizardExePath
    Write-Log "SetupWizard.exe rigenerato: $($rebuiltWizard.LastWriteTimeUtc.ToString('u'))" "SUCCESS"
}

# ---------------------------------------------------------------------------
# Risolvi SourcePath (root del repository)
# ---------------------------------------------------------------------------
# Lo script è in deployment\scripts\, la root repo è due livelli su
$script:RepoRoot = (Resolve-Path "$PSScriptRoot\..\.." -ErrorAction SilentlyContinue).Path
$script:ExportWorktree = $null

function Remove-ExportWorktree {
    if ($script:ExportWorktree -and (Test-Path $script:ExportWorktree)) {
        & git -C $script:RepoRoot worktree remove --force "$script:ExportWorktree" 2>$null | Out-Null
        if (Test-Path $script:ExportWorktree) {
            Remove-Item -LiteralPath $script:ExportWorktree -Recurse -Force -ErrorAction SilentlyContinue
        }
        & git -C $script:RepoRoot worktree prune 2>$null | Out-Null
        Write-Log "Export temporaneo del branch rimosso." "INFO"
        $script:ExportWorktree = $null
    }
}
# Qualunque errore: niente cartelle lasciate in giro.
trap { Remove-ExportWorktree; break }

if ($SourcePath) {
    # Cartella esplicita: l'utente sa cosa sta facendo.
    $resolvedSourcePath = Resolve-Path $SourcePath -ErrorAction SilentlyContinue
    if (-not $resolvedSourcePath) {
        Write-Log "SourcePath non valido: $SourcePath" "ERROR"
        exit 1
    }
    $SourcePath = $resolvedSourcePath.Path
}
elseif ($FromWorkingTree) {
    if (-not $script:RepoRoot) {
        Write-Log "Impossibile determinare la root del progetto. Specifica -SourcePath." "ERROR"
        exit 1
    }
    $SourcePath = $script:RepoRoot
    Write-Log "-FromWorkingTree: impacchetto la CARTELLA DI LAVORO, comprese eventuali modifiche non committate." "WARN"
}
else {
    # DEFAULT: impacchetta il branch di release, esportandolo in una cartella
    # temporanea. Cosi' non conta su quale branch e' il repo, ne' se ha WIP sporco.
    if (-not $script:RepoRoot) {
        Write-Log "Impossibile determinare la root del repository." "ERROR"
        exit 1
    }
    & git -C $script:RepoRoot rev-parse --verify --quiet "$Branch" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Branch di release '$Branch' non trovato." "ERROR"
        Write-Log "Usa -Branch <nome> per un altro branch, oppure -FromWorkingTree per impacchettare la cartella corrente." "ERROR"
        exit 1
    }
    $commit = (& git -C $script:RepoRoot rev-parse --short "$Branch").Trim()
    $script:ExportWorktree = Join-Path ([System.IO.Path]::GetTempPath()) ("pn-pkg-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    Write-Log "Impacchetto il branch '$Branch' (commit $commit) — NON la cartella di lavoro." "INFO"
    & git -C $script:RepoRoot worktree add --detach --quiet "$script:ExportWorktree" "$Branch" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $script:ExportWorktree)) {
        Write-Log "Impossibile esportare il branch '$Branch'." "ERROR"
        exit 1
    }
    $SourcePath = $script:ExportWorktree

    # Artefatti di build NON versionati (gitignorati: *.spec, deployment/dist/) ma
    # necessari alla creazione del pacchetto: li prendiamo dal repo locale, perche'
    # l'export del branch, per definizione, contiene solo i file committati.
    # NB: si copia solo lo .spec, NON SetupWizard.exe: l'exe viene rigenerato dallo
    # script a partire dal setup_wizard.py del branch, cosi' il wizard nel pacchetto
    # corrisponde davvero al codice che stai rilasciando (un exe vecchio sul disco
    # non deve finire in produzione).
    foreach ($relPath in @("deployment\SetupWizard.spec")) {
        $artifactSrc = Join-Path $script:RepoRoot $relPath
        if (Test-Path -LiteralPath $artifactSrc) {
            $artifactDst = Join-Path $SourcePath $relPath
            $artifactDstDir = Split-Path -Parent $artifactDst
            if (-not (Test-Path -LiteralPath $artifactDstDir)) {
                New-Item -ItemType Directory -Path $artifactDstDir -Force | Out-Null
            }
            Copy-Item -LiteralPath $artifactSrc -Destination $artifactDst -Force
            Write-Log "Artefatto non versionato copiato nell'export: $relPath" "INFO"
        }
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
# SetupWizard.exe - rebuild automatico se mancante/obsoleto
# ---------------------------------------------------------------------------
Invoke-SetupWizardRebuildIfNeeded -RootPath $SourcePath

# ---------------------------------------------------------------------------
# Release guard (documentazione, versioni, wizard, smoke ACL)
# ---------------------------------------------------------------------------
$releaseGuard = Join-Path $SourcePath "tools\release_guard.ps1"
if (-not (Test-Path -LiteralPath $releaseGuard)) {
    Write-Log "release_guard.ps1 non trovato in tools\\." "ERROR"
    exit 1
}

Write-Log "Esecuzione release guard..." "STEP"
$guardArgs = @{ SourcePath = $SourcePath }
if ($WithTests) { $guardArgs['WithTests'] = $true }
& $releaseGuard @guardArgs
if ($LASTEXITCODE -ne 0) {
    Write-Log "release_guard fallito: correggi i mismatch prima di creare il pacchetto." "ERROR"
    exit 1
}
Write-Log "release guard completato." "SUCCESS"

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
# Pattern di esclusione - separati per tipo (directory vs file)
# ---------------------------------------------------------------------------
# IMPORTANTE: il pacchetto è costruito con una ALLOWLIST (vedi $includeTopLevel
# più sotto): si copiano SOLO i path noti necessari al deploy, non "tutto tranne".
# Questo evita che cartelle spurie/sensibili del working dir (ssl/, database/,
# backup*/, hotfix/, temp/, media_private/, dump DB, ecc.) finiscano nello zip.
# Gli $excludeDirs/$excludeFiles qui sotto servono a PULIRE all'interno dei path
# inclusi (es. media/media_private/logs/__pycache__ dentro django_app/).
#
# DIRECTORY da escludere (passate a robocopy con /XD)
$excludeDirs = @(
    ".git",           # repository git
    ".claude",        # worktree degli agent + cache (pesante, contiene copie di file)
    ".tmp_py",        # workspace temporaneo locale
    ".tmp_tests",     # test temporanei con permessi variabili
    ".venv",          # virtual environment Python
    "venv",           # virtual environment alternativo
    "node_modules",   # dipendenze JS
    "__pycache__",    # cache Python
    "logs",           # log applicazione
    "media",          # media locale (upload runtime, dati personali)
    "media_private",  # documenti personali fuori webroot (referti, ecc.) - GDPR
    "doc",            # documentazione interna: contiene xlsx/csv con dati personali
    "docs",           # idem: import/export con dati personali, non serve in prod
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
    ".env",           # NON includere .env - va gestito separatamente sul server
    "config.ini",     # eventuale residuo legacy locale
    "db.sqlite3",
    "*.sqlite3",
    "*.pyc",
    "*.pyo",
    "DIPENDENTI.csv", # file sensibile
    "medical-examinations-people.xlsx",  # dato sanitario fuori posto (difesa in profondità)
    "*.bak",          # backup locali di sorgenti (es. *.html.bak): cruft, non vanno in prod
    "*.exe",
    "*.db"
)
# NB sui pattern Excel/CSV:
# - NON usare "*.xls": in robocopy il wildcard cattura anche "*.xlsx" e rimuoverebbe
#   django_app/tasks/vrf_template/MOD_073_VRF_Rev10.xlsx, template runtime di vrf_generator.py.
# - NON escludere "*.xlsx"/"*.csv" globalmente per lo stesso motivo (template runtime).
# I file Excel/CSV con dati personali vivono in doc/, docs/, media/ e .claude/,
# tutti già esclusi via $excludeDirs. L'unico dato personale fuori da quelle dir
# (medical-examinations-people.xlsx) è escluso per nome qui sopra.

# ---------------------------------------------------------------------------
# ALLOWLIST: solo i path top-level necessari al deploy finiscono nel pacchetto.
# deploy-release.ps1 richiede django_app/ (obbligatorio), e usa deployment/scripts,
# sql/ (trigger), tools/. VERSION e i .md di root sono documentazione/versione.
# Tutto il resto del working dir (ssl, database, backup*, hotfix, temp, config,
# media_private, ecc.) NON viene mai copiato.
# ---------------------------------------------------------------------------
$includeDirs = @(
    "django_app",     # applicazione (obbligatoria per il deploy)
    "deployment",     # script di deploy/attivazione + dist/SetupWizard.exe
    "tools",          # release_guard e helper
    "sql"             # trigger/DDL SQL Server applicati in deploy
)
$includeRootFiles = @(
    "VERSION",
    "README.md",
    "CHANGELOG.md",
    "CLAUDE.md"
)

Write-Log "Copia file sorgenti in temp dir (allowlist)..." "STEP"

# Copia ciascuna directory inclusa con robocopy, applicando le esclusioni di
# pulizia interna (media/media_private/logs/__pycache__/.env/sqlite, ecc.).
foreach ($dir in $includeDirs) {
    $src = Join-Path $SourcePath $dir
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Log "Path incluso assente, salto: $dir" "WARN"
        continue
    }
    $dst = Join-Path $tempDir $dir
    $robocopyArgs = @(
        $src,
        $dst,
        "/E",           # subdirectory incluse
        "/NFL", "/NDL", "/NJH", "/NJS",
        "/R:0", "/W:0"
    )
    foreach ($ex in $excludeDirs)  { $robocopyArgs += "/XD"; $robocopyArgs += $ex }
    foreach ($ef in $excludeFiles) { $robocopyArgs += "/XF"; $robocopyArgs += $ef }

    & robocopy @robocopyArgs | Out-Null
    # Robocopy exit code ≤ 7 = success (bit mask)
    if ($LASTEXITCODE -gt 7) {
        Write-Log "Robocopy fallito (dir=$dir) con exit code $LASTEXITCODE" "ERROR"
        exit 1
    }
}

# File di root inclusi singolarmente.
foreach ($file in $includeRootFiles) {
    $src = Join-Path $SourcePath $file
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $tempDir $file) -Force
    } else {
        Write-Log "File di root incluso assente, salto: $file" "WARN"
    }
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
# .NET ZipFile::CreateFromDirectory è ~10x più veloce di Compress-Archive
# su progetti con molti file piccoli (nessun overhead PowerShell per file).
# Fastest evita compressione pesante su file già piccoli/binari senza beneficio reale.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $tempDir,
    $zipPath,
    [System.IO.Compression.CompressionLevel]::Fastest,
    $false
)
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
# Pulizia: rimuove l'export temporaneo del branch (nessuna cartella lasciata in giro)
# ---------------------------------------------------------------------------
Remove-ExportWorktree

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
