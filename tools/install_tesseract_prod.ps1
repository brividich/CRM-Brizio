<#
.SYNOPSIS
  Installa e configura Tesseract OCR per l'acquisizione dei referti di
  sorveglianza sanitaria. Da eseguire SULL'HOST DI PRODUZIONE, come amministratore.

.DESCRIPTION
  Tesseract e' l'unica dipendenza BINARIA di sistema del portale: sta fuori dal
  venv e fuori dal pacchetto di rilascio, quindi non arriva col deploy e va messa
  a mano una volta sola. Senza, il modulo referti archivia le scansioni ma non
  legge nessun campo.

  Lo script fa, in quest'ordine:
    1. mette Tesseract sull'host - SCARICANDOLO da internet (-Scarica), copiando
       una cartella portable (-SorgentePortable) o eseguendo un installer gia'
       presente (-Installer);
    2. verifica che il pacchetto lingua 'ita' ci sia davvero;
    3. scrive TESSERACT_CMD e TESSDATA_PREFIX nel .env PERSISTENTE (con backup);
    4. concede lettura+esecuzione all'identita' dell'app-pool;
    5. riavvia l'app-pool, perche' il .env si legge all'avvio;
    6. prova un OCR vero e dice se il risultato e' utilizzabile.

  IDEMPOTENTE: rieseguirlo su un host gia' a posto non rompe nulla e non
  ricopia inutilmente. Usare -DryRun per vedere cosa farebbe senza toccare niente.

  PERCHE' LA COPIA PORTABLE E' LA STRADA CONSIGLIATA
  La cartella 'tesseract-bin' gia' impacchettata nell'eseguibile usato dalla
  segreteria e' la STESSA build su cui l'estrazione e' stata tarata. Le versioni
  di Tesseract cambiano il motore di riconoscimento fra major: installarne una
  diversa introduce una variabile proprio nel punto piu' delicato. Se e'
  disponibile, si usa quella.

