# Procedure Refresh v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completare il ciclo di vita ISO 9001/EN 9100 del modulo `procedure_refresh`: motore scadenze/solleciti, sync SGI automatica, segnalazioni di modifica tracciate, ACL v2 e pulizia UX.

**Architecture:** Tutto dentro `django_app/procedure_refresh` con tocchi mirati a `automazioni/schedules.py` (2 schedule nuovi) e `core/middleware.py` (1 riga in `API_ACL_GATE_PATHS`). Nessuna nuova dipendenza. Pattern riusati: `tickets/escalation_config.py` per la config SiteConfig, `core.email_utils.send_hub_mail` per le mail, `core.notifiche.invia_notifica` per le notifiche in-app, `core.acl_v2.check_acl_access_v2` per il check canonico.

**Tech Stack:** Django 5.2, django-q2 (CRON schedules, mai tipo "S"), SQL Server/SQLite, SSR + HTMX-less JS minimale.

**Spec:** `docs/superpowers/specs/2026-07-06-procedure-refresh-v2-design.md`

## Global Constraints

- Test scoped: `python django_app\manage.py test django_app.procedure_refresh --keepdb --settings=config.settings.test` (mai full suite).
- Mail SEMPRE su `email_notifica` risolta dall'anagrafica, mai il campo `email` legacy (è il login).
- Flag nuovi default-off (`pr_reminder_attivo=False`, `pr_sgi_auto_sync_attivo=False`).
- Un commit per fase, messaggi `feat(procedure_refresh): …` / `fix(procedure_refresh): …`; stage SOLO i file propri (worktree condiviso).
- CHANGELOG.md/README.md aggiornati per fase; version bump (docs/ai/06) a fine lavoro.
- Niente mail automatica all'assegnazione (decisione: la manda il supporto IT).
- Le segnalazioni di modifica non si cancellano mai; solo cambi stato loggati con `log_action`.

---

### Task 0: Bugfix `campaign_remove_document` + import morto

**Files:**
- Modify: `django_app/procedure_refresh/views.py:46` (togli import UtenteLegacy inutilizzato), `views.py:929` (`campaign_id=campaign.pk` → `campaign_id=pk`)
- Test: `django_app/procedure_refresh/tests.py`

**Steps:**
- [ ] Test di regressione `test_campaign_remove_document` (manager rimuove doc da campagna → 302, record eliminato, nessun 500). Run → FAIL (NameError).
- [ ] Fix (`campaign_id=pk`), togli `from core.legacy_models import UtenteLegacy` da `_is_manager`. Run → PASS.
- [ ] Commit `fix(procedure_refresh): 500 NameError su rimozione documento da campagna`.

### Task A1: `reminder_config.py`

**Files:**
- Create: `django_app/procedure_refresh/reminder_config.py`
- Test: `tests.py::ReminderConfigTests`

**Produces:** `get_reminder_config() -> dict` con chiavi `attivo: bool`, `pre_giorni: list[int]`, `post_cadenza_giorni: int`, `digest_giorno: str` (`""|lun..dom`), `digest_destinatari: list[str]`; `save_reminder_config(*, attivo, pre_giorni, post_cadenza_giorni, digest_giorno, digest_destinatari) -> bool`.

Pattern identico a `tickets/escalation_config.py` (SiteConfig.get/set). Chiavi: `pr_reminder_attivo` (default "0"), `pr_reminder_pre_giorni` ("7,2", clamp 0-60, max 5 soglie), `pr_reminder_post_cadenza_giorni` ("7", clamp 1-60), `pr_reminder_digest_giorno` ("lun", vuoto=off), `pr_reminder_digest_destinatari` (CSV email).

- [ ] Test parsing/default/clamp → FAIL; implementa; PASS; (commit con A3).

### Task A2: `ReadEventType.OVERDUE_MARKED`

- Modify: `models.py` — aggiungi `OVERDUE_MARKED = "overdue_marked", "Marcata scaduta"` a `ReadEventType`.
- [ ] `makemigrations procedure_refresh` (AlterField choices) + test scelta presente.

### Task A3: task `run_assignment_lifecycle`

