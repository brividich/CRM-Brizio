$ErrorActionPreference = "Stop"

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Title)
    Write-Host ""
    Write-Host "=== $Title ==="
}

function Invoke-FullGuardStep {
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

Invoke-FullGuardStep "Patch 21 guard" {
    & .\scripts\patch21_guard.ps1
}

Invoke-FullGuardStep "Full Django test suite" {
    & .\.venv\Scripts\python.exe .\django_app\manage.py test --settings=config.settings.test -v 1 --keepdb
}

Invoke-FullGuardStep "Patch 21 audit" {
    & .\scripts\patch21_audit.ps1
}

Write-Host ""
Write-Host "Patch 21 full guard PASS"
