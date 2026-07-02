<#
.SYNOPSIS
  Check READ-ONLY pre-migrazione dati Formazione + Visite mediche DEV -> PROD.
  NON scrive nulla (nessuna conferma necessaria): produce un "fingerprint" JSON per
  ambiente e un verdetto di allineamento.

.DESCRIPTION
  Risponde alle due domande che decidono se un dumpdata/loaddata diretto e' sicuro:
    1) In PROD le tabelle Formazione+Visite sono vuote? (niente collisioni di PK)
    2) Gli ID dei CATALOGHI di base (mansioni/aree/ruoli/qualifiche/categorie/rischi)
       coincidono DEV<->PROD? (se lo stesso PK ha significato diverso, le FK dei record
       finirebbero sulla riga sbagliata -> corruzione silenziosa)

  Uso in 3 passi:
    # 1) su DEV (dove hai inserito i dati):
    .\tools\check_migra_formazione.ps1 -Mode Scan -Settings config.settings.dev  -Out check_dev.json
    # 2) su PROD (host app):
    .\tools\check_migra_formazione.ps1 -Mode Scan -Settings config.settings.prod -Out check_prod.json
    # 3) porta i due json nello stesso posto e confronta:
    .\tools\check_migra_formazione.ps1 -Mode Compare -DevJson check_dev.json -ProdJson check_prod.json

  -ManagePy: percorso a manage.py (autodetect se lanciato dalla root del repo o da tools\).
#>
[CmdletBinding()]
param(
  [ValidateSet('Scan','Compare')][string]$Mode = 'Scan',
  [string]$Settings = 'config.settings.dev',
  [string]$ManagePy = '',
  [string]$Out = 'check_formazione.json',
  [string]$DevJson = 'check_dev.json',
  [string]$ProdJson = 'check_prod.json'
)
$ErrorActionPreference = 'Stop'

function Resolve-ManagePy([string]$p) {
  if ($p) { return $p }
  foreach ($c in @('django_app\manage.py', 'manage.py', '..\django_app\manage.py')) {
    if (Test-Path $c) { return (Resolve-Path $c).Path }
  }
  throw "manage.py non trovato: passa -ManagePy <percorso completo>."
}

