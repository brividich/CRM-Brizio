param(
    [string]$SourcePath = "",
    [switch]$Quiet,
    [int]$AclMaxMissing = 222,
    [switch]$FailOnDeploymentWarn,
    [string]$ArtifactDir = "",
    # -WithLive abilita i contract test livello B (toccano Graph/LDAP/SMTP reali).
    # Usare prima di un release significativa o quando si sospetta una rotazione
    # di credenziali. Richiede config\.env.test con integrazioni configurate.
    [switch]$WithLive,
    # -WithTests abilita la test suite Django e i contract test.
    # Di default i test sono saltati per velocizzare la build locale.
    [switch]$WithTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $SourcePath) {
    $SourcePath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $SourcePath = (Resolve-Path $SourcePath).Path
}

$failures = [System.Collections.Generic.List[string]]::new()

if (-not $ArtifactDir) {
    $ArtifactDir = Join-Path $SourcePath "django_app"
} else {
    if ([System.IO.Path]::IsPathRooted($ArtifactDir)) {
        $ArtifactDir = [System.IO.Path]::GetFullPath($ArtifactDir)
    } else {
        $ArtifactDir = [System.IO.Path]::GetFullPath((Join-Path $SourcePath $ArtifactDir))
    }
}

function Write-GuardInfo {
    param([string]$Message)
    if (-not $Quiet) {
        Write-Host "[release_guard] $Message"
    }
}

function Add-Failure {
    param([string]$Message)
    $script:failures.Add($Message)
    Write-Host "[release_guard][FAIL] $Message" -ForegroundColor Red
}

function Write-TextArtifact {
    param(
        [string]$Path,
        [string[]]$Lines
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        [void](New-Item -ItemType Directory -Path $parent -Force)
    }
    $text = ($Lines -join [System.Environment]::NewLine)
    [System.IO.File]::WriteAllText($Path, $text, [System.Text.UTF8Encoding]::new($false))
}

