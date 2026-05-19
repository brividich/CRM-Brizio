# SEC-PREPROD-02 — Evidence Report

**Progetto:** NOVICROM HUB (Portale Novicrom / CRM-Brizio)
**Ambito:** Patch security pre-produzione — object-level authorization (H1, M2, M3, M1)
**Branch:** `pre-prod-security`
**Baseline commit:** `f8005f8` — *Harden asset assignment and release guard*
**Data:** 2026-05-16
**Autore intervento:** Application Security Engineer (sessione assistita)
**Classificazione documento:** Interno — Evidence di remediation, propedeutico ad audit PDF
**Patch correlate:** [SEC-PREPROD-01](SEC-PREPROD-01_EVIDENCE.md) (header / CSRF / SQL / `json_script`),
[SEC-PREPROD-03](SEC-PREPROD-03_EVIDENCE.md) (stabilizzazione 5 test `admin_portale`)

---

## Indice

1. [Rischi chiusi](#1-rischi-chiusi)
2. [File modificati](#2-file-modificati)
3. [Policy implementate](#3-policy-implementate)
4. [Test aggiunti ed esiti](#4-test-aggiunti-ed-esiti)
5. [Failure preesistenti (non introdotte dalla patch)](#5-failure-preesistenti-non-introdotte-dalla-patch)
6. [acl_coverage_report](#6-acl_coverage_report)
7. [AUDIT EVIDENCE](#7-audit-evidence)
8. [Go / No-Go](#8-go--no-go)

Patch di hardening pre-produzione completata. Tutte le modifiche sono minime, senza
refactor, senza nuove dipendenze, senza cambi DB / URL / UX.

---

## 1. Rischi chiusi

| Finding | Descrizione | Esito |
|---|---|---|
| H1 | `rilevazione_incidenti.export_pdf` — nessun controllo ruolo / IDOR su PII | ✅ Chiuso |
| M2 | `timbri._download_image` — token Graph inviabile a host arbitrario | ✅ Chiuso |
| M3 | `rentri` — CRUD registro rifiuti senza gate ruolo esplicito | ✅ Chiuso |
| M1 | `rilevazione_incidenti` — viste lettura senza difesa in profondità | ⚠️ Chiuso parzialmente (vedi note) |

---

## 2. File modificati

| File | Motivo security | Tipo |
|---|---|---|
| `django_app/rilevazione_incidenti/views.py` | H1: gate ruolo su `export_pdf` + fix 404 mascherato; M1: `@login_required` | Modifica |
| `django_app/rilevazione_incidenti/tests.py` | Test H1 + M1 | Modifica |
| `django_app/timbri/views.py` | M2: allowlist host per token Graph | Modifica |
| `django_app/timbri/tests.py` | Test M2 | Modifica |
| `django_app/rentri/views.py` | M3: gate ruolo scrittura | Modifica |
| `django_app/rentri/tests.py` | Test M3 | Nuovo file |
| `CHANGELOG.md` | Voce `[Unreleased]` / Security | Modifica |

---

## 3. Policy implementate

### H1 — `export_pdf`

`export_pdf` genera il PDF solo se `is_superuser` OR `_can_manage_rspp(request)` OR
`_can_create(request)` (gestori sicurezza / preposti / RSPP / admin). Altrimenti → **403
reale** con template `forbidden`. Rilevazione inesistente → **Http404** (eliminato il bug
"template forbidden con status 404"). Nessun ruolo nuovo inventato — riusati gli helper
esistenti del modulo.

### M2 — `_download_image`

Nuovo helper `_is_graph_trusted_host(url)`: accetta solo `http(s)` verso
`graph.microsoft.com`, `*.graph.microsoft.com`, `*.sharepoint.com`. `_download_image`
rifiuta (`RuntimeError`, nessuna `requests.get`) ogni URL fuori allowlist, senza hostname o
con schema non valido. Timeout 30s già presente, mantenuto. Token mai loggato.

### M3 — `rentri` CRUD

Nuovo helper `_can_manage_rentri(request)` (superuser o admin legacy) + `_require_rentri_manager`
che ritorna `JsonResponse` 403. Applicato a tutte le scritture: `carico` / `scarico_*` /
`rettifica` (`_handle_form` POST), `modifica` (POST), `elimina`, `import_confirm`,
`api_sync_pull`. Lettura (`elenco`, `export_pdf`, `import_preview`) invariata. `elimina`
resta `@require_POST`.

### M1 — viste lettura `rilevazione_incidenti`

Aggiunto `@login_required` come difesa in profondità a `lista`, `dettaglio`, `modifica`,
`elimina`, `statistiche`, `heatmap`, `impostazioni`, `export_csv`, `export_pdf`. Il blocco
per-proprietario su `dettaglio` non è stato implementato: il modello `RilevazioneIncidente`
non ha un concetto di proprietario/autore (il campo `nominativo` è testo libero, nessun
`created_by`), quindi un gate per-owner richiederebbe refactor + cambio DB → fuori scope
(vedi Rischi residui).

---

## 4. Test aggiunti ed esiti

| Comando | Esito |
|---|---|
| `manage.py check --settings=config.settings.test` | ✅ System check identified no issues |
| `manage.py makemigrations --check --dry-run` | ✅ No changes detected |
| `test rilevazione_incidenti.tests timbri…HostAllowlistTests rentri.tests` | ✅ 24 test OK |
| `test core.tests tickets.tests admin_portale.tests` (baseline) | ✅ 235 test OK |
| `test … 6 moduli` (suite estesa) | 277 test — 3 fail + 1 error (tutti preesistenti `timbri`) |
| `acl_coverage_report --max-missing 0` | ❌ Fallita per gap preesistente (vedi §6) |
| `git diff --check` (file patch) | ✅ Nessun problema whitespace |

**Test nuovi:**

- `ExportPdfAuthorizationTests` (5): basic → 403, RSPP → 200, superuser → 200, `sp_id`
  mancante → 404, regressione 403/404 coerenti.
- `ReadViewsAuthGuardTests` + `ReadViewsAuthenticatedAccessTests` (M1).
- `TimbriDownloadImageHostAllowlistTests` (5): graph → `Authorization`, sharepoint →
  `Authorization`, host untrusted → no download, `sharepoint.com` solo in query →
  rifiutato, schema/host mancante → rifiutato.
- `RentriWriteAuthorizationTests` (8): create / modify / delete / import / sync gated,
  delete solo POST.

---

## 5. Failure preesistenti (non introdotte dalla patch)

Confermate identiche eseguendo `timbri.tests` sul codice pre-patch via `git stash` →
`FAILED (failures=3, errors=1)`:

- `TimbriViewTests.test_caporeparto_can_view_but_cannot_create` — 302 (redirect onboarding
  utente non-superuser senza `UserOnboarding`).
- `TimbriAnagraficaIntegrationTests.test_anagrafica_list_shows_timbri_link` — 302.
- `TimbriDownloadAuditTests.test_serve_timbri_image_denied_…` — 302.
- `TimbriViewTests.test_reset_table_deduplicates_uppercase_legacy_rows` — ERROR.

> **Nota:** una esecuzione della suite estesa ha mostrato 8 failure (vs 3) per flakiness
> preesistente di isolamento test tra app (tabella raw `anagrafica_dipendenti` / sqlite in
> `.tmp_tests`); `core + tickets + admin_portale` da soli sono 235 OK stabili.

---

## 6. acl_coverage_report

Fallita con **76 route applicative senza binding canonico**. Preesistente: il baseline
documentato in `CLAUDE.md` è `--max-missing 222`; la patch non aggiunge né rimuove URL. Come
da istruzioni, ACL non è stata modificata → patch separata di copertura ACL.

---

## 7. AUDIT EVIDENCE

### 7.1 Finding chiusi

| Finding | Severità | Stato | Patch | Test |
|---|---:|---|---|---|
| H1 — `export_pdf` IDOR/PII | High | Chiuso | Gate `superuser` / `_can_manage_rspp` / `_can_create` + `Http404` su risorsa mancante | `ExportPdfAuthorizationTests` (5) |
| M2 — `_download_image` SSRF / leak token | Medium | Chiuso | Helper `_is_graph_trusted_host` + allowlist host | `TimbriDownloadImageHostAllowlistTests` (5) |
| M3 — `rentri` write senza gate ruolo | Medium | Chiuso | `_can_manage_rentri` + `_require_rentri_manager` su 5 endpoint scrittura | `RentriWriteAuthorizationTests` (8) |
| M1 — viste lettura senza difesa in profondità | Medium | Chiuso parziale | `@login_required` su 9 viste | `ReadViewsAuthGuardTests`, `ReadViewsAuthenticatedAccessTests` |

### 7.2 File modificati

| File | Motivo security | Tipo modifica |
|---|---|---|
| `django_app/rilevazione_incidenti/views.py` | H1: gate ruolo + 404 reale; M1: `@login_required` | Modifica codice |
| `django_app/rilevazione_incidenti/tests.py` | Copertura test H1 + M1 | Modifica test |
| `django_app/timbri/views.py` | M2: allowlist host token Graph | Modifica codice |
| `django_app/timbri/tests.py` | Copertura test M2 | Modifica test |
| `django_app/rentri/views.py` | M3: gate ruolo scrittura | Modifica codice |
| `django_app/rentri/tests.py` | Copertura test M3 | Nuovo file test |
| `CHANGELOG.md` | Tracciabilità security | Modifica doc |

### 7.3 Comandi eseguiti

- `python manage.py check --settings=config.settings.test` → **OK** — System check
  identified no issues (0 silenced).
- `python manage.py makemigrations --check --dry-run --settings=config.settings.test` →
  **OK** — No changes detected (nessuna migrazione, coerente con il vincolo "no DB change").
- Test mirati `rilevazione_incidenti.tests` +
  `timbri.tests.TimbriDownloadImageHostAllowlistTests` + `rentri.tests` → **OK** —
  Ran 24 tests … OK.
- Test estesi `core.tests tickets.tests admin_portale.tests rilevazione_incidenti.tests
  timbri.tests rentri.tests` → Ran 277 tests — `FAILED (failures=3, errors=1)`: i 4 falli
  sono preesistenti in `timbri.tests` (confermato via `git stash` sul codice pre-patch:
  stesso `FAILED (failures=3, errors=1)`).
- Baseline `core.tests tickets.tests admin_portale.tests` → **OK** — Ran 235 tests … OK.
- `python manage.py acl_coverage_report --include-admin --format json --fail-on-missing
  --max-missing 0 --settings=config.settings.test` → **FALLITA**: ACL coverage check failed:
  76 route applicative senza binding canonico — gap preesistente (baseline progetto
  `--max-missing 222`), nessuna route aggiunta/rimossa dalla patch.
- `git diff --check` (file patch) → **OK**, nessun problema whitespace.
  (`CLAUDE.md:103 new blank line at EOF` è preesistente, file non parte di SEC-PREPROD-02.)
- `git status --short` → `M CHANGELOG.md`, `M django_app/rentri/views.py`,
  `M django_app/rilevazione_incidenti/tests.py`, `M django_app/rilevazione_incidenti/views.py`,
  `M django_app/timbri/tests.py`, `M django_app/timbri/views.py`,
  `?? django_app/rentri/tests.py`.

### 7.4 Evidenza remediation

#### H1 — `rilevazione_incidenti.export_pdf`

- **Prima:** nessun controllo; qualunque utente con accesso ACL al modulo scaricava il PDF
  (PII, descrizioni infortunio, 5WHY, note RSPP) di qualsiasi rilevazione via `sp_id`.
  Risorsa mancante → template `forbidden` con status 404 incoerente.
- **Dopo:** generazione consentita solo a superuser / preposti / RSPP; non autorizzato →
  403 reale; rilevazione inesistente → 404 reale (`Http404`).
- **Test:** `ExportPdfAuthorizationTests.test_basic_module_user_is_forbidden` (403),
  `test_rspp_user_is_allowed` / `test_superuser_is_allowed` (200),
  `test_missing_incident_returns_404…`, `test_denied_is_real_403_and_missing_is_real_404`.
- **Rischio residuo:** con whitelist `acl_preposti` vuota, `_can_create` resta aperto a
  tutti gli autenticati (comportamento documentato L3, fuori scope) — l'export PDF resta
  comunque non più debole del dettaglio.

#### M2 — `timbri._download_image`

- **Prima:** `requests.get(url, headers={Authorization: Bearer <graph_token>})` su URL
  preso dai campi della lista SharePoint; un URL verso host non Microsoft riceveva il
  bearer token Graph.
- **Dopo:** token e download solo verso host in allowlist Graph / SharePoint; URL non
  attendibili / malformati → `RuntimeError` senza alcuna richiesta HTTP.
- **Test:** `TimbriDownloadImageHostAllowlistTests` — `Authorization` presente per
  `graph.microsoft.com` / `*.sharepoint.com`; `attacker.local` e
  `attacker.local/?ref=sharepoint.com` non scaricati; schema/host invalidi rifiutati.
- **Rischio residuo:** nessuno per il vettore identificato; resta la fiducia implicita nei
  contenuti delle liste SharePoint configurate (sorgente amministrativa).

#### M3 — `rentri` CRUD

- **Prima:** creazione / modifica / eliminazione / import del registro rifiuti (dato a
  valenza legale) protetti solo da login + ACL di path, senza gate ruolo nel modulo.
- **Dopo:** scritture consentite solo a superuser / admin legacy; altri → `JsonResponse`
  403 senza alcuna modifica. `elimina` resta solo POST.
- **Test:** `RentriWriteAuthorizationTests` — basic user bloccato su
  create / modify / delete / import / sync (403, dato invariato), admin consentito, GET su
  `elimina` → 405.
- **Rischio residuo:** la lettura (`elenco`, `export_pdf`) resta secondo ACL di modulo —
  coerente con la richiesta.

#### M1 — viste lettura `rilevazione_incidenti`

- **Prima:** nessun `@login_required`, dipendenza esclusiva dal middleware ACL.
- **Dopo:** `@login_required` su tutte le viste principali (difesa in profondità).
- **Test:** `ReadViewsAuthGuardTests` (anonimo → redirect login),
  `ReadViewsAuthenticatedAccessTests` (accesso autenticato funzionante).
- **Rischio residuo:** nessun gate per-proprietario su `dettaglio` (vedi Rischi residui).

### 7.5 Rischi residui

| Rischio | Owner consigliato | Priorità | Scadenza | Accettabilità in produzione |
|---|---|---|---|---|
| ACL coverage: 76 route senza `RoutePermissionBinding` canonico (`acl_coverage_report --max-missing 0` fallisce) | Team ACL / Platform | Media | Prossima patch ACL pre-GA | Accettabile: baseline progetto è `--max-missing 222`, nessuna route nuova introdotta; il middleware ACL + fallback legacy resta attivo |
| M1 per-owner su `dettaglio` / `lista`: ogni utente con accesso al modulo vede tutte le rilevazioni (no concetto di proprietario nel modello) | Owner modulo Sicurezza | Bassa | Da decidere con business | *Needs manual decision*: implementare lo scoping richiederebbe refactor + nuovo campo `created_by` (cambio DB). Accettabile ora: H1 chiude l'esposizione PDF; la lista incidenti è plausibilmente a trasparenza di reparto |
| L1–L4 + bug `campaign_remove_document` | Team Security | Bassa | Patch successive (già pianificate) | Accettabile: esplicitamente esclusi dallo scope di questa patch |
| Flakiness isolamento test suite estesa (tabella raw `anagrafica_dipendenti`, sqlite in `.tmp_tests`) | Team QA | Bassa | Backlog QA | Accettabile: non di sicurezza; non blocca il deploy. *(Causa analizzata e mitigata in SEC-PREPROD-03.)* |
| 4 test preesistenti falliti in `timbri.tests` (redirect onboarding / dedup legacy) | Owner modulo Timbri | Bassa | Backlog | Accettabile: preesistenti, non legati a SEC-PREPROD-02 (confermato su codice pre-patch) |

---

## 8. Go / No-Go

**GO per i finding in scope:** H1, M2, M3 chiusi e testati; M1 chiuso come difesa in
profondità. Nessuna regressione introdotta (`check` OK, nessuna migrazione, baseline
`core / tickets / admin_portale` 235 OK, falli residui tutti preesistenti e confermati).

Resta **condizionato** — non bloccante per questa patch — il follow-up sulla copertura ACL
(76 route) e la decisione manuale sullo scoping per-proprietario di `rilevazione_incidenti`,
da indirizzare in patch dedicate prima della GA.

---

*Fine documento — SEC-PREPROD-02 Evidence Report. Pronto per conversione in PDF di audit.*
