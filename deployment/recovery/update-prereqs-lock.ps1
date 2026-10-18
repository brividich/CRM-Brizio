# update-prereqs-lock.ps1
# Compila deployment\recovery\prereqs.lock.json: per ogni voce scarica l'installer dall'URL
# indicato (o dalle alternative), segue i redirect, VERIFICA LA FIRMA Authenticode
# (Status=Valid e firmatario atteso) e solo allora registra url_resolved, sha256, size,
# firmatario e versione. Una voce che non passa la verifica resta senza sha256:
# restore-host.ps1 non la scaricherà mai.
#
#   .\update-prereqs-lock.ps1                                  # aggiorna il lock (cache in %TEMP%)
#   .\update-prereqs-lock.ps1 -CacheDir \\nas\hub-backup\_prereqs   # e lascia gli installer nella cache del NAS
#   .\update-prereqs-lock.ps1 -Only odbc-driver-18
#
# Va rilanciato quando si vuole aggiornare un prerequisito; il lock aggiornato si committa.

[CmdletBinding()]
param(
    [string]$LockPath = "",
    [string]$CacheDir = (Join-Path $env:TEMP "pn-prereqs"),
    [string[]]$Only = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# $PSScriptRoot non è affidabile nei default dei parametri di Windows PowerShell 5.1
if (-not $LockPath) { $LockPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "prereqs.lock.json" }

function Resolve-LatestPython([string]$minor) {
    $index = (Invoke-WebRequest "https://www.python.org/ftp/python/" -UseBasicParsing).Content
    $patches = [regex]::Matches($index, "href=""$([regex]::Escape($minor))\.(\d+)/""") | ForEach-Object { [int]$_.Groups[1].Value } |
        Sort-Object -Descending -Unique
    foreach ($p in $patches) {
        $v = "$minor.$p"
        $u = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
        try { $null = Invoke-WebRequest $u -Method Head -UseBasicParsing; return $v } catch { continue }
    }
    throw "Nessun installer amd64 trovato per Python $minor"
}

function Get-FinalUrlAndDownload([string]$url, [string]$dest) {
    $resp = Invoke-WebRequest $url -UseBasicParsing -OutFile $dest -PassThru -MaximumRedirection 10
    $final = $url
    try {
        if ($resp.BaseResponse.PSObject.Properties["ResponseUri"]) { $final = [string]$resp.BaseResponse.ResponseUri }
        elseif ($resp.BaseResponse.RequestMessage) { $final = [string]$resp.BaseResponse.RequestMessage.RequestUri }
    } catch { }
    return $final
}

function Get-MsiVersion([string]$path) {
    try {
        $installer = New-Object -ComObject WindowsInstaller.Installer
        $db = $installer.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $installer, @($path, 0))
        $view = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @("SELECT Value FROM Property WHERE Property='ProductVersion'"))
        $view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null) | Out-Null
        $rec = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
        return $rec.GetType().InvokeMember("StringData", "GetProperty", $null, $rec, 1)
    } catch { return "" }
}

$lock = Get-Content $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$results = @()
foreach ($item in $lock.items) {
    if ($Only.Count -and $Only -notcontains $item.name) { continue }
    $candidates = @($item.url)
    if ($item.PSObject.Properties["url_alternatives"]) { $candidates += @($item.url_alternatives) }
    $done = $false
    foreach ($cand in $candidates) {
        $url = $cand
        try {
            if ($url -match '\{latest:(\d+\.\d+)\}') {
                $v = Resolve-LatestPython $Matches[1]
                $url = $url -replace '\{latest:\d+\.\d+\}', $v
            }
            $tmp = Join-Path $CacheDir ("download-" + [guid]::NewGuid().ToString("N"))
            $final = Get-FinalUrlAndDownload $url $tmp
            $sig = Get-AuthenticodeSignature -FilePath $tmp
            $signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "" }
            if ($sig.Status -ne "Valid" -or $signer -notlike "*$($item.signer_must_contain)*") {
                Remove-Item $tmp -Force
                throw "firma non valida o firmatario inatteso ($($sig.Status), '$signer')"
            }
            $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $tmp).Hash.ToLowerInvariant()
            $size = (Get-Item $tmp).Length
            $fileName = [IO.Path]::GetFileName(([uri]$final).AbsolutePath)
            if ($item.PSObject.Properties["file_must_contain"] -and $fileName -notlike ("*" + $item.file_must_contain + "*")) {
                Remove-Item -LiteralPath $tmp -Force
                throw "il file scaricato ($fileName) non contiene '$($item.file_must_contain)'"
            }
            if (-not $fileName -or $fileName -notmatch '\.(exe|msi)$') { $fileName = "$($item.name).$($item.kind)" }
            $cached = Join-Path $CacheDir "$($item.name)-$($sha.Substring(0,12))-$fileName"
            Move-Item -Force $tmp $cached
            # la lettura della versione MSI tiene aperto il file (COM): dopo lo spostamento
            $version = if ($item.kind -eq "msi") { Get-MsiVersion $cached } else { (Get-Item $cached).VersionInfo.ProductVersion }
            foreach ($k in "url_resolved", "sha256", "size", "signer", "version", "file_name", "verified_at", "error") {
                if ($item.PSObject.Properties[$k]) { $item.PSObject.Properties.Remove($k) }
            }
            $item | Add-Member url_resolved $final
            $item | Add-Member sha256 $sha
            $item | Add-Member size $size
            $item | Add-Member signer $signer
            $item | Add-Member version ([string]$version)
            $item | Add-Member file_name (Split-Path $cached -Leaf)
            $item | Add-Member verified_at ((Get-Date).ToString("s"))
            $results += "OK    $($item.name) $version sha256=$($sha.Substring(0,16))… ($([int]($size/1KB)) KB)"
            $done = $true
            break
        } catch {
            $results += "FAIL  $($item.name) da $url : $_"
        }
    }
    if (-not $done) {
        foreach ($k in "sha256", "url_resolved") { if ($item.PSObject.Properties[$k]) { $item.PSObject.Properties.Remove($k) } }
        if ($item.PSObject.Properties["error"]) { $item.PSObject.Properties.Remove("error") }
        $item | Add-Member error "non verificato: scaricare dalla pagina ufficiale e rilanciare con l'URL corretto"
    }
}
$lock.updated_at = (Get-Date).ToString("s")
$json = $lock | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($LockPath, $json, (New-Object Text.UTF8Encoding $false))
$results | ForEach-Object { Write-Host $_ }
Write-Host "Lock aggiornato: $LockPath · installer verificati in $CacheDir"
