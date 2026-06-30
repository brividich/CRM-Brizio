<#
.SYNOPSIS
    Go-live AI/RAG in prod - incatena la "sezione 5" del runbook docs/ai/RUNBOOK_DEPLOY_AI.md
    con stop-on-error (si ferma al primo passo fallito).

.DESCRIPTION
    Esegue, in ordine e abortendo al primo errore:
      1. manage.py check               (GATE: core.E001 fallisce se .env ha chiavi duplicate)
      2. [opz -RunImport] import_sgi_da_share --json (dry-run) + --apply
      3. index_sgi_documents --json    (re-index: calcola e CACHA gli embeddings bge-m3 via TEI)
      4. [salvo -SkipApproveSkillMatrix] ai_seed_skillmatrix_privacy_review --approve
      5. setup_q_schedules             ((ri)registra gli schedule, incl. sgi_share_check)
      6. [salvo -SkipHealthcheck] tools\ai_healthcheck_prod.ps1

    PRE-REQUISITI (NON fatti da questo script - vedi runbook):
      - deploy + activate gia' eseguiti;
      - .env persistente C:\PortaleNovicrom\prod\config\.env gia' sistemato:
        OLLAMA_EMBED_ENABLED=1, RAG_EMBED_BACKEND=openai, RAG_EMBED_OPENAI_BASE_URL/MODEL,
        e nessuna chiave duplicata.

.PARAMETER DryRun
    Stampa i comandi senza eseguirli.

.PARAMETER RunImport
    Esegue anche import_sgi_da_share (dry-run + apply) prima del re-index.
    Default OFF: in genere serve solo il re-index dopo aver riacceso gli embeddings.

.PARAMETER FailOnEmbedError
    Passa --fail-on-error a index_sgi_documents: aborta se gli embeddings (TEI) non
    rispondono, invece di degradare silenziosamente a BM25-only. Consigliato per un go-live.

.EXAMPLE
    .\tools\ai_golive_prod.ps1
.EXAMPLE
    .\tools\ai_golive_prod.ps1 -RunImport -FailOnEmbedError
.EXAMPLE
    .\tools\ai_golive_prod.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$AppRoot  = "C:\PortaleNovicrom\prod\current",
    [string]$PyExe    = "C:\PortaleNovicrom\prod\venv\Scripts\python.exe",
    [string]$Settings = "config.settings.prod",
    [switch]$RunImport,
    [switch]$FailOnEmbedError,
    [switch]$SkipApproveSkillMatrix,
    [switch]$SkipHealthcheck,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ManageRel   = "django_app\manage.py"
$ManageFull  = Join-Path $AppRoot $ManageRel
$Healthcheck = Join-Path $AppRoot "tools\ai_healthcheck_prod.ps1"

function Write-Step([string]$n, [string]$msg) {
    Write-Host ""
    Write-Host ("==================================================================")
    Write-Host ("  STEP $n  -  $msg")
    Write-Host ("==================================================================")
}

function Invoke-Manage([string]$n, [string]$title, [string[]]$mgArgs) {
    $full = @($ManageRel) + $mgArgs + @("--settings=$Settings")
    Write-Step $n "$title"
    Write-Host ("  > python " + ($full -join " "))
    if ($DryRun) { Write-Host "  (DRY-RUN: non eseguito)"; return }
    & $PyExe @full
    if ($LASTEXITCODE -ne 0) {
        throw "STEP $n '$title' FALLITO (exit $LASTEXITCODE). Procedura interrotta."
    }
    Write-Host "  OK"
}

