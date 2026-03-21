<#
.SYNOPSIS
    Deploya un pacchetto release su un ambiente (test o prod).
    NON attiva il release — usa activate-release.ps1 per quello.

.DESCRIPTION
    Questo script:
    1. Estrae il pacchetto zip in releases\TIMESTAMP\
    2. Copia .env e config.ini dal config\ dell'ambiente
    3. Aggiorna le dipendenze pip nel venv condiviso
    4. Esegue collectstatic (output in static\)
    5. Esegue migrate
    6. Esegue createcachetable (se primo deploy)
    7. Stampa il tag release da usare con activate-release.ps1

    NOTA: il release rimane in releases\ ma NON diventa "current" finché
    non si esegue activate-release.ps1 (o si usa -AutoActivate).

.PARAMETER Environment
    Ambiente target: "test" oppure "prod"

.PARAMETER PackagePath
    Percorso al file .zip creato da package-release.ps1

.PARAMETER AutoActivate
    Se specificato, dopo il deploy attiva automaticamente il release.
    Utile per deploy veloci in TEST. Default: $false (raccomandato per PROD)

.PARAMETER SkipMigrate
    Salta l'esecuzione delle migration Django. Da usare con cautela.

.PARAMETER SkipCollectStatic
    Salta collectstatic. Utile se i file statici non sono cambiati.

.EXAMPLE
    .\deploy-release.ps1 -Environment test  -PackagePath "C:\PortaleNovicrom\shared\packages\portale-novicrom-v0.8.2-20260321_143000.zip"
    .\deploy-release.ps1 -Environment prod  -PackagePath "C:\...\portale-novicrom-v0.8.2-20260321_143000.zip" -AutoActivate
    .\deploy-release.ps1 -Environment test  -PackagePath "..." -SkipMigrate -SkipCollectStatic
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [Parameter(Mandatory = $true)]
    [string]$PackagePath,

    [switch]$AutoActivate,
    [switch]$SkipMigrate,
    [switch]$SkipCollectStatic
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin
Assert-ValidEnvironment -Env $Environment

# ---------------------------------------------------------------------------
# Validazione input
# ---------------------------------------------------------------------------
if (-not (Test-Path $PackagePath)) {
    Write-Log "Pacchetto non trovato: $PackagePath" "ERROR"
    exit 1
}

$paths       = Get-EnvPaths -Env $Environment
$settingsMod = "config.settings.$Environment"
$releaseTag  = Get-Date -Format "yyyyMMdd_HHmmss"
$releaseDir  = "$($paths.Releases)\$releaseTag"

Write-LogSeparator
Write-Log "DEPLOY RELEASE — $($Environment.ToUpper())" "STEP"
Write-Log "Pacchetto:  $PackagePath" "INFO"
Write-Log "Release ID: $releaseTag" "INFO"
Write-Log "Directory:  $releaseDir" "INFO"
Write-LogSeparator

# ---------------------------------------------------------------------------
# 1. Estrazione pacchetto
# ---------------------------------------------------------------------------
Write-Log "[1/7] Estrazione pacchetto..." "STEP"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Expand-Archive -Path $PackagePath -DestinationPath $releaseDir -Force
Write-Log "Pacchetto estratto in: $releaseDir" "SUCCESS"