function Invoke-GuardCommand {
    param(
        [string]$PythonExe,
        [string]$ManagePy,
        [string[]]$Arguments,
        [string]$Label,
        [string]$ArtifactPath = "",
        [string[]]$FailOnOutputPattern = @(),
        [string]$FailOnOutputMessage = ""
    )

    Write-GuardInfo "Eseguo ${Label}: $PythonExe $ManagePy $($Arguments -join ' ')"
    Push-Location $SourcePath
    $previousErrorActionPreference = $ErrorActionPreference
    $tempRoot = Join-Path $SourcePath ".tmp_tests\release_guard"
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $stdoutPath = Join-Path $tempRoot ("stdout-{0}.log" -f ([guid]::NewGuid().ToString("N")))
    $stderrPath = Join-Path $tempRoot ("stderr-{0}.log" -f ([guid]::NewGuid().ToString("N")))
    try {
        $ErrorActionPreference = "Continue"
        & $PythonExe $ManagePy @Arguments 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
        $stdout = @(Get-Content -LiteralPath $stdoutPath -ErrorAction SilentlyContinue | ForEach-Object { "$_" })
        $stderr = @(Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue | ForEach-Object { "$_" })
        $output = @($stdout + $stderr)
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        foreach ($tempPath in @($stdoutPath, $stderrPath)) {
            if ($tempPath -and (Test-Path -LiteralPath $tempPath)) {
                Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
            }
        }
        Pop-Location
    }

    if ($ArtifactPath) {
        Write-TextArtifact -Path $ArtifactPath -Lines $stdout
        Write-GuardInfo "Artifact aggiornato: $ArtifactPath"
    }

    if ($exitCode -ne 0) {
        Add-Failure("$Label fallito con exit code $exitCode")
        if (-not $Quiet) {
            $output | ForEach-Object { Write-Host "  $_" }
        }
    }

    if ($FailOnOutputPattern.Count -gt 0) {
        $outputText = $output -join [System.Environment]::NewLine
        foreach ($pattern in $FailOnOutputPattern) {
            if ([regex]::IsMatch($outputText, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
                if ($FailOnOutputMessage) {
                    Add-Failure($FailOnOutputMessage)
                } else {
                    Add-Failure("$Label ha prodotto output non valido: $pattern")
                }
                if (-not $Quiet) {
                    $output | ForEach-Object { Write-Host "  $_" }
                }
                break
            }
        }
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Assert-FileExists {
    param(
        [string]$Path,
        [string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Failure("$Label mancante: $Path")
        return $false
    }
    return $true
}

function Read-Text {
    param([string]$Path)
    return [System.IO.File]::ReadAllText($Path)
}

function Read-FirstLine {
    param([string]$Path)
    return (Get-Content -LiteralPath $Path -TotalCount 1 -Encoding UTF8).Trim()
}

function Assert-Contains {
    param(
        [string]$Text,
        [string]$Needle,
        [string]$Label
    )
    if (-not $Text.Contains($Needle)) {
        Add-Failure("$Label deve contenere: $Needle")
    }
}

function Assert-Regex {
    param(
        [string]$Text,
        [string]$Pattern,
        [string]$Label
    )
    if (-not [regex]::IsMatch($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::Multiline)) {
        Add-Failure("$Label non soddisfa il pattern richiesto: $Pattern")
    }
}

function Resolve-Python {
    param([string]$RootPath)

    $venvPython = Join-Path $RootPath ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    $altVenvPython = Join-Path $RootPath "venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $altVenvPython) {
        return $altVenvPython
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }

    return $null
}

$versionPath = Join-Path $SourcePath "VERSION"
if (-not (Assert-FileExists -Path $versionPath -Label "VERSION")) {
    exit 1
}
$version = Read-FirstLine $versionPath
Write-GuardInfo "Versione canonica rilevata: $version"

$paths = @{
    Readme = Join-Path $SourcePath "README.md"
    Claude = Join-Path $SourcePath "CLAUDE.md"
    Changelog = Join-Path $SourcePath "CHANGELOG.md"
    DocIndex = Join-Path $SourcePath "doc\README.md"
    StartHere = Join-Path $SourcePath "doc\START_HERE.md"
    Testing = Join-Path $SourcePath "doc\TESTING.md"
    Architecture = Join-Path $SourcePath "doc\ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md"
    Structure = Join-Path $SourcePath "doc\STRUTTURA_ATTUALE_PORTALE.md"
    DeployGuide = Join-Path $SourcePath "deployment\README_DEPLOY_IIS_WINDOWS.md"
    AdminManual = Join-Path $SourcePath "tools\MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md"
    EnvExample = Join-Path $SourcePath "django_app\.env.example"
    AppVersion = Join-Path $SourcePath "django_app\config\app_version.py"
    DjangoVersion = Join-Path $SourcePath "django_app\VERSION"
    SetupWizard = Join-Path $SourcePath "deployment\setup_wizard.py"
    SetupWizardExe = Join-Path $SourcePath "deployment\dist\SetupWizard.exe"
    SetupWizardSpec = Join-Path $SourcePath "deployment\SetupWizard.spec"
    SetupWizardBundleRules = Join-Path $SourcePath "deployment\setup_wizard_bundle_rules.json"
    PackageRelease = Join-Path $SourcePath "deployment\scripts\package-release.ps1"
}

foreach ($entry in $paths.GetEnumerator()) {
    [void](Assert-FileExists -Path $entry.Value -Label $entry.Key)
}

$readmeText = Read-Text $paths.Readme
$claudeText = Read-Text $paths.Claude
$changelogText = Read-Text $paths.Changelog
$docIndexText = Read-Text $paths.DocIndex
$startHereText = Read-Text $paths.StartHere
$testingText = Read-Text $paths.Testing
$architectureText = Read-Text $paths.Architecture
$structureText = Read-Text $paths.Structure
$deployGuideText = Read-Text $paths.DeployGuide
$adminManualText = Read-Text $paths.AdminManual
$envExampleText = Read-Text $paths.EnvExample
$appVersionText = Read-Text $paths.AppVersion
$setupWizardText = Read-Text $paths.SetupWizard
$setupWizardSpecText = Read-Text $paths.SetupWizardSpec
$packageReleaseText = Read-Text $paths.PackageRelease
$setupWizardBundleRulesText = Read-Text $paths.SetupWizardBundleRules

Assert-Regex -Text $readmeText -Pattern ("version-" + [regex]::Escape($version)) -Label "README.md"
Assert-Contains -Text $readmeText -Needle "doc/START_HERE.md" -Label "README.md"
Assert-Contains -Text $readmeText -Needle "doc/TESTING.md" -Label "README.md"
Assert-Contains -Text $readmeText -Needle "doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md" -Label "README.md"

Assert-Contains -Text $claudeText -Needle ("Versione app corrente: **{0}**" -f $version) -Label "CLAUDE.md"
Assert-Contains -Text $claudeText -Needle "tools/release_guard.ps1" -Label "CLAUDE.md"
Assert-Contains -Text $claudeText -Needle "_load_dotenv(...)" -Label "CLAUDE.md"

Assert-Regex -Text $changelogText -Pattern ("^##\s+" + [regex]::Escape($version) + "\s+-\s+") -Label "CHANGELOG.md"
Assert-Contains -Text $changelogText -Needle "NOVICROM HUB" -Label "CHANGELOG.md"

Assert-Contains -Text $docIndexText -Needle ("**{0}**" -f $version) -Label "doc/README.md"
Assert-Contains -Text $docIndexText -Needle "START_HERE.md" -Label "doc/README.md"
Assert-Contains -Text $docIndexText -Needle "../CHANGELOG.md" -Label "doc/README.md"

Assert-Contains -Text $startHereText -Needle ("**{0}**" -f $version) -Label "doc/START_HERE.md"
Assert-Contains -Text $startHereText -Needle "Sviluppatore" -Label "doc/START_HERE.md"
Assert-Contains -Text $startHereText -Needle "Admin Funzionale" -Label "doc/START_HERE.md"
Assert-Contains -Text $startHereText -Needle "Deployer" -Label "doc/START_HERE.md"
Assert-Contains -Text $startHereText -Needle "Tester / UAT" -Label "doc/START_HERE.md"

Assert-Contains -Text $testingText -Needle ("**{0}**" -f $version) -Label "doc/TESTING.md"
Assert-Contains -Text $testingText -Needle "config.settings.dev" -Label "doc/TESTING.md"
Assert-Contains -Text $testingText -Needle "config.settings.test" -Label "doc/TESTING.md"
Assert-Contains -Text $testingText -Needle "config.settings.prod" -Label "doc/TESTING.md"
Assert-Contains -Text $testingText -Needle "_load_dotenv(...)" -Label "doc/TESTING.md"

Assert-Contains -Text $architectureText -Needle ("**{0}**" -f $version) -Label "doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md"
Assert-Contains -Text $architectureText -Needle "legacy-only" -Label "doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md"
Assert-Contains -Text $architectureText -Needle "legacy_fallback" -Label "doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md"
Assert-Contains -Text $architectureText -Needle "canonico" -Label "doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md"
Assert-Contains -Text $architectureText -Needle "ibrido" -Label "doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md"

Assert-Contains -Text $structureText -Needle ("Versione: {0}" -f $version) -Label "doc/STRUTTURA_ATTUALE_PORTALE.md"
Assert-Contains -Text $structureText -Needle "_load_dotenv(...)" -Label "doc/STRUTTURA_ATTUALE_PORTALE.md"

Assert-Contains -Text $deployGuideText -Needle ("**{0}**" -f $version) -Label "deployment/README_DEPLOY_IIS_WINDOWS.md"
Assert-Contains -Text $deployGuideText -Needle "config.settings.dev" -Label "deployment/README_DEPLOY_IIS_WINDOWS.md"
Assert-Contains -Text $deployGuideText -Needle "config.settings.test" -Label "deployment/README_DEPLOY_IIS_WINDOWS.md"
Assert-Contains -Text $deployGuideText -Needle "config.settings.prod" -Label "deployment/README_DEPLOY_IIS_WINDOWS.md"
Assert-Contains -Text $deployGuideText -Needle "_load_dotenv(...)" -Label "deployment/README_DEPLOY_IIS_WINDOWS.md"
Assert-Contains -Text $deployGuideText -Needle "tools/release_guard.ps1" -Label "deployment/README_DEPLOY_IIS_WINDOWS.md"

Assert-Contains -Text $adminManualText -Needle ("v{0}" -f $version) -Label "tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md"
Assert-Contains -Text $adminManualText -Needle "ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md" -Label "tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md"

Assert-Contains -Text $envExampleText -Needle ("APP_VERSION={0}" -f $version) -Label "django_app/.env.example"
Assert-Contains -Text $envExampleText -Needle "INSTANCE_NAME=NOVICROM HUB" -Label "django_app/.env.example"

$envVersionMatches = [regex]::Matches($envExampleText, '(?m)^APP_VERSION(?:_[A-Z_]+)?=(.+)$')
foreach ($match in $envVersionMatches) {
    $value = $match.Groups[1].Value.Trim()
    if ($value -ne $version) {
        Add-Failure("django_app/.env.example contiene una APP_VERSION fuori sync: $($match.Value)")
    }
}

Assert-Contains -Text $appVersionText -Needle ('DEFAULT_APP_VERSION = "{0}"' -f $version) -Label "django_app/config/app_version.py"
Assert-Contains -Text $setupWizardText -Needle ('_DEFAULT_APP_VERSION = "{0}"' -f $version) -Label "deployment/setup_wizard.py"

$djangoVersion = Read-FirstLine $paths.DjangoVersion
if ($djangoVersion -ne $version) {
    Add-Failure("django_app/VERSION non allineato a VERSION (root=$version, django_app=$djangoVersion)")
}

$brandFiles = @(
    $paths.Readme,
    $paths.Claude,
    $paths.DocIndex,
    $paths.StartHere,
    $paths.Testing,
    $paths.Architecture,
    $paths.Structure,
    $paths.DeployGuide,
    $paths.AdminManual,
    $paths.EnvExample
)
$legacyBrandPattern = '\b(BoluHUB|BrizioHUB)\b'
foreach ($path in $brandFiles) {
    $text = Read-Text $path
    if ([regex]::IsMatch($text, $legacyBrandPattern)) {
        Add-Failure("Brand legacy trovato nel file canonico: $path")
    }
}

$forbiddenSnippets = @(
    "environ.Env.read_env(",
    "env = environ.Env()",
    "import environ, os"
)
$snippetFiles = @(
    $paths.Readme,
    $paths.Claude,
    $paths.DocIndex,
    $paths.StartHere,
    $paths.Testing,
    $paths.Architecture,
    $paths.Structure,
    $paths.DeployGuide,
    $paths.AdminManual
)
foreach ($path in $snippetFiles) {
    $text = Read-Text $path
    foreach ($snippet in $forbiddenSnippets) {
        if ($text.Contains($snippet)) {
            Add-Failure("Snippet obsoleto trovato in ${path}: $snippet")
        }
    }
}

Assert-Contains -Text $packageReleaseText -Needle "release_guard.ps1" -Label "deployment/scripts/package-release.ps1"
Assert-Contains -Text $setupWizardSpecText -Needle "setup_wizard_bundle_rules.json" -Label "deployment/SetupWizard.spec"

$bundleRules = $null
try {
    $bundleRules = $setupWizardBundleRulesText | ConvertFrom-Json
} catch {
    Add-Failure("deployment/setup_wizard_bundle_rules.json non e JSON valido: $($_.Exception.Message)")
}

if (-not ($bundleRules -and $bundleRules.exclude_dir_names)) {
    Add-Failure("deployment/setup_wizard_bundle_rules.json deve definire exclude_dir_names")
}
if (-not ($bundleRules -and $bundleRules.exclude_file_patterns)) {
    Add-Failure("deployment/setup_wizard_bundle_rules.json deve definire exclude_file_patterns")
}

$setupWizardExeInfo = Get-Item -LiteralPath $paths.SetupWizardExe
$triggerFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
$triggerFiles.Add((Get-Item -LiteralPath $versionPath))
$triggerFiles.Add((Get-Item -LiteralPath $paths.SetupWizard))
$triggerFiles.Add((Get-Item -LiteralPath $paths.SetupWizardSpec))
$triggerFiles.Add((Get-Item -LiteralPath $paths.SetupWizardBundleRules))

$deploymentScriptDir = Join-Path $SourcePath "deployment\scripts"
if (Test-Path -LiteralPath $deploymentScriptDir) {
    foreach ($file in (Get-ChildItem -LiteralPath $deploymentScriptDir -File -Recurse -ErrorAction SilentlyContinue)) {
        $triggerFiles.Add($file)
    }
}

$deploymentConfigDir = Join-Path $SourcePath "deployment\config"
if (Test-Path -LiteralPath $deploymentConfigDir) {
    foreach ($file in (Get-ChildItem -LiteralPath $deploymentConfigDir -File -Recurse -ErrorAction SilentlyContinue)) {
        $triggerFiles.Add($file)
    }
}

# django_app/ escluso intenzionalmente dai trigger del wizard:
# gli aggiornamenti applicativi usano il pacchetto zip + deploy-release.ps1,
# non richiedono la rebuild del wizard (riservato alle installazioni fresh).

$newestTrigger = $triggerFiles | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
$wizardFreshnessGrace = [TimeSpan]::FromMinutes(2)
$wizardStaleness = $newestTrigger.LastWriteTimeUtc - $setupWizardExeInfo.LastWriteTimeUtc
if ($wizardStaleness -gt $wizardFreshnessGrace) {
    Add-Failure(
        "deployment/dist/SetupWizard.exe obsoleto rispetto a $($newestTrigger.FullName) " +
        "(exe=$($setupWizardExeInfo.LastWriteTimeUtc.ToString('u')), trigger=$($newestTrigger.LastWriteTimeUtc.ToString('u')))"
    )
} elseif ($wizardStaleness.TotalSeconds -gt 0 -and -not $Quiet) {
    Write-GuardInfo(
        "SetupWizard.exe rientra nella finestra di tolleranza (" +
        "$([math]::Round($wizardStaleness.TotalSeconds, 1))s) rispetto a $($newestTrigger.FullName)"
    )
}

$pythonExe = Resolve-Python -RootPath $SourcePath
if (-not $pythonExe) {
    Add-Failure("Python non trovato. Serve per eseguire i controlli Django del release guard.")
} else {
    $djangoManage = Join-Path $SourcePath "django_app\manage.py"
    $aclArtifact = Join-Path $ArtifactDir "acl_report_latest.json"
    $deploymentArtifact = Join-Path $ArtifactDir "deployment_validation_latest.json"

    # Raccoglie il risultato di un job parallelo e aggiunge eventuali fallimenti.
    function Receive-GuardJobResult {
        param(
            [System.Management.Automation.Job]$Job,
            [string]$Label,
            [string[]]$FailOnPattern = @(),
            [string]$FailOnMessage = ""
        )
        $r = Receive-Job -Job $Job -Wait -AutoRemoveJob
        $exitCode = if ($null -eq $r) { -1 } else { [int]$r.ExitCode }
        $output   = if ($null -eq $r) { @() } else { @($r.Output) }
        if ($exitCode -ne 0) {
            $script:failures.Add("$Label fallito con exit code $exitCode")
            Write-Host "[release_guard][FAIL] $Label fallito con exit code $exitCode" -ForegroundColor Red
            if (-not $Quiet) { $output | ForEach-Object { Write-Host "  $_" } }
            return
        }
        if ($FailOnPattern.Count -gt 0) {
            $outputText = $output -join "`n"
            foreach ($pattern in $FailOnPattern) {
                if ([regex]::IsMatch($outputText, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
                    $msg = if ($FailOnMessage) { $FailOnMessage } else { "$Label ha prodotto output non valido: $pattern" }
                    $script:failures.Add($msg)
                    Write-Host "[release_guard][FAIL] $msg" -ForegroundColor Red
                    if (-not $Quiet) { $output | ForEach-Object { Write-Host "  $_" } }
                    return
                }
            }
        }
        Write-GuardInfo "$Label OK"
    }

    # ── WAVE 1: check stateless in parallelo ──────────────────────────────────
    # check, makemigrations --check e secret_hygiene_check non toccano il test DB
    # condiviso e possono girare in background mentre la test suite avanza.
    # I contract test usano un loro DB isolato (test_<name>): stessa logica.
    Write-GuardInfo "WAVE 1: avvio in background check, migrations, hygiene e contract tests..."

    $jobCheck = Start-Job -ScriptBlock {
        Set-Location $using:SourcePath
        $out = & $using:pythonExe $using:djangoManage check --settings=config.settings.test 2>&1 | ForEach-Object { "$_" }
        [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $out }
    }

    $jobMigrations = Start-Job -ScriptBlock {
        Set-Location $using:SourcePath
        $out = & $using:pythonExe $using:djangoManage makemigrations --check --dry-run 2>&1 | ForEach-Object { "$_" }
        [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $out }
    }

    $jobHygiene = Start-Job -ScriptBlock {
        Set-Location $using:SourcePath
        $out = & $using:pythonExe $using:djangoManage secret_hygiene_check 2>&1 | ForEach-Object { "$_" }
        [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $out }
    }

    if (-not $WithTests) {
        Write-GuardInfo "WARN: -WithTests non specificato - test suite e contract tests SALTATI."
        Write-Host "[release_guard][WARN] Test suite saltata. Usa -WithTests per eseguirla." -ForegroundColor Yellow
        $jobContracts = $null
    } else {
        # Contract test: usano DB isolato (test_<name>), compatibili col background.
        # --parallel sfrutta i core disponibili per ridurre il tempo di esecuzione.
        $jobContracts = Start-Job -ScriptBlock {
            Set-Location $using:SourcePath
            $out = & $using:pythonExe $using:djangoManage test core.contract_tests --settings=config.settings.test --parallel 2>&1 | ForEach-Object { "$_" }
            [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $out }
        }

        # Test suite principale (foreground): --parallel usa i core disponibili.
        # manage.py test crea un DB isolato (test_<name>) distinto dal test DB
        # di bootstrap_acl_v2, quindi non interferisce con i job paralleli.
        # La discovery globale da repo root non entra in django_app/ (non e un package);
        # il gate usa le app project-critical gia validate.
        [void](Invoke-GuardCommand `
            -PythonExe $pythonExe `
            -ManagePy $djangoManage `
            -Arguments @("test", "core", "tasks", "attrezzature", "monitoring.tests", "monitoring.test_health", "--settings=config.settings.test", "--parallel") `
            -Label "Django test suite" `
            -FailOnOutputPattern @("Found 0 test", "NO TESTS RAN") `
            -FailOnOutputMessage "Test gate invalid because Django discovered zero tests.")
    }

    # Raccolta Wave 1
    Receive-GuardJobResult -Job $jobCheck       -Label "Django check"
    Receive-GuardJobResult -Job $jobMigrations  -Label "makemigrations --check"
    Receive-GuardJobResult -Job $jobHygiene     -Label "secret_hygiene_check"
    if ($null -ne $jobContracts) {
        Receive-GuardJobResult -Job $jobContracts -Label "Contract tests (livello A)" `
            -FailOnPattern @("Found 0 test", "NO TESTS RAN") `
            -FailOnMessage "Contract tests gate invalid: zero tests scoperti."
    }

    # ── WAVE 2: bootstrap + ACL coverage + validation (sequenziali) ──────────
    # Queste operazioni scrivono/leggono il test DB condiviso e devono restare
    # sequenziali tra loro. Girano dopo Wave 1 per garantire che il DB sia pronto.
    [void](Invoke-GuardCommand `
        -PythonExe $pythonExe `
        -ManagePy $djangoManage `
        -Arguments @("bootstrap_acl_v2", "--apply", "--settings=config.settings.test") `
        -Label "bootstrap_acl_v2 --apply (test DB)")

    [void](Invoke-GuardCommand `
        -PythonExe $pythonExe `
        -ManagePy $djangoManage `
        -Arguments @("acl_coverage_report", "--max-missing", "$AclMaxMissing", "--settings=config.settings.test") `
        -Label "acl_coverage_report --max-missing $AclMaxMissing")

    [void](Invoke-GuardCommand `
        -PythonExe $pythonExe `
        -ManagePy $djangoManage `
        -Arguments @("acl_coverage_report", "--format", "json", "--settings=config.settings.test") `
        -Label "acl_coverage_report JSON artifact" `
        -ArtifactPath $aclArtifact)

    $deploymentValidationArgs = @("validate_deployment", "--format", "json", "--settings=config.settings.test")
    if ($FailOnDeploymentWarn) {
        $deploymentValidationArgs += "--fail-on-warn"
    }
    [void](Invoke-GuardCommand `
        -PythonExe $pythonExe `
        -ManagePy $djangoManage `
        -Arguments $deploymentValidationArgs `
        -Label "validate_deployment JSON artifact" `
        -ArtifactPath $deploymentArtifact)

    if ($WithLive) {
        Write-GuardInfo "Eseguo contract test livello B (live integration). Richiedono credenziali reali."
        $env:RUN_LIVE_INTEGRATION_TESTS = "1"
        try {
            [void](Invoke-GuardCommand `
                -PythonExe $pythonExe `
                -ManagePy $djangoManage `
                -Arguments @("test", "core.contract_tests", "--tag", "live_integration", "--settings=config.settings.test") `
                -Label "Contract tests live (livello B)")
        } finally {
            Remove-Item Env:RUN_LIVE_INTEGRATION_TESTS -ErrorAction SilentlyContinue
        }
    }
}

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "[release_guard] Controlli falliti: $($failures.Count)" -ForegroundColor Red
    exit 1
}

Write-Host "[release_guard] OK - documentazione, versioni, wizard, hygiene, ACL e validazione deploy sono coerenti." -ForegroundColor Green
exit 0
