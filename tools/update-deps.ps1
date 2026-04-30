# tools/update-deps.ps1 — gestione dipendenze pip-tools
# Workflow: modifica requirements.in / requirements-dev.in -> deps-compile -> deps-sync
#
# Utilizzo:
#   .\tools\update-deps.ps1 compile       # rigenera entrambi i .txt dai .in
#   .\tools\update-deps.ps1 sync          # installa/rimuove pacchetti per allinearsi ai .txt
#   .\tools\update-deps.ps1 upgrade       # aggiorna tutto il possibile e rigenera i .txt
#   .\tools\update-deps.ps1 compile-prod  # solo requirements.txt
#   .\tools\update-deps.ps1 compile-dev   # solo requirements-dev.txt

param(
    [Parameter(Position=0)]
    [ValidateSet("compile", "sync", "upgrade", "compile-prod", "compile-dev")]
    [string]$Command = "compile"
)

$ReqDir = "$PSScriptRoot\..\django_app"
$ProdIn  = "$ReqDir\requirements.in"
$ProdTxt = "$ReqDir\requirements.txt"
$DevIn   = "$ReqDir\requirements-dev.in"
$DevTxt  = "$ReqDir\requirements-dev.txt"

$CompileFlags = @("--strip-extras", "--annotation-style=line")

function Invoke-Compile {
    param([string]$In, [string]$Out, [switch]$Upgrade)
    $flags = $CompileFlags
    if ($Upgrade) { $flags += "--upgrade" }
    Write-Host ">> pip-compile $In -> $Out" -ForegroundColor Cyan
    pip-compile $In -o $Out @flags
    if ($LASTEXITCODE -ne 0) { throw "pip-compile failed for $In" }
}

switch ($Command) {
    "compile" {
        Invoke-Compile -In $ProdIn -Out $ProdTxt
        Invoke-Compile -In $DevIn  -Out $DevTxt
        Write-Host "`nDone. Esegui 'sync' per installare." -ForegroundColor Green
    }
    "compile-prod" {
        Invoke-Compile -In $ProdIn -Out $ProdTxt
    }
    "compile-dev" {
        Invoke-Compile -In $DevIn -Out $DevTxt
    }
    "sync" {
        Write-Host ">> pip-sync requirements.txt + requirements-dev.txt" -ForegroundColor Cyan
        pip-sync $ProdTxt $DevTxt
        if ($LASTEXITCODE -ne 0) { throw "pip-sync failed" }
        Write-Host "Sync completato." -ForegroundColor Green
    }
    "upgrade" {
        Invoke-Compile -In $ProdIn -Out $ProdTxt -Upgrade
        Invoke-Compile -In $DevIn  -Out $DevTxt  -Upgrade
        Write-Host "`nUpgrade completato. Esegui 'sync' per installare." -ForegroundColor Green
    }
}
