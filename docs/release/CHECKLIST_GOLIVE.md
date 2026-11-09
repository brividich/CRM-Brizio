# Checklist go-live NOVICROM HUB (A.8.19, A.8.13, A.8.32)

Copia questo file nella cartella della release (OneDrive, `ISO27001_Change_Management_HUB/<RFC>/`) e compila ogni riga con data e ora, esecutore (ruolo) ed esito. Una riga «NO» senza motivazione blocca il passo successivo.

| RFC | Versione | Commit atteso | Pacchetto | Finestra concordata |
|---|---|---|---|---|
| | | | | |

## Prima del deploy

| # | Passo | Comando o riferimento | Data/ora | Esecutore | Esito |
|---|---|---|---|---|---|
| 1 | RFC autorizzata (o cambio urgente registrato) | REGISTRO_RFC.md | | | |
| 2 | Verbale di collaudo su TEST firmato | VERBALE_COLLAUDO_TEMPLATE.md | | | |
| 3 | `release/prod` contiene il commit atteso e nient'altro | `git log --oneline -3 origin/release/prod` | | | |
| 4 | Checkout condiviso allineato a quel commit e `VERSION` giusto | `git -C "C:\Dev\Portale Novicrom" pull --ff-only origin release/prod` | | | |
| 5 | Pacchetto creato dal branch (non da cartella), guard verde | `package-release.ps1` senza `-SourcePath`; log con `[SUCCESS] release guard completato` | | | |
| 6 | `BUILD_INFO.json` dello zip: `source=branch`, commit = atteso, `dirty=false` | `unzip -p <zip> BUILD_INFO.json` | | | |
| 7 | Backup pre-deploy di DB e cartella | `backup-environment.ps1 -Environment prod` o task FULL recente | | | |
| 8 | `config\prod\.env` persistente verificato: nessuna chiave `APP_VERSION`, segreti invariati | account admin su NOVISQL | | | |
| 9 | Utenti avvisati della finestra | mail o avviso in bacheca | | | |

## Deploy

| # | Passo | Comando o riferimento | Data/ora | Esecutore | Esito |
|---|---|---|---|---|---|
| 10 | Deploy della release | `deploy-release.ps1 -Environment prod -PackagePath <zip>` (con `-AllowEnvDrift` solo se le chiavi del `.env` sono cambiate di proposito) oppure SetupWizard | | | |
| 11 | Migrazioni applicate senza errori | log del deploy, `migrate --check` | | | |
| 12 | `collectstatic` eseguito | log del deploy | | | |
| 13 | Attivazione | `activate-release.ps1 -Environment prod -ReleaseTag <tag> -SkipSmokeTest` (PROD non risponde su localhost) | | | |
| 14 | App pool riciclato e qcluster riavviato | log del wizard o `restart-iis-env.ps1` | | | |

## Dopo il deploy

| # | Passo | Comando o riferimento | Data/ora | Esecutore | Esito |
|---|---|---|---|---|---|
| 15 | `current\BUILD_INFO.json` = commit atteso e versione attesa | `\\NOVISQL\PortaleNovicrom\prod\current\BUILD_INFO.json` | | | |
| 16 | Login, dashboard e footer con la versione nuova | browser su https://hub.costruzioninovicrom.it/ | | | |
| 17 | Centrale di comando senza errori recenti; task django-q in esecuzione | Amministrazione > Centrale | | | |
| 18 | Superfici pubbliche invariate (`/approval-actions/*`) | prova con link di approvazione di test | | | |
| 19 | Tag `prod-vX.Y.Z` sul commit attivato, pushato | `git tag -a prod-vX.Y.Z <commit> -m "..." && git push origin prod-vX.Y.Z` | | | |
| 20 | Registro RFC aggiornato a «rilasciata» | REGISTRO_RFC.md | | | |
| 21 | Dopo tre giorni lavorativi: riesame post-rilascio e chiusura RFC | RIESAME_POST_RILASCIO_TEMPLATE.md | | | |

## Rollback

Se un passo da 11 a 18 fallisce senza rimedio immediato: `rollback-release.ps1 -Environment prod` (riporta la junction `current` alla release precedente), ripristino del DB dal backup del passo 7 solo se le migrazioni hanno modificato dati, riavvio di app pool e qcluster, riga «Emergenza» nel registro RFC.
