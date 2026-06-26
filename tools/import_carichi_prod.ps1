<#
.SYNOPSIS
  Import carichi macchina in produzione (cumulativo da una o piu' edizioni del foglio).
  Stage .xlsx in cartella temporanea -> dry-run -> conferma -> import -> cleanup.

.DESCRIPTION
  I file "Carichi macchina*.xlsx" contengono nomi clienti/pezzi reali e NON stanno nel
  repo/pacchetto di prod. Questo script li copia in una cartella temporanea fuori dal
  webroot, esegue il DRY-RUN dell'import (che stampa il report: codici mappati/non
  mappati, periodo, pianificazioni), mostra il piano, chiede conferma esplicita, esegue
  l'import e infine CANCELLA i file temporanei (cleanup garantito anche su errore/Ctrl-C).

  Con piu' edizioni l'import e' CUMULATIVO: l'edizione piu' recente (per data reale degli
  snapshot) e' il piano vivo, le piu' vecchie arricchiscono solo lo storico
  (affinita'/recency/pool). L'ordine dei file NON conta: la recency e' calcolata dalle
  date reali nei fogli.

.PARAMETER SourceDir
  Cartella che contiene i file .xlsx delle edizioni del foglio. Puo' essere UNC o locale.

.PARAMETER Pattern
  Filtro dei file da importare dentro SourceDir. Default: 'Carichi macchina*.xlsx'

.PARAMETER AppRoot
  Radice app prod (contiene django_app\manage.py). Default: C:\PortaleNovicrom\prod\current

.PARAMETER PythonExe
  Python del venv prod. Default: C:\PortaleNovicrom\prod\venv\Scripts\python.exe

.PARAMETER Settings
  Modulo settings Django. Default: config.settings.prod

.EXAMPLE
  .\import_carichi_prod.ps1 -SourceDir "\\PCLBOVA\Dev\Portale Novicrom"

.NOTES
  Da eseguire SUL SERVER DI PROD (pclogsys). Sola lettura fino alla conferma APPLICA.
  I codici-macchina non mappati vanno risolti a mano via MacchinaAlias (vedi report).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir,

    [string]$Pattern   = 'Carichi macchina*.xlsx',
    [string]$AppRoot   = 'C:\PortaleNovicrom\prod\current',
    [string]$PythonExe = 'C:\PortaleNovicrom\prod\venv\Scripts\python.exe',
    [string]$Settings  = 'config.settings.prod'
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# --- 1) Validazioni preliminari -------------------------------------------------
Write-Step '1/5 Verifica prerequisiti'

if (-not (Test-Path $SourceDir)) {
    throw "SourceDir non trovata: $SourceDir"
}
$files = @(Get-ChildItem -Path $SourceDir -Filter $Pattern -File | Sort-Object Name)
if ($files.Count -eq 0) {
    throw "Nessun file '$Pattern' in $SourceDir"
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
Write-Host "Edizioni : $($files.Count)"
$files | ForEach-Object { Write-Host "  - $($_.Name)" }

# --- 2) Staging in cartella temporanea -----------------------------------------
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stage = Join-Path $env:TEMP "carichi_xlsx_$stamp"

try {
    Write-Step '2/5 Copia .xlsx in staging temporaneo'
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    $staged = @()
    foreach ($f in $files) {
        $dst = Join-Path $stage $f.Name
        Copy-Item $f.FullName $dst -Force
        $staged += $dst
    }
    Write-Host "Staging  : $stage"

    Push-Location $AppRoot
    try {
        # --- 3) DRY-RUN -----------------------------------------------------------
        Write-Step '3/5 DRY-RUN (nessuna scrittura)'
        & $PythonExe 'django_app\manage.py' import_carichi @staged --dry-run --settings=$Settings
        if ($LASTEXITCODE -ne 0) {
            throw "Dry-run terminato con codice $LASTEXITCODE - import ANNULLATO."
        }

        # --- 4) Conferma esplicita -----------------------------------------------
        Write-Step '4/5 Conferma'
        Write-Host 'Rivedi il report qui sopra (macchine mappate, CODICI NON MAPPATI, periodo, pianificazioni).' -ForegroundColor Yellow
        Write-Host 'I codici-macchina veri non mappati andranno agganciati a mano (MacchinaAlias).' -ForegroundColor Yellow
        $ans = Read-Host "Scrivi APPLICA per scrivere in PROD (qualsiasi altra cosa annulla)"
        if ($ans -ne 'APPLICA') {
            Write-Host 'Annullato dall''utente. Nessuna scrittura.' -ForegroundColor Yellow
            return
        }

        # --- 5) IMPORT ------------------------------------------------------------
        Write-Step '5/5 IMPORT (scrittura)'
        & $PythonExe 'django_app\manage.py' import_carichi @staged --settings=$Settings
        if ($LASTEXITCODE -ne 0) {
            throw "Import terminato con codice $LASTEXITCODE - verifica lo stato del DB."
        }
        Write-Host "`nFatto. Apri /carichi-macchina/ per verificare la vista Excel e il Gantt." -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
finally {
    # --- Cleanup garantito: i file con dati reali non restano sul server ---------
    if (Test-Path $stage) {
        Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Cleanup  : rimosso staging $stage" -ForegroundColor DarkGray
    }
}
