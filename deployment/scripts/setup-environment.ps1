<#
.SYNOPSIS
    Prima configurazione di un ambiente (test o prod) su Windows Server.
    Crea la struttura directory, il virtualenv Python e installa i requisiti.

.DESCRIPTION
    Da eseguire UNA SOLA VOLTA per ambiente, o dopo una reinstallazione.
    NON configura IIS (usa configure-iis-site.ps1 per quello).

.PARAMETER Environment
    Ambiente target: "test" oppure "prod"

.PARAMETER PythonPath
    Percorso all'eseguibile python.exe da usare.
    Default: auto-discovery di un Python 3.11+ valido

.PARAMETER RequirementsPath
    Percorso al file requirements.txt.
    Default: rilevato automaticamente dalla sorgente del progetto.

.EXAMPLE
    .\setup-environment.ps1 -Environment test
    .\setup-environment.ps1 -Environment prod -PythonPath "C:\Python312\python.exe"
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [string]$PythonPath = "",

    [string]$RequirementsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin

function Test-SupportedPythonPath {
    param(
        [string]$Candidate
    )

    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) {
        return $null
    }

    try {
        $versionOutput = & $Candidate --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        $versionText = ($versionOutput | Out-String).Trim()
        if ($versionText -match 'Python\s+(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                return [pscustomobject]@{
                    Path    = $Candidate
                    Version = $versionText
                }
            }
        }
    } catch {
        return $null
    }

    return $null
}

function Find-PythonExecutable {
    param(
        [string]$PreferredPath
    )

    $candidates = New-Object System.Collections.Generic.List[string]

    if ($PreferredPath) {
        $candidates.Add($PreferredPath)
    }

    $staticCandidates = @(
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files (x86)\Python313\python.exe",
        "C:\Program Files (x86)\Python312\python.exe",
        "C:\Program Files (x86)\Python311\python.exe"
    )
    foreach ($candidate in $staticCandidates) {
        $candidates.Add($candidate)
    }

    if ($env:LOCALAPPDATA) {
        foreach ($versionDir in @("Python313", "Python312", "Python311")) {
            $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\$versionDir\python.exe"))
        }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and $pythonCmd.Source) {
        $candidates.Add($pythonCmd.Source)
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        $normalized = $candidate.ToLowerInvariant()
        if ($seen.ContainsKey($normalized)) { continue }
        $seen[$normalized] = $true
        $info = Test-SupportedPythonPath -Candidate $candidate
        if ($info) {
            return $info
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher -and $pyLauncher.Source) {
        foreach ($selector in @("-3.13", "-3.12", "-3.11")) {
            try {
                $resolvedPath = & $pyLauncher.Source $selector -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -ne 0) { continue }
                $resolved = (($resolvedPath | Out-String).Trim() -split "`r?`n")[0].Trim()
                $info = Test-SupportedPythonPath -Candidate $resolved
                if ($info) {
                    return $info
                }
            } catch {
                continue
            }
        }
    }

    return $null
}

Write-LogSeparator
Write-Log "SETUP AMBIENTE: $($Environment.ToUpper())" "STEP"
Write-LogSeparator

# ---------------------------------------------------------------------------
# Verifica Python
# ---------------------------------------------------------------------------
$resolvedPython = Find-PythonExecutable -PreferredPath $PythonPath
if (-not $resolvedPython) {
    if ($PythonPath) {
        Write-Log "Python non trovato o non supportato in: $PythonPath" "ERROR"
    }
    Write-Log "Installa Python 3.11+ e riprova, oppure specifica -PythonPath" "ERROR"
    exit 1
}
$PythonPath = $resolvedPython.Path
$pyVersion = $resolvedPython.Version
Write-Log "Python trovato: $pyVersion ($PythonPath)" "INFO"

