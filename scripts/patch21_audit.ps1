$ErrorActionPreference = "Stop"

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Title)
    Write-Host ""
    Write-Host "=== $Title ==="
}

function New-ForbiddenPattern {
    param([Parameter(Mandatory = $true)][string[]]$Parts)
    return ($Parts -join "")
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$Failed = $false

Write-Section "File chiave Patch 21"
$KeyFiles = @(
    "django_app/assets/services/maintenance_register.py",
    "django_app/assets/services/dashboard_kpi.py",
    "django_app/assets/management/commands/seed_assets_antincendio.py",
    "django_app/tickets/migrations/0008_ticket_include_in_maintenance_register.py",
    "django_app/dpi/migrations/0004_tipo_modello_taglia_dpi.py",
    "django_app/tasks/migrations/0027_project_safety_impact.py"
)

foreach ($File in $KeyFiles) {
    if (Test-Path -LiteralPath $File -PathType Leaf) {
        Write-Host "PASS file presente: $File"
    } else {
        Write-Host "FAIL file mancante: $File"
        $Failed = $true
    }
}

Write-Section "Pattern vietati"
$ForbiddenPatterns = @(
    (New-ForbiddenPattern @("TYPE_", "ANTINCENDIO")),
    (New-ForbiddenPattern @("Asset.TYPE_", "ANTINCENDIO")),
    (New-ForbiddenPattern @("add_asset_type_", "antincendio")),
    (New-ForbiddenPattern @("0062_seed_", "antincendio")),
    (New-ForbiddenPattern @("Provider API request ", "failed")),
    (New-ForbiddenPattern @("debug", "_test")),
    (New-ForbiddenPattern @("TODO ", "PATCH 21")),
    (New-ForbiddenPattern @("FIXME ", "PATCH 21")),
    (New-ForbiddenPattern @("mongo", "lo"))
)

foreach ($Pattern in $ForbiddenPatterns) {
    $Matches = & git grep -n --fixed-strings -- $Pattern -- .
    $ExitCode = $LASTEXITCODE

    if ($ExitCode -eq 0) {
        Write-Host "FAIL pattern trovato: $Pattern"
        $Matches | ForEach-Object { Write-Host $_ }
        $Failed = $true
    } elseif ($ExitCode -eq 1) {
        Write-Host "PASS pattern assente: $Pattern"
    } else {
        Write-Host "FAIL errore git grep per pattern: $Pattern (exit code $ExitCode)"
        $Failed = $true
    }
}

if ($Failed) {
    Write-Host ""
    Write-Error "Patch 21 audit FAIL"
    exit 1
}

Write-Host ""
Write-Host "Patch 21 audit PASS"
