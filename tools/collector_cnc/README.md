# Collector CNC (OPC UA) → NOVICROM HUB

Collector dell'officina per le macchine DMG MORI con server OPC UA (IoTconnector). Gira su un PC della rete d'officina, **legge soltanto** (nessuna scrittura, nessun metodo chiamato) e:

- tiene il proprio database locale `machines.db`: periodi di stato, segnali, allarmi, contatori al minuto;
- prende dal portale **l'elenco delle macchine da leggere** e gli **invia** stato e contatori.

Due modelli dati gestiti: **umati / OPC UA for Machine Tools** e **DMG MORI BasicDataSet** (`MODELS` in `collector.py`).

## Tutto si configura dal portale

**Asset › Configurazione › Macchine collegate**:

- **Macchine**: «Collega una macchina» › *Collector OPC UA* › indirizzo OPC UA (IP), porta (4840), codice breve (es. DM6), utente e password OPC UA se la macchina non accetta l'accesso anonimo (password cifrata). «Crea i contatori Ore e Cicli se mancano» li prepara per i piani di manutenzione.
- **Collector** (amministratori del modulo Asset): «Crea il collector e il token» con gli **IP ammessi** (l'IP del PC del collector). Il token si vede **una volta sola**; «Nuovo token» lo sostituisce, «Disattiva» lo blocca. «Tutte le macchine» o solo quelle spuntate.

Sul PC del collector servono solo due variabili d'ambiente (utente o servizio che lancia il collector):

- `PORTALE_URL` — indirizzo del portale, es. `https://portale.dominio.local` (la pagina lo mostra accanto al token);
- `PORTALE_TOKEN` — il token del collector;
- facoltativa `PORTALE_CA` — certificato .pem della CA interna, se l'HTTPS del portale non è firmato da una CA pubblica.

Poi `pip install asyncua` e `py collector.py`.

## Come lavora

| Cosa | Endpoint | Quando |
|---|---|---|
| elenco delle macchine da leggere | `GET /api/assets/contatori/ingest/config/` | all'avvio e ogni 5 minuti: macchine aggiunte, tolte o cambiate nel portale partono o si fermano senza riavviare |
| stato, programma, modalità, pezzi, allarmi attivi | `POST /api/assets/contatori/ingest/stato/` | a ogni cambio (entro 5 s) e comunque ogni minuto |
| contatore **Ore** (ore di lavoro) e **Cicli** (pezzi totali) | `POST /api/assets/contatori/ingest/` | ogni ora |

- L'ultimo elenco scaricato resta in `machines.portale.json` accanto allo script (contiene le password OPC UA: resta sul PC, è fuori dal repository): se all'avvio il portale non risponde si riparte da quello.
- Senza `PORTALE_URL`/`PORTALE_TOKEN` il collector lavora da solo con `machines.json` (vedi `machines.example.json`), come prima.
- Se il portale è giù il collector continua a registrare in locale e riprova ogni minuto.
- Ore: BasicDataSet `OperationTimeOverall` in secondi (÷ 3600). umati `OperationDuration` letto come ore: **da verificare su una macchina umati** confrontandolo con le ore del pannello (`hours_factor` in `MODELS`).

Contratto degli endpoint: `docs/moduli/assets_contatori_ingest.md`. L'endpoint del portale resta solo rete interna (`docs/ai/05_SECURITY_BOUNDARIES.md`).

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
