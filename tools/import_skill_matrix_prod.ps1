<#
.SYNOPSIS
  F2b - Import baseline Skill Matrix MOD.187 in produzione.
  Stage CSV in cartella temporanea -> dry-run -> conferma -> --apply -> cleanup.

.DESCRIPTION
  I 3 CSV seed contengono dati personali (nomi dipendenti) e NON sono nel
  repo/pacchetto di prod. Questo script li copia in una cartella temporanea
  fuori dal webroot, esegue il DRY-RUN dell'import, mostra il piano, chiede
  conferma esplicita, esegue --apply e infine CANCELLA i CSV temporanei.
  I CSV non restano mai sul server (cleanup garantito anche su errore/Ctrl-C).

.PARAMETER SourceDir
  Cartella che contiene i 3 CSV seed:
    skm_operatori.csv, skm_matrice_livelli.csv, skm_storico_delta.csv
  Puo' essere un percorso UNC (\\PCLBOVA\...) o locale.

.PARAMETER AppRoot
  Radice app prod (contiene django_app\manage.py). Default: C:\PortaleNovicrom\prod\current

.PARAMETER PythonExe
  Python del venv prod. Default: C:\PortaleNovicrom\prod\venv\Scripts\python.exe

.PARAMETER Settings
  Modulo settings Django. Default: config.settings.prod

.PARAMETER Baseline
  Snapshot baseline. Default: 2026-04-30

.EXAMPLE
  .\import_skill_matrix_prod.ps1 -SourceDir "\\PCLBOVA\Dev\Portale Novicrom\docs\anagrafica\skillmatrix"

.NOTES
  Da eseguire SUL SERVER DI PROD (pclogsys). Sola lettura fino al --apply.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir,

    [string]$AppRoot   = 'C:\PortaleNovicrom\prod\current',
    [string]$PythonExe = 'C:\PortaleNovicrom\prod\venv\Scripts\python.exe',
    [string]$Settings  = 'config.settings.prod',
    [string]$Baseline  = '2026-04-30'
)

$ErrorActionPreference = 'Stop'
$required = @('skm_operatori.csv', 'skm_matrice_livelli.csv', 'skm_storico_delta.csv')

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# --- 1) Validazioni preliminari -------------------------------------------------
Write-Step '1/5 Verifica prerequisiti'

if (-not (Test-Path $SourceDir)) {
    throw "SourceDir non trovata: $SourceDir"
}
$missing = $required | Where-Object { -not (Test-Path (Join-Path $SourceDir $_)) }
if ($missing) {
    throw "CSV mancanti in $SourceDir : $($missing -join ', ')"
}

$managePy = Join-Path $AppRoot 'django_app\manage.py'
if (-not (Test-Path $managePy)) {
    throw "manage.py non trovato: $managePy (controlla -AppRoot)"
}

if (-not (Test-Path $PythonExe)) {
    $fallback = Join-Path (Split-Path $AppRoot -Parent) 'venv\Scripts\python.exe'
    if (Test-Path $fallback) {
        $PythonExe = $fallback
    } else {
        Write-Host "Python venv non trovato, uso 'python' dal PATH." -ForegroundColor Yellow
        $PythonExe = 'python'
    }
}

Write-Host "Source   : $SourceDir"
Write-Host "AppRoot  : $AppRoot"
Write-Host "Python   : $PythonExe"
Write-Host "Settings : $Settings"
Write-Host "Baseline : $Baseline"

# --- 2) Staging in cartella temporanea -----------------------------------------
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stage = Join-Path $env:TEMP "skm_seed_$stamp"

try {
    Write-Step '2/5 Copia CSV in staging temporaneo'
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    foreach ($f in $required) {
        Copy-Item (Join-Path $SourceDir $f) (Join-Path $stage $f) -Force
    }
    Write-Host "Staging  : $stage"
    Write-Host "Copiati  : $($required -join ', ')"

    Push-Location $AppRoot
    try {
        # --- 3) DRY-RUN -----------------------------------------------------------
        Write-Step '3/5 DRY-RUN (nessuna scrittura)'
        & $PythonExe 'django_app\manage.py' import_skill_matrix `
            --base-dir $stage --baseline $Baseline --settings=$Settings
        if ($LASTEXITCODE -ne 0) {
            throw "Dry-run terminato con codice $LASTEXITCODE - import ANNULLATO."
        }

        # --- 4) Conferma esplicita -----------------------------------------------
        Write-Step '4/5 Conferma'
        Write-Host 'Rivedi il piano qui sopra (operatori risolti, macchine bloccate, coerenza storico).' -ForegroundColor Yellow
        $ans = Read-Host "Scrivi APPLICA per scrivere la baseline in PROD (qualsiasi altra cosa annulla)"
        if ($ans -ne 'APPLICA') {
            Write-Host 'Annullato dall''utente. Nessuna scrittura.' -ForegroundColor Yellow
            return
        }

        # --- 5) APPLY -------------------------------------------------------------
        Write-Step '5/5 APPLY (scrittura baseline)'
        & $PythonExe 'django_app\manage.py' import_skill_matrix `
            --base-dir $stage --baseline $Baseline --apply --settings=$Settings
        if ($LASTEXITCODE -ne 0) {
            throw "APPLY terminato con codice $LASTEXITCODE - verifica lo stato del DB."
        }
        Write-Host "`nFatto. Apri /anagrafica/skill-matrix/ per verificare la matrice." -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
finally {
    # --- Cleanup garantito: i CSV con dati personali non restano sul server -----
    if (Test-Path $stage) {
        Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Cleanup  : rimosso staging $stage" -ForegroundColor DarkGray
    }
}
