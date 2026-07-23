<#
.SYNOPSIS
    Verifica (e, con -Apply, allinea) il branch di rilascio `release/prod` a `main`
    PRIMA di impacchettare con deployment/scripts/package-release.ps1.

.DESCRIPTION
    Il packager esporta un COMMIT del branch `release/prod` (non la cartella di
    lavoro), leggendone il ref LOCALE. Quindi, perche' la produzione riceva il
    lavoro consolidato, `release/prod` deve puntare a `main` prima del package.

    Questo script automatizza SOLO la parte sicura e ripetibile di quel controllo
    — quella che il pre-flight di package-release.ps1 rileva ma non risolve:

      1. `git fetch` e verifica che `main` locale == `origin/main`
         (trappola nota: un `main` locale stale impacchetta il commit sbagliato).
      2. Working tree pulito nel checkout condiviso.
      3. Confronto `release/prod` vs `main` nei DUE versi:
           - allineati                -> ok, si puo' impacchettare;
           - release/prod ANTENATO di main (solo indietro, nessun commit divergente)
                                       -> fast-forward SICURO: con -Apply lo allinea;
           - release/prod ha commit NON in main (divergenza)
                                       -> STOP. Serve integrazione manuale in `main`
                                          (merge del/i branch feature), poi ri-eseguire.
                                          Lo script NON esegue merge di lavoro divergente.

    Di default NON tocca nulla (solo diagnosi). Con -Apply esegue l'allineamento
    fast-forward e, salvo -NoPush, il push di `main` e `release/prod`.

    NB: la coerenza delle migrazioni (leaf multipli -> merge migration) resta a
    `manage.py makemigrations --check`, non e' compito di questo script.

.PARAMETER RepoRoot
    Radice del repo (checkout condiviso). Default: due livelli sopra questo script.

.PARAMETER Main
    Nome del branch di integrazione. Default: "main".

.PARAMETER ReleaseBranch
    Nome del branch di rilascio esportato dal packager. Default: "release/prod".

.PARAMETER Apply
    Esegue l'allineamento fast-forward (altrimenti solo diagnosi).

.PARAMETER NoPush
    Con -Apply, non fa il push su origin (utile per provare in locale).

.PARAMETER NoFetch
    Salta `git fetch` (diagnosi offline sui ref gia' presenti).

.EXAMPLE
    # Solo diagnosi (non tocca nulla)
    pwsh -File tools/sync-release-prod.ps1

.EXAMPLE
    # Allinea release/prod a main (se fast-forward sicuro) e fa il push
    pwsh -File tools/sync-release-prod.ps1 -Apply

.OUTPUTS
    Exit code: 0 = allineato (o allineato con successo). 1 = azione necessaria
    (divergenza / main stale / working tree sporco) oppure errore.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$Main = "main",
    [string]$ReleaseBranch = "release/prod",
    [switch]$Apply,
    [switch]$NoPush,
    [switch]$NoFetch
)

$ErrorActionPreference = "Stop"

# ── logging coerente col resto dei tool ─────────────────────────────────────
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $color = switch ($Level) {
        "ERROR"   { "Red" }
        "WARN"    { "Yellow" }
        "SUCCESS" { "Green" }
        "STEP"    { "Cyan" }
        default   { "Gray" }
    }
    $tag = $Level.PadRight(7)
    Write-Host "[$tag] $Message" -ForegroundColor $color
}
function Write-Sep { Write-Host ("-" * 72) -ForegroundColor DarkGray }

function Git-Value {
    # Un singolo valore trimmato (rev-parse, rev-list --count). Exit code in $LASTEXITCODE.
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    ((& git -C $RepoRoot @GitArgs 2>$null | Select-Object -First 1) | Out-String).Trim()
}
function Git-Lines {
    # Array di righe non vuote (status, log, worktree list).
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    @(& git -C $RepoRoot @GitArgs 2>$null | Where-Object { $_ -and $_.Trim() })
}