.PARAMETER SorgentePortable
  Cartella contenente tesseract.exe e la sottocartella tessdata (tipicamente la
  'tesseract-bin' dell'eseguibile portable). Se indicata, viene copiata in
  -Destinazione e non serve nessun installer.

.PARAMETER Scarica
  SCARICA Tesseract da internet direttamente sull'host: prende l'ultimo installer
  UB-Mannheim per Windows a 64 bit e, subito dopo, il file lingua 'ita' dal
  repository ufficiale tessdata. E' la strada da usare quando sul server non c'e'
  ne' la cartella portable ne' un installer gia' copiato.
  RICHIEDE che l'host abbia accesso a internet (anche via proxy di sistema).

.PARAMETER Installer
  Percorso di un installer UB-Mannheim gia' scaricato (tesseract-ocr-w64-setup-*.exe),
  da usare quando l'host NON ha accesso a internet. Viene eseguito in modo silenzioso.
  L'installazione silenziosa non porta con se' le lingue aggiuntive: se 'ita' manca
  e non e' consentito scaricarlo, lo script lo dice e si ferma prima di scrivere il .env.

.PARAMETER UrlInstaller
  URL esplicito dell'installer, per saltare il rilevamento automatico della
  versione piu' recente (utile per bloccarsi su una versione nota).

.PARAMETER HostAtteso
  Nome dell'host di produzione atteso. Se il computer su cui gira lo script ha un
  altro nome, compare un avviso: installare sulla macchina sbagliata e' un errore
  silenzioso che si scopre tardi. Default: PCLOGSYS. Vuoto = nessun controllo.

.PARAMETER Destinazione
  Dove installare/copiare Tesseract. Default: C:\PortaleNovicrom\tools\tesseract

.PARAMETER EnvPath
  Il .env PERSISTENTE di produzione (NON current\django_app\.env, che il deploy
  riscrive a ogni rilascio). Default: C:\PortaleNovicrom\prod\config\.env

.PARAMETER AppPool
  Nome dell'app-pool IIS da riavviare e la cui identita' riceve i permessi.
  Default: PortaleNovicrom

.PARAMETER IdentitaAppPool
  Account con cui gira l'app-pool, se diverso da quello rilevato automaticamente
  (es. 'CNOVICROM\hubcn' per un'identita' di dominio).

.PARAMETER PdfDiProva
  PDF su cui fare la verifica finale end-to-end. Facoltativo: senza, la verifica
  si ferma all'elenco delle lingue.

.PARAMETER DryRun
  Mostra le operazioni senza eseguirle.

.EXAMPLE
  # Scarica tutto da internet e configura (host con accesso alla rete)
  .\install_tesseract_prod.ps1 -Scarica

.EXAMPLE
  # Strada consigliata quando la si ha: riusa la build gia' validata
  .\install_tesseract_prod.ps1 -SorgentePortable '\\pcufficio\condivisa\tesseract-bin'

.EXAMPLE
  # Host senza internet, con installer copiato a mano
  .\install_tesseract_prod.ps1 -Installer 'C:\temp\tesseract-ocr-w64-setup-5.5.0.exe'

.EXAMPLE
  # Solo verifica di un host gia' configurato
  .\install_tesseract_prod.ps1 -DryRun

.EXAMPLE
  # Da un'altra macchina, senza copiare lo script sul server
  Invoke-Command -ComputerName PCLOGSYS -FilePath .\install_tesseract_prod.ps1 -ArgumentList @()
#>
[CmdletBinding()]
param(
    [string]$SorgentePortable,
    [switch]$Scarica,
    [string]$Installer,
    [string]$UrlInstaller,
    [string]$HostAtteso     = 'PCLOGSYS',
    [string]$Destinazione    = 'C:\PortaleNovicrom\tools\tesseract',
    [string]$EnvPath         = 'C:\PortaleNovicrom\prod\config\.env',
    [string]$AppPool         = 'PortaleNovicrom',
    [string]$IdentitaAppPool,
    [string]$PdfDiProva,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Info  { param($m) Write-Host "  $m" }
function Passo { param($m) Write-Host "`n[ $m ]" -ForegroundColor Cyan }
function Ok    { param($m) Write-Host "  OK  $m" -ForegroundColor Green }
function Avviso{ param($m) Write-Host "  !   $m" -ForegroundColor Yellow }
function Fatale{ param($m) Write-Host "  X   $m" -ForegroundColor Red; exit 1 }
function Farebbe { param($m) Write-Host "  ~   [dry-run] $m" -ForegroundColor DarkGray }

# Dove stanno le cose, in chiaro: se un domani un indirizzo cambia, si corregge
# qui e non dentro la logica.
$UrlListaInstaller = 'https://digi.bib.uni-mannheim.de/tesseract/'
$UrlLinguaIta      = 'https://github.com/tesseract-ocr/tessdata/raw/main/ita.traineddata'

# Lo User-Agent predefinito di Windows PowerShell viene RIFIUTATO (403) dal sito
# che pubblica gli installer. Non e' un capriccio: senza questo, -Scarica fallisce
# solo in produzione, perche' PowerShell 7 usa un User-Agent diverso e passa.
$UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
             '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'

function Inizializza-Rete {
    # TLS moderno e proxy di sistema: su Windows Server il default puo' non bastare.
    try {
        [Net.ServicePointManager]::SecurityProtocol = `
            [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
    } catch {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    }
    # Molti server escono solo via proxy autenticato con le credenziali di dominio.
    try {
        [Net.WebRequest]::DefaultWebProxy.Credentials = `
            [Net.CredentialCache]::DefaultNetworkCredentials
    } catch { }
    # La barra di avanzamento di Invoke-WebRequest rallenta i download di ordini
    # di grandezza su PowerShell 5: spegnerla non e' estetica.
    $global:ProgressPreference = 'SilentlyContinue'
}

function Scarica-File {
    param([string]$Url, [string]$Destinazione, [string]$Descrizione)
    Info "Scarico $Descrizione..."
    Info "  da $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destinazione -UseBasicParsing -TimeoutSec 300 -UserAgent $UserAgent
    } catch {
        Fatale ("Download fallito ($Descrizione): " + $_.Exception.Message + "`n" +
                "      Se l'host non ha accesso a internet, scarica il file altrove e usa " +
                "-Installer (per l'eseguibile) copiando a mano ita.traineddata in tessdata.")
    }
    if (-not (Test-Path $Destinazione)) { Fatale "File non scaricato: $Descrizione" }
    $mb = [math]::Round((Get-Item $Destinazione).Length / 1MB, 1)
    Ok "$Descrizione scaricato ($mb MB)"
}

function Trova-UltimoInstaller {
    # Ultimo tesseract-ocr-w64-setup-*.exe pubblicato da UB Mannheim.
    Info "Cerco l'ultima versione su $UrlListaInstaller"
    try {
        $pagina = Invoke-WebRequest -Uri $UrlListaInstaller -UseBasicParsing -TimeoutSec 60 -UserAgent $UserAgent
    } catch {
        Fatale ("Elenco versioni non raggiungibile: " + $_.Exception.Message + "`n" +
                "      Usa -UrlInstaller con un indirizzo esplicito, oppure -Installer con un file gia' scaricato.")
    }
    $nomi = [regex]::Matches($pagina.Content, 'tesseract-ocr-w64-setup-[0-9][^"''<>\s]*\.exe') |
            ForEach-Object { $_.Value } | Sort-Object -Unique
    if (-not $nomi) {
        Fatale "Nessun installer w64 trovato nell'elenco. Usa -UrlInstaller con un indirizzo esplicito."
    }
    # I nomi contengono versione e data (5.4.0.20240606): l'ordinamento testuale
    # mette per ultimo il piu' recente. LIMITE NOTO: e' un ordinamento di stringhe,
    # quindi il giorno in cui uscisse una 5.10 verrebbe messa prima della 5.9.
    # Per bloccarsi su una versione precisa c'e' -UrlInstaller.
    $scelto = $nomi | Sort-Object | Select-Object -Last 1
    Ok "Versione individuata: $scelto"
    return ($UrlListaInstaller.TrimEnd('/') + '/' + $scelto)
}

Write-Host "`n=== Tesseract OCR per l'acquisizione referti - NOVICROM HUB ===" -ForegroundColor White
if ($DryRun) { Avviso "Modalita' DRY-RUN: nessuna modifica verra' applicata." }

# -- 0. Prerequisiti ---------------------------------------------------------
Passo "Prerequisiti"

$amministratore = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($amministratore) {
    Ok "Sessione amministrativa."
} elseif ($DryRun) {
    # In dry-run non si scrive niente: pretendere i privilegi impedirebbe di
    # guardare cosa succederebbe, che e' proprio a cosa serve il dry-run.
    Avviso "Sessione non amministrativa: in dry-run va bene, per l'esecuzione vera servira'."
} else {
    Fatale "Servono i diritti di amministratore: la copia dei file, gli ACL e il riavvio dell'app-pool li richiedono."
}

$modi = @($SorgentePortable, $Installer, $(if ($Scarica) { 'scarica' })) |
        Where-Object { $_ }
if ($modi.Count -gt 1) {
    Fatale "Indica UNA sola fra -SorgentePortable, -Installer e -Scarica."
}

if ($HostAtteso -and $env:COMPUTERNAME -and
    $env:COMPUTERNAME.ToUpper() -ne $HostAtteso.ToUpper()) {
    # Installare sulla macchina sbagliata non da' errore: da' un server che
    # sembra a posto e un portale che continua a non leggere niente.
    Avviso "Questo computer si chiama '$env:COMPUTERNAME', non '$HostAtteso'."
    Avviso "Se e' voluto prosegui pure; altrimenti interrompi ora (Ctrl+C) - hai 5 secondi."
    if (-not $DryRun) { Start-Sleep -Seconds 5 }
}
Info "Host: $env:COMPUTERNAME"

if ($Destinazione -match '\s' -and ($Installer -or $Scarica)) {
    # L'installer NSIS vuole /D= come ultimo argomento e SENZA virgolette:
    # con uno spazio nel percorso l'installazione finisce altrove, in silenzio.
    Fatale "Con -Installer o -Scarica la destinazione non puo' contenere spazi: '$Destinazione'."
}

# -- 1. Mettere Tesseract sull'host ------------------------------------------
Passo "Installazione"

$exe = Join-Path $Destinazione 'tesseract.exe'

if ($SorgentePortable) {
    if (-not (Test-Path $SorgentePortable)) {
        Fatale "Cartella sorgente non trovata: $SorgentePortable"
    }
    if (-not (Test-Path (Join-Path $SorgentePortable 'tesseract.exe'))) {
        Fatale "In '$SorgentePortable' non c'e' tesseract.exe. Indica la cartella che lo contiene (tipicamente 'tesseract-bin')."
    }
    if (-not (Test-Path (Join-Path $SorgentePortable 'tessdata'))) {
        Fatale "In '$SorgentePortable' manca la sottocartella 'tessdata': senza dati lingua Tesseract non legge niente."
    }

    if ($DryRun) {
        Farebbe "copia '$SorgentePortable' -> '$Destinazione'"
    } else {
        Info "Copia in corso da '$SorgentePortable'..."
        $null = New-Item -ItemType Directory -Force -Path $Destinazione
        # /E sottocartelle comprese, /NFL /NDL /NJH /NJS output sobrio.
        & robocopy $SorgentePortable $Destinazione /E /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
        # Robocopy usa codici < 8 per "riuscito con variazioni": non sono errori.
        if ($LASTEXITCODE -ge 8) { Fatale "Copia fallita (robocopy $LASTEXITCODE)." }
        Ok "Copiato in $Destinazione"
    }
}
elseif ($Installer -or $Scarica) {
    $daEseguire = $Installer
    $scaricati  = $null

    if ($Scarica) {
        if ($DryRun) {
            Farebbe "scarica l'installer da $UrlListaInstaller e ita.traineddata da GitHub"
            Farebbe "poi installa in '$Destinazione'"
        } else {
            Inizializza-Rete
            $scaricati = Join-Path $env:TEMP ("tesseract-dl-" + [guid]::NewGuid().ToString('N'))
            $null = New-Item -ItemType Directory -Force -Path $scaricati

            $url = if ($UrlInstaller) { $UrlInstaller } else { Trova-UltimoInstaller }
            $daEseguire = Join-Path $scaricati 'tesseract-setup.exe'
            Scarica-File -Url $url -Destinazione $daEseguire -Descrizione "installer Tesseract"
        }
    }

    if (-not $DryRun) {
        if (-not (Test-Path $daEseguire)) { Fatale "Installer non trovato: $daEseguire" }
        Info "Esecuzione installer (silenziosa)..."
        # /D= DEVE restare l'ultimo argomento e senza virgolette (regola NSIS).
        $p = Start-Process -FilePath $daEseguire -ArgumentList "/S", "/D=$Destinazione" -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fatale "Installer uscito con codice $($p.ExitCode)." }
        Ok "Installato in $Destinazione"

        if ($scaricati) {
            # Il file lingua si scarica SEMPRE quando siamo in modalita' -Scarica:
            # l'installazione silenziosa non porta con se' le lingue aggiuntive, e
            # senza 'ita' il riconoscimento dei certificati e' inservibile.
            $cartellaDati = Join-Path $Destinazione 'tessdata'
            $null = New-Item -ItemType Directory -Force -Path $cartellaDati
            Scarica-File -Url $UrlLinguaIta `
                         -Destinazione (Join-Path $cartellaDati 'ita.traineddata') `
                         -Descrizione "pacchetto lingua italiano"
            Remove-Item $scaricati -Recurse -Force -ErrorAction SilentlyContinue
        }
    } elseif ($Installer) {
        Farebbe "esegue '$Installer' in modo silenzioso con destinazione '$Destinazione'"
    }
}
else {
    # Nessuna sorgente: si assume host gia' predisposto, oppure Tesseract nel PATH.
    if (-not (Test-Path $exe)) {
        $nelPath = Get-Command tesseract -ErrorAction SilentlyContinue
        if ($nelPath) {
            $exe = $nelPath.Source
            $Destinazione = Split-Path $exe -Parent
            Avviso "Nessuna sorgente indicata: uso il Tesseract trovato nel PATH ($exe)."
        } else {
            Fatale "Tesseract non e' presente in '$Destinazione' ne' nel PATH. Rilancia con -SorgentePortable o -Installer."
        }
    } else {
        Info "Tesseract gia' presente in ${Destinazione} - nessuna reinstallazione."
    }
}