$failed = $false
try {
    # --- Pre-flight: percorsi ---
    Write-Step "0" "Pre-flight (percorsi prod)"
    if (-not (Test-Path $PyExe))      { throw "Python venv prod non trovato: $PyExe" }
    if (-not (Test-Path $ManageFull)) { throw "manage.py non trovato: $ManageFull" }
    Write-Host "  AppRoot : $AppRoot"
    Write-Host "  Python  : $PyExe"
    Write-Host "  Settings: $Settings"
    Push-Location $AppRoot

    # --- 1. GATE check (core.E001 = nessuna chiave .env duplicata) ---
    Invoke-Manage "1" "check (GATE: .env senza duplicati)" @("check")

    # --- 2. (opz) import share SGI ---
    if ($RunImport) {
        Invoke-Manage "2a" "import_sgi_da_share (dry-run / preview)" @("import_sgi_da_share","--json")
        Invoke-Manage "2b" "import_sgi_da_share --apply"            @("import_sgi_da_share","--apply")
    } else {
        Write-Step "2" "import_sgi_da_share - SALTATO (-RunImport assente)"
    }

    # --- 3. re-index RAG (calcola + cacha embeddings) ---
    $idxArgs = @("index_sgi_documents","--json")
    if ($FailOnEmbedError) { $idxArgs += "--fail-on-error" }
    Invoke-Manage "3" "index_sgi_documents (re-index + cache embeddings)" $idxArgs

    # --- 4. (salvo skip) accendi tool Skill Matrix ---
    if ($SkipApproveSkillMatrix) {
        Write-Step "4" "ai_seed_skillmatrix_privacy_review --approve - SALTATO (-SkipApproveSkillMatrix)"
    } else {
        Invoke-Manage "4" "ai_seed_skillmatrix_privacy_review --approve (accende il tool, gated ACL)" `
            @("ai_seed_skillmatrix_privacy_review","--approve")
    }

    # --- 5. (ri)registra schedule ---
    Invoke-Manage "5" "setup_q_schedules (incl. sgi_share_check CRON 04:30)" @("setup_q_schedules")

    Pop-Location

    # --- 6. (salvo skip) healthcheck ---
    if ($SkipHealthcheck) {
        Write-Step "6" "ai_healthcheck_prod.ps1 - SALTATO (-SkipHealthcheck)"
    } elseif (-not (Test-Path $Healthcheck)) {
        Write-Step "6" "ai_healthcheck_prod.ps1 - NON TROVATO ($Healthcheck), salto"
    } else {
        Write-Step "6" "ai_healthcheck_prod.ps1 (TEI/Ollama, embed dim, RAG, schedule, cluster)"
        Write-Host ("  > " + $Healthcheck)
        if (-not $DryRun) {
            & $Healthcheck -AppRoot $AppRoot -PyExe $PyExe -Settings $Settings
            if ($LASTEXITCODE -ne 0) {
                Write-Host ""
                Write-Host "  ATTENZIONE: healthcheck ha segnalato almeno un FAIL (exit $LASTEXITCODE)."
                Write-Host "  I passi 1-5 sono andati a buon fine; rivedi i check sopra (TEI raggiungibile?"
                Write-Host "  embed dim 1024? sgi_chunks>0? cluster vivo?) prima di considerare chiuso il go-live."
            } else {
                Write-Host "  OK (healthcheck verde)"
            }
        }
    }

    Write-Host ""
    Write-Host "------------------------------------------------------------------"
    if ($DryRun) {
        Write-Host "  DRY-RUN completato: nessun comando eseguito."
    } else {
        Write-Host "  GO-LIVE AI: passi 1-5 completati."
        Write-Host "  Verifiche manuali residue (vedi runbook, sez. 6):"
        Write-Host "   - chat: 'di cosa parla MT CN 06' -> panoramica (no confabulazione)"
        Write-Host "   - chat: 'chi puo' sostituire DM11' -> tool Skill Matrix (utente con ACL skillmatrix.view)"
        Write-Host "   - monitoring /system_status -> card 'Indice documentale (RAG)' popolata"
    }
    Write-Host "------------------------------------------------------------------"
}
catch {
    $failed = $true
    if ((Get-Location).Path -ne $PSScriptRoot) { try { Pop-Location -ErrorAction SilentlyContinue } catch {} }
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Red
    Write-Host ("  GO-LIVE INTERROTTO: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "==================================================================" -ForegroundColor Red
    Write-Host "  Correggi la causa e rilancia: lo script e' idempotente (re-index,"
    Write-Host "  seed --approve, setup_q_schedules si possono ripetere senza danni)."
}
finally {
    if ($failed) { exit 1 }
}
