# NOVICROM HUB — Runbook comandi & script

Foglio operativo di tutti gli script eseguibili (Django management commands + PowerShell di deploy/manutenzione), raggruppati per area con una riga di spiegazione ciascuno.

> Aggiornato: 2026-07-07 · App v1.3.0 · Non esaustivo al 100% sui tanti import una-tantum, ma copre tutto ciò che serve in esercizio.

## Legenda sicurezza

| Simbolo | Significato |
|---|---|
| 🟢 | Sola lettura / idempotente / sicuro da rilanciare |
| 🟡 | Scrive dati (spesso ha `--dry-run` di default e `--apply` per eseguire) |
| 🔴 | Tocca la produzione, è distruttivo o va usato con cautela |

## Convenzioni

- **Ambiente**: attiva prima il virtualenv.
  ```powershell
  cd "C:\Dev\Portale Novicrom"
  .\.venv\Scripts\Activate.ps1
  ```
- **Settings**: ogni comando accetta `--settings`:
  - `config.settings.dev` (SQLite/dev) · `config.settings.test` (per test/check) · `config.settings.prod` (SQL Server, **solo sull'host di prod**).
- **Manage.py**: i comandi si lanciano come `python django_app\manage.py <comando> [opzioni] --settings=config.settings.<env>`.
- **Prod**: gira sul branch `feature/skill-matrix-mod187` (host `pclogsys`, app-pool `CNOVICROM\hubcn`). Le variabili d'ambiente **persistenti** stanno in `config\.env` (NON in `current\django_app\.env`, che il deploy riscrive).
- **Molti reminder/digest** non si lanciano a mano: sono schedulati da django-q2 (vedi `setup_q_schedules` e `automazioni/schedules.py`). Qui sono elencati perché puoi lanciarli manualmente per test.

---

## 1 · Setup & avvio (dev)

| Cmd | | Cosa fa |
|---|---|---|
| `python -m venv .venv` | 🟢 | Crea il virtualenv |
| `.\.venv\Scripts\Activate.ps1` | 🟢 | Attiva il venv |
| `pip install -r django_app\requirements.txt` | 🟢 | Installa le dipendenze |
| `python django_app\manage.py migrate --settings=config.settings.dev` | 🟡 | Applica le migrazioni al DB dev |
| `python django_app\manage.py runserver --settings=config.settings.dev` | 🟢 | Avvia il server di sviluppo |
| `python django_app\manage.py createsuperuser --settings=config.settings.dev` | 🟡 | Crea un utente admin |
| `python django_app\manage.py collectstatic --settings=config.settings.prod` | 🟡 | Raccoglie gli static (deploy) |

## 2 · Test & quality gate

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py test <app> --keepdb --settings=config.settings.test` | 🟢 | Test di **una** app (preferito; `--keepdb` non ricrea il DB) |
| `python django_app\manage.py test --settings=config.settings.test` | 🟡 | **Intera** suite (lento — usare solo se richiesto) |
| `python django_app\manage.py check --settings=config.settings.test` | 🟢 | System check (config/modelli) |
| `python django_app\manage.py makemigrations --check --settings=config.settings.test` | 🟢 | Verifica che non manchino migrazioni |
| `python django_app\manage.py secret_hygiene_check` | 🟢 | Scansiona i file Git per segreti/path sensibili hardcoded |
| `python django_app\manage.py validate_deployment --format json --settings=config.settings.test` | 🟢 | Valida la configurazione di deploy |
| `.\tools\release_guard.ps1` | 🟢 | Gate pre-release (test seriali su SQLite, no `--parallel`) |

## 3 · ACL v2 (autorizzazioni)

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py bootstrap_acl_v2 --dry-run` | 🟢 | Anteprima del bootstrap permessi/binding canonici v2 |
| `python django_app\manage.py bootstrap_acl_v2` | 🟡 | Applica il bootstrap ACL v2 (idempotente) |
| `python django_app\manage.py acl_fallback_report --only-unbound` | 🟢 | Route senza binding canonico (debito ACL) |
| `python django_app\manage.py acl_coverage_report --max-missing 222` | 🟢 | Copertura ACL canonica sulle route registrate |
| `python django_app\manage.py acl_diagnose` | 🟢 | Diagnosi accesso route (canonico vs legacy) |
| `python django_app\manage.py acl_strict_readiness` | 🟢 | Verifica prontezza per `ACL_STRICT_CANONICAL=True` |
| `python django_app\manage.py acl_sync_legacy_grants` | 🟡 | Allinea i grant legacy ai permessi canonici |
| `python django_app\manage.py seed_acl_uat` | 🟡 | Seed ACL per ambiente di collaudo |

> **Nota**: in prod `ACL_STRICT_CANONICAL=True` dal 2026-06-05. Ogni route API va mappata in `core/middleware.py` `API_ACL_GATE_PATHS` verso una risorsa bound, altrimenti i non-superuser prendono 403.

## 4 · AI / RAG

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py index_sgi_documents` | 🟢 | Ricostruisce l'indice RAG + warm embeddings del corpus SGI |
| `python django_app\manage.py index_sgi_documents --json` | 🟢 | Come sopra, output JSON per monitoraggio |
| `python django_app\manage.py ai_eval --rag` | 🟢 | Valuta recall@k del RAG su golden query |
| `python django_app\manage.py warmup_ollama` | 🟢 | Pre-carica il modello chat Ollama (evita cold-start) |
| `python django_app\manage.py monitoring_ai_alert` | 🟢 | Health-check AI (Ollama/TEI) + alert email su degrado |
| `.\tools\ai_healthcheck_prod.ps1` | 🟢 | Healthcheck AI in prod (Ollama `10.0.0.34:11434`, TEI `:8081`) |
| `.\tools\ai_golive_prod.ps1` | 🔴 | Go-live/re-index RAG in prod (embeddings bge-m3 via TEI) |

> Topologia prod AI: app su `pclogsys`; Ollama + TEI su `pcgavancini` (`10.0.0.34`). `OLLAMA_RAG_SOURCE_PATHS` deve includere `django_app/ai_assistant/knowledge`.

## 5 · Presa Visione / corpus SGI (`procedure_refresh`)  ⟵ *il tema di stasera*

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py import_sgi_da_share` | 🟢 | **Dry-run**: scandisce la share SGI e mostra cosa importerebbe (usa `PROCEDURE_REFRESH_SGI_SHARE_ROOT`). **Il modo più veloce per capire se la cartella è configurata/raggiungibile**: se manca la root o non è raggiungibile, fallisce subito con messaggio chiaro |
| `python django_app\manage.py import_sgi_da_share --root "\\server\sistema gestione integrato"` | 🟢 | Dry-run puntando a una root esplicita |
| `python django_app\manage.py import_sgi_da_share --json` | 🟢 | Dry-run con output JSON |
| `python django_app\manage.py import_sgi_da_share --apply` | 🟡 | **Scrive**: registra documenti + revisioni correnti nel DB |
| `python django_app\manage.py import_sgi_da_share --solo-procedure` | 🟢/🟡 | Esclude la modulistica MOD.xxx (solo MT/MTSI/IDOR/…) |
| poi → `python django_app\manage.py index_sgi_documents` | 🟢 | Indicizza nel RAG i documenti appena importati |

**Sync automatica + log** (novità 2026-07-07 — richiede deploy del codice recente):
- Gira come task django-q2 `procedure_refresh.tasks.run_sgi_auto_sync` (schedule 03:00, dietro flag `pr_sgi_auto_sync_attivo`) e come watchdog `run_sgi_share_check` (documenti spariti).
- **Pulsante «Sincronizza ora»** in `/procedure-refresh/impostazioni/` → forza il task (anche a flag spento) e re-indicizza.
- **Log dei cambiamenti**: `/procedure-refresh/admin/sync-log/` (modello `SgiSyncLog`, migration `0007`). Si popola **solo se il sync applica qualcosa** (nuovo documento / revisione più recente / documento sparito). Se la share è già allineata al DB, il sync gira ma non scrive righe.
- **Diagnosi rapida shell** (mostra `skipped`/`reason` se la cartella non è impostata/raggiungibile):
  ```powershell
  python django_app\manage.py shell --settings=config.settings.prod
  >>> from procedure_refresh.tasks import run_sgi_auto_sync
  >>> run_sgi_auto_sync(force=True, reindex=False)   # {skipped, reason, created, updated, revisions}
  ```

> ⚠️ Perché in prod «il sync non ha registrato log»: (1) il codice del log è recente — **serve il deploy in prod + `migrate` (0007)**; (2) `PROCEDURE_REFRESH_SGI_SHARE_ROOT` deve stare in `config\.env` e la share dev'essere leggibile da `hubcn`; (3) se nulla è cambiato sulla share, «nessun log» è corretto.

## 6 · MOD.128 MPQ (processi qualificati)

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py import_mod128 --pdf <file>` | 🟢 | Dry-run: importa il MOD.128 dal PDF nei modelli MPQ |
| `python django_app\manage.py import_mod128 --pdf <file> --apply` | 🟡 | Scrive gli MPQ (idempotente) |
| `python django_app\manage.py import_mod128 --pdf <file> --esterni "Cognome Nome"` | 🟡 | Marca come qualificatore esterno una persona non a organico |
| `python django_app\manage.py mpq_propaga_timbri --dry-run` | 🟢 | Anteprima: sospende/riattiva i timbri collegati alle abilitazioni + notifica MSM |
| `python django_app\manage.py mpq_propaga_timbri` | 🟡 | Applica la propagazione stato abilitazioni → timbri |

> Il PDF del MOD.128 contiene **PII** e resta **fuori dal repo**.

## 7 · Skill Matrix MOD.187 (abilitazioni macchina)

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py skm_seed_catalogo` | 🟡 | Sincronizza il catalogo competenze dagli asset live |
| `python django_app\manage.py skm_asset_match_report` | 🟢 | Report match competenza↔macchina → asset (sola lettura) |
| `python django_app\manage.py skm_export_assets` | 🟢 | Export codici asset per validazione |
| `python django_app\manage.py import_skill_matrix --apply` | 🟡 | Import baseline abilitazioni (dry-run di default) |
| `python django_app\manage.py skm_continuita_sync` | 🟡 | Sospende/riattiva abilitazioni per continuità operativa |
| `.\tools\import_skill_matrix_prod.ps1` | 🔴 | Import Skill Matrix in prod |

## 8 · Reminder / digest / escalation (schedulati — lanciabili a mano per test)

| Cmd | | Cosa fa |
|---|---|---|
| `send_visite_expiry_reminders` | 🟡 | Digest visite mediche scadute/in scadenza |
| `send_visite_mediche_digest` | 🟡 | AU45 — digest mensile visite (HR + medico) |
| `send_contratti_expiry_reminders` | 🟡 | Digest contratti a termine/prova in scadenza |
| `send_training_expiry_reminders` | 🟡 | Reminder corsi formazione in scadenza |
| `send_formazione_audit_digest` | 🟡 | AU47 — digest trimestrale formazione (audit ISO) |
| `send_formazione_session_reminders` | 🟡 | Reminder + invito `.ics` sessioni formative |
| `send_idoneita_digest` | 🟡 | Digest idoneità mansione (RSPP/medico/HR) |
| `send_dpi_expiry_reminders` | 🟡 | Digest DPI scaduti/in scadenza |
| `send_caporeparto_morning_digest` | 🟡 | AU51 — digest mattutino caporeparto |
| `send_sla_reminders` | 🟡 | Reminder ticket con SLA scaduto |
| `run_tickets_escalation` | 🟡 | Escalation ticket urgenti non assegnati |
| `send_ticket_daily_digest` | 🟡 | AU52 — digest ticket assegnati in scadenza |
| `run_anomalie_escalation` | 🟡 | Escalation anomalie «in attesa» per OP |
| `flush_anomalie_notifications` | 🟡 | Mail di conferma aggiornamenti anomalie |
| `send_task_reminders` | 🟡 | Materializza i reminder task come Notifica portale |
| `send_maintenance_reminders` | 🟡 | Reminder scadenze manutenzione / OdL in ritardo |
| `check_rentri_scadenze` | 🟡 | Scadenze adempimenti RENTRI |
| `report_scadenze_settimanale` | 🟡 | Report settimanale visite + contratti (automazioni) |

*(lanciare come `python django_app\manage.py <cmd> --settings=config.settings.<env>`)*

## 9 · Automazioni & coda

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py setup_q_schedules` | 🟡 | Registra/aggiorna gli Schedule django-q2 |
| `python django_app\manage.py process_automation_queue` | 🟡 | Processa la coda SQL `automation_event_queue` |
| `python django_app\manage.py poll_approval_mailbox` | 🟡 | Legge la mailbox IMAP e processa le approvazioni |
| `python django_app\manage.py process_approval_mailbox` | 🟡 | Processa le risposte di approvazione (Graph) |
| `python django_app\manage.py apply_sql_triggers` | 🔴 | (Re)crea i trigger SQL Server (DROP+CREATE, idempotente) |
| `python django_app\manage.py cleanup_run_logs` | 🟡 | Elimina i RunLog oltre la retention (GDPR) |
| `.\deployment\start_qcluster.ps1` | 🔴 | Avvia il cluster django-q2 (prod: via Task Scheduler `QCluster_PROD`) |

> django-q2: usare schedule tipo **"I" (minuti)**, MAI **"S" (secondi)** (crashano).

## 10 · Import dati (una-tantum / periodici)

| Cmd | | Cosa fa |
|---|---|---|
| `import_dipendenti_xlsx` / `import_dipendenti_csv` | 🟡 | Anagrafica dipendenti da Excel/CSV |
| `import_cedolini` | 🟡 | Saldi ferie/ROL/ex-festività mensili da XLSX |
| `import_retribuzioni` | 🟡 | Storico voci paga da XLSX studio paghe |
| `importa_visite_mediche_xlsx` | 🟡 | Storico visite mediche da XLSX |
| `import_formazione_gestionale` | 🟡 | Dati formazione HR dagli Excel del gestionale |
| `import_asr` | 🟡 | Matrice formazione/abilitazioni ASR |
| `import_dpi_storico` | 🟡 | Storico DPI da Excel |
| `import_assets_excel` / `import_work_machines_excel` | 🟡 | Asset / macchine di lavoro da Excel |
| `import_carichi` | 🟡 | Edizioni `Carichi_macchina.xlsx` (idempotente) |
| `import_rentri_csv` | 🟡 | Registrazioni RENTRI da CSV |
| `importa_rilevazioni_csv` | 🟡 | Rilevazioni sicurezza da CSV (Power Apps) |
| `import_preposto_csv` | 🟡 | Diario preposto da CSV |
| `import_timbri_csv` / `import_timbri_da_share` | 🟡 | Timbri da CSV / immagini timbri dalla share |
| `.\tools\import_carichi_prod.ps1` | 🔴 | Import carichi macchina in prod |
| `.\tools\import_specifiche_prod.ps1` | 🔴 | Import specifiche in prod |

## 11 · Sincronizzazioni sorgenti esterne

| Cmd | | Cosa fa |
|---|---|---|
| `sync_ldap_users` | 🟡 | Importa utenti da LDAP/AD → legacy + auth_user + gruppi |
| `sync_assenze_sharepoint` | 🟡 | Assenze da SharePoint → DB |
| `sync_asset_documents_from_sharepoint` | 🟡 | Documenti asset da SharePoint |
| `assets_ensure_sharepoint_metadata` | 🟡 | Cartelle asset su SharePoint + colonne metadato |
| `assets_ensure_public_share_links` | 🟡 | Link pubblici Graph read-only cartelle asset |
| `reconcile_usernames` | 🟡 | Allinea `User.username` all'`aliasusername` anagrafica |
| `sync_reparto_capo_mapping` | 🟡 | Allinea mapping reparto↔caporeparto |

## 12 · Manutenzione / GDPR / sicurezza

| Cmd | | Cosa fa |
|---|---|---|
| `python django_app\manage.py backup_portale` | 🟡 | Backup DB + config + file del portale |
| `python django_app\manage.py media_audit` | 🟢 | Segnala file sensibili in `MEDIA_ROOT` (servito senza auth) |
| `python django_app\manage.py cleanup_expired_documents` | 🔴 | Retention GDPR dei documenti dipendente (cleanup) |
| `python django_app\manage.py encrypt_existing_documents` | 🔴 | Cifra at-rest i file privati esistenti (una-tantum) |
| `python django_app\manage.py ensure_legacy_schema` | 🔴 | Crea/riallinea le tabelle legacy su SQL Server |
| `python django_app\manage.py cleanup_run_logs` | 🟡 | Retention RunLog automazioni |
| `python django_app\manage.py report_reparti_orfani` | 🟢 | Elenca i dipendenti con reparto legacy "orfano" (cancellato dal catalogo `Reparto`) |
| `python django_app\manage.py report_reparti_orfani --reassign "VECCHIO=NUOVO"` | 🟢 | Anteprima dry-run di una rimappatura reparto |
| `python django_app\manage.py report_reparti_orfani --reassign "VECCHIO=NUOVO" --apply --eseguito-da <user>` | 🟡 | Applica la rimappatura (storicizza + risincronizza area/caporeparto) |

## 13 · Deploy & Release (PowerShell, host di prod)

Ordine tipico di un rilascio (parametri esatti nell'header di ciascuno script sotto `deployment\scripts\`):

| Script | | Cosa fa |
|---|---|---|
| `.\tools\release_guard.ps1` | 🟢 | Gate: test seriali + check prima di impacchettare |
| `deployment\scripts\package-release.ps1` | 🟡 | Crea lo zip di release (**allowlist**: niente dati sensibili) |
| `deployment\scripts\backup-environment.ps1` | 🟡 | Backup dell'ambiente prima del deploy |
| `deployment\scripts\deploy-release.ps1` | 🔴 | Deploy della release (copia `current`, `migrate`, static, IIS) |
| `deployment\scripts\activate-release.ps1` | 🔴 | Attiva la release copiata (switch `current`) |
| `deployment\scripts\smoke-test.ps1` | 🟢 | Smoke test post-deploy (usa `-SkipSmokeTest` se punta a localhost e prod è host-header) |
| `deployment\scripts\rollback-release.ps1` | 🔴 | Rollback alla release precedente |
| `deployment\scripts\configure-iis-site.ps1` | 🔴 | (Ri)configura il sito IIS |
| `deployment\scripts\secure-env-acl.ps1` | 🔴 | ACL sul file `.env` (permessi ristretti) |
| `deployment\scripts\patch-release.ps1` | 🔴 | Patch mirata di una release già attiva |

> **Attenzioni deploy** (vissute sul campo): il `migrate` dev'essere **globale**, non selettivo dal MODULE_REGISTRY (altrimenti tabelle mancanti → 500). Modificare **solo** `config\.env` (persistente), non `current\…\.env`. Gli static IIS richiedono `IIS_IUSRS`+`IUSR` con `RX` ereditari. Non rimuovere l'identità app-pool `hubcn`.

## 14 · Utility varie

| Cmd | | Cosa fa |
|---|---|---|
| `.\tools\update-deps.ps1` | 🟢 | Aggiorna/compila le dipendenze (`requirements`) |
| `.\tools\install-git-hooks.ps1` | 🟢 | Installa gli hook Git del repo |
| `.\tools\build_anomalie_ui.ps1` | 🟡 | Build della UI React del modulo anomalie |
| `.\tools\check_migra_formazione.ps1` | 🟢 | Verifica la migrazione formazione DEV→PROD |
| `python django_app\manage.py deduplicate_nav` | 🟡 | Deduplica le voci del navigation registry |
| `python django_app\manage.py monitoring_healthcheck` | 🟢 | Health check del modulo monitoring |

---

### Come scoprire le opzioni di un comando
Ogni management command documenta le sue opzioni:
```powershell
python django_app\manage.py <comando> --help --settings=config.settings.dev
```
E la lista completa (tutti i 143 comandi disponibili):
```powershell
python django_app\manage.py help --settings=config.settings.dev
```
