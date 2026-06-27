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
| [13_AI_GOVERNANCE_PREDICTIVE_POLICY.md](13_AI_GOVERNANCE_PREDICTIVE_POLICY.md) | Policy operativa Assistente AI: confini ACL server-side, niente salvataggi automatici di prompt/dati, tracciabilità via fonti o `tool:*`, funzioni predittive assistive ed esplicabili. |
| [PIANO_ACL_FASE2_DISMISSIONE_LEGACY.md](PIANO_ACL_FASE2_DISMISSIONE_LEGACY.md) | Piano operativo per chiudere il doppio sistema ACL (legacy+canonico): moduli interessati, procedura per modulo, trappola dei filtri `--app`/`--apps`, ordine e rischi. Autosufficiente per una nuova sessione. |
| [CHECKLIST_ATTIVAZIONE_ACL_STRICT_PROD.md](CHECKLIST_ATTIVAZIONE_ACL_STRICT_PROD.md) | Checklist operativa per attivare `ACL_STRICT_CANONICAL` in prod (misura readiness, UAT, prod, rollback) e per la pulizia del codice legacy (≥ 2026-06-19). |
| [ASSET_MAINTENANCE_PLAN.md](ASSET_MAINTENANCE_PLAN.md) | Diagnosi + roadmap a fasi del dominio Asset/Manutenzioni (dashboard → template → regole → viste → report): anelli rotti del ciclo di vita e ordine di intervento. |
| [AUTOMATION_PACKAGE_REFERENCE.md](AUTOMATION_PACKAGE_REFERENCE.md) | Reference autonomo per generare file `.automation_package.json` importabili nel modulo Automazioni: struttura package, nodi, esempi. |
| [RUNBOOK_PROD_DEPLOY_E_MAIL_ANOMALIE.md](RUNBOOK_PROD_DEPLOY_E_MAIL_ANOMALIE.md) | Topologia deploy PROD/TEST (server `pclogsys`, share `X:`/`Y:`) e runbook dell'incidente 401 sulla mail anomalie CC/CAR. |
| [TABELLE_PERSONALIZZABILI.md](TABELLE_PERSONALIZZABILI.md) | Infrastruttura tabelle personalizzabili per-utente (`UserTablePreference`): sort/filtro/ricerca/visibilità/ordine per colonna, rollout client-side globale. |
| [RAG_SGI_ROLLOUT.md](RAG_SGI_ROLLOUT.md) | RAG SGI (documenti SGI citabili nell'Assistente AI): riepilogo F1–F3, settings con default, runbook di rollout prod (pull modello embedding, stemming opt-in, `index_sgi_documents` + schedulazione), verifica funzionale. |
| [14_AI_EXPANSION_ROADMAP.md](14_AI_EXPANSION_ROADMAP.md) | Backlog ordinato (a ondate) per espandere l'AI nel portale: nuovi tool live, copiloti per-modulo, allargamento RAG, predittivo/digest. Vincoli, pattern riusabili, effort e ordine di partenza. |
| [GUIDA_AI.html](GUIDA_AI.html) | Guida HTML (autoconsistente, per utenti) al funzionamento dell'Assistente AI: architettura on-premise (Ollama+TEI), RAG SGI citabile, tabella dei tool runtime, esempi di domande, limiti/privacy/governance, roadmap a ondate. **Da tenere aggiornata a ogni nuova capacità AI** (nuovi tool, nuovi corpora RAG, cambi di policy). |
| [OLLAMA_GPU_TUNING.md](OLLAMA_GPU_TUNING.md) | Runbook ottimizzazione GPU/modelli AI su PCGAVANCINI (A4000 16GB): topologia Ollama(chat) + TEI(embeddings), env server-side raccomandate (max_loaded_models=1 perché gli embeddings sono su TEI, flash attention, KV-cache q8_0, num_parallel), come applicarle via NSSM, settings portale (num_predict cap), verifica (`ai_healthcheck_prod.ps1`, `ollama ps`, `nvidia-smi`) e rollback. |

## Rule Of Thumb

Start with root [../../CLAUDE.md](../../CLAUDE.md). If the task touches a specific area, open the matching file above. If the task changes code, check [06_TESTING_AND_QUALITY_GATES.md](06_TESTING_AND_QUALITY_GATES.md) before finishing.