$tessdata = Join-Path $Destinazione 'tessdata'

if ($DryRun -and -not (Test-Path $exe)) {
    Avviso "Verifiche successive saltate: in dry-run l'eseguibile non e' ancora sul posto."
    Write-Host "`nDry-run completato.`n" -ForegroundColor DarkGray
    exit 0
}
if (-not (Test-Path $exe)) { Fatale "Eseguibile non trovato dopo l'installazione: $exe" }

# -- 2. Il pacchetto lingua italiano c'e' davvero? ---------------------------
Passo "Pacchetto lingua"

$env:TESSDATA_PREFIX = $tessdata
$lingue = & $exe --list-langs 2>&1 | ForEach-Object { $_.ToString().Trim() }
Info ("Versione: " + ((& $exe --version 2>&1 | Select-Object -First 1) -replace '\s+$',''))

if ($lingue -notcontains 'ita') {
    Write-Host ""
    Avviso "Il pacchetto lingua 'ita' NON risulta installato."
    Info "Lingue presenti: $($lingue -join ', ')"
    Info ""
    Info "I certificati sono in italiano: senza 'ita' il riconoscimento e' inservibile."
    Info "Rimedi:"
    Info "  - host con internet : rilancia con -Scarica (prende anche il file lingua)"
    Info "  - host senza internet: copia 'ita.traineddata' in $tessdata"
    Info "    scaricandolo da $UrlLinguaIta"
    Fatale "Interrotto PRIMA di scrivere il .env: un host con le variabili impostate e la lingua assente sembra configurato e non lo e'."
}
Ok "Lingua 'ita' presente."

