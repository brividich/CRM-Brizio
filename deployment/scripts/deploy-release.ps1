<#
.SYNOPSIS
    Deploya un pacchetto release su un ambiente (test o prod).
    NON attiva il release - usa activate-release.ps1 per quello.

.DESCRIPTION
    Questo script:
    1. Estrae il pacchetto zip in releases\TIMESTAMP\
    2. Copia .env dal config\ dell'ambiente
    3. Aggiorna le dipendenze pip nel venv condiviso
    4. Esegue collectstatic (output in static\)
    4b. Riallinea ACL su static\ e media\ per IIS_IUSRS (mitiga la perdita
        di ereditarieta NTFS dopo collectstatic --clear, che altrimenti
        fa rispondere 401 a IIS StaticFileModule su tutti i CSS/JS)
    5. Esegue migrate
    6. Allinea schema legacy/runtime SQL Server
    7. Applica trigger SQL Server (trg_*.sql in automazioni/migrations/ e sql/)
    8. Riallinea assenze.tipo_assenza a Flessibilita su SQL Server
    9. Esegue createcachetable (se primo deploy)
   10. Esegue setup_q_schedules (registra/aggiorna gli Schedule django-q2 dei
       background job: automation queue, mailbox approvazioni, report scadenze,
       notifiche/escalation anomalie) - idempotente
   11. Registra/aggiorna il Task Scheduler per process_automation_queue (idempotente)
   12. Stampa il tag release da usare con activate-release.ps1

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

.PARAMETER AllowEnvDrift
    Forza il deploy anche se current\django_app\.env e config\.env non sono
    allineati. Default: il deploy si ferma per evitare ripristini silenziosi
    di configurazioni modificate nel file .env della release attiva.

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
    [switch]$SkipCollectStatic,
    [switch]$SkipSqlTriggers,
    [switch]$AllowEnvDrift
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

function Get-EnvKeyValueMap {
    param([string]$Path)

    $map = @{}
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        if ($line -notmatch "^\s*([^#=]+)=(.*)$") {
            continue
        }
        $key = $Matches[1].Trim()
        if (-not $key) {
            continue
        }
        $map[$key] = $Matches[2].Trim()
    }
    return $map
}

function Get-EnvDriftKeys {
    param(
        [string]$ConfigEnvPath,
        [string]$CurrentEnvPath
    )

    $configMap = Get-EnvKeyValueMap -Path $ConfigEnvPath
    $currentMap = Get-EnvKeyValueMap -Path $CurrentEnvPath
    $allKeys = @($configMap.Keys + $currentMap.Keys) | Sort-Object -Unique
    $driftKeys = @()

    foreach ($key in $allKeys) {
        if (-not $configMap.ContainsKey($key) -or -not $currentMap.ContainsKey($key)) {
            $driftKeys += $key
            continue
        }
        if ($configMap[$key] -ne $currentMap[$key]) {
            $driftKeys += $key
        }
    }
    return $driftKeys
}

