# Contatori asset — ingest dai collector

Contratto dell'endpoint che riceve le letture dei contatori (ore, km, cicli) dai
collector esterni, per esempio lo script OPC UA delle CNC. Codice:
[`django_app/assets/api_meters.py`](../../django_app/assets/api_meters.py).

[← Scheda modulo assets](assets.md)

## Regole

- **Solo rete interna.** Il percorso non va pubblicato su Entra Application Proxy.
  Ogni collector ha i suoi **IP ammessi** (IP o reti CIDR), scritti in **Asset ›
  Configurazione › Macchine collegate › Collector**; valgono anche quelli di
  `ASSETS_METER_INGEST_ALLOWED_IPS` del `.env` (default `127.0.0.1,::1`). Il token si
  controlla prima della rete: token errato `401`, rete non ammessa per quel collector `403`.
- **Un token per collector.** Si crea dalla stessa pagina («Crea il collector e il token»,
  solo amministratori del modulo Asset; anche dall'admin Django o con `manage.py
  meter_ingest_client`). Il token in chiaro si vede **una sola volta**, nella risposta della
  pagina: a DB resta l'hash SHA-256. «Nuovo token» lo sostituisce (il vecchio smette subito
  di funzionare), «Disattiva» lo blocca: un collector disattivato riceve `401`.
- **Asset consentiti.** Ogni collector scrive solo sugli asset elencati (o su tutti con
  `--tutti` / «tutti gli asset con contatore»). Il contatore deve già esistere sull'asset
  (scheda asset → Contatori).
- **Valori.** Un valore in calo è rifiutato (riga `rejected`): un azzeramento si dichiara
  a mano dalla scheda asset con una nota. Una lettura con `read_at` uguale o più vecchio
  dell'ultima registrata è ignorata (`ignored_older`): reinviare lo stesso lotto non
  cambia nulla.

## Richiesta

`POST /api/assets/contatori/ingest/` — `Content-Type: application/json`,
`Authorization: Bearer <token>`; al massimo **500** letture per chiamata (oltre: `413`).

```json
{
  "readings": [
    {"asset_tag": "CNC-001", "meter_type": "HOURS", "value": 12345.6, "read_at": "2026-10-16T08:00:00+02:00"}
  ]
}
```

- `meter_type`: `HOURS`, `KM`, `CYCLES`, `OTHER`.
- `read_at`: ISO 8601 **con** fuso orario (senza: riga `rejected`).

## Risposta

`200` con l'esito di ogni riga, nello stesso ordine:

```json
{
  "results": [
    {"index": 0, "asset_tag": "CNC-001", "meter_type": "HOURS", "status": "accepted", "reason": ""}
  ],
  "accepted": 1, "ignored_older": 0, "rejected": 0
}
```

Errori di autenticazione e rete rispondono in JSON: `401` token mancante/errato/disattivato,
`403` rete non ammessa, `413` lotto troppo grande, `422` corpo non valido.

## Esempio (token fittizio)

```bash
curl -X POST https://portale.example.local/api/assets/contatori/ingest/ \
  -H "Authorization: Bearer TOKEN-DI-ESEMPIO" \
  -H "Content-Type: application/json" \
  -d '{"readings":[{"asset_tag":"CNC-001","meter_type":"HOURS","value":12345.6,"read_at":"2026-10-16T08:00:00+02:00"}]}'
```

```powershell
$body = @{ readings = @(@{ asset_tag = "CNC-001"; meter_type = "HOURS"; value = 12345.6; read_at = (Get-Date).ToString("o") }) } | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri "https://portale.example.local/api/assets/contatori/ingest/" `
  -Headers @{ Authorization = "Bearer TOKEN-DI-ESEMPIO" } -ContentType "application/json" -Body $body
```

## Elenco delle macchine per il collector

`GET /api/assets/contatori/ingest/config/` — stessa autenticazione. Ritorna le macchine scritte
nel portale che quel collector deve leggere (fonte «Collector OPC UA», attive, con l'indirizzo
OPC UA, consentite al collector), nel formato di `machines.json`:

```json
{"collector": "Collector CNC officina",
 "machines": [{"name": "DM6", "ip": "192.0.2.15", "port": 4840, "serial": "…", "model": "DMC 125",
               "department": "CN5", "asset_tag": "CNC-001", "username": "", "password": ""}]}
```

`password` è quella OPC UA della macchina (a DB cifrata con `secret_box`): viaggia in chiaro
solo verso il collector autenticato, quindi l'endpoint va usato in HTTPS. `tools/collector_cnc`
lo legge all'avvio e ogni 5 minuti.

## Stato delle macchine (collector OPC UA)

`POST /api/assets/contatori/ingest/stato/` — stessa autenticazione, stessa rete e stessi asset
consentiti delle letture; al massimo **100** macchine per chiamata (oltre: `413`). Lo usa
`tools/collector_cnc` (collector OPC UA delle DMG MORI) a ogni cambio di stato e almeno una volta
al minuto: oltre 15 minuti senza invii il portale mostra la macchina come «non aggiornata».

```json
{
  "macchine": [
    {"asset_tag": "CNC-001", "stato": "ALLARME", "dal": "2026-10-23T08:14:05+00:00",
     "programma": "DM9_0014", "modalita": "AUTO", "esecuzione": "INTERRUPTED", "pezzi": 7,
     "allarmi": [{"codice": "2001", "testo": "Pressione lubrificazione bassa", "severita": 900, "dal": "2026-10-23T08:14:03+00:00"}]}
  ]
}
```

- `stato`: `LAVORO`, `SETUP` (MDI/manuale), `INTERROTTA`, `FERMA`, `ALLARME`, `EMERGENZA`, `OFFLINE`.
- `dal`: inizio dello stato sulla macchina, ISO 8601 **con** fuso; apre un periodo di stato
  (`PeriodoStatoMacchina`) solo quando lo stato cambia.
- `allarmi`: quelli attivi; dalla `severita` 801 in su sono «allarme», sotto «avviso».
- La macchina compare in **Macchine collegate** al primo invio (fonte «Collector OPC UA»).
  Righe `ignored` = collegamento sospeso nel portale; `rejected` = asset sconosciuto o non
  consentito, stato non valido, `dal` senza fuso, macchina già letta via MTConnect.

## Adattare il collector esistente

Fatto in `tools/collector_cnc` (`portale.py`, vedi il suo README). Regole per altri collector:
leggere il token da una variabile d'ambiente (mai
nel codice), inviare `read_at` dell'istante di lettura sulla macchina con l'offset,
raggruppare al massimo 500 letture per chiamata e registrare le righe `rejected`.
Ripetere un invio fallito è sicuro: le letture già registrate tornano `ignored_older`.
