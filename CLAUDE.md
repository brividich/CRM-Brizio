# CLAUDE.md - NOVICROM HUB AI Instructions

Versione app corrente: **1.0.1** (2026-04-28)

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

# ACL / release support
python django_app\manage.py bootstrap_acl_v2 --dry-run
python django_app\manage.py acl_fallback_report --only-unbound
python django_app\manage.py acl_coverage_report --max-missing 216
.\tools\release_guard.ps1
```

No tests are required for documentation-only changes unless project files outside documentation are changed.

## Patch Workflow

- Read only the relevant AI doc(s), not the whole `docs/ai` folder.
- Keep edits scoped and compatible with existing module boundaries.
- For code changes, update `CHANGELOG.md`; update `README.md` only when visible functionality, URLs, setup, dependencies, or user-facing docs change.
- Update root `CLAUDE.md` only for concise operational changes; put long-form details in the relevant `docs/ai/*.md` file.
- If user-facing behavior changes, follow the version-bump checklist in [docs/ai/06_TESTING_AND_QUALITY_GATES.md](docs/ai/06_TESTING_AND_QUALITY_GATES.md).
- If `deployment/setup_wizard.py` changes, regenerate `deployment/dist/SetupWizard.exe` and respect bundle exclusions.

## Documentation Map

- [docs/ai/00_INDEX.md](docs/ai/00_INDEX.md) - AI documentation index.
- [docs/ai/01_PROJECT_CONTEXT.md](docs/ai/01_PROJECT_CONTEXT.md) - product context, SiteConfig, search, audit, onboarding, logging, cache.
- [docs/ai/02_ARCHITECTURE.md](docs/ai/02_ARCHITECTURE.md) - stack, ACL, routing, deployment-only infrastructure.
- [docs/ai/03_BACKEND_MODULES.md](docs/ai/03_BACKEND_MODULES.md) - app catalog, Hub Tools, automations backend.
- [docs/ai/04_FRONTEND_DIRECTION.md](docs/ai/04_FRONTEND_DIRECTION.md) - SSR/HTMX, navigation, dashboards, designer UI.
- [docs/ai/05_SECURITY_BOUNDARIES.md](docs/ai/05_SECURITY_BOUNDARIES.md) - ACL/security/privacy boundaries.
- [docs/ai/06_TESTING_AND_QUALITY_GATES.md](docs/ai/06_TESTING_AND_QUALITY_GATES.md) - release guard, versioning, Setup Wizard, tests.
- [docs/ai/07_PATCH_HISTORY.md](docs/ai/07_PATCH_HISTORY.md) - patch/release-history maintenance rules.
- [docs/ai/08_ROADMAP.md](docs/ai/08_ROADMAP.md) - current direction and known debt.
- [docs/ai/09_PROMPT_LIBRARY.md](docs/ai/09_PROMPT_LIBRARY.md) - reusable targeted prompts.

## Current Product Direction

- Keep NOVICROM HUB as the canonical brand.
- Keep `dashboard` as KPI/launcher; domain workflows stay in their modules.
- Continue ACL migration toward canonical v2 while preserving legacy fallback until coverage is complete.
- Keep automation approvals fail-closed, deduplicated, auditable, and portable across email/Teams/Graph paths.
- Keep Setup Wizard and Windows/IIS deployment flows fail-fast and reproducible.
- For Security Center AI, prioritize safety/compliance workflows, privacy, auditability, and synthetic test/demo data.
