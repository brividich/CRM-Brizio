#Requires -Version 5.1
<# Console operativa: preparazione e completamento del deploy qcluster.
   Il pacchetto si distribuisce con il wizard/deploy esistente, tra le due fasi.
   Dot-source carica solo le funzioni per i test; nessuna azione automatica.
#>
param(
    [ValidateSet('test','prod')][string]$Environment = 'test',
    [string]$PortaleRoot = 'C:\PortaleNovicrom'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:QC = @{
    Environment=$Environment; Root=[IO.Path]::GetFullPath($PortaleRoot)
    Prepared=$false; Verified=$false; LauncherUpdated=$false; WatchdogInstalled=$false
}

function Get-QCPath([string]$Relative) {
    Join-Path (Join-Path $script:QC.Root $script:QC.Environment) $Relative
}
function Get-QCTaskName { 'QCluster_' + $script:QC.Environment.ToUpperInvariant() }
function Get-QCTask { Get-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName (Get-QCTaskName) }
function Assert-QCAdmin {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Aprire PowerShell come amministratore sul server.'
    }
}
function Confirm-QC([string]$Message) {
    $token = $script:QC.Environment.ToUpperInvariant()
    Write-Host $Message -ForegroundColor Yellow
    if ((Read-Host "Scrivi $token per procedere, Invio per annullare") -cne $token) {
        throw 'Operazione annullata. Nessun passo successivo eseguito.'
    }
}
function Get-QCLauncher {
    $task = Get-QCTask
    $actions = @($task.Actions)
    if ($actions.Count -ne 1 -or [IO.Path]::GetFileName($actions[0].Execute) -notin @('powershell.exe','pwsh.exe')) {
        throw 'Il task deve avere una sola azione PowerShell. Verificare manualmente la configurazione.'
    }
    $arguments = $actions[0].Arguments
    if ($arguments -notmatch '(?i)(?:^|\s)-File\s+(?:"([^"]+)"|(\S+))') { throw 'Parametro -File del launcher non riconosciuto.' }
    $launcher = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
    if (-not [IO.Path]::IsPathRooted($launcher) -or [IO.Path]::GetFileName($launcher) -ne 'start_qcluster.ps1') {
        throw 'Launcher non standard: aggiornamento automatico bloccato.'
    }
    $taskEnvironment = 'prod'
    if ($arguments -match '(?i)(?:^|\s)-Environment\s+"?(test|prod)"?(?=\s|$)') { $taskEnvironment = $Matches[1] }
    if ($taskEnvironment -ne $script:QC.Environment) { throw 'Ambiente del task diverso da quello selezionato.' }
    $taskRoot = 'C:\PortaleNovicrom'
    if ($arguments -match '(?i)(?:^|\s)-PortaleRoot\s+(?:"([^"]+)"|(\S+))') {
        $taskRoot = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
    }
    if ([IO.Path]::GetFullPath($taskRoot).TrimEnd('\') -ne $script:QC.Root.TrimEnd('\')) {
        throw 'Radice del task diversa da -PortaleRoot.'
    }
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Launcher del task non trovato.' }
    return [IO.Path]::GetFullPath($launcher)
}
function Assert-QCPreflight {
    Assert-QCAdmin
    foreach ($relative in @('venv\Scripts\python.exe','current\django_app\manage.py','config\.env')) {
        if (-not (Test-Path -LiteralPath (Get-QCPath $relative) -PathType Leaf)) { throw "File richiesto assente: $relative" }
    }
    $null = Get-QCLauncher
}
function Get-QCWorkerProcesses {
    $python = Get-QCPath 'venv\Scripts\python.exe'
    $environmentPath = Get-QCPath ''
    $processes = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -OperationTimeoutSec 10)
    if (@($processes | Where-Object { -not $_.ExecutablePath -or -not $_.CommandLine }).Count) {
        throw 'Impossibile verificare tutti i processi Python. Controllare i privilegi; nessuna terminazione automatica.'
    }
    @($processes | Where-Object {
        ($_.ExecutablePath -eq $python -or $_.CommandLine.IndexOf($environmentPath, [StringComparison]::OrdinalIgnoreCase) -ge 0) -and
        $_.CommandLine -match '(?i)\b(qcluster|process_automation_queue|process_approval_mailbox)\b|--multiprocessing-fork'
    })
}
function Assert-QCStopped {
    if ((Get-QCTask).State -ne 'Disabled') { throw 'Disabilitare e fermare il worker con Preparazione prima di continuare.' }
    $left = @(Get-QCWorkerProcesses)
    if ($left.Count) { throw "Processi automazioni ancora presenti (PID: $($left.ProcessId -join ', ')). Verificarli e arrestarli manualmente." }
}
function Assert-QCPrepared {
    Assert-QCPreflight
    if (-not $script:QC.Prepared) { throw 'Eseguire Preparazione in questa sessione: include conferma backup SQL e verifica arresto.' }
    Assert-QCStopped
}
function Get-QCReleaseIdentity {
    $current=Get-Item -LiteralPath (Get-QCPath 'current') -Force
    $target=if ($current.PSObject.Properties['Target']) { @($current.Target) -join '|' } else { '' }
    $build=Get-QCPath 'current\BUILD_INFO.json'
    $hash=if (Test-Path -LiteralPath $build) { (Get-FileHash -LiteralPath $build).Hash } else { '' }
    "$($current.FullName)|$target|$($current.CreationTimeUtc.Ticks)|$hash"
}
function Assert-QCVerified {
    Assert-QCPrepared
    if (-not $script:QC.Verified -or $script:QC.VerifiedRelease -ne (Get-QCReleaseIdentity)) {
        throw 'Release non verificata o current cambiato: ripetere opzione 3.'
    }
}
function Set-QCMaintenance {
    $logs = Get-QCPath 'logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    [DateTimeOffset]::UtcNow.AddHours(2).ToString('o') |
        Set-Content -LiteralPath (Join-Path $logs 'qcluster-maintenance-until.txt') -Encoding ASCII
}
function Invoke-QCSteps([string]$Title, [array]$Steps) {
    $completed = 0
    try {
        foreach ($step in $Steps) {
            Write-Host "[$($completed+1)/$($Steps.Count)] $($step.Name)" -ForegroundColor Cyan
            Write-Progress -Id 72 -Activity $Title -Status $step.Name -PercentComplete ([int](100*$completed/$Steps.Count))
            & $step.Run
            $completed++
            Write-Host 'OK' -ForegroundColor Green
        }
        Write-Host "$Title completato: $completed/$($Steps.Count)." -ForegroundColor Green
    } catch {
        Write-Host "INTERROTTO dopo $completed/$($Steps.Count) passi. $($_.Exception.Message)" -ForegroundColor Red
        throw
    } finally { Write-Progress -Id 72 -Activity $Title -Completed }
}
function Invoke-QCPython([string[]]$Arguments, [int[]]$AllowedCodes = @(0)) {
    $previousSettings = $env:DJANGO_SETTINGS_MODULE
    $previousBootstrap = $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP
    $env:DJANGO_SETTINGS_MODULE = 'config.settings.prod'
    $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP = '1'
    Push-Location (Get-QCPath 'current\django_app')
    try {
        & (Get-QCPath 'venv\Scripts\python.exe') manage.py @Arguments --settings=config.settings.prod
        if ($LASTEXITCODE -notin $AllowedCodes) { throw "Comando $($Arguments[0]) fallito (exit $LASTEXITCODE)." }
    } finally {
        Pop-Location
        $env:DJANGO_SETTINGS_MODULE = $previousSettings
        $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP = $previousBootstrap
    }
}
function Invoke-QCHealth([ValidateRange(1,60)][int]$TimeoutSeconds=20) {
    $logs=Get-QCPath 'logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $id=[Guid]::NewGuid().ToString('N')
    $stdout=Join-Path $logs "console-health-$id.out.tmp"
    $stderr=Join-Path $logs "console-health-$id.err.tmp"
    $oldSettings=$env:DJANGO_SETTINGS_MODULE; $oldBootstrap=$env:PORTAL_SKIP_RUNTIME_BOOTSTRAP
    $env:DJANGO_SETTINGS_MODULE='config.settings.prod'; $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP='1'
    $probe=$null
    try {
        $probe=Start-Process -FilePath (Get-QCPath 'venv\Scripts\python.exe') -WorkingDirectory (Get-QCPath 'current\django_app') `
            -ArgumentList @('manage.py','automation_health','--settings=config.settings.prod','--no-color') `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $null=$probe.Handle
        if (-not $probe.WaitForExit($TimeoutSeconds*1000)) {
            # Terminate only this read-only probe and its venv-launcher child.
            & "$env:SystemRoot\System32\taskkill.exe" /PID $probe.Id /T /F | Out-Null
            throw 'Controllo salute scaduto. Nessun worker terminato.'
        }
        if ($probe.ExitCode -notin @(0,2)) { throw "Controllo salute fallito (exit $($probe.ExitCode)); verificare DB/migrazioni." }
        $health=Get-Content -LiteralPath $stdout -Raw | ConvertFrom-Json
        Write-Host ($health | ConvertTo-Json -Compress)
        if ($probe.ExitCode -ne 0 -or $health.unhealthy -ne $false -or $health.worker_alive -ne $true) {
            throw 'Worker o coda non sani.'
        }
    } finally {
        if ($probe) { $probe.Dispose() }
        Remove-Item -LiteralPath $stdout,$stderr -ErrorAction SilentlyContinue
        $env:DJANGO_SETTINGS_MODULE=$oldSettings; $env:PORTAL_SKIP_RUNTIME_BOOTSTRAP=$oldBootstrap
    }
}
function Backup-QCLauncher {
    $backup = Get-QCPath ('logs\qcluster-deploy-backups\' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-Item -LiteralPath (Get-QCLauncher) -Destination (Join-Path $backup 'start_qcluster.ps1')
    Export-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName (Get-QCTaskName) |
        Set-Content -LiteralPath (Join-Path $backup 'worker-task.xml') -Encoding Unicode
    Write-Host "Backup launcher/task: $backup. Il backup SQL resta a cura dell'operatore."
}
function Start-QCPreparation {
    Assert-QCPreflight
    Confirm-QC 'Confermi backup SQL completato, portale in manutenzione e task legacy fermati/disabilitati? Il worker verra fermato.'
    $script:QC.Prepared=$false; $script:QC.Verified=$false; $script:QC.LauncherUpdated=$false; $script:QC.WatchdogInstalled=$false
    $script:QC.Previewed=$false
    Invoke-QCSteps 'Preparazione' @(
        @{Name='Backup launcher e definizione task';Run={ Backup-QCLauncher }},
        @{Name='Pausa watchdog per due ore';Run={ Set-QCMaintenance }},
        @{Name='Disabilitazione e arresto worker';Run={
            Disable-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName (Get-QCTaskName) | Out-Null
            Stop-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName (Get-QCTaskName)
        }},
        @{Name='Verifica processi residui';Run={
            for ($n=0; $n -lt 6; $n++) {
                if (@(Get-QCWorkerProcesses).Count -eq 0) { break }
                Start-Sleep -Seconds 5
            }
            Assert-QCStopped
        }}
    )
    $script:QC.Prepared=$true
    Write-Host 'ORA distribuisci e attiva il pacchetto con il wizard/deploy abituale, poi torna al menu.' -ForegroundColor Yellow
    Write-Host 'Il deploy puo ricreare il poller legacy: disabilitalo di nuovo prima di proseguire. Non avviare ancora il qcluster.'
}
function Invoke-QCVerification {
    Assert-QCPrepared
    $script:QC.Verified=$false
    $script:QC.Previewed=$false; $script:QC.LauncherUpdated=$false; $script:QC.WatchdogInstalled=$false
    $release=Get-QCReleaseIdentity
    foreach ($relative in @('current\deployment\watch_qcluster.ps1','current\deployment\scripts\install-qcluster-watchdog.ps1',
        'current\django_app\automazioni\migrations\0027_clusterheartbeat_clusterwatchdogstate.py')) {
        if (-not (Test-Path -LiteralPath (Get-QCPath $relative))) { throw 'Release priva del watchdog: verificare il pacchetto e current.' }
    }
    Set-QCMaintenance
    Invoke-QCSteps 'Configurazione nuova release' @(
        @{Name='Migrazioni di tutti i moduli';Run={ Invoke-QCPython @('migrate','--noinput') }},
        @{Name='Trigger SQL';Run={ Invoke-QCPython @('apply_sql_triggers') }},
        @{Name='Pianificazioni e flussi gestiti';Run={ Invoke-QCPython @('setup_q_schedules') }},
        @{Name='Controllo Django';Run={ Invoke-QCPython @('check') }},
        @{Name='Verifica nessuna migrazione pendente';Run={ Invoke-QCPython @('migrate','--check') }}
    )
    if ($release -ne (Get-QCReleaseIdentity)) { throw 'current e cambiato durante la verifica: ripetere il controllo.' }
    $script:QC.VerifiedRelease=$release; $script:QC.Verified=$true
}
function Update-QCLauncher {
    Assert-QCVerified
    $script:QC.LauncherUpdated=$false
    $source = Get-QCPath 'current\deployment\start_qcluster.ps1'
    $destination = Get-QCLauncher
    if (-not (Test-Path -LiteralPath $source)) { throw 'Launcher non presente nella nuova release.' }
    Backup-QCLauncher
    if ([IO.Path]::GetFullPath($source) -ne $destination) { Copy-Item -LiteralPath $source -Destination $destination -Force }
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash) { throw 'Verifica copia launcher fallita.' }
    $script:QC.LauncherUpdated=$true
    Write-Host "Launcher verificato: $destination"
}
function Get-QCWorkerAccount {
    [xml]$taskXml = Export-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName (Get-QCTaskName)
    $identity = [string]$taskXml.Task.Principals.Principal.UserId
    try {
        $sid = if ($identity -match '^S-1-') {
            [Security.Principal.SecurityIdentifier]::new($identity)
        } else {
            [Security.Principal.NTAccount]::new($identity).Translate([Security.Principal.SecurityIdentifier])
        }
        $sid.Translate([Security.Principal.NTAccount]).Value
    } catch {
        throw 'Impossibile risolvere l account del task: verificare la connessione al dominio.'
    }
}
function Install-QCWatchdog {
    Assert-QCVerified
    Set-QCMaintenance
    $script:QC.WatchdogInstalled=$false
    $worker = Get-QCTask
    $options = @{Environment=$script:QC.Environment;PortaleRoot=$script:QC.Root}
    if ([string]$worker.Principal.LogonType -eq 'Password') {
        $account = Get-QCWorkerAccount
        Write-Host "Account del worker verificato: $account"
        $options.Credential = Get-Credential -UserName $account -Message "Password per $account (mantenere il nome completo)"
        if (-not $options.Credential) { throw 'Credenziali annullate.' }
    }
    & (Get-QCPath 'current\deployment\scripts\install-qcluster-watchdog.ps1') @options
    $watch = Get-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName ('QClusterWatchdog_' + $script:QC.Environment.ToUpperInvariant())
    if ($watch.State -eq 'Disabled') { throw 'Watchdog installato ma disabilitato.' }
    $script:QC.WatchdogInstalled=$true
}
function Start-QCWorker {
    Assert-QCVerified
    if (-not ($script:QC.Verified -and $script:QC.LauncherUpdated -and $script:QC.WatchdogInstalled)) {
        throw 'Completare prima configurazione, launcher e installazione watchdog in questa sessione.'
    }
    Enable-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName (Get-QCTaskName) | Out-Null
    Start-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName (Get-QCTaskName)
    Write-Host 'Attendo il primo heartbeat: tre sonde limitate a 20s, intervallo 10s. La manutenzione resta attiva.'
    $healthy=$false
    for ($attempt=1; $attempt -le 3; $attempt++) {
        Write-Progress -Id 73 -Activity 'Avvio worker' -Status "Controllo $attempt/3" -PercentComplete (($attempt-1)*100/3)
        Start-Sleep -Seconds 10
        try { Invoke-QCHealth; $healthy=$true; break }
        catch { Write-Host 'Worker/coda non ancora sani.' -ForegroundColor Yellow }
    }
    Write-Progress -Id 73 -Activity 'Avvio worker' -Completed
    # Resume even if unhealthy: the independent watchdog must report the problem.
    $maintenance = Get-QCPath 'logs\qcluster-maintenance-until.txt'
    if (Test-Path -LiteralPath $maintenance) { Remove-Item -LiteralPath $maintenance }
    Start-ScheduledTask -TaskPath '\PortaleNovicrom\' -TaskName ('QClusterWatchdog_' + $script:QC.Environment.ToUpperInvariant())
    $script:QC.Prepared=$false
    if (-not $healthy) { throw 'Worker/coda non sani dopo tre sonde. Watchdog riattivato: consultare log, non riaprire il portale.' }
    Write-Host 'Worker sano e watchdog riattivato. Verificare entro 2 minuti ultimo controllo e consegna email in TEST.' -ForegroundColor Green
}
function Invoke-QCRecovery([switch]$Apply) {
    Assert-QCVerified
    if ($Apply) {
        Confirm-QC 'Operazione straordinaria: hai verificato le anteprime in questa sessione e il backup SQL? Unione Assenze e recupero broker modificano dati.'
        if (-not $script:QC.ContainsKey('Previewed') -or -not $script:QC.Previewed) { throw 'Eseguire prima le anteprime (opzione 7).' }
        $script:QC.Previewed=$false
        Invoke-QCPython @('merge_assenze_flows','--apply','--workers-stopped')
        Invoke-QCPython @('recover_automation_broker','--apply','--workers-stopped')
    } else {
        $script:QC.Previewed=$false
        Invoke-QCPython @('merge_assenze_flows')
        Invoke-QCPython @('recover_automation_broker')
        $script:QC.Previewed=$true
    }
}
function Show-QCStatus {
    Assert-QCPreflight
    $task=Get-QCTask
    Write-Host "Worker: $($task.State) | Account: $($task.Principal.UserId) | Logon: $($task.Principal.LogonType)"
    Write-Host "Launcher: $(Get-QCLauncher)"
    $pause=Get-QCPath 'logs\qcluster-maintenance-until.txt'
    if (Test-Path -LiteralPath $pause) { Write-Host "Manutenzione fino a: $(Get-Content -LiteralPath $pause -Raw)" }
    Invoke-QCHealth -TimeoutSeconds 45
}
function Start-QCMenu {
    Assert-QCAdmin
    while ($true) {
        Write-Host "`nNOVICROM HUB | QCLUSTER | $($script:QC.Environment.ToUpperInvariant()) | $($script:QC.Root)" -ForegroundColor Cyan
        Write-Host "Preparato=$($script:QC.Prepared) Configurato=$($script:QC.Verified) Launcher=$($script:QC.LauncherUpdated) Watchdog=$($script:QC.WatchdogInstalled)"
        Write-Host @'
 1  Diagnostica e stato (sola lettura)
 2  PRIMA DEL DEPLOY: backup launcher, pausa e arresto
    -> Distribuisci/attiva il pacchetto con il wizard abituale, poi torna qui.
 3  DOPO IL DEPLOY: migrazioni, trigger, pianificazioni e check
 4  Aggiorna il launcher realmente usato dal task
 5  Installa/aggiorna il watchdog
 6  Avvia worker, verifica salute e riattiva watchdog
 7  Recupero precedente: ANTEPRIMA Assenze e broker
 8  Recupero precedente: APPLICA (opzionale, dopo anteprima)
 9  Completa in sequenza 3 -> 4 -> 5 -> 6 (senza recupero dati)
 L  Percorsi log e istruzioni finali
 0  Esci (non cambia lo stato dei task)
'@
        $choice=Read-Host 'Scelta'
        if ($choice -eq '0') { Write-Host 'Controllare lo stato del worker prima di lasciare il server. Nessun riavvio implicito.'; return }
        try {
            switch ($choice.ToUpperInvariant()) {
                '1' { Show-QCStatus }
                '2' { Start-QCPreparation }
                '3' { Confirm-QC 'Confermi nuova release attivata, portale in manutenzione e task legacy nuovamente disabilitati?'; Invoke-QCVerification }
                '4' { Confirm-QC 'Aggiornare il launcher del task?'; Update-QCLauncher }
                '5' { Confirm-QC 'Installare il controllo esterno con email agli amministratori configurati?'; Install-QCWatchdog }
                '6' { Confirm-QC 'Avviare worker e riattivare il watchdog?'; Start-QCWorker }
                '7' { Invoke-QCRecovery }
                '8' { Invoke-QCRecovery -Apply }
                '9' {
                    Confirm-QC 'Confermi nuova release attivata, portale in manutenzione, legacy disabilitati e destinatari email verificati? Eseguo 3-4-5-6.'
                    Invoke-QCSteps 'Completamento guidato' @(
                        @{Name='Configurazione database';Run={ Invoke-QCVerification }},
                        @{Name='Aggiornamento launcher';Run={ Update-QCLauncher }},
                        @{Name='Installazione watchdog';Run={ Install-QCWatchdog }},
                        @{Name='Avvio e verifica';Run={ Start-QCWorker }}
                    )
                }
                'L' {
                    Write-Host "Log: $(Get-QCPath 'logs\qcluster.log') e $(Get-QCPath 'logs\qcluster-watchdog.log')"
                    Write-Host 'Event Viewer > Applicazione > NovicromQCluster. Collaudare allarme/ripristino in TEST.'
                    Write-Host 'Riaprire il portale solo dopo salute regolare e verifica avanzamento coda. Il fermo server richiede monitor esterno.'
                }
                default { Write-Host 'Scelta non valida.' -ForegroundColor Yellow }
            }
        } catch { Write-Host "ERRORE: $($_.Exception.Message)" -ForegroundColor Red }
    }
}
if ($MyInvocation.InvocationName -ne '.') { Start-QCMenu }