# ---------------------------------------------------------------------------
# Struttura directory
# ---------------------------------------------------------------------------
$paths = Get-EnvPaths -Env $Environment
$dirs  = @(
    $paths.Base,
    $paths.Releases,
    $paths.Logs,
    $paths.Config,
    $paths.Static,
    $paths.Media,
    $paths.Run,
    "$DEPLOY_BASE\shared",
    "$DEPLOY_BASE\shared\scripts",
    "$DEPLOY_BASE\shared\packages",
    "$DEPLOY_BASE\shared\backups"
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Log "Creata directory: $dir" "INFO"
    } else {
        Write-Log "Directory esistente: $dir" "INFO"
    }
}

# ---------------------------------------------------------------------------
# Virtualenv
# ---------------------------------------------------------------------------
$venvPath = $paths.Venv
if (Test-Path "$venvPath\Scripts\python.exe") {
    Write-Log "Virtualenv già esistente: $venvPath" "INFO"
    $recreate = Read-Host "Vuoi ricreare il virtualenv? (s/N)"
    if ($recreate -match "^[sS]$") {
        Write-Log "Rimozione venv esistente..." "WARN"
        Remove-Item $venvPath -Recurse -Force
    }
}

if (-not (Test-Path "$venvPath\Scripts\python.exe")) {
    Write-Log "Creazione virtualenv in: $venvPath" "STEP"
    & $PythonPath -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Creazione virtualenv fallita." "ERROR"
        exit 1
    }
    Write-Log "Virtualenv creato." "SUCCESS"
}

# ---------------------------------------------------------------------------
# Aggiorna pip e installa wheel / pyodbc build tools
# ---------------------------------------------------------------------------
Write-Log "Aggiornamento pip..." "STEP"
& "$venvPath\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { Write-Log "Aggiornamento pip fallito (non bloccante)." "WARN" }

# ---------------------------------------------------------------------------
# Installa requirements (opzionale in questa fase)
# ---------------------------------------------------------------------------
if ($RequirementsPath -and (Test-Path $RequirementsPath)) {
    Write-Log "Installazione dipendenze da: $RequirementsPath" "STEP"
    & "$venvPath\Scripts\python.exe" -m pip install -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Installazione requisiti fallita." "ERROR"
        exit 1
    }
    Write-Log "Dipendenze installate." "SUCCESS"
} else {
    Write-Log "RequirementsPath non specificato o non trovato - skip. Le dipendenze verranno installate durante deploy-release.ps1." "WARN"
}

# ---------------------------------------------------------------------------
# File config di esempio (se non esistono)
# ---------------------------------------------------------------------------
$envExampleSrc = "$PSScriptRoot\..\config\.env.$Environment.example"
$envDest       = "$($paths.Config)\.env"
if (-not (Test-Path $envDest)) {
    if (Test-Path $envExampleSrc) {
        Copy-Item $envExampleSrc $envDest
        Write-Log "Copiato .env.example in $envDest - MODIFICA CON I VALORI REALI!" "WARN"
    } else {
        Write-Log "File .env non trovato in $envDest - crealo prima del deploy!" "WARN"
    }
}

# ---------------------------------------------------------------------------
# File marker versione ambiente
# ---------------------------------------------------------------------------
@"
ENVIRONMENT=$Environment
CREATED=$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
PYTHON=$PythonPath
PYTHON_VERSION=$pyVersion
"@ | Set-Content "$($paths.Run)\environment.txt" -Encoding UTF8

Write-LogSeparator
Write-Log "Setup ambiente '$Environment' completato." "SUCCESS"
Write-Log "" "INFO"
Write-Log "PROSSIMI PASSI:" "STEP"
Write-Log "  1. Copia e modifica il file config: $($paths.Config)\.env" "INFO"
Write-Log "  2. Configura IIS: .\configure-iis-site.ps1 -Environment $Environment" "INFO"
Write-Log "  3. Deploya il primo release: .\deploy-release.ps1 -Environment $Environment -PackagePath <zip>" "INFO"
Write-LogSeparator
