# CLAUDE.md - NOVICROM HUB AI Instructions

Versione app corrente: **1.3.0** (2026-07-05)

## Prime Directive

Build and maintain NOVICROM HUB conservatively: preserve security boundaries, auditability, legacy compatibility, and operational reliability. Prefer existing Django/SSR/HTMX patterns over new abstractions. Keep root `CLAUDE.md` short; long-form context lives in `docs/ai/`.

Do not read all docs automatically. Open only the files relevant to the current task.

## Security Boundaries

- Never include secrets, real customer data, mailbox dumps, production logs, credentials, certificates, private reports, or raw personal-data exports in prompts, docs, commits, generated examples, screenshots, or test fixtures.
- Treat `.env`, deploy `config/.env`, Graph/LDAP/SMTP credentials, certificates, database dumps, media with personal data, mailbox content, and production logs as sensitive runtime material.
- Use synthetic examples for incidents, procedures, DPI, approvals, mailbox messages, Graph payloads, SharePoint data, and employee/customer records.
- Preserve ACL v2 as the primary authorization layer; legacy ACL is compatibility fallback only when no canonical binding exists.
- Navigation visibility is not a security boundary. Server-side ACL/middleware decisions remain authoritative.
- Public/token surfaces must stay narrow: `/automazioni/approvazione/*` and `/approval-actions/*` only for approval tokens; publish only `/approval-actions/*` through Entra Application Proxy.
- API/AJAX protected endpoints must return JSON `401/403`, not HTML redirects.
- For Security Center AI work (`diario_preposto`, `rilevazione_incidenti`, `procedure_refresh`, `dpi`, `rentri`), preserve audit trail, source-of-truth boundaries, privacy, and user-visible traceability.

Details: [docs/ai/05_SECURITY_BOUNDARIES.md](docs/ai/05_SECURITY_BOUNDARIES.md).

## Project Summary

NOVICROM HUB is the internal Django portal for workflows, operations, safety/compliance, automations, and granular ACL governance. Historical names such as `Portale Novicrom` may remain only as deployment/path examples or legacy references.

Primary product areas:
- Core platform: `core`, `dashboard`, `admin_portale`, `hub_tools`, `setup_wizard`, `monitoring`.
- Operations: `anagrafica`, `assets`, `tasks` / KICK-OFF, `planimetria`.
- HR/workflow: `assenze`, `anomalie`, `tickets`, `timbri`, `notizie`.
- Safety/compliance: `dpi`, `diario_preposto`, `rilevazione_incidenti`, `procedure_refresh`, `rentri`.
- Automation: `automazioni` visual designer, SQL queue, approvals, Graph mailbox polling.

## Tech Stack

- Backend: Django 5.2, Python 3.11+.
- Production runtime: Waitress via IIS HttpPlatformHandler.
- Databases: SQL Server in test/prod via `mssql-django` + `pyodbc`; SQLite only for Django-only development.
- Auth cascade: `AxesStandaloneBackend` -> `SQLServerLegacyBackend` -> `LDAPBackend` -> `ModelBackend`.
- Frontend: server-rendered Django templates, custom CSS, HTMX partial updates; no full JS framework.
- Integrations: Microsoft Graph/SharePoint/Outlook Calendar, LDAP/AD, SMTP, Entra Application Proxy for approval actions.
- Cache: SQL Server `DatabaseCache` in production; local memory cache in dev.

## Essential Commands

```powershell
# Dev setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r django_app\requirements.txt
python django_app\manage.py migrate --settings=config.settings.dev
python django_app\manage.py runserver --settings=config.settings.dev

# Tests / checks
python django_app\manage.py test
python django_app\manage.py check --settings=config.settings.test
python django_app\manage.py secret_hygiene_check
python django_app\manage.py validate_deployment --format json --settings=config.settings.test

# Tests - scoped (prefer these during development)
python django_app\manage.py test django_app.<app_name> --settings=config.settings.test
python django_app\manage.py test django_app.<app_name> --keepdb --settings=config.settings.test

# ACL / release support
python django_app\manage.py bootstrap_acl_v2 --dry-run
python django_app\manage.py acl_fallback_report --only-unbound
python django_app\manage.py acl_coverage_report --max-missing 222
# Settings files call _load_dotenv(...) to read .env at startup
.\tools\release_guard.ps1  # also: tools/release_guard.ps1
```

No tests are required for documentation-only changes unless project files outside documentation are changed.

## Resource Constraints

- **Never run the full test suite (`manage.py test`) unless explicitly asked.**
- Default to running only the tests for the app being modified:
  `python django_app\manage.py test django_app.<app_name> --settings=config.settings.test`
- Use `--keepdb` whenever possible to avoid recreating the test DB on every run.
- Do not run `runserver` and the full test suite simultaneously.
- Prefer `--verbosity 0` when running tests in background to reduce I/O.

## Background Work Guard (ALWAYS)

