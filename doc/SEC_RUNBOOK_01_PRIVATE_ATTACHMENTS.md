# SEC-RUNBOOK-01 — Deploy allegati privati scadenze asset

Runbook operativo per mettere in produzione la remediation degli allegati delle scadenze amministrative asset salvati su storage privato (`ASSETS_PRIVATE_ROOT`) e serviti tramite download autenticato.

Stato collegato: **SEC-GUARD-02 / SEC-GUARD-02F — COMPLETA, PASS WITH WARNINGS**.

---

## 1. Obiettivo

Garantire che gli allegati caricati per il completamento delle scadenze amministrative asset non siano più esposti tramite `/media/` o URL pubblici, ma siano:

- salvati in una directory privata fuori dalla root pubblica;
- scaricabili solo tramite view autenticata/autorizzata;
- migrati in modo controllato dai percorsi legacy;
- verificabili prima e dopo il deploy;
- recuperabili con una procedura di rollback manuale.

---

## 2. Componenti coinvolti

Percorsi applicativi previsti dalla remediation:

- `django_app/assets/storage.py`
- `django_app/assets/views.py`
- `django_app/assets/urls.py`
- `django_app/assets/models.py`
- `django_app/assets/management/commands/migrate_admin_deadline_attachments_private.py`
- `django_app/assets/migrations/0060_private_admin_deadline_attachment_storage.py`
- `django_app/config/settings/base.py`
- `django_app/.env.example`

Comando operativo principale:

```powershell
python django_app/manage.py migrate_admin_deadline_attachments_private --apply --delete-source --settings=config.settings.prod
```

---

## 3. Prerequisiti ambiente

### 3.1 Variabili richieste

In produzione deve essere configurata una directory privata:

```env
ASSETS_PRIVATE_ROOT=D:\Novicrom\PortalePrivate\assets
```

Il percorso deve essere:

- fuori da `MEDIA_ROOT`;
- fuori dalla directory statica servita da IIS;
- persistente tra release/deploy;
- incluso nei backup applicativi;
- leggibile/scrivibile dall'identità Windows usata da Waitress/IIS.

### 3.2 Permessi NTFS consigliati

Esempio indicativo per Windows Server:

```powershell
$PrivateRoot = "D:\Novicrom\PortalePrivate\assets"
New-Item -ItemType Directory -Force -Path $PrivateRoot

# Esempio: sostituire con l'identità reale del pool/app/service account.
icacls $PrivateRoot /inheritance:r
icacls $PrivateRoot /grant "Administrators:(OI)(CI)(F)"
icacls $PrivateRoot /grant "NOVICROM\svc-portale:(OI)(CI)(M)"
icacls $PrivateRoot /remove "Users" "Everyone" 2>$null
```

Verificare sempre l'identità reale del processo applicativo prima di applicare i comandi.

---

## 4. Sequenza deploy raccomandata

### 4.1 Prima del deploy

1. Eseguire backup DB.
2. Eseguire backup della cartella `media` corrente.
3. Creare/verificare `ASSETS_PRIVATE_ROOT`.
4. Verificare che il nuovo valore sia presente nel file `.env` dell'ambiente target.
5. Verificare che la release non contenga DB, media, log o segreti.

### 4.2 Deploy codice e migrazioni

```powershell
python django_app/manage.py check --settings=config.settings.prod
python django_app/manage.py makemigrations --check --dry-run --settings=config.settings.prod
python django_app/manage.py migrate --settings=config.settings.prod
python django_app/manage.py validate_deployment --settings=config.settings.prod
```

Se `validate_deployment` segnala warning non bloccanti già noti, registrarli nel verbale di deploy. Qualsiasi `FAIL` va trattato come blocco.

### 4.3 Dry-run migrazione allegati legacy

```powershell
python django_app/manage.py migrate_admin_deadline_attachments_private --dry-run --settings=config.settings.prod
```

Controllare l'output per:

- numero record candidati;
- file sorgente mancanti;
- collisioni di nome;
- record già migrati;
- errori path/sicurezza;
- totale file che verrebbero copiati.

Non procedere con `--apply` se il dry-run mostra errori non compresi.

### 4.4 Apply senza cancellazione sorgente

Primo passaggio consigliato:

```powershell
python django_app/manage.py migrate_admin_deadline_attachments_private --apply --settings=config.settings.prod
```

Verifiche immediate:

```powershell
Get-ChildItem -Recurse $env:ASSETS_PRIVATE_ROOT
```

Poi aprire dal portale alcuni allegati migrati con utente autorizzato.

### 4.5 Apply con cancellazione sorgente legacy

Solo dopo verifica positiva e backup disponibile:

```powershell
python django_app/manage.py migrate_admin_deadline_attachments_private --apply --delete-source --settings=config.settings.prod
```

Il comando deve cancellare il sorgente legacy solo dopo copia riuscita e aggiornamento record.

---

## 5. Test post-deploy obbligatori

### 5.1 Download autorizzato

1. Accedere con un utente autorizzato alla vista asset/scadenza.
2. Aprire un allegato già migrato.
3. Risultato atteso: HTTP 200 e contenuto corretto.

### 5.2 Download non autorizzato