**Files:**
- Modify: `django_app/procedure_refresh/tasks.py`, `django_app/automazioni/schedules.py` (CRON `45 6 * * *`)
- Test: `tests.py::AssignmentLifecycleTests`

**Produces:** `run_assignment_lifecycle(**kwargs) -> dict` fail-safe con `{"ok", "overdue_marked", "pre_sent", "post_sent", "digest_sent"}`.

Logica:
1. **OVERDUE (sempre, anche con attivo=False):** assegnazioni `assigned|opened`, campagna `published`, `due_date < oggi` → `status=overdue` + `ProcedureReadEvent(OVERDUE_MARKED)`.
2. **Pre-scadenza (se attivo):** pendenti con `due_date - oggi ∈ pre_giorni`; dedup: nessun invio se esiste `REMINDER_SENT` con `meta_json` contenente `"kind": "pre<N>"` per quell'assegnazione. Mail `send_hub_mail` a `email_notifica` + `invia_notifica`.
3. **Post-scadenza (se attivo):** `overdue`; dedup: nessun `REMINDER_SENT` kind `post` più recente di `post_cadenza_giorni`.
4. **Digest gestore (se attivo e oggi==digest_giorno):** una mail a `digest_destinatari` con elenco inadempienti per campagna/reparto (riusa `_user_department_map`); dedup per giorno (kind `digest` su un evento della prima assegnazione o SiteConfig `pr_reminder_digest_last`).

Helper `_notification_email_map(users) -> dict[int, str]`: mappa `user.pk → email_notifica` via `core.models.Profile` (`user_id→legacy_user_id`) e `core.legacy_models.AnagraficaDipendente` (`utente_id`, campo `email_notifica`); fallback stringa vuota (niente mail, resta la Notifica in-app).

- [ ] Test (email backend locmem, `django.core.mail.outbox`): marcatura overdue con evento; attivo=False → 0 mail ma overdue marcati; pre-soglia inviata una sola volta su doppio run; post rispettoso della cadenza; digest solo nel giorno giusto. TDD rosso→verde.
- [ ] Schedule in `automazioni/schedules.py` (commento + CRON, `repeats: -1`).
- [ ] Commit `feat(procedure_refresh): motore scadenze e solleciti configurabili (OVERDUE + reminder + digest)`.

### Task A4: Notifica in-app all'assegnazione + "Copia destinatari"

**Files:** `views.py::assign_users`, `views.py::campaign_detail`, `templates/.../campaign_detail.html`; test `AssignUsersNotificaTests`.

- [ ] `assign_users`: dopo il loop, per ogni utente con assegnazioni create → `invia_notifica(legacy_user_id, "generico", f"Ti sono stati assegnati N documenti in presa visione (campagna X, scadenza gg/mm/aaaa).", url_azione="/procedure-refresh/")`. Legacy id via Profile map (riusa `_notification_email_map`-style lookup). Una notifica per utente per azione.
- [ ] `campaign_detail`: context `recipients_clipboard` = righe `Nome Cognome <email_notifica>` degli assegnatari pendenti + lista `senza_email`; template: bottone "Copia elenco destinatari" (navigator.clipboard.writeText su textarea nascosta) + avviso "N utenti senza email di notifica".
- [ ] Test: assign crea Notifica (1 per utente); context contiene recipients. Commit `feat(procedure_refresh): notifica in-app all'assegnazione + copia elenco destinatari`.

### Task A5: Card impostazioni solleciti in dashboard admin

**Files:** `views.py::admin_dashboard` (branch POST `save_reminder_config`), `templates/.../admin_dashboard.html`; test.

- [ ] POST con hidden `save_reminder_config=1` → `save_reminder_config(...)` + `log_action` + redirect. GET: context `reminder_cfg`. Card con toggle/inputs (stile card branding esistente).
- [ ] Test POST salva chiavi SiteConfig. Commit `feat(procedure_refresh): impostazioni solleciti da dashboard admin`.

### Task B1: estrazione `upsert_candidate` + perimetro sicuro

**Files:** `management/commands/import_sgi_da_share.py`; test `AutoSyncSafeSubsetTests`.

