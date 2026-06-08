<#
.SYNOPSIS
    Configura il sito IIS e l'application pool per un ambiente Portale Novicrom.

.DESCRIPTION
    - Crea l'application pool (No Managed Code)
    - Crea il sito IIS con physical path sull'ambiente
    - Crea virtual directories /static/ e /media/
    - Copia il web.config template nella root del sito
    - Imposta i permessi NTFS per l'account IIS AppPool

.PARAMETER Environment
    Ambiente: "test" oppure "prod"

.PARAMETER Port
    Porta HTTP del sito. Default: 8080 (test), 80 (prod)

.PARAMETER Hostname
    Hostname binding IIS (es. portale.azienda.local). Default: vuoto (risponde su tutte le IP)

.PARAMETER WebConfigTemplate
    Percorso al web.config template. Default: ..\config\web.config.httpplatform.template

.EXAMPLE
    .\configure-iis-site.ps1 -Environment test -Port 8080
    .\configure-iis-site.ps1 -Environment prod -Port 80 -Hostname "portale.cnovicrom.local"
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [int]$Port = 0,   # 0 = auto (8080 per test, 80 per prod)

    [string]$Hostname = "",

    [string]$WebConfigTemplate = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin

# Default port
if ($Port -eq 0) {
    $Port = if ($Environment -eq "prod") { 80 } else { 8080 }
}

# Default template
if (-not $WebConfigTemplate) {
    $WebConfigTemplate = "$PSScriptRoot\..\config\web.config.httpplatform.template"
}

$paths       = Get-EnvPaths -Env $Environment
$siteName    = "PortaleNovicrom-$($Environment.ToUpper())"
$appPoolName = "PortaleNovicrom-$($Environment.ToUpper())"
$siteRoot    = $paths.Base          # C:\PortaleNovicrom\test (o prod)
$binding     = if ($Hostname) { "${Hostname}:${Port}:" } else { "*:${Port}:" }

Write-LogSeparator
Write-Log "CONFIGURAZIONE IIS - $siteName (porta $Port)" "STEP"
Write-LogSeparator

Import-Module WebAdministration -ErrorAction Stop

# ---------------------------------------------------------------------------
# Application Pool
# ---------------------------------------------------------------------------
Write-Log "Configurazione Application Pool: $appPoolName" "STEP"
if (Test-Path -LiteralPath "IIS:\AppPools\$appPoolName") {
    Write-Log "App pool gia esistente - aggiornamento configurazione..." "WARN"
}
else {
    New-WebAppPool -Name $appPoolName | Out-Null
    Write-Log "App pool creato: $appPoolName" "SUCCESS"
}

Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name "managedRuntimeVersion" -Value ""          # No Managed Code
Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name "managedPipelineMode"    -Value "Integrated"
Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name "startMode"              -Value "AlwaysRunning"
Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name "autoStart"              -Value $true
Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name "processModel.idleTimeout" -Value ([TimeSpan]::Zero)
Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name "recycling.periodicRestart.time" -Value ([TimeSpan]::Zero)
# Restart giornaliero alle 3:00 di notte
$recycleTime = [Microsoft.Web.Administration.ConfigurationElement]@{}
$appPool = Get-Item "IIS:\AppPools\$appPoolName"
Write-Log "App pool configurato (No Managed Code, AlwaysRunning)." "SUCCESS"

# ---------------------------------------------------------------------------
# Sito IIS
# ---------------------------------------------------------------------------
Write-Log "Configurazione sito IIS: $siteName" "STEP"

