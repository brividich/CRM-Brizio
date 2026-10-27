# Runbook — Collector CNC

Componente in sola lettura: legge DMG MORI (OPC UA), Heidenhain (LSV2) e Fanuc (FOCAS). Codice in `django_app/assets/collector_cnc/`. Uso e garanzie: [README del collector](../../../django_app/assets/collector_cnc/README.md). Decisioni: [adr/](adr/).

## 1. Pilota su NOVISQL (2-3 giorni, in ombra)

1. Copia la cartella `django_app/assets/collector_cnc` in `C:\CollectorCnc` su NOVISQL.
2. Apri PowerShell **come utente normale** (non serve amministratore) in `C:\CollectorCnc`.
3. Prima volta:
   ```powershell
   .\avvia_collector.ps1 -Installa -FwlibPath C:\Fanuc\Fwlib64.dll
   ```
   Senza Internet aggiungi `-Wheelhouse .\wheels`; vedi il README per scaricare i pacchetti su un altro PC.
4. Controlla `pilota\machines.json`: le macchine attive sono DM6-MDC (.115), AGV1 (.105) e HYUNDAI (.117). Poi lancia:
   ```powershell
   .\avvia_collector.ps1 -Verifica
   .\avvia_collector.ps1 -Once
   ```
   Il JSON di `-Once` va confrontato con il pannello di ogni macchina.
