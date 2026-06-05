<#
.SYNOPSIS
    Attiva un release specifico sull'ambiente (aggiorna il junction "current").

.DESCRIPTION
    - Salva il release attivo come "previous" (per rollback)
    - Ferma l'app pool IIS
    - Aggiorna il junction current -> releases\ReleaseTag
    - Riavvia l'app pool IIS
    - Esegue smoke test automatico
    - In caso di fallimento smoke test: rollback automatico

.PARAMETER Environment
    Ambiente: "test" oppure "prod"

.PARAMETER ReleaseTag
    Tag del release (nome cartella in releases\), es. "20260321_143000"
    Se omesso: usa l'ultimo release disponibile in releases\

.PARAMETER SkipSmokeTest
    Salta il smoke test post-attivazione. Non raccomandato per PROD.

.PARAMETER SkipConfirmProd
    Salta la richiesta di conferma per PROD. Utile per automazione.

.EXAMPLE
    .\activate-release.ps1 -Environment test -ReleaseTag 20260321_143000
    .\activate-release.ps1 -Environment prod -ReleaseTag 20260321_143000
    .\activate-release.ps1 -Environment test   # usa l'ultimo release disponibile
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [string]$ReleaseTag = "",

    [switch]$SkipSmokeTest,
    [switch]$SkipConfirmProd
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin
Assert-ValidEnvironment -Env $Environment

$paths       = Get-EnvPaths -Env $Environment
$appPoolName = "PortaleNovicrom-$($Environment.ToUpper())"

# ---------------------------------------------------------------------------
# Risolvi ReleaseTag
# ---------------------------------------------------------------------------
if (-not $ReleaseTag) {
    $latest = Get-ChildItem $paths.Releases -Directory -ErrorAction SilentlyContinue |
              Sort-Object Name -Descending |
              Select-Object -First 1
    if (-not $latest) {
        Write-Log "Nessun release trovato in: $($paths.Releases)" "ERROR"
        exit 1
    }
    $ReleaseTag = $latest.Name
    Write-Log "Nessun ReleaseTag specificato - uso l'ultimo: $ReleaseTag" "INFO"
}

$targetDir = "$($paths.Releases)\$ReleaseTag"
if (-not (Test-Path $targetDir)) {
    Write-Log "Release non trovato: $targetDir" "ERROR"
    exit 1
}

Write-LogSeparator
Write-Log "ATTIVAZIONE RELEASE - $($Environment.ToUpper())" "STEP"
Write-Log "Release:    $ReleaseTag" "INFO"
Write-Log "Target:     $targetDir" "INFO"
Write-LogSeparator

# ---------------------------------------------------------------------------
# Conferma per PROD
# ---------------------------------------------------------------------------
if ($Environment -eq "prod" -and -not $SkipConfirmProd) {
    $currentTarget = Get-CurrentReleaseTarget -CurrentPath $paths.Current
    Write-Log "" "INFO"
    Write-Log "ATTENZIONE: stai per attivare in PRODUZIONE!" "WARN"
    Write-Log "  Release attuale: $currentTarget" "WARN"
    Write-Log "  Nuovo release:   $targetDir" "WARN"
    Write-Log "" "INFO"
    $confirm = Read-Host "Confermi? (digita 'SI' per procedere)"
    if ($confirm -ne "SI") {
        Write-Log "Operazione annullata dall'utente." "WARN"
        exit 0
    }
}

# ---------------------------------------------------------------------------
# Salva release corrente come "previous" (per rollback)
# ---------------------------------------------------------------------------
$currentTarget = Get-CurrentReleaseTarget -CurrentPath $paths.Current
if ($currentTarget -and $currentTarget -ne $targetDir) {
    Save-PreviousRelease -RunDir $paths.Run -CurrentTarget $currentTarget
    Write-Log "Release precedente salvato: $currentTarget" "INFO"
}

# ---------------------------------------------------------------------------
# Stop app pool
# ---------------------------------------------------------------------------
Write-Log "Stop app pool: $appPoolName" "STEP"
Stop-IISAppPool -AppPoolName $appPoolName
Start-Sleep -Seconds 2   # breve attesa per terminare richieste in corso

# ---------------------------------------------------------------------------
# Aggiorna junction current
# ---------------------------------------------------------------------------
Write-Log "Aggiornamento junction current..." "STEP"
try {
    Set-CurrentJunction -JunctionPath $paths.Current -TargetPath $targetDir
} catch {
    Write-Log "Errore aggiornamento junction: $_" "ERROR"
    Write-Log "Ripristino app pool..." "WARN"
    Start-IISAppPool -AppPoolName $appPoolName
    exit 1
}

# ---------------------------------------------------------------------------
# Avvia app pool
# ---------------------------------------------------------------------------
Write-Log "Avvio app pool: $appPoolName" "STEP"
Start-IISAppPool -AppPoolName $appPoolName
Start-Sleep -Seconds 15  # attesa avvio processo Python/waitress (waitress impiega alcuni secondi)

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if (-not $SkipSmokeTest) {
    Write-Log "Smoke test post-attivazione..." "STEP"
    $baseUrl = if ($Environment -eq "prod") { "http://localhost:80" } else { "http://localhost:8080" }
    try {
        & "$PSScriptRoot\smoke-test.ps1" -Environment $Environment -BaseUrl $baseUrl -Quiet
        if ($LASTEXITCODE -ne 0) { throw "Smoke test fallito" }
        Write-Log "Smoke test PASSATO." "SUCCESS"
    } catch {
        Write-Log "Smoke test FALLITO: $_" "ERROR"
        Write-Log "AVVIO ROLLBACK AUTOMATICO..." "WARN"
        if ($currentTarget) {
            Set-CurrentJunction -JunctionPath $paths.Current -TargetPath $currentTarget
            Invoke-IISRecycle -AppPoolName $appPoolName
            Write-Log "Rollback completato - ripristinato: $currentTarget" "WARN"
        }
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Pulizia release vecchi
# ---------------------------------------------------------------------------
Write-Log "Pulizia release obsoleti (mantiene gli ultimi $KEEP_RELEASES)..." "INFO"
Remove-OldReleases -ReleasesDir $paths.Releases -CurrentTarget $targetDir

# ---------------------------------------------------------------------------
# Riepilogo
# ---------------------------------------------------------------------------
Write-LogSeparator
Write-Log "Release ATTIVATO con successo!" "SUCCESS"
Write-Log "  Ambiente:  $($Environment.ToUpper())" "INFO"
Write-Log "  Release:   $ReleaseTag" "INFO"
Write-Log "  Current:   $($paths.Current) -> $targetDir" "INFO"
Write-Log "" "INFO"
Write-Log "Per rollback rapido:" "INFO"
Write-Log "  .\rollback-release.ps1 -Environment $Environment" "INFO"
Write-LogSeparator
