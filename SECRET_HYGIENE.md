# Secret hygiene

Questo repository non deve contenere credenziali, dump dati o configurazioni runtime reali.

## File da non versionare

- `.env`, `.env.*` esclusi i soli `.env.example`
- `config.ini` reali, file `*.local` e `local_settings.py`
- database locali o dump: `*.db`, `*.sqlite3`, `*.bak`, `database/`
- log, media e allegati runtime: `logs/`, `django_app/logs/`, `media/`, `django_app/media/`, `media_private/`
- chiavi e certificati privati: `*.pem`, `*.key`, `*.pfx`, `*.p12`, `*.jks`, `*.keystore`
- export operativi generati: release zip, pacchetti Power Automate, report ACL/dev locali

## Esempi configurazione

I file `.env.example` devono restare puliti: usare solo `CHANGE_ME`, valori vuoti, domini `example.local` o placeholder come `<GRAPH_TENANT_ID>`.
Non inserire indirizzi email, tenant ID, list ID, host interni o account di servizio reali.

## Controllo release

Prima di pubblicare o aprire una PR eseguire:

```bash
python django_app/manage.py secret_hygiene_check
```

Il comando e integrato nel release guard (`tools/release_guard.ps1`) come
controllo bloccante: un finding HIGH ferma la creazione del pacchetto.

Per includere anche file non versionati ma non ignorati:

```bash
python django_app/manage.py secret_hygiene_check --include-untracked
```
