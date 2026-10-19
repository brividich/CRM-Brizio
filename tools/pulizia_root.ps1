<#
.SYNOPSIS
    Elenca i file e le cartelle NON tracciati nella radice del repo. Non cancella nulla.

.DESCRIPTION
    Igiene repo (18/10/2026). Mostra cosa e' rimasto nella radice fuori da git,
    distinguendo cio' che e' gia' coperto da .gitignore (ignorato) da cio' che
    compare in `git status` (non tracciato e non ignorato: va spostato, versionato
    o aggiunto a .gitignore). La cancellazione resta una scelta manuale.

.PARAMETER IncludeIgnored
    Elenca anche gli elementi ignorati da .gitignore (default: solo quelli visibili
    in `git status`).

.EXAMPLE
    .\tools\pulizia_root.ps1
    .\tools\pulizia_root.ps1 -IncludeIgnored
#>
[CmdletBinding()]
param(
    [switch]$IncludeIgnored,
    # Repository da esaminare (default: quello che contiene lo script).
    [string]$RepoPath = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$repoRoot = (git -C $RepoPath rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw "Non sono dentro un repository git." }

function Get-RootEntries([string[]]$gitArgs) {
    # --directory: una cartella non tracciata compare come "nome/" senza elencarne il contenuto.
    # core.quotepath=off: nomi con caratteri non ASCII leggibili, non in ottale.
    $lines = git -C $repoRoot -c core.quotepath=off ls-files --others --directory @gitArgs
    foreach ($line in $lines) {
        $name = $line.Trim('"')
        $trimmed = $name.TrimEnd('/')
        if ($trimmed -and -not $trimmed.Contains('/')) { $name }
    }
}

function Write-Entries([string]$title, [string[]]$entries) {
    Write-Host ""
    Write-Host "$title ($($entries.Count))" -ForegroundColor Cyan
    if (-not $entries) { Write-Host "  (nessuno)"; return }
    foreach ($entry in ($entries | Sort-Object)) {
        $full = Join-Path $repoRoot $entry.TrimEnd('/')
        $item = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
        $size = ""
        if ($item -and -not $item.PSIsContainer) { $size = "{0,10:N0} KB" -f [math]::Ceiling($item.Length / 1KB) }
        elseif ($item) { $size = "{0,13}" -f "<dir>" }
        Write-Host ("  {0}  {1}" -f $size, $entry)
    }
}

$visibili = @(Get-RootEntries @("--exclude-standard"))
Write-Entries "Non tracciati in radice (visibili in git status)" $visibili

if ($IncludeIgnored) {
    $ignorati = @(Get-RootEntries @("--ignored", "--exclude-standard"))
    Write-Entries "Ignorati da .gitignore in radice" $ignorati
}

Write-Host ""
Write-Host "Nessun file e' stato cancellato. Per rimuovere: Remove-Item manuale dopo verifica." -ForegroundColor Yellow
