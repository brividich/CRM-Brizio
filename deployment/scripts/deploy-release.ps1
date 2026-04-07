<#
.SYNOPSIS
    Deploya un pacchetto release su un ambiente (test o prod).
    NON attiva il release - usa activate-release.ps1 per quello.

.DESCRIPTION
    Questo script:
    1. Estrae il pacchetto zip in releases\TIMESTAMP\
    2. Copia .env e config.ini dal config\ dell'ambiente
    3. Aggiorna le dipendenze pip nel venv condiviso
    4. Esegue collectstatic (output in static\)
    5. Esegue migrate
    6. Riallinea assenze.tipo_assenza a Flessibilita su SQL Server
    7. Esegue createcachetable (se primo deploy)
    8. Stampa il tag release da usare con activate-release.ps1

    NOTA: il release rimane in releases\ ma NON diventa "current" finche
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
    .\deploy-release.ps1 -Environment test  -PackagePath "C:\PortaleNovicrom\shared\packages\portale-novicrom-vX.Y.Z-20260321_143000.zip"
    .\deploy-release.ps1 -Environment prod  -PackagePath "C:\...\portale-novicrom-vX.Y.Z-20260321_143000.zip" -AutoActivate
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

$paths = Get-EnvPaths -Env $Environment
$settingsMap = @{
    "test" = "config.settings.prod"
    "prod" = "config.settings.prod"
}
$settingsMod = $settingsMap[$Environment]
$releaseTag = Get-Date -Format "yyyyMMdd_HHmmss"
$releaseDir = "$($paths.Releases)\$releaseTag"

function Get-InstalledSqlServerOdbcDrivers {
    try {
        $drivers = @(Get-OdbcDriver -Name "*SQL Server*" -ErrorAction Stop |
            Select-Object -ExpandProperty Name -Unique)
        if ($drivers.Count -gt 0) {
            return $drivers
        }
    }
    catch {
    }

    $registryNames = @()
    foreach ($keyPath in @(
        "HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Drivers",
        "HKLM:\SOFTWARE\WOW6432Node\ODBC\ODBCINST.INI\ODBC Drivers"
    )) {
        if (-not (Test-Path $keyPath)) {
            continue
        }
        try {
            $props = Get-ItemProperty -Path $keyPath -ErrorAction Stop
            foreach ($property in $props.PSObject.Properties) {
                if ($property.Name -like "*SQL Server*" -and $property.Name -notlike "PS*") {
                    $registryNames += $property.Name
                }
            }
        }
        catch {
        }
    }

    @($registryNames | Sort-Object -Unique)
}

function Get-PreferredSqlServerOdbcDriver {
    param([string[]]$Drivers)

    $ordered = @(
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "ODBC Driver 11 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server"
    )

    foreach ($candidate in $ordered) {
        if ($Drivers -contains $candidate) {
            return $candidate
        }
    }
    if ($Drivers.Count -gt 0) {
        return $Drivers[0]
    }
    return $null
}

function Sync-ReleaseEnvSqlDriver {
    param([string]$EnvPath)

    if (-not (Test-Path $EnvPath)) {
        return
    }

    $content = Get-Content $EnvPath -Raw -Encoding UTF8
    if ($content -notmatch "(?m)^DB_ENGINE=sqlserver\s*$") {
        return
    }

    $installedDrivers = Get-InstalledSqlServerOdbcDrivers
    if (-not $installedDrivers -or $installedDrivers.Count -eq 0) {
        throw "Nessun driver ODBC SQL Server installato sul server applicativo."
    }

    $preferredDriver = Get-PreferredSqlServerOdbcDriver -Drivers $installedDrivers
    if (-not $preferredDriver) {
        throw "Impossibile determinare un driver ODBC SQL Server valido."
    }

    $configuredDriver = $null
    $driverMatch = [regex]::Match($content, "(?m)^DB_DRIVER=(.+)$")
    if ($driverMatch.Success) {
        $configuredDriver = $driverMatch.Groups[1].Value.Trim()
    }

    if (-not $configuredDriver) {
        $content = $content.TrimEnd() + "`r`nDB_DRIVER=$preferredDriver`r`n"
        Set-Content -Path $EnvPath -Value $content -Encoding UTF8
        Write-Log "  DB_DRIVER assente: allineato automaticamente a '$preferredDriver'." "WARN"
        return
    }

    if ($installedDrivers -contains $configuredDriver) {
        Write-Log "  Driver ODBC SQL Server confermato: $configuredDriver" "INFO"
        return
    }

    $content = [regex]::Replace(
        $content,
        "(?m)^DB_DRIVER=.+$",
        "DB_DRIVER=$preferredDriver"
    )
    Set-Content -Path $EnvPath -Value $content -Encoding UTF8
    Write-Log "  DB_DRIVER '$configuredDriver' non installato: riallineato a '$preferredDriver'." "WARN"
}

function Assert-StaticAssetsPresent {
    param([string]$StaticRoot)

    $requiredFiles = @(
        (Join-Path $StaticRoot "core\css\theme.css"),
        (Join-Path $StaticRoot "monitoring\css\monitoring.css")
    )

    $missing = @($requiredFiles | Where-Object { -not (Test-Path $_) })
    if ($missing.Count -gt 0) {
        throw "Statici attesi non trovati: $($missing -join ', ')"
    }
}

Write-LogSeparator
Write-Log "DEPLOY RELEASE - $($Environment.ToUpper())" "STEP"
Write-Log "Pacchetto:  $PackagePath" "INFO"
Write-Log "Release ID: $releaseTag" "INFO"
Write-Log "Directory:  $releaseDir" "INFO"
Write-LogSeparator

