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
    1. mette Tesseract sull'host (copia portable oppure installer gia' scaricato);
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

.PARAMETER Installer
  Percorso di un installer UB-Mannheim gia' scaricato (tesseract-ocr-w64-setup-*.exe),
  da usare quando non si ha la copia portable. Viene eseguito in modo silenzioso.
  ATTENZIONE: l'installazione silenziosa NON include le lingue aggiuntive; se
  'ita' manca, lo script lo dice e si ferma prima di scrivere il .env.

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
  # Strada consigliata: riusa la build gia' validata
  .\install_tesseract_prod.ps1 -SorgentePortable '\\pcufficio\condivisa\tesseract-bin'

.EXAMPLE
  # Con installer scaricato a parte
  .\install_tesseract_prod.ps1 -Installer 'C:\temp\tesseract-ocr-w64-setup-5.5.0.exe'

.EXAMPLE
  # Solo verifica di un host gia' configurato
  .\install_tesseract_prod.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$SorgentePortable,
    [string]$Installer,
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

Write-Host "`n=== Tesseract OCR per l'acquisizione referti — NOVICROM HUB ===" -ForegroundColor White
if ($DryRun) { Avviso "Modalita' DRY-RUN: nessuna modifica verra' applicata." }

# ── 0. Prerequisiti ─────────────────────────────────────────────────────────
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

if ($SorgentePortable -and $Installer) {
    Fatale "Indica -SorgentePortable OPPURE -Installer, non entrambi."
}

# ── 1. Mettere Tesseract sull'host ──────────────────────────────────────────
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
elseif ($Installer) {
    if (-not (Test-Path $Installer)) { Fatale "Installer non trovato: $Installer" }
    if ($DryRun) {
        Farebbe "esegue '$Installer' in modo silenzioso con destinazione '$Destinazione'"
    } else {
        Info "Esecuzione installer (silenziosa)..."
        $p = Start-Process -FilePath $Installer -ArgumentList "/S", "/D=$Destinazione" -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fatale "Installer uscito con codice $($p.ExitCode)." }
        Ok "Installato in $Destinazione"
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
        Info "Tesseract gia' presente in ${Destinazione} — nessuna reinstallazione."
    }
}

$tessdata = Join-Path $Destinazione 'tessdata'

if ($DryRun -and -not (Test-Path $exe)) {
    Avviso "Verifiche successive saltate: in dry-run l'eseguibile non e' ancora sul posto."
    Write-Host "`nDry-run completato.`n" -ForegroundColor DarkGray
    exit 0
}
if (-not (Test-Path $exe)) { Fatale "Eseguibile non trovato dopo l'installazione: $exe" }

# ── 2. Il pacchetto lingua italiano c'e' davvero? ───────────────────────────
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
    Info "Rimedio: copiare 'ita.traineddata' in $tessdata"
    Info "  (installer UB-Mannheim: rieseguirlo spuntando Additional language data -> Italian)"
    Fatale "Configurazione interrotta prima di scrivere il .env, per non lasciare l'host in uno stato a meta'."
}
Ok "Lingua 'ita' presente."

# ── 3. Configurazione nel .env persistente ──────────────────────────────────
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

# ── 4. Permessi per l'identita' dell'app-pool ───────────────────────────────
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

# ── 5. Riavvio dell'app-pool ────────────────────────────────────────────────
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

# ── 6. Prova vera ───────────────────────────────────────────────────────────
Passo "Verifica"

if ($DryRun) {
    Farebbe "esegue un OCR di prova"
    Write-Host "`nDry-run completato.`n" -ForegroundColor DarkGray
    exit 0
}

if ($PdfDiProva) {
    if (-not (Test-Path $PdfDiProva)) {
        Avviso "PDF di prova non trovato: $PdfDiProva — verifica end-to-end saltata."
    } else {
        # Qui si verifica il MOTORE, non la catena intera: la rasterizzazione del
        # PDF la fa il portale con PyMuPDF, e riprodurla in PowerShell
        # significherebbe misurare una cosa diversa da quella che gira in
        # produzione. Su un'immagine il controllo e' diretto; su un PDF la prova
        # vera e' il pulsante «Prova adesso» della pagina Impostazioni.
        if ($PdfDiProva -notmatch '\.(png|jpg|jpeg|tif|tiff|bmp)$') {
            Info "File PDF: la prova completa si fa dal portale col pulsante «Prova adesso»."
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
Write-Host "  Deve comparire «Riconoscimento testo attivo» col percorso qui sopra."
Write-Host "  Poi indica la cartella delle scansioni, accendi l'acquisizione e usa «Prova adesso»."
Write-Host ""
Write-Host "Nota: finche' non e' mappato almeno un giudizio nella tabella alias in fondo" -ForegroundColor DarkGray
Write-Host "a quella pagina, i referti restano tutti in coda. E' voluto, ma spiega una coda" -ForegroundColor DarkGray
Write-Host "che sembra non smaltirsi." -ForegroundColor DarkGray
Write-Host ""
