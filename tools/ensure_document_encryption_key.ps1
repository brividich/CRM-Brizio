<#
.SYNOPSIS
  Garantisce che DOCUMENT_ENCRYPTION_KEY sia impostata nel .env persistente di
  produzione, in modo SICURO e IDEMPOTENTE. Da eseguire SULL'HOST DI PRODUZIONE.

.DESCRIPTION
  Gli storage privati del portale (referti medici, contratti, consegne DPI,
  allegati fornitori/tasks/VRF, firme timbri) cifrano at-rest con AES-256 Fernet
  SOLO se DOCUMENT_ENCRYPTION_KEY e' impostata. Senza chiave, core.encrypted_storage
  e' fail-open (scrive in chiaro). La guardia in config/settings/prod.py blocca
  l'avvio se la chiave manca o non e' una chiave Fernet valida.

  REGOLE DI SICUREZZA APPLICATE DA QUESTO SCRIPT:
    - Se una chiave e' GIA' presente e valorizzata -> NON la tocca (cambiare la
      chiave renderebbe ILLEGGIBILI i file gia' cifrati). Esce senza modifiche.
    - Se assente o vuota -> genera una chiave Fernet valida e la imposta.
    - Fa un BACKUP del .env prima di scrivere.
    - NON stampa mai il valore della chiave (ne' a video ne' in log).

.PARAMETER EnvPath
  Percorso del .env PERSISTENTE di produzione (NON l'attivo usa-e-getta in
  current\django_app\.env). Default: C:\PortaleNovicrom\prod\config\.env

.PARAMETER PythonExe
  Python del venv di produzione (deve avere il pacchetto 'cryptography').
  Default: C:\PortaleNovicrom\prod\venv\Scripts\python.exe

.EXAMPLE
  .\ensure_document_encryption_key.ps1
  .\ensure_document_encryption_key.ps1 -EnvPath 'D:\app\config\.env'
#>
[CmdletBinding()]
param(
    [string]$EnvPath   = 'C:\PortaleNovicrom\prod\config\.env',
    [string]$PythonExe = 'C:\PortaleNovicrom\prod\venv\Scripts\python.exe'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $EnvPath)) {
    Write-Error "File .env non trovato: $EnvPath. Specifica -EnvPath col percorso del .env persistente di produzione."
    exit 1
}
if (-not (Test-Path $PythonExe)) {
    # Fallback: prova 'python' nel PATH
    $resolved = (Get-Command python -ErrorAction SilentlyContinue)
    if ($null -eq $resolved) {
        Write-Error "Python non trovato: $PythonExe. Specifica -PythonExe col python del venv di produzione (deve avere 'cryptography')."
        exit 1
    }
    $PythonExe = $resolved.Source
}

$lines = Get-Content -Path $EnvPath -Encoding UTF8
$keyLineIdx = -1
$hasValue = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*DOCUMENT_ENCRYPTION_KEY\s*=(.*)$') {
        $keyLineIdx = $i
        if ($Matches[1].Trim().Trim('"').Trim("'") -ne '') { $hasValue = $true }
        break
    }
}

if ($hasValue) {
    Write-Host "DOCUMENT_ENCRYPTION_KEY gia' configurata in $EnvPath. Nessuna modifica (cambiarla romperebbe i file gia' cifrati)." -ForegroundColor Green
    exit 0
}

# Genera una chiave Fernet valida (a runtime, mai dal repo).
$newKey = (& $PythonExe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").Trim()
if ([string]::IsNullOrWhiteSpace($newKey)) {
    Write-Error "Generazione chiave fallita (cryptography non disponibile nel venv?)."
    exit 1
}

# Backup del .env prima di scrivere.
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backup = "$EnvPath.bak_$stamp"
Copy-Item -Path $EnvPath -Destination $backup -Force
Write-Host "Backup creato: $backup"

if ($keyLineIdx -ge 0) {
    # Riga presente ma vuota -> sostituisci
    $lines[$keyLineIdx] = "DOCUMENT_ENCRYPTION_KEY=$newKey"
} else {
    # Riga assente -> appendi
    $lines += "DOCUMENT_ENCRYPTION_KEY=$newKey"
}

# Scrivi UTF-8 senza BOM (coerente con i loader .env).
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($EnvPath, $lines, $utf8NoBom)

Write-Host "DOCUMENT_ENCRYPTION_KEY impostata in $EnvPath (valore NON mostrato)." -ForegroundColor Green
Write-Host "Prossimi passi: redeploy/copia del .env nell'attivo e riavvio del processo; poi i comandi di migrazione file privati." -ForegroundColor Yellow
