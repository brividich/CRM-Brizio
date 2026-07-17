# SOC IT — Guida di configurazione resa in-app + rifiniture UX Configuration Studio

- **Data:** 2026-07-17
- **Modulo:** `django_app/security/` (Security Center IT — "SOC IT - CN", montato su `/soc/`)
- **Branch:** `feature/soc-config-guide` (worktree `C:\Dev\pn-soc-guide`)
- **Versione app di partenza:** 1.3.0
- **Ambito scelto con il richiedente:** *Guida + rifiniture UX della configurazione* — **nessuna modifica** al motore alert/dedup, parser, ingestione, modelli o migrazioni.

---

## 1. Problema

Il modulo `security` (SOC IT) è funzionalmente maturo: sorgenti + ingestione mailbox (Graph/IMAP/mock/manuale), parser, regole alert con dedup a livello DB, finding vulnerabilità/CVE, monitoraggio backup/NAS, evidence, ticket di remediation, canali notifica email/Teams, regole di soppressione, KPI, audit log, layer AI/RAG. La **Configuration Studio** in `/soc/admin/config/` copre 9 sezioni (general, sources, parsers, alert-rules, suppressions, backups, notifications, ticketing, audit) + diagnostica + moduli.

Ma la **documentazione promessa dall'UI non esiste**:

- `SECURITY_CENTER_DOCS` (in `security/views.py`, ~riga 830) elenca **13 documenti** (`00_START_HERE.md` … `11_OPERATIONS_RUNBOOK.md`, `MAILBOX_INGESTION.md`), incluso `08_CONFIGURATION_GUIDE.md`.
- Le pagine `Guida / Operatività` (`/soc/security/help/`) e `Indice documentazione` (`/soc/security/admin/docs/`) mostrano **solo una tabella con i nomi dei file**, non il contenuto.
- `admin_docs.html` dichiara che i doc vivono in `docs/security-center/`, ma **quella cartella e quei file non esistono** in tutto il repo.

Inoltre le 9 sezioni di configurazione sono spartane: `{{ form.as_p }}` nudo senza help, il "Test regola" usa un input JSON grezzo `{"value": 1}` senza spiegazione, empty-state minimali, nessun collegamento dalla sezione alla guida o alla diagnostica.

## 2. Obiettivo

1. Creare **realmente** la documentazione (13 doc Markdown), con al centro la **guida di configurazione**.
2. Rendere le due pagine in-app **funzionanti**: indice **clickabile** → pagina che **renderizza** il Markdown nel tema SOC.
3. **Rifinire la UX** della Configuration Studio con help contestuale e collegamenti, senza toccare la logica.

## 3. Decisioni prese (con il richiedente)

| Tema | Decisione |
|---|---|
| Ampiezza | Guida + rifiniture UX della configurazione. **No** revisione funzionale del motore. |
| Forma guida | Markdown **reso in-app** (non documento esterno). |
| Rendering | **Renderer interno, zero dipendenze** (né `markdown` né `bleach` nel venv). |
| Doc set | **Set completo**: tutti i 13 documenti indicizzati (indice senza voci rotte). |

## 4. Vincolo di deploy critico (posizione dei file)

Il packager `deployment/scripts/package-release.ps1` costruisce il pacchetto con una **allowlist** (`$includeDirs = django_app, deployment, tools, sql`) e passa a robocopy `/XD` la lista `$excludeDirs`, che include **`doc`** e **`docs`**. `robocopy /XD <nome>` esclude **qualsiasi cartella con quel nome a qualunque livello dell'albero**.

Conseguenze:
- I `.md` in `docs/security-center/` (root) **non arrivano in produzione** (root `docs/` esclusa).
- Anche una `django_app/security/docs/` verrebbe **scartata** perché la cartella si chiama `docs`.

**Decisione:** la guida vive in **`django_app/security/guide/`**. `guide` non è in `$excludeDirs`; i `.md` non sono in `$excludeFiles` → la cartella viene impacchettata e i doc esistono in prod. Il loader risolve il percorso in modo robusto via `Path(__file__).resolve().parent / "guide"` (funziona identico in dev e in prod). Il testo dell'indice che oggi cita `docs/security-center/` viene aggiornato per riflettere la guida integrata.

## 5. Architettura della soluzione

Due componenti indipendenti, entrambi **presentation-only**.

### 5.1 Renderer Markdown interno (`django_app/security/docs_render.py`)

Nessuna dipendenza esterna. Contenuto **attendibile** (file del repo), ma il renderer resta **difensivo**: fa `html.escape` del testo prima di applicare l'inline markup, e in fase inline scarta gli schemi di link non sicuri (`javascript:`, `data:`), ammettendo solo `http`, `https`, `mailto` e link relativi/anchor.

Funzioni pubbliche:

- `render_markdown(text: str) -> str` → HTML sicuro (marcato `mark_safe`). Blocchi supportati: heading ATX `#`..`######` (con `id` slug per le ancore), paragrafi, liste ordinate/non ordinate (almeno 1 livello di nesting), code fence ```` ``` ````, blockquote `>`, regola orizzontale `---`, tabelle GFM `| … |`. Inline: `**grassetto**`, `*corsivo*`, `` `code` ``, `[testo](url)`, a-capo forzato.
- `build_toc(text: str) -> list[dict]` → indice `{level, text, slug}` per la barra laterale del doc.
- `DOC_SLUGS` / `slug_for(filename)` / `filename_for(slug)` → mappa **whitelist** slug↔filename derivata da `SECURITY_CENTER_DOCS`. Slug = filename senza `.md`, minuscolo, `_`→`-` (`00_START_HERE.md` → `00-start-here`).
- `load_doc(slug) -> dict | None` → risolve il filename **solo dalla whitelist** (mai dal path grezzo: guard anti path-traversal), legge UTF-8, ritorna `{meta, html, toc}`. Slug sconosciuto → `None` (la view fa 404). File assente sul disco → contenuto placeholder "documento non ancora disponibile" (fail-soft, nessun 500).

### 5.2 Rendering in-app dei doc

- **Nuova view** `doc_detail(request, slug)` in `views.py`, gated da `can_view_security_center(request.user)` (coerente con l'accesso al SOC; l'indice admin resta gated da `can_manage_security_config`). 404 su slug fuori whitelist.
- **Nuova route** in `urls.py`: `security/docs/<slug:slug>/` → `doc_detail` (name `doc_detail`).
- **Nuovo template** `security/templates/security/doc_detail.html` (estende `_base_soc.html`): titolo doc + TOC laterale + HTML renderizzato, con pulsante "← Indice" e link "Configurazione"/"Diagnostica".
- `SECURITY_CENTER_DOCS` arricchito con `slug` per costruire gli URL.
- `admin_docs.html` e `help.html`: le righe della tabella diventano **link** a `doc_detail`. Aggiornato il testo che cita `docs/security-center/`.

### 5.3 Rifiniture UX Configuration Studio (no logica)

- **Dizionario** `CONFIG_SECTION_HELP` in `views.py`: per ciascuna delle 9 sezioni `{titolo, intro, doc_slug, tips[]}`.
- Ogni view `admin_config_*` aggiunge `section_help` al context.
- **Nuovo partial** `security/templates/security/admin_config/_section_help.html`: pannello `sec-panel` in cima alla sezione con intro, pulsante "Apri guida" → `doc_detail(doc_slug)`, pulsante "Diagnostica", elenco `tips`. Incluso nelle 9 pagine.
- **Fix mirati:** in `alert_rules.html` il test-regola riceve label + micro-spiegazione dell'input JSON; empty-state resi più chiari dove sono scarni. Nessun cambio ai form/campi del modello.
- **Navigazione:** voce "Guida" nella `soc-nav` di `_base_soc.html` (punta a `help`), così la guida è raggiungibile da tutto il modulo.

## 6. File toccati

**Nuovi**
- `django_app/security/guide/` → 13 `.md`: `00_START_HERE`, `01_ARCHITECTURE`, `02_ADMIN_GUIDE`, `03_ADDONS`, `04_WATCHGUARD_ADDON`, `05_DEFENDER_ADDON`, `06_BACKUP_ADDON`, `07_ALERT_LIFECYCLE`, `08_CONFIGURATION_GUIDE`, `09_TROUBLESHOOTING`, `10_DEVELOPER_GUIDE`, `11_OPERATIONS_RUNBOOK`, `MAILBOX_INGESTION`.
- `django_app/security/docs_render.py`
- `django_app/security/templates/security/doc_detail.html`
- `django_app/security/templates/security/admin_config/_section_help.html`
- `django_app/security/tests/test_docs_render.py`
- `django_app/security/tests/test_docs_views.py`

**Modificati**
- `django_app/security/views.py` (view `doc_detail`, `slug` in `SECURITY_CENTER_DOCS`, `CONFIG_SECTION_HELP`, context nelle 9 view di config)
- `django_app/security/urls.py` (route `doc_detail`)
- `django_app/security/templates/security/admin_docs.html`, `help.html`
- `django_app/security/templates/security/_base_soc.html` (voce nav "Guida")
- Le 9 `django_app/security/templates/security/admin_config/*.html` (include `_section_help`, fix mirati)
- `CHANGELOG.md`, `README.md` (riga modulo `security`)

## 7. Contenuto dei 13 documenti (indice sintetico)

Contenuto **operativo e sintetico**, in italiano, con esempi **sintetici** (nessun dato reale/segreto, coerente con i Security Boundaries). I riferimenti ai comandi usano quelli reali del modulo: `seed_security_center_config`, `security_center_diagnostics`, `ingest_security_mailbox`, `run_security_parsers`, `evaluate_security_rules`, `build_daily_kpi_snapshots`, `check_security_source_heartbeat`, `send_security_test_notification`, `collega_asset_security`, `security_db_check`, `security_uat_smoke_check`.

1. **00_START_HERE** — ambito (non è un SIEM), prerequisiti, primo setup in 30 minuti, checklist.
2. **01_ARCHITECTURE** — flusso Report/email/upload → ingestione → parser → metriche/finding → regole → alert/soppressione → evidence → ticket → dashboard; ruolo di KPI e audit.
3. **02_ADMIN_GUIDE** — le 9 sezioni della Configuration Studio, cosa fa ciascuna, campi principali.
4. **03_ADDONS** — modello core vs moduli; come i moduli si innestano.
5. **04_WATCHGUARD_ADDON** — input supportati, metriche, regole, riduzione rumore, limiti.
6. **05_DEFENDER_ADDON** — vulnerabilità via email, evidenze CVE, dedup ticket, ricorrenze.
7. **06_BACKUP_ADDON** — sorgente Synology Active Backup, job attesi, backup mancanti, salute.
8. **07_ALERT_LIFECYCLE** — stati alert e differenze (presa in carico, posticipo, silenziamento, soppressione, risoluzione, falso positivo, chiusura).
9. **08_CONFIGURATION_GUIDE** — *(centro)* configurazione seed + impostazioni DB per sorgenti, parser, regole, soppressioni, backup, notifiche, ticketing; permessi/ACL (`security.config.view`, `manage_security_configuration`, `is_staff`).
10. **09_TROUBLESHOOTING** — problemi comuni: nessun parser, nessun alert, nessun ticket, backup non rilevato, notifiche mute, permesso negato.
11. **10_DEVELOPER_GUIDE** — purezza dei parser, struttura output, test, seed, visibilità dashboard.
12. **11_OPERATIONS_RUNBOOK** — checklist giornaliera/settimanale/mensile.
13. **MAILBOX_INGESTION** — ingestione schedulata da mailbox, provider (Graph/IMAP/mock/manuale), dedup, gate mittente/DKIM-SPF, `expected_every_hours`/heartbeat, troubleshooting.

## 8. Strategia di test (TDD)

- `test_docs_render.py`: heading→`<h1..6>` con `id` slug; liste ordinate/non; code fence che **escapa** l'HTML interno; tabella GFM; link con schema `javascript:` **scartato**; grassetto/corsivo/inline-code; `load_doc` su slug valido ritorna contenuto; slug `../../x` o sconosciuto → `None`.
- `test_docs_views.py`: `doc_detail` → redirect/403 per anonimo/non autorizzato; 200 per utente SOC; 404 su slug fuori whitelist; una sezione `admin_config_*` contiene il pannello di help (`assertContains`).
- Vincoli test del progetto: usare `@override_settings(LEGACY_AUTH_ENABLED=False)` dove serve evitare il 403 dell'ACL middleware; label `security` per lo scoping (`manage.py test django_app.security --settings=config.settings.test --keepdb`). Nel worktree può mancare `.env` (non è regressione).

## 9. Non-obiettivi (guard anti-overscope)

- Nessuna modifica a: motore regole/dedup, parser, ingestione, notifiche, heartbeat, modelli, migrazioni.
- Nessuna nuova dipendenza pip.
- Nessun restyle globale del tema (si riusano i token `sec-*` esistenti).
- Nessun documento con dati reali/segreti: solo esempi sintetici.

## 10. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Cartella guida scartata dal packager | Nome `guide` (non `doc`/`docs`); loader via `Path(__file__)`; verifica in fase di test/UAT che i file esistano a runtime. |
| Path traversal via slug | Whitelist slug↔filename; mai path da input. |
| Injection nei doc | `html.escape` + allowlist schemi link nel renderer. |
| Renderer incompleto sul Markdown reale | I doc si scrivono usando **solo** i costrutti supportati; i test coprono i costrutti usati. |
| Regressione ACL sulle pagine | `doc_detail` gated con helper esistenti; test di accesso. |

## 11. Definition of Done

- I 13 `.md` esistono in `django_app/security/guide/` e si aprono renderizzati da `admin_docs` e `help`.
- La guida di configurazione è completa e accurata rispetto ai comandi/permessi reali.
- Le 9 sezioni config mostrano il pannello di help con link a guida + diagnostica.
- Test `django_app.security` verdi (renderer + view).
- `CHANGELOG.md` e `README.md` aggiornati.
- Commit su `feature/soc-config-guide` nel worktree dedicato.