# ── risoluzione RepoRoot ────────────────────────────────────────────────────
if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
    Write-Log "Repository git non trovato in '$RepoRoot'. Usa -RepoRoot per indicarlo." "ERROR"
    exit 1
}
Write-Log "Repo: $RepoRoot" "STEP"
Write-Log ("Modalita': " + $(if ($Apply) { "APPLY (allineamento + push)" } else { "solo diagnosi (nessuna modifica)" })) "STEP"
Write-Sep

# ── il checkout dev'essere su Main (il packager si lancia da li') ──────────
$currentBranch = Git-Value rev-parse --abbrev-ref HEAD
if ($currentBranch -ne $Main) {
    Write-Log "Il checkout condiviso e' sul branch '$currentBranch', non '$Main'." "ERROR"
    Write-Log "Esegui questo script (e il package) dal checkout condiviso posizionato su '$Main'." "ERROR"
    exit 1
}

# ── 1) fetch + main == origin/main ─────────────────────────────────────────
if (-not $NoFetch) {
    Write-Log "git fetch origin..." "STEP"
    & git -C $RepoRoot fetch --quiet origin 2>&1 | Out-Null
}

$mainSha = Git-Value rev-parse --verify --quiet $Main
if (-not $mainSha) { Write-Log "Branch '$Main' non trovato." "ERROR"; exit 1 }

