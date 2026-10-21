# Politica dell'audit automatico (`core_auditlog`)

Versione politica: **2** (`core/audit_policy.py`, `AUDIT_POLICY_VERSION`) · introdotta il 17/10/2026 (BUILD_SPEC R0) · v2 del 21/10/2026: dati personali sensibili in classe C (GDPR).

## Perché

A ottobre 2026 `core_auditlog` occupava il 67% del database di produzione (4,6 GB su 7 GB) e cresceva di circa 2,45 GB al mese. Il 95% veniva dall'audit automatico (`core/audit_signals.py`) su modelli tecnici, che sono già log con tabelle proprie, e da copie integrali di contenuti voluminosi (file, corpi email). Ai ritmi di allora il database avrebbe raggiunto il limite di 10 GB di SQL Server Express in 5–7 settimane.

La politica riduce solo ciò che è elencato. Tutto il resto resta in audit completo.

## Classi

| Classe | Trattamento | Modelli |
|---|---|---|
| **A** — critico / ISO (default) | audit completo; nessuna riga per gli update senza modifiche reali; valori oltre 500 caratteri troncati con lunghezza e impronta SHA-256 | tutti i modelli non elencati sotto: anagrafica, sorveglianza sanitaria, formazione, assets/manutenzione, DPI, ticket, anomalie, assenze, tasks/KICK-OFF, diario preposto, incidenti, procedure, RENTRI, controllo accessi (`RolePermissionGrant`, `RoutePermissionBinding`, `NavigationItem`, `Pulsante`…), configurazione Security Center |
| **B** — tecnico ad alto volume | **escluso**: nessuna riga e nessun listener | `automazioni.AutomationRunLog`, `AutomationActionLog`, `ClusterHeartbeat`, `BrokerRecoveryEntry`; `monitoring.AutomationExecution`, `IssueOccurrence`; `security.SecurityCveImpact`, `SecurityKpiSnapshot`, `SecurityReportMetric`; `contatori.RilevazioneSNMP` |
| **C** — contenuti voluminosi o personali | **solo metadati**: modello, pk, etichetta, utente, IP, data e nomi dei campi; mai i valori | `security.SecuritySourceFile`, `SecurityMailboxMessage`, `SecurityReport`; `procedure_refresh.SgiTestoEstratto`. **Dalla v2 (GDPR)**: sorveglianza sanitaria (`anagrafica.VisitaMedica`, `DipendenteVisitaFacoltativa`, `DerogaOperativaVisita`, `RefertoIntakeRiga`, `RequisitoVisitaDipendente`), dati civili e familiari (`DipendenteAnagraficaCivile`, `FiglioACarico`), retribuzioni e cedolini (`ImportazioneRetributiva`, `VoceRetributiva`, `ImportazioneCedolini`, `SaldoCedolino`), selezione (`Candidato`, `CandidatoPunteggio`, `CandidatoLog`), `assenze.CertificazionePresenza`, `dpi.ConsegnaDPI` (firma), chat AI (`ai_assistant.AiConversationMessage`, `AiChatFeedback`, `security.AIConversationMessage`, `SecurityAiInteractionLog`) |
| **D** — rumorosi con campi tecnici | audit completo, ma un update che tocca solo i campi tecnici non produce righe; i campi tecnici cambiati insieme a quelli reali compaiono solo per nome in `campi_tecnici_cambiati` | `automazioni.AutomationRule` (`last_run_at`, `last_test_at`, `updated_at`), `automazioni.ManagedFlow` (`queued_task_id`, `running_until`, `lease_token`), `contatori.DispositivoSNMP` (stato e dati letti a ogni interrogazione SNMP: `snmp_*`, `sys_name`, `sys_description`, `sys_object_id`, `sys_uptime_seconds`, `firmware_rilevato_il`), `security.SecurityCveRecord` (`nvd_fetched_at`, `impact_computed_at`, `epss`, `epss_percentile`, `nvd_error`), `core.Notifica` (`popup_shown`, `letta`, `letta_il`) |

