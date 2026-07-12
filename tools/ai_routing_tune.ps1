<#
.SYNOPSIS
    Ritaratura del routing semantico dei tool AI: misura e propone la soglia migliore.

.DESCRIPTION
    Esegue il comando `ai_routing_probe` su una serie di SOGLIE candidate e riepiloga,
    per ciascuna, quante sonde attivano il dominio atteso. Consiglia la soglia PIU' ALTA
    che tiene tutte le sonde OK (massima precisione a parita' di recall) e stampa le
    righe da incollare in `config\.env`.

    DA ESEGUIRE IN PROD, dove gli embeddings (TEI/Ollama) sono live: offline il probe
    degrada a keyword-only e non c'e' nulla da misurare (lo script lo rileva e si ferma).
    Read-only: non scrive nulla, non tocca il `.env` (usa override --threshold per-run).

.PARAMETER Thresholds
    Soglie candidate da provare (default: 0.70 0.66 0.62 0.58 0.54).

.PARAMETER Settings
    Modulo settings Django (default: config.settings.prod).

.PARAMETER TopK
    Override opzionale di TOP_K applicato a TUTTE le prove.

.PARAMETER Margin
    Override opzionale di MARGIN applicato a TUTTE le prove.

.EXAMPLE
    .\tools\ai_routing_tune.ps1
.EXAMPLE
    .\tools\ai_routing_tune.ps1 -Thresholds 0.72,0.68,0.64 -TopK 3
#>
[CmdletBinding()]
param(
    [double[]] $Thresholds = @(0.70, 0.66, 0.62, 0.58, 0.54),
    [string]   $Settings   = "config.settings.prod",
    [int]      $TopK,
    [double]   $Margin
)

$ErrorActionPreference = "Stop"

# --- Risoluzione percorsi (script in tools\, repo root = parent) --------------
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ManagePy = Join-Path $RepoRoot "django_app\manage.py"
$PyVenv   = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $PyVenv) { $PyVenv } else { "python" }

if (-not (Test-Path $ManagePy)) {
    Write-Error "manage.py non trovato in $ManagePy. Esegui lo script dalla radice del repo."
    exit 1
}

Write-Host "== Ritaratura routing semantico tool AI ==" -ForegroundColor Cyan
Write-Host "Python:   $PythonExe"
Write-Host "Settings: $Settings"
Write-Host "Soglie:   $($Thresholds -join ', ')"
Write-Host ""

# Argomenti comuni (margin/top-k applicati a tutte le prove, se passati).
$commonArgs = @("--settings=$Settings")
if ($PSBoundParameters.ContainsKey('TopK'))   { $commonArgs += @("--top-k", "$TopK") }
if ($PSBoundParameters.ContainsKey('Margin')) { $commonArgs += @("--margin", "$Margin") }

function Invoke-Probe([double]$Threshold) {
    & $PythonExe $ManagePy ai_routing_probe @commonArgs --threshold $Threshold 2>&1 | Out-String
}

# --- Prova la prima soglia per verificare che gli embeddings siano live -------
$first = Invoke-Probe $Thresholds[0]
if ($first -match "keyword-only" -or $first -match "routing semantico spento") {
    Write-Host $first
    Write-Warning "Embeddings NON live (o routing disabilitato): impossibile misurare. Esegui in PROD con TEI/Ollama attivi."
    exit 2
}

# --- Sweep -------------------------------------------------------------------
$results = @()
foreach ($t in $Thresholds) {
    $out = if ($t -eq $Thresholds[0]) { $first } else { Invoke-Probe $t }
    $pass = $null; $tot = $null
    if ($out -match "Sonde col dominio atteso attivo:\s*(\d+)/(\d+)") {
        $pass = [int]$Matches[1]; $tot = [int]$Matches[2]
    }
    # Righe MISS (per capire quali domini non scattano a questa soglia).
    $miss = ([regex]::Matches($out, "MISS \(atteso (\w+)\)") | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique) -join ", "
    $results += [pscustomobject]@{
        Soglia = $t
        OK     = if ($null -ne $pass) { "$pass/$tot" } else { "?" }
        Pass   = $pass
        Tot    = $tot
        Miss   = if ($miss) { $miss } else { "-" }
    }
}

Write-Host ""
Write-Host "== Riepilogo ==" -ForegroundColor Cyan
$results | Format-Table Soglia, OK, Miss -AutoSize

# --- Raccomandazione: soglia PIU' ALTA con tutte le sonde OK -----------------
$full = $results | Where-Object { $_.Tot -and $_.Pass -eq $_.Tot } | Sort-Object Soglia -Descending
if ($full) {
    $best = $full[0].Soglia
    Write-Host "CONSIGLIATA: AI_TOOL_ROUTING_THRESHOLD=$best  (soglia piu' alta con tutte le sonde OK)" -ForegroundColor Green
} else {
    $bestRow = $results | Where-Object { $_.Pass } | Sort-Object Pass -Descending, Soglia -Descending | Select-Object -First 1
    $best = if ($bestRow) { $bestRow.Soglia } else { $Thresholds[-1] }
    Write-Warning "Nessuna soglia porta TUTTE le sonde a OK. Migliore parziale: $best ($($bestRow.OK))."
    Write-Host "Se restano MISS: controlla i seed in _DOMAIN_ROUTING_SEEDS del dominio mancante o affidati al gate keyword." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== Da mettere in config\.env (persistente), poi riavviare l'app-pool ==" -ForegroundColor Cyan
Write-Host "AI_TOOL_ROUTING_THRESHOLD=$best"
if ($PSBoundParameters.ContainsKey('TopK'))   { Write-Host "AI_TOOL_ROUTING_TOP_K=$TopK" }
if ($PSBoundParameters.ContainsKey('Margin')) { Write-Host "AI_TOOL_ROUTING_MARGIN=$Margin" }
Write-Host ""
Write-Host "Verifica finale col dettaglio per-sonda:" -ForegroundColor Cyan
Write-Host "  $PythonExe $ManagePy ai_routing_probe --settings=$Settings --threshold $best"
