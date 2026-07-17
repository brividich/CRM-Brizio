# Runbook operativo

Checklist per tenere il Security Center in salute. Le cadenze sono indicative: adattale al tuo contesto.

## Giornaliera

- Apri la **dashboard** (`/soc/`) e controlla alert aperti e critici.
- Lavora la coda **alert** (`/soc/alerts/`): prendi in carico, risolvi o chiudi.
- Controlla i **ticket** di remediation aperti, in particolare le CVE ad alto CVSS.
- Verifica i **backup** falliti o mancanti.
- Controlla eventuali **avvisi parser** in diagnostica.

## Settimanale

- Rivedi le **soppressioni** attive: sono ancora giustificate? Qualcuna è scaduta?
- Individua le **regole rumorose** (troppi falsi positivi) e taratale.
- Guarda i **trend backup** e i ticket irrisolti da tempo.

## Mensile

- Rivedi le **soglie** delle regole e la **retention** delle evidenze.
- Analizza i **trend KPI** per un quadro direzionale.
- Passa in rassegna il **registro audit** delle modifiche di configurazione.

## Comandi schedulati consigliati

Questi comandi vanno schedulati sul server (es. via lo scheduler del portale). L'ordine tipico è: ingestione, poi heartbeat, poi snapshot KPI.

```
python manage.py ingest_security_mailbox
python manage.py check_security_source_heartbeat
python manage.py build_daily_kpi_snapshots
```

L'ingestione mailbox può girare anche in modalità continua con `--loop` (vedi [Ingestione da mailbox](/soc/docs/mailbox-ingestion/)). L'heartbeat va schedulato **accanto** all'ingestione: è l'unico controllo che rileva l'assenza di dati, non ciò che arriva.

## Prima di fidarsi di una nuova sorgente

- Ingerisci un campione reale e verifica metriche/alert attesi.
- Esegui la diagnostica (`security_center_diagnostics`).
- Controlla che la cadenza attesa/heartbeat sia impostata.
