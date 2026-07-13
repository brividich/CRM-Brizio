# Security Center AI - Domain Knowledge

Security Center AI è una piattaforma Django per Report Intelligence, non un SIEM completo.

## Architettura

Analizza report, email, CSV, PDF e notifiche di sicurezza provenienti da fonti configurate. Non raccoglie log in tempo reale, ma elabora report periodici e notifiche.

## Moduli principali

### WatchGuard Intelligence
- Analisi report firewall WatchGuard
- Monitoraggio traffico di rete
- Identificazione anomalie di connessione
- Policy firewall e VPN

### Microsoft Defender Vulnerability Intelligence
- Report vulnerabilità Microsoft Defender
- Gestione CVE e CVSS
- Priorità basata su asset esposti
- Patch management

### Backup Monitoring
- Monitoraggio backup NAS e cloud
- Verifica integrità backup
- Alert per backup falliti o mancanti
- Recovery point objectives

### Security Alerts
- Alert generati da regole configurate
- Deduplicazione e aggregazione
- Baseline deviation detection
- Cooldown e dedup window

### Evidence Container
- Raccolta evidenze per alert e ticket
- Link a eventi, report e ticket
- Tracciamento decisioni
- Audit trail

### Remediation Tickets
- Ticket per vulnerabilità e incidenti
- Link a CVE e asset
- Tracking stato e occorrenze
- Correlazione con alert ed evidenze

### KPI Dashboard
- Metriche di sicurezza aggregate
- Trend e baseline
- Alert aperti e risolti
- Ticket aperti e chiusi

### Configuration Studio
- Configurazione fonti dati
- Regole di alert
- Suppression rules
- Addon registry

### Addon Registry
- Estensioni modulari
- Parser custom
- Integrationi esterne
- Plugin system

## Principi operativi

### Priorità
- Critical > High > Medium > Low
- CVSS >= 9.0: massima priorità
- Asset critici: priorità elevata
- Endpoint esposti: priorità elevata
- Backup falliti o mancanti: priorità critica

### Deduplicazione
- Hash-based deduplication
- Time window: 1440 minuti default
- Aggregazione eventi simili
- Evita rumore

### Baseline
- Deviation detection
- Trend analysis
- Anomaly detection
- Context-aware alerting

### Anti-rumore
- Cooldown periodi
- Suppression rules
- Volume-based filtering
- Contextual relevance

## Data model

### SecurityAlert
- source: SecuritySource
- event: SecurityEventRecord
- severity: critical/high/medium/low
- status: new/acknowledged/closed/snoozed
- dedup_hash: deduplication key
- decision_trace: JSON metadata
- evidence_containers: related evidence
- tickets: related tickets
- action_logs: history

### SecurityReport
- source: SecuritySource
- report_type: tipo report
- parser_name: parser utilizzato
- parse_status: parsed/failed/pending
- parsed_payload: JSON content
- metrics: SecurityReportMetric[]
- vulnerabilities: SecurityVulnerabilityFinding[]

### SecurityRemediationTicket
- source: SecuritySource
- cve/cve_ids: CVE references
- affected_product: prodotto interessato
- severity: severità massima
- max_cvss: CVSS massimo
- max_exposed_devices: dispositivi esposti
- status: open/in_progress/closed
- occurrence_count: occorrenze
- evidence: related evidence containers
- linked_alerts: related alerts

### SecurityEvidenceContainer
- source: SecuritySource
- alert: related alert
- status: open/closed
- decision_trace: JSON metadata
- items: SecurityEvidenceItem[]

## Fonti dati

### SecuritySource
- name: nome fonte
- source_type: tipo (watchguard, defender, backup, etc.)
- enabled: stato
- configuration: JSON config
- last_sync_at: ultima sincronizzazione

### SecurityEventRecord
- source: SecuritySource
- event_type: tipo evento
- severity: severità
- payload: JSON payload
- parsed_at: timestamp parsing
