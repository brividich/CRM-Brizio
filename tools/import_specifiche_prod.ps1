# =============================================================================
#  import_specifiche_prod.ps1  --  Import GUIDATO delle Specifiche (F8)
# -----------------------------------------------------------------------------
#  Pipeline completa con guardrail:
#    1) CONVERTE i listoni del gestionale nei CSV template
#         (OK SPTE .xls  -> specifiche_spte.csv + allegati_spte.csv)
#         (MOD.097 .xlsx -> specifiche_cliente.csv)
#    2) IMPORT dry-run (validazione, nessuna scrittura)
#    3) IMPORT --apply    (solo con -Apply, previa conferma)
#    4) ALLEGATI  -> di DEFAULT: COLLEGAMENTO alla share (percorso_esterno):
#         il PDF resta sul master aziendale (single source of truth, protetto da
#         Adobe) e il portale lo serve on-demand. Con -Copia invece si copia il
#         PDF nello storage privato cifrato.
#
#  DRY-RUN DI DEFAULT: senza -Apply converte e VALIDA soltanto (0 scritture).
#  Idempotente e ri-eseguibile.
#
#  NB: eseguilo sul SERVER giusto (DB prod raggiungibile) e, per il passo 4, su
#      una macchina che VEDE la share \\novisrv\... (al portale serve solo LETTURA).
#      Tieni file .xls/.xlsx/CSV FUORI dal repo (dati reali).
#
#  ESEMPI (da C:\PortaleNovicrom\prod\current\django_app, oppure passa -ManagePy):
#    # anteprima (converte + valida, non scrive)
#    powershell -ExecutionPolicy Bypass -File tools\import_specifiche_prod.ps1 `
#        -SpteXls "C:\PortaleNovicrom\import\OK SPTE AL 25-6-26.xls" `
#        -ClienteXlsx "C:\PortaleNovicrom\import\MOD.097 - SPE - Specifiche Cliente.xlsx"
#    # esecuzione reale (con conferme): import + collegamento allegati
#    powershell -ExecutionPolicy Bypass -File tools\import_specifiche_prod.ps1 `
#        -SpteXls "...OK SPTE....xls" -ClienteXlsx "...MOD.097....xlsx" -Apply
# =============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$SpteXls,
    [Parameter(Mandatory = $true)] [string]$ClienteXlsx,
    [string]$OutDir  = "C:\PortaleNovicrom\import\csv",
    [string]$Settings = "config.settings.prod",
    [string]$Python  = "python",
    [string]$ManagePy = "",
    [switch]$Apply,          # senza questo flag: solo conversione + dry-run
    [switch]$Copia,          # passo 4: COPIA nello storage cifrato invece del collegamento
    [switch]$SkipAttach,     # salta del tutto il passo 4 (allegati)
    [switch]$IncludiFvali,   # NON escludere le SPTE con fvali (default: escluse)
    [switch]$Yes             # niente conferme (esecuzioni non presidiate); NON scavalca il gate share
)

$ErrorActionPreference = "Stop"
# Forza Python in UTF-8: la console di prod e' spesso cp1252 e l'output dei comandi
# (che puo' contenere caratteri non-ASCII) andrebbe in UnicodeEncodeError.
$env:PYTHONUTF8 = "1"

function Write-Step([string]$Titolo) {
    Write-Host ""
    Write-Host ("=" * 74) -ForegroundColor Cyan
    Write-Host "  $Titolo" -ForegroundColor Cyan
    Write-Host ("=" * 74) -ForegroundColor Cyan
}

function Invoke-Manage {
    # "python manage.py <args>" con args come ARRAY (quoting sicuro per path con spazi);
    # ferma su exit-code != 0.
    param([Parameter(Mandatory = $true)][string[]]$MArgs)
    Write-Host ("> {0} {1} {2}" -f $Python, (Split-Path $script:ManagePyPath -Leaf), ($MArgs -join " ")) -ForegroundColor DarkGray
    & $Python $script:ManagePyPath @MArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Comando fallito (exit $LASTEXITCODE): manage.py $($MArgs -join ' ')"
    }
}

function Confirm-Step([string]$Domanda) {
    if ($Yes) { return $true }
    $r = Read-Host "$Domanda  [scrivi SI (maiuscolo) per procedere]"
    return ($r -ceq "SI")   # case-SENSITIVE: solo esattamente 'SI' procede
}

# --- preflight --------------------------------------------------------------
Write-Step "PREFLIGHT"

if ([string]::IsNullOrWhiteSpace($ManagePy)) {
    $candidati = @(
        (Join-Path (Get-Location) "manage.py"),
        (Join-Path (Get-Location) "django_app\manage.py"),
        (Join-Path $PSScriptRoot "..\django_app\manage.py")
    )
    $ManagePy = $candidati | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($ManagePy) -or -not (Test-Path $ManagePy)) {
    throw "manage.py non trovato. Lancia lo script da .\django_app oppure passa -ManagePy <percorso>."
}
$script:ManagePyPath = (Resolve-Path $ManagePy).Path

if (-not (Test-Path -LiteralPath $SpteXls))     { throw "File SPTE non trovato: $SpteXls" }
if (-not (Test-Path -LiteralPath $ClienteXlsx)) { throw "File Cliente non trovato: $ClienteXlsx" }
if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path

$csvSpte     = Join-Path $OutDir "specifiche_spte.csv"
$csvCliente  = Join-Path $OutDir "specifiche_cliente.csv"
$csvAllegati = Join-Path $OutDir "allegati_spte.csv"

