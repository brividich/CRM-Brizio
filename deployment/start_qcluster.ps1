#Requires -Version 5.1
<#
.SYNOPSIS
    Avvia il worker django-q2 (qcluster) per NOVICROM HUB.
    Progettato per essere lanciato da Task Scheduler come processo persistente
    con auto-restart on crash.

    IMPORTANTE: questo file e' volutamente in ASCII puro (niente accenti o
    box-drawing). Caratteri non-ASCII salvati con encoding errato (mojibake)
    rompono il parser PowerShell e fanno fallire il task senza log -> non
    reintrodurli.

.DESCRIPTION
    Lo script individua il venv dell'ambiente selezionato, avvia
    'python manage.py qcluster --settings=config.settings.prod'
    e lo riavvia automaticamente se termina in modo inatteso.

    Registrare in Task Scheduler con:
      - Trigger: "All'avvio" (At startup)  oppure  "Alla connessione utente"
      - Azione: powershell.exe -NonInteractive -ExecutionPolicy Bypass
                -File "C:\PortaleNovicrom\shared\scripts\start_qcluster.ps1"
      - Flag: "Esegui indipendentemente dall'accesso utente"
      - Account: account di servizio o account Windows dell'applicazione

.PARAMETER Environment
    Ambiente target: 'test' oppure 'prod' (default: 'prod').

.PARAMETER PortaleRoot
    Cartella radice degli ambienti. Default: C:\PortaleNovicrom

.PARAMETER RestartDelaySec
    Secondi di attesa prima del restart dopo un'uscita. Default: 5.

.PARAMETER LogFile
    Percorso file di log. Default: <PortaleRoot>\<Environment>\logs\qcluster.log
#>

param(
    [ValidateSet("test", "prod")]
    [string]$Environment = "prod",

    [string]$PortaleRoot = "C:\PortaleNovicrom",

    [ValidateRange(1, 3600)][int]$RestartDelaySec = 5,

    [string]$LogFile = "",

    [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# -- Percorsi --------------------------------------------------------------
$EnvRoot    = Join-Path $PortaleRoot $Environment
$CurrentDir = Join-Path $EnvRoot "current\django_app"
$VenvPython = Join-Path $EnvRoot "venv\Scripts\python.exe"
$LogsDir    = Join-Path $EnvRoot "logs"
# Deployed TEST also uses SQL Server via prod settings and ENV/config/.env.
# config.settings.test is reserved for isolated SQLite unit tests.
$Settings   = "config.settings.prod"

if (-not $LogFile) {
    $LogFile = Join-Path $LogsDir "qcluster.log"
}

# -- Utility log -----------------------------------------------------------
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$Level] $Message"
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch {}
    Write-Host $line
}

# -- Preflight -------------------------------------------------------------
# La cartella log va creata PRIMA dei controlli, cosi' Write-Log puo' loggare
# anche l'eventuale errore di preflight.
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}
if (-not (Test-Path $VenvPython)) {
    Write-Log "Python venv non trovato: $VenvPython" "ERROR"
    exit 1
}
if (-not (Test-Path $CurrentDir)) {
    Write-Log "Cartella django_app non trovata: $CurrentDir" "ERROR"
    exit 1
}

$rootBytes = [Text.Encoding]::UTF8.GetBytes($EnvRoot.ToLowerInvariant())
$rootHash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($rootBytes)).Replace("-", "").Substring(0, 16)
$clusterMutex = [Threading.Mutex]::new($false, "Global\NovicromQCluster_$rootHash")
try { $ownsMutex = $clusterMutex.WaitOne(0) }
catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) { Write-Log "Launcher gia attivo per questo ambiente." "WARN"; $clusterMutex.Dispose(); exit 0 }
try {
Write-Log "=== qcluster START (env=$Environment, pid=$PID) ==="

# -- Residui di un launcher precedente -------------------------------------
# Stop-ScheduledTask / Stop-Process uccidono SOLO il launcher: i python figli
# restano vivi senza padre e il nuovo launcher (mutex abbandonato) avvierebbe
# un secondo cluster sulla stessa coda. Qui teniamo il mutex, quindi ogni
# qcluster di questo venv e' un residuo: si chiude con tutto l'albero.
try {
    $leftovers = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -OperationTimeoutSec 10 -ErrorAction Stop |
        Where-Object { $_.ExecutablePath -eq $VenvPython -and $_.CommandLine -match '\bqcluster\b' })
    foreach ($old in $leftovers) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $old.ProcessId /T /F 2>&1 | Out-Null
        Write-Log "Chiuso qcluster residuo di un launcher precedente (PID $($old.ProcessId))." "WARN"
    }
} catch {
    Write-Log "Verifica qcluster residui non riuscita: $_" "WARN"
}