$originMain = "origin/$Main"
$originMainSha = Git-Value rev-parse --verify --quiet $originMain
if ($originMainSha) {
    if ($mainSha -ne $originMainSha) {
        $behind = Git-Value rev-list --count "$Main..$originMain"
        $ahead  = Git-Value rev-list --count "$originMain..$Main"
        Write-Sep
        Write-Log "'$Main' locale ($($mainSha.Substring(0,8))) != '$originMain' ($($originMainSha.Substring(0,8)))." "ERROR"
        Write-Log "  indietro di $behind, avanti di $ahead commit." "INFO"
        if ([int]$ahead -eq 0) {
            Write-Log "'$Main' e' solo INDIETRO: aggiornalo prima di rilasciare —  git -C `"$RepoRoot`" merge --ff-only $originMain" "ERROR"
        } else {
            Write-Log "'$Main' locale e origin sono DIVERGENTI: riconcilia a mano prima di rilasciare." "ERROR"
        }
        Write-Log "Il packager legge i ref LOCALI: un '$Main' stale impacchetta il commit sbagliato." "ERROR"
        Write-Sep
        exit 1
    }
    Write-Log "'$Main' allineato a '$originMain' ($($mainSha.Substring(0,8)))." "SUCCESS"
} else {
    Write-Log "'$originMain' non presente (nessun fetch o remote diverso): salto il confronto con origin." "WARN"
}

# ── 2) working tree pulito ─────────────────────────────────────────────────
$dirty = Git-Lines status --porcelain
if ($dirty.Count -gt 0) {
    Write-Sep
    Write-Log "$($dirty.Count) file non committati nel checkout condiviso:" "WARN"
    foreach ($l in $dirty) { Write-Log "    $l" "INFO" }
    Write-Log "Non bloccano l'allineamento di '$ReleaseBranch', ma NON finiranno nel pacchetto (il package esporta un commit)." "WARN"
    Write-Sep
}

# ── 3) release/prod vs main ────────────────────────────────────────────────
$relSha = Git-Value rev-parse --verify --quiet $ReleaseBranch
if (-not $relSha) {
    Write-Log "Branch di rilascio '$ReleaseBranch' non presente in locale." "ERROR"
    Write-Log "Crealo allineato a '$Main':  git -C `"$RepoRoot`" branch $ReleaseBranch $Main" "ERROR"
    exit 1
}

# release/prod e' checked out in un worktree? (allora niente `branch -f`)
$relWorktree = $null
$wtLines = (& git -C $RepoRoot worktree list --porcelain 2>$null)
$curWtPath = $null
foreach ($line in $wtLines) {
    if ($line -like "worktree *") { $curWtPath = $line.Substring(9).Trim() }
    elseif ($line -like "branch *") {
        $b = $line.Substring(7).Trim() -replace '^refs/heads/', ''
        if ($b -eq $ReleaseBranch) { $relWorktree = $curWtPath }
    }
}

$behindRel = [int](Git-Value rev-list --count "$ReleaseBranch..$Main")   # commit in main non in prod
$aheadRel  = [int](Git-Value rev-list --count "$Main..$ReleaseBranch")   # commit in prod non in main

Write-Sep
Write-Log "Confronto: '$ReleaseBranch' ($($relSha.Substring(0,8)))  vs  '$Main' ($($mainSha.Substring(0,8)))" "STEP"
Write-Log "  commit in '$Main' NON in '$ReleaseBranch' : $behindRel" "INFO"
Write-Log "  commit in '$ReleaseBranch' NON in '$Main' : $aheadRel" "INFO"

# CASO A — divergenza: STOP, serve integrazione manuale.
if ($aheadRel -gt 0) {
    Write-Sep
    Write-Log "'$ReleaseBranch' ha $aheadRel commit che NON sono in '$Main': linee DIVERGENTI." "ERROR"
    Write-Log "Questo lavoro e' probabilmente gia' in produzione: NON lo si scavalca automaticamente." "ERROR"
    foreach ($l in @(Git-Lines log --oneline "$Main..$ReleaseBranch")) { Write-Log "    $l" "INFO" }
    Write-Sep
    Write-Log "Integra a mano quel/i commit in '$Main' (merge del branch feature, risolvi i conflitti e le" "ERROR"
    Write-Log "eventuali migrazioni), poi rilancia. Lo script allinea solo i fast-forward sicuri." "ERROR"
    exit 1
}

# CASO B — gia' allineato.
if ($behindRel -eq 0) {
    Write-Sep
    Write-Log "'$ReleaseBranch' e' allineato a '$Main' ($($mainSha.Substring(0,8))). Pronto per il package." "SUCCESS"
    exit 0
}

# CASO C — solo indietro: fast-forward sicuro.
Write-Sep
Write-Log "'$ReleaseBranch' e' indietro di $behindRel commit (fast-forward SICURO verso '$Main')." "SUCCESS"
foreach ($l in @(Git-Lines log --oneline "$ReleaseBranch..$Main")) { Write-Log "    $l" "INFO" }

if (-not $Apply) {
    Write-Sep
    Write-Log "Diagnosi soltanto. Per allineare:  pwsh -File tools/sync-release-prod.ps1 -Apply" "WARN"
    exit 1
}

# ── APPLY: allinea release/prod a main ─────────────────────────────────────
Write-Sep
if ($relWorktree) {
    Write-Log "'$ReleaseBranch' e' checked out nel worktree '$relWorktree': avanzo li' con merge --ff-only." "STEP"
    & git -C $relWorktree merge --ff-only $Main 2>&1 | ForEach-Object { Write-Log "    $_" "INFO" }
    if ($LASTEXITCODE -ne 0) { Write-Log "Fast-forward fallito nel worktree." "ERROR"; exit 1 }
} else {
    Write-Log "Sposto '$ReleaseBranch' a '$Main' (non e' checked out da nessuna parte)." "STEP"
    & git -C $RepoRoot branch -f $ReleaseBranch $Main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Log "Impossibile spostare '$ReleaseBranch'." "ERROR"; exit 1 }
}

$relSha = Git-Value rev-parse --verify --quiet $ReleaseBranch
Write-Log "'$ReleaseBranch' ora a $($relSha.Substring(0,8))." "SUCCESS"

if ($NoPush) {
    Write-Log "-NoPush: salto il push. Ricorda che il package legge il ref LOCALE (gia' allineato)." "WARN"
    exit 0
}

# Push main (se serve) e release/prod.
foreach ($b in @($Main, $ReleaseBranch)) {
    Write-Log "git push origin $b ..." "STEP"
    & git -C $RepoRoot push origin $b 2>&1 | ForEach-Object { Write-Log "    $_" "INFO" }
    if ($LASTEXITCODE -ne 0) { Write-Log "Push di '$b' fallito." "ERROR"; exit 1 }
}
Write-Sep
Write-Log "Fatto: '$Main' == '$ReleaseBranch' == $($relSha.Substring(0,8)). Puoi impacchettare." "SUCCESS"
exit 0