if ($Mode -eq 'Scan') {
  $mp = Resolve-ManagePy $ManagePy
  # Introspezione model-agnostica: tutte le tabelle Training* + le tre di Visite, e i
  # cataloghi di base con la loro etichetta str() per confrontare pk->significato.
  $py = @'
import os, sys, json
sys.path.insert(0, os.getcwd())
import django
django.setup()
from django.apps import apps
VISITE = {"TipoVisitaMedica", "VisitaMedica", "AnagraficaVisiteMedichePermission"}
CATALOG = ["RuoloOperativo","AreaAziendale","Mansione","TipoQualifica","CategoriaCorso","FattoreRischio"]
out = {"data_counts": {}, "catalogs": {}}
for m in apps.get_app_config("anagrafica").get_models():
    n = m.__name__
    if n.startswith("Training") or n in VISITE:
        try:
            out["data_counts"][n] = m.objects.count()
        except Exception as e:
            out["data_counts"][n] = "ERR:%s" % e
for n in CATALOG:
    try:
        M = apps.get_model("anagrafica", n)
        out["catalogs"][n] = {str(o.pk): str(o)[:100] for o in M.objects.all().order_by("pk")[:5000]}
    except Exception as e:
        out["catalogs"][n] = {"__error__": str(e)}
print("=== JSON START ===")
print(json.dumps(out, ensure_ascii=False))
print("=== JSON END ===")
'@
  Write-Host ("Scan ambiente [{0}] (read-only)..." -f $Settings) -ForegroundColor Cyan
  # Python STANDALONE con django.setup() (exec dell'INTERO file): 'manage.py shell' con
  # stdin usa una REPL riga-per-riga che si rompe sui blocchi indentati. Cwd = cartella
  # di manage.py cosi' 'config.settings.*' e le app sono importabili. I warning Django
  # vanno su stderr e non devono abortire: il check di riuscita sono i marker JSON.
  $djangoDir = Split-Path $mp
  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("scan_form_{0}.py" -f $PID)
  Set-Content -Path $tmp -Value $py -Encoding UTF8
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $prevDSM = $env:DJANGO_SETTINGS_MODULE
  Push-Location $djangoDir
  $env:DJANGO_SETTINGS_MODULE = $Settings
  $raw = (& python $tmp 2>&1 | Out-String)
  Pop-Location
  $env:DJANGO_SETTINGS_MODULE = $prevDSM
  $ErrorActionPreference = $prevEAP
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  $m = [regex]::Match($raw, '=== JSON START ===\s*(.+?)\s*=== JSON END ===', 'Singleline')
  if (-not $m.Success) { Write-Host $raw; throw "Output JSON non trovato (vedi sopra per l'errore Django)." }
  $json = $m.Groups[1].Value.Trim()
  Set-Content -Path $Out -Value $json -Encoding UTF8
  $data = $json | ConvertFrom-Json

  Write-Host "`n--- Conteggi tabelle Formazione + Visite ---" -ForegroundColor Yellow
  $tot = 0
  $data.data_counts.PSObject.Properties | Sort-Object Name | ForEach-Object {
    if ($_.Value -is [int]) { $tot += $_.Value }
    if ($_.Value -isnot [int] -or $_.Value -gt 0) { "{0,-40} {1}" -f $_.Name, $_.Value }
  }
  Write-Host ("Totale righe dati (non vuote sopra): {0}" -f $tot)
  Write-Host "`n--- Cataloghi di base (n. righe) ---" -ForegroundColor Yellow
  $data.catalogs.PSObject.Properties | Sort-Object Name | ForEach-Object {
    $cnt = ($_.Value.PSObject.Properties | Where-Object { $_.Name -ne '__error__' } | Measure-Object).Count
    "{0,-24} {1} righe" -f $_.Name, $cnt
  }
  Write-Host ("`nFingerprint salvato: {0}" -f (Resolve-Path $Out)) -ForegroundColor Green
  Write-Host "Copialo sull'altro ambiente e lancia -Mode Compare."
}
elseif ($Mode -eq 'Compare') {
  if (-not (Test-Path $DevJson))  { throw "Manca $DevJson (lancia lo Scan su dev)." }
  if (-not (Test-Path $ProdJson)) { throw "Manca $ProdJson (lancia lo Scan su prod)." }
  $dev  = Get-Content $DevJson  -Raw | ConvertFrom-Json
  $prod = Get-Content $ProdJson -Raw | ConvertFrom-Json

  Write-Host "===================== VERDETTO PRE-MIGRAZIONE =====================" -ForegroundColor Cyan

  # [1] Tabelle target in PROD devono essere vuote
  Write-Host "`n[1] Tabelle Formazione+Visite in PROD (attese ~vuote):" -ForegroundColor Yellow
  $prodNonEmpty = @()
  $prod.data_counts.PSObject.Properties | Sort-Object Name | ForEach-Object {
    if ($_.Value -is [int] -and $_.Value -gt 0) { $prodNonEmpty += ("{0}={1}" -f $_.Name, $_.Value) }
  }
  if ($prodNonEmpty.Count -eq 0) { Write-Host "  OK: tutte vuote." -ForegroundColor Green }
  else { Write-Host ("  ATTENZIONE, gia' popolate: " + ($prodNonEmpty -join ', ')) -ForegroundColor Red }

  # [2] Allineamento cataloghi: pericoloso solo il CONFLITTO (stesso pk, etichetta diversa)
  Write-Host "`n[2] Allineamento ID cataloghi DEV vs PROD:" -ForegroundColor Yellow
  $totConflict = 0
  foreach ($p in $dev.catalogs.PSObject.Properties) {
    $name = $p.Name; $dcat = $p.Value; $pcat = $prod.catalogs.$name
    $dc = ($dcat.PSObject.Properties | Where-Object { $_.Name -ne '__error__' } | Measure-Object).Count
    if ($null -eq $pcat) { Write-Host ("  ?  {0}: assente in prod (verra' migrato)" -f $name) -ForegroundColor DarkYellow; continue }
    $pc = ($pcat.PSObject.Properties | Where-Object { $_.Name -ne '__error__' } | Measure-Object).Count
    $conflict = 0; $prodMissing = 0; $examples = @()
    foreach ($row in $dcat.PSObject.Properties) {
      if ($row.Name -eq '__error__') { continue }
      $pk = $row.Name; $devLabel = $row.Value; $prodLabel = $pcat.$pk
      if ($null -eq $prodLabel) { $prodMissing++ }
      elseif ($prodLabel -ne $devLabel) { $conflict++; if ($examples.Count -lt 3) { $examples += ("pk={0}: dev='{1}' | prod='{2}'" -f $pk,$devLabel,$prodLabel) } }
    }
    $totConflict += $conflict
    if ($pc -eq 0) { Write-Host ("  ?  {0}: prod vuoto (dev={1}) -> verra' migrato" -f $name,$dc) -ForegroundColor DarkYellow }
    elseif ($conflict -eq 0) { Write-Host ("  OK {0}: dev={1} prod={2}, nessun conflitto (mancanti-in-prod={3})" -f $name,$dc,$pc,$prodMissing) -ForegroundColor Green }
    else {
      Write-Host ("  !! {0}: dev={1} prod={2}, CONFLITTI={3} (stesso ID, significato diverso)" -f $name,$dc,$pc,$conflict) -ForegroundColor Red
      $examples | ForEach-Object { Write-Host ("        " + $_) -ForegroundColor Red }
    }
  }

  Write-Host "`n========================= ESITO =========================" -ForegroundColor Cyan
  if ($prodNonEmpty.Count -eq 0 -and $totConflict -eq 0) {
    Write-Host "GO: prod vuote + nessun conflitto di catalogo -> dumpdata/loaddata diretto e' sicuro." -ForegroundColor Green
    Write-Host "    (i cataloghi 'assenti/vuoti in prod' verranno inclusi nel dump)."
  } else {
    Write-Host "STOP: serve gestione dedicata prima di caricare." -ForegroundColor Red
    if ($prodNonEmpty.Count) { Write-Host ("  - Prod non vuote: " + ($prodNonEmpty -join ', ')) -ForegroundColor Red }
    if ($totConflict)       { Write-Host ("  - {0} conflitti di catalogo (rimappatura FK per nome necessaria)." -f $totConflict) -ForegroundColor Red }
  }
}
