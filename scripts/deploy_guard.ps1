<#
.SYNOPSIS
    deploy_guard.ps1 - Orchestratore deploy fail-fast per NOVICROM HUB.

.DESCRIPTION
    Esegue, in ordine, i guard di deploy per ambiente test/prod:
        1. Probe configurazione (deploy_env_probe.ps1)
        2. Django check + migrate + validate_deployment
        3. Preview/Apply migrate_admin_deadline_attachments_private
        4. Restart App Pool IIS (opzionale, fail-fast guarded)
        5. Smoke HTTP post-deploy (opzionale)

    Compatibile Windows PowerShell 5.1+.

    Sicurezza:
        - Mai stampa o salva valori segreti.
        - Mai modifica web.config (solo lettura via probe).
        - Mai esegue git pull / DB backup / drop.
        - --delete-source richiede DOPPIO flag esplicito.

.PARAMETER Environment
    test|prod (mandatory). In prod sono attive le validazioni piu' severe.

.PARAMETER IisSiteName
    Se valorizzato, lo script risolve ProjectRoot dal physicalPath del sito IIS.

.PARAMETER IisAppPool
    App pool da riavviare (se -RestartAppPool).

.PARAMETER ProjectRoot
    Path del repo (alternativa a IisSiteName).

.PARAMETER SettingsModule
    Settings Django (default config.settings.prod).

.PARAMETER PythonExe
    Eseguibile Python (default 'python').

.PARAMETER ApplyPrivateAttachments
    Esegue migrate_admin_deadline_attachments_private --apply.

.PARAMETER DeleteSourcePrivateAttachments
    Aggiunge --delete-source. Richiede anche -ConfirmDeleteSource e
    -ApplyPrivateAttachments.

.PARAMETER ConfirmDeleteSource
    Doppia conferma per la cancellazione delle source originali.

.PARAMETER RestartAppPool
    Riavvia l'app pool IIS al termine degli step Django.

.PARAMETER SmokeUrl
    URL base per smoke HTTP post-deploy.

.PARAMETER ReportDir
    Directory output report (default .\deploy_reports).

.PARAMETER StrictWarnings
    Tratta WARN di validate_deployment come failure.

.PARAMETER NoMigrate
    Salta lo step migrate.

.PARAMETER AllowSelfSignedCert
    Inoltrato a deploy_smoke.ps1.

.EXAMPLE
    .\deploy_guard.ps1 -Environment test -ProjectRoot 'C:\Dev\Portale Novicrom' -SettingsModule config.settings.test

