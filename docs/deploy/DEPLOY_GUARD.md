# DEPLOY GUARD - NOVICROM HUB

Versione script: **1.0.0**
Compatibilita: Windows PowerShell 5.1+

## Scopo

`scripts/deploy_guard.ps1` orchestra in modo sicuro il deploy in TEST/PROD eseguendo,
in ordine fail-fast:

1. risoluzione del path reale del sito IIS (o `-ProjectRoot` esplicito);
2. parsing in sola lettura di `web.config` per applicare le `environmentVariable`
   IIS al processo PowerShell corrente;
3. probe configurazione Django (`deploy_env_probe.ps1`);
4. `manage.py check`;
5. `manage.py migrate` (skippabile con `-NoMigrate`);
6. `manage.py validate_deployment` con parsing `Summary: OK=N WARN=N FAIL=N`;
7. `manage.py migrate_admin_deadline_attachments_private` in modalita preview;
8. eventuale `--apply` solo con `-ApplyPrivateAttachments`;
9. eventuale `--delete-source` solo con DOPPIO flag `-DeleteSourcePrivateAttachments` + `-ConfirmDeleteSource`;
10. riavvio App Pool (solo con `-RestartAppPool`, solo se tutti gli step OK);
11. smoke HTTP `/healthz`, `/version`, `/login/` (solo con `-SmokeUrl`). In `prod`
    `/version` e' obbligatorio (404, body vuoto o unreachable -> exit 2). In `test`
    resta WARN per retrocompatibilita.

Output: report timestampato in `deploy_reports/deploy_guard_<env>_<yyyyMMdd_HHmmss>.log`.

## Esempio deploy TEST

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_guard.ps1 `
    -Environment test `
    -IisSiteName "PortaleNovicrom-Test" `
    -IisAppPool "PortaleNovicrom-Test" `
    -RestartAppPool `
    -SmokeUrl "https://test-portale-novicrom.local"
```

## Esempio deploy PROD (senza apply allegati)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_guard.ps1 `
    -Environment prod `
    -IisSiteName "PortaleNovicrom" `
    -IisAppPool "PortaleNovicrom" `
    -RestartAppPool `
    -SmokeUrl "https://portale-novicrom.local" `
    -StrictWarnings
```

## Esempio deploy PROD con apply allegati privati

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_guard.ps1 `
    -Environment prod `
    -IisSiteName "PortaleNovicrom" `
    -IisAppPool "PortaleNovicrom" `
    -ApplyPrivateAttachments `
    -RestartAppPool `
    -SmokeUrl "https://portale-novicrom.local" `
    -StrictWarnings
```

## Esempio deploy con cancellazione sorgenti legacy (raro)

L'operazione di cancellazione delle sorgenti originali degli allegati e disabilitata
per default e richiede DOPPIO flag esplicito (`-DeleteSourcePrivateAttachments` +
`-ConfirmDeleteSource`) insieme a `-ApplyPrivateAttachments`. Usare solo dopo che
una migrazione `--apply` precedente ha gia replicato i file nello storage privato.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_guard.ps1 `
    -Environment prod `
    -IisSiteName "PortaleNovicrom" `
    -IisAppPool "PortaleNovicrom" `
    -ApplyPrivateAttachments `
    -DeleteSourcePrivateAttachments `
    -ConfirmDeleteSource `
    -RestartAppPool `
    -SmokeUrl "https://portale-novicrom.local"
