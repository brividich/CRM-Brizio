# Ingestione da mailbox

Molti report di sicurezza arrivano via email. L'ingestione da mailbox li importa in automatico, li deduplica e li passa al motore parser.

## Provider

| Provider | Uso |
| --- | --- |
| manual | Inserimento manuale (utile in sviluppo/test) |
| mock | Sorgente finta per prove riproducibili |
| graph | Mailbox Microsoft 365 via Microsoft Graph |
| imap | Mailbox generica via IMAP |

Con Microsoft Graph l'ingestione è **incrementale e paginata**: non perde backlog e riparte dall'ultimo messaggio visto.

## Configurazione della sorgente mail

| Campo | Significato | Consiglio |
| --- | --- | --- |
| Allowlist mittente | Domini/indirizzi ammessi | Ancora la provenienza al dominio del vendor |
| Richiede mittente verificato | Accetta solo se DKIM/SPF passano | Attiva quando il provider espone l'header di autenticazione |
| Oggetto include/escludi | Filtri sull'oggetto | Restringi ai report reali |
| Corpo include | Filtro sul corpo | Opzionale |
| Estensioni allegati | Allegati ammessi | pdf, csv |
| Max messaggi per run | Tetto per esecuzione | 50 |
| Cadenza attesa (ore) | Per l'heartbeat | 24 per un report giornaliero |

La provenienza è stabilita **solo dal mittente** (dominio ancorato), con gate opzionale DKIM/SPF: fail-closed, i messaggi senza header di autenticazione vengono rifiutati quando il gate è attivo.

## Deduplica

Ogni messaggio ha un'impronta (fingerprint) calcolata da sorgente, id esterno, oggetto e data. Lo stesso messaggio importato due volte non viene rielaborato. La deduplica di alert/ticket a valle è garantita a livello database (indici unici parziali).

## Schedulazione

```
python manage.py ingest_security_mailbox
```

Per un polling continuo esiste la modalità `--loop`. Schedula l'ingestione con la cadenza dei tuoi report e affiancale sempre l'heartbeat:

```
python manage.py check_security_source_heartbeat
```

## Troubleshooting

- **Messaggi non importati:** controlla allowlist mittente, filtri oggetto/corpo e, se attivo, il gate mittente verificato.
- **Sorgente silente:** se non arriva nulla ma non scatta alcun alert, verifica la cadenza attesa (`expected_every_hours`) e che l'heartbeat sia schedulato.
- **Doppioni sospetti:** ricorda che la deduplica è per `(sorgente, dedup_hash)` e che un elemento chiuso può legittimamente riaprirsi.
