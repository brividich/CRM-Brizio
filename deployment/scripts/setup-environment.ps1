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
    Default: "C:\Python311\python.exe"

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

    [string]$PythonPath = "C:\Python311\python.exe",

    [string]$RequirementsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin

Write-LogSeparator
Write-Log "SETUP AMBIENTE: $($Environment.ToUpper())" "STEP"
Write-LogSeparator

# ---------------------------------------------------------------------------
# Verifica Python
# ---------------------------------------------------------------------------
if (-not (Test-Path $PythonPath)) {
    Write-Log "Python non trovato in: $PythonPath" "ERROR"
    Write-Log "Installa Python 3.11+ e riprova, oppure specifica -PythonPath" "ERROR"
    exit 1
}
$pyVersion = & $PythonPath --version 2>&1
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
    Write-Log "RequirementsPath non specificato o non trovato — skip. Le dipendenze verranno installate durante deploy-release.ps1." "WARN"
}

# ---------------------------------------------------------------------------
# File config di esempio (se non esistono)
# ---------------------------------------------------------------------------
$envExampleSrc = "$PSScriptRoot\..\config\.env.$Environment.example"
$envDest       = "$($paths.Config)\.env"
if (-not (Test-Path $envDest)) {
    if (Test-Path $envExampleSrc) {
        Copy-Item $envExampleSrc $envDest
        Write-Log "Copiato .env.example in $envDest — MODIFICA CON I VALORI REALI!" "WARN"
    } else {
        Write-Log "File .env non trovato in $envDest — crealo prima del deploy!" "WARN"
    }
}

$configIniDest = "$($paths.Config)\config.ini"
if (-not (Test-Path $configIniDest)) {
    Write-Log "File config.ini non trovato in $configIniDest — crealo prima del deploy!" "WARN"
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
Write-Log "  2. Copia e modifica: $($paths.Config)\config.ini" "INFO"
Write-Log "  3. Configura IIS: .\configure-iis-site.ps1 -Environment $Environment" "INFO"
Write-Log "  4. Deploya il primo release: .\deploy-release.ps1 -Environment $Environment -PackagePath <zip>" "INFO"
Write-LogSeparator
