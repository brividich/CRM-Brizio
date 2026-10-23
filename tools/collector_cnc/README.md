# Collector CNC (OPC UA) → NOVICROM HUB

Collector dell'officina per le macchine DMG MORI con server OPC UA (IoTconnector). Gira su un PC della rete d'officina, **legge soltanto** (nessuna scrittura, nessun metodo chiamato) e:

- tiene il proprio database locale `machines.db`: periodi di stato, segnali, allarmi, contatori al minuto;
- se configurato, **invia al portale** lo stato reale delle macchine e i contatori.

Due modelli dati gestiti: **umati / OPC UA for Machine Tools** e **DMG MORI BasicDataSet** (`MODELS` in `collector.py`).

## Stati

| Collector | Portale | Quando |
|---|---|---|
| `LAVORO` | In lavoro | programma in esecuzione in automatico |
| `SETUP` | Lavoro MDI/manuale | in esecuzione in MDI o manuale |
| `INTERROTTA` | Interrotta | programma interrotto |
| `FERMA` | Ferma | nessun programma in corso |
| `ALLARME` | In allarme | messaggio attivo con severità ≥ 801 (o allarmi attivi nel BasicDataSet) |
| `EMERGENZA` | Emergenza | emergenza premuta |
| `OFFLINE` | Offline | server OPC UA non raggiungibile |

Sul portale: mappa officina (livello «Allarme sulla CNC», riquadro «Dal controllo della macchina») e pagina **Asset › Configurazione › Macchine collegate**.

## Cosa arriva al portale

| Cosa | Endpoint | Quando |
|---|---|---|
| stato, programma, modalità, pezzi, allarmi attivi | `POST /api/assets/contatori/ingest/stato/` | a ogni cambio (entro 5 s) e comunque ogni minuto |
| contatore **Ore** (ore di lavoro) e **Cicli** (pezzi totali) | `POST /api/assets/contatori/ingest/` | ogni ora |

Ore: BasicDataSet `OperationTimeOverall` in secondi (÷ 3600). umati `OperationDuration` letto come ore: **da verificare su una macchina umati** confrontandolo con le ore del pannello (`hours_factor` in `MODELS`).

Contratto degli endpoint: `docs/moduli/assets_contatori_ingest.md`. Se il portale è giù, il collector continua a registrare in locale e riprova ogni minuto.

## Messa in servizio

1. **Portale** (chi amministra):
   - crea il token del collector: `python manage.py meter_ingest_client "Collector CNC officina" --asset CNC-0001 --asset CNC-0002` (o `--tutti`). Il token si vede **una volta sola**;
   - aggiungi l'IP del PC del collector a `ASSETS_METER_INGEST_ALLOWED_IPS` nel `.env` e riavvia il portale;
   - sulle schede delle macchine crea i contatori **Ore** e **Cicli** se vuoi che i piani di manutenzione a contatore usino i dati della macchina.
2. **PC del collector**:
   - `pip install asyncua`;
   - copia `machines.example.json` in `machines.json` e scrivi le macchine vere, con `asset_tag` = codice dell'asset nel portale (senza `asset_tag` la macchina non viene inviata). `machines.json` e `machines.db` restano sul PC: **mai nel repository**;
   - variabili d'ambiente (utente o servizio che lancia il collector): `PORTALE_URL` (es. `https://portale.dominio.local`), `PORTALE_TOKEN`, e se serve `PORTALE_CA` (certificato .pem della CA interna);
   - `py collector.py`. In avvio scrive «portale: invio di N macchine a …»; le righe scartate dal portale (asset non consentito o sconosciuto) compaiono nel log.

Il collector non va pubblicato verso Internet e l'endpoint del portale resta solo rete interna (`docs/ai/05_SECURITY_BOUNDARIES.md`).