function Assert-EnvConfigMatchesCurrent {
    param(
        [string]$ConfigEnvPath,
        [string]$CurrentEnvPath,
        [switch]$AllowDrift
    )

    if (-not (Test-Path $CurrentEnvPath)) {
        return
    }

    $configHash = (Get-FileHash -Path $ConfigEnvPath -Algorithm SHA256).Hash
    $currentHash = (Get-FileHash -Path $CurrentEnvPath -Algorithm SHA256).Hash
    if ($configHash -eq $currentHash) {
        Write-Log "  .env persistente allineato alla release attiva." "INFO"
        return
    }

    $driftKeys = @(Get-EnvDriftKeys -ConfigEnvPath $ConfigEnvPath -CurrentEnvPath $CurrentEnvPath)
    $keysLabel = if ($driftKeys.Count -gt 0) { $driftKeys -join ", " } else { "(solo commenti/ordine/encoding)" }

    if ($AllowDrift) {
        Write-Log "  .env attivo diverso da config\.env; continuo per -AllowEnvDrift." "WARN"
        Write-Log "  Chiavi divergenti: $keysLabel" "WARN"
        return
    }

    $message = @(
        "Il .env attivo differisce dal .env persistente dell'ambiente.",
        "Deploy interrotto per evitare di ripristinare configurazioni vecchie.",
        "",
        "Persistente : $ConfigEnvPath",
        "Attivo      : $CurrentEnvPath",
        "Chiavi      : $keysLabel",
        "",
        "Allinea le modifiche desiderate in config\.env, poi riesegui il deploy.",
        "Usa -AllowEnvDrift solo se vuoi forzare il comportamento storico."
    ) -join [Environment]::NewLine
    throw $message
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
Write-Log "[1/9] Estrazione pacchetto..." "STEP"
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
Write-Log "[2/9] Copia configurazione..." "STEP"
$envFile = "$($paths.Config)\.env"
if (-not (Test-Path $envFile)) {
    Write-Log "File .env non trovato: $envFile" "ERROR"
    Write-Log "Crea il file prima di eseguire il deploy." "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
try {
    Assert-EnvConfigMatchesCurrent `
        -ConfigEnvPath $envFile `
        -CurrentEnvPath "$($paths.Current)\django_app\.env" `
        -AllowDrift:$AllowEnvDrift
}
catch {
    Write-Log "$_" "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
Copy-Item $envFile "$djangoApp\.env" -Force
Write-Log "  .env copiato." "INFO"
Sync-ReleaseEnvSqlDriver -EnvPath "$djangoApp\.env"
$secureEnvScript = Join-Path $PSScriptRoot "secure-env-acl.ps1"
if (Test-Path $secureEnvScript) {
    try {
        & $secureEnvScript -Environment $Environment -AdditionalEnvPath "$djangoApp\.env" -Quiet
        Write-Log "  ACL .env ristrette." "INFO"
    } catch {
        Write-Log "  Hardening ACL .env non completato: $_" "WARN"
    }
}

# ---------------------------------------------------------------------------
# 3. Verifica / crea venv
# ---------------------------------------------------------------------------
Write-Log "[3/9] Verifica virtualenv..." "STEP"
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
Write-Log "[4/9] Installazione dipendenze pip..." "STEP"
$reqFile = "$djangoApp\requirements.txt"
if (-not (Test-Path $reqFile)) {
    Write-Log "requirements.txt non trovato: $reqFile" "ERROR"
    Remove-Item $releaseDir -Recurse -Force
    exit 1
}
# NB: pip scrive warning innocui su stderr; sotto ErrorActionPreference=Stop PowerShell
# li promuove a errore terminante (NativeCommandError) anche con exit code 0.
# Disattiviamo temporaneamente lo Stop attorno alla sola chiamata nativa e ci
# affidiamo a $LASTEXITCODE come unico indicatore di successo.
$pipLog = "$($paths.Logs)\pip-install-$releaseTag.log"
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $venvPython -m pip install -r $reqFile --no-warn-script-location 2>&1 | Tee-Object -FilePath $pipLog
$pipExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($pipExit -ne 0) {
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
    Write-Log "[5/9] collectstatic..." "STEP"
    # STATIC_ROOT deve puntare a $paths.Static - verificato nel .env
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -PyArgs   @("manage.py", "collectstatic", "--noinput", "--clear", "--settings=$settingsMod") `
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
    Write-Log "[5/9] collectstatic - SALTATO (flag -SkipCollectStatic)" "WARN"
}

# ---------------------------------------------------------------------------
# 5b. Riallineo ACL su static\ e media\ per IIS_IUSRS
# ---------------------------------------------------------------------------
# collectstatic --clear svuota e ricrea STATIC_ROOT: i file creati da Python
# non ereditano sempre le ACL del padre e l'app pool IIS perde il diritto
# di lettura. Senza IIS_IUSRS:RX, StaticFileModule risponde 401 (Access
# denied due to ACLs) su tutti i CSS/JS sotto /static/ e la pagina arriva
# al browser completamente priva di stile, pur restando autenticata.
# Riapplichiamo IIS_IUSRS:(OI)(CI)RX in modo idempotente ad ogni deploy:
# costa pochi ms e blinda la pipeline anche se collectstatic e' saltato.
Write-Log "[5b/9] Riallineo ACL static\ e media\ per IIS..." "STEP"
# IIS_IUSRS copre l'identity dell'app pool; IUSR e' l'utente di Anonymous
# Authentication e NON e' membro di IIS_IUSRS in tutte le configurazioni:
# concediamo entrambi per essere robusti rispetto a come e' configurata
# l'autenticazione del sito (Anonymous attiva, AppPool identity, ecc.).
$iisPrincipals = @("IIS_IUSRS", "IUSR")
# static\ e media\: sola lettura (RX) - servono solo a IIS per servire i file.
foreach ($aclPath in @($paths.Static, $paths.Media)) {
    if (-not (Test-Path $aclPath)) {
        Write-Log "  Path inesistente, salto: $aclPath" "WARN"
        continue
    }
    foreach ($principal in $iisPrincipals) {
        & icacls "$aclPath" /grant "${principal}:(OI)(CI)RX" /T /Q | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "  ACL ${principal}:RX applicata su $aclPath" "INFO"
        } else {
            Write-Log "  icacls ${principal} exit code $LASTEXITCODE su $aclPath - verificare" "WARN"
        }
    }
}
# media_private\: l'app SCRIVE qui (allegati anomalie, documenti). Serve Modify (M),
# non solo RX, altrimenti l'upload allegati fallisce con 500 (cartella non scrivibile).
# media_private NON e' servita da IIS (fuori webroot, GDPR): i permessi servono
# all'identity dell'app pool per leggere/scrivere/cancellare i file caricati.
if ($paths.MediaPrivate -and (Test-Path $paths.MediaPrivate)) {
    foreach ($principal in $iisPrincipals) {
        & icacls "$($paths.MediaPrivate)" /grant "${principal}:(OI)(CI)M" /T /Q | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "  ACL ${principal}:M applicata su $($paths.MediaPrivate)" "INFO"
        } else {
            Write-Log "  icacls ${principal} exit code $LASTEXITCODE su $($paths.MediaPrivate) - verificare" "WARN"
        }
    }
} else {
    Write-Log "  media_private inesistente, salto ACL scrittura: $($paths.MediaPrivate)" "WARN"
}

