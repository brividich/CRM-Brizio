# AI Documentation Index

This directory contains the long-form AI context that used to live in the root `CLAUDE.md`.

Important: Do not read all docs automatically. Open only the files relevant to the current task.

## Map

| File | Use when you need |
| --- | --- |
| [01_PROJECT_CONTEXT.md](01_PROJECT_CONTEXT.md) | Product summary, SiteConfig, global search, audit, onboarding, logging, cache, known debt. |
| [02_ARCHITECTURE.md](02_ARCHITECTURE.md) | Stack, ACL architecture, routing, deployment-only infrastructure, settings, Graph/SharePoint architecture. |
| [03_BACKEND_MODULES.md](03_BACKEND_MODULES.md) | Django app catalog, module-specific backend rules, Hub Tools, automations engine. |
| [04_FRONTEND_DIRECTION.md](04_FRONTEND_DIRECTION.md) | SSR/HTMX conventions, navigation rendering, dashboards, visual designer UI rules. |
| [05_SECURITY_BOUNDARIES.md](05_SECURITY_BOUNDARIES.md) | ACL, auth boundaries, public/token routes, hardening, sensitive-file boundaries, Security Center AI safety rules. |
| [06_TESTING_AND_QUALITY_GATES.md](06_TESTING_AND_QUALITY_GATES.md) | Required update workflow, release guard, version bump, Setup Wizard rules, test/dev commands. |
| [07_PATCH_HISTORY.md](07_PATCH_HISTORY.md) | Patch workflow, version/changelog rules, release-history maintenance. |
| [08_ROADMAP.md](08_ROADMAP.md) | Current product direction, migration goals, technical debt, Security Center AI direction. |
| [09_PROMPT_LIBRARY.md](09_PROMPT_LIBRARY.md) | Reusable task prompts for future AI sessions. |
| [10_MAINTENANCE_MODERNIZATION.md](10_MAINTENANCE_MODERNIZATION.md) | Checklist operativa del piano di ammodernamento sezione manutenzione (P1.1→P3.5). Aggiornare i checkbox a ogni completamento. |
| [11_FEATURE_BACKLOG.md](11_FEATURE_BACKLOG.md) | Backlog funzionalità pianificate (competitive analysis). Checklist di avanzamento per modulo con priorità e note tecniche. |
| [12_AI_RUNTIME_TOOLS_TODOLIST.md](12_AI_RUNTIME_TOOLS_TODOLIST.md) | Piano dettagliato per estendere l'Assistente AI ai dati live del portale con tool runtime, ACL e audit metadata-only. |
| [13_AI_GOVERNANCE.md](13_AI_GOVERNANCE.md) | Governance AI Fase 5: matrice campi consentiti/vietati per modulo, policy retention audit e FAQ, prompt di sistema, runbook operativo. |

## Rule Of Thumb

Start with root [../../CLAUDE.md](../../CLAUDE.md). If the task touches a specific area, open the matching file above. If the task changes code, check [06_TESTING_AND_QUALITY_GATES.md](06_TESTING_AND_QUALITY_GATES.md) before finishing.
