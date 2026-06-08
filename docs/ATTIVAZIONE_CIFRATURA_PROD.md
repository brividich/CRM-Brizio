# Attivazione cifratura at rest in produzione

**Da eseguire una sola volta** dopo il deploy del branch `feat/acl-chiusura-migrazione-fase1`.

---

## Prerequisiti

- Deploy già effettuato e app che risponde correttamente
- Accesso RDP/console a `pclogsys`
- Accesso alla shell Python del venv prod

---

## Passo 1 — Generare la chiave di cifratura

Apri una PowerShell su `pclogsys` e attiva il venv prod:

```powershell
cd C:\PortaleNovicrom\prod
.\venv\Scripts\Activate.ps1
```

Genera la chiave (AES-256 Fernet, base64 url-safe):

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copia l'output — è una stringa di ~44 caratteri, es.:
`t3k9XwQ2...` (44 caratteri base64)

> **IMPORTANTE:** salvala subito in un posto sicuro (password manager aziendale, KeePass, ecc.).
> Se la perdi, i file cifrati diventano illeggibili per sempre.

---

## Passo 2 — Aggiungere la chiave al .env persistente

Il file da modificare è **`C:\PortaleNovicrom\prod\config\.env`**
(quello persistente — NON `current\django_app\.env` che viene riscritto dal deploy).

Apri con Notepad o VS Code e aggiungi in fondo:

```
DOCUMENT_ENCRYPTION_KEY=<incolla qui la chiave del passo 1>
```

Salva il file.

---

## Passo 3 — Propagare la configurazione all'istanza attiva

Copia il .env persistente nell'istanza attiva:

```powershell
Copy-Item C:\PortaleNovicrom\prod\config\.env `
          C:\PortaleNovicrom\prod\current\django_app\.env -Force
```

Poi riavvia l'app pool IIS per ricaricare la configurazione:

```powershell
& "$env:windir\system32\inetsrv\appcmd.exe" recycle apppool /apppool.name:"NovicromHub"
```

---

## Passo 4 — Verifica che la chiave sia caricata

```powershell
cd C:\PortaleNovicrom\prod\current\django_app
python manage.py shell --settings=config.settings.prod -c "
from django.conf import settings
key = getattr(settings, 'DOCUMENT_ENCRYPTION_KEY', '')
print('OK - chiave caricata:', bool(key), '- lunghezza:', len(key))
"
```

Deve stampare `OK - chiave caricata: True - lunghezza: 44`.

---

## Passo 5 — Dry-run: vedere quanti file verranno cifrati

```powershell
python manage.py encrypt_existing_documents --settings=config.settings.prod
```

L'output mostra quanti file esistenti (non ancora cifrati) verranno processati.
I nuovi file caricati da questo momento in poi vengono cifrati automaticamente.

---

## Passo 6 — Cifrare i file esistenti

```powershell
python manage.py encrypt_existing_documents --apply --settings=config.settings.prod
```

L'output elenca ogni file cifrato e riepiloga i contatori finali:
`scansionati: N, cifrati: N, già cifrati: 0, errori: 0`

Se ci sono errori: il file specifico viene loggato ma gli altri vengono processati ugualmente.
Riesegui il comando — i file già cifrati vengono saltati automaticamente.

---

## Passo 7 — Smoke test funzionale

Verifica che il download dei file funzioni ancora:

- Apri un documento dipendente da Anagrafica → Documenti
- Scarica un allegato ticket
- Visualizza un'immagine timbro da `/timbri/`
- Verifica un allegato Diario Preposto

Se qualcosa non si apre: controlla i log Waitress/IIS e verifica che `DOCUMENT_ENCRYPTION_KEY` sia identica nel `.env` persistente e nell'istanza attiva.

---

## Note operative

| Cosa | Dove |
|---|---|
| Chiave da modificare in futuro | Solo `C:\PortaleNovicrom\prod\config\.env` |
| La chiave viene sovrascritta dal deploy? | No — il deploy legge da `config\.env` e lo riscrive in `current\django_app\.env` |
| Chiave persa = file illeggibili? | Sì — nessun recovery possibile senza la chiave |
| Backup del .env persistente | Incluso nel backup del server (stessa priorità dei dati) |
| File caricati prima di questo passo | Leggibili as-is (non cifrati), il mixin li serve trasparentemente |
| File caricati dopo questo passo | Cifrati automaticamente al salvataggio |
| Cifrare storage specifico | `--storage anagrafica` / `timbri` / `tickets` / `diario_preposto` / `assets` |
