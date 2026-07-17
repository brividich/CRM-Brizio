# Modulo Microsoft Defender

Il modulo Defender elabora le email di notifica sulle vulnerabilità e le trasforma in finding CVE, evidenze e ticket di remediation.

## Flusso

```
email vulnerabilità -> parser -> finding CVE -> evidenze -> ticket di remediation
```

## Cosa produce

| Elemento | Significato |
| --- | --- |
| Finding CVE | CVE, prodotto interessato, CVSS, dispositivi esposti |
| Evidenza | Prove a supporto (report, dettagli) |
| Ticket | Unità di remediation che aggrega le CVE correlate |

## Deduplica e ricorrenze

- I finding sono deduplicati per `(sorgente, dedup_hash)`: la stessa CVE sullo stesso prodotto non genera doppioni.
- Se una vulnerabilità già chiusa **si ripresenta**, il ticket può riaprirsi (configurabile in Ticketing).
- L'**aggregazione per prodotto** raggruppa più CVE dello stesso prodotto in un unico ticket, così la remediation è per prodotto e non per singola CVE.

## Priorità

Usa il **CVSS** e il numero di **dispositivi esposti** per stabilire la priorità di lavorazione: i ticket con CVSS alto e ampia esposizione vanno per primi. Gli SLA per severità (sezione Ticketing) guidano gli avvisi di scadenza.

## Collegamento agli asset

I finding possono essere collegati agli asset del registro HUB tramite `collega_asset_security`, così una vulnerabilità è ricondotta al dispositivo reale.