# -- 3. Configurazione nel .env persistente ----------------------------------
Passo "Configurazione (.env persistente)"

if (-not (Test-Path $EnvPath)) {
    Fatale "File .env non trovato: $EnvPath. Indica con -EnvPath il .env PERSISTENTE (non quello in current\django_app\, che il deploy riscrive)."
}

$daScrivere = @{
    'TESSERACT_CMD'   = $exe
    'TESSDATA_PREFIX' = $tessdata
}

$righe = @(Get-Content -Path $EnvPath -Encoding UTF8)
$modificato = $false

foreach ($chiave in $daScrivere.Keys) {
    $valore = $daScrivere[$chiave]
    $indice = -1
    for ($i = 0; $i -lt $righe.Count; $i++) {
        if ($righe[$i] -match "^\s*$chiave\s*=") { $indice = $i; break }
    }

    if ($indice -ge 0) {
        $attuale = ($righe[$indice] -replace "^\s*$chiave\s*=", '').Trim().Trim('"').Trim("'")
        if ($attuale -eq $valore) {
            Info "$chiave gia' corretta."
            continue
        }
        if ($DryRun) { Farebbe "$chiave : '$attuale' -> '$valore'" }
        else { $righe[$indice] = "$chiave=$valore" }
    } else {
        if ($DryRun) { Farebbe "aggiunge $chiave=$valore" }
        else { $righe += "$chiave=$valore" }
    }
    $modificato = $true
}

