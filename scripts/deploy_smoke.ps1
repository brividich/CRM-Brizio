<#
.SYNOPSIS
    deploy_smoke.ps1 - HTTP smoke probe per NOVICROM HUB post-deploy.

.DESCRIPTION
    Esegue probe HTTP riusabili contro un'istanza appena rilasciata:
        - /healthz (preferito) con fallback a /health
        - /version  (opzionale: WARN se 404)
        - /login/   (200 o redirect 3xx accettati)

    Compatibile Windows PowerShell 5.1+ (no pipeline chain, no ternario,
    no null-coalescing). Mai stampa header, query string o segreti.

.PARAMETER BaseUrl
    URL base dell'istanza (es. https://hub.example.local). Trailing slash
    rimosso automaticamente.

.PARAMETER TimeoutSec
    Timeout per richiesta HTTP (default 15).

.PARAMETER AllowSelfSignedCert
    Se presente, accetta certificati self-signed (utile in test/preprod).

.PARAMETER ReportPath
    Se valorizzato, appende righe redatte al file di log indicato.

.PARAMETER Environment
    'test' (default) o 'prod'. In 'prod' /version e' obbligatorio: 404, body
    vuoto o unreachable -> exit 1. In 'test' resta WARN (retrocompatibilita).

.EXAMPLE
    .\deploy_smoke.ps1 -BaseUrl https://hub.test.example -TimeoutSec 20

.EXAMPLE
    .\deploy_smoke.ps1 -BaseUrl https://hub.local -AllowSelfSignedCert -ReportPath C:\logs\smoke.log

.EXAMPLE
    .\deploy_smoke.ps1 -BaseUrl https://hub.example -Environment prod

.NOTES
    Version: 1.1.0 (DEPLOY-GUARD-01B: -Environment, /version obbligatorio in prod)
    Security: nessun valore segreto viene mai loggato. Solo path, status code
              e flag booleani sono scritti su console e nel report.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSec = 15,

    [Parameter(Mandatory = $false)]
    [switch]$AllowSelfSignedCert,

    [Parameter(Mandatory = $false)]
    [string]$ReportPath,

    # DEPLOY-GUARD-01B: ambiente di esecuzione. In 'prod' /version e' obbligatorio
    # (404 / body vuoto / unreachable -> exit 1). In 'test' (default per backward-compat)
    # /version resta WARN se assente, per non bloccare ambienti non ancora aggiornati.
    [Parameter(Mandatory = $false)]
    [ValidateSet('test', 'prod')]
    [string]$Environment = 'test'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptVersion = '1.1.0'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-SmokeLog {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Message
    )
    Write-Host $Message
    if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
        try {
            Add-Content -Path $ReportPath -Value $Message -Encoding utf8
        } catch {
            # Non bloccare lo smoke per problemi di logging.
            Write-Host "[SMOKE][WARN] Report append failed: $($_.Exception.Message)"
        }
    }
}

$script:PreviousCertificatePolicy = $null
$script:PreviousSecurityProtocol = $null

