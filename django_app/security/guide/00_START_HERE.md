# Da qui

Benvenuto nella guida del **Security Center IT (SOC IT - CN)**, il modulo del portale NOVICROM HUB che raccoglie report di sicurezza informatica (antivirus/EDR, firewall, backup, vulnerabilità) e li trasforma in metriche, alert e ticket di remediation tracciabili.

## Cos'è e cosa non è

Il Security Center è un **portale di intelligence sui report ricorrenti**. Prende email, PDF, CSV e upload dei vari sistemi di sicurezza, li normalizza e ne ricava un quadro operativo unico: alert aperti, ticket di remediation, KPI, stato dei backup.

**Non** è un SIEM completo: non fa ricerca su log grezzi ad alto volume né correlazione in tempo reale. Si concentra sui report periodici che i vendor già producono e sulle notifiche verso il team.

## Prerequisiti

- Accesso al modulo `/soc/` con permesso ACL `security.config.view` (per la configurazione serve anche `security.manage_security_configuration` o `is_staff`).
- I comandi `manage.py` vanno lanciati sul server applicativo (in produzione l'app-pool gira come utente dedicato; in sviluppo dal proprio venv). Il primo setup **non richiede la shell**: la pagina `/soc/admin/autoconfig/` fa le stesse cose dal browser.

## Primo setup in 30 minuti

1. Apri `/soc/admin/autoconfig/` e premi **Completa la configurazione**: semina la configurazione di base (idempotente, tracciata nell'audit). Equivalente da shell: `python manage.py seed_security_center_config`.
2. Apri `/soc/admin/config/` e passa in rassegna le 9 sezioni: Generali, Sorgenti, Parser, Regole alert, Soppressioni, Backup, Notifiche, Ticketing, Audit.
3. Lancia la diagnostica: `python manage.py security_center_diagnostics` (o la pagina `/soc/admin/diagnostics/`) e risolvi gli avvisi — quelli risolvibili in automatico compaiono come **correzioni suggerite** nella pagina di autoconfigurazione.
4. Ingerisci qualche campione valido per prendere confidenza: `python manage.py ingest_sample_security_data`.
5. Esegui la pipeline dalla pagina `/soc/pipeline/` (oppure `run_security_parsers`, `evaluate_security_rules`, `build_daily_kpi_snapshots`).
6. Verifica che compaiano alert, ticket e KPI nella dashboard `/soc/`.

## Dove guardare ogni giorno

- **Dashboard** (`/soc/`): alert aperti, critici, ticket aperti.
- **Alert** (`/soc/alerts/`): coda di lavoro, presa in carico e chiusura.
- **Ticket** (`/soc/tickets/`): remediation delle vulnerabilità.
- **Pipeline** (`/soc/pipeline/`): rilancio manuale di parser, regole e KPI.

## Prossimi passi

- Per configurare in dettaglio ogni parte: [Guida alla configurazione](/soc/docs/08-configuration-guide/).
- Per capire gli stati degli alert: [Ciclo di vita degli alert](/soc/docs/07-alert-lifecycle/).
- Per la routine operativa: [Runbook operativo](/soc/docs/11-operations-runbook/).
