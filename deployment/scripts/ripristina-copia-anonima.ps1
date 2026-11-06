<#
.SYNOPSIS
    Ripristina un .bak di produzione sulla macchina di sviluppo e lo anonimizza subito.

.DESCRIPTION
    Crea il database PN_COPIAPROD_ANON sull'istanza locale, senza toccare gli altri. Se
    l'anonimizzazione non riesce, elimina la copia: una copia con dati reali non resta in giro.
    Procedura completa: docs/dr/COPIA_PROD_ANONIMIZZATA.md

.EXAMPLE
    .\deployment\scripts\ripristina-copia-anonima.ps1 -BakPath "C:\Temp\prod.bak" -Migra
#>
param(
    [Parameter(Mandatory = $true)][string]$BakPath,
    [string]$Istanza = "localhost\SQLEXPRESS",
    [string]$NomeDb = "PN_COPIAPROD_ANON",
    [string]$Python = "",
    [switch]$Sostituisci,
    [switch]$Migra
)
$ErrorActionPreference = "Stop"

if ($NomeDb -notmatch '_ANON$') { throw "Il nome del database deve finire con _ANON." }
if ($NomeDb -notmatch '^[A-Za-z0-9_]+$') { throw "Nome del database non valido." }
if ($Istanza -notmatch '^(localhost|127\.0\.0\.1|\.)(\\|,|$)') { throw "La copia si crea solo su questa macchina." }
if (-not (Test-Path -LiteralPath $BakPath)) { throw "File non trovato: $BakPath" }
$BakPath = (Resolve-Path -LiteralPath $BakPath).Path
# Il ripristino lo esegue il servizio SQL, non l'utente: gli serve il permesso di lettura sul file.
$servizio = if ($Istanza -match '\\(.+)$') { "NT Service\MSSQL`$$($Matches[1])" } else { "NT Service\MSSQLSERVER" }
& icacls $BakPath /grant "${servizio}:R" 2>&1 | Out-Null
# Se non si puo' assegnare, il servizio puo' averlo gia' (per esempio dalla cartella): decide il ripristino.
if ($LASTEXITCODE -ne 0) { Write-Warning "Permesso di lettura per $servizio non assegnato su $BakPath." }

$radice = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Python) {
    foreach ($candidato in @((Join-Path $radice ".venv\Scripts\python.exe"), "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe")) {
        if (Test-Path -LiteralPath $candidato) { $Python = $candidato; break }
    }
}
if (-not $Python) { throw "Python non trovato: indicarlo con -Python." }

function Invoke-Sql([string]$Sql) {
    $uscita = & sqlcmd -S $Istanza -E -C -b -W -h -1 -s "|" -Q "SET NOCOUNT ON; $Sql" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Errore SQL: $($uscita -join ' ')" }
    return $uscita
}

function Remove-Copia {
    Invoke-Sql "IF DB_ID(N'$NomeDb') IS NOT NULL BEGIN ALTER DATABASE [$NomeDb] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$NomeDb]; END" | Out-Null
}

$esiste = (Invoke-Sql "SELECT CASE WHEN DB_ID(N'$NomeDb') IS NULL THEN 0 ELSE 1 END" | Select-Object -First 1).Trim()
if ($esiste -eq "1") {
    if (-not $Sostituisci) { throw "$NomeDb esiste gia': usare -Sostituisci per rifarla." }
    Remove-Copia
}

$cartellaDati = (Invoke-Sql "SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260))" | Select-Object -First 1).Trim()
$sqlBak = $BakPath.Replace("'", "''")
$sposta = @()
$i = 0
foreach ($riga in (Invoke-Sql "RESTORE FILELISTONLY FROM DISK=N'$sqlBak'")) {
    if (-not "$riga".Trim()) { continue }
    $campi = "$riga" -split '\|'
    $estensione = if ($campi[2] -eq 'L') { 'ldf' } else { 'mdf' }
    $sposta += "MOVE N'$($campi[0].Replace("'", "''"))' TO N'$cartellaDati$($NomeDb)_$i.$estensione'"
    $i++
}
if (-not $sposta) { throw "Nessun file trovato nel backup." }

Write-Host "Ripristino di $NomeDb in corso..."
Invoke-Sql "RESTORE DATABASE [$NomeDb] FROM DISK=N'$sqlBak' WITH $($sposta -join ', '), RECOVERY" | Out-Null

$env:COPIA_DB_NAME = $NomeDb
$env:COPIA_DB_HOST = $Istanza
$manage = Join-Path $radice "django_app\manage.py"
$impostazioni = "--settings=config.settings.copia_anonima"

Write-Host "Anonimizzazione in corso..."
$vecchia = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python $manage anonimizza_copia $impostazioni --esegui 2>&1 | Where-Object { "$_" -notmatch 'RuntimeWarning|warnings\.warn' } | ForEach-Object { "$_" }
$esito = $LASTEXITCODE
$ErrorActionPreference = $vecchia
if ($esito -ne 0) {
    Remove-Copia
    throw "Anonimizzazione NON riuscita: la copia e' stata eliminata."
}

if ($Migra) {
    Write-Host "Migrazioni sulla copia..."
    $ErrorActionPreference = "Continue"
    & $Python $manage migrate $impostazioni --noinput 2>&1 | Where-Object { "$_" -notmatch 'RuntimeWarning|warnings\.warn' } | ForEach-Object { "$_" }
    $esito = $LASTEXITCODE
    $ErrorActionPreference = $vecchia
    if ($esito -ne 0) { Write-Warning "Migrazioni NON riuscite: la copia resta anonimizzata, ma con lo schema di partenza." }
}

Write-Host "Fatto. Ricordarsi di cancellare il file .bak dalla macchina di sviluppo: $BakPath"