5. Avvio del pilota:
   ```powershell
   .\avvia_collector.ps1 -DurataOre 72
   ```
   La finestra mostra il log. Tutto finisce anche in `pilota\logs\`: `collector.log` (5 MB × 5) e `console-*.log`.
6. Lo script svuota `PORTALE_URL`/`PORTALE_TOKEN` per il suo processo: **niente arriva al portale**. Se sul server gira anche il collector integrato del portale, lo script lo segnala: le DMG in comune avranno due sessioni OPC UA in lettura.
7. Fine del pilota: CTRL+C, oppure si ferma da solo dopo `-DurataOre`. Lo script stampa:
   - quanti avvii ci sono stati;
   - le righe ERROR;
   - i thread bloccati;
   - l'ultima riga di salute.

**Cosa guardare durante il pilota** (requisito della Fase 3):
- `salute:` ogni 10 minuti: la **memoria** deve restare stabile, cioè non salire giorno dopo giorno, e i **thread** devono restare costanti (uno per macchina LSV2/FOCAS più quelli di Python).
- `thread bloccati`: deve restare 0. Se sale, cerca «thread bloccato» nel log.
- Gli stati in `pilota\dati\status.json` e in `pilota\dati\<macchina>\<giorno>.jsonl` vanno confrontati con quello che si vede in officina.
- Nessun effetto sui controlli: chiedi agli operatori se compaiono messaggi o sessioni DNC strane sui pannelli Heidenhain.

## 2. Avvio e arresto

| Dove | Avvio | Arresto |
|---|---|---|
| Finestra PowerShell | `.\avvia_collector.ps1` | CTRL+C |
| Servizio Windows (NSSM) | `nssm start CollectorCnc` | `nssm stop CollectorCnc` (manda CTRL+C, attesa 15 s) |
| Linux (systemd) | `sudo systemctl start cnc-collector` | `sudo systemctl stop cnc-collector` (SIGTERM, attesa 30 s) |

Lo stop è sempre pulito:
- le attese si interrompono subito;
- le sessioni OPC UA e LSV2 si chiudono e gli handle FOCAS vengono liberati;
- gli intervalli aperti in machines.db si chiudono.

Un thread che non esce entro il timeout viene scritto nel log («thread non terminati»).

## 3. Dove sono i log e i dati

| Cosa | Dove |
|---|---|
| Log del collector | `logs/collector.log` (+ `.1` … `.5`), una riga per evento, con `[macchina driver host]` |
| Tutto quello mostrato a schermo dallo script | `pilota/logs/console-<data>.log` |
| Registro locale | `machines.db` (SQLite): `state_log`, `signal_log`, `alarm_log`, `counter_log`, `outbox` |
| Uscita JSONL | `dati/<macchina>/<AAAA-MM-GG>.jsonl`, `dati/status.json` |
| Esplorazione OPC UA | `browse_<macchina>.tsv` accanto a machines.json |

Query utili su machines.db, con `sqlite3 machines.db` o DB Browser for SQLite:

```sql
SELECT machine, state, start_utc, end_utc, program FROM state_log ORDER BY id DESC LIMIT 50;
SELECT machine, code, message, start_utc, end_utc FROM alarm_log ORDER BY id DESC LIMIT 50;
```

## 4. I 10 errori più probabili

| # | Nel log | Causa | Cosa fare |
|---|---|---|---|
| 1 | `non raggiungibile (… timed out)` | macchina spenta, cavo, VLAN, porta chiusa sul WatchGuard | `Test-NetConnection <ip> -Port 4840/19000/8193`; aprire la porta solo dall'host del collector |
| 2 | `-> NON_LEGGIBILE (login DNC rifiutato … opzione software #18)` | il controllo Heidenhain non ha l'opzione #18 | chiedere a Heidenhain/DMG l'opzione; fino ad allora la macchina resta «Non leggibile» (non OFFLINE) |
| 3 | `libreria Fwlib non trovata` / `non caricata` | `CNC_FWLIB_PATH` mancante o DLL a 32 bit con Python a 64 | indicare `Fwlib64.dll` con `-FwlibPath` o in `collector.env` |
| 4 | `rifiuta l'accesso anonimo (…Identity…)` | server OPC UA con utente obbligatorio (es. DM7) | `username` + `password_env` in machines.json, password in `collector.env` |
| 5 | `collector NON avviato: N errori nella configurazione` | machines.json non valido | `.\avvia_collector.ps1 -Verifica`, correggere le righe ERRORE |
| 6 | `cnc_statinfo = -16: connessione persa` | rete instabile o controllo Fanuc riavviato | si riconnette da solo con backoff; se continua, controllare la rete |
| 7 | `override_state disattivata … dopo 3 errori` | il controllo non supporta quella lettura | nessuna azione: la lettura non viene più chiamata (si riattiva alla riconnessione o al riavvio del collector) |
| 8 | `thread bloccato in una lettura da oltre …` | una chiamata alla libreria non risponde | il thread è stato sostituito da solo; se si ripete, segnalarlo con il log |
| 9 | `machines.db non scrivibile (database is locked)` | un altro programma ha il file aperto (DB Browser, antivirus, backup) | chiudere il programma: le scritture in attesa partono da sole |
| 10 | `l'orologio di sistema è saltato di …` | NTP o cambio ora manuale | controllare la sincronizzazione dell'ora del server; le durate restano corrette |

Altri: `matricola attesa … ma il server riporta …` significa che l'IP è cambiato (controllare machines.json); `nodo … assente, ignorato` è normale per i segnali che una macchina non ha.

## 5. Aggiungere una macchina

1. Aggiungi la riga in `machines.json` con `name`, `driver` e `ip` (vedi `machines.example.json`).
2. `.\avvia_collector.ps1 -Verifica`.
3. `.\avvia_collector.ps1 -Once NOME`, e confronta il JSON con il pannello.
4. Solo OPC UA non DMG: `py collector.py --config pilota\machines.json --browse NOME`, poi incolla `nodes` e le mappe `execution_map`/`mode_map`.
5. Riavvia lo script o il servizio.

## 6. Mettere una macchina in ombra o disabilitarla

- **Ombra** (`"ombra": true`): la macchina si legge e si salva in machines.db e nei JSONL, ma **non va al portale**. Le macchine nuove si aggiungono così.
- **Disabilitata** (`"enabled": false`): la macchina non si legge affatto. Con `--once NOME` si può comunque leggere una volta, per confronto.
- In entrambi i casi serve un riavvio. Con il collector configurato dal portale, le modifiche arrivano entro 5 minuti senza riavviare.

## 7. Piano di rollback

1. **Collector da solo** (pilota, PC):
   - fermalo (CTRL+C, `nssm stop`, `systemctl stop`);
   - per tornare alla versione precedente, ricopia la cartella `collector_cnc` dal commit precedente: `git show <commit>:django_app/assets/collector_cnc/...`, oppure `git archive <commit> django_app/assets/collector_cnc`;
   - machines.db resta compatibile: le versioni precedenti ignorano le tabelle `outbox`/`meta` e la colonna `cond_key`.
2. **Una macchina sola**: `"enabled": false`, oppure `"ombra": true` per smettere di inviare. Nessun riavvio del portale.
3. **Portale** (solo quando il ramo sarà deployato), la migrazione `assets 0157_collector_eventi_non_leggibile` è reversibile:
   ```powershell
   python django_app\manage.py migrate assets 0156 --settings=<settings>
   ```
   Poi si rideploya la release precedente. Le righe nello stato `non_leggibile` tornano a mostrare il codice grezzo finché la release vecchia è attiva.
4. **Collector integrato nel portale** (task `CollectorCnc_<ENV>`): con il deploy della release precedente il launcher riavvia da solo il codice vecchio.

## 8. Controlli prima di una release

```powershell
python django_app\manage.py test assets.tests_cnc --settings=config.settings.test
cd django_app; python -m mypy --strict --follow-imports=silent --ignore-missing-imports -p assets.collector_cnc
python -m ruff check django_app/assets/collector_cnc django_app/assets/tests_cnc
```
