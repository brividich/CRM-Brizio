$ErrorActionPreference = "Stop"

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Title)
    Write-Host ""
    Write-Host "=== $Title ==="
}

function Invoke-GuardStep {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Section $Title
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Step fallito: $Title (exit code $LASTEXITCODE)"
        exit 1
    }
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Invoke-GuardStep "Django check" {
    & .\.venv\Scripts\python.exe .\django_app\manage.py check --settings=config.settings.test
}

Invoke-GuardStep "Django makemigrations check dry-run" {
    & .\.venv\Scripts\python.exe .\django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test
}

Invoke-GuardStep "Patch 21 app tests" {
    & .\.venv\Scripts\python.exe .\django_app\manage.py test assets.tests tickets.tests dpi.tests diario_preposto.tests tasks.tests --settings=config.settings.test -v 1 --keepdb
}

Invoke-GuardStep "Git diff whitespace check" {
    & git diff --check
}

Write-Section "Git working tree status"
$Status = & git status --porcelain
if ($LASTEXITCODE -ne 0) {
    Write-Error "Step fallito: git status --porcelain (exit code $LASTEXITCODE)"
    exit 1
}

if ($Status) {
    Write-Warning "Working tree non pulito"
    $Status | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "Working tree pulito"
}

Write-Host ""
Write-Host "Patch 21 guard PASS"
