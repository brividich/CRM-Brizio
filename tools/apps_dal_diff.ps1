<#
.SYNOPSIS
    Restituisce le app Django i cui file compaiono nel diff fra BaseRef e HeadRef.

.DESCRIPTION
    Usato dal workflow .github/workflows/pr-check.yml per lanciare i test delle sole
    app toccate da una PR. Un'app e' una cartella diretta di django_app/ con apps.py
    (config/ e le cartelle di supporto sono escluse). Scrive su stdout le etichette
    separate da spazio, oppure una stringa vuota se nessuna app e' coinvolta.

.EXAMPLE
    .\tools\apps_dal_diff.ps1 -BaseRef origin/main
    .\tools\apps_dal_diff.ps1 -BaseRef $env:BASE_SHA -HeadRef HEAD
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaseRef,
    [string]$HeadRef = "HEAD"
)

$ErrorActionPreference = "Stop"
$repoRoot = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
$djangoRoot = Join-Path $repoRoot "django_app"

# Diff a tre punti: solo cio' che la PR introduce rispetto al merge-base.
$files = git -C $repoRoot -c core.quotepath=off diff --name-only "$BaseRef...$HeadRef"
if ($LASTEXITCODE -ne 0) { throw "git diff fallito fra $BaseRef e $HeadRef" }

$apps = New-Object System.Collections.Generic.SortedSet[string]
foreach ($file in $files) {
    if ($file -notmatch '^django_app/([^/]+)/') { continue }
    $app = $Matches[1]
    if ($app -eq "config" -or $app.StartsWith(".")) { continue }
    # Solo pacchetti app veri (gitlink, cartelle statiche ecc. restano fuori).
    if (Test-Path -LiteralPath (Join-Path $djangoRoot "$app\apps.py")) {
        [void]$apps.Add($app)
    }
}

Write-Output ($apps -join " ")
