# install-sql2025-instance.ps1
# Installa (silent, idempotente) un'istanza nominata di SQL Server 2025 Express
# AFFIANCATA a quella esistente, con la stessa collation e lo stesso modo di
# autenticazione dell'istanza di origine. Non tocca l'istanza esistente né i suoi DB.
#
# Uso:
#   .\install-sql2025-instance.ps1 -MediaPath D:\SQL2025\Express -WhatIf
#   .\install-sql2025-instance.ps1 -MediaPath D:\SQL2025\Express -InstanceName HUB2025 -TcpPort 14330
#   .\install-sql2025-instance.ps1 -InstallerPath D:\SQLEXPR_x64_ENU.exe            # pacchetto da estrarre
#
# Media: dal bootstrapper ufficiale SQL2025-SSEI-Expr.exe → «Scarica supporti» → «Express Core»
# (pacchetto SQLEXPR_x64_*.exe). Vedi docs/dr/SQL2025_MIGRAZIONE.md.
#
# Esito: exit 0 = installata/già presente e verificata; 3010 = installata, serve riavvio; 1 = errore.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstanceName = "HUB2025",
    [string]$SourceInstance = ".\SQLEXPRESS",
    [string]$MediaPath = "",
    [string]$InstallerPath = "",
    [ValidateRange(1024, 65535)][int]$TcpPort = 14330,
    [string[]]$SysAdminAccounts = @(),
    [string]$DataDir = "",
    [string]$WorkDir = "C:\PortaleNovicrom\shared\sql2025",
    [switch]$OpenFirewall,
    # Macchina nuova (restore-host.ps1): collation e autenticazione dal manifest del backup,
    # senza leggerle da un'istanza esistente.
    [string]$Collation = "",
    [ValidateSet("", "windows", "mixed")][string]$AuthMode = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"
. "$PSScriptRoot\_sqllib.ps1"

