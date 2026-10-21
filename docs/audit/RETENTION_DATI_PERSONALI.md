# Retention dei dati personali

Documento nato con l'audit sicurezza del 09/10/2026 (Fase 3) ed esteso ai moduli di dominio con l'analisi GDPR del 21/10/2026. Elenca dove il portale conserva dati personali e con quale regola vengono cancellati o ridotti.

I termini marcati «proposta» vengono dalla checklist GDPR del 21/10/2026 e **non sono ancora validati dal DPO**. Per questo i dati di dipendenti e candidati non si cancellano da soli: il portale li conta e un amministratore conferma.

Collegati: [registro dei trattamenti](../gdpr/REGISTRO_TRATTAMENTI.md), [DPIA preliminare](../gdpr/DPIA_PRELIMINARE.md), [soggetti esterni](../gdpr/RESPONSABILI_ART28.md).

## Archivi tecnici

| Dato | Dove | Contenuto personale | Regola | Stato |
| --- | --- | --- | --- | --- |
| RunLog automazioni | `automazioni_automationrunlog` (+ action log) | payload della regola (ferie, ticket, anomalie) | `cleanup_run_logs` ogni notte alle 03:30, finestra `automazioni_runlog_retention_days` (SiteConfig, default 90 giorni) | Attivo |
| Coda eventi automazioni | `automation_event_queue` | `payload_json` / `old_payload_json` | stessa finestra dei RunLog, solo eventi `done`; gli eventi `error` restano per l'analisi | Attivo |
| Notifiche in-app | `core_notifica` | testo, destinatario | archiviazione automatica configurabile | Attivo |
| Monitoring: occorrenze errori | `monitoring_issueoccurrence` | utente, URL senza query string, user agent, hash della sessione | `gdpr_retention` (`monitoring_occorrenze`): 90 giorni | Attivo (proposta) |
| Monitoring: segnalazioni utente | `monitoring_userproblemreport` | testo libero, utente, URL | `gdpr_retention` (`monitoring_segnalazioni`): 12 mesi, solo con la issue risolta o ignorata (o senza issue) | Attivo (proposta) |
| Monitoring: esecuzioni job | `monitoring_automationexecution` | `payload_json` del job | `gdpr_retention` (`monitoring_esecuzioni`): 30 giorni, sempre tenuta l'ultima di ogni job | Attivo (proposta) |
| Assistente AI: conversazioni | `ai_assistant_aiconversation*` | domande e risposte | `ai_pulisci_conversazioni`, `AI_CHAT_HISTORY_RETENTION_DAYS` (90) | Attivo |
| Assistente AI: feedback chat | `ai_assistant_aichatfeedback` | domanda e risposta | `gdpr_retention` (`ai_feedback`): 90 giorni | Attivo (proposta) |
| Assistente AI: audit tool | per tool, `AiToolPrivacyReview.retention_days` | parametri e metadati delle chiamate | finestra per tool o policy globale | Da verificare per ogni tool attivo |
| Link di approvazione | `automazioni_automationapprovallink` | email del destinatario, impronta del token | `gdpr_retention` (`approval_link`): 6 mesi, solo richieste decise o scadute (chi ha deciso resta su `AutomationApproval`) | Attivo (proposta) |
| Risposte di approvazione dalla casella | `automazioni_approvalmailboxmessage` | corpo delle mail | `gdpr_retention` (`approval_posta`): 6 mesi, solo messaggi già elaborati | Attivo (proposta) |
| Casella SOC | `security_securitymailboxmessage` | mittente, corpo, payload originale | `gdpr_retention` (`soc_posta`): dopo 12 mesi mittente, corpo e originale svuotati; la riga resta (dedup, report collegati) | Attivo (proposta) |
| Chat e log AI del SOC | `security_aiconversation*`, `security_securityaiinteractionlog` | domande, username | `gdpr_retention` (`soc_ai`): 12 mesi | Attivo (proposta) |
| Tentativi di accesso | tabelle `axes_*` | username, IP | `gdpr_retention` (`accessi`): 90 giorni | Attivo (proposta) |
| Sessioni | `django_session` | id utente | `gdpr_retention` (`sessioni`): sessioni scadute, ogni notte | Attivo |
| Log applicativi | `DJANGO_LOG_DIR`: `app.log`, `qcluster.log`, `commands.log`, `sql.log` | username, IP, path | rotazione giornaliera, 5 file | Attivo |
| Backup | `BACKUP_DIR` | database completo; documenti (già cifrati) | ultimi `BACKUP_RETENTION` backup | Attivo. I `.bak` di SQL Server non sono cifrati: Express non supporta `WITH ENCRYPTION`, vedi sotto |
| Audit trail | `core_auditlog` | chi, cosa, quando; per i dati sensibili solo i nomi dei campi (politica v2) | 60 mesi online, archivio 120 mesi (`audit_archive`, `docs/dr/AUDIT_POLICY.md`) | Attivo, lancio manuale |