# ---------------------------------------------------------------------------
# 6. migrate
# ---------------------------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Log "[6/9] migrate..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -PyArgs   @("manage.py", "migrate", "--settings=$settingsMod", "--noinput") `
                    -EnvVars  $djangoEnv
        Write-Log "migrate completato." "SUCCESS"
    }
    catch {
        Write-Log "migrate fallito: $_" "ERROR"
        Write-Log "ATTENZIONE: il pacchetto e estratto ma il DB potrebbe essere inconsistente." "WARN"
        Remove-Item $releaseDir -Recurse -Force
        exit 1
    }

    # Verifica che non ci siano migration pendenti dopo il migrate
    Write-Log "  Verifica migration pendenti post-migrate..." "INFO"
    try {
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $showOutput = & "$($paths.Venv)\Scripts\python.exe" "$djangoApp\manage.py" showmigrations `
            --settings=$settingsMod --list 2>&1 | Out-String
        $ErrorActionPreference = $prevEAP
        $pendingLines = @(($showOutput -split "`n") | Where-Object { $_ -match "^\s+\[ \]" })
        if ($pendingLines.Count -gt 0) {
            Write-Log "ERRORE: $($pendingLines.Count) migration non applicate dopo il migrate:" "ERROR"
            $pendingLines | ForEach-Object { Write-Log "  $_" "ERROR" }
            Write-Log "Possibile causa: -SkipMigrate usato in deploy precedente o migration aggiunta senza deploy." "WARN"
            Remove-Item $releaseDir -Recurse -Force
            exit 1
        }
        Write-Log "  Tutte le migration applicate." "SUCCESS"
    }
    catch {
        Write-Log "  Verifica migration pendenti fallita (non bloccante): $_" "WARN"
    }
}
else {
    Write-Log "[6/9] migrate - SALTATO (flag -SkipMigrate)" "WARN"
    Write-Log "ATTENZIONE: saltare migrate puo lasciare tabelle mancanti. Verificare manualmente." "WARN"
}

# ---------------------------------------------------------------------------
# 7. Allinea schema legacy/runtime SQL Server
# ---------------------------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Log "[7/10] ensure_legacy_schema..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -PyArgs   @("manage.py", "ensure_legacy_schema", "--settings=$settingsMod") `
                    -EnvVars  $djangoEnv
        Write-Log "ensure_legacy_schema completato." "SUCCESS"
    }
    catch {
        Write-Log "ensure_legacy_schema fallito: $_" "ERROR"
        Write-Log "ATTENZIONE: il DB legacy/runtime potrebbe essere privo di tabelle operative richieste." "WARN"
        Remove-Item $releaseDir -Recurse -Force
        exit 1
    }
}
else {
    Write-Log "[7/10] ensure_legacy_schema - SALTATO (flag -SkipMigrate)" "WARN"
}

# ---------------------------------------------------------------------------
# 8. Applica trigger SQL Server
# ---------------------------------------------------------------------------
if (-not $SkipSqlTriggers) {
    Write-Log "[8/10] Applicazione trigger SQL Server..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -PyArgs   @("manage.py", "apply_sql_triggers", "--settings=$settingsMod") `
                    -EnvVars  $djangoEnv
        Write-Log "Trigger SQL applicati." "SUCCESS"
    }
    catch {
        Write-Log "apply_sql_triggers fallito: $_" "WARN"
        Write-Log "ATTENZIONE: i trigger SQL potrebbero non essere aggiornati. Verificare manualmente." "WARN"
        # Non bloccante: le migration Django sono gia passate, il trigger e solo un complemento
    }
}
else {
    Write-Log "[8/10] Trigger SQL - SALTATO (flag -SkipSqlTriggers)" "WARN"
}

