# Checklist — NOVICROM HUB Recovery (BUILD_SPEC backup e ripristino)

Aggiornata a ogni avanzamento. Legenda: [x] fatto · [~] in corso · [ ] da fare · [B] azione riservata a Brizio (Claude prepara, non esegue).

Ordine: R0 → R0.3 plan/revisione/run → S1 → recovery FULL + log orario → R1 → R2 → R3 → R4.

## R0 — Governo dell'audit automatico (`fix/audit-policy-crescita`)

- [x] Worktree `C:\Dev\pn-audit-policy` da `origin/main` (7307b7f5)
- [x] R0.0 Ricognizione codice (`core/audit_signals.py`, `core/apps.py`, modelli classi B/C/D) — tutti i 19 modelli dello spec esistono
- [x] R0.1 Classificazione A/B/C/D verificata sui modelli reali (DispositivoSNMP: aggiunti `sys_name`, `sys_description`, `sys_object_id`, riscritti a ogni poll)
- [x] R0.2.1 `core/audit_policy.py` + system check `core.W002` (chiave errata) / `core.W003` (campo ignorato inesistente)
- [x] R0.2.2 Collegamento segnali per-modello (`connect_audit_signals`, `dispatch_uid`) in `core/apps.py`
- [x] R0.2.3 Niente righe per update senza modifiche reali (`auto_now` + campi ignorati → `campi_tecnici_cambiati`)
- [x] R0.2.4 Troncamento valori > 500 caratteri con impronta; binari mai serializzati; classe C solo nomi campi
- [x] R0.2.5 `pre_save` leggero per metadata_only (solo impronte, niente contenuti in memoria)
- [x] R0.2.6 Verifica viste audit per modulo: tutte filtrano moduli di business (`notizie`, `tasks`, `assets`, `assenze`, `anomalie`, `timbri`, `anagrafica`, `permessi`) o sono generiche; nessuna dipende da righe `auto_*` di B/C; `storico_oggetto` usa `oggetto_tipo/id`, mai valorizzati dall'audit automatico
- [x] R0.2.7 `hub_db_tuning --query-store-max-mb 100 [--apply]` (dry-run di default; no-op fuori da SQL Server)
- [x] R0.2.8 Diagnostica `django_cache` nel doctor (`hub_backup_doctor` versione R0: capacità, top tabelle, audit, cache)
- [x] R0.2 committato (`68ebe571`), 21 test verdi
- [x] R0.3 `audit_archive --plan / --run / --restore` (lotti per id, ≤1000 parametri, ripresa, archivio jsonl.gz + manifest) — commit `5bc24a14`, 13 test verdi
- [x] R0.4 Conservazione: classe A 60 mesi (`--category business`, soglia minima imposta), archivi 120 mesi (`--prune-archives`, mai senza manifest verificato) — task mensile/settimanale arriva con `register-backup-tasks.ps1` (R1), esito in `BackupRun` (R1)
- [x] R0.5 Osservabilità: check `audit_growth` (monitoring), previsione saturazione, top modelli con classe (pagina R2 la riuserà)
- [x] R0.6 Test: 49 nuovi in `django_app.core` verdi; regressione su core, monitoring, tickets, automazioni, security, contatori: 2657 test, 3 falliti **preesistenti** (falliscono identici su `origin/main` nello stesso ambiente: `core.test_acl_cleanup_command…test_sync_legacy_riallinea…`, `core.test_security_audit_residui…test_denied_when_workorder_page_denied`, `security.tests.test_asset_overview…test_projection_query_count…`)
- [x] R0.7 Documentazione (`05_SECURITY_BOUNDARIES.md`, `docs/dr/AUDIT_POLICY.md`, `docs/moduli/core.md`, `monitoring.md`), CHANGELOG, guida admin Centro guide. Bump: non fatto (pratica attuale: `[Unreleased]` + bump al rilascio; funzione solo admin/terminale). `schema_db.py`: descrizione di `core` già generica, invariata
- [x] Commit e push su `fix/audit-policy-crescita` (`68ebe571`, `5bc24a14`, `8aa653cb`, fix `4264e4bb`: Query Store spento non si accende senza `--enable`; doctor distingue le azioni esplicite)
- [x] Verifica su SQL Server reale (copia del DB di sviluppo su SQL 2025): doctor, `audit_archive --plan` → `--run` (1.091 righe tecniche archiviate in 17 parti e cancellate, classe A invariata 668/668) → `--plan` a zero → `--restore` in tabella separata
- [ ] PR verso `main`: da aprire a mano (`gh` non autenticato) — https://github.com/brividich/CRM-Brizio/compare/main...fix/audit-policy-crescita?expand=1 ; testo pronto nello scratchpad `pr_r0.md`
- [B] Deploy R0.2 in produzione
- [B] `audit_archive --plan` in prod → revisione → `audit_archive --run`

## S1 — SQL Server 2025 Express, istanza affiancata

