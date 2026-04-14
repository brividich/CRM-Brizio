<#
.SYNOPSIS
    Applica una patch veloce (file singoli) sul release attivo senza fare un deploy completo.

.DESCRIPTION
    Copia i file indicati dal repo locale verso la release "current" dell'ambiente,
    ricicla l'app pool IIS e opzionalmente esegue management command Django.

    Pensato per hotfix su file Python/template/SQL che non richiedono
    migrate, collectstatic o aggiornamento dipendenze.

    ATTENZIONE: sovrascrive direttamente i file in current\. Non crea un
    nuovo release né aggiorna la junction. Usare solo per patch minime e
    testate. Per modifiche strutturali usare il deploy completo.

.PARAMETER Environment
    Ambiente target: "test" oppure "prod"

.PARAMETER Files
    Uno o piu percorsi relativi alla root del repo (es. "django_app/automazioni/services.py").
    Separati da virgola oppure specificare il parametro piu volte.
    Se omesso usa -PatchList.

.PARAMETER PatchList
    Percorso a un file .txt con un file per riga (percorsi relativi alla root repo).

.PARAMETER RepoRoot
    Root del repository locale. Default: directory padre di deployment\.

.PARAMETER RunManage
    Lista di management command da eseguire dopo la copia, es:
    "apply_sql_triggers", "collectstatic --noinput"
    Ogni stringa viene eseguita come: python manage.py <stringa> --settings=config.settings.prod

.PARAMETER SkipRecycle
    Non ricicla l'app pool IIS dopo la patch.

.PARAMETER AppPool
    Nome dell'app pool IIS. Default: "PortaleNovicrom_<Environment>"

.EXAMPLE
    # Patch singolo file + riciclo pool
    .\patch-release.ps1 -Environment test -Files "django_app/automazioni/services.py"

    # Patch multipli file
    .\patch-release.ps1 -Environment test -Files "django_app/automazioni/services.py","django_app/automazioni/views.py"

    # Patch da lista + esegui apply_sql_triggers
    .\patch-release.ps1 -Environment test -PatchList ".\hotfix_files.txt" -RunManage "apply_sql_triggers"

    # Solo management command, senza copiare file
    .\patch-release.ps1 -Environment test -RunManage "apply_sql_triggers"
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [string[]]$Files = @(),

    [string]$PatchList = "",

    [string]$RepoRoot = "",

    [string[]]$RunManage = @(),

    [switch]$SkipRecycle,

    [string]$AppPool = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

Assert-Admin
Assert-ValidEnvironment -Env $Environment

# ---------------------------------------------------------------------------
# Risolvi percorsi
# ---------------------------------------------------------------------------
if (-not $RepoRoot) {
    # deployment\scripts\ -> su due livelli = root repo
    $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
}
if (-not (Test-Path $RepoRoot)) {
    Write-Log "RepoRoot non trovato: $RepoRoot" "ERROR"
    exit 1
}

$paths      = Get-EnvPaths -Env $Environment
$currentDir = $paths.Current
$venvPath   = $paths.Venv
$djangoApp  = "$currentDir\django_app"
$settingsMod = "config.settings.prod"

if (-not (Test-Path $currentDir)) {
    Write-Log "Release current non trovata: $currentDir" "ERROR"
    exit 1
}

if (-not $AppPool) {
    $AppPool = "PortaleNovicrom_$Environment"
}

# ---------------------------------------------------------------------------
# Raccogli lista file da patchare
# ---------------------------------------------------------------------------
$filesToPatch = [System.Collections.Generic.List[string]]::new()

foreach ($f in $Files) {
    if ($f.Trim()) { $filesToPatch.Add($f.Trim()) }
}

if ($PatchList -and (Test-Path $PatchList)) {
    $lines = Get-Content $PatchList | Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith('#') }
    foreach ($line in $lines) {
        $filesToPatch.Add($line.Trim())
    }
}