Il lavoro notturno `gdpr_retention` gira alle 03:15 (`core/gdpr_retention.py`). Ogni termine si cambia in SiteConfig con `gdpr_ret_<regola>_giorni` (min 7, max 3650). `manage.py gdpr_retention` mostra i conteggi senza cambiare nulla.

## Dati di dominio

| Dato | Regola | Stato |
| --- | --- | --- |
| Documenti dei dipendenti (contratti, referti, attestati) | `retention_until` per tipo (10 anni dalla cessazione) | Conteggio settimanale + conferma in «Conservazione dei dati» |
| Dipendenti cessati | dopo 10 anni dalla cessazione «Ripulisci»: via dati civili e bancari, recapiti privati, foto, figli, taglie e telefono, voci retributive e saldi del cedolino, prescrizioni e note delle visite. Restano nome, rapporto, formazione, DPI, visite con date ed esito | Conteggio settimanale + conferma (proposta: 10 anni) |
| Candidati chiusi o «in database» | dopo 24 mesi dall'ultima modifica, anonimizzazione (restano stato, date, esiti) | Conteggio settimanale + conferma (proposta: 24 mesi) |
| Candidati assunti | passano alla scheda del dipendente | Nessuna scadenza propria |
| Presenze e assenze (tabelle legacy `assenze`, certificazioni) | proposta 5 anni | **Da fare**: tabelle legacy, serve decisione su cosa resta per lo storico ferie |
| Timbri (registro firme/timbri) | — | **Da decidere** |
| Allegati di ticket, task, diario preposto, suggestion corner | — | **Da decidere** (dipende dalla conservazione del record) |
| Nome del dipendente nelle tabelle legacy | resta: serve allo storico | Per un'anonimizzazione completa serve una decisione del DPO |

## Backup e cifratura

SQL Server Express non permette la cifratura nativa dei backup (`BACKUP ... WITH ENCRYPTION`). Le alternative, da decidere con l'IT:

1. cartella NAS cifrata (cifratura della cartella condivisa) con accesso solo all'account del servizio di backup;
2. cifratura applicativa dei `.bak` nel motore dei backup, con chiave nel Recovery Kit: richiede di aggiornare anche ripristino e drill (`restore-host.ps1`, `drill.py`).

I documenti privati sono già cifrati nei backup (Fernet, `DOCUMENT_ENCRYPTION_KEY`).

## Regole

- Un nuovo archivio con dati personali nasce con la sua regola di cancellazione oppure con una riga «da decidere» in questo documento.
- Le cancellazioni hanno sempre un'anteprima (`--apply` per applicare). I dati di dipendenti e candidati richiedono la conferma di un amministratore.
- L'audit trail legale (`core_auditlog`) segue la sua politica (`docs/dr/AUDIT_POLICY.md`), non queste finestre.
