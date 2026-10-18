<#
.SYNOPSIS
    Dry-run delle migrazioni pendenti: genera l'SQL con `sqlmigrate` e segnala i
    costrutti che SQL Server rifiuta o che rompono la transazione. Non applica nulla.

.DESCRIPTION
    1. `showmigrations --plan` sul database indicato da -Settings (default
       config.settings.prod_readonly = DB di produzione in sola lettura) e filtro
       delle righe "[ ]" (migrazioni non applicate), nell'ordine di applicazione.
    2. Per ognuna `sqlmigrate <app> <numero>` -> deployment/dryrun/<data>/NNN_<app>_<migrazione>.sql
       (cartella ignorata da git: contiene SQL dello schema di produzione).
    3. Analisi dell'SQL generato:
       - indici filtrati con NOT/OR/LIKE nella clausola WHERE (SQL Server li rifiuta:
         errore 156, `migrate` fallisce e la release NON viene attivata);
         `IS NOT NULL` e' ammesso e non viene segnalato;
       - INSERT a batch (DECLARE @t TABLE / OUTPUT INSERTED) dentro un SAVE TRANSACTION:
         al primo scarto lascia result set pendenti e invalida l'intera transazione;
       - operazioni RunPython (non visibili in sqlmigrate): da rivedere a mano.
    Dettagli: docs/ai/06_TESTING_AND_QUALITY_GATES.md, sezione "Dry-run migrazioni".

    Nota tecnica: il profilo prod_readonly installa un router che nega ogni migrazione
    (allow_migrate=False), e con quel router `sqlmigrate` produrrebbe SQL vuoto. Lo
    script quindi esegue `sqlmigrate` in un processo Python in cui i router sono
    disattivati: `sqlmigrate` legge solo `django_migrations` e lo schema, non scrive
    nulla, e la barriera di sola lettura sulle query (execute_wrapper + grant
    db_datareader) resta attiva.

.PARAMETER Settings
    Modulo settings Django (default config.settings.prod_readonly).

.PARAMETER App
    Limita il dry-run a una o piu' app (etichette Django).

.PARAMETER OutRoot
    Cartella radice dell'output (default deployment/dryrun nel repo).

.PARAMETER RepoPath
    Checkout di cui verificare le migrazioni (default: quello che contiene lo
    script). Serve per controllare un altro branch, es. un worktree di release/prod.
    `.env.prod_readonly` si cerca nella radice di quel checkout; altrimenti
    impostare PROD_READONLY_ENV_FILE.