if ($InstanceName -notmatch '^[A-Za-z][A-Za-z0-9_]{0,15}$' -or $InstanceName -ieq "MSSQLSERVER" -or $InstanceName -ieq "SQLEXPRESS") {
    Write-Log "Nome istanza non valido o riservato: '$InstanceName'." "ERROR"; exit 1
}
$dryRun = [bool]$WhatIfPreference
if (-not $dryRun) { Assert-Admin }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force -Path $WorkDir -WhatIf:$false | Out-Null
$transcript = Join-Path $WorkDir "install-$InstanceName-$stamp.log"
$wi = $WhatIfPreference; $WhatIfPreference = $false; Start-Transcript -Path $transcript -Append | Out-Null; $WhatIfPreference = $wi
try {
    Write-LogSeparator
    Write-Log "Istanza SQL Server 2025 affiancata: $InstanceName (origine: $SourceInstance)$(if ($dryRun) { ' [WhatIf]' })" "STEP"

    # ── 1. Prerequisiti ufficiali (Microsoft Learn, «SQL Server 2025: Hardware and Software Requirements») ──
    $os = Get-CimInstance Win32_OperatingSystem
    $build = [int]$os.BuildNumber
    $isServer = $os.ProductType -ne 1
    Write-Log "Sistema: $($os.Caption) build $build" "INFO"
    if ((-not $isServer -and $build -lt 10240) -or ($isServer -and $build -lt 17763)) {
        throw "Sistema non supportato: serve Windows 10/11 o Windows Server 2019+."
    }
    if ($os.Caption -match "Windows 1[01]" -and $os.Caption -notmatch "Pro|Business|Enterprise|Home|IoT|Education") {
        Write-Log "Edizione di Windows non presente nella matrice ufficiale: verificare prima di procedere." "WARN"
    }
    $netRelease = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" -ErrorAction SilentlyContinue).Release
    if (-not $netRelease -or $netRelease -lt 461808) { throw ".NET Framework 4.7.2 o superiore richiesto (Release=$netRelease)." }
    $ramMB = [int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)
    if ($ramMB -lt 1024) { Write-Log "RAM $ramMB MB: sotto il consigliato (1 GB) per Express." "WARN" }
    $freeSys = Get-FreeSpaceMB $env:SystemDrive
    if ($freeSys -ne $null -and $freeSys -lt 6144) { throw "Servono almeno 6 GB liberi sul disco di sistema (liberi: $freeSys MB)." }
    Write-Log "Prerequisiti OK (.NET release $netRelease, RAM $ramMB MB, liberi su $($env:SystemDrive) $freeSys MB)." "SUCCESS"

    $target = ".\$InstanceName"
    $serviceName = "MSSQL`$$InstanceName"

    # ── 2. Idempotenza: istanza già presente? ──
    $existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Log "Servizio $serviceName già presente (stato: $($existing.Status))." "INFO"
        if ($existing.Status -ne "Running" -and -not $dryRun) { Start-Service $serviceName }
    }

    # ── 3. Collation e autenticazione dall'istanza di origine ──
    if ($Collation) {
        $src = [pscustomobject]@{ Edition = "(dal manifest del backup)"; ProductVersion = "-"; Collation = $Collation
                                  WindowsAuthOnly = ($AuthMode -ne "mixed") }
    } else {
        $src = Get-SqlInstanceInfo -Instance $SourceInstance
    }
    Write-Log "Origine ${SourceInstance}: $($src.Edition) $($src.ProductVersion), collation $($src.Collation), $(if ($src.WindowsAuthOnly) { 'solo Windows' } else { 'mista' })" "INFO"

    if (-not $existing) {
        if ($SysAdminAccounts.Count -eq 0) {
            $SysAdminAccounts = @([Security.Principal.WindowsIdentity]::GetCurrent().Name, "BUILTIN\Administrators")
        }
        $setupExe = $null
        if ($MediaPath) {
            $setupExe = Join-Path $MediaPath "setup.exe"
        } elseif ($InstallerPath) {
            $extractDir = Join-Path $WorkDir "media-$stamp"
            if ($PSCmdlet.ShouldProcess($InstallerPath, "Estrazione supporti in $extractDir")) {
                $p = Start-Process -FilePath $InstallerPath -ArgumentList "/q", "/x:`"$extractDir`"" -Wait -PassThru
                if ($p.ExitCode -ne 0) { throw "Estrazione del pacchetto fallita (exit $($p.ExitCode))." }
            }
            $setupExe = Join-Path $extractDir "setup.exe"
        } else {
            throw "Indicare -MediaPath (cartella con setup.exe) o -InstallerPath (pacchetto SQLEXPR_x64_*.exe)."
        }
        if (-not $dryRun -and -not (Test-Path $setupExe)) { throw "setup.exe non trovato: $setupExe" }

        $admins = ($SysAdminAccounts | ForEach-Object { '"' + $_ + '"' }) -join " "
        $ini = @(
            "; Generato da install-sql2025-instance.ps1 il $stamp — nessuna password in questo file",
            "[OPTIONS]",
            'ACTION="Install"',
            'FEATURES=SQLENGINE',
            "INSTANCENAME=`"$InstanceName`"",
            "INSTANCEID=`"$InstanceName`"",
            "SQLCOLLATION=`"$($src.Collation)`"",
            "SQLSYSADMINACCOUNTS=$admins",
            "SQLSVCACCOUNT=`"NT Service\MSSQL`$$InstanceName`"",
            'SQLSVCSTARTUPTYPE="Automatic"',
            'TCPENABLED="1"',
            'NPENABLED="0"',
            'BROWSERSVCSTARTUPTYPE="Automatic"',
            'UPDATEENABLED="False"',
            'SUPPRESSPRIVACYSTATEMENTNOTICE="True"',
            'INDICATEPROGRESS="True"'
        )
        if ($DataDir) {
            $ini += "SQLUSERDBDIR=`"$DataDir`""
            $ini += "SQLUSERDBLOGDIR=`"$DataDir`""
            $ini += "SQLBACKUPDIR=`"$(Join-Path $DataDir 'Backup')`""
        }
        $iniPath = Join-Path $WorkDir "ConfigurationFile-$InstanceName.ini"
        $ini | Set-Content -Path $iniPath -Encoding Unicode -WhatIf:$false
        Write-Log "ConfigurationFile: $iniPath" "INFO"
        $ini | ForEach-Object { Write-Host "    $_" }

        if ($PSCmdlet.ShouldProcess("$env:COMPUTERNAME\$InstanceName", "Installazione silent SQL Server 2025 Express")) {
            Write-Log "Avvio setup (alcuni minuti)..." "STEP"
            $p = Start-Process -FilePath $setupExe -ArgumentList "/ConfigurationFile=`"$iniPath`"", "/IACCEPTSQLSERVERLICENSETERMS", "/Q" -Wait -PassThru -NoNewWindow
            if ($p.ExitCode -notin @(0, 3010)) {
                throw "Setup terminato con exit $($p.ExitCode): vedi %ProgramFiles%\Microsoft SQL Server\170\Setup Bootstrap\Log\Summary.txt"
            }
            $script:setupExit = $p.ExitCode
            Write-Log "Setup completato (exit $($p.ExitCode))." "SUCCESS"
        }
    }

    # ── 4. Modo di autenticazione come l'origine (mai una password su riga di comando) ──
    $instanceNames = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL" -ErrorAction SilentlyContinue
    $instanceId = if ($instanceNames -and $instanceNames.PSObject.Properties[$InstanceName]) { $instanceNames.$InstanceName } else { $null }
    if (-not $instanceId -and $dryRun) { $instanceId = "MSSQL17.$InstanceName" }
    if (-not $instanceId) { throw "Istanza $InstanceName non trovata nel registro dopo l'installazione." }
    $regBase = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId\MSSQLServer"
    $needRestart = $false
    $wantedMode = if ($src.WindowsAuthOnly) { 1 } else { 2 }
    $regProps = Get-ItemProperty $regBase -ErrorAction SilentlyContinue
    $currentMode = if ($regProps -and $regProps.PSObject.Properties["LoginMode"]) { $regProps.LoginMode } else { $null }
    if ($currentMode -ne $wantedMode) {
        if ($PSCmdlet.ShouldProcess($InstanceName, "LoginMode = $wantedMode ($(if ($wantedMode -eq 1) { 'solo Windows' } else { 'mista, sa resta disabilitato' }))")) {
            Set-ItemProperty -Path $regBase -Name LoginMode -Value $wantedMode
            $needRestart = $true
        }
    }

    # ── 5. Porta TCP fissa ──
    $tcpKey = "$regBase\SuperSocketNetLib\Tcp\IPAll"
    $tcp = Get-ItemProperty $tcpKey -ErrorAction SilentlyContinue
    $tcpPortNow = if ($tcp -and $tcp.PSObject.Properties["TcpPort"]) { "$($tcp.TcpPort)" } else { "" }
    $tcpDynNow = if ($tcp -and $tcp.PSObject.Properties["TcpDynamicPorts"]) { "$($tcp.TcpDynamicPorts)" } else { "" }
    if ($tcpPortNow -ne "$TcpPort" -or $tcpDynNow -ne "") {
        $inUse = Get-NetTCPConnection -LocalPort $TcpPort -State Listen -ErrorAction SilentlyContinue
        if ($inUse -and -not $dryRun) {
            $owner = (Get-Process -Id ($inUse | Select-Object -First 1).OwningProcess -ErrorAction SilentlyContinue).ProcessName
            if ($owner -ne "sqlservr") { throw "Porta $TcpPort già in uso da '$owner'." }
        }
        if ($PSCmdlet.ShouldProcess($InstanceName, "Porta TCP fissa $TcpPort")) {
            Set-ItemProperty -Path "$regBase\SuperSocketNetLib\Tcp" -Name Enabled -Value 1
            Set-ItemProperty -Path $tcpKey -Name TcpPort -Value "$TcpPort"
            Set-ItemProperty -Path $tcpKey -Name TcpDynamicPorts -Value ""
            $needRestart = $true
        }
    }
    if ($needRestart -and -not $dryRun) {
        Write-Log "Riavvio del servizio $serviceName per applicare la configurazione." "STEP"
        Restart-Service -Name $serviceName -Force
        Start-Sleep -Seconds 3
    }

    if ($OpenFirewall) {
        $ruleName = "SQL Server $InstanceName (TCP $TcpPort)"
        if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
            if ($PSCmdlet.ShouldProcess($ruleName, "Regola firewall in ingresso (profilo Domain)")) {
                New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $TcpPort -Action Allow -Profile Domain | Out-Null
            }
        }
    } else {
        Write-Log "Firewall non modificato: il portale gira sulla stessa macchina (usare -OpenFirewall solo se serve l'accesso da rete)." "INFO"
    }

    # ── 6. Verifica ──
    if ($dryRun) {
        Write-Log "WhatIf: nessuna modifica eseguita. Collation prevista: $($src.Collation); porta $TcpPort." "SUCCESS"
        exit 0
    }
    $info = Get-SqlInstanceInfo -Instance $target
    if ($info.Major -lt 17) { throw "L'istanza $target risponde con versione $($info.ProductVersion): attesa 17.x (2025)." }
    if ($info.Collation -ne $src.Collation) { throw "Collation diversa: $($info.Collation) ≠ $($src.Collation) dell'origine." }
    if ($info.Edition -notmatch "Express") { Write-Log "Edizione rilevata: $($info.Edition) (attesa Express)." "WARN" }
    $port = Invoke-SqlQuery -Instance "tcp:127.0.0.1,$TcpPort" -Query "SELECT CAST(SERVERPROPERTY('InstanceName') AS NVARCHAR(128))"
    Write-Log "Istanza $target pronta: $($info.Edition) $($info.ProductVersion), collation $($info.Collation), TCP $TcpPort (risponde come '$($port[0][0])')." "SUCCESS"
    Write-Log "DB_HOST possibili: '$($info.MachineName)\$InstanceName' (con SQL Browser) oppure '$($info.MachineName),$TcpPort'." "INFO"
    if ((Get-Variable setupExit -Scope Script -ErrorAction SilentlyContinue) -and $script:setupExit -eq 3010) {
        Write-Log "Il setup richiede un riavvio della macchina." "WARN"; exit 3010
    }
    exit 0
} catch {
    Write-Log "$_" "ERROR"
    exit 1
} finally {
    $WhatIfPreference = $false; Stop-Transcript | Out-Null
}