```

## Parametri

| Parametro | Default | Obbligatorio | Descrizione |
|---|---|---|---|
| `Environment` | - | Si | `test` o `prod`. In `prod` validazioni piu severe (DEBUG=True e SECRET_KEY placeholder fanno fallire). |
| `IisSiteName` | - | No | Nome sito IIS. Lo script risolve `ProjectRoot` dal `physicalPath`. |
| `IisAppPool` | - | No | Nome App Pool IIS da riavviare (con `-RestartAppPool`). |
| `ProjectRoot` | - | No | Path del repo (alternativa a `-IisSiteName`). |
| `SettingsModule` | `config.settings.prod` | No | Settings Django da utilizzare per check/migrate/validate. |
| `PythonExe` | `python` | No | Eseguibile Python per i comandi `manage.py`. |
| `ApplyPrivateAttachments` | off | No | Esegue `migrate_admin_deadline_attachments_private --apply`. |
| `DeleteSourcePrivateAttachments` | off | No | Aggiunge `--delete-source`. Richiede `-ConfirmDeleteSource` e `-ApplyPrivateAttachments`. |
| `ConfirmDeleteSource` | off | No | Doppia conferma per la cancellazione sorgenti. |
| `RestartAppPool` | off | No | Riavvia l'app pool IIS al termine degli step Django (solo se tutti OK). |
| `SmokeUrl` | - | No | URL base per smoke HTTP post-deploy (`/healthz`, `/version`, `/login/`). |
| `ReportDir` | `.\deploy_reports` | No | Directory per il report timestampato. |
| `StrictWarnings` | off | No | Tratta i `WARN` di `validate_deployment` come failure. |
| `NoMigrate` | off | No | Salta lo step `manage.py migrate`. |
| `AllowSelfSignedCert` | off | No | Inoltrato a `deploy_smoke.ps1` per certificati self-signed. |

## Exit code

| Codice | Significato |
|---|---|
| 0 | Tutti gli step OK |
| 1 | Step critico fallito (probe, check, migrate, validate, restart, allegati apply) |
| 2 | Step critici OK ma smoke post-deploy fallito |

## Sicurezza e limiti

- Le environment variable di `web.config` valgono per IIS ma non per PowerShell.
  Lo script le carica nel processo corrente per simulare il contesto IIS.
- `web.config` e in **sola lettura**. Lo script non lo modifica mai.
- Le secret (SECRET_KEY, PASSWORD, TOKEN, CLIENT_SECRET, GRAPH_CLIENT_SECRET, API_KEY,
  PRIVATE) **non vengono mai stampate** ne salvate nel report. Solo `<set len=N>` o `<missing>`.
- Lo script non esegue `git pull`, `backup`, `drop` o modifiche al DB oltre i comandi
  Django previsti.
- La cancellazione delle sorgenti legacy degli allegati richiede DOPPIO flag esplicito.
- In prod (`-Environment prod`), DEBUG=True o SECRET_KEY placeholder fanno bloccare il deploy.

## Script ausiliari

### `scripts/deploy_env_probe.ps1`

Riusabile come standalone per verifica rapida senza eseguire nulla di distruttivo.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_env_probe.ps1 `
    -ProjectRoot "." -SettingsModule config.settings.prod
```

### `scripts/deploy_smoke.ps1`

Riusabile come standalone per testare un'istanza gia deployata. Accetta
`-Environment test|prod` (default `test`). In `prod` `/version` e' obbligatorio:
404, body vuoto o errore di rete fa fallire lo smoke (exit 1). In `test` resta
WARN per non bloccare ambienti non ancora aggiornati.

```powershell
# Smoke standalone su istanza test (default)
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_smoke.ps1 `
    -BaseUrl https://test-portale-novicrom.local

# Smoke standalone su prod (/version obbligatorio)
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_smoke.ps1 `
    -BaseUrl https://portale-novicrom.local -Environment prod
```

Quando lo smoke viene invocato da `deploy_guard.ps1`, il parametro `-Environment`
viene propagato automaticamente: deploy in prod => smoke in modalita prod.

## Validazione locale rapida

Comandi che puoi eseguire prima di un deploy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_env_probe.ps1 -ProjectRoot "." -SettingsModule config.settings.prod
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_guard.ps1 -Environment test -ProjectRoot "." -NoMigrate
python .\django_app\manage.py check --settings=config.settings.prod
python .\django_app\manage.py validate_deployment --settings=config.settings.prod
```

## Note tecniche

- Compatibile Windows PowerShell 5.1+ (no `&&`/`||`/ternario/`??`).
- Richiede modulo `WebAdministration` se si usano `-IisSiteName`/`-IisAppPool`/`-RestartAppPool`.
- Su ambienti senza IIS, usare sempre `-ProjectRoot` come fallback.
- I file di report sono in `.\deploy_reports\` (creato se non esiste). Da ignorare in `.gitignore` se non gia presente.