# ---------------------------------------------------------------------------
# 1. Estrazione pacchetto
# ---------------------------------------------------------------------------
Write-Log "[1/8] Estrazione pacchetto..." "STEP"
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
Write-Log "[2/8] Copia configurazione..." "STEP"
$envFile = "$($paths.Config)\.env"
$configFile = "$($paths.Config)\config.ini"

if (-not (Test-Path $envFile)) {
    Write-Log "File .env non trovato: $envFile" "ERROR"
    Write-Log "Crea il file prima di eseguire il deploy." "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
Copy-Item $envFile "$djangoApp\.env" -Force
Write-Log "  .env copiato." "INFO"
Sync-ReleaseEnvSqlDriver -EnvPath "$djangoApp\.env"

if (Test-Path $configFile) {
    Copy-Item $configFile "$djangoApp\config.ini" -Force
    Copy-Item $configFile "$releaseDir\config.ini" -Force
    Write-Log "  config.ini copiato in django_app\\ e nella root del release." "INFO"
}
else {
    Write-Log "  config.ini non trovato in $configFile - potrebbe essere necessario." "WARN"
}

# ---------------------------------------------------------------------------
# 3. Verifica / crea venv
# ---------------------------------------------------------------------------
Write-Log "[3/8] Verifica virtualenv..." "STEP"
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
Write-Log "[4/8] Installazione dipendenze pip..." "STEP"
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
    PYTHONPATH = $djangoApp
    STATIC_ROOT = $paths.Static
    MEDIA_ROOT = $paths.Media
}

# ---------------------------------------------------------------------------
# 5. collectstatic
# ---------------------------------------------------------------------------
if (-not $SkipCollectStatic) {
    Write-Log "[5/8] collectstatic..." "STEP"
    # STATIC_ROOT deve puntare a $paths.Static - verificato nel .env
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -Args     @("manage.py", "collectstatic", "--noinput", "--settings=$settingsMod") `
                    -EnvVars  $djangoEnv
        Assert-StaticAssetsPresent -StaticRoot $paths.Static
        Write-Log "collectstatic completato e statici verificati." "SUCCESS"
    }
    catch {
        Write-Log "collectstatic fallito: $_" "ERROR"
        Remove-Item $releaseDir -Recurse -Force
        exit 1
    }
}
else {
    Write-Log "[5/8] collectstatic - SALTATO (flag -SkipCollectStatic)" "WARN"
}

# ---------------------------------------------------------------------------
# 6. migrate
# ---------------------------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Log "[6/8] migrate..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -Args     @("manage.py", "migrate", "--settings=$settingsMod", "--noinput") `
                    -EnvVars  $djangoEnv
        Write-Log "migrate completato." "SUCCESS"
    }
    catch {
        Write-Log "migrate fallito: $_" "ERROR"
        Write-Log "ATTENZIONE: il pacchetto e estratto ma il DB potrebbe essere inconsistente." "WARN"
        Remove-Item $releaseDir -Recurse -Force
        exit 1
    }
}
else {
    Write-Log "[6/8] migrate - SALTATO (flag -SkipMigrate)" "WARN"
}

# ---------------------------------------------------------------------------
# 7. allinea tipo_assenza assenze (idempotente, richiesto per DB legacy)
# ---------------------------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Log "[7/8] allinea assenze.tipo_assenza a Flessibilita..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -Args     @("manage.py", "allinea_tipo_assenza_flessibilita", "--settings=$settingsMod") `
                    -EnvVars  $djangoEnv
        Write-Log "allinea_tipo_assenza_flessibilita completato." "SUCCESS"
    }
    catch {
        Write-Log "allinea_tipo_assenza_flessibilita fallito: $_" "ERROR"
        Write-Log "ATTENZIONE: il DB legacy assenze potrebbe rifiutare Flessibilita finche il vincolo non viene riallineato." "WARN"
        Remove-Item $releaseDir -Recurse -Force
        exit 1
    }
}
else {
    Write-Log "[7/8] allinea tipo_assenza - SALTATO (flag -SkipMigrate)" "WARN"
}

# ---------------------------------------------------------------------------
# 8. createcachetable (idempotente, sicuro da rieseguire)
# ---------------------------------------------------------------------------
Write-Log "[8/8] createcachetable (idempotente)..." "STEP"
try {
    Invoke-Venv -VenvPath $paths.Venv `
                -WorkDir  $djangoApp `
                -Args     @("manage.py", "createcachetable", "--settings=$settingsMod") `
                -EnvVars  $djangoEnv
    Write-Log "createcachetable completato." "SUCCESS"
}
catch {
    Write-Log "createcachetable fallito (non bloccante se la tabella esiste gia): $_" "WARN"
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
    Write-Log "AutoActivate attivo - avvio activate-release.ps1..." "STEP"
    & "$PSScriptRoot\activate-release.ps1" -Environment $Environment -ReleaseTag $releaseTag
}
else {
    Write-Log "Release pronto ma NON ancora attivo." "INFO"
    Write-Log "Per attivarlo:" "STEP"
    Write-Log "  .\activate-release.ps1 -Environment $Environment -ReleaseTag $releaseTag" "INFO"
    Write-Log "" "INFO"
    Write-Log "Per fare smoke test prima di attivare (opzionale):" "INFO"
    Write-Log "  .\smoke-test.ps1 -Environment $Environment  # testa l'ambiente corrente" "INFO"
}
Write-LogSeparator