if (Test-Path -LiteralPath "IIS:\Sites\$siteName") {
    Write-Log "Sito gia esistente - verifica configurazione..." "WARN"
    Set-ItemProperty "IIS:\Sites\$siteName" -Name "physicalPath" -Value $siteRoot
}
else {
    New-Website -Name $siteName `
                -PhysicalPath $siteRoot `
                -ApplicationPool $appPoolName `
                -Port $Port `
                -HostHeader $Hostname `
                -Force | Out-Null
    Write-Log "Sito creato: $siteName -> $siteRoot" "SUCCESS"
}

# Associa app pool al sito
Set-ItemProperty "IIS:\Sites\$siteName" -Name "applicationPool" -Value $appPoolName
Write-Log "App pool '$appPoolName' associato al sito." "SUCCESS"

# ---------------------------------------------------------------------------
# Virtual Directories: /static/ e /media/
# ---------------------------------------------------------------------------
Write-Log "Configurazione virtual directories..." "STEP"

# Assicura che le cartelle esistano
foreach ($vdir in @($paths.Static, $paths.Media, $paths.MediaPrivate)) {
    if (-not (Test-Path -LiteralPath $vdir)) {
        New-Item -ItemType Directory -Path $vdir -Force | Out-Null
    }
}

# Virtual directory /static/
$staticVdirPath = "IIS:\Sites\$siteName\static"
if (-not (Test-Path -LiteralPath $staticVdirPath)) {
    New-WebVirtualDirectory -Site $siteName -Name "static" -PhysicalPath $paths.Static | Out-Null
    Write-Log "Virtual directory /static/ -> $($paths.Static)" "SUCCESS"
}
else {
    Set-ItemProperty $staticVdirPath -Name "physicalPath" -Value $paths.Static
    Write-Log "Virtual directory /static/ aggiornata." "INFO"
}

# Virtual directory /media/
$mediaVdirPath = "IIS:\Sites\$siteName\media"
if (-not (Test-Path -LiteralPath $mediaVdirPath)) {
    New-WebVirtualDirectory -Site $siteName -Name "media" -PhysicalPath $paths.Media | Out-Null
    Write-Log "Virtual directory /media/ -> $($paths.Media)" "SUCCESS"
}
else {
    Set-ItemProperty $mediaVdirPath -Name "physicalPath" -Value $paths.Media
    Write-Log "Virtual directory /media/ aggiornata." "INFO"
}

# ---------------------------------------------------------------------------
# web.config dal template
# ---------------------------------------------------------------------------
Write-Log "Installazione web.config..." "STEP"
$webConfigDest = "$siteRoot\web.config"
if (Test-Path -LiteralPath $WebConfigTemplate) {
    $content = Get-Content $WebConfigTemplate -Raw -Encoding UTF8
    # Sostituisce segnaposto ENVIRONMENT nel template
    $content = $content -replace "%%ENVIRONMENT%%",  $Environment
    $content = $content -replace "%%ENV_PATH%%",     $siteRoot
    $content = $content -replace "%%VENV_PATH%%",    $paths.Venv
    $content = $content -replace "%%LOGS_PATH%%",    $paths.Logs
    # test usa config.settings.prod: l'ambiente IIS TEST deve girare con SQL Server
    # e le stesse impostazioni del profilo prod, NON il profilo SQLite/dev del test runner.
    $settingsMap = @{
        "test" = "config.settings.prod"
        "prod" = "config.settings.prod"
    }
    if (-not $settingsMap.ContainsKey($Environment)) {
        throw "Ambiente '$Environment' non ha un mapping settings configurato in configure-iis-site.ps1."
    }
    $content = $content -replace "%%SETTINGS_MOD%%", $settingsMap[$Environment]
    $content = $content -replace "%%DJANGO_APP%%",   "$siteRoot\current\django_app"

    $content | Set-Content $webConfigDest -Encoding UTF8
    Write-Log "web.config scritto in: $webConfigDest" "SUCCESS"
}
else {
    Write-Log "Template web.config non trovato: $WebConfigTemplate" "WARN"
    Write-Log "Crea manualmente web.config in: $webConfigDest" "WARN"
}

# ---------------------------------------------------------------------------
# Permessi NTFS per IIS AppPool identity
# ---------------------------------------------------------------------------
Write-Log "Impostazione permessi NTFS..." "STEP"
$iisUser = "IIS AppPool\$appPoolName"
$acls = @(
    @{ Path = $siteRoot;             Rights = "ReadAndExecute" },
    @{ Path = $paths.Static;         Rights = "ReadAndExecute" },
    @{ Path = $paths.Media;          Rights = "Modify" },
    @{ Path = $paths.MediaPrivate;   Rights = "Modify" },
    @{ Path = $paths.Logs;           Rights = "Modify" },
    @{ Path = $paths.Run;            Rights = "Modify" },
    @{ Path = $paths.Config;         Rights = "Read" }
)
foreach ($acl in $acls) {
    try {
        $aclObj = Get-Acl $acl.Path
        $rule   = New-Object System.Security.AccessControl.FileSystemAccessRule(
                      $iisUser, $acl.Rights, "ContainerInherit,ObjectInherit", "None", "Allow")
        $aclObj.SetAccessRule($rule)
        Set-Acl -Path $acl.Path -AclObject $aclObj
        Write-Log "  $($acl.Rights) -> $($acl.Path)" "INFO"
    } catch {
        Write-Log "  Permesso non impostato per $($acl.Path): $_" "WARN"
    }
}

$secureEnvScript = Join-Path $PSScriptRoot "secure-env-acl.ps1"
if (Test-Path $secureEnvScript) {
    try {
        & $secureEnvScript -Environment $Environment -Quiet
        Write-Log "ACL .env ristrette." "SUCCESS"
    } catch {
        Write-Log "Hardening ACL .env non completato: $_" "WARN"
    }
}

# ---------------------------------------------------------------------------
# Task Scheduler helper per riavvio IIS dal portale
# ---------------------------------------------------------------------------
Write-Log "Registrazione helper riavvio IIS per Crea Release..." "STEP"
$restartHelperScript = "$PSScriptRoot\register-iis-restart-helper.ps1"
if (Test-Path $restartHelperScript) {
    try {
        & $restartHelperScript -Environment $Environment -ErrorAction Stop
        Write-Log "Helper riavvio IIS registrato per $Environment." "SUCCESS"
    } catch {
        Write-Log "Helper riavvio IIS non registrato (non bloccante): $_" "WARN"
        Write-Log "  Per registrarlo manualmente: .\register-iis-restart-helper.ps1 -Environment $Environment" "WARN"
    }
} else {
    Write-Log "register-iis-restart-helper.ps1 non trovato - helper non registrato." "WARN"
}

# ---------------------------------------------------------------------------
# Avvia sito
# ---------------------------------------------------------------------------
Write-Log "Avvio sito IIS..." "STEP"
Start-Website -Name $siteName -ErrorAction SilentlyContinue
Start-WebAppPool -Name $appPoolName -ErrorAction SilentlyContinue

Write-LogSeparator
Write-Log "Configurazione IIS completata." "SUCCESS"
Write-Log "" "INFO"
Write-Log "Sito:       $siteName" "INFO"
Write-Log "URL:        http://$(if ($Hostname) { $Hostname } else { 'localhost' }):$Port/" "INFO"
Write-Log "Root:       $siteRoot" "INFO"
Write-Log "App Pool:   $appPoolName" "INFO"
Write-Log "Static:     $($paths.Static)" "INFO"
Write-Log "Media:      $($paths.Media)" "INFO"
Write-Log "MediaPriv:  $($paths.MediaPrivate) (solo AppPool, non servita da IIS)" "INFO"
Write-Log "" "INFO"
Write-Log "PROSSIMO: .\deploy-release.ps1 -Environment $Environment -PackagePath <zip>" "STEP"
Write-LogSeparator