# ---------------------------------------------------------------------------
# Riepilogo
# ---------------------------------------------------------------------------
Write-LogSeparator
Write-Log "patch-release.ps1 — ambiente: $Environment" "STEP"
Write-Log "Current release : $currentDir" "INFO"
Write-Log "Repo root       : $RepoRoot" "INFO"
Write-Log "File da patchare: $($filesToPatch.Count)" "INFO"
if ($RunManage.Count) {
    Write-Log "Management cmd  : $($RunManage -join ', ')" "INFO"
}
Write-LogSeparator

# ---------------------------------------------------------------------------
# Copia file
# ---------------------------------------------------------------------------
$copied  = 0
$skipped = 0
$errors  = 0

if ($filesToPatch.Count -gt 0) {
    Write-Log "[1] Copia file..." "STEP"
    foreach ($relPath in $filesToPatch) {
        # normalizza separatori
        $relNorm = $relPath.Replace('/', '\')
        $src  = Join-Path $RepoRoot $relNorm
        $dest = Join-Path $currentDir $relNorm

        if (-not (Test-Path $src)) {
            Write-Log "  [MANCANTE] $relPath" "WARN"
            $skipped++
            continue
        }

        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }

        try {
            Copy-Item -Path $src -Destination $dest -Force
            Write-Log "  [OK] $relPath" "SUCCESS"
            $copied++
        }
        catch {
            Write-Log "  [ERRORE] $relPath : $_" "ERROR"
            $errors++
        }
    }
    Write-Log "Copia completata: $copied OK, $skipped non trovati, $errors errori." "INFO"
} else {
    Write-Log "[1] Nessun file da copiare — saltato." "INFO"
}

# ---------------------------------------------------------------------------
# Management command Django
# ---------------------------------------------------------------------------
if ($RunManage.Count -gt 0) {
    Write-Log "[2] Management command Django..." "STEP"

    # Carica le env vars dal .env della release corrente
    $envFile = "$currentDir\django_app\.env"
    $djangoEnv = @{}
    if (Test-Path $envFile) {
        Get-Content $envFile | Where-Object { $_ -match '^\s*[^#].*=.*' } | ForEach-Object {
            $parts = $_ -split '=', 2
            if ($parts.Count -eq 2) {
                $djangoEnv[$parts[0].Trim()] = $parts[1].Trim()
            }
        }
    }

    foreach ($cmd in $RunManage) {
        $cmdParts = $cmd -split '\s+', 2
        $subCommand = $cmdParts[0]
        $extraArgs  = if ($cmdParts.Count -gt 1) { $cmdParts[1] -split '\s+' } else { @() }

        $fullArgs = @("manage.py", $subCommand) + $extraArgs + @("--settings=$settingsMod")
        Write-Log "  python $($fullArgs -join ' ')" "INFO"
        try {
            Invoke-Venv -VenvPath $venvPath -WorkDir $djangoApp -Args $fullArgs -EnvVars $djangoEnv
            Write-Log "  [OK] $subCommand" "SUCCESS"
        }
        catch {
            Write-Log "  [ERRORE] $subCommand : $_" "ERROR"
            $errors++
        }
    }
}

# ---------------------------------------------------------------------------
# Riciclo IIS
# ---------------------------------------------------------------------------
if (-not $SkipRecycle) {
    Write-Log "[3] Recycle IIS App Pool: $AppPool..." "STEP"
    Invoke-IISRecycle -AppPoolName $AppPool
} else {
    Write-Log "[3] Recycle IIS — saltato (flag -SkipRecycle)." "WARN"
}

# ---------------------------------------------------------------------------
# Risultato finale
# ---------------------------------------------------------------------------
Write-LogSeparator
if ($errors -gt 0) {
    Write-Log "Patch completata con $errors errori. Verificare l'output." "WARN"
} else {
    Write-Log "Patch applicata con successo." "SUCCESS"
}
Write-LogSeparator