if ($modificato -and -not $DryRun) {
    $stamp  = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backup = "$EnvPath.bak_$stamp"
    Copy-Item -Path $EnvPath -Destination $backup -Force
    Info "Backup: $backup"

    # UTF-8 SENZA BOM: un BOM in testa al .env rende illeggibile la prima chiave
    # e ha gia' bloccato dei rilasci in passato.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($EnvPath, $righe, $utf8NoBom)
    Ok "Scritto $EnvPath"
} elseif (-not $modificato) {
    Ok "Nessuna modifica necessaria."
}

# -- 4. Permessi per l'identita' dell'app-pool -------------------------------
Passo "Permessi"

$identita = $IdentitaAppPool
if (-not $identita) {
    try {
        Import-Module WebAdministration -ErrorAction Stop
        $pool = Get-Item "IIS:\AppPools\$AppPool" -ErrorAction Stop
        $identita = if ($pool.processModel.identityType -eq 'SpecificUser') {
            $pool.processModel.userName
        } else {
            "IIS AppPool\$AppPool"
        }
    } catch {
        $identita = "IIS AppPool\$AppPool"
        Avviso "App-pool '$AppPool' non interrogabile: uso '$identita'. Se l'app-pool gira con un account di dominio, rilancia con -IdentitaAppPool."
    }
}
Info "Identita': $identita"

