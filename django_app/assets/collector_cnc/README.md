# Collector CNC (OPC UA) → NOVICROM HUB

Collector per le macchine DMG MORI con server OPC UA (IoTconnector): **legge soltanto** (nessuna scrittura, nessun metodo chiamato). Due modelli dati gestiti: **umati / OPC UA for Machine Tools** e **DMG MORI BasicDataSet** (`MODELS` in `collector.py`).

Si sceglie **dove gira** in **Asset › Configurazione › Macchine collegate › Dove gira il collector**. Le due modalità si escludono: le macchine non vengono mai lette due volte.

## Modalità «Sul server del portale» (consigliata se il server raggiunge le macchine)

Il collector gira dentro il portale e scrive direttamente nel database: niente PC dedicato, niente token.

- Requisito di rete: il server del portale deve raggiungere le macchine sulla porta OPC UA (di solito **4840**). Verifica dal server: `Test-NetConnection 192.168.23.115 -Port 4840`.
- Libreria: `asyncua` è in `requirements.txt`: arriva con `pip install -r requirements.txt` nel venv del portale.
- Servizio: `python manage.py collector_cnc`, lanciato all'avvio dal task `\PortaleNovicrom\CollectorCnc_<ENV>` con `deployment/start_collector_cnc.ps1` (stesso schema e stesso account del qcluster: riavvio automatico, log in `<ambiente>\logs\collector_cnc.log`).
- Installazione del task: Setup Wizard › Server Dashboard › riquadro **Collector CNC** › «Installa task» (stato, Avvia, Ferma e log nello stesso riquadro). Senza wizard: `deployment/scripts/install-collector-cnc-task.ps1 -Environment prod -Credential (Get-Credential 'DOMINIO\utente')`. «Registra schedule» non basta: registra solo gli schedule django-q.
- Aggiornamenti: quando si attiva una release nuova (il junction `current` cambia cartella) il collector esce da solo e il launcher lo riavvia col codice nuovo, entro un minuto più 15 secondi.
- Prova senza leggere: `python manage.py collector_cnc --prova` (modalità, macchine da leggere, ultimo segnale).
- Ogni minuto il servizio lascia un segnale di vita: la pagina Macchine collegate dice «Attivo / Fermo / Mai partito» e il controllo infrastruttura `collector_cnc` (Centrale di comando, /readyz) avvisa se si ferma.
- Registro dettagliato dei segnali: `<PRIVATE_ATTACHMENTS_ROOT>/collector_cnc/machines.db`.

## Modalità «Su un PC dell'officina»

Il collector gira su un PC della rete d'officina e parla con il portale via HTTP.

1. Nel portale, riquadro **Collector su un PC dell'officina**: «Crea il collector e il token» con l'IP del PC. Il token si vede **una volta sola**.
2. Sul PC: copia questa cartella (`collector.py`, `portale.py`), `pip install asyncua`, imposta le variabili d'ambiente `PORTALE_URL` (la pagina lo mostra accanto al token), `PORTALE_TOKEN` e, se l'HTTPS del portale è firmato dalla CA interna, `PORTALE_CA` (file .pem). Poi `py collector.py`.

| Cosa | Endpoint | Quando |
|---|---|---|
| elenco delle macchine | `GET /api/assets/contatori/ingest/config/` | all'avvio e ogni 5 minuti |
| stato, programma, modalità, pezzi, allarmi | `POST /api/assets/contatori/ingest/stato/` | a ogni cambio (entro 5 s) e comunque ogni minuto |
| contatori **Ore** e **Cicli** | `POST /api/assets/contatori/ingest/` | ogni ora |

- L'ultimo elenco scaricato resta in `machines.portale.json` accanto allo script (contiene le password OPC UA: resta sul PC, fuori dal repository).
- Senza `PORTALE_URL`/`PORTALE_TOKEN` lavora da solo con `machines.json` (vedi `machines.example.json`).
- Con la modalità «Sul server del portale» l'elenco che riceve è vuoto: il PC smette di leggere entro 5 minuti.

## In entrambe le modalità

- **Macchine**: «Collega una macchina» › *Collector OPC UA* › indirizzo OPC UA (IP), porta (4840), codice breve (es. DM6), utente e password OPC UA solo se la macchina non accetta l'accesso anonimo (password cifrata). «Crea i contatori Ore e Cicli se mancano».
- **Cerca le macchine in rete** (amministratori): il portale prova la rete indicata (al massimo /24, solo interna) sulla porta OPC UA, legge matricola e modello dati dal namespace DMG MORI (`cerca.py`, sola lettura) e abbina ogni server all'asset: matricola già vista, indirizzo già collegato, numero di serie.
- Le macchine aggiunte, tolte o cambiate nel portale partono o si fermano entro 5 minuti, senza riavviare il collector.
- Il collector manda nello stato anche il valore grezzo delle ore (`ore_lette`), la matricola letta dal server (`matricola`) e il modello dati (`modello`): il portale li mostra in Macchine collegate e usa la matricola come `serial` dell'elenco (niente più avvisi «matricola attesa … ma il server riporta …» quando l'asset ha un'altra matricola).
- Ore: BasicDataSet `OperationTimeOverall` in secondi (÷ 3600). umati `OperationDuration` letto come ore: **da verificare su una macchina umati** confrontandolo con il pannello. Se non torna, l'unità si cambia dal portale («Le ore lette dalla CNC sono in», `hours_unit` nell'elenco): il portale converte le ore dal valore grezzo e ricalcola subito il contatore Ore.
- Avviso a ore (ogni N ore di lavoro) e report «Utilizzo delle CNC»: tutto nel portale, il collector non cambia.

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