$modo = if ($Apply) { "APPLY (scrittura reale)" } else { "DRY-RUN (nessuna scrittura)" }
Write-Host "  manage.py : $script:ManagePyPath"
Write-Host "  settings  : $Settings"
Write-Host "  SPTE .xls : $SpteXls"
Write-Host "  Cliente   : $ClienteXlsx"
Write-Host "  Output    : $OutDir"
Write-Host "  Passo 4   : " -NoNewline; Write-Host $(if ($Copia) { "COPIA nello storage cifrato" } else { "COLLEGAMENTO alla share" }) -ForegroundColor Yellow
Write-Host "  Modalita' : $modo" -ForegroundColor Yellow
if ($Apply -and $Yes) {
    Write-Host "  ATTENZIONE: -Apply -Yes -> scritture su $Settings SENZA conferme interattive." -ForegroundColor Red
}

# --- 1) conversione ---------------------------------------------------------
Write-Step "1/4  CONVERSIONE listoni -> CSV (sola lettura, non tocca il DB)"
$convArgs = @("converti_export_gestionale",
    "--spte", $SpteXls, "--cliente", $ClienteXlsx, "--out", $OutDir, "--settings=$Settings")
if ($IncludiFvali) { $convArgs += "--includi-fvali" }
Invoke-Manage $convArgs
Write-Host "  CSV generati in $OutDir" -ForegroundColor Green

# --- 2) import dry-run ------------------------------------------------------
Write-Step "2/4  IMPORT dry-run (validazione, nessuna scrittura)"
Invoke-Manage @("import_specifiche_storico", $csvSpte,    "--settings=$Settings")
Invoke-Manage @("import_specifiche_storico", $csvCliente, "--settings=$Settings")

if (-not $Apply) {
    Write-Step "FINE (dry-run)"
    Write-Host "  Anteprima completata. Nessuna scrittura effettuata." -ForegroundColor Green
    Write-Host "  NB: gli allegati (passo 4) NON sono stati validati: la verifica dei PDF" -ForegroundColor Yellow
    Write-Host "      richiede le Specifiche gia' importate e avviene solo dopo -Apply." -ForegroundColor Yellow
    Write-Host "  Verifica i conteggi qui sopra, poi rilancia con -Apply." -ForegroundColor Yellow
    return
}

# --- 3) import --apply ------------------------------------------------------
Write-Step "3/4  IMPORT --apply (scrittura sul DB $Settings)"
if (-not (Confirm-Step "Confermi l'import REALE delle specifiche su $Settings?")) {
    throw "Import annullato dall'operatore."
}
Invoke-Manage @("import_specifiche_storico", $csvSpte,    "--apply", "--settings=$Settings")
Invoke-Manage @("import_specifiche_storico", $csvCliente, "--apply", "--settings=$Settings")
Write-Host "  Import specifiche completato." -ForegroundColor Green

# --- 4) allegati (collegamento share di default; copia con -Copia) ----------
if ($SkipAttach) {
    Write-Step "4/4  ALLEGATI  (SALTATO per -SkipAttach)"
    return
}
$attachCmd   = if ($Copia) { "allega_pdf_da_share" } else { "collega_pdf_da_share" }
$attachLabel = if ($Copia) { "COPIA nello storage cifrato" } else { "COLLEGAMENTO alla share" }
Write-Step "4/4  ALLEGATI  ($attachLabel)"

if (-not (Test-Path -LiteralPath $csvAllegati)) {
    Write-Host "  Mappa allegati assente ($csvAllegati): salto il passo allegati." -ForegroundColor Yellow
    return
}

# Raggiungibilita' share: campiona i PRIMI record (un singolo path storto non deve far
# fallire tutto). Se NESSUNO dei campioni esiste, la share e' verosimilmente irraggiungibile
# da qui: salto (evita una run 'a vuoto'). Questo gate NON e' scavalcato da -Yes.
$cmdRun = "$Python `"$script:ManagePyPath`" $attachCmd `"$csvAllegati`" --apply --settings=$Settings"
$sample = Import-Csv -LiteralPath $csvAllegati -Delimiter ";" | Select-Object -First 8
$raggiungibile = $false
foreach ($r in $sample) {
    if ($r.path -and (Test-Path -LiteralPath $r.path)) { $raggiungibile = $true; break }
}
if (-not $raggiungibile) {
    Write-Host "  Share non raggiungibile: nessuno dei primi file esiste da questa macchina." -ForegroundColor Red
    if ($sample.Count -gt 0) { Write-Host "  Es.: $($sample[0].path)" -ForegroundColor Red }
    Write-Host "  Salto gli allegati (le specifiche restano importate). Da una macchina che vede la share:" -ForegroundColor Yellow
    Write-Host "    $cmdRun" -ForegroundColor Yellow
    return
}

# dry-run allegati (ora le Specifiche esistono: mostra quanti PDF verrebbero collegati/copiati)
Invoke-Manage @($attachCmd, $csvAllegati, "--settings=$Settings")
if (-not (Confirm-Step "Confermi il passo allegati REALE ($attachLabel)?")) {
    Write-Host "  Allegati annullati: le specifiche restano importate senza allegati. Piu' tardi:" -ForegroundColor Yellow
    Write-Host "    $cmdRun" -ForegroundColor Yellow
    return
}
Invoke-Manage @($attachCmd, $csvAllegati, "--apply", "--settings=$Settings")

Write-Step "FINE"
Write-Host "  Import + allegati ($attachLabel) completati su $Settings." -ForegroundColor Green