**Produces:** `upsert_candidate(info: dict) -> tuple[str, bool]` (modulare, `Command._upsert` la richiama); `filter_auto_safe(candidates: list[dict]) -> tuple[list[dict], list[dict]]` — safe se `not fallback` E (codice nuovo O doc interamente figlio dell'import: tutte revisioni `fileserver` + `requires_acknowledgement=False` + zero assegnazioni su ogni revisione).

- [ ] Test filter_auto_safe (nuovo→safe; doc con revisione sharepoint→escluso; con assegnazione→escluso; requires_ack=True→escluso; fallback→escluso). TDD. (commit con B2)

### Task B2: task `run_sgi_auto_sync` + schedule 03:00

**Files:** `tasks.py`, `automazioni/schedules.py` (CRON `0 3 * * *`); test.

**Produces:** `run_sgi_auto_sync(force: bool = False, reindex: bool = False, **kwargs) -> dict` con `{"ok","skipped","created","updated","revisions","excluded"}`. Guard: se non `force` e SiteConfig `pr_sgi_auto_sync_attivo`≠"1" → skipped. Scan (`scan_share_candidates`), `filter_auto_safe`, upsert dei safe, esito JSON in SiteConfig `pr_sgi_last_sync` (timestamp ISO + contatori). Se `reindex=True` e cambi>0 → `async_task("ai_assistant.tasks.run_index_sgi_documents")` (import lazy, try/except fail-safe). Notturno: `reindex=False` (ci pensa lo schedule 03:30).

- [ ] Test con share fittizia in tmpdir (`override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=...)`, PDF vuoti nominati bene): flag off→skipped; flag on→crea documenti; doc ibrido non toccato; `pr_sgi_last_sync` scritto. Commit `feat(procedure_refresh): sync SGI automatica notturna (perimetro sicuro) dietro flag`.

### Task B3: pulsante "Sincronizza ora" in dashboard

**Files:** `urls.py` (`admin/sgi-sync/` → `sgi_sync_now`), `views.py`, `admin_dashboard.html`, `acl_bootstrap.py` (risorsa `pr_sgi_sync`); test.

- [ ] View `@require_POST sgi_sync_now`: manager check → `async_task("procedure_refresh.tasks.run_sgi_auto_sync", force=True, reindex=True)` + `log_action` + message "Sincronizzazione avviata" + redirect dashboard. Card dashboard mostra `pr_sgi_last_sync` (parse JSON) + stato flag + toggle flag (POST `save_sgi_auto_sync`).
- [ ] Test con `mock.patch("procedure_refresh.views.async_task")`. Commit `feat(procedure_refresh): pulsante Sincronizza ora + toggle auto-sync in dashboard`.

### Task B4: watchdog — documenti spariti dalla share

**Files:** `import_sgi_da_share.py::detect_share_drift` (aggiungi chiave `missing`), `tasks.py::run_sgi_share_check` (Issue include missing; se auto-sync attivo il messaggio parla di "anomalie residue"); test.

- [ ] `missing`: doc attivi con revisione corrente `fileserver` il cui `source_path` non esiste più sotto root o matcha `_SUPERATO_RE`. Solo notifica, mai disattivazione. Test con tmpdir. Commit `feat(procedure_refresh): watchdog rileva documenti SGI spariti dalla share`.

### Task C1: modello `ProcedureChangeRequest`

**Files:** `models.py`, `admin.py`, migrazione; test.

Campi (dalla spec): `document` FK PROTECT related_name `change_requests`; `revision` FK PROTECT null/blank; `assignment` FK SET_NULL null/blank; `created_by` FK SET_NULL null; `testo` TextField; `status` choices `ChangeRequestStatus` (APERTA="aperta" default, IN_CARICO="in_carico", RECEPITA="recepita", RESPINTA="respinta"); `risposta_gestore` TextField blank; `gestita_da` FK SET_NULL null related_name `pr_change_requests_gestite`; `gestita_il` DateTime null; `recepita_in_revisione` FK SET_NULL null related_name `+`; timestamps. Meta: ordering `-created_at`, index `(document, status)`.

- [ ] Test creazione/default/str. Commit con C2.

### Task C2: segnalazione dal dettaglio assegnazione

**Files:** `views.py::assignment_detail` (branch POST `submit_change_request`), `assignment_detail.html`; test.

- [ ] POST `submit_change_request` con `change_text` non vuoto → crea CR (document=rev.document, revision, assignment, created_by=request.user), `log_action("segnalazione_modifica", ...)`, message, redirect PRG. Template: sezione "Proponi modifiche a questo documento" (textarea) + elenco proprie segnalazioni con badge stato. Test: crea CR; testo vuoto → errore. Commit `feat(procedure_refresh): segnalazioni di modifica documento (proposta dal lettore)`.

### Task C3: gestione segnalazioni lato gestore

**Files:** `urls.py` (`admin/segnalazioni/` list + `admin/segnalazioni/<pk>/stato/` POST), `views.py` (`change_request_list`, `change_request_set_status`), nuovo template `pages/change_request_list.html`, `acl_bootstrap.py` (+ `pr_change_requests`, bump `_BOOTSTRAP_CACHE_KEY` a v3), `admin_dashboard.html` (KPI aperte), `document_list` (badge count via annotate); test.

- [ ] List filtrabile `?doc=&stato=`; azione POST cambio stato (valida transizioni: da aperta/in_carico a qualsiasi; `recepita` accetta `recepita_in_revisione` opzionale tra le revisioni del documento) + `risposta_gestore` + `gestita_da/gestita_il` + `log_action`. Mai delete.
- [ ] Test: manager cambia stato con risposta; non-manager 302; KPI conta aperte. Commit `feat(procedure_refresh): gestione segnalazioni modifica con stati e chiusura ciclo`.

### Task D1: check canonico ACL v2 + API gate

**Files:** `views.py` (`_can_manage`), `core/middleware.py` (`API_ACL_GATE_PATHS`); test.

- [ ] `_can_manage(request)`: `True` se `_is_manager(request)` (fallback legacy: superuser/admin) OPPURE `check_acl_access_v2(path="/procedure-refresh/impostazioni/", legacy_user=get_legacy_user(request.user), django_user=request.user, request=request)`. Sostituisci tutte le chiamate `_is_manager(` nelle view admin con `_can_manage(`. (`_is_manager` resta come fallback interno.)
- [ ] `API_ACL_GATE_PATHS["/procedure-refresh/api/"] = "/procedure-refresh/impostazioni/"` con commento.
- [ ] Test: utente semplice → redirect; superuser → 200; `mock.patch("procedure_refresh.views.check_acl_access_v2", return_value=True)` → 200 per utente semplice. Verifica finale: `acl_fallback_report --only-unbound` invariato o migliorato. Commit `feat(procedure_refresh): gate ACL v2 canonico per area gestione + API gate path`.

### Task D2: tab Presa visione / Corpus AI + picker filtrato

**Files:** `views.py::document_list` (param `?vista=pv|rag` default `pv`, `?q=` su code/title), `document_list.html` (tab + search), `views.py::campaign_detail` (`available_revisions` filtrato `document__requires_acknowledgement=True, is_current=True`), `campaign_detail.html`; test.

- [ ] Test: doc RAG-only fuori dal picker e fuori dalla vista default; ricerca per codice. Commit `feat(procedure_refresh): separazione presa visione / corpus AI in elenchi e picker campagna`.

### Task finale: documentazione e versione

- [ ] CHANGELOG.md `[Unreleased]` (tutte le fasi, elenco file); README.md sezione modulo (nuove funzioni: solleciti, sync SGI, segnalazioni); version bump secondo `docs/ai/06_TESTING_AND_QUALITY_GATES.md`.
- [ ] Run test scoped finale + `manage.py check --settings=config.settings.test`.

## Self-review

- Copertura spec: Fase 0→Task 0; A→A1-A5; B→B1-B4; C→C1-C3; D→D1-D2; docs→finale. ✔
- Nessun placeholder; firme coerenti (`run_assignment_lifecycle`, `run_sgi_auto_sync`, `filter_auto_safe`, `_can_manage`). ✔
- Vincoli globali in testa, default-off, email_notifica. ✔