### Perché ogni modello di classe B e C ha già una traccia

| Modello | Traccia alternativa |
|---|---|
| `AutomationRunLog`, `AutomationActionLog` | sono loro stessi il registro delle esecuzioni delle automazioni |
| `ClusterHeartbeat`, `BrokerRecoveryEntry` | stato tecnico del cluster e del broker; nessun significato di business |
| `AutomationExecution`, `IssueOccurrence` | registro dei job e delle occorrenze del Monitoraggio |
| `SecurityCveImpact`, `SecurityKpiSnapshot`, `SecurityReportMetric` | dati derivati, ricalcolati dalle fonti |
| `RilevazioneSNMP` | è la serie storica delle letture SNMP |
| `SecuritySourceFile`, `SecurityMailboxMessage`, `SecurityReport` | il contenuto è nella tabella stessa; le modifiche di configurazione del Security Center restano in `SecurityConfigurationAuditLog` |
| `SgiTestoEstratto` | testo estratto dai documenti SGI, rigenerabile dalla fonte |
| modelli GDPR della v2 | il valore corrente è nel record stesso; l'audit conserva chi, quando, quale record e quali campi. Copiare i valori per 5+10 anni vanificava i termini di conservazione e l'anonimizzazione (`docs/audit/RETENTION_DATI_PERSONALI.md`). Gli export e le letture sensibili restano tracciati da `log_action` |

## Cosa non cambia

- Le chiamate esplicite `log_action(...)` (azioni utente) non passano dalla politica: stesso record di prima.
- `login_fallito` e ogni evento di autenticazione.
- Gli insert e i delete dei modelli di classe A e D si registrano sempre, con i valori.
- `oggetto_tipo`/`oggetto_id` e `storico_oggetto()`. L'audit automatico non li valorizza: lo storico per record mostrato sulle schede viene solo da `log_action`.
- Le pagine di audit dei moduli (notizie, tasks, assets, assenze, anomalie, timbri, anagrafica, permessi) filtrano moduli di business e non leggono righe dei modelli di classe B o C.

## Come cambiare la politica

1. Modifica `core/audit_policy.py` e incrementa `AUDIT_POLICY_VERSION`.
2. Aggiorna le tabelle di questo documento e la voce in `CHANGELOG.md`.
3. `manage.py check`: una chiave che non corrisponde a un modello installato produce il warning `core.W002`, un campo ignorato inesistente produce `core.W003`.
4. PR verso `main` con revisione: una modifica della politica di logging va tracciata (ISO/IEC 27001).

Un modello si sposta in classe B solo se ha già una traccia propria. Un modello di business non va mai in classe B; va in classe C solo per minimizzazione dei dati personali (GDPR art. 5.1.c), mai per risparmiare spazio.

Dopo un passaggio in classe C le righe già scritte con i valori si riducono con `audit_archive --run --category contenuti --archive-dir <UNC>` (archivio a soli metadati, riga ridotta in DB). Le righe automatiche non sono nel sigillo mensile (`core/audit_sigilli.py` esclude `auto_*`), quindi la riduzione non rompe la catena.

## Archivio e pulizia dello storico (`manage.py audit_archive`)

| Comando | Effetto |
|---|---|
| `audit_archive` / `--plan [--json]` | dry-run: per categoria e modello mostra righe, MB stimati e intervallo di date. Non scrive nulla |
| `--run --archive-dir <UNC> [--before AAAA-MM-GG] [--batch 20000] [--max-minutes 60] [--checkpoint]` | archivia, poi cancella o riduce. Si può interrompere: rilanciato, riprende dall'ultimo id (`audit_archive_state.json`) |
| `--category business --older-than-months 60` | righe di classe A più vecchie di 60 mesi: archiviate, poi tolte dal DB. Sotto i 60 mesi il comando si rifiuta |
| `--restore <manifest.json\|part>` `[--into-table core_auditlog_restored]` | rilegge un archivio in una tabella separata, mai dentro `core_auditlog` |
| `--prune-archives --archive-dir <UNC> [--run]` | elimina i mesi d'archivio oltre 120 mesi; un mese senza `manifest.json` verificato non si elimina mai |

