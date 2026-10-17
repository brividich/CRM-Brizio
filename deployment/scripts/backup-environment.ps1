<#
.SYNOPSIS
    Backup di un ambiente prima di un deploy critico.

.DESCRIPTION
    Esegue backup di:
    - config\.env
    - media\ (file utente)
    - Database SQL Server (via sqlcmd - opzionale)
    - Lista pacchetti pip installati (pip freeze)
    - Info sul release attivo

    Il backup viene salvato in:
    C:\PortaleNovicrom\shared\backups\ENVIRONMENT-YYYYMMDD_HHmmss\

.PARAMETER Environment
    Ambiente: "test" oppure "prod"

.PARAMETER IncludeMedia
    Include il backup della directory media\. Può essere voluminoso.
    Default: $true

.PARAMETER IncludeDatabase
    Tenta backup SQL Server via sqlcmd. Richiede sqlcmd sul PATH
    e permessi adeguati sul DB. Default: $false

.PARAMETER SqlServerName
    Nome server SQL (usato solo se -IncludeDatabase). Default: letto da .env

.PARAMETER DatabaseName
    Nome database (usato solo se -IncludeDatabase). Default: letto da .env

.PARAMETER UseHubBackup
    Delega a "manage.py hub_backup --type all" (backup verificato con manifest, file
    incrementali, fotografia della macchina). Default: $true. Con $false si usa il
    percorso storico (copia di media e, con -IncludeDatabase, BACKUP DATABASE).

.NOTES
    Audit M10: il .env completo NON viene copiato nel backup dati (solo i NOMI delle
    variabili in config\env_keys.txt). Se il .env dichiara BACKUP_ENV_DIR, la copia
    completa va li', in una destinazione separata.

.EXAMPLE
    .\backup-environment.ps1 -Environment prod
    .\backup-environment.ps1 -Environment prod -IncludeDatabase -SqlServerName "SQL01"
    .\backup-environment.ps1 -Environment test -IncludeMedia:$false
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [bool]$IncludeMedia = $true,
    [switch]$IncludeDatabase,
    [string]$SqlServerName  = "",
    [string]$DatabaseName   = "",
    [bool]$UseHubBackup     = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin
Assert-ValidEnvironment -Env $Environment

$paths      = Get-EnvPaths -Env $Environment
$timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = "$DEPLOY_BASE\shared\backups\$Environment-$timestamp"

Write-LogSeparator
Write-Log "BACKUP - $($Environment.ToUpper())" "STEP"
Write-Log "Destinazione: $backupRoot" "INFO"
Write-LogSeparator

New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$logFile = "$backupRoot\backup.log"
"Backup avviato: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Set-Content $logFile

function Log-BackupStep { param([string]$msg) Write-Log $msg "INFO"; $msg | Add-Content $logFile }

# ---------------------------------------------------------------------------
# 1. Config files
# ---------------------------------------------------------------------------
Log-BackupStep "[1] Backup config..."
$configBackup = "$backupRoot\config"
New-Item -ItemType Directory -Path $configBackup -Force | Out-Null

# Audit M10: nel backup dati solo i NOMI delle variabili; il .env completo solo in BACKUP_ENV_DIR.
$envSrc = "$($paths.Config)\.env"
if (Test-Path $envSrc) {
    $envLines = Get-Content $envSrc
    $envLines | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } |
        ForEach-Object { ($_ -split '=', 2)[0].Trim() } | Set-Content "$configBackup\env_keys.txt" -Encoding UTF8
    Log-BackupStep "  Nomi delle variabili .env -> config\env_keys.txt (valori esclusi)"
    $envDir = ""
    foreach ($line in $envLines) { if ($line -match '^\s*BACKUP_ENV_DIR\s*=\s*(.+)$') { $envDir = $Matches[1].Trim().Trim('"') } }
    if ($envDir) {
        $dest = Join-Path $envDir "$Environment\$timestamp"
        try {
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Copy-Item $envSrc (Join-Path $dest ".env") -Force
            Log-BackupStep "  .env completo copiato nella destinazione separata BACKUP_ENV_DIR"
        } catch {
            Log-BackupStep "  Copia .env in BACKUP_ENV_DIR fallita: $_"
        }
    } else {
        Log-BackupStep "  BACKUP_ENV_DIR non configurata: .env completo NON copiato (custodirlo nel Recovery Kit)"
    }
} else {
    Log-BackupStep "  Non trovato (non critico): $envSrc"
}

# ---------------------------------------------------------------------------
# 2. Info release attivo
# ---------------------------------------------------------------------------
Log-BackupStep "[2] Salvataggio info release..."
$currentTarget = Get-CurrentReleaseTarget -CurrentPath $paths.Current
@"
BACKUP_TIMESTAMP=$timestamp
ENVIRONMENT=$Environment
CURRENT_RELEASE=$currentTarget
BACKUP_DATE=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
"@ | Set-Content "$backupRoot\backup_info.txt" -Encoding UTF8
Log-BackupStep "  Release attivo: $currentTarget"

# ---------------------------------------------------------------------------
# 3. pip freeze
# ---------------------------------------------------------------------------
Log-BackupStep "[3] pip freeze..."
$pipFreezeFile = "$backupRoot\pip_freeze.txt"
try {
    & "$($paths.Venv)\Scripts\python.exe" -m pip freeze 2>&1 | Set-Content $pipFreezeFile -Encoding UTF8
    Log-BackupStep "  pip freeze salvato in: $pipFreezeFile"
} catch {
    Log-BackupStep "  pip freeze fallito: $_"
}

