#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registra in Task Scheduler il raccoglitore del Registro accessi
    (\PortaleNovicrom\RegistroLog_<ENV>), con lo stesso account del qcluster, e lo avvia.

    IMPORTANTE: file in ASCII puro (niente accenti), come start_qcluster.ps1.

.DESCRIPTION
    Il raccoglitore legge il registro eventi dei server Windows (account nel gruppo
    "Event Log Readers") e riceve il syslog di ESXi, switch, firewall e NAS.
    "Registra schedule" non basta: registra solo gli schedule django-q nel database.

    Il task parte all'avvio del server ed esegue <PortaleRoot>\<env>\current\deployment\
    start_registro_log.ps1, cioe' lo script della release attiva. Quando si attiva una release
    nuova il raccoglitore esce da solo e il launcher lo riavvia col codice nuovo: dopo il deploy
    non serve nessun passo.

    Si puo' rilanciare: aggiorna il task esistente e lo riavvia. Nessuna password viene salvata
    nei file: con un account a password la tiene solo Task Scheduler.

.EXAMPLE
    .\install-registro-log-task.ps1 -Environment prod -Credential (Get-Credential 'DOMINIO\utente')
#>
param(
    [ValidateSet('test', 'prod')][string]$Environment = 'prod',
    [string]$PortaleRoot = 'C:\PortaleNovicrom',
    [PSCredential]$Credential
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskPath = '\PortaleNovicrom\'
$workerName = 'QCluster_' + $Environment.ToUpperInvariant()
$taskName = 'RegistroLog_' + $Environment.ToUpperInvariant()
$root = $PortaleRoot.TrimEnd('\')
$script = Join-Path $root "$Environment\current\deployment\start_registro_log.ps1"
if (-not (Test-Path -LiteralPath $script)) {
    throw "Script non trovato: $script. Attivare prima una release che contiene il Registro accessi."
}
$worker = Get-ScheduledTask -TaskPath $taskPath -TaskName $workerName -ErrorAction SilentlyContinue
if (-not $worker) {
    throw "Task $taskPath$workerName non trovato: installare prima il qcluster, il raccoglitore usa lo stesso account."
}
$logon = [string]$worker.Principal.LogonType
if ($logon -eq 'Password') {
    if (-not $Credential) {
        throw 'Il qcluster usa un account con password: passare -Credential con lo stesso account.'
    }
    # CIM puo' abbreviare DOMINIO\utente in utente: l'export del task riporta il SID.
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
        throw 'Le credenziali appartengono a un account diverso dal qcluster (SID diverso). Nessun task modificato.'
    }
} elseif ($logon -notin @('ServiceAccount', 'S4U')) {
    throw 'Il qcluster usa un account interattivo (parte solo con utente connesso): correggere prima il task del qcluster.'
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Environment {1} -PortaleRoot "{2}"' -f $script, $Environment, $root)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $settings `
    -Principal $worker.Principal -Description "Raccoglitore del Registro accessi NOVICROM HUB $($Environment.ToUpperInvariant()) (manage.py registro_log)."
$existing = Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running') {
    # Il launcher tiene i python figli in un job kill-on-close: fermandolo si chiudono anche loro.
    Stop-ScheduledTask -TaskPath $taskPath -TaskName $taskName
    for ($i = 0; $i -lt 20 -and (Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName).State -eq 'Running'; $i++) { Start-Sleep -Seconds 1 }
}
$register = @{ TaskPath=$taskPath; TaskName=$taskName; InputObject=$task; Force=$true }
if ($logon -eq 'Password') {
    $register.User = $Credential.UserName
    $register.Password = $Credential.GetNetworkCredential().Password
}
try { Register-ScheduledTask @register | Out-Null }
finally { $register.Remove('Password') }
Start-ScheduledTask -TaskPath $taskPath -TaskName $taskName
Start-Sleep -Seconds 5
$state = (Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName).State
Write-Host "Installato $taskPath$taskName (account $($worker.Principal.UserId)), stato: $state."
Write-Host "Log: $root\$Environment\logsegistro_log.log. Fonti e impostazioni in SOC > Registro accessi > Fonti."
Write-Output "STATE:$state"
