# CLAUDE.md - NOVICROM HUB

Versione app corrente: **1.6.8** (2026-10-16)

Portale Django interno (SSR + HTMX) per flussi di lavoro, operatività, sicurezza/compliance, automazioni e permessi granulari. Marchio canonico **NOVICROM HUB**; «Portale Novicrom» resta solo in percorsi di deploy e riferimenti storici.

Lavora in modo conservativo: preserva confini di sicurezza, tracciabilità, compatibilità legacy e affidabilità; preferisci i pattern Django/SSR/HTMX esistenti a nuove astrazioni. Il contesto lungo è in `docs/ai/` ([indice](docs/ai/00_INDEX.md)): apri solo il file che serve al compito, mai tutta la cartella.

## Sicurezza

- Mai segreti, dati reali di persone o clienti, contenuto di caselle, log di produzione, credenziali, certificati o export di dati personali in prompt, documenti, commit, esempi, screenshot o fixture: solo dati sintetici.
- Materiale sensibile a runtime: `.env` (anche `config/.env` del deploy), credenziali Graph/LDAP/SMTP, certificati, dump di database, media con dati personali, log di produzione.
- ACL v2 è il livello di autorizzazione primario; l'ACL legacy è solo il fallback dove manca un binding canonico. La visibilità nel menu non protegge niente: decide il server.
- Superfici pubbliche a token strette: solo `/automazioni/approvazione/*` e `/approval-actions/*`; via Entra Application Proxy si pubblica solo `/approval-actions/*`. Ogni nuova esenzione da login/ACL va in `MIDDLEWARE_EXEMPT_PREFIXES` (`config/settings/base.py`) **e** in `PUBLIC_VIEWS` di `core/test_security_audit_fase3.py`.
- Endpoint API/AJAX protetti: JSON `401/403`, mai redirect HTML.
- Security Center AI (`diario_preposto`, `rilevazione_incidenti`, `procedure_refresh`, `dpi`, `rentri`): preserva audit trail, fonti di verità, privacy e tracciabilità visibile all'utente.

Dettagli: [docs/ai/05_SECURITY_BOUNDARIES.md](docs/ai/05_SECURITY_BOUNDARIES.md).

## Stack

- Waitress dietro IIS (HttpPlatformHandler). SQL Server in test/prod (`mssql-django` + `pyodbc`); SQLite solo per sviluppo Django-only. Cache su database in prod, in memoria in dev.
- Login a cascata: `AxesStandaloneBackend` → `SQLServerLegacyBackend` → `LDAPBackend` → `ModelBackend`.
- Template server-side, CSS proprio, HTMX; nessun framework JS. Integrazioni: Graph/SharePoint/Outlook, LDAP/AD, SMTP, Entra Application Proxy.
- I settings leggono `.env` all'avvio con `_load_dotenv(...)`.

Architettura: [02_ARCHITECTURE.md](docs/ai/02_ARCHITECTURE.md). Moduli: [03_BACKEND_MODULES.md](docs/ai/03_BACKEND_MODULES.md). Setup di sviluppo: [06_TESTING_AND_QUALITY_GATES.md](docs/ai/06_TESTING_AND_QUALITY_GATES.md).

## Test e controlli

```powershell
python django_app\manage.py test django_app.<app> --keepdb --settings=config.settings.test
python django_app\manage.py check --settings=config.settings.test
python django_app\manage.py secret_hygiene_check
python django_app\manage.py validate_deployment --format json --settings=config.settings.test
python django_app\manage.py bootstrap_acl_v2 --dry-run
python django_app\manage.py acl_coverage_report --max-missing 222
```

- **Mai la suite completa** (`manage.py test` senza app) se non è richiesta: solo l'app toccata, con `--keepdb`. In background `--verbosity 0`; mai `runserver` insieme alla suite completa.
- Per modifiche solo di documentazione non servono test.
- Prima del pacchetto: release guard `tools/release_guard.ps1`.

## Sessioni parallele e git

Più sessioni lavorano sul repo in contemporanea: branch e file non committati appartengono alla cartella, non alla sessione.

- Il checkout condiviso `C:\Dev\Portale Novicrom` è **sola lettura**: lì mai `git checkout`/`git switch`, mai `git add -A`/`git commit -a`.
- Apri con `git status`; lavora in un worktree dedicato: `git worktree add C:\Dev\pn-<tema> -B feature/<area>-<tema> origin/main`. Committa e pusha da lì, poi `git worktree remove` (percorso troppo lungo: `cmd /c rmdir /s /q <path>` + `git worktree prune`).
- Ogni sessione chiude con un commit: nessun lavoro resta fuori da git.
- Merge **sempre feature → main → release/prod** (regola di Brizio, 02/10/2026): mai una feature direttamente in release.
- Committare non è deployare: in produzione va solo ciò che è in `release/prod`, da cui `package-release.ps1` crea il pacchetto. Il pacchetto nasce solo da un commit; `-FromWorkingTree -Force` è un'emergenza.

Motivazioni e dettagli: [06_TESTING_AND_QUALITY_GATES.md](docs/ai/06_TESTING_AND_QUALITY_GATES.md#sessioni-parallele-e-disciplina-git).

## Lavoro in background

Appena avvii un processo, un subagente o un lavoro in background (`run_in_background`, `Workflow`, polling esterno), arma un `ScheduleWakeup` di guardia (`delaySeconds: 270`, `reason` esplicita). Riarmalo a ogni risveglio finché il lavoro è in corso e chiudilo (`stop: true`) quando finisce: le attese senza guardia hanno bloccato la sessione.

## A ogni modifica, in automatico

- `CHANGELOG.md`, sezione `[Unreleased]`: file toccati e descrizione.
- Cambiano funzioni visibili, URL, setup o dipendenze: scheda `docs/moduli/<app>.md`. La tabella moduli del `README.md` solo se cambiano riassunto o URL, con righe brevi.
- Cambia una funzione visibile, nello stesso commit:
  - guida in-app del modulo (pulsante «? Guida», es. `anomalie/guida.py`, `timbri/guida.py`, `security/guide/`) con le etichette e le soglie reali del codice; link «? Guida» sulle pagine nuove; se il modulo non ha una guida, va creata;
  - Centro guide `core/guide_moduli/contenuti/<modulo>.py` (parti `uso`, `admin`, `problemi`; un modulo nuovo va registrato in `core/guide_moduli/__init__.py`);
  - per tabelle, app o integrazioni nuove: `hub_tools/schema_db.py` (`APP_INFO`, `CONNESSIONI_ESTERNE`).
- Cambia il comportamento per l'utente: checklist di bump versione in [06_TESTING_AND_QUALITY_GATES.md](docs/ai/06_TESTING_AND_QUALITY_GATES.md).
- Cambia `deployment/setup_wizard.py`: rigenera `deployment/dist/SetupWizard.exe` rispettando le esclusioni del bundle.
- Questo file resta corto: qui solo regole operative, i dettagli nel file giusto di `docs/ai/`.