.EXAMPLE
    .\deploy_guard.ps1 -Environment prod -IisSiteName 'NovicromHub' -IisAppPool 'NovicromHubPool' `
        -ApplyPrivateAttachments -RestartAppPool -SmokeUrl 'https://hub.example' -StrictWarnings

.NOTES
    Version: 1.0.0
    Exit codes:
        0 = tutto OK
        1 = un comando critico e' fallito
        2 = step critici OK ma smoke post-deploy ha fallito
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('test', 'prod')]
    [string]$Environment,

    [Parameter(Mandatory = $false)]
    [string]$IisSiteName,

    [Parameter(Mandatory = $false)]
    [string]$IisAppPool,

    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $false)]
    [string]$SettingsModule = 'config.settings.prod',

    [Parameter(Mandatory = $false)]
    [string]$PythonExe = 'python',

    [Parameter(Mandatory = $false)]
    [switch]$ApplyPrivateAttachments,

    [Parameter(Mandatory = $false)]
    [switch]$DeleteSourcePrivateAttachments,

    [Parameter(Mandatory = $false)]
    [switch]$ConfirmDeleteSource,

    [Parameter(Mandatory = $false)]
    [switch]$RestartAppPool,

    [Parameter(Mandatory = $false)]
    [string]$SmokeUrl,

    [Parameter(Mandatory = $false)]
    [string]$ReportDir = '.\deploy_reports',

    [Parameter(Mandatory = $false)]
    [switch]$StrictWarnings,

    [Parameter(Mandatory = $false)]
    [switch]$NoMigrate,

    [Parameter(Mandatory = $false)]
    [switch]$AllowSelfSignedCert
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptVersion = '1.1.0'

# ---------------------------------------------------------------------------
# Stato globale (popolato durante l'esecuzione)
# ---------------------------------------------------------------------------

$script:ReportFile     = $null
$script:StepResults    = @()
$script:CriticalFailed = $false
$script:SmokeFailed    = $false
$script:OriginalLocation = Get-Location

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Message
    )
    Write-Host $Message
    if ($null -ne $script:ReportFile) {
        try {
            Add-Content -Path $script:ReportFile -Value $Message -Encoding utf8
        } catch {
            Write-Host "[GUARD][WARN] Report append failed: $($_.Exception.Message)"
        }
    }
}

function Write-Section {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title
    )
    Write-Log ''
    Write-Log "=== $Title ==="
}

function Add-StepResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [ValidateSet('OK', 'FAIL', 'WARN', 'SKIP')]
        [string]$Status,

        [Parameter(Mandatory = $false)]
        [string]$Detail = ''
    )
    $script:StepResults += [PSCustomObject]@{
        Step   = $Name
        Status = $Status
        Detail = $Detail
    }
}

function Invoke-NativeSafe {
    # NOTE PS 5.1: con $ErrorActionPreference='Stop', qualsiasi exe nativo
    # (es. Python) che scrive su stderr (anche solo log INFO) genera
    # NativeCommandError che fa terminare lo script. Sospendiamo Stop solo
    # per la chiamata, controlliamo $LASTEXITCODE separatamente, e
    # ripristiniamo. Restituisce il risultato del scriptblock.
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        return & $Action
    } finally {
        $ErrorActionPreference = $prevEAP
    }
}

function Fail-Fast {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Step,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    Write-Log "[GUARD][FAIL] $Step :: $Message"
    Add-StepResult -Name $Step -Status 'FAIL' -Detail $Message
    $script:CriticalFailed = $true
    throw "$Step failed: $Message"
}

function Resolve-IisProjectRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SiteName
    )

    try {
        Import-Module WebAdministration -ErrorAction Stop
    } catch {
        throw "WebAdministration module not available: $($_.Exception.Message)"
    }

    $site = $null
    try {
        $site = Get-Website -Name $SiteName -ErrorAction Stop
    } catch {
        throw "IIS site '$SiteName' not found: $($_.Exception.Message)"
    }
    if ($null -eq $site) {
        throw "IIS site '$SiteName' not found."
    }

    $physical = [string]$site.physicalPath
    if ([string]::IsNullOrWhiteSpace($physical)) {
        throw "IIS site '$SiteName' has empty physicalPath."
    }
    # Espandi variabili %SystemDrive% etc.
    $expanded = [System.Environment]::ExpandEnvironmentVariables($physical)
    if (-not (Test-Path -LiteralPath $expanded)) {
        throw "IIS physicalPath does not exist on disk: $expanded"
    }
    return (Resolve-Path -LiteralPath $expanded).Path
}

# ---------------------------------------------------------------------------
# 1) Bootstrap / validazione input
# ---------------------------------------------------------------------------

try {
    if ($DeleteSourcePrivateAttachments -and -not $ConfirmDeleteSource) {
        Write-Host "[GUARD][FAIL] -DeleteSourcePrivateAttachments requires -ConfirmDeleteSource (double opt-in)."
        exit 1
    }
    if ($DeleteSourcePrivateAttachments -and -not $ApplyPrivateAttachments) {
        Write-Host "[GUARD][FAIL] -DeleteSourcePrivateAttachments requires -ApplyPrivateAttachments."
        exit 1
    }
    if ($RestartAppPool -and [string]::IsNullOrWhiteSpace($IisAppPool)) {
        Write-Host "[GUARD][FAIL] -RestartAppPool requires -IisAppPool."
        exit 1
    }

    # ---------------------------------------------------------------------------
    # 2) Resolve project root
    # ---------------------------------------------------------------------------

    $resolvedRoot = $null
    if (-not [string]::IsNullOrWhiteSpace($IisSiteName)) {
        $resolvedRoot = Resolve-IisProjectRoot -SiteName $IisSiteName
    } elseif (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
        if (-not (Test-Path -LiteralPath $ProjectRoot)) {
            Write-Host "[GUARD][FAIL] ProjectRoot not found: $ProjectRoot"
            exit 1
        }
        $resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    } else {
        Write-Host "[GUARD][FAIL] Either -IisSiteName or -ProjectRoot must be provided."
        exit 1
    }

    $managePy = Join-Path $resolvedRoot 'django_app\manage.py'
    $prodSettings = Join-Path $resolvedRoot 'django_app\config\settings\prod.py'
    if (-not (Test-Path -LiteralPath $managePy)) {
        Write-Host "[GUARD][FAIL] manage.py not found at $managePy"
        exit 1
    }
    if (-not (Test-Path -LiteralPath $prodSettings)) {
        Write-Host "[GUARD][FAIL] prod settings not found at $prodSettings"
        exit 1
    }

    # ---------------------------------------------------------------------------
    # 3) Locate web.config (read-only)
    # ---------------------------------------------------------------------------

    $resolvedWebConfig = $null
    $webConfigCandidates = @(
        (Join-Path $resolvedRoot 'web.config'),
        (Join-Path $resolvedRoot 'django_app\web.config')
    )
    foreach ($c in $webConfigCandidates) {
        if (Test-Path -LiteralPath $c) {
            $resolvedWebConfig = (Resolve-Path -LiteralPath $c).Path
            break
        }
    }

    # ---------------------------------------------------------------------------
    # 4) Init report
    # ---------------------------------------------------------------------------

    if (-not (Test-Path -LiteralPath $ReportDir)) {
        New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
    }
    $ReportDir = (Resolve-Path -LiteralPath $ReportDir).Path

    $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $script:ReportFile = Join-Path $ReportDir "deploy_guard_${Environment}_${timestamp}.log"
    New-Item -ItemType File -Path $script:ReportFile -Force | Out-Null

    Write-Log "deploy_guard.ps1 v$ScriptVersion"
    Write-Log "Timestamp        : $(Get-Date -Format 'o')"
    Write-Log "Hostname         : $env:COMPUTERNAME"
    Write-Log "User             : $env:USERNAME"
    Write-Log "Environment      : $Environment"
    Write-Log "ProjectRoot      : $resolvedRoot"
    if (-not [string]::IsNullOrWhiteSpace($IisSiteName)) {
        Write-Log "IIS Site         : $IisSiteName"
    }
    if (-not [string]::IsNullOrWhiteSpace($IisAppPool)) {
        Write-Log "IIS AppPool      : $IisAppPool"
    }
    Write-Log "SettingsModule   : $SettingsModule"
    Write-Log "PythonExe        : $PythonExe"
    if ($null -ne $resolvedWebConfig) {
        Write-Log "web.config       : $resolvedWebConfig"
    } else {
        Write-Log "web.config       : <not found> (IIS env override NOT applied via probe)"
    }
    Write-Log "Apply privattach : $([bool]$ApplyPrivateAttachments)"
    Write-Log "Delete source    : $([bool]$DeleteSourcePrivateAttachments)"
    Write-Log "Restart AppPool  : $([bool]$RestartAppPool)"
    Write-Log "Smoke URL set    : $([bool](-not [string]::IsNullOrWhiteSpace($SmokeUrl)))"
    Write-Log "StrictWarnings   : $([bool]$StrictWarnings)"
    Write-Log "NoMigrate        : $([bool]$NoMigrate)"
    Write-Log "Report file      : $script:ReportFile"
    Write-Log "NOTE: secrets are never printed nor written. Sensitive env vars appear as <set len=N>."

    # ---------------------------------------------------------------------------
    # 5) deploy_env_probe.ps1
    # ---------------------------------------------------------------------------

    Write-Section 'STEP env probe'
    $probeScript = Join-Path $PSScriptRoot 'deploy_env_probe.ps1'
    if (-not (Test-Path -LiteralPath $probeScript)) {
        Fail-Fast -Step 'env_probe' -Message "deploy_env_probe.ps1 not found at $probeScript"
    }

    # NOTA PS 5.1: lo splat con array @() di stringhe non binda parametri
    # nominati in modo affidabile (PositionalParameterNotFound). Usiamo
    # hashtable splat che e' l'unico approccio robusto.
    $probeArgs = @{
        ProjectRoot    = $resolvedRoot
        SettingsModule = $SettingsModule
        PythonExe      = $PythonExe
        ReportPath     = $script:ReportFile
    }
    if ($null -ne $resolvedWebConfig) {
        $probeArgs['WebConfigPath'] = $resolvedWebConfig
    }
    if ($Environment -eq 'prod') {
        $probeArgs['RequireProd'] = $true
    }

    Write-Log "[GUARD] -> Running: deploy_env_probe.ps1"
    & $probeScript @probeArgs
    $probeExit = $LASTEXITCODE
    if ($probeExit -ne 0) {
        Fail-Fast -Step 'env_probe' -Message "deploy_env_probe.ps1 exited with code $probeExit"
    }
    Add-StepResult -Name 'env_probe' -Status 'OK'

    # ---------------------------------------------------------------------------
    # 6) Comandi Django (pushd django_app)
    # ---------------------------------------------------------------------------

    $djangoAppPath = Join-Path $resolvedRoot 'django_app'
    Push-Location $djangoAppPath
    try {
        # Garantisci settings module nell'env per coerenza con il probe.
        Set-Item -Path 'env:DJANGO_SETTINGS_MODULE' -Value $SettingsModule

        # 6a. check
        Write-Section 'STEP django check'
        Write-Log "[GUARD] -> Running: $PythonExe manage.py check --settings=$SettingsModule"
        Invoke-NativeSafe { & $PythonExe manage.py check --settings=$SettingsModule }
        $checkExit = $LASTEXITCODE
        if ($checkExit -ne 0) {
            Fail-Fast -Step 'django_check' -Message "manage.py check exit=$checkExit"
        }
        Add-StepResult -Name 'django_check' -Status 'OK'

        # 6b. migrate
        Write-Section 'STEP django migrate'
        if ($NoMigrate) {
            Write-Log '[GUARD] migrate skipped (-NoMigrate)'
            Add-StepResult -Name 'django_migrate' -Status 'SKIP' -Detail '-NoMigrate'
        } else {
            Write-Log "[GUARD] -> Running: $PythonExe manage.py migrate --settings=$SettingsModule"
            Invoke-NativeSafe { & $PythonExe manage.py migrate --settings=$SettingsModule }
            $migrateExit = $LASTEXITCODE
            if ($migrateExit -ne 0) {
                Fail-Fast -Step 'django_migrate' -Message "manage.py migrate exit=$migrateExit"
            }
            Add-StepResult -Name 'django_migrate' -Status 'OK'
        }

        # 6c. validate_deployment
        Write-Section 'STEP validate_deployment'
        Write-Log "[GUARD] -> Running: $PythonExe manage.py validate_deployment --settings=$SettingsModule"
        # NOTE PS 5.1: vedi Invoke-NativeSafe (stderr+EAP=Stop -> NativeCommandError).
        $validateOutput = Invoke-NativeSafe { & $PythonExe manage.py validate_deployment --settings=$SettingsModule 2>&1 | Out-String }
        $validateExit = $LASTEXITCODE
        Write-Log $validateOutput.TrimEnd()

        if ($validateExit -ne 0) {
            Fail-Fast -Step 'validate_deployment' -Message "validate_deployment exit=$validateExit"
        }

        $okCount = -1
        $warnCount = -1
        $failCount = -1
        $summaryMatch = [regex]::Match($validateOutput, 'Summary:\s*OK=(\d+)\s+WARN=(\d+)\s+FAIL=(\d+)')
        if ($summaryMatch.Success) {
            $okCount   = [int]$summaryMatch.Groups[1].Value
            $warnCount = [int]$summaryMatch.Groups[2].Value
            $failCount = [int]$summaryMatch.Groups[3].Value
            Write-Log "[GUARD] validate_deployment summary: OK=$okCount WARN=$warnCount FAIL=$failCount"
        } else {
            Fail-Fast -Step 'validate_deployment' -Message 'Summary line not found in validate_deployment output.'
        }

        # Tech-debt noto
        if ($validateOutput -match 'RuntimeWarning: Accessing the database during app initialization is discouraged') {
            Write-Log '[GUARD] TECH-DEBT noted: validate_deployment touches DB during app init (RuntimeWarning).'
        }

        if ($failCount -gt 0) {
            Fail-Fast -Step 'validate_deployment' -Message "validate_deployment FAIL=$failCount"
        }
        if ($warnCount -gt 0 -and $StrictWarnings) {
            Fail-Fast -Step 'validate_deployment' -Message "validate_deployment WARN=$warnCount with -StrictWarnings"
        }

        $validateDetail = "OK=$okCount WARN=$warnCount FAIL=$failCount"
        if ($warnCount -gt 0) {
            Add-StepResult -Name 'validate_deployment' -Status 'WARN' -Detail $validateDetail
        } else {
            Add-StepResult -Name 'validate_deployment' -Status 'OK' -Detail $validateDetail
        }

        # 6d. migrate_admin_deadline_attachments_private (PREVIEW)
        Write-Section 'STEP private attachments preview'
        Write-Log "[GUARD] -> Running: $PythonExe manage.py migrate_admin_deadline_attachments_private --settings=$SettingsModule -v 2 (preview)"
        $previewOutput = Invoke-NativeSafe { & $PythonExe manage.py migrate_admin_deadline_attachments_private --settings=$SettingsModule -v 2 2>&1 | Out-String }
        $previewExit = $LASTEXITCODE
        Write-Log $previewOutput.TrimEnd()
        if ($previewExit -ne 0) {
            Fail-Fast -Step 'private_attachments_preview' -Message "preview exit=$previewExit"
        }
        $previewMatch = [regex]::Match($previewOutput, '(APPLY|DRY-RUN):\s*copied=(\d+)\s+skipped=(\d+)\s+missing=(\d+)\s+deleted=(\d+)\s+updated=(\d+)\s+collisions=(\d+)')
        $previewDetail = ''
        if ($previewMatch.Success) {
            $previewDetail = "{0} copied={1} skipped={2} missing={3} deleted={4} updated={5} collisions={6}" -f `
                $previewMatch.Groups[1].Value, $previewMatch.Groups[2].Value, $previewMatch.Groups[3].Value, `
                $previewMatch.Groups[4].Value, $previewMatch.Groups[5].Value, $previewMatch.Groups[6].Value, `
                $previewMatch.Groups[7].Value
            Write-Log "[GUARD] private attachments preview: $previewDetail"
        } else {
            Write-Log '[GUARD][WARN] private attachments preview output did not contain expected summary line.'
        }
        Add-StepResult -Name 'private_attachments_preview' -Status 'OK' -Detail $previewDetail

        # 6e. APPLY (opzionale, doppio-flag richiesto per delete-source)
        if ($ApplyPrivateAttachments) {
            Write-Section 'STEP private attachments apply'
            $applyArgs = @('manage.py', 'migrate_admin_deadline_attachments_private', "--settings=$SettingsModule", '--apply', '-v', '2')
            if ($DeleteSourcePrivateAttachments -and $ConfirmDeleteSource) {
                $applyArgs += '--delete-source'
                Write-Log '[GUARD] --delete-source enabled (double opt-in confirmed).'
            }
            Write-Log "[GUARD] -> Running: $PythonExe $($applyArgs -join ' ')"
            $applyOutput = Invoke-NativeSafe { & $PythonExe @applyArgs 2>&1 | Out-String }
            $applyExit = $LASTEXITCODE
            Write-Log $applyOutput.TrimEnd()
            if ($applyExit -ne 0) {
                Fail-Fast -Step 'private_attachments_apply' -Message "apply exit=$applyExit"
            }
            $applyMatch = [regex]::Match($applyOutput, '(APPLY|DRY-RUN):\s*copied=(\d+)\s+skipped=(\d+)\s+missing=(\d+)\s+deleted=(\d+)\s+updated=(\d+)\s+collisions=(\d+)')
            $applyDetail = ''
            if ($applyMatch.Success) {
                $applyDetail = "{0} copied={1} skipped={2} missing={3} deleted={4} updated={5} collisions={6}" -f `
                    $applyMatch.Groups[1].Value, $applyMatch.Groups[2].Value, $applyMatch.Groups[3].Value, `
                    $applyMatch.Groups[4].Value, $applyMatch.Groups[5].Value, $applyMatch.Groups[6].Value, `
                    $applyMatch.Groups[7].Value
                Write-Log "[GUARD] private attachments apply: $applyDetail"
            } else {
                Write-Log '[GUARD][WARN] private attachments apply output did not contain expected summary line.'
            }
            Add-StepResult -Name 'private_attachments_apply' -Status 'OK' -Detail $applyDetail
        } else {
            Add-StepResult -Name 'private_attachments_apply' -Status 'SKIP' -Detail 'flag not provided'
        }
    } finally {
        Pop-Location
    }

    # ---------------------------------------------------------------------------
    # 7) Restart App Pool
    # ---------------------------------------------------------------------------

    Write-Section 'STEP iis app pool restart'
    if ($RestartAppPool) {
        try {
            Import-Module WebAdministration -ErrorAction Stop
        } catch {
            Fail-Fast -Step 'iis_restart' -Message "WebAdministration module not available: $($_.Exception.Message)"
        }
        if (-not (Test-Path -Path "IIS:\AppPools\$IisAppPool")) {
            Fail-Fast -Step 'iis_restart' -Message "App pool '$IisAppPool' not found in IIS:\AppPools"
        }
        Write-Log "[GUARD] -> Restarting IIS App Pool '$IisAppPool'"
        Restart-WebAppPool -Name $IisAppPool
        Add-StepResult -Name 'iis_restart' -Status 'OK' -Detail "pool=$IisAppPool"
    } else {
        Write-Log '[GUARD] App pool restart skipped (-RestartAppPool not provided).'
        Add-StepResult -Name 'iis_restart' -Status 'SKIP' -Detail 'flag not provided'
    }

    # ---------------------------------------------------------------------------
    # 8) Smoke
    # ---------------------------------------------------------------------------

    Write-Section 'STEP smoke'
    if (-not [string]::IsNullOrWhiteSpace($SmokeUrl)) {
        $smokeScript = Join-Path $PSScriptRoot 'deploy_smoke.ps1'
        if (-not (Test-Path -LiteralPath $smokeScript)) {
            Write-Log "[GUARD][WARN] deploy_smoke.ps1 not found at $smokeScript - skipping smoke."
            Add-StepResult -Name 'smoke' -Status 'WARN' -Detail 'smoke script missing'
        } else {
            # DEPLOY-GUARD-01B: propaga -Environment cosi' che lo smoke
            # renda /version obbligatorio in prod.
            # NOTA PS 5.1: hashtable splat (vedi commento sopra su probeArgs).
            $smokeArgs = @{
                BaseUrl     = $SmokeUrl
                ReportPath  = $script:ReportFile
                Environment = $Environment
            }
            if ($AllowSelfSignedCert) {
                $smokeArgs['AllowSelfSignedCert'] = $true
            }
            Write-Log "[GUARD] -> Running: deploy_smoke.ps1 -BaseUrl $SmokeUrl -Environment $Environment"
            & $smokeScript @smokeArgs
            $smokeExit = $LASTEXITCODE
            if ($smokeExit -ne 0) {
                Write-Log "[GUARD][WARN] smoke exited with code $smokeExit (post-deploy issue)."
                Add-StepResult -Name 'smoke' -Status 'FAIL' -Detail "exit=$smokeExit"
                $script:SmokeFailed = $true
            } else {
                Add-StepResult -Name 'smoke' -Status 'OK'
            }
        }
    } else {
        Write-Log '[GUARD] Smoke skipped (-SmokeUrl not provided).'
        Add-StepResult -Name 'smoke' -Status 'SKIP' -Detail '-SmokeUrl not provided'
    }
} catch {
    # Eccezione lanciata da Fail-Fast o errore non gestito.
    if (-not $script:CriticalFailed) {
        Write-Log "[GUARD][FAIL] Unhandled exception: $($_.Exception.Message)"
        Add-StepResult -Name 'unhandled' -Status 'FAIL' -Detail $_.Exception.Message
        $script:CriticalFailed = $true
    }
} finally {
    # Riporta location originale se Push-Location aveva ancora effetto
    try {
        Set-Location $script:OriginalLocation
    } catch {
        # ignora
    }

    Write-Section 'SUMMARY'
    if ($script:StepResults.Count -gt 0) {
        $summaryText = ($script:StepResults | Format-Table -AutoSize | Out-String).Trim()
        Write-Log $summaryText
    } else {
        Write-Log '(no steps recorded)'
    }

    $finalExit = 0
    if ($script:CriticalFailed) {
        $finalExit = 1
    } elseif ($script:SmokeFailed) {
        $finalExit = 2
    }

    Write-Log ''
    Write-Log "[GUARD] CriticalFailed=$($script:CriticalFailed) SmokeFailed=$($script:SmokeFailed)"
    Write-Log "[GUARD] Exit code: $finalExit"
    if ($null -ne $script:ReportFile) {
        Write-Host "[GUARD] Report: $script:ReportFile"
    }

    exit $finalExit
}
