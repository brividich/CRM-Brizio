# Ambiente TEST dell'HUB (A.8.31 Separazione degli ambienti)

## Stato al 09/11/2026

- **PROD** su NOVISQL: `C:\PortaleNovicrom\prod` (condivisione `\\NOVISQL\PortaleNovicrom\prod`), istanza SQL `NOVISQL\CNHUB`, pool IIS `PortaleNovicrom-PROD`.
- **TEST su NOVISQL: non esiste.** Su NOVISQL ci sono solo `prod`, `shared` e `tools`.
- Il vecchio TEST su PCLOGSYS (`\\PCLOGSYS\PortaleNovicrom\test`) è fermo ad aprile 2026, `APP_VERSION=1.0.0`, senza `BUILD_INFO.json`: va considerato dismesso e non va più usato per collaudi.
- Conseguenza: i rilasci da ottobre 2026 compresa la 1.9.1 sono stati collaudati direttamente in PROD. È lo scostamento principale rilevato nel piano ISO 27001 e va chiuso prima del prossimo rilascio con migrazioni.

## Obiettivo

Un ambiente TEST sullo stesso server di PROD, con lo stesso pacchetto, settings `config.settings.prod` (l'ambiente di deploy «test» usa i settings di produzione: `config.settings.test` è solo il profilo SQLite della suite automatica), database separato e dati sintetici o anonimizzati con autorizzazione scritta.

## Procedura di creazione (account admin su NOVISQL, cartella `deployment\scripts` del pacchetto corrente)

| # | Passo | Comando | Note |
|---|---|---|---|
| 1 | Struttura cartelle e virtualenv | `.\setup-environment.ps1 -Environment test` | Crea `C:\PortaleNovicrom\test\{config,current,releases,logs}` e il venv con i requisiti del pacchetto |
| 2 | Database | SQL Server Management Studio su `NOVISQL\CNHUB`: database `PortaleNovicrom_TEST`, login dedicato con `db_owner` solo su quel database | Mai riusare il login di PROD |
| 3 | Configurazione | copia `prod\config\.env` in `test\config\.env` e cambia: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DJANGO_SECRET_KEY` (nuova), credenziali Graph/SMTP di test o spente, `AI_*` verso il modello di test | Nessuna chiave `APP_VERSION`; ACL del file con `secure-env-acl.ps1 -Environment test` |
| 4 | Sito IIS | `.\configure-iis-site.ps1 -Environment test -Port 8080 -Hostname hubtest.cnovicrom.local` | Pool `PortaleNovicrom-TEST` con identità di servizio dedicata; binding solo sulla rete interna, **non** pubblicato su Entra Application Proxy |
| 5 | Primo deploy | `.\deploy-release.ps1 -Environment test -PackagePath "\\NOVISQL\PortaleNovicrom\shared\packages\<zip>"` poi `.\activate-release.ps1 -Environment test -ReleaseTag <tag>` | Lo smoke test su TEST funziona perché il sito risponde in locale sulla porta 8080 |
| 6 | Dati | seed sintetico (`manage.py seed_acl_uat` e i seed dei moduli, oppure fixture del repository) oppure copia anonimizzata con AUTORIZZAZIONE_COPIA_PROD_TEST_TEMPLATE.md firmata e `ripristina-copia-anonima.ps1` | Data di cancellazione nel modulo |
| 7 | Task pianificati | solo il qcluster di TEST (`install-qcluster-watchdog.ps1 -Environment test`); niente invio mail reali, niente polling delle caselle di produzione | Verificare `EMAIL_BACKEND` e `AUTOMAZIONI_*` nel `.env` |
| 8 | Verifica | login, footer con la versione, `BUILD_INFO.json`, Centrale senza errori | Compilare la prima riga di VERBALE_COLLAUDO_TEMPLATE.md |

## Regole d'uso

- Lo stesso zip va prima su TEST e poi su PROD: `BUILD_INFO.json` identico nei due ambienti è l'evidenza del collaudo.
- TEST non riceve mail, notifiche push o chiamate Graph verso utenti reali: backend mail su file o console, integrazioni spente o puntate a tenant di prova.
- Chi accede a TEST è elencato nel MOD.167 insieme agli accessi a PROD e al repository.
- Il TEST su PCLOGSYS va spento e la cartella archiviata o cancellata dopo la creazione del nuovo ambiente (registrare l'operazione nel registro RFC come cambio standard).
