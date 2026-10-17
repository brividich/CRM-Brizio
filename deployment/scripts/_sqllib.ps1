# _sqllib.ps1 - Funzioni SQL Server condivise (sqlcmd) per gli script di istanza/migrazione DB.
# Da includere dopo _lib.ps1 con: . "$PSScriptRoot\_sqllib.ps1"
# Non eseguire direttamente. Usa sempre l'autenticazione Windows (-E): nessuna password.

Set-StrictMode -Version Latest

# Database che gli script HUB non toccano mai senza consenso esplicito.
$SQL_SYSTEM_DATABASES   = @("master", "model", "msdb", "tempdb")
$SQL_EXTERNAL_DATABASES = @("DLM", "CNGAUGE")   # sull'istanza ma non dell'HUB

function Find-Sqlcmd {
    $cmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $roots = @("$env:ProgramFiles\Microsoft SQL Server", "${env:ProgramFiles(x86)}\Microsoft SQL Server") |
        Where-Object { $_ -and (Test-Path $_) }
    foreach ($root in $roots) {
        $found = Get-ChildItem -Path $root -Filter SQLCMD.EXE -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    throw "sqlcmd non trovato: installare gli strumenti da riga di comando di SQL Server (ODBC 18)."
}

function Invoke-SqlQuery {
    <#
    Esegue una query con sqlcmd (-b: exit code <> 0 su errore) e restituisce le righe
    come array di array di stringhe (separatore \x1f, nessuna intestazione).
    #>
    param(
        [Parameter(Mandatory)][string]$Instance,
        [Parameter(Mandatory)][string]$Query,
        [string]$Database = "master",
        [int]$TimeoutSec = 60
    )
    $sqlcmd = Find-Sqlcmd
    $sep = [char]0x1f
    $sqlArgs = @("-S", $Instance, "-E", "-d", $Database, "-b", "-h", "-1", "-W", "-s", $sep,
              "-t", "$TimeoutSec", "-C", "-Q", "SET NOCOUNT ON; $Query")
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $out = & $sqlcmd @sqlArgs 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0) {
        throw "sqlcmd su '$Instance' fallito (exit $code): $(($out | Out-String).Trim())"
    }
    $rows = @()
    foreach ($line in @($out)) {
        $text = "$line"
        if ($text.Trim() -eq "") { continue }
        $rows += ,@($text.Split($sep) | ForEach-Object { $_.Trim() })
    }
    return ,$rows
}

function Invoke-SqlNonQuery {
    param(
        [Parameter(Mandatory)][string]$Instance,
        [Parameter(Mandatory)][string]$Statement,
        [string]$Database = "master",
        [int]$TimeoutSec = 3600
    )
    $sqlcmd = Find-Sqlcmd
    $sqlArgs = @("-S", $Instance, "-E", "-d", $Database, "-b", "-t", "$TimeoutSec", "-C", "-Q", $Statement)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $out = & $sqlcmd @sqlArgs 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    $text = ($out | Out-String).Trim()
    if ($code -ne 0) { throw "sqlcmd su '$Instance' fallito (exit $code): $text" }
    return $text
}

function ConvertTo-SqlLiteral([string]$Value) { return "N'" + $Value.Replace("'", "''") + "'" }
function ConvertTo-SqlName([string]$Value)    { return "[" + $Value.Replace("]", "]]") + "]" }

function Get-SqlInstanceInfo {
    param([Parameter(Mandatory)][string]$Instance)
    $r = (Invoke-SqlQuery -Instance $Instance -Query @"
SELECT CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(64)),
       CAST(SERVERPROPERTY('Edition') AS NVARCHAR(128)),
       CAST(SERVERPROPERTY('Collation') AS NVARCHAR(128)),
       CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS INT),
       CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS NVARCHAR(512)),
       CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS NVARCHAR(512)),
       CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS NVARCHAR(512)),
       CAST(SERVERPROPERTY('MachineName') AS NVARCHAR(128))
"@)[0]
    return [pscustomobject]@{
        Instance        = $Instance
        ProductVersion  = $r[0]
        Major           = [int]($r[0].Split(".")[0])
        Edition         = $r[1]
        Collation       = $r[2]
        WindowsAuthOnly = ($r[3] -eq "1")
        DefaultDataPath = $r[4]
        DefaultLogPath  = $r[5]
        DefaultBackupPath = $r[6]
        MachineName     = $r[7]
    }
}

function Get-SqlDatabaseInfo {
    param([Parameter(Mandatory)][string]$Instance, [Parameter(Mandatory)][string]$Database)
    $lit = ConvertTo-SqlLiteral $Database
    $rows = Invoke-SqlQuery -Instance $Instance -Query @"
SELECT d.state_desc, d.recovery_model_desc, d.compatibility_level, CAST(DATABASEPROPERTYEX(d.name, 'Collation') AS NVARCHAR(128)),
       SUSER_SNAME(d.owner_sid),
       (SELECT CAST(SUM(CAST(size AS BIGINT)) * 8 / 1024 AS BIGINT) FROM sys.master_files WHERE database_id = d.database_id)
FROM sys.databases d WHERE d.name = $lit
"@
    if ($rows.Count -eq 0) { return $null }
    $r = $rows[0]
    return [pscustomobject]@{
        Name = $Database; State = $r[0]; RecoveryModel = $r[1]; CompatibilityLevel = [int]$r[2]
        Collation = $r[3]; Owner = $r[4]; AllocatedMB = [int64]$r[5]
    }
}

function Assert-HubDatabaseName {
    <# Rifiuta i DB di sistema e (senza consenso esplicito) i DB esterni all'HUB. #>
    param([Parameter(Mandatory)][string]$Database, [switch]$AllowExternal)
    if ($SQL_SYSTEM_DATABASES -contains $Database.ToLowerInvariant()) {
        throw "Database di sistema '$Database': operazione rifiutata."
    }
    $isExternal = $SQL_EXTERNAL_DATABASES | Where-Object { $_ -ieq $Database }
    if ($isExternal -and -not $AllowExternal) {
        throw "Il database '$Database' non è dell'HUB: rifiutato. Per spostarlo serve -AllowExternalDatabase (decisione di Brizio)."
    }
}

function Get-FreeSpaceMB([string]$Path) {
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))   # anche se la cartella non esiste ancora
    if (-not $root -or $root.StartsWith("\\")) { return $null }      # UNC: spazio non determinabile qui
    $drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($root.TrimEnd('\'))'" -ErrorAction SilentlyContinue
    if (-not $drive) { return $null }
    return [int64]($drive.FreeSpace / 1MB)
}