# -- Figli legati al launcher ----------------------------------------------
# Job object con KILL_ON_JOB_CLOSE: se il launcher muore (stop del task, kill,
# riavvio) Windows chiude anche tutti i processi python avviati da qui.
# Non con -Once: chi lancia il test resterebbe nel job.
if (-not $Once) {
    try {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class NovicromQcJob {
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimit { public long a; public long b; public uint LimitFlags; public IntPtr c; public IntPtr d; public uint e; public IntPtr f; public uint g; public uint h; }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong a; public ulong b; public ulong c; public ulong d; public ulong e; public ulong f; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimit { public BasicLimit Basic; public IoCounters Io; public IntPtr a; public IntPtr b; public IntPtr c; public IntPtr d; }
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr CreateJobObject(IntPtr attr, string name);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetInformationJobObject(IntPtr job, int cls, IntPtr info, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    public static IntPtr Handle;
    public static void BindCurrentProcess() {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        ExtendedLimit info = new ExtendedLimit();
        info.Basic.LimitFlags = 0x2000;
        int size = Marshal.SizeOf(typeof(ExtendedLimit));
        IntPtr ptr = Marshal.AllocHGlobal(size);
        try {
            Marshal.StructureToPtr(info, ptr, false);
            if (!SetInformationJobObject(job, 9, ptr, (uint)size)) throw new System.ComponentModel.Win32Exception();
        } finally { Marshal.FreeHGlobal(ptr); }
        if (!AssignProcessToJobObject(job, GetCurrentProcess())) throw new System.ComponentModel.Win32Exception();
        Handle = job;
    }
}
'@ -ErrorAction Stop
        # L'handle resta aperto fino all'uscita del launcher: nessuna chiusura esplicita.
        [NovicromQcJob]::BindCurrentProcess()
        Write-Log "Processi qcluster legati al launcher (job kill-on-close)."
    } catch {
        Write-Log "Job object non disponibile, i figli potrebbero sopravvivere al launcher: $_" "WARN"
    }
}

# -- Loop di restart -------------------------------------------------------
$attempt = 0
while ($true) {
    $attempt++
    Write-Log "Avvio qcluster - tentativo #$attempt"

    try {
        # File redirection is handled by .NET, without PowerShell event callbacks.
        # Blocking WaitForExit + Register-ObjectEvent can fill the child pipes.
        $runStamp = (Get-Date).ToString("yyyyMMdd_HHmmss_fff")
        $stdoutPath = Join-Path $LogsDir "qcluster_${PID}_${runStamp}.out.log"
        $stderrPath = Join-Path $LogsDir "qcluster_${PID}_${runStamp}.err.log"
        $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP = "0"
        $env:DJANGO_SETTINGS_MODULE = $Settings
        $env:PYTHONUNBUFFERED = "1"
        # Query SQL con timeout: una connessione morta (riavvio SQL) diventa un errore
        # invece di appendere il cluster per sempre. Sovrascrivibile da ambiente.
        if (-not $env:DB_QUERY_TIMEOUT) { $env:DB_QUERY_TIMEOUT = "300" }
        $proc = Start-Process -FilePath $VenvPython `
            -ArgumentList @("manage.py", "qcluster", "--settings=$Settings") `
            -WorkingDirectory $CurrentDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -ErrorAction Stop
        $null = $proc.Handle
        Write-Log "qcluster avviato - PID processo figlio: $($proc.Id)"
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode
        $proc.Dispose()

        Write-Log "qcluster terminato con exit code $exitCode" "WARN"
        if ($Once) { exit $exitCode }
    }
    catch {
        Write-Log "Eccezione durante avvio/attesa qcluster: $_" "ERROR"
        if ($Once) { exit 1 }
    }

    Write-Log "Restart tra $RestartDelaySec secondi..." "WARN"
    Start-Sleep -Seconds $RestartDelaySec
}

}
finally {
    if ($ownsMutex) { $clusterMutex.ReleaseMutex() }
    $clusterMutex.Dispose()
}
