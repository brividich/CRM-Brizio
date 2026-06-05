<#
.SYNOPSIS
    Smoke test HTTP automatico per Portale Novicrom.

.DESCRIPTION
    Verifica che l'applicazione risponda correttamente dopo un deploy.
    Testa endpoint critici e verifica i codici HTTP attesi.

.PARAMETER Environment
    Ambiente: "test" oppure "prod"

.PARAMETER BaseUrl
    URL base dell'applicazione. Default: http://localhost:8080 (test) / http://localhost:80 (prod)

.PARAMETER Timeout
    Timeout per ogni richiesta HTTP in secondi. Default: 30

.PARAMETER Quiet
    Riduce l'output al minimo (solo esito finale). Utile se chiamato da altri script.

.PARAMETER WaitSeconds
    Secondi di attesa iniziale (per dare tempo all'app di avviarsi). Default: 5

.EXAMPLE
    .\smoke-test.ps1 -Environment test
    .\smoke-test.ps1 -Environment prod -BaseUrl "http://portale.cnovicrom.local"
    .\smoke-test.ps1 -Environment test -WaitSeconds 10
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("test","prod")]
    [string]$Environment,

    [string]$BaseUrl = "",
    [int]$Timeout = 30,
    [switch]$Quiet,
    [int]$WaitSeconds = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"

# Default URL
if (-not $BaseUrl) {
    $BaseUrl = if ($Environment -eq "prod") { "http://localhost:80" } else { "http://localhost:8080" }
}
$BaseUrl = $BaseUrl.TrimEnd("/")

if (-not $Quiet) {
    Write-LogSeparator
    Write-Log "SMOKE TEST - $($Environment.ToUpper())" "STEP"
    Write-Log "URL base: $BaseUrl" "INFO"
    Write-LogSeparator
}

# ---------------------------------------------------------------------------
# Attesa avvio app
# ---------------------------------------------------------------------------
if ($WaitSeconds -gt 0) {
    if (-not $Quiet) { Write-Log "Attesa ${WaitSeconds}s per avvio applicazione..." "INFO" }
    Start-Sleep -Seconds $WaitSeconds
}

# ---------------------------------------------------------------------------
# Definizione test
# ---------------------------------------------------------------------------
# Formato: @{ Path; ExpectedCode; Description; ExpectRedirect }
$tests = @(
    @{ Path = "/health";       ExpectedCode = 200; Description = "Health check endpoint" },
    @{ Path = "/version";      ExpectedCode = 200; Description = "Version endpoint" },
    @{ Path = "/login/";       ExpectedCode = 200; Description = "Login page (no auth)" },
    @{ Path = "/static/css/";  ExpectedCode = 403; Description = "Static directory listing (403 atteso)" },
    @{ Path = "/";             ExpectedCode = 302; Description = "Root redirect a login (302 atteso)" },
    @{ Path = "/nonexistente-12345/"; ExpectedCode = 404; Description = "404 handler funzionante" }
)

# ---------------------------------------------------------------------------
# Funzione HTTP test
# ---------------------------------------------------------------------------
function Test-Endpoint {
    param([string]$Url, [int]$Expected, [string]$Desc, [int]$TimeoutSec)
    try {
        $response = Invoke-WebRequest -Uri $Url `
                                      -TimeoutSec $TimeoutSec `
                                      -MaximumRedirection 0 `
                                      -UseBasicParsing `
                                      -ErrorAction SilentlyContinue
        $actual = $response.StatusCode
    } catch [System.Net.WebException] {
        # WebException per 3xx, 4xx, 5xx - leggi il codice dalla response
        if ($_.Exception.Response) {
            $actual = [int]$_.Exception.Response.StatusCode
        } else {
            $actual = -1
        }
    } catch {
        $actual = -1
    }

    $pass = ($actual -eq $Expected)
    return @{ Pass = $pass; Actual = $actual; Expected = $Expected; Url = $Url; Desc = $Desc }
}

# ---------------------------------------------------------------------------
# Esecuzione test
# ---------------------------------------------------------------------------
$results = @()
$passed  = 0
$failed  = 0

foreach ($test in $tests) {
    $url    = "$BaseUrl$($test.Path)"
    $result = Test-Endpoint -Url $url -Expected $test.ExpectedCode -Desc $test.Description -TimeoutSec $Timeout

    if ($result.Pass) {
        $passed++
        if (-not $Quiet) {
            Write-Log "  [PASS] $($test.Description) -> HTTP $($result.Actual)" "SUCCESS"
        }
    } else {
        $failed++
        $statusStr = if ($result.Actual -eq -1) { "TIMEOUT/CONN_ERR" } else { "HTTP $($result.Actual)" }
        Write-Log "  [FAIL] $($test.Description)" "ERROR"
        Write-Log "         URL: $url" "ERROR"
        Write-Log "         Atteso: HTTP $($test.ExpectedCode) - Ottenuto: $statusStr" "ERROR"
    }
    $results += $result
}

# ---------------------------------------------------------------------------
# Test aggiuntivo: verifica Django (non pagina di errore 500)
# ---------------------------------------------------------------------------
try {
    $loginUrl = "$BaseUrl/login/"
    $resp = Invoke-WebRequest -Uri $loginUrl -TimeoutSec $Timeout -UseBasicParsing -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) {
        # Verifica che NON sia una pagina di errore Django (500)
        if ($resp.Content -match "Server Error \(500\)|Internal Server Error|OperationalError|ProgrammingError") {
            Write-Log "  [FAIL] Login page restituisce errore Django!" "ERROR"
            $failed++
        } else {
            if (-not $Quiet) { Write-Log "  [PASS] Login page senza errori Django." "SUCCESS" }
            $passed++
        }
        # Verifica presenza form login
        if ($resp.Content -match 'type="password"') {
            if (-not $Quiet) { Write-Log "  [PASS] Form login presente nella pagina." "SUCCESS" }
            $passed++
        } else {
            Write-Log "  [WARN] Form login non trovato nella pagina /login/" "WARN"
        }
    }
} catch {
    Write-Log "  [WARN] Verifica contenuto login fallita: $_" "WARN"
}

# ---------------------------------------------------------------------------
# Risultato finale
# ---------------------------------------------------------------------------
$total = $passed + $failed
if (-not $Quiet) {
    Write-LogSeparator
}

if ($failed -eq 0) {
    Write-Log "SMOKE TEST PASSATO: $passed/$total test OK" "SUCCESS"
    exit 0
} else {
    Write-Log "SMOKE TEST FALLITO: $failed/$total test KO - $passed OK, $failed FAIL" "ERROR"
    exit 1
}
