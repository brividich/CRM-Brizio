<#
.SYNOPSIS
    Script GUIDATO per gli import storici Sicurezza su PROD.
    Menu interattivo: backup DB + i 3 import (SMS, Diario Preposto, Rilevazioni).

.DESCRIZIONE
    Esegue automaticamente solo le operazioni SICURE (check migrazioni, catalogo
    reparti, DRY-RUN). Prima di OGNI scrittura reale chiede di digitare CONFERMA.
    Nessuna azione distruttiva senza conferma esplicita.

    Prerequisiti nella cartella -ImportDir (default C:\PortaleNovicrom\prod\_import):
      - "Registro SMS_Suggestion Corner.csv"   (per SMS)  + reparto_map.json
      - diario_preposto.csv                     (per Diario Preposto)
      - rilevazioni.csv                         (per Rilevazioni)

.ESEMPIO
    powershell -ExecutionPolicy Bypass -File .\guida_import_sicurezza.ps1
#>
[CmdletBinding()]
param(
    [string]$ProdRoot  = "C:\PortaleNovicrom\prod",
    [string]$ImportDir = "C:\PortaleNovicrom\prod\_import",
    [string]$Settings  = "config.settings.prod"
)

$ErrorActionPreference = "Stop"
$py = Join-Path $ProdRoot "venv\Scripts\python.exe"
$mg = Join-Path $ProdRoot "current\django_app\manage.py"

