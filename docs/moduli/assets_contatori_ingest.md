# Contatori asset — ingest dai collector

Contratto dell'endpoint che riceve le letture dei contatori (ore, km, cicli) dai
collector esterni, per esempio lo script OPC UA delle CNC. Codice:
[`django_app/assets/api_meters.py`](../../django_app/assets/api_meters.py).

[← Scheda modulo assets](assets.md)

## Regole

- **Solo rete interna.** Il percorso non va pubblicato su Entra Application Proxy.
  Il portale accetta solo i client IP in `ASSETS_METER_INGEST_ALLOWED_IPS` (IP o reti
  CIDR separati da virgola; default `127.0.0.1,::1`): da altre reti risponde `403`.
- **Un token per collector.** Si crea dall'admin Django («Collector letture contatori»)
  o con `manage.py meter_ingest_client "<nome>" [--tutti | --asset TAG ...]`. Il token
  in chiaro si vede **una sola volta**: a DB resta l'hash SHA-256. Per cambiarlo:
  `--rigenera`. Un collector disattivato riceve `401`.
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

## Adattare il collector esistente

Il collector OPC UA standalone deve: leggere il token da una variabile d'ambiente (mai
nel codice), inviare `read_at` dell'istante di lettura sulla macchina con l'offset,
raggruppare al massimo 500 letture per chiamata e registrare le righe `rejected`.
Ripetere un invio fallito è sicuro: le letture già registrate tornano `ignored_older`.
