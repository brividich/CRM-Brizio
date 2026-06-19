<#
.SYNOPSIS
    Ricompila il bundle UI della pagina "Gestione Anomalie".

.DESCRIPTION
    La pagina /gestione-anomalie usa React (UMD, build di produzione) con un
    componente unico. Il sorgente versionato e' :

        django_app/anomalie/static/anomalie/js/src/gestione_anomalie.jsx

    e viene transpilato offline (solo JSX, @babel/preset-react) nel bundle
    committato:

        django_app/anomalie/static/anomalie/js/gestione_anomalie.bundle.js

    Il runtime di produzione (Waitress/IIS) NON esegue npm: il bundle e i file
    react*.production.min.js sono artefatti committati. Questo script serve solo
    in fase di sviluppo, quando si modifica il .jsx.

    Requisiti: Node.js + npm nel PATH. Le dipendenze Babel vengono installate in
    una cartella temporanea (non toccano il repo).

.EXAMPLE
    pwsh tools/build_anomalie_ui.ps1
#>
[CmdletBinding()]
param(
    [string]$ReactVersion = "18.3.1"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$jsDir = Join-Path $repoRoot "django_app/anomalie/static/anomalie/js"
$src = Join-Path $jsDir "src/gestione_anomalie.jsx"
$bundle = Join-Path $jsDir "gestione_anomalie.bundle.js"

if (-not (Test-Path $src)) { throw "Sorgente JSX non trovato: $src" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm non e' nel PATH: installa Node.js." }

$build = Join-Path ([System.IO.Path]::GetTempPath()) "anomalie_ui_build"
New-Item -ItemType Directory -Force -Path $build | Out-Null
Push-Location $build
try {
    if (-not (Test-Path (Join-Path $build "package.json"))) {
        npm init -y | Out-Null
    }
    Write-Host "Installo la toolchain Babel (temporanea)..."
    npm install --no-save --no-audit --no-fund "@babel/core@^7" "@babel/cli@^7" "@babel/preset-react@^7" | Out-Null

    $babel = Join-Path $build "node_modules/.bin/babel"
    $preset = Join-Path $build "node_modules/@babel/preset-react"

    Write-Host "Transpilo $src -> $bundle"
    & $babel $src --presets $preset --no-babelrc -o $bundle
    if ($LASTEXITCODE -ne 0) { throw "Transpilazione Babel fallita." }

    Write-Host "Aggiorno i build React di produzione ($ReactVersion)..."
    npm install --no-save --no-audit --no-fund "react@$ReactVersion" "react-dom@$ReactVersion" | Out-Null
    Copy-Item (Join-Path $build "node_modules/react/umd/react.production.min.js") (Join-Path $jsDir "react.production.min.js") -Force
    Copy-Item (Join-Path $build "node_modules/react-dom/umd/react-dom.production.min.js") (Join-Path $jsDir "react-dom.production.min.js") -Force

    node --check $bundle
    if ($LASTEXITCODE -ne 0) { throw "Il bundle generato non e' JavaScript valido." }
    Write-Host "OK: bundle e build React aggiornati." -ForegroundColor Green
}
finally {
    Pop-Location
}