# ---------------------------------------------------------------------------
# 9. allinea tipo_assenza assenze (idempotente, richiesto per DB legacy)
# ---------------------------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Log "[9/10] allinea assenze.tipo_assenza a Flessibilita..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -PyArgs   @("manage.py", "allinea_tipo_assenza_flessibilita", "--settings=$settingsMod") `
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
    Write-Log "[9/10] allinea tipo_assenza - SALTATO (flag -SkipMigrate)" "WARN"
}

# ---------------------------------------------------------------------------
# 10. createcachetable (idempotente, sicuro da rieseguire)
# ---------------------------------------------------------------------------
Write-Log "[10/12] createcachetable (idempotente)..." "STEP"
try {
    Invoke-Venv -VenvPath $paths.Venv `
                -WorkDir  $djangoApp `
                -PyArgs   @("manage.py", "createcachetable", "--settings=$settingsMod") `
                -EnvVars  $djangoEnv
    Write-Log "createcachetable completato." "SUCCESS"
}
catch {
    Write-Log "createcachetable fallito (non bloccante se la tabella esiste gia): $_" "WARN"
}

# ---------------------------------------------------------------------------
# 11. setup_q_schedules (idempotente): registra/aggiorna gli Schedule django-q2
#     dei background job (automation queue, approval mailbox, report scadenze,
#     notifiche anomalie, escalation OP da controllare). Va dopo migrate perche
#     usa le tabelle django-q. Idempotente: update_or_create per nome. Il
#     qcluster attivo raccoglie gli Schedule aggiornati al ciclo successivo.
# ---------------------------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Log "[11/12] setup_q_schedules (registrazione background job)..." "STEP"
    try {
        Invoke-Venv -VenvPath $paths.Venv `
                    -WorkDir  $djangoApp `
                    -PyArgs   @("manage.py", "setup_q_schedules", "--settings=$settingsMod") `
                    -EnvVars  $djangoEnv
        Write-Log "setup_q_schedules completato: schedule django-q allineati al codice della release." "SUCCESS"
    }
    catch {
        Write-Log "setup_q_schedules fallito (non bloccante): $_" "WARN"
        Write-Log "  Gli schedule django-q potrebbero non essere aggiornati. Registrali con:" "WARN"
        Write-Log "  manage.py setup_q_schedules --settings=$settingsMod" "WARN"
    }
}
else {
    Write-Log "[11/12] setup_q_schedules - SALTATO (flag -SkipMigrate)" "WARN"
    Write-Log "ATTENZIONE: i nuovi schedule django-q non sono registrati. Eseguire setup_q_schedules a mano." "WARN"
}