- [x] Worktree `C:\Dev\pn-sql2025`, branch `feature/sql2025-istanza` (sopra `fix/audit-policy-crescita`)
- [x] Requisiti ufficiali (Microsoft Learn): Windows 11 Pro supportato per Express; .NET 4.7.2; 6 GB liberi; Express 2025 = 50 GB/DB, 4 core, buffer pool 1.410 MB
- [x] Driver: mssql-django supporta SQL 2025 dalla 1.7 (repo: 1.7.4); **la macchina di sviluppo gira già su SQL 2025 Express 17.0.1000.7**
- [x] `install-sql2025-instance.ps1` (WhatIf, collation e autenticazione dall'istanza attuale, porta fissa, idempotente) — dry-run verificato su PS 5.1 e 7
- [x] `move-db-to-instance.ps1` (WhatIf, rifiuta sistema e DLM/CNGAUGE, mai REPLACE, riferimenti cross-DB, origine OFFLINE, rollback automatico in manutenzione, idempotente) — giro reale su copia del DB di sviluppo: 464 MB in 28 s, Django check pulito, 0 migrazioni mancanti
- [x] `hub_db_tuning --compatibility-level N [--apply]` (comando dedicato per il 170 dopo 2 settimane)
- [x] Test `deployment/tests/test-sql-scripts.ps1` (guardie + giro completo su DB sintetico), verdi su PS 5.1 e 7; test Django 44 verdi
- [x] `docs/dr/SQL2025_MIGRAZIONE.md` (requisiti, passi, tempi, rollback)
- [x] Commit e push su `feature/sql2025-istanza` (`5fead6bd`)
- [ ] PR: da aprire a mano dopo quella di R0 (oppure con base `fix/audit-policy-crescita`) — https://github.com/brividich/CRM-Brizio/compare/main...feature/sql2025-istanza?expand=1 ; testo nello scratchpad `pr_s1.md`
- [B] Installazione istanza `HUB2025` sul PC di produzione
- [B] Prova su TEST (`move-db-to-instance.ps1 -Environment test …`) e tempi reali
- [B] Migrazione PROD, poi recovery FULL + log orario (R1), Query Store 100 MB, compat 170 dopo 2 settimane

## R1 — Motore di backup verificabile

- [x] Worktree `C:\Dev\pn-backup`, branch `feature/backup-motore` (sopra `feature/sql2025-istanza`)
- [x] Package `core/backup_engine/` (config, sqlserver, transfer, files, host_manifest, manifest + schema JSON v1, retention, status, doctor, engine) — nome `backup_engine` perché `.gitignore` esclude le cartelle `backup/`
- [x] Modelli `BackupRun`, `RestoreDrill` (migrazione `monitoring 0003`, nessuna collisione con altri branch)
- [x] Comandi `hub_backup` (full/log/files/host/retention/all, exit 0/1/2), `hub_backup_verify`, `hub_backup_set_recovery`, `hub_backup_doctor` esteso; `backup_portale` wrapper compatibile
- [x] `BACKUP_EXTRA_DATABASES` (DLM/CNGAUGE), `HUB_PUBLIC_HOSTNAME`/`HUB_ALT_HOSTNAMES` con controlli ALLOWED_HOSTS/CSRF/DNS/SPN
- [x] `register-backup-tasks.ps1` (dry-run verificato su PS 5.1); `backup-environment.ps1` senza `.env` + `-UseHubBackup`
- [x] Test: 38 nuovi (sqlcmd simulato, copia verificata, file incrementali, GFS, manifest senza segreti, end-to-end SQLite, riconciliazione); regressione core+monitoring+hub_tools 968 test, solo i 2 preesistenti
- [x] Prova reale su SQL Server 2025 (copia del DB di sviluppo, poi eliminata): FULL 280 MB verificato, catena log dopo `hub_backup_set_recovery --full --confirm`, manomissione → FAILED, retention, wrapper; corretto un difetto della retention emerso dalla prova
- [x] `docs/dr/BACKUP_MOTORE.md`, CHANGELOG, `docs/moduli/core.md`, `monitoring.md`, guide Centro guide (amministrazione, emergenza), `schema_db.py` (share dei backup)
- [x] Commit e push su `feature/backup-motore` (`1bb94717`)
- [ ] PR: da aprire a mano dopo R0 e S1 (oppure con base `feature/sql2025-istanza`) — https://github.com/brividich/CRM-Brizio/compare/main...feature/backup-motore?expand=1 ; testo nello scratchpad `pr_r1.md`
- [B] `.env` prod: `BACKUP_TARGET` (share NAS), `BACKUP_ENV_DIR`, nomi del portale → `hub_backup_doctor` → `hub_backup --type all` → `register-backup-tasks.ps1`

## R2 — Osservabilità e drill

- [ ] Check health backup/log/drill/kit/capacità
- [ ] Pagina "Backup e ripristino" nella Centrale di comando
- [ ] `hub_restore_drill`
- [ ] `HUB_TOOLS_DB_RESTORE_ENABLED=False` (restore in-app disattivato)
- [ ] Test R2

## R3 — Recovery Kit e restore headless

- [ ] `hub_recovery_kit export/verify/import`
- [ ] `hub_restore_plan`
- [ ] `restore-host.ps1` (fasi 0–11, ripresa, WhatIf) + `prereqs.lock.json`
- [ ] Test Pester + Python

## R4 — Wizard "Ripristina da backup" + runbook

- [ ] Modalità nel SetupWizard + rigenerazione exe
- [ ] `RUNBOOK_RIPRISTINO.md`, `DR_PLAN.md`, `RECOVERY_KIT.md`