1. Accedere con un utente privo del permesso operativo sul record.
2. Tentare il download dell'allegato.
3. Risultato atteso: HTTP 403 o 404 secondo pattern applicativo esistente, mai HTTP 200.

### 5.3 URL pubblico `/media/`

1. Verificare che il record non esponga `.file.url` pubblico.
2. Tentare accesso diretto a un eventuale vecchio percorso `/media/...`.
3. Risultato atteso: file assente, non raggiungibile o comunque non usato dall'applicazione.

### 5.4 Nuovo upload

1. Completare una scadenza amministrativa asset caricando un nuovo allegato.
2. Verificare che il file venga creato sotto `ASSETS_PRIVATE_ROOT`.
3. Verificare download autorizzato.
4. Verificare assenza di URL pubblico.

### 5.5 Path traversal

Tentativi con nomi file anomali non devono uscire dalla directory privata:

- `../file.pdf`
- `..\file.pdf`
- `C:\temp\file.pdf`
- `/etc/passwd`
- nomi con slash misti o caratteri non attesi.

Risultato atteso: il file viene normalizzato/bloccato e non viene mai scritto o letto fuori da `ASSETS_PRIVATE_ROOT`.

---

## 6. Validazione regression consigliata

Prima di chiudere il deploy, eseguire almeno:

```powershell
python django_app/manage.py check --settings=config.settings.prod
python django_app/manage.py validate_deployment --settings=config.settings.prod
```

In ambiente test/staging, la validazione completa di SEC-GUARD-02F era:

```powershell
python django_app/manage.py check --settings=config.settings.test
python django_app/manage.py makemigrations --check --dry-run --settings=config.settings.test
python django_app/manage.py test assets.tests --settings=config.settings.test --verbosity 2
python django_app/manage.py test automazioni.tests --settings=config.settings.test --verbosity 2
python django_app/manage.py validate_deployment --settings=config.settings.test
```

Esito atteso registrato in SEC-GUARD-02F:

- `assets.tests`: 157 test OK;
- `automazioni.tests`: 310 test OK;
- `validate_deployment`: OK bloccante, `OK=19`, `WARN=3`, `FAIL=0`.

---

## 7. Warning noti e gestione

| Warning | Interpretazione | Azione |
|---|---|---|
| `assets.0060_private_admin_deadline_attachment_storage` non applicata | Atteso prima di `migrate` sull'ambiente target | Eseguire `migrate` prima della migrazione file |
| `LDAP_GROUP_ALLOWLIST` mancante | Warning di configurazione AD/LDAP | Valutare allowlist esplicita o documentare eccezione |
| controllo repo pubblico non applicabile | Check non eseguibile in ambiente senza web/repo privato | Documentare come non applicabile |
| DB access durante app initialization | Warning preesistente | Tracciare come debito tecnico separato |

---

## 8. Rollback manuale

Scenario: dopo il deploy gli allegati non si aprono o la configurazione private root è errata.

1. Non rilanciare `--delete-source`.
2. Ripristinare il backup DB se la migrazione dati ha già aggiornato i path e si vuole tornare allo stato precedente.
3. Ripristinare la cartella `media` dal backup se necessaria.
4. Correggere `ASSETS_PRIVATE_ROOT` e permessi NTFS.
5. Rieseguire dry-run.
6. Rieseguire apply senza delete-source.

Se `--delete-source` è già stato eseguito, il rollback richiede backup della cartella `media` o copia inversa dai file presenti in `ASSETS_PRIVATE_ROOT`, più ripristino coerente dei riferimenti DB.

---

## 9. Troubleshooting

### Allegato non trovato

Controllare:

- record DB dell'allegato;
- path relativo salvato;
- presenza fisica sotto `ASSETS_PRIVATE_ROOT`;
- permessi NTFS;
- log applicativo;
- output del comando migrazione.

### Allegato dà 403/404 per utente corretto

Controllare:

- autenticazione utente;
- relazione tra utente e asset/scadenza;
- permessi applicativi richiesti dalla view;
- eventuali filtri reparto/ruolo applicati al modulo assets.

### Nuovo upload non salva file

Controllare:

- `ASSETS_PRIVATE_ROOT` valorizzato;
- permessi scrittura service account;
- limite dimensione file;
- estensione/MIME consentiti;
- errori form nella risposta HTML.

### File duplicati o collisioni

Il comando deve essere idempotente. In caso di collisione:

- non sovrascrivere file diversi senza controllo;
- confrontare contenuto/hash quando possibile;
- registrare warning operativo;
- rilanciare dry-run dopo eventuale correzione manuale.

---

## 10. Checklist chiusura deploy

- [ ] Backup DB eseguito.
- [ ] Backup `media` eseguito.
- [ ] `ASSETS_PRIVATE_ROOT` creato e persistente.
- [ ] Permessi NTFS verificati.
- [ ] `migrate` eseguito.
- [ ] `validate_deployment` senza FAIL.
- [ ] Dry-run migrazione allegati controllato.
- [ ] Apply migrazione eseguito.
- [ ] Delete-source eseguito solo dopo verifica.
- [ ] Download autorizzato testato.
- [ ] Download non autorizzato testato.
- [ ] Nuovo upload testato.
- [ ] Vecchi URL `/media/` non usati.
- [ ] Warning residui documentati.