.EXAMPLE
    .\tools\migration_dryrun.ps1
    .\tools\migration_dryrun.ps1 -App anagrafica,assets
    .\tools\migration_dryrun.ps1 -Settings config.settings.dev
    .\tools\migration_dryrun.ps1 -RepoPath C:\Dev\pn-release -Python C:\Dev\Portale` Novicrom\.venv\Scripts\python.exe
#>
[CmdletBinding()]
param(
    [string]$Settings = "config.settings.prod_readonly",
    [string[]]$App = @(),
    [string]$OutRoot = "",
    [string]$Python = "",
    [string]$RepoPath = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$repoRoot = (git -C $RepoPath rev-parse --show-toplevel).Trim()
$djangoDir = Join-Path $repoRoot "django_app"

if (-not $Python) {
    $venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { "python" }
}
if (-not $OutRoot) { $OutRoot = Join-Path $repoRoot "deployment\dryrun" }
$outDir = Join-Path $OutRoot (Get-Date -Format "yyyy-MM-dd_HHmmss")

# --- 1. Piano delle migrazioni non applicate ---------------------------------
Write-Host "showmigrations --plan ($Settings)..." -ForegroundColor Cyan
Push-Location $djangoDir
try {
    $planOutput = & $Python manage.py showmigrations --plan --settings=$Settings 2>&1
    $planExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($planExit -ne 0) {
    $planOutput | ForEach-Object { Write-Host $_ }
    throw "showmigrations fallito (exit $planExit)."
}

$pending = New-Object System.Collections.Generic.List[object]
foreach ($line in $planOutput) {
    # Formato: "[ ]  app.0012_nome" (con -v2 compaiono anche le dipendenze: ignorate).
    if ("$line" -match '^\s*\[ \]\s+([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)') {
        $label = $Matches[1]; $name = $Matches[2]
        if ($App.Count -and $App -notcontains $label) { continue }
        $pending.Add([pscustomobject]@{ App = $label; Name = $name })
    }
}

if ($pending.Count -eq 0) {
    Write-Host "Nessuna migrazione pendente." -ForegroundColor Green
    exit 0
}
Write-Host "Migrazioni pendenti: $($pending.Count)"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

# --- 2. sqlmigrate in un unico processo (router disattivati, vedi .DESCRIPTION)
$listFile = Join-Path $outDir "_pending.json"
$i = 0
$jobs = foreach ($m in $pending) {
    $i++
    [pscustomobject]@{
        app  = $m.App
        name = $m.Name
        file = Join-Path $outDir ("{0:D3}_{1}_{2}.sql" -f $i, $m.App, $m.Name)
    }
}
ConvertTo-Json -InputObject @($jobs) -Depth 3 | Set-Content -LiteralPath $listFile -Encoding utf8

$helper = @'
import io, json, os, sys
sys.path.insert(0, os.getcwd())  # django_app/: lo script vive nella cartella di output
import django
from django.core.management import call_command
django.setup()
from django.db import router
router.routers = []  # il ReadOnlyRouter di prod_readonly svuoterebbe l'SQL
failed = 0
with open(sys.argv[1], encoding="utf-8-sig") as fh:
    jobs = json.load(fh)
for job in jobs:
    buf = io.StringIO()
    try:
        call_command("sqlmigrate", job["app"], job["name"], stdout=buf)
        text = buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - riportato nel file e nel riepilogo
        failed += 1
        text = f"-- ERRORE sqlmigrate: {exc!r}\n"
    with open(job["file"], "w", encoding="utf-8") as out:
        out.write(text)
    print(f"{job['app']}.{job['name']}")
sys.exit(1 if failed else 0)
'@
$helperFile = Join-Path $outDir "_sqlmigrate_helper.py"
Set-Content -LiteralPath $helperFile -Value $helper -Encoding utf8

Write-Host "sqlmigrate -> $outDir" -ForegroundColor Cyan
$prevSettings = $env:DJANGO_SETTINGS_MODULE
Push-Location $djangoDir
try {
    $env:DJANGO_SETTINGS_MODULE = $Settings
    & $Python $helperFile $listFile | ForEach-Object { Write-Host "  $_" }
    $sqlExit = $LASTEXITCODE
} finally {
    Pop-Location
    $env:DJANGO_SETTINGS_MODULE = $prevSettings
}
foreach ($tmp in @($helperFile, $listFile)) {
    try { [System.IO.File]::Delete($tmp) } catch { Write-Host "File temporaneo non rimosso: $tmp" }
}

# --- 3. Analisi dell'SQL generato --------------------------------------------
$findings = New-Object System.Collections.Generic.List[object]
function Add-Finding($job, [int]$lineNo, [string]$kind, [string]$text) {
    $findings.Add([pscustomobject]@{
        Migrazione = "$($job.app).$($job.name)"
        Riga       = $lineNo
        Tipo       = $kind
        Testo      = $text.Trim()
    })
}

foreach ($job in $jobs) {
    if (-not (Test-Path -LiteralPath $job.file)) { continue }
    $lines = @(Get-Content -LiteralPath $job.file -Encoding utf8)
    $inSavepoint = $false
    for ($n = 0; $n -lt $lines.Count; $n++) {
        $line = $lines[$n]
        $lineNo = $n + 1

        if ($line -match '^-- ERRORE sqlmigrate') { Add-Finding $job $lineNo "ERRORE" $line; continue }
        if ($line -match '(?i)^\s*--\s*Raw Python operation') {
            Add-Finding $job $lineNo "RunPython (rivedere a mano)" $line
        }

        # Indice filtrato: CREATE [UNIQUE] [NONCLUSTERED] INDEX ... WHERE <predicato>
        if ($line -match '(?i)\bCREATE\s+(UNIQUE\s+)?((NON)?CLUSTERED\s+)?INDEX\b.*\bWHERE\b(?<pred>.*)$') {
            $pred = $Matches['pred'] -replace '(?i)\bIS\s+NOT\s+NULL\b', ''
            if ($pred -match '(?i)\bNOT\b') { Add-Finding $job $lineNo "Indice filtrato con NOT" $line }
            if ($pred -match '(?i)\bOR\b') { Add-Finding $job $lineNo "Indice filtrato con OR" $line }
            if ($pred -match '(?i)\bLIKE\b') { Add-Finding $job $lineNo "Indice filtrato con LIKE" $line }
        }

        if ($line -match '(?i)\bSAVE\s+TRAN(SACTION)?\b') { $inSavepoint = $true; continue }
        if ($line -match '(?i)\b(ROLLBACK|COMMIT)\s+TRAN(SACTION)?\b') { $inSavepoint = $false; continue }
        if ($inSavepoint -and $line -match '(?i)(\bDECLARE\s+@\w+\s+TABLE\b|\bOUTPUT\s+INSERTED\.)') {
            Add-Finding $job $lineNo "INSERT a batch dentro savepoint" $line
        }
    }
}

# --- Riepilogo ----------------------------------------------------------------
$reportFile = Join-Path $outDir "_report.txt"
$critical = @($findings | Where-Object { $_.Tipo -notlike "RunPython*" })
$report = @(
    "Dry-run migrazioni - $(Get-Date -Format 'yyyy-MM-dd HH:mm') - settings $Settings"
    "Migrazioni pendenti: $($pending.Count)"
    "Segnalazioni bloccanti: $($critical.Count)  (RunPython da rivedere: $($findings.Count - $critical.Count))"
    ""
)
$report += ($findings | Format-Table -AutoSize -Wrap | Out-String -Width 220)
$report | Set-Content -LiteralPath $reportFile -Encoding utf8
$report | ForEach-Object { Write-Host $_ }
Write-Host "SQL e report in: $outDir" -ForegroundColor Cyan

if ($sqlExit -ne 0 -or $critical.Count -gt 0) { exit 1 }
exit 0
