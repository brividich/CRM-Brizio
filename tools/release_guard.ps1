param(
    [string]$SourcePath = "",
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $SourcePath) {
    $SourcePath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $SourcePath = (Resolve-Path $SourcePath).Path
}

$failures = [System.Collections.Generic.List[string]]::new()

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

function Require-File {
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

function Test-IsExcludedByWizardBundleRules {
    param(
        [string]$BaseDir,
        [System.IO.FileInfo]$File,
        [string[]]$ExcludeDirNames,
        [string[]]$ExcludeFilePatterns
    )

    $normalizedBaseDir = [System.IO.Path]::GetFullPath($BaseDir).TrimEnd('\', '/')
    $normalizedFilePath = [System.IO.Path]::GetFullPath($File.FullName)
    if ($normalizedFilePath.StartsWith($normalizedBaseDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relativePath = $normalizedFilePath.Substring($normalizedBaseDir.Length).TrimStart('\', '/')
    } else {
        $relativePath = $File.Name
    }
    $pathSegments = $relativePath -split '[\\/]'

    if ($pathSegments.Count -gt 1) {
        $lastDirectoryIndex = $pathSegments.Count - 2
        foreach ($segment in $pathSegments[0..$lastDirectoryIndex]) {
            if ($ExcludeDirNames -contains $segment) {
                return $true
            }
        }
    }

    foreach ($pattern in $ExcludeFilePatterns) {
        if ($File.Name -like $pattern) {
            return $true
        }
    }

    return $false
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
if (-not (Require-File -Path $versionPath -Label "VERSION")) {
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
    [void](Require-File -Path $entry.Value -Label $entry.Key)
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
$wizardExcludedDirNames = @()
$wizardExcludedFilePatterns = @()
try {
    $bundleRules = $setupWizardBundleRulesText | ConvertFrom-Json
} catch {
    Add-Failure("deployment/setup_wizard_bundle_rules.json non e JSON valido: $($_.Exception.Message)")
}

if ($bundleRules -and $bundleRules.exclude_dir_names) {
    $wizardExcludedDirNames = @($bundleRules.exclude_dir_names | ForEach-Object { [string]$_ })
} else {
    Add-Failure("deployment/setup_wizard_bundle_rules.json deve definire exclude_dir_names")
}

if ($bundleRules -and $bundleRules.exclude_file_patterns) {
    $wizardExcludedFilePatterns = @($bundleRules.exclude_file_patterns | ForEach-Object { [string]$_ })
} else {
    Add-Failure("deployment/setup_wizard_bundle_rules.json deve definire exclude_file_patterns")
}

$setupWizardExeInfo = Get-Item -LiteralPath $paths.SetupWizardExe
$triggerFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
$triggerFiles.Add((Get-Item -LiteralPath $versionPath))
$triggerFiles.Add((Get-Item -LiteralPath $paths.SetupWizard))
$triggerFiles.Add((Get-Item -LiteralPath $paths.SetupWizardSpec))

$deploymentScriptDir = Join-Path $SourcePath "deployment\scripts"
if (Test-Path -LiteralPath $deploymentScriptDir) {
    foreach ($file in (Get-ChildItem -LiteralPath $deploymentScriptDir -File -Recurse)) {
        $triggerFiles.Add($file)
    }
}

$deploymentConfigDir = Join-Path $SourcePath "deployment\config"
if (Test-Path -LiteralPath $deploymentConfigDir) {
    foreach ($file in (Get-ChildItem -LiteralPath $deploymentConfigDir -File -Recurse)) {
        $triggerFiles.Add($file)
    }
}

$djangoAppDir = Join-Path $SourcePath "django_app"
if (Test-Path -LiteralPath $djangoAppDir) {
    $djangoFiles = Get-ChildItem -LiteralPath $djangoAppDir -File -Recurse | Where-Object {
        -not (Test-IsExcludedByWizardBundleRules -BaseDir $djangoAppDir -File $_ -ExcludeDirNames $wizardExcludedDirNames -ExcludeFilePatterns $wizardExcludedFilePatterns)
    }
    foreach ($file in $djangoFiles) {
        $triggerFiles.Add($file)
    }
}

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
    Add-Failure("Python non trovato. Serve per eseguire bootstrap_acl_v2 --dry-run.")
} else {
    Write-GuardInfo "Eseguo bootstrap_acl_v2 --dry-run con: $pythonExe"
    Push-Location $SourcePath
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $aclOutput = & $pythonExe manage.py bootstrap_acl_v2 --dry-run --settings=config.settings.dev 2>&1 | ForEach-Object { "$_" }
        $aclExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }

    if ($aclExitCode -ne 0) {
        Add-Failure("bootstrap_acl_v2 --dry-run fallito con exit code $aclExitCode")
        if (-not $Quiet) {
            $aclOutput | ForEach-Object { Write-Host "  $_" }
        }
    }
}

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "[release_guard] Controlli falliti: $($failures.Count)" -ForegroundColor Red
    exit 1
}

Write-Host "[release_guard] OK - documentazione, versioni, wizard e smoke ACL sono coerenti." -ForegroundColor Green
exit 0
