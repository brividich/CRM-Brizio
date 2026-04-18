# tools/install-git-hooks.ps1 — installa gli hook di progetto in .git/hooks/
# Uso: da root repo: powershell -ExecutionPolicy Bypass -File tools\install-git-hooks.ps1

$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel) 2>$null
if (-not $repoRoot) {
    Write-Error "Non sono in una repo git."
    exit 1
}

$hooksSrc = Join-Path $repoRoot "tools\git-hooks"
$hooksDst = Join-Path $repoRoot ".git\hooks"

if (-not (Test-Path $hooksSrc)) {
    Write-Error "Cartella tools\git-hooks mancante."
    exit 1
}

$installed = @()
Get-ChildItem -Path $hooksSrc -File | ForEach-Object {
    $target = Join-Path $hooksDst $_.Name
    Copy-Item -Path $_.FullName -Destination $target -Force
    # Su Windows git-bash interpreta shebang; nessuna chmod serve
    $installed += $_.Name
}

Write-Host "Hook installati in $hooksDst:" -ForegroundColor Green
$installed | ForEach-Object { Write-Host "  - $_" }
Write-Host "Test: crea un file .env in staging con 'git add -f .env' e prova un commit — deve fallire."