# ---------------------------------------------------------------------------
# 4. Motore di backup verificabile (default)
# ---------------------------------------------------------------------------
if ($UseHubBackup) {
    Log-BackupStep "[4] hub_backup --type all (DB verificato, file incrementali, macchina)..."
    $settingsModule = "config.settings.prod"
    try {
        Invoke-Venv -VenvPath $paths.Venv -WorkDir $paths.DjangoApp -PyArgs @("manage.py", "hub_backup", "--type", "all", "--env", $Environment, "--no-exit-code", "--settings=$settingsModule")
        Log-BackupStep "  hub_backup completato: esito e set in <BACKUP_TARGET>\$Environment\status.json"
    } catch {
        Log-BackupStep "  hub_backup fallito: $_"
    }
    $IncludeMedia = $false
    $IncludeDatabase = $false
}

# ---------------------------------------------------------------------------
# 4b. Media (percorso storico, solo con -UseHubBackup:$false)
# ---------------------------------------------------------------------------
if ($IncludeMedia) {
    Log-BackupStep "[4] Backup media..."
    $mediaBackup = "$backupRoot\media"
    if (Test-Path $paths.Media) {
        try {
            # Usa robocopy per velocità (meglio di Copy-Item su cartelle grandi)
            & robocopy $paths.Media $mediaBackup /E /NFL /NDL /NJH /NJS | Out-Null
            if ($LASTEXITCODE -le 7) {
                Log-BackupStep "  Media backup completato."
            } else {
                Log-BackupStep "  Media backup con errori (exit code $LASTEXITCODE)."
            }
        } catch {
            Log-BackupStep "  Media backup fallito: $_"
        }
    } else {
        Log-BackupStep "  Directory media non trovata: $($paths.Media)"
    }
} else {
    Log-BackupStep "[4] Media backup SALTATO (IncludeMedia=false)"
}

# ---------------------------------------------------------------------------
# 5. Database SQL Server (opzionale)
# ---------------------------------------------------------------------------
if ($IncludeDatabase) {
    Log-BackupStep "[5] Backup database SQL Server..."

    # Tenta di leggere i parametri dal .env se non specificati
    if (-not $SqlServerName -or -not $DatabaseName) {
        $envContent = Get-Content "$($paths.Config)\.env" -ErrorAction SilentlyContinue
        foreach ($line in $envContent) {
            if ($line -match "^DB_HOST\s*=\s*(.+)$")     { if (-not $SqlServerName)  { $SqlServerName  = $Matches[1].Trim() } }
            if ($line -match "^DB_NAME\s*=\s*(.+)$")     { if (-not $DatabaseName)   { $DatabaseName   = $Matches[1].Trim() } }
        }
    }

    if (-not $SqlServerName -or -not $DatabaseName) {
        Log-BackupStep "  SQL Server non configurato - skip. Specifica -SqlServerName e -DatabaseName."
    } else {
        $bakFile = "$backupRoot\${DatabaseName}_$timestamp.bak"
        $sqlCmd = @"
BACKUP DATABASE [$DatabaseName]
TO DISK = N'$bakFile'
WITH FORMAT, INIT, SKIP, STATS=10;
"@
        try {
            $sqlCmdPath = Get-Command sqlcmd -ErrorAction SilentlyContinue
            if ($sqlCmdPath) {
                & sqlcmd -S $SqlServerName -E -Q $sqlCmd 2>&1 | Tee-Object -FilePath "$backupRoot\db_backup.log"
                if ($LASTEXITCODE -eq 0) {
                    Log-BackupStep "  DB backup completato: $bakFile"
                } else {
                    Log-BackupStep "  DB backup fallito (exit code $LASTEXITCODE). Vedi db_backup.log."
                }
            } else {
                Log-BackupStep "  sqlcmd non trovato nel PATH - skip DB backup."
            }
        } catch {
            Log-BackupStep "  DB backup errore: $_"
        }
    }
} else {
    Log-BackupStep "[5] Database backup SALTATO (usa -IncludeDatabase per abilitarlo)"
}

# ---------------------------------------------------------------------------
# 6. Zip del backup (opzionale, solo per config - non per media che può essere enorme)
# ---------------------------------------------------------------------------
Log-BackupStep "[6] Compressione config backup..."
$zipPath = "$DEPLOY_BASE\shared\backups\$Environment-$timestamp-config.zip"
try {
    Compress-Archive -Path "$configBackup\*","$backupRoot\backup_info.txt","$backupRoot\pip_freeze.txt" `
                     -DestinationPath $zipPath -CompressionLevel Fastest
    Log-BackupStep "  Config backup zippato: $zipPath"
} catch {
    Log-BackupStep "  Zip config fallito (non critico): $_"
}

# ---------------------------------------------------------------------------
# Pulizia backup vecchi (mantiene ultimi 10)
# ---------------------------------------------------------------------------
$allBackups = Get-ChildItem "$DEPLOY_BASE\shared\backups" -Directory -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -like "$Environment-*" } |
              Sort-Object Name -Descending
$oldBackups = $allBackups | Select-Object -Skip 10
foreach ($old in $oldBackups) {
    Remove-Item $old.FullName -Recurse -Force
    Write-Log "  Eliminato backup vecchio: $($old.Name)" "INFO"
}

# ---------------------------------------------------------------------------
# Fine
# ---------------------------------------------------------------------------
"Backup completato: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Add-Content $logFile

Write-LogSeparator
Write-Log "BACKUP completato." "SUCCESS"
Write-Log "  Directory: $backupRoot" "INFO"
Write-Log "  Config zip: $zipPath" "INFO"
Write-LogSeparator
