<#
.SYNOPSIS
    Esegue in modo silent il poller della queue automazioni.

.DESCRIPTION
    Wrapper pensato per Task Scheduler Windows. Avvia `process_automation_queue`
    senza mostrare finestre console e appende stdout/stderr a un file di log.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,

    [Parameter(Mandatory = $true)]
    [string]$ManagePy,

    [Parameter(Mandatory = $true)]
    [string]$LogFile,

    [string]$SettingsModule = "config.settings.prod"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python non trovato: $PythonExe"
}
if (-not (Test-Path $ManagePy)) {
    throw "manage.py non trovato: $ManagePy"
}

$logDir = Split-Path -Parent $LogFile
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $PythonExe
$startInfo.WorkingDirectory = Split-Path -Parent $ManagePy
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$null = $startInfo.ArgumentList.Add($ManagePy)
$null = $startInfo.ArgumentList.Add("process_automation_queue")
$null = $startInfo.ArgumentList.Add("--settings=$SettingsModule")

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo
$null = $process.Start()
$stdout = $process.StandardOutput.ReadToEnd()
$stderr = $process.StandardError.ReadToEnd()
$process.WaitForExit()

if ($stdout) {
    Add-Content -Path $LogFile -Value $stdout -Encoding UTF8
}
if ($stderr) {
    Add-Content -Path $LogFile -Value $stderr -Encoding UTF8
}

exit $process.ExitCode