function Set-AllowSelfSignedCert {
    # In PS 5.1 non esiste -SkipCertificateCheck su Invoke-WebRequest.
    # Rimpiazziamo il callback. Salviamo lo stato precedente per ripristino.
    $script:PreviousCertificatePolicy = [System.Net.ServicePointManager]::CertificatePolicy
    $script:PreviousSecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol
    if ($null -eq ([System.Management.Automation.PSTypeName]'NovicromSmokeCertPolicy').Type) {
        Add-Type -TypeDefinition @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class NovicromSmokeCertPolicy : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int problem) {
        return true;
    }
}
"@
    }
    [System.Net.ServicePointManager]::CertificatePolicy = New-Object NovicromSmokeCertPolicy
    # TLS moderni
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = `
            [System.Net.SecurityProtocolType]::Tls12 -bor `
            [System.Net.SecurityProtocolType]::Tls11 -bor `
            [System.Net.SecurityProtocolType]::Tls
    } catch {
        # Ignora se l'enum non supporta tutti i valori sulla piattaforma.
    }
}

function Restore-CertificatePolicy {
    # Ripristina lo stato globale per non sporcare la sessione PowerShell padre.
    if ($null -ne $script:PreviousCertificatePolicy) {
        try {
            [System.Net.ServicePointManager]::CertificatePolicy = $script:PreviousCertificatePolicy
        } catch { }
    }
    if ($null -ne $script:PreviousSecurityProtocol) {
        try {
            [System.Net.ServicePointManager]::SecurityProtocol = $script:PreviousSecurityProtocol
        } catch { }
    }
}

function Invoke-SmokeRequest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    $result = [PSCustomObject]@{
        Url        = $Url
        StatusCode = 0
        Ok         = $false
        Error      = ''
        BodyHint   = ''
    }

    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -MaximumRedirection 0 -ErrorAction Stop
        $result.StatusCode = [int]$resp.StatusCode
        $result.Ok = $true
        if ($null -ne $resp.Content) {
            $body = [string]$resp.Content
            if ($body.Length -gt 0) {
                $hint = $body.Substring(0, [Math]::Min(80, $body.Length))
                # Rimuovi a/capo per non sporcare il log
                $hint = ($hint -replace "[\r\n]+", ' ').Trim()
                $result.BodyHint = $hint
            }
        }
    } catch [System.Net.WebException] {
        $we = $_.Exception
        if ($null -ne $we.Response) {
            try {
                $result.StatusCode = [int]$we.Response.StatusCode
                # 3xx vengono trattati come "errore" da Invoke-WebRequest con
                # MaximumRedirection 0: li consideriamo OK a livello probe.
                if ($result.StatusCode -ge 300 -and $result.StatusCode -lt 400) {
                    $result.Ok = $true
                } else {
                    $result.Ok = $false
                    $result.Error = $we.Message
                }
            } catch {
                $result.Ok = $false
                $result.Error = $we.Message
            }
        } else {
            $result.Ok = $false
            $result.Error = $we.Message
        }
    } catch {
        $result.Ok = $false
        $result.Error = $_.Exception.Message
    }

    return $result
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

$BaseUrl = $BaseUrl.TrimEnd('/')

Write-SmokeLog "[SMOKE] deploy_smoke.ps1 v$ScriptVersion"
Write-SmokeLog "[SMOKE] BaseUrl: $BaseUrl"
Write-SmokeLog "[SMOKE] Environment: $Environment"
Write-SmokeLog "[SMOKE] TimeoutSec: $TimeoutSec"
Write-SmokeLog "[SMOKE] AllowSelfSignedCert: $([bool]$AllowSelfSignedCert)"

if ($AllowSelfSignedCert) {
    Set-AllowSelfSignedCert
    Write-SmokeLog '[SMOKE][WARN] CertificatePolicy globale modificata; verra'' ripristinata a fine script.'
}

$results = @()
$criticalFail = $false
$warnings = 0

# Wrappa tutto il main in try/finally per garantire ripristino CertificatePolicy
try {

# --- /healthz with /health fallback -----------------------------------------
$healthOk = $false
$healthPath = '/healthz'
$healthRes = Invoke-SmokeRequest -Url ($BaseUrl + $healthPath)
if ($healthRes.Ok -and $healthRes.StatusCode -eq 200) {
    $healthOk = $true
} elseif ($healthRes.StatusCode -eq 404) {
    Write-SmokeLog "[SMOKE] /healthz -> 404 - falling back to /health"
    $healthPath = '/health'
    $healthRes = Invoke-SmokeRequest -Url ($BaseUrl + $healthPath)
    if ($healthRes.Ok -and $healthRes.StatusCode -eq 200) {
        $healthOk = $true
    }
}
$results += [PSCustomObject]@{
    Endpoint = $healthPath
    Status   = $healthRes.StatusCode
    Ok       = $healthOk
    Note     = if ($healthOk) { 'health probe OK' } else { 'health probe FAIL' }
}
Write-SmokeLog "[SMOKE] $healthPath -> HTTP $($healthRes.StatusCode)"
if (-not $healthOk) {
    $criticalFail = $true
    if (-not [string]::IsNullOrEmpty($healthRes.Error)) {
        Write-SmokeLog "[SMOKE][ERR] $healthPath error: $($healthRes.Error)"
    }
}

# --- /version ---------------------------------------------------------------
# DEPLOY-GUARD-01B: in prod /version e' obbligatorio. In test resta WARN per
# retrocompatibilita su ambienti non ancora aggiornati.
$versionRes = Invoke-SmokeRequest -Url ($BaseUrl + '/version')
$versionNote = ''
$versionOk = $false
$versionRequired = ($Environment -eq 'prod')
if ($versionRes.Ok -and $versionRes.StatusCode -eq 200) {
    if (-not [string]::IsNullOrWhiteSpace($versionRes.BodyHint)) {
        $versionOk = $true
        $versionNote = 'version endpoint reachable'
    } else {
        $versionNote = 'version endpoint returned empty body'
        if ($versionRequired) {
            $criticalFail = $true
            $versionNote = 'version endpoint returned empty body (REQUIRED in prod)'
        } else {
            $warnings++
        }
    }
} elseif ($versionRes.StatusCode -eq 404) {
    if ($versionRequired) {
        $versionNote = 'version endpoint not implemented (REQUIRED in prod)'
        $criticalFail = $true
    } else {
        $versionNote = 'version endpoint not implemented (WARN in test)'
        $warnings++
    }
} else {
    if ($versionRequired) {
        $versionNote = "version endpoint unreachable (REQUIRED in prod, status=$($versionRes.StatusCode))"
        $criticalFail = $true
    } else {
        $versionNote = "version endpoint unreachable (status=$($versionRes.StatusCode))"
        $warnings++
    }
}
$results += [PSCustomObject]@{
    Endpoint = '/version'
    Status   = $versionRes.StatusCode
    Ok       = $versionOk
    Note     = $versionNote
}
Write-SmokeLog "[SMOKE] /version -> HTTP $($versionRes.StatusCode) ($versionNote)"

# --- /login/ ----------------------------------------------------------------
$loginRes = Invoke-SmokeRequest -Url ($BaseUrl + '/login/')
$loginOk = $false
$loginNote = ''
if ($loginRes.StatusCode -eq 200 -or ($loginRes.StatusCode -ge 300 -and $loginRes.StatusCode -lt 400)) {
    $loginOk = $true
    $loginNote = 'login reachable'
} elseif ($loginRes.StatusCode -ge 500) {
    $loginNote = 'login endpoint 5xx'
    $criticalFail = $true
} elseif ($loginRes.StatusCode -eq 0) {
    $loginNote = "network error: $($loginRes.Error)"
    $criticalFail = $true
} else {
    $loginNote = "unexpected status $($loginRes.StatusCode)"
    $warnings++
}
$results += [PSCustomObject]@{
    Endpoint = '/login/'
    Status   = $loginRes.StatusCode
    Ok       = $loginOk
    Note     = $loginNote
}
Write-SmokeLog "[SMOKE] /login/ -> HTTP $($loginRes.StatusCode) ($loginNote)"

# --- Riepilogo --------------------------------------------------------------
Write-SmokeLog ''
Write-SmokeLog '[SMOKE] === Summary ==='
$tableText = ($results | Format-Table -AutoSize | Out-String).Trim()
Write-SmokeLog $tableText
Write-SmokeLog "[SMOKE] warnings=$warnings criticalFail=$criticalFail"

if ($criticalFail) {
    Write-SmokeLog '[SMOKE] RESULT: FAIL'
    $script:SmokeExitCode = 1
} else {
    Write-SmokeLog '[SMOKE] RESULT: OK'
    $script:SmokeExitCode = 0
}

} finally {
    if ($AllowSelfSignedCert) {
        Restore-CertificatePolicy
    }
}

exit $script:SmokeExitCode