# Verifica che django_app esista nel pacchetto
$djangoApp = "$releaseDir\django_app"
if (-not (Test-Path $djangoApp)) {
    Write-Log "Struttura pacchetto non valida: manca django_app\ in $releaseDir" "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
Write-Log "Struttura pacchetto verificata." "SUCCESS"

# ---------------------------------------------------------------------------
# 2. Copia configurazione da config\
# ---------------------------------------------------------------------------
Write-Log "[2/7] Copia configurazione..." "STEP"
$envFile    = "$($paths.Config)\.env"
$configFile = "$($paths.Config)\config.ini"

if (-not (Test-Path $envFile)) {
    Write-Log "File .env non trovato: $envFile" "ERROR"
    Write-Log "Crea il file prima di eseguire il deploy." "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
Copy-Item $envFile    "$djangoApp\.env"    -Force
Write-Log "  .env copiato." "INFO"

if (Test-Path $configFile) {
    Copy-Item $configFile "$djangoApp\config.ini" -Force
    Write-Log "  config.ini copiato." "INFO"
} else {
    Write-Log "  config.ini non trovato in $configFile — potrebbe essere necessario." "WARN"
}

# ---------------------------------------------------------------------------
# 3. Verifica / crea venv
# ---------------------------------------------------------------------------
Write-Log "[3/7] Verifica virtualenv..." "STEP"
$venvPython = "$($paths.Venv)\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Log "Virtualenv non trovato. Esegui prima setup-environment.ps1." "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
$pyVer = & $venvPython --version 2>&1
Write-Log "Venv Python: $pyVer" "INFO"

# ---------------------------------------------------------------------------
# 4. Installazione dipendenze
# ---------------------------------------------------------------------------
Write-Log "[4/7] Installazione dipendenze pip..." "STEP"
$reqFile = "$djangoApp\requirements.txt"
if (-not (Test-Path $reqFile)) {
    Write-Log "requirements.txt non trovato: $reqFile" "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
& $venvPython -m pip install -r $reqFile --no-warn-script-location 2>&1 | Tee-Object -FilePath "$($paths.Logs)\pip-install-$releaseTag.log"
if ($LASTEXITCODE -ne 0) {
    Write-Log "Installazione pip fallita. Vedi log: $($paths.Logs)\pip-install-$releaseTag.log" "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
Write-Log "Dipendenze installate." "SUCCESS"

# ---------------------------------------------------------------------------
# Ambiente per i comandi Django
# ---------------------------------------------------------------------------
$djangoEnv = @{
    DJANGO_SETTINGS_MODULE = $settingsMod
    PYTHONPATH             = $djangoApp
}

# ---------------------------------------------------------------------------
# 5. collectstatic
# ---------------------------------------------------------------------------
if (-not $SkipCollectStatic) {
    Write-Log "[5/7] collectstatic..." "STEP"
    # STATIC_ROOT deve puntare a $paths.Static — verificato nel .env
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -Args     @("manage.py", "collectstatic", "--noinput", "--settings=$settingsMod") `
                    -EnvVars  $djangoEnv
        Write-Log "collectstatic completato." "SUCCESS"
    } catch {
        Write-Log "collectstatic fallito: $_" "ERROR"
        Remove-Item $releaseDir -Recurse -Force
        exit 1
    }
} else {
    Write-Log "[5/7] collectstatic — SALTATO (flag -SkipCollectStatic)" "WARN"
}

# ---------------------------------------------------------------------------
# 6. migrate
# ---------------------------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Log "[6/7] migrate..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -Args     @("manage.py", "migrate", "--settings=$settingsMod", "--noinput") `
                    -EnvVars  $djangoEnv
        Write-Log "migrate completato." "SUCCESS"
    } catch {
        Write-Log "migrate fallito: $_" "ERROR"
        Write-Log "ATTENZIONE: il pacchetto è estratto ma il DB potrebbe essere inconsistente." "WARN"
        Remove-Item $releaseDir -Recurse -Force
        exit 1
    }
} else {
    Write-Log "[6/7] migrate — SALTATO (flag -SkipMigrate)" "WARN"
}

# ---------------------------------------------------------------------------
# 7. createcachetable (idempotente, sicuro da rieseguire)
# ---------------------------------------------------------------------------
Write-Log "[7/7] createcachetable (idempotente)..." "STEP"
try {
    Invoke-Venv -VenvPath $paths.Venv `
                -WorkDir  $djangoApp `
                -Args     @("manage.py", "createcachetable", "--settings=$settingsMod") `
                -EnvVars  $djangoEnv
    Write-Log "createcachetable completato." "SUCCESS"
} catch {
    Write-Log "createcachetable fallito (non bloccante se la tabella esiste già): $_" "WARN"
}

# ---------------------------------------------------------------------------
# Salva marker release
# ---------------------------------------------------------------------------
@"
RELEASE_TAG=$releaseTag
PACKAGE=$PackagePath
DEPLOYED=$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
ENVIRONMENT=$Environment
"@ | Set-Content "$releaseDir\.release_info" -Encoding UTF8

Write-LogSeparator
Write-Log "Deploy completato: $releaseTag" "SUCCESS"
Write-Log "" "INFO"

if ($AutoActivate) {
    Write-Log "AutoActivate attivo — avvio activate-release.ps1..." "STEP"
    & "$PSScriptRoot\activate-release.ps1" -Environment $Environment -ReleaseTag $releaseTag
} else {
    Write-Log "Release pronto ma NON ancora attivo." "INFO"
    Write-Log "Per attivarlo:" "STEP"
    Write-Log "  .\activate-release.ps1 -Environment $Environment -ReleaseTag $releaseTag" "INFO"
    Write-Log "" "INFO"
    Write-Log "Per fare smoke test prima di attivare (opzionale):" "INFO"
    Write-Log "  .\smoke-test.ps1 -Environment $Environment  # testa l'ambiente corrente" "INFO"
}
Write-LogSeparator
