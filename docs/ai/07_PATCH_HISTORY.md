# Patch History

Patch and release-history maintenance rules moved out of root CLAUDE.md.

Important: Do not read all docs automatically. Open only the files relevant to the current task.

## Current Version Source

- Root VERSION is the single source of truth for the app version.
- CHANGELOG.md is the canonical detailed patch history.
- Root CLAUDE.md should stay concise and only point to this AI documentation layer.

## Aggiornamenti obbligatori dopo ogni modifica

**REGOLA: dopo ogni modifica al codice (nuova funzionalitÃƒÆ’Ã‚Â , bugfix, refactor significativo) aggiornare SEMPRE e AUTOMATICAMENTE questi file, senza aspettare istruzioni esplicite:**

1. **`docs/ai/*.md` + `CLAUDE.md` leggero** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â aggiornare il file AI mirato per dettagli lunghi; aggiornare `CLAUDE.md` solo per regole operative concise
2. **`CHANGELOG.md`** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â aggiungere o aggiornare la voce nella sezione della versione corrente
3. **`README.md`** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â aggiornare se la modifica cambia funzionalitÃƒÆ’Ã‚Â  visibili, URL, setup o dipendenze
4. **Versione** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â se la modifica ÃƒÆ’Ã‚Â¨ rilevante per l'utente finale, applicare la checklist "Bump di versione" qui sotto

Questo aggiornamento ÃƒÆ’Ã‚Â¨ parte integrante di ogni task, non un'attivitÃƒÆ’Ã‚Â  opzionale.

### Governance docs/release

- Brand documentale canonico: `NOVICROM HUB`
- I nomi storici come `Portale Novicrom` possono restare solo come esempio di istanza, percorso o cartella di deploy
- Set canonico da mantenere coerente con `VERSION`: `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs/ai/*.md`, `doc/README.md`, `doc/START_HERE.md`, `doc/TESTING.md`, `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`, `doc/STRUTTURA_ATTUALE_PORTALE.md`, `deployment/README_DEPLOY_IIS_WINDOWS.md`, `tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md`
- Guard operativo: `tools/release_guard.ps1`
- Il release guard esegue anche `secret_hygiene_check` (bloccante), `acl_coverage_report --max-missing 216`, `validate_deployment --format json --settings=config.settings.test` (FAIL bloccanti, WARN ammessi) e `check --settings=config.settings.test`.
- Artifact guard generati e non versionati: `django_app/acl_report_latest.json` e `django_app/deployment_validation_latest.json`.
- Non usare `acl_coverage_report --fail-on-missing` nel guard finche la baseline storica non e azzerata; ogni aumento di `-AclMaxMissing` deve essere una decisione esplicita.
- `deployment/scripts/package-release.ps1` deve eseguire il guard prima di creare lo zip

---

## Bump di versione - checklist obbligatoria

Ad ogni bump di versione (es. `0.7.3 -> 0.7.4`) aggiornare TUTTI questi file, senza eccezioni. Il release guard (`tools/release_guard.ps1`) verifica ognuno di essi e blocca il packaging se uno solo e fuori allineamento.

### File codice (hardcode da aggiornare)

1. `VERSION` (root repo) â€” single source of truth (`X.Y.Z`)
2. `django_app/VERSION` â€” mirror di compatibilita, deve combaciare con root `VERSION`
3. `django_app/config/app_version.py` â€” riga `DEFAULT_APP_VERSION = "X.Y.Z"`
4. `deployment/setup_wizard.py` â€” riga `_DEFAULT_APP_VERSION = "X.Y.Z"`

### File configurazione

1. `django_app/.env.example` â€” `APP_VERSION=X.Y.Z` + tutte le `APP_VERSION_*`
2. `config\test\.env` e `config\prod\.env` â€” `APP_VERSION=X.Y.Z` (source of truth runtime deploy)

### File documentazione (tutti devono mostrare la versione nel frontmatter/header)

1. `CLAUDE.md` header â€” `Versione app corrente: **X.Y.Z** (YYYY-MM-DD)`
2. `CHANGELOG.md` â€” aggiungere sezione `## X.Y.Z - YYYY-MM-DD`
3. `README.md` â€” badge `![Version X.Y.Z](https://img.shields.io/badge/version-X.Y.Z-F97316)`
4. `doc/README.md` â€” `> Versione documentazione: **X.Y.Z**`
5. `doc/START_HERE.md` â€” `> Versione documentazione: **X.Y.Z**`
6. `doc/TESTING.md` â€” `> Versione documentazione: **X.Y.Z**`
7. `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md` â€” `> Versione documentazione: **X.Y.Z**`
8. `doc/STRUTTURA_ATTUALE_PORTALE.md` â€” `Data snapshot: YYYY-MM-DD | Versione: X.Y.Z`
9. `deployment/README_DEPLOY_IIS_WINDOWS.md` â€” `> Versione repo: **X.Y.Z**`
10. `tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md` â€” `> NOVICROM HUB Â· Aggiornato: YYYY-MM-DD (vX.Y.Z)`

### Regole operative

- I default codice leggono da `VERSION` tramite `config/app_version.py`; evitare ulteriori hardcode.
- Il file `.env` runtime ha precedenza sui default nel codice: se non viene aggiornato, UI e wizard mostrano il valore precedente.
- Dopo ogni modifica a `setup_wizard.py` rigenerare `deployment/dist/SetupWizard.exe` (vedi sezione Setup Wizard).

---

