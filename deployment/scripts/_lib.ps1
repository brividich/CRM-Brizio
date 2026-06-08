# _lib.ps1 - Libreria condivisa per tutti gli script di deployment Portale Novicrom
# Da includere con: . "$PSScriptRoot\_lib.ps1"
# Non eseguire direttamente.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configurazione globale
# ---------------------------------------------------------------------------
$DEPLOY_BASE   = "C:\PortaleNovicrom"
$VALID_ENVS    = @("test", "prod")
$KEEP_RELEASES = 5   # quanti release tenere in releases\ (il resto viene eliminato)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO","WARN","ERROR","SUCCESS","STEP")]
        [string]$Level = "INFO"
    )
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $colors = @{
        INFO    = "Cyan"
        WARN    = "Yellow"
        ERROR   = "Red"
        SUCCESS = "Green"
        STEP    = "Magenta"
    }
    Write-Host "[$ts] [$Level] $Message" -ForegroundColor $colors[$Level]
}

function Write-LogSeparator { Write-Host ("=" * 72) -ForegroundColor DarkGray }

# ---------------------------------------------------------------------------
# Verifica privilegi amministrativi
# ---------------------------------------------------------------------------
function Assert-Admin {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Log "Questo script richiede privilegi di amministratore." "ERROR"
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Validazione ambiente
# ---------------------------------------------------------------------------
function Assert-ValidEnvironment {
    param([string]$Env)
    if ($Env -notin $VALID_ENVS) {
        Write-Log "Ambiente non valido: '$Env'. Valori ammessi: $($VALID_ENVS -join ', ')" "ERROR"
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Percorsi standard per un ambiente
# ---------------------------------------------------------------------------
function Get-EnvPaths {
    param([string]$Env)
    $base = "$DEPLOY_BASE\$Env"
    return @{
        Base     = $base
        Current  = "$base\current"
        Releases = "$base\releases"
        Logs     = "$base\logs"
        Config   = "$base\config"
        Static   = "$base\static"
        Media        = "$base\media"
        MediaPrivate = "$base\media_private"
        Run      = "$base\run"
        Venv     = "$base\venv"
        DjangoApp = "$base\current\django_app"
    }
}

# ---------------------------------------------------------------------------
# Legge il target del junction "current" (= release attiva)
# ---------------------------------------------------------------------------
function Get-CurrentReleaseTarget {
    param([string]$CurrentPath)
    if (-not (Test-Path $CurrentPath)) { return $null }
    $item = Get-Item $CurrentPath -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    # Per un junction, Target restituisce il percorso reale
    return $item.Target
}

# ---------------------------------------------------------------------------
# Imposta/aggiorna il junction "current" verso un release
# ---------------------------------------------------------------------------
function Set-CurrentJunction {
    param(
        [string]$JunctionPath,
        [string]$TargetPath
    )
    if (-not (Test-Path $TargetPath -PathType Container)) {
        Write-Log "Target release non trovata: $TargetPath" "ERROR"
        exit 1
    }
    # Rimuove junction esistente senza cancellare il contenuto
    if (Test-Path $JunctionPath) {
        Write-Log "Rimozione junction esistente: $JunctionPath" "INFO"
        cmd /c "rmdir `"$JunctionPath`"" | Out-Null
    }
    New-Item -ItemType Junction -Path $JunctionPath -Target $TargetPath | Out-Null
    Write-Log "Junction aggiornata: $JunctionPath -> $TargetPath" "SUCCESS"
}

# ---------------------------------------------------------------------------
# Salva il release precedente in un file marker (per rollback rapido)
# ---------------------------------------------------------------------------
function Save-PreviousRelease {
    param([string]$RunDir, [string]$CurrentTarget)
    if ($CurrentTarget) {
        $markerFile = "$RunDir\previous_release.txt"
        $CurrentTarget | Set-Content -Path $markerFile -Encoding UTF8
        Write-Log "Release precedente salvata in: $markerFile" "INFO"
    }
}

function Get-PreviousRelease {
    param([string]$RunDir)
    $markerFile = "$RunDir\previous_release.txt"
    if (Test-Path $markerFile) {
        return (Get-Content $markerFile -Raw).Trim()
    }
    return $null
}

# ---------------------------------------------------------------------------
# IIS: recycle application pool
# ---------------------------------------------------------------------------
function Invoke-IISRecycle {
    param([string]$AppPoolName)
    Write-Log "Recycle IIS App Pool: $AppPoolName" "STEP"
    try {
        Import-Module WebAdministration -ErrorAction Stop
        $pool = Get-WebConfigurationProperty -Filter "system.applicationHost/applicationPools/add[@name='$AppPoolName']" -Name "." -ErrorAction Stop
        if ($null -eq $pool) {
            Write-Log "App pool '$AppPoolName' non trovato in IIS." "WARN"
            return
        }
        $state = (Get-WebAppPoolState -Name $AppPoolName).Value
        if ($state -eq "Started") {
            Restart-WebAppPool -Name $AppPoolName
            Write-Log "App pool '$AppPoolName' riciclato." "SUCCESS"
        } else {
            Start-WebAppPool -Name $AppPoolName
            Write-Log "App pool '$AppPoolName' avviato." "SUCCESS"
        }
    } catch {
        Write-Log "Errore IIS recycle: $_" "WARN"
    }
}

function Stop-IISAppPool {
    param([string]$AppPoolName)
    try {
        Import-Module WebAdministration -ErrorAction Stop
        $state = (Get-WebAppPoolState -Name $AppPoolName -ErrorAction SilentlyContinue).Value
        if ($state -eq "Started") {
            Stop-WebAppPool -Name $AppPoolName
            Start-Sleep -Seconds 2
            Write-Log "App pool '$AppPoolName' fermato." "INFO"
        }
    } catch {
        Write-Log "Impossibile fermare app pool '$AppPoolName': $_" "WARN"
    }
}

function Start-IISAppPool {
    param(
        [string]$AppPoolName,
        [int]$MaxRetries = 6,
        [int]$RetryDelaySeconds = 3
    )
    try {
        Import-Module WebAdministration -ErrorAction Stop
    } catch {
        Write-Log "Impossibile caricare WebAdministration: $_" "WARN"
        return
    }
    # Lo stato 'Stopping'/transizione dopo uno stop fa fallire Start-WebAppPool con
    # HRESULT 0x80070425 ("Il servizio non puo accettare messaggi di controllo in
    # questo momento."). Ritentiamo finche' lo stato diventa 'Started'.
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        $state = (Get-WebAppPoolState -Name $AppPoolName -ErrorAction SilentlyContinue).Value
        if ($state -eq "Started") {
            Write-Log "App pool '$AppPoolName' avviato." "SUCCESS"
            return
        }
        try {
            Start-WebAppPool -Name $AppPoolName -ErrorAction Stop
            Start-Sleep -Seconds 2
            $state = (Get-WebAppPoolState -Name $AppPoolName -ErrorAction SilentlyContinue).Value
            if ($state -eq "Started") {
                Write-Log "App pool '$AppPoolName' avviato." "SUCCESS"
                return
            }
        } catch {
            Write-Log "Avvio app pool '$AppPoolName' tentativo $attempt/$MaxRetries non riuscito: $_" "WARN"
        }
        Start-Sleep -Seconds $RetryDelaySeconds
    }
    Write-Log "Impossibile avviare app pool '$AppPoolName' dopo $MaxRetries tentativi." "WARN"
}

# ---------------------------------------------------------------------------
# Pulizia release vecchi (mantiene $KEEP_RELEASES più recenti)
# ---------------------------------------------------------------------------
function Remove-OldReleases {
    param([string]$ReleasesDir, [string]$CurrentTarget)
    if (-not (Test-Path $ReleasesDir)) { return }
    $releases = Get-ChildItem $ReleasesDir -Directory | Sort-Object Name -Descending
    $toDelete  = $releases | Select-Object -Skip $KEEP_RELEASES
    foreach ($r in $toDelete) {
        if ($r.FullName -eq $CurrentTarget) {
            Write-Log "Skipping release attiva: $($r.FullName)" "WARN"
            continue
        }
        Write-Log "Eliminazione release vecchia: $($r.FullName)" "INFO"
        Remove-Item $r.FullName -Recurse -Force
    }
}

# ---------------------------------------------------------------------------
# Esegue comando Python nel contesto del venv
# ---------------------------------------------------------------------------
function Invoke-Venv {
    param(
        [string]$VenvPath,
        [string]$WorkDir,
        [string[]]$PyArgs,
        [hashtable]$EnvVars = @{}
    )
    $pythonExe = "$VenvPath\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        Write-Log "Python non trovato nel venv: $pythonExe" "ERROR"
        exit 1
    }
    $origDir = $PWD
    Set-Location $WorkDir
    try {
        $env_backup = @{}
        foreach ($kv in $EnvVars.GetEnumerator()) {
            $env_backup[$kv.Key] = [System.Environment]::GetEnvironmentVariable($kv.Key)
            [System.Environment]::SetEnvironmentVariable($kv.Key, $kv.Value)
        }
        # I comandi Django scrivono spesso warning su stderr (deprecazioni, migrate):
        # sotto ErrorActionPreference=Stop PowerShell potrebbe promuoverli a errore
        # terminante. Ci affidiamo a $LASTEXITCODE come unico indicatore di esito.
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $pythonExe @PyArgs
        $pyExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP
        if ($pyExit -ne 0) {
            Write-Log "Comando Python fallito con exit code $pyExit" "ERROR"
            throw "Python command failed"
        }
    } finally {
        Set-Location $origDir
        foreach ($kv in $env_backup.GetEnumerator()) {
            [System.Environment]::SetEnvironmentVariable($kv.Key, $kv.Value)
        }
    }
}
