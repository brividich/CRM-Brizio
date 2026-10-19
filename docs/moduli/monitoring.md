# `monitoring` — osservabilità interna

Area **Core** · URL `/monitoring/` · codice [`django_app/monitoring/`](../../django_app/monitoring/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Monitoring interno, issue tracking, alert email, segnalazioni utente, monitor automazioni

## Dettaglio

Superficie di monitoring del portale, issue tracking interno e segnalazioni utenti.

- **Issue tracking** interno per bug segnalati dagli utenti
- **Alert email** su eventi di sistema configurabili
- **Monitor automazioni** con health card della queue
- **Salute degli schedule** (`/admin-portale/monitoring/schedules/`, `monitoring/schedule_health.py`): per ogni job di `automazioni/schedules.py` ultimo run (riuscito/fallito, con l'errore), fallimenti nelle 24 h, prossimo run e stato (In regola, In ritardo, Ultimo run fallito, Non registrato, Mai eseguito, Disabilitato); *In ritardo* = prossimo run passato da più di metà cadenza (minimo 10 minuti). Banner in cima: cluster fermo (nessun job completato da 20 minuti) o numero di schedule da controllare.
- **Segnalazioni utente** dirette all'admin
- **Backup e ripristino** (`/admin-portale/monitoring/backup/`, solo amministratori): RPO, ultimo FULL, catena log, prova di ripristino con RTO, capacità DB, Recovery Kit, «Verifica ora», piano di ripristino scaricabile; check `backup_*`/`restore_drill`/`recovery_kit`/`db_capacity` in readyz (mai critical) e schedule `backup_health_alert`. Dettaglio: [docs/dr/BACKUP_MOTORE.md](../dr/BACKUP_MOTORE.md).
- **Esiti dei backup e prove di ripristino**: modelli `BackupRun` (full, log, files, host, retention, verifica, archivio audit) e `RestoreDrill` (migrazione `0003`), scritti dal motore di backup `core/backup_engine` ([docs/dr/BACKUP_MOTORE.md](../dr/BACKUP_MOTORE.md)).
- **Liveness/readiness probe** runtime (`/healthz`, `/readyz`) con check su DB, cache, Graph, LDAP, SMTP, queue automazioni e crescita dell'audit (`audit_growth`: warning oltre 500 MB/mese, fail sotto 60 giorni dalla saturazione del limite SQL Express, mai critical, memoizzato 1 h); risultato memoizzato in cache, IP allowlist via `HEALTHZ_ALLOWED_IPS`. Riusabili da `validate_deployment --with-integration` per coerenza tra deploy validation e runtime
- **Allarmi del server** (18/10/2026, `monitoring/infra_checks.py`): check `qcluster` (ultimo task completato, soglia `MONITORING_QCLUSTER_STALE_MINUTES` 40), `qcluster_coda` (OrmQ oltre `MONITORING_QUEUE_WARN` 50, task falliti 24 h), `disk_space` (dischi di log, media, archivi privati, staging backup; `MONITORING_DISK_WARN_PCT` 15 / `_FAIL_PCT` 5), `tls_cert` (certificato https di `SITE_URL`, `MONITORING_TLS_WARN_DAYS` 30 / `_FAIL_DAYS` 7, cache 6 h, catena non validata). Nel registro di `/readyz` e nella Centrale, sempre `critical=False`. Schedule `infra_health_alert` (30 min): Issue per WARN/FAIL (chiuse quando tornano OK), mail solo per i FAIL con dedup e quiet hours. Comando `infra_health_alert [--solo-mostra]`, registrabile in Utilità di pianificazione con `register-backup-tasks.ps1 -IncludeInfraAlert` (allarme anche a qcluster fermo).
- **Provenienza della build** nella Centrale di comando (`/admin-portale/monitoring/status/`): commit, branch, autore e data letti dal `BUILD_INFO.json` scritto nel pacchetto da `package-release.ps1`, con banner rosso se il codice in esecuzione non corrisponde a un commit pulito del branch di release. Manifest assente = "sviluppo — nessun pacchetto"
- CSS dedicato in `static/monitoring/css/monitoring.css` verificato in `collectstatic`
- **Controllo `graph_token` corretto** (19/10/2026): leggeva le credenziali solo dai settings Django e in produzione, dove stanno nel `.env`, risultava sempre «Credenziali Graph non configurate» (SKIPPED). Ora usa `core.m365_graph.credenziali()`, come il resto del portale.
- **Stato dei servizi Microsoft 365** (19/10/2026, check `m365_servizi` in `monitoring/infra_checks.py`): legge `admin/serviceAnnouncement/healthOverviews` (permesso Graph `ServiceHealth.Read.All`, cache 15 minuti) e va in WARN se Exchange Online, SharePoint Online, OneDrive, Teams, Entra, Intune, Defender XDR o la suite segnalano un disservizio in corso; mai FAIL e mai critical. È nel registro di `/readyz` e nella Centrale di comando, non negli allarmi email del server (`INFRA_CHECK_NAMES`).
