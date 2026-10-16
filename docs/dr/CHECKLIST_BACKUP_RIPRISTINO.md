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
- [ ] R0.2.7 `hub_db_tuning --query-store-max-mb 100 [--apply]` (dry-run di default)
- [ ] R0.2.8 Diagnostica `django_cache` nel doctor
- [x] R0.2 committato (`68ebe571`), 21 test verdi
- [~] R0.3 `audit_archive --plan / --run / --restore` (lotti per id, ≤1000 parametri, ripresa, archivio jsonl.gz + manifest) — codice scritto, test in corso
- [~] R0.4 Conservazione: classe A 60 mesi (`--category business`, soglia minima imposta), archivi 120 mesi (`--prune-archives`, mai senza manifest verificato) — task mensile/settimanale arriva con `register-backup-tasks.ps1` (R1), esito in `BackupRun` (R1)
- [ ] R0.5 Osservabilità: `check_audit_growth`, previsione saturazione
- [ ] R0.6 Test in `django_app.core`
- [ ] R0.7 Documentazione (`05_SECURITY_BOUNDARIES.md`, `docs/dr/AUDIT_POLICY.md`), CHANGELOG, guida admin, bump patch
- [ ] Commit, push, PR verso `main` (stop alla PR)
- [B] Deploy R0.2 in produzione
- [B] `audit_archive --plan` in prod → revisione → `audit_archive --run`

## S1 — SQL Server 2025 Express, istanza affiancata

- [ ] Verifica requisiti ufficiali Windows 11 / hardware
- [ ] `install-sql2025-instance.ps1` (WhatIf, collation identica, idempotente)
- [ ] Prova su TEST + verifica mssql-django/pyodbc/ODBC 18
- [ ] `move-db-to-instance.ps1` (WhatIf, rifiuta DLM/CNGAUGE)
- [ ] `docs/dr/SQL2025_MIGRAZIONE.md`
- [B] Migrazione PROD, recovery FULL, Query Store 100 MB

## R1 — Motore di backup verificabile

- [ ] Package `core/backup/` (config, sqlserver, transfer, files, host_manifest, manifest, retention, status)
- [ ] Modelli `BackupRun`, `RestoreDrill`
- [ ] Comandi `hub_backup`, `hub_backup_verify`, `hub_backup_doctor`, `hub_backup_set_recovery`; `backup_portale` wrapper
- [ ] `register-backup-tasks.ps1`; `backup-environment.ps1` senza `.env`
- [ ] Test R1

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
