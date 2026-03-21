<#
.SYNOPSIS
    Rollback rapido al release precedente (o a un release specifico).

.DESCRIPTION
    - Se non specificato, usa il "previous_release.txt" salvato da activate-release.ps1
    - Altrimenti permette di scegliere qualsiasi release in releases\
    - Ferma app pool, aggiorna junction, riavvia, smoke test

.PARAMETER Environment
    Ambiente: "test" oppure "prod"

.PARAMETER ReleaseTag
    Tag specifico a cui tornare. Se omesso: usa il precedente salvato automaticamente.

.PARAMETER Force
    Salta la richiesta di conferma.

.EXAMPLE
    .\rollback-release.ps1 -Environment prod               # torna al precedente
    .\rollback-release.ps1 -Environment prod -ReleaseTag 20260320_120000
    .\rollback-release.ps1 -Environment test -Force
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [string]$ReleaseTag = "",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin
Assert-ValidEnvironment -Env $Environment

$paths       = Get-EnvPaths -Env $Environment
$appPoolName = "PortaleNovicrom-$($Environment.ToUpper())"

Write-LogSeparator
Write-Log "ROLLBACK — $($Environment.ToUpper())" "STEP"
Write-LogSeparator

# ---------------------------------------------------------------------------
# Determina release attuale
# ---------------------------------------------------------------------------
$currentTarget = Get-CurrentReleaseTarget -CurrentPath $paths.Current
Write-Log "Release attivo: $currentTarget" "INFO"

# ---------------------------------------------------------------------------
# Determina target rollback
# ---------------------------------------------------------------------------
$rollbackTarget = $null

if ($ReleaseTag) {
    $rollbackTarget = "$($paths.Releases)\$ReleaseTag"
    if (-not (Test-Path $rollbackTarget)) {
        Write-Log "Release specificato non trovato: $rollbackTarget" "ERROR"
        exit 1
    }
} else {
    # Tenta il file marker "previous"
    $previousPath = Get-PreviousRelease -RunDir $paths.Run
    if ($previousPath -and (Test-Path $previousPath)) {
        $rollbackTarget = $previousPath
        $rollbackTag    = Split-Path $rollbackTarget -Leaf
        Write-Log "Release precedente trovato (marker): $rollbackTag" "INFO"
    } else {
        # Fallback: secondo release più recente in releases\
        Write-Log "Marker 'previous_release.txt' non trovato — uso il penultimo release disponibile." "WARN"
        $allReleases = Get-ChildItem $paths.Releases -Directory -ErrorAction SilentlyContinue |
                       Sort-Object Name -Descending
        # Filtra il release corrente
        $candidates = $allReleases | Where-Object { $_.FullName -ne $currentTarget }
        if ($candidates.Count -eq 0) {
            Write-Log "Nessun release precedente trovato. Rollback impossibile." "ERROR"
            Write-Log "Releases disponibili:" "INFO"
            $allReleases | ForEach-Object { Write-Log "  - $($_.Name)" "INFO" }
            exit 1
        }
        $rollbackTarget = $candidates[0].FullName
        $rollbackTag    = $candidates[0].Name
        Write-Log "Rollback target (penultimo): $rollbackTag" "INFO"
    }
}

$rollbackTag = Split-Path $rollbackTarget -Leaf

# ---------------------------------------------------------------------------
# Mostra lista releases disponibili se rollback non ovvio
# ---------------------------------------------------------------------------
Write-Log "" "INFO"
Write-Log "Releases disponibili:" "INFO"
Get-ChildItem $paths.Releases -Directory | Sort-Object Name -Descending | ForEach-Object {
    $marker = if ($_.FullName -eq $currentTarget) { " [ATTIVO]" } else { "" }
    $marker2 = if ($_.FullName -eq $rollbackTarget) { " [TARGET ROLLBACK]" } else { "" }
    Write-Log "  $($_.Name)$marker$marker2" "INFO"
}
Write-Log "" "INFO"

# ---------------------------------------------------------------------------
# Conferma
# ---------------------------------------------------------------------------
if (-not $Force) {
    Write-Log "ROLLBACK:" "WARN"
    Write-Log "  Da:  $currentTarget" "WARN"
    Write-Log "  A:   $rollbackTarget" "WARN"
    Write-Log "" "INFO"
    $confirm = Read-Host "Confermi rollback? (s/N)"
    if ($confirm -notmatch "^[sS]$") {
        Write-Log "Rollback annullato." "WARN"
        exit 0
    }
}

# ---------------------------------------------------------------------------
# Esegui rollback (riutilizza activate-release.ps1)
# ---------------------------------------------------------------------------
Write-Log "Esecuzione rollback..." "STEP"
& "$PSScriptRoot\activate-release.ps1" `
    -Environment $Environment `
    -ReleaseTag $rollbackTag `
    -SkipConfirmProd

if ($LASTEXITCODE -ne 0) {
    Write-Log "Rollback fallito con exit code $LASTEXITCODE" "ERROR"
    exit 1
}

Write-LogSeparator
Write-Log "ROLLBACK COMPLETATO con successo!" "SUCCESS"
Write-Log "  Ambiente: $($Environment.ToUpper())" "INFO"
Write-Log "  Release:  $rollbackTag" "INFO"
Write-LogSeparator
