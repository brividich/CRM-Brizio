<#
.SYNOPSIS
    Avvia il collector CNC fuori dal portale e dal Setup Wizard (pilota su NOVISQL, PC dell'officina),
    in sola lettura, con il log a schermo e su file.

.DESCRIPTION
    Pensato per il pilota di 2-3 giorni: si lancia da una finestra PowerShell e resta acceso finché non
    premi CTRL+C (o fino a -DurataOre). Non tocca il portale: PORTALE_URL e PORTALE_TOKEN vengono
    svuotati per questo processo, quindi niente viene inviato (modalità ombra). Tutto resta nella
    cartella di lavoro:

      <Cartella>\machines.json        macchine da leggere (al primo avvio: copia di machines.example.json)
      <Cartella>\collector.env        segreti facoltativi (CNC_DM7_PASSWORD, CNC_FWLIB_PATH), mai nel log
      <Cartella>\machines.db          registro locale (stati, segnali, allarmi, contatori)
      <Cartella>\dati\                un JSONL per macchina e giorno + status.json (ultimo stato)
      <Cartella>\logs\collector.log   log del collector, a rotazione 5 MB x 5
      <Cartella>\logs\console-<data>.log  tutto quello che compare a schermo (anche errori imprevisti)

    Se il collector si chiude per un errore imprevisto lo script lo riavvia dopo 30 secondi; con un errore
    nella configurazione si ferma e dice cosa correggere.

.PARAMETER Cartella
    Cartella di lavoro (default: .\pilota accanto allo script).
.PARAMETER Python
    python.exe da usare (default: il venv <Cartella>\.venv, creato con -Installa).
.PARAMETER Installa
    Crea il venv e installa le dipendenze (requirements-collector.txt); con -Wheelhouse senza Internet.
.PARAMETER Wheelhouse
    Cartella con i pacchetti scaricati prima su un PC con Internet:
    py -m pip download -r requirements-collector.txt -d wheels
.PARAMETER FwlibPath
    File o cartella della libreria Fanuc (Fwlib64.dll). In alternativa CNC_FWLIB_PATH in collector.env.
.PARAMETER DurataOre
    Ferma il collector dopo queste ore (0 = finché non premi CTRL+C).
.PARAMETER Verifica
    Solo controllo della configurazione (--check-config), senza connettersi.
.PARAMETER Once
    Una lettura per macchina (o solo di quella indicata) con il JSON a schermo, poi esce.

.EXAMPLE
    .\avvia_collector.ps1 -Installa -FwlibPath C:\Fanuc\Fwlib64.dll
.EXAMPLE
    .\avvia_collector.ps1 -Once DM6-MDC
.EXAMPLE
    .\avvia_collector.ps1 -DurataOre 72
#>
[CmdletBinding()]
param(
    [string]$Cartella = "",
    [string]$Python = "",
    [switch]$Installa,
    [string]$Wheelhouse = "",
    [string]$FwlibPath = "",
    [double]$DurataOre = 0,
    [switch]$Verifica,
    [string]$Once = ""
)

$ErrorActionPreference = "Stop"
if (-not $Cartella) { $Cartella = Join-Path $PSScriptRoot "pilota" }   # PowerShell 5.1: $PSScriptRoot è vuoto nei default dei parametri
$Script = Join-Path $PSScriptRoot "collector.py"
$Requisiti = Join-Path $PSScriptRoot "requirements-collector.txt"

function Scrivi([string]$testo, [string]$colore = "Gray") {
    $riga = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $testo
    Write-Host $riga -ForegroundColor $colore
    if ($script:ConsoleLog) { Add-Content -Path $script:ConsoleLog -Value $riga -Encoding UTF8 }
}

# --- cartella di lavoro ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $Cartella, (Join-Path $Cartella "logs"), (Join-Path $Cartella "dati") | Out-Null
$Cartella = (Resolve-Path $Cartella).Path
$script:ConsoleLog = Join-Path $Cartella ("logs\console-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$Config = Join-Path $Cartella "machines.json"
if (-not (Test-Path $Config)) {
    Copy-Item (Join-Path $PSScriptRoot "machines.example.json") $Config
    Scrivi "Creato $Config dall'esempio (pilota: DM6-MDC, AGV1, HYUNDAI). Controllalo prima del pilota." "Yellow"
}

# --- Python e dipendenze --------------------------------------------------------------------------
$Venv = Join-Path $Cartella ".venv"
if (-not $Python) { $Python = Join-Path $Venv "Scripts\python.exe" }
if ($Installa) {
    if (-not (Test-Path $Python)) {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if (-not $py) { throw "Python non trovato: installa Python 3.11 o più recente (64 bit) oppure usa -Python <percorso>." }
        Scrivi "Creo l'ambiente Python in $Venv"
        & py -3 -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw "creazione del venv non riuscita" }
    }
    $pip = @("-m", "pip", "install", "--disable-pip-version-check", "-r", $Requisiti)
    if ($Wheelhouse) { $pip += @("--no-index", "--find-links", $Wheelhouse) }
    Scrivi "Installo asyncua e pyLSV2"
    & $Python @pip
    if ($LASTEXITCODE -ne 0) { throw "installazione delle dipendenze non riuscita (senza Internet usa -Wheelhouse)" }
}
if (-not (Test-Path $Python)) { throw "Python non trovato in $Python : lancia una volta con -Installa oppure indica -Python." }
$versione = & $Python -c "import sys, struct; print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P') * 8))"
$parti = $versione.Split(" ")
if ([version]$parti[0] -lt [version]"3.11") { throw "Serve Python 3.11 o più recente (trovato $($parti[0]))." }
Scrivi "Python $($parti[0]) a $($parti[1]) bit: $Python"

# --- ambiente: segreti da collector.env, niente portale ---------------------------------------------
$EnvFile = Join-Path $Cartella "collector.env"
if (Test-Path $EnvFile) {
    $caricate = @()
    foreach ($riga in Get-Content $EnvFile -Encoding UTF8) {
        $t = $riga.Trim()
        if (-not $t -or $t.StartsWith("#") -or -not $t.Contains("=")) { continue }
        $nome, $valore = $t.Split("=", 2)
        if ($valore) { Set-Item -Path ("Env:" + $nome.Trim()) -Value $valore.Trim(); $caricate += $nome.Trim() }
    }
    Scrivi ("Variabili da collector.env: " + ($(if ($caricate) { $caricate -join ", " } else { "nessuna" })))
}
if ($FwlibPath) { $env:CNC_FWLIB_PATH = $FwlibPath }
if ($env:CNC_FWLIB_PATH) {
    Scrivi "Libreria Fanuc: $($env:CNC_FWLIB_PATH)"
    if ($parti[1] -eq "64" -and $env:CNC_FWLIB_PATH -match "Fwlib32\.dll$") { Scrivi "ATTENZIONE: Python a 64 bit vuole Fwlib64.dll" "Yellow" }
}
# Modalità ombra garantita: questo processo non conosce il portale.
$env:PORTALE_URL = ""
$env:PORTALE_TOKEN = ""
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

# Il collector integrato del portale potrebbe già leggere le stesse DMG da questo server: lo si segnala.
$integrato = Get-ScheduledTask -TaskPath "\PortaleNovicrom\" -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like "CollectorCnc_*" -and $_.State -eq "Running" }
if ($integrato) {
    Scrivi "Nota: è attivo anche il collector integrato del portale ($($integrato.TaskName -join ', ')): le DMG in comune avranno due sessioni OPC UA in lettura." "Yellow"
}

$base = @($Script, "--config", $Config, "--db", (Join-Path $Cartella "machines.db"), "--log-file", (Join-Path $Cartella "logs\collector.log"))

function Esegui([string[]]$argomenti) {
    # Mostra a schermo e salva in console-*.log ogni riga (anche gli errori di Python su stderr).
    $vecchia = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Python @argomenti 2>&1 | ForEach-Object {
            $riga = "$_"
            Write-Host $riga
            Add-Content -Path $script:ConsoleLog -Value $riga -Encoding UTF8
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $vecchia
    }
}

if ($Verifica) { exit (Esegui ($base + @("--check-config"))) }
if ($PSBoundParameters.ContainsKey("Once")) {
    $a = $base + @("--once")
    if ($Once) { $a += $Once }
    exit (Esegui $a)
}

# --- servizio con riavvio automatico ---------------------------------------------------------------
$codice = Esegui ($base + @("--check-config"))
if ($codice -ne 0) { Scrivi "Configurazione da correggere: il collector non parte." "Red"; exit 2 }

$fine = if ($DurataOre -gt 0) { (Get-Date).AddHours($DurataOre) } else { [datetime]::MaxValue }
$avvii = 0
Scrivi ("Collector in sola lettura avviato" + $(if ($DurataOre -gt 0) { " per $DurataOre ore (fino a $($fine.ToString('dd/MM HH:mm')))" } else { ": CTRL+C per fermarlo" })) "Green"
Scrivi "Log: $(Join-Path $Cartella 'logs')  -  dati: $(Join-Path $Cartella 'dati')"
try {
    while ((Get-Date) -lt $fine) {
        $avvii++
        $ore = if ($DurataOre -gt 0) { [math]::Max(0.01, ($fine - (Get-Date)).TotalHours) } else { 0 }
        $codice = Esegui ($base + @("-v", "--jsonl", (Join-Path $Cartella "dati"), "--durata-ore", "$ore"))
        if ($codice -eq 0) { break }                 # fermato con CTRL+C o durata raggiunta
        if ($codice -eq 2) { Scrivi "Configurazione non valida: correggi machines.json." "Red"; break }
        Scrivi "Il collector si è chiuso con codice $codice (avvio n. $avvii): riparto tra 30 secondi." "Red"
        Start-Sleep -Seconds 30
    }
} finally {
    $log = Join-Path $Cartella "logs\collector.log"
    if (Test-Path $log) {
        $errori = (Select-String -Path $log -Pattern " ERROR " -SimpleMatch | Measure-Object).Count
        $bloccati = (Select-String -Path $log -Pattern "thread bloccato" -SimpleMatch | Measure-Object).Count
        $salute = Select-String -Path $log -Pattern "salute:" -SimpleMatch | Select-Object -Last 1
        Scrivi "Riepilogo: avvii $avvii, righe ERROR $errori, thread bloccati $bloccati"
        if ($salute) { Scrivi ("Ultima " + $salute.Line.Substring($salute.Line.IndexOf("salute:"))) }
    }
    Scrivi "Collector fermato." "Green"
}