function Head($t) { Write-Host "`n============ $t ============" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  $t" -ForegroundColor Yellow }
function Mg { param([Parameter(ValueFromRemainingArguments=$true)]$a); & $py $mg @a "--settings=$Settings" }
function ConfirmWrite($msg) {
    Write-Host "`n>>> $msg" -ForegroundColor Yellow
    return (Read-Host "    Digita CONFERMA per procedere (altro = annulla)") -eq "CONFERMA"
}
function NeedFile($p) {
    if (-not (Test-Path $p)) { Warn "MANCA il file: $p"; return $false }
    return $true
}

# --- Sanity iniziale ---
foreach ($p in @($py, $mg)) { if (-not (Test-Path $p)) { throw "Percorso non trovato: $p" } }
New-Item -ItemType Directory -Force $ImportDir | Out-Null

function Step-Migrazioni {
    Head "Verifica migrazioni (devono essere tutte [X])"
    foreach ($m in @("suggestion_corner","diario_preposto","rilevazione_incidenti")) {
        Write-Host "-- $m" -ForegroundColor Gray
        Mg showmigrations $m
    }
}

function Step-Backup {
    Head "Backup del database (PROD)"
    $info = Mg shell -c "from django.conf import settings as s; d=s.DATABASES['default']; print('DBNAME=' + str(d['NAME'])); print('DBHOST=' + str(d.get('HOST') or 'localhost'))"
    $db  = (($info | Select-String '^DBNAME=' | Select-Object -First 1).Line -replace '^DBNAME=','').Trim()
    $srv = (($info | Select-String '^DBHOST=' | Select-Object -First 1).Line -replace '^DBHOST=','').Trim()
    if (-not $db) { Warn "Nome DB non rilevato (settings). Esegui il backup manualmente."; return }
    Write-Host "  DB   : $db"
    Write-Host "  Host : $srv"
    if (-not (Get-Command sqlcmd -ErrorAction SilentlyContinue)) {
        Warn "sqlcmd non trovato: esegui il backup con SSMS/strumento del DBA e torna al menu."
        return
    }
    $backupDir = Join-Path $ProdRoot "_backup"
    New-Item -ItemType Directory -Force $backupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $bak = Join-Path $backupDir "${db}_$stamp.bak"
    if (ConfirmWrite "Eseguo BACKUP DATABASE [$db] -> $bak") {
        sqlcmd -S $srv -Q "BACKUP DATABASE [$db] TO DISK='$bak' WITH INIT, STATS=5"
        if ($LASTEXITCODE -eq 0) { Ok "Backup completato: $bak" } else { Warn "Backup FALLITO (exit $LASTEXITCODE) — verifica permessi/DBA." }
    } else { Warn "Backup annullato." }
}

function Step-SMS {
    Head "Import #1 — Suggestion Corner (SMS)"
    $csv = Join-Path $ImportDir "Registro SMS_Suggestion Corner.csv"
    $json = Join-Path $ImportDir "sms_storico.json"
    $map  = Join-Path $ImportDir "reparto_map.json"

    # (opz) rigenera il JSON risolvendo i nomi sull'anagrafica di PROD
    if (Test-Path $csv) {
        if (ConfirmWrite "Rigenero sms_storico.json dal CSV (risolve i nomi su anagrafica PROD)?") {
            Mg converti_sms_storico --file $csv --out $json
        }
    }
    if (-not (NeedFile $json)) { return }
    if (-not (Test-Path $map)) { Warn "reparto_map.json assente: creo un template minimo."; '{ "Altro": "", "Generico": "" }' | Set-Content -Encoding UTF8 $map }

    Head "Catalogo Reparto (PROD) — usa questi nomi ESATTI nella mappa"
    Mg shell -c "from anagrafica.models import Reparto; [print(' -', repr(r.nome)) for r in Reparto.objects.order_by('nome')]"

    Head "DRY-RUN SMS (nessuna scrittura)"
    Mg import_suggestion_corner_legacy --file $json --reparto-map $map
    Warn "Se sopra compare 'Reparti non trovati': apri $map, aggiungi le righe mancanti e rilancia questa voce di menu."

    if (ConfirmWrite "APPLY import SMS su PROD (scrittura reale)") {
        Mg import_suggestion_corner_legacy --file $json --reparto-map $map --apply
        Mg shell -c "from suggestion_corner.models import SuggestionCorner as S; print('SMS importati:', S.objects.filter(da_portale=False).count())"
    }
}

function Step-Diario {
    Head "Import #2 — Diario Preposto"
    $csv = Join-Path $ImportDir "diario_preposto.csv"
    if (-not (NeedFile $csv)) { return }
    $user = Read-Host "  Username Django da attribuire come autore (creato_da), invio per lasciare vuoto"
    $extra = @(); if ($user) { $extra = @("--created-by", $user) }

    Head "DRY-RUN Diario (nessuna scrittura)"
    Mg import_preposto_csv $csv --dry-run @extra

    if (ConfirmWrite "IMPORT reale Diario Preposto su PROD") {
        Mg import_preposto_csv $csv @extra
        Mg shell -c "from diario_preposto.models import SegnalazionePreposto as S; print('Diario:', S.objects.count())"
    }
}

function Step-Rilevazioni {
    Head "Import #3 — Segnalazioni Sicurezza (rilevazioni)"
    Warn "ATTENZIONE: questo comando NON ha dry-run e scrive subito. Usa --skip-existing per non duplicare."
    $csv = Join-Path $ImportDir "rilevazioni.csv"
    if (-not (NeedFile $csv)) { return }

    if (ConfirmWrite "IMPORT rilevazioni su PROD con --skip-existing") {
        Mg importa_rilevazioni_csv $csv --skip-existing
        Mg shell -c "import collections; from rilevazione_incidenti.models import RilevazioneIncidente as R; print('Rilevazioni:', R.objects.count()); print(collections.Counter(R.objects.values_list('tipo_evento', flat=True)))"
    }
}

function Step-Verifica {
    Head "Verifica conteggi (tutti i moduli)"
    Mg shell -c "from suggestion_corner.models import SuggestionCorner as A; from diario_preposto.models import SegnalazionePreposto as B; from rilevazione_incidenti.models import RilevazioneIncidente as C; print('SMS importati:', A.objects.filter(da_portale=False).count()); print('Diario:', B.objects.count()); print('Rilevazioni:', C.objects.count())"
}

# --- Menu ---
while ($true) {
    Write-Host "`n================ GUIDA IMPORT SICUREZZA (PROD) ================" -ForegroundColor Cyan
    Write-Host " ProdRoot : $ProdRoot"
    Write-Host " ImportDir: $ImportDir"
    Write-Host " ------------------------------------------------------------"
    Write-Host "  0) Verifica migrazioni"
    Write-Host "  1) Backup database (FALLO PRIMA DEGLI IMPORT)"
    Write-Host "  2) Import #1  Suggestion Corner (SMS)"
    Write-Host "  3) Import #2  Diario Preposto"
    Write-Host "  4) Import #3  Segnalazioni Sicurezza (rilevazioni)"
    Write-Host "  5) Verifica conteggi finali"
    Write-Host "  q) Esci"
    switch ((Read-Host "Scelta").Trim().ToLower()) {
        "0" { Step-Migrazioni }
        "1" { Step-Backup }
        "2" { Step-SMS }
        "3" { Step-Diario }
        "4" { Step-Rilevazioni }
        "5" { Step-Verifica }
        "q" { break }
        default { Warn "Scelta non valida." }
    }
}
Write-Host "`nUscita. Ricorda: cancella i file dati da $ImportDir a fine import (contengono nomi reali)." -ForegroundColor Cyan
