# Retention dei dati personali — code, monitoring, log AI

Documento richiesto dall'audit sicurezza del 09/10/2026 (Fase 3). Elenca dove il portale conserva dati personali **fuori dai moduli di dominio** e con quale regola vengono cancellati. Le finestre marcate «da decidere» vanno concordate con il DPO e poi applicate.

## Situazione

| Dato | Dove | Contenuto personale | Cancellazione | Stato |
| --- | --- | --- | --- | --- |
| RunLog automazioni | `automazioni_automationrunlog` (+ action log) | payload della regola (ferie, ticket, anomalie) | `cleanup_run_logs` ogni notte alle 03:30, finestra `automazioni_runlog_retention_days` (SiteConfig, default 90 giorni) | Attivo |
| Coda eventi automazioni | `automation_event_queue` | `payload_json` / `old_payload_json` del record che ha scatenato l'evento | stessa finestra dei RunLog, solo eventi `done` (da questa release); gli eventi `error` restano per l'analisi | Attivo |
| Notifiche in-app | `core_notifica` | testo della notifica, destinatario | archiviazione automatica configurabile (giorni non lette / lette / conservazione dell'archivio) | Attivo |
| Monitoring — occorrenze errori | `monitoring_issueoccurrence` | utente, URL (senza query string da questa release), user agent, hash della sessione | nessuna | **Da decidere** (proposta: 90 giorni) |
| Monitoring — segnalazioni utente | `monitoring_userproblemreport` | testo libero scritto dal dipendente, utente, URL | nessuna | **Da decidere** (proposta: 12 mesi dalla chiusura della issue) |
| Monitoring — esecuzioni job | `monitoring_automationexecution` | `payload_json` del job | nessuna | **Da decidere** (proposta: 30 giorni) |
| Assistente AI — feedback chat | `ai_assistant_aichatfeedback` | domanda e risposta della chat (anche dati HR) | nessuna | **Da decidere**; finding B8 dell'audit (FAQ create dalle risposte senza revisione) |
| Assistente AI — audit tool | per tool, `AiToolPrivacyReview.retention_days` | parametri e metadati delle chiamate ai tool | finestra per tool o policy globale | Da verificare per ogni tool attivo |
| Log applicativi | `DJANGO_LOG_DIR`: `app.log`, `qcluster.log`, `commands.log`, `sql.log` | username, IP, path | rotazione giornaliera, 5 file (`sql.log`: `SQL_LOG_BACKUP_COUNT`) | Attivo |
| Backup | `BACKUP_DIR` | database completo e, con `--include-media`, documenti (cifrati) | ultimi `BACKUP_RETENTION` backup (default 10) | Attivo; il `.env` completo va solo in `BACKUP_ENV_DIR` |

## Regole

- Un nuovo archivio con dati personali (tabella di log, coda, cache persistente) nasce con la sua regola di cancellazione oppure con una riga «da decidere» in questa tabella.
- Le cancellazioni girano come job django-q notturni e hanno sempre una modalità di anteprima (`--apply` per cancellare davvero), come `cleanup_run_logs`.
- L'audit trail legale (`core_auditlog`, `core.log_action`) non è soggetto a queste finestre.
