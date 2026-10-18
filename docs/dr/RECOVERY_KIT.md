# Recovery Kit

Senza il Recovery Kit **i documenti privati non si aprono più**: referti, documenti HR, specifiche, timbri e allegati sono cifrati con `DOCUMENT_ENCRYPTION_KEY`. Quella chiave sta nel `.env` e, per scelta (audit M10), non è dentro i backup dei dati.

Il kit è un file `.hubkit` cifrato che contiene:

- il `.env` completo;
- il certificato del binding HTTPS (`.pfx`), con una password casuale che si trova solo dentro il kit.

## Come è fatto

| Elemento | Valore |
|---|---|
| Chiave | scrypt (n = 2^17, r = 8, p = 1) dalla **passphrase** |
| Cifratura | AES-256-GCM |
| Intestazione | versione, salt, nonce, data, ambiente, macchina, impronte SHA-256 di `DOCUMENT_ENCRYPTION_KEY`, `SECRET_KEY` e del `.env` (mai i valori) |
| Integrità | l'intestazione è dato autenticato: se si modifica un byte, il kit non si apre più |
| Passphrase | almeno **5 parole** e 20 caratteri; si digita a mano, mai sulla riga di comando |

Codice: `django_app/core/backup_engine/recovery_kit.py`. Usa solo Python e `cryptography`, quindi su una macchina nuova si esegue anche **senza Django**.

## Comandi

```powershell
# esportazione (sul server, PowerShell nella cartella django_app della release attiva)
python manage.py hub_recovery_kit export --out \\<share-segreti>\hub\prod-20261017.hubkit --pfx-thumbprint <thumbprint>
# verifica: decifra in memoria e confronta con le chiavi in uso, non scrive nulla
python manage.py hub_recovery_kit verify \\<share-segreti>\hub\prod-20261017.hubkit
# import su un ambiente (di solito lo fa restore-host.ps1)
python manage.py hub_recovery_kit import <file.hubkit> --to prod --force
# su una macchina senza portale configurato
python django_app\core\backup_engine\recovery_kit.py verify <file.hubkit>
```

`export`:

- rifiuta di sovrascrivere un kit esistente;
- dopo averlo scritto, lo rilegge e controlla che si apra;
- aggiorna `<LOG_DIR>\recovery-kit.json`, che contiene data e impronte, mai valori.

Il monitoraggio confronta queste impronte con l'ambiente attuale. Quando `.env` o chiavi cambiano dopo l'esportazione, il riquadro «Recovery Kit» della pagina Backup e ripristino diventa giallo («Da rigenerare»).

## Dove si custodisce (decisione del 16/10/2026)

| # | Collocazione | Cosa |
|---|---|---|
| 1 | Share dei segreti (ACL ristrette, diversa dalla share dei backup) | il file `.hubkit` |
| 2 | Vaultwarden | il file `.hubkit` come allegato della voce «NOVICROM HUB – Recovery Kit» |
| 3 | Synology C2, cifrato lato client | il file `.hubkit`, insieme agli archivi |
| 4 | Busta sigillata in Direzione (cassaforte) | **la passphrase**, scritta a mano, con la data del kit |

La passphrase la conoscono Brizio e la Direzione, e non sta mai nello stesso posto del file.

## Quando rigenerarlo

- a ogni modifica del `.env` (nuova password, nuovo host DB, nuova chiave Graph…);
- dopo una rotazione di `DOCUMENT_ENCRYPTION_KEY` (`rotate_document_encryption_key`);
- dopo il rinnovo del certificato HTTPS;
- in ogni caso quando la pagina «Backup e ripristino» mostra «Da rigenerare».

Dopo l'esportazione:

1. verificare il kit con `hub_recovery_kit verify`;
2. sostituirlo nelle collocazioni 1–3;
3. se la passphrase è cambiata, aggiornare la busta.

## Prova periodica

Ogni trimestre, durante il ripristino completo su una VM isolata (vedi il runbook), si usa il kit custodito: non una copia appena esportata. È il solo modo di scoprire in tempo che la passphrase nella busta non è più quella giusta.
