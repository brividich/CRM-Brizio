#Requires -Version 5.1
#Requires -RunAsAdministrator
param(
    [ValidateSet('test', 'prod')][string]$Environment = 'prod',
    [string]$PortaleRoot = 'C:\PortaleNovicrom',
    [PSCredential]$Credential
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskPath = '\PortaleNovicrom\'
$workerName = 'QCluster_' + $Environment.ToUpperInvariant()
$worker = Get-ScheduledTask -TaskPath $taskPath -TaskName $workerName
$watchName = 'QClusterWatchdog_' + $Environment.ToUpperInvariant()
$source = Join-Path (Split-Path $PSScriptRoot -Parent) 'watch_qcluster.ps1'
$destDir = Join-Path $PortaleRoot 'shared\scripts'
$dest = Join-Path $destDir 'watch_qcluster.ps1'
$logon = [string]$worker.Principal.LogonType
if ($logon -eq 'Password') {
    if (-not $Credential) {
        throw 'Passare -Credential per lo stesso account del worker (Get-Credential). Nessuna password viene salvata nei file.'
    }
    # CIM may abbreviate DOMAIN\user to user. The exported task stores its SID.
    [xml]$workerXml = Export-ScheduledTask -TaskPath $taskPath -TaskName $workerName
    $workerIdentity = [string]$workerXml.Task.Principals.Principal.UserId
    try {
        $workerSid = if ($workerIdentity -match '^S-1-') {
            [Security.Principal.SecurityIdentifier]::new($workerIdentity)
        } else {
            [Security.Principal.NTAccount]::new($workerIdentity).Translate([Security.Principal.SecurityIdentifier])
        }
        $credentialSid = [Security.Principal.NTAccount]::new($Credential.UserName).Translate([Security.Principal.SecurityIdentifier])
    } catch {
        throw 'Impossibile risolvere gli account Windows. Usare DOMINIO\utente e verificare la connessione al dominio.'
    }
    if ($credentialSid.Value -ne $workerSid.Value) {
        throw 'Le credenziali appartengono a un account diverso dal worker (SID diverso). Nessun task modificato.'
    }
} elseif ($logon -notin @('ServiceAccount', 'S4U')) {
    throw 'Il worker deve usare un account non interattivo (Password, ServiceAccount o S4U). Correggere prima il task worker.'
}
if (-not [Diagnostics.EventLog]::SourceExists('NovicromQCluster')) {
    New-EventLog -LogName Application -Source 'NovicromQCluster'
}
New-Item -ItemType Directory -Path $destDir -Force | Out-Null
if (Test-Path -LiteralPath $dest) {
    Copy-Item -LiteralPath $dest -Destination "$dest.$([DateTime]::UtcNow.ToString('yyyyMMddHHmmssfff')).bak"
}
Copy-Item -LiteralPath $source -Destination $dest -Force
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Environment {1} -PortaleRoot "{2}"' -f $dest, $Environment, $PortaleRoot.TrimEnd('\'))
$startup = New-ScheduledTaskTrigger -AtStartup
$minute = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Trigger @($startup, $minute) -Settings $settings `
    -Principal $worker.Principal -Description "Controllo esterno qcluster $Environment ogni minuto, email e ripristino task fermo."
$register = @{ TaskPath=$taskPath; TaskName=$watchName; InputObject=$task; Force=$true }
if ($logon -eq 'Password') {
    $register.User = $Credential.UserName
    $register.Password = $Credential.GetNetworkCredential().Password
}
try { Register-ScheduledTask @register | Out-Null }
finally { $register.Remove('Password') }
Write-Host "Installato $taskPath$watchName. Primo controllo entro un minuto. Account: $($worker.Principal.UserId)."
Write-Host 'Verificare migrazioni, heartbeat e destinatari MONITORING_ADMIN_EMAILS. Testare arresto e ripristino in TEST.'