Categorie della pulizia (`policy`, il default):

- `tecnico`: righe dei modelli di classe B, archiviate complete e poi cancellate.
- `update_nullo`: update di classe D senza modifiche significative, archiviati completi e poi cancellati.
- `contenuti`: righe di classe C con valori. I valori sono proprio il dato che non si vuole duplicare: si archiviano a soli metadati e la riga in DB viene ridotta a metadati, non cancellata.
- La classe A non viene mai toccata da questa categoria.

Formato: `<archive-dir>\auditlog\<AAAA-MM>\part-<n>.jsonl.gz` + `manifest.json` (righe, id min/max, SHA-256 di ogni parte, versione della politica, data). Ogni parte viene scritta su un file temporaneo, rinominata, riletta e verificata **prima** di toccare il DB. Le cancellazioni avvengono in transazioni brevi, a blocchi di 1.000 id (il limite di SQL Server è 2.100 parametri).

### Ordine operativo (produzione, lo esegue Brizio)

1. Deploy della politica (questo blocco).
2. `manage.py audit_archive --plan` e revisione dell'output.
3. `manage.py audit_archive --run --archive-dir \\<nas>\hub-archivi --max-minutes 60 --checkpoint`, ripetuto finché esce «completato». Va fatto **prima** di passare il DB al recovery model FULL.
4. Backup FULL subito dopo.
5. **Non** fare `SHRINK` del file dati: lo spazio liberato viene riusato.

## Conservazione

| Cosa | Dove | Quanto |
|---|---|---|
| Audit di classe A | online in `core_auditlog` | 60 mesi, poi archiviato (`--category business`, mensile, attivo solo dopo il passaggio a SQL Server 2025) |
| Archivi (`auditlog\<AAAA-MM>`) | NAS, replicato da Hyper Backup su Synology C2 e su un secondo NAS | 120 mesi, poi eliminati da `--prune-archives` con dry-run e log |
| Classi B/C | archiviazione settimanale (domenica 05:30) come difesa futura | 120 mesi |

I task pianificati vengono registrati da `register-backup-tasks.ps1` (blocco R1), che porta anche l'esito in `BackupRun`.

## Osservabilità

- `manage.py hub_backup_doctor`: spazio usato rispetto al limite dell'edizione (Express: 10 GB fino a SQL Server 2022, 50 GB con SQL Server 2025), top tabelle, crescita giornaliera e mensile dell'audit, top modelli degli ultimi 7 giorni con la loro classe, previsione di saturazione, versione della politica, diagnostica della cache su DB.
- Check `audit_growth` del monitoring: warning se la crescita proiettata supera 500 MB al mese, fail se la saturazione prevista scende sotto 60 giorni. Non è mai critical per `/readyz`: un problema di capacità non deve togliere il sito dal bilanciamento.
- `manage.py hub_db_tuning --query-store-max-mb 100 [--apply]`: limite del Query Store (dry-run di default). Se il Query Store è spento non lo accende, salvo `--enable`.

## Riferimenti normativi

- **ISO/IEC 27001:2022** — A.8.15 *Logging* (registrare le attività rilevanti, proteggere i log) e A.5.33 *Protezione delle registrazioni*: le azioni utente e gli eventi di autenticazione restano integri, gli archivi hanno impronte verificabili, la politica è versionata e modificabile solo tramite revisione.
- **ISO 9100 / EN 9100** — §7.5.3 *Controllo delle informazioni documentate*: conservazione delle registrazioni per un periodo definito (60 mesi online, 120 mesi d'archivio), recuperabili (`--restore`).
- **GDPR** (Reg. UE 2016/679) — art. 5.1.c *minimizzazione* e art. 5.1.e *limitazione della conservazione*: niente copie di corpi email e contenuti di file nell'audit, conservazione a scadenza definita.