# ---------------------------------------------------------------------------
# Warmup modello AI (best-effort, NON bloccante): pre-carica subito il modello
# chat Ollama cosi' la prima richiesta utente non paga il cold start, senza
# attendere il primo tick dello schedule ai_warmup_ollama. Il command esce 0
# anche su errore (nessun -fail-on-error) -> non puo' mai far fallire il deploy;
# e' no-op se l'AI e' disabilitata o il provider e' Open WebUI. Timeout corto:
# se il modello e' freddo la chiamata avvia comunque il load lato Ollama e lo
# schedule lo completa al tick successivo.
# ---------------------------------------------------------------------------
Write-Log "Warmup modello AI (pre-caricamento Ollama)..." "STEP"
try {
    Invoke-Venv -VenvPath $paths.Venv `
                -WorkDir  $djangoApp `
                -PyArgs   @("manage.py", "warmup_ollama", "--json", "--timeout", "120", "--settings=$settingsMod") `
                -EnvVars  $djangoEnv
    Write-Log "Warmup AI eseguito (o saltato se AI disabilitata/Open WebUI)." "SUCCESS"
}
catch {
    Write-Log "Warmup AI non riuscito (non bloccante, il load prosegue lato Ollama): $_" "WARN"
}

# ---------------------------------------------------------------------------
# [12/12] Registra/aggiorna Task Scheduler automation queue (idempotente)
# ---------------------------------------------------------------------------
Write-Log "[12/12] Registrazione task poller automation queue..." "STEP"
$scheduleScript = "$PSScriptRoot\schedule-automation-queue.ps1"
if (Test-Path $scheduleScript) {
    try {
        & $scheduleScript -Environment $Environment -ErrorAction Stop
        Write-Log "Task poller automation queue registrato per $Environment." "SUCCESS"
    }
    catch {
        Write-Log "Task poller non registrato (non bloccante): $_" "WARN"
        Write-Log "  Per registrarlo manualmente: .\schedule-automation-queue.ps1 -Environment $Environment" "WARN"
    }
}
else {
    Write-Log "schedule-automation-queue.ps1 non trovato - task non registrato." "WARN"
}

# ---------------------------------------------------------------------------
# Registra/aggiorna helper riavvio IIS per portale (idempotente)
# ---------------------------------------------------------------------------
Write-Log "Registrazione helper riavvio IIS..." "STEP"
$sharedScriptsDir = Join-Path $DEPLOY_BASE "shared\scripts"
$releaseScriptsDir = Join-Path $releaseDir "deployment\scripts"
if (-not (Test-Path $sharedScriptsDir)) {
    New-Item -ItemType Directory -Path $sharedScriptsDir -Force | Out-Null
}
if (Test-Path $releaseScriptsDir) {
    foreach ($helperName in @("_lib.ps1", "register-iis-restart-helper.ps1", "restart-iis-env.ps1")) {
        $helperSource = Join-Path $releaseScriptsDir $helperName
        if (Test-Path $helperSource) {
            Copy-Item $helperSource (Join-Path $sharedScriptsDir $helperName) -Force
        }
    }
}
$restartHelperScript = Join-Path $sharedScriptsDir "register-iis-restart-helper.ps1"
if (-not (Test-Path $restartHelperScript)) {
    $restartHelperScript = "$PSScriptRoot\register-iis-restart-helper.ps1"
}
if (Test-Path $restartHelperScript) {
    try {
        & $restartHelperScript -Environment $Environment -ErrorAction Stop
        Write-Log "Helper riavvio IIS registrato per $Environment." "SUCCESS"
    }
    catch {
        Write-Log "Helper riavvio IIS non registrato (non bloccante): $_" "WARN"
        Write-Log "  Per registrarlo manualmente: .\register-iis-restart-helper.ps1 -Environment $Environment" "WARN"
    }
}
else {
    Write-Log "register-iis-restart-helper.ps1 non trovato - helper non registrato." "WARN"
}

# ---------------------------------------------------------------------------
# Salva marker release
# ---------------------------------------------------------------------------
$releaseInfo = @(
    "RELEASE_TAG=$releaseTag",
    "PACKAGE=$PackagePath",
    "DEPLOYED=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "ENVIRONMENT=$Environment"
) -join [Environment]::NewLine
$releaseInfoPath = Join-Path $releaseDir ".release_info"
$releaseInfo | Set-Content -Path $releaseInfoPath -Encoding UTF8

Write-LogSeparator
Write-Log "Deploy completato: $releaseTag" "SUCCESS"
Write-Log "" "INFO"

if ($AutoActivate) {
    Write-Log "AutoActivate attivo - avvio activate-release.ps1..." "STEP"
    & "$PSScriptRoot\activate-release.ps1" -Environment $Environment -ReleaseTag $releaseTag
}
else {
    $currentTargetAfterDeploy = Get-CurrentReleaseTarget -CurrentPath $paths.Current
    if ($currentTargetAfterDeploy -ne $releaseDir) {
        Write-Log "ATTENZIONE: il nuovo pacchetto e stato estratto ma NON e ancora attivo." "WARN"
        if ($currentTargetAfterDeploy) {
            Write-Log "  current punta ancora a: $currentTargetAfterDeploy" "WARN"
        } else {
            Write-Log "  current non punta ancora a nessuna release attiva." "WARN"
        }
        Write-Log "  release appena deployato: $releaseDir" "WARN"
    }
    Write-Log "Release pronto ma NON ancora attivo." "INFO"
    Write-Log "Per attivarlo:" "STEP"
    Write-Log "  .\activate-release.ps1 -Environment $Environment -ReleaseTag $releaseTag" "INFO"
    if ($Environment -eq "test") {
        Write-Log "Suggerimento: in TEST usa -AutoActivate per evitare di dimenticare lo switch del current." "WARN"
    }
    Write-Log "" "INFO"
    Write-Log "Per fare smoke test prima di attivare (opzionale):" "INFO"
    Write-Log "  .\smoke-test.ps1 -Environment $Environment  # testa l'ambiente corrente" "INFO"
}
Write-LogSeparator