- Whenever you start a **process, subagent (`Agent`), or background work** (`run_in_background` Bash/PowerShell, `Workflow`, long `Task`, external status polling), immediately arm a `ScheduleWakeup` **guard** so you regain control even if the completion notification never arrives.
- Cadence ~5 min: use `delaySeconds: 270` (stays inside the 5-min prompt-cache TTL). Re-arm on each wake while the work is still in flight; explicit `reason`.
- Close the guard (`ScheduleWakeup(stop: true)`) when the work finishes. The guard protects a **real wait** — don't leave hollow wakeups when nothing is running.
- Rationale: past background waits left the session **stuck**; this is the safety heartbeat.

## Session Isolation (ALWAYS)

Multiple Claude sessions work on this repo **at the same time**. The branch and the uncommitted files belong to the *folder*, not to the session: if every session works in `C:\Dev\Portale Novicrom`, one session's `git checkout` switches the branch under the others, and one session's `git add` stages another session's WIP (it also silently discards uncommitted edits made there).

- **Never work directly in the shared checkout `C:\Dev\Portale Novicrom`**, and never run `git checkout`/`git switch` there. Treat it as a read-only reference.
- Before producing any commit, create a **dedicated worktree** on a dedicated branch:
  `git worktree add C:\Dev\pn-<topic> -B <branch> origin/<base-branch>`
  Work, test, commit and push from there; then `git worktree remove` (if the path is too long for git: `cmd /c rmdir /s /q <path>` + `git worktree prune`).
- If you must touch a file in the shared checkout, **stage only your own hunks** — never `git add -A` / `git commit -a`: the working tree holds other sessions' WIP.

## Disciplina git di sessione (ALWAYS)

Il server di sviluppo serve la **cartella di lavoro**: il codice "funziona" anche quando non è committato. Il packager invece esporta un **commit del branch di release**. Un file non committato quindi funziona in locale e non esiste per la produzione — e la divergenza si scopre al deploy.

- **Ogni sessione APRE con `git status`.** Se il tree è già sporco, il lavoro precedente va chiuso prima: non si costruisce sopra il WIP di un altro.
- **Ogni sessione CHIUDE con un commit** su branch feature (`feature/<area>-<tema>`), nel worktree dedicato di cui sopra. Nessuna sessione termina con working tree sporco.
- **Committare non è deployare.** Un commit WIP su branch feature è al sicuro, recuperabile e visibile in `git branch` — ma **non è in produzione**. Il codice è in produzione solo quando è in **`release/prod`**: è da lì che `package-release.ps1` esporta. Non c'è alcun motivo per lasciare lavoro fuori da git, e nessuna garanzia che un commit fuori da `release/prod` arrivi mai sul server.
- **Il pacchetto si produce SOLO da un commit.** Il pre-flight di `package-release.ps1` fallisce se il tree è sporco o se il branch corrente ha commit assenti da `release/prod`. `-FromWorkingTree -Force` è un'emergenza, non una scorciatoia: il pacchetto che ne esce si dichiara non tracciabile in `BUILD_INFO.json` e la Centrale di comando lo mostra in rosso.
- In sviluppo (`DEBUG=True`) il badge in alto a destra tiene i due numeri sotto gli occhi: file non committati e commit non ancora in `release/prod`.

## Patch Workflow

- Read only the relevant AI doc(s), not the whole `docs/ai` folder.
- Keep edits scoped and compatible with existing module boundaries.
- **MANDATORY after every code change:** update `CHANGELOG.md` with all modified files and a description under `[Unreleased]`. Do this automatically, without waiting for an explicit request.
- **MANDATORY when visible functionality, URLs, setup, dependencies, or user-facing docs change:** update `README.md` (module catalog table and/or the relevant `<details>` section). Do this automatically, without waiting for an explicit request.
- Update root `CLAUDE.md` only for concise operational changes; put long-form details in the relevant `docs/ai/*.md` file.
- If user-facing behavior changes, follow the version-bump checklist in [docs/ai/06_TESTING_AND_QUALITY_GATES.md](docs/ai/06_TESTING_AND_QUALITY_GATES.md).
- If `deployment/setup_wizard.py` changes, regenerate `deployment/dist/SetupWizard.exe` and respect bundle exclusions.

## Documentation Map

Long-form context lives in `docs/ai/`. The canonical, complete index is [docs/ai/00_INDEX.md](docs/ai/00_INDEX.md) — open only the file relevant to the current task. Keep this pointer here instead of duplicating the file list. Two pointers worth inlining: security boundaries in [docs/ai/05_SECURITY_BOUNDARIES.md](docs/ai/05_SECURITY_BOUNDARIES.md), and the pre-finish quality gates in [docs/ai/06_TESTING_AND_QUALITY_GATES.md](docs/ai/06_TESTING_AND_QUALITY_GATES.md).

## Current Product Direction

- Keep NOVICROM HUB as the canonical brand.
- Keep `dashboard` as KPI/launcher; domain workflows stay in their modules.
- Continue ACL migration toward canonical v2 while preserving legacy fallback until coverage is complete.
- Keep automation approvals fail-closed, deduplicated, auditable, and portable across email/Teams/Graph paths.
- Keep Setup Wizard and Windows/IIS deployment flows fail-fast and reproducible.
- For Security Center AI, prioritize safety/compliance workflows, privacy, auditability, and synthetic test/demo data.