if ($DryRun) {
    Farebbe "icacls '$Destinazione' /grant '${identita}:(OI)(CI)RX' /T"
} else {
    # L'app-pool non gira come l'amministratore che esegue questo script: senza
    # lettura+esecuzione qui, Tesseract non parte e il sintomo e' una coda di
    # referti che non si smaltisce mai, senza errori evidenti.
    $esito = & icacls $Destinazione /grant "${identita}:(OI)(CI)RX" /T /Q 2>&1
    if ($LASTEXITCODE -ne 0) {
        Avviso "Concessione permessi non riuscita: $esito"
        Avviso "Verifica a mano che '$identita' possa leggere ed eseguire in $Destinazione."
    } else {
        Ok "Lettura+esecuzione concesse a $identita"
    }
}

# -- 5. Riavvio dell'app-pool ------------------------------------------------
Passo "Riavvio applicazione"

if ($DryRun) {
    Farebbe "Restart-WebAppPool -Name '$AppPool'"
} else {
    try {
        Import-Module WebAdministration -ErrorAction Stop
        Restart-WebAppPool -Name $AppPool -ErrorAction Stop
        Ok "App-pool '$AppPool' riavviato (il .env si legge all'avvio)."
    } catch {
        Avviso "Riavvio automatico non riuscito: $($_.Exception.Message)"
        Avviso "Riavvia a mano l'app-pool '$AppPool': finche' non riparte, il portale non vede le nuove variabili."
    }
}

# -- 6. Prova vera -----------------------------------------------------------
Passo "Verifica"

if ($DryRun) {
    Farebbe "esegue un OCR di prova"
    Write-Host "`nDry-run completato.`n" -ForegroundColor DarkGray
    exit 0
}

if ($PdfDiProva) {
    if (-not (Test-Path $PdfDiProva)) {
        Avviso "PDF di prova non trovato: $PdfDiProva - verifica end-to-end saltata."
    } else {
        # Qui si verifica il MOTORE, non la catena intera: la rasterizzazione del
        # PDF la fa il portale con PyMuPDF, e riprodurla in PowerShell
        # significherebbe misurare una cosa diversa da quella che gira in
        # produzione. Su un'immagine il controllo e' diretto; su un PDF la prova
        # vera e' il pulsante 'Prova adesso' della pagina Impostazioni.
        if ($PdfDiProva -notmatch '\.(png|jpg|jpeg|tif|tiff|bmp)$') {
            Info "File PDF: la prova completa si fa dal portale col pulsante 'Prova adesso'."
            Info "(qui servirebbe la rasterizzazione, che nel portale fa PyMuPDF)"
        } else {
            $tmp = Join-Path $env:TEMP ("referto-check-" + [guid]::NewGuid().ToString('N'))
            $null = New-Item -ItemType Directory -Force -Path $tmp
            try {
                $uscita = Join-Path $tmp 'out'
                & $exe $PdfDiProva $uscita -l ita --psm 6 2>&1 | Out-Null
                $testo = Get-Content "$uscita.txt" -Raw -ErrorAction SilentlyContinue
                if ($testo -and $testo.Trim().Length -gt 100) {
                    Ok "OCR riuscito: $($testo.Trim().Length) caratteri riconosciuti."
                } else {
                    Avviso "OCR eseguito ma con pochissimo testo: controlla la qualita' della scansione."
                }
            } finally {
                Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Write-Host ""
Write-Host "=== Fatto ===" -ForegroundColor Green
Write-Host "  Eseguibile : $exe"
Write-Host "  Dati lingua: $tessdata"
Write-Host "  Configurato: $EnvPath"
Write-Host ""
Write-Host "Ultimo passo, dal portale:" -ForegroundColor Yellow
Write-Host "  /anagrafica/visite-mediche/referti/impostazioni/"
Write-Host "  Deve comparire 'Riconoscimento testo attivo' col percorso qui sopra."
Write-Host "  Poi indica la cartella delle scansioni, accendi l'acquisizione e usa 'Prova adesso'."
Write-Host ""
Write-Host "Nota: finche' non e' mappato almeno un giudizio nella tabella alias in fondo" -ForegroundColor DarkGray
Write-Host "a quella pagina, i referti restano tutti in coda. E' voluto, ma spiega una coda" -ForegroundColor DarkGray
Write-Host "che sembra non smaltirsi." -ForegroundColor DarkGray
Write-Host ""
