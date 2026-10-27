# Collector CNC → NOVICROM HUB

Collector delle CNC dell'officina, **in sola lettura**: DMG MORI via OPC UA (box MDC, CELOS X; modelli dati **umati / OPC UA for Machine Tools** e **DMG MORI BasicDataSet**, oppure una mappa di nodi scritta in configurazione), **Heidenhain** iTNC 530 / TNC 640 via **LSV2** (pyLSV2) e **Fanuc** via **FOCAS** (Fwlib). Gira in due modi:

- **da solo** (pilota, PC dell'officina, VM Linux): `py collector.py --config machines.json`, oppure `avvia_collector.ps1` su Windows. Vedi «Uso da riga di comando» qui sotto;
- **con il portale**, configurato da Asset › Configurazione › Macchine collegate. Vedi le sezioni sul portale più sotto. Per ora dal portale si configurano solo le macchine OPC UA.

Runbook operativo (avvio, log, errori frequenti, ombra, rollback): [`docs/assets/collector_cnc/RUNBOOK.md`](../../../docs/assets/collector_cnc/RUNBOOK.md). Decisioni: [`docs/assets/collector_cnc/adr/`](../../../docs/assets/collector_cnc/adr/).

## Garanzie di sola lettura

- Nessuna scrittura verso l'NC: niente parametri, variabili, macro, file, programmi, tabelle utensili, segnali PLC; niente trasferimento di file; niente start/stop/reset/selezione programma.
- **Whitelist per driver** (`drivers/`): ogni libreria passa da `ProxySolaLettura` (`drivers/base.py`), che lascia chiamare solo un `frozenset` di letture, anche sugli oggetti restituiti (nodi OPC UA, dati pyLSV2, funzioni Fwlib). Qualunque altro nome solleva `PermissionError`.

  | Driver | Ammesso |
  |---|---|
  | OPC UA (asyncua) | client: `connect`, `disconnect`, `get_namespace_array`, `get_node`, `read_attributes`, `read_values`; nodi: `nodeid`, `read_browse_name`, `get_children`, `read_value` |
  | LSV2 (pyLSV2 1.8) | `connect`, `disconnect`, `versions`, `execution_state`, `program_status`, `program_stack`, `override_state`, `get_error_messages` |
  | FOCAS (Fwlib) | `cnc_allclibhndl3`, `cnc_freelibhndl`, `cnc_statinfo`, `cnc_exeprgname`, `cnc_actf`, `cnc_acts`, `cnc_rdparam` (solo param. 6711), `cnc_startupprocess`/`cnc_exitprocess` (Linux) |

- **Verifiche automatiche** in `assets/tests_cnc/`:
  - una «spia» registra ogni chiamata alle librerie durante esecuzioni complete contro i simulatori, e la confronta con la whitelist;
  - un controllo statico cerca in `drivers/` i nomi di scrittura elencati in `vietati.py`;
  - un test fissa le whitelist esatte.
- LSV2: `safe_mode=False` serve solo per il login DNC, che è necessario per leggere lo stato. `connect()` di pyLSV2 fa il login INSPECT e FILETRANSFER: sono diritti di sessione, e le funzioni sui file non sono raggiungibili. Con `compatibility_mode` non manda comandi di sistema.
- **Basso impatto**:
  - una sola connessione persistente per macchina;
  - polling ogni 5 s (mai sotto 2 s, anche se la configurazione dice meno), con jitter ±5 % e avvio scaglionato;
  - con la macchina irraggiungibile, backoff da `poll` fino a 300 s;
  - una lettura che fallisce 3 volte di seguito non viene più chiamata su quella macchina.

## Porte da aprire sul WatchGuard

Solo **dall'host del collector verso la VLAN macchine**, in uscita TCP:

| Porta | Protocollo | Macchine |
|---|---|---|
| 4840 | OPC UA (box MDC, CELOS X) | DMG MORI |
| 19000 | Heidenhain LSV2 | AGV1-3, DM3, DM14, DM6 (confronto) |
| 8193 | Fanuc FOCAS | HYUNDAI |

Nessuna porta in ingresso verso l'host del collector. Verifica: `Test-NetConnection 192.168.23.105 -Port 19000`.

## Installazione (da solo)

1. Copia la cartella `collector_cnc` sull'host del collector (tutta, con `drivers/`).
2. **Windows**: `.\avvia_collector.ps1 -Installa`. Crea `pilota\.venv` e installa `requirements-collector.txt`. Senza Internet:
   - su un PC con Internet: `py -m pip download -r requirements-collector.txt -d wheels`;
   - copia la cartella `wheels` sull'host;
   - lancia `-Installa -Wheelhouse .\wheels`.
3. **Linux**: `python3 -m venv .venv && .venv/bin/pip install -r requirements-collector.txt`.
4. **Fanuc**: la libreria Fwlib non è su PyPI e non sta nel repository. Imposta `CNC_FWLIB_PATH` (file o cartella) in `collector.env` o con `-FwlibPath`:
   - Python a 64 bit vuole `Fwlib64.dll`;
   - su Linux serve `libfwlib32.so`.
5. Python 3.11 o più recente. Dipendenze: solo libreria standard più asyncua e pyLSV2.

## Uso da riga di comando

```text
py collector.py --config machines.json                   servizio, silenzioso (log solo su file)
py collector.py --config machines.json -v                servizio con il log anche a schermo
py collector.py --config machines.json --check-config    valida la configurazione senza connettersi
py collector.py --config machines.json --once            una lettura di ogni macchina abilitata, JSON a schermo
py collector.py --config machines.json --once DM6        solo DM6 (anche se disabilitata: confronto LSV2/MDC)
py collector.py --config machines.json --browse DM6-MDC  esplora lo spazio OPC UA e propone i nodi
py collector.py --config machines.json --jsonl dati      anche dati/<macchina>/<giorno>.jsonl e dati/status.json
                                       --durata-ore 72   si ferma da solo dopo 72 ore
```

- **Log**:
  - su file a rotazione, 5 MB × 5 (`collector.log`, o `log_file` nella configurazione);
  - a schermo solo con `-v`;
  - asyncua e pyLSV2 solo a livello ERROR; il trasporto di pyLSV2 è muto, perché il collector segnala già lui il cambio di stato;
  - ogni riga porta `[macchina driver host]`;
  - gli errori ripetuti si scrivono solo al cambio di stato;
  - ogni 10 minuti c'è una riga `salute:` con memoria, thread, stati, thread bloccati e code.
- **`--check-config`** segnala come errori:
  - driver sconosciuto, host non valido o duplicato (stesso host e porta);
  - polling sotto 2 s;
  - password in chiaro;
  - variabile d'ambiente della password mancante, Fwlib non trovata;
  - NodeId non validi, codici di `execution_map` sconosciuti.

  Con errori **il servizio non parte** (codice 2): niente avvio parziale silenzioso. L'esistenza dell'`asset_tag` nel portale la verifica il portale all'invio (riga «asset sconosciuto»).
- **`--once`** non scrive niente su disco. Codice 0 se tutte le macchine sono leggibili, 1 altrimenti; lo stato e il motivo sono nel JSON.
- **`--browse`**:
  - parte da `Objects`, escluso `Objects/Server`, con al massimo 8 livelli e 20 000 nodi (`--profondita`, `--max-nodi`);
  - salva `browse_<macchina>.tsv` con nodeid, percorso, classe, tipo e valore;
  - stampa i 5 nodi più probabili per ogni campo e uno snippet `nodes` da incollare;
  - riconosce OPC 40501 (umati), un modello derivato da MTConnect e DMG MORI BasicDataSet.

  Per le DMG MORI la mappa non serve: il collector conosce già i loro modelli.

### machines.json

Esempio completo: `machines.example.json`. Contiene le macchine pilota DM6-MDC, AGV1 e HYUNDAI; le altre sono già scritte con `"enabled": false`.

```json
{"collector": {"poll_seconds": 5, "heartbeat_seconds": 300, "log_file": "logs/collector.log"},
 "machines": [
   {"name": "AGV1", "driver": "lsv2", "ip": "192.168.23.105"},
   {"name": "DM7", "driver": "opcua", "ip": "192.168.23.20", "username": "LETTORE", "password_env": "CNC_DM7_PASSWORD"},
   {"name": "X1", "driver": "opcua", "ip": "192.0.2.10", "nodes": {"exec": "ns=2;s=State", "program": "ns=2;s=Prog"},
    "execution_map": {"0": "RUNNING", "1": "INTERRUPTED", "2": "IDLE"}, "mode_map": {"0": "AUTO", "1": "MDI"}}
 ]}
```

Campi di una macchina:

| Campo | Significato |
|---|---|
| `name`, `ip` | obbligatori |
| `driver` | `opcua` (default), `lsv2` o `focas` |
| `port` | default 4840, 19000 o 8193 |
| `poll_seconds`, `timeout` | ritmo di lettura e timeout delle chiamate |
| `enabled` | `false` = la macchina non si legge |
| `ombra` | `true` = si legge e si salva, ma non si manda al portale |
| `asset_tag` | solo se la macchina va al portale |
| `username`, `password_env` | credenziali OPC UA: la password **mai nel file**, solo il nome della variabile d'ambiente (`collector.env`) |
| `fwlib_path` | libreria Fanuc per questa macchina |
| `nodes`, `execution_map`, `mode_map`, `hours_factor` | OPC UA con mappa di nodi |

**Aggiungere una macchina**:
1. Aggiungi la riga in `machines.json`.
2. Lancia `--check-config`.
3. Lancia `--once NOME` e confronta il JSON con il pannello della macchina.
4. Riavvia il servizio.

Per una DMG che non è riconosciuta da sola, prima usa `--browse NOME` e incolla `nodes`.

### Stati

| Collector | Quando |
|---|---|
| `LAVORO` | programma in esecuzione in automatico (Heidenhain: STARTED + AUTOMATIC; Fanuc: run START/MSTR in MEM/RMT) |
| `SETUP` | in esecuzione in MDI, manuale, passo singolo o riferimenti |
| `INTERROTTA` | programma fermato o in pausa (Heidenhain STOPPED/INTERRUPTED; Fanuc STOP/HOLD) |
| `FERMA` | nessun programma in corso (Heidenhain IDLE/FINISHED/CANCELLED; Fanuc RESET) |
| `ALLARME` | allarme attivo (OPC UA severità ≥ 801; Heidenhain ERROR; Fanuc alarm ≠ 0) |
| `EMERGENZA` | emergenza (Fanuc: emergency ≠ 0, priorità massima) |
| `OFFLINE` | macchina non raggiungibile o nessuna lettura recente: intervallo esplicito con inizio e fine |
| `NON_LEGGIBILE` | risponde ma non dà lo stato (Heidenhain senza opzione #18 DNC, Fwlib mancante) |

Tabelle complete in `stati.py`. Cicli Heidenhain: +1 sul fronte verso FINISHED, solo se era in AUTOMATIC. Pezzi Fanuc (param. 6711): la prima lettura è la base, poi si somma il delta; un azzeramento non sottrae niente. I totali ripartono da machines.db.

## Uscite

- `machines.db` (sempre): intervalli di stato, cambi di segnale, allarmi, contatori, coda verso il portale. Se il file è bloccato le scritture restano in coda in memoria e si applicano dopo, nell'ordine.
- `--jsonl DIR` (facoltativa, interfaccia `Sink` in `sink.py`):
  - `DIR/<macchina>/<AAAA-MM-GG>.jsonl` a ogni cambio e ogni `heartbeat_seconds` (300 s di default);
  - `DIR/status.json` con l'ultimo stato di ogni macchina, scritto in modo atomico.

  Un'uscita nuova (PostgreSQL, MQTT) si aggiunge implementando `Sink.write(record)`.
- Portale (solo con `PORTALE_URL` e `PORTALE_TOKEN`): store-and-forward in ordine, con eventi idempotenti (ADR 0004).

## Servizio Windows con NSSM

```powershell
nssm install CollectorCnc "C:\CollectorCnc\pilota\.venv\Scripts\python.exe" "C:\CollectorCnc\collector.py --config C:\CollectorCnc\pilota\machines.json --db C:\CollectorCnc\pilota\machines.db --log-file C:\CollectorCnc\pilota\logs\collector.log --jsonl C:\CollectorCnc\pilota\dati"
nssm set CollectorCnc AppDirectory C:\CollectorCnc
nssm set CollectorCnc AppEnvironmentExtra CNC_FWLIB_PATH=C:\Fanuc\Fwlib64.dll
nssm set CollectorCnc AppStopMethodConsole 15000
nssm set CollectorCnc AppExit Default Restart
nssm set CollectorCnc AppRestartDelay 30000
nssm start CollectorCnc
```

- Le password OPC UA vanno in `AppEnvironmentExtra`, non in `machines.json`.
- `AppStopMethodConsole` manda CTRL+C: il collector chiude sessioni e handle prima di uscire.

## Unit systemd (VM Linux)

File di esempio: `systemd/cnc-collector.service`. Installazione:

```bash
sudo cp systemd/cnc-collector.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cnc-collector
journalctl -u cnc-collector -f      # avvio/arresto; il log del collector è in /opt/cnc-collector/logs
```

SIGTERM ferma il collector in modo pulito: chiude le sessioni e libera gli handle FOCAS. Il riavvio automatico avviene con `Restart=on-failure`; con una configurazione non valida (codice 2) non riparte.

## Qualità

```powershell
python django_app\manage.py test assets.tests_cnc --settings=config.settings.test
python -m mypy --strict --follow-imports=silent --ignore-missing-imports -p assets.collector_cnc   # da django_app
python -m ruff check django_app/assets/collector_cnc django_app/assets/tests_cnc
```

---

## Con il portale

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
2. Sul PC: copia questa cartella (`collector.py`, `portale.py`, `cerca.py`, `vietati.py` e la sottocartella `drivers/`), `pip install asyncua`, imposta le variabili d'ambiente `PORTALE_URL` (la pagina lo mostra accanto al token), `PORTALE_TOKEN` e, se l'HTTPS del portale è firmato dalla CA interna, `PORTALE_CA` (file .pem). Poi `py collector.py`.

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

## Stati nel portale

| Collector | Portale | Quando |
|---|---|---|
| `LAVORO` | In lavoro | programma in esecuzione in automatico |
| `SETUP` | Lavoro MDI/manuale | in esecuzione in MDI o manuale |
| `INTERROTTA` | Interrotta | programma interrotto |
| `FERMA` | Ferma | nessun programma in corso |
| `ALLARME` | In allarme | messaggio attivo con severità ≥ 801 (o allarmi attivi nel BasicDataSet) |
| `EMERGENZA` | Emergenza | emergenza premuta |
| `OFFLINE` | Offline | server OPC UA non raggiungibile |
