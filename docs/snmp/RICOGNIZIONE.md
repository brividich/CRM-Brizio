# Ricognizione SNMP — FASE 0

Data: 2026-10-02 · Base: `origin/main` `a2671499` (il modulo `contatori` è identico a `release/prod` `9257612f`).
Solo lettura: nessun codice modificato in questa fase.

## 1. App e moduli coinvolti

| Area | File | Ruolo |
|---|---|---|
| App `contatori` (il "contatori_hub" del task) | `django_app/contatori/` | Centrale MFC + Centrale SNMP generica (`/contatori/snmp/…`) |
| Trasporto SNMP | `contatori/snmp.py` | GET/WALK, discovery di rete, contatori Canon, consumabili |
| Printer-MIB | `contatori/printer_snmp.py` | Contatori e consumabili per indice, indipendenti dal vendor |
| Logica | `contatori/services.py` | Detection profilo, applicazione profilo → sonde, `interroga_dispositivo`, `interroga_macchina`, match asset |
| Job | `contatori/tasks.py` + `automazioni/schedules.py` | django-q2 |
| Cifratura | `contatori/credential_crypto.py` | Fernet con chiave derivata da `SECRET_KEY` |
| Comandi | `snmp_discover`, `poll_snmp_devices`, `leggi_contatori[_mensili]`, `collega_asset`, `seed_demo` | Diagnostica e operatività |
| Legame asset | `assets/services/it_monitoring.py`, `assets/templates/assets/partials/it_monitoring.html` | Snapshot in sola lettura nella scheda asset (filtrato da ACL) |

Legame con `assets.Asset`:
- `Macchina.asset` e `DispositivoSNMP.asset` sono FK nullable (`SET_NULL`).
- `services.trova_asset_snmp()` cerca prima `Asset.serial_number__iexact`, poi `AssetEndpoint.ip`. In caso di ambiguità non sceglie.
- La scheda asset legge **solo** l'ultima `RilevazioneSNMP` (stato, contatori e consumabili stampante) e l'ultima `LetturaMensileContatori`. Non avvia mai un polling.
- **Nessun valore SNMP viene scritto sull'asset** (`manufacturer`/`model`/`serial_number`, `AssetITDetails`). Le uniche scritture "di identità" sono su `DispositivoSNMP`: `sys_*` sempre, `produttore` se vuoto, `matricola` se vuota.

## 2. Formato dei preset

I preset sono **righe DB**, non JSON/YAML:
- `ProfiloSNMP`: slug, produttore, categoria (`STAMPANTE`, `FIREWALL`, `RETE`, `SERVER`, `STORAGE`, `UPS`, `AMBIENTE`, `GENERICO`), `sys_object_id_prefix`, `sys_descr_pattern` (regex), versione/porta/timeout di default, `precaricato`.
- `ColonnaProfiloSNMP`: nome, OID, `tipo_valore` (NUMERO/TESTO/TIMETICKS), `modalita` (GET/WALK), `aggregazione` (PRIMO/MASSIMO/MINIMO/SOMMA), unità, `fattore`, `contatore_mfc` (a4_bn…).
- Seed: migrazione `0009_seed_profili_snmp.py` (RunPython, `update_or_create` per slug/oid).

Selezione del preset (`services.trova_profilo_snmp`):
- Match per prefisso di `sysObjectID` (vince il più lungo) o per regex su `sysDescr`.
- Se più profili hanno lo stesso prefisso e nessuno corrisponde per `sysDescr`, restituisce `None`: niente assegnazione a caso.
- Avviene solo al primo polling se `profilo_snmp` è vuoto. `applica_profilo_dispositivo` materializza le colonne come `SondaSNMP` e cancella le sonde generate da altri profili, preservando quelle manuali.

Mappatura dei valori: ogni sonda produce un `ValoreSNMP` (numero o testo) dentro una `RilevazioneSNMP`. È uno **scalare per OID**: le colonne WALK vengono ridotte a un solo valore. Non esiste un concetto di tabella indicizzata, di chiave normalizzata, di catena di fallback o di transform: solo `÷100` per TIMETICKS e `× fattore`. L'eccezione sono le stampanti: `dati_stampante` (JSON) contiene liste indicizzate.

Soglie: `SondaSNMP.soglia_{warning,critica}_{min,max}` per singola sonda; non esistono soglie a livello di profilo.

## 3. Motore di polling

- Libreria: **puresnmp 2.0.1** (+ x690), asyncio. Ogni funzione chiama `asyncio.run()` → dall'esterno è sincrona. Import lazy.
- Operazioni:
  - `client.get` sequenziale per OID (`leggi_oids`);
  - `client.walk` = **GETNEXT** (`leggi_colonna`, `_tabella`, `printer_snmp`);
  - **GETBULK non è mai usato**, anche se `bulkwalk`/`bulktable` sono disponibili.
- Timeout:
  - `send_udp(timeout=…)` per pacchetto;
  - budget complessivi: `SPECIFICATION_BUDGET` 30 s, `WALK_BUDGET` 10 s, 20 s per colonna stampante;
  - limiti righe: `MAX_WALK_ROWS` 256, 128 righe per colonna stampante.
- Retry: **non configurati**. Vale il default di `puresnmp.transport.send_udp` (`retries=10`), quindi un host muto consuma l'intero budget anziché 3 s × 2 retry.
- Schedulazione django-q2 (`automazioni/schedules.py`):
  - `contatori_poll_snmp` ogni **5 min** → `run_poll_snmp` accoda un job per dispositivo (timeout 110 s, lock in cache per evitare duplicati);
  - `contatori_letture_mensili` cron `0 8 1 * *`.
- Concorrenza: la limita solo il numero di worker del qcluster. Non c'è backoff sui dispositivi irraggiungibili: chi è in errore viene ripollato ogni 5 minuti.
- Health e inventario non sono distinti: ogni poll rilegge sempre `SYSTEM_OIDS` e tutte le sonde.
- Discovery di rete: `scansiona_hosts` (fino a 512 host, concorrenza 32, fino a 8 community provate in ordine) in job persistente `DiscoverySNMP`.

## 4. SNMPv3 e credenziali

- **SNMPv3 non supportato**: le scelte disponibili sono solo `v1`/`v2c` (`ProfiloSNMP`, `DispositivoSNMP`, `CommunitySNMP`, `ImpostazioniSNMP`, validazione in `scansiona_hosts`).
- puresnmp 2.0.1 ha la classe `V3`, ma i plugin installati sono auth `md5`/`sha1` e priv solo `example.py`. **Per AES/DES manca il pacchetto `puresnmp-crypto`**; SHA-2 non è disponibile. Prima di promettere authPriv serve aggiungere la dipendenza, aggiornare `requirements.in`/`.txt` (attenzione al pip-compile Windows) e fare una verifica su device reale.
- Dove stanno le community oggi:
  - `CommunitySNMP.segreto_cifrato`: Fernet, chiave HMAC(`SECRET_KEY`), supporta `SECRET_KEY_FALLBACKS`, mai mostrata nei form. È la strada corretta.
  - **In chiaro nel DB**: `ImpostazioniSNMP.community` (nessun default dalla migrazione `contatori 0028`), `Macchina.snmp_community`, `DispositivoSNMP.community`.
  - ~~Il default della community era scritto nel codice~~: rimosso (ottobre 2026, migrazione `contatori 0028`). Senza community configurata la lettura si ferma con l'errore `SNMP-008`.
- Ordine di precedenza: community salvata > override manuale > globale.
- I messaggi d'errore riportano `str(exc)` di puresnmp con l'host: da verificare che non includano mai la community (in v1/v2c puresnmp normalmente non la stampa).

## 5. Preset esistenti (migrazione 0009) e gap

37 profili. Le colonne sono generiche per categoria e **identiche per tutti i vendor** della categoria:

| Categoria | Profili (PEN) | Colonne |
|---|---|---|
| STAMPANTE | canon-ir-adv (1602), kyocera (1347), hp-printer (11), ricoh (367), xerox (253), brother (2435), lexmark (641), epson (1248), sharp (1536), konica-minolta (18334), toshiba (186), oki (2001), samsung (236), zebra (10642) | `43.10.2.1.4` WALK MASSIMO. Solo Canon ha anche i 4 GET `1602.1.11.1.3.1.4.{113,112,123,122}` |
| FIREWALL | fortinet (12356), palo-alto (25461), sophos (2604), check-point (2620), sonicwall (8741) | `2.2.1.10` / `2.2.1.16` WALK SOMMA (ifIn/OutOctets a 32 bit) |
| RETE | cisco (9), juniper (2636), mikrotik (14988), ubiquiti (41112), hpe-aruba (11) | come FIREWALL |
| SERVER | dell (674), hpe (232), lenovo (19046), supermicro (10876), vmware (6876), microsoft (311), net-snmp (8072) | `25.1.6.0` processi, `25.1.5.0` utenti |
| STORAGE | synology (6574), qnap (24681), netapp (789) | **nessuna** |
| UPS | apc (318), eaton (534), vertiv (476) | UPS-MIB `33.1.2.{1,2,3,4}.0` |

OID letti sempre per ogni dispositivo (`SYSTEM_OIDS`): sysDescr, sysObjectID, sysUpTime, sysContact, sysName, sysLocation, `43.5.1.1.17.1` (seriale Printer-MIB, indice fisso `.1`).

Problemi rilevati:
1. **Manca il profilo WatchGuard** (PEN 3097): il firewall aziendale non viene riconosciuto.
2. **Rischio di detection errata HPE switch → stampante**. Il profilo `hp-printer` ha prefisso `…4.1.11` e regex `HP|LaserJet|PageWide`. Il `sysDescr` ProCurve tipico ("HP J9729A 2920-48G…") contiene "HP" e non "ProCurve"/"Aruba", quindi passa la regex di `hp-printer` e non quella di `hpe-aruba`. Il pareggio di prefisso viene risolto a favore di `hp-printer` → categoria STAMPANTE → walk Printer-MIB sullo switch. Da confermare col walk; la correzione è usare prefissi più specifici (`11.2.3.7.11` switch, `11.2.3.9` stampanti) **dopo** la verifica.
3. Le colonne di rete sommano contatori a 32 bit di tutte le interfacce: wrap su link ≥ 100 Mb/s e un valore senza significato operativo. Mancano ifHC*, stato porte ed errori.
4. SERVER: processi/utenti hanno scarso valore. Mancano CPU, RAM, storage e hardware vendor.
5. STORAGE: zero colonne → Synology monitorato solo con `sys*`.
6. UPS: UPS-MIB RFC 1628 è spesso disattivato sugli APC (che espongono PowerNet-MIB `318`). Nessun fallback.
7. Nessun modulo comune: ENTITY-MIB (seriale/modello/fw), IF-MIB tabellare, HOST-RESOURCES storage/CPU, LLDP, Q-BRIDGE, POE, UCD-SNMP.
8. Nessun campo `verified`/fonte: gli OID sono "da MIB standard / PEN IANA", senza walk reali.

Gap rispetto al catalogo della FASE 2: della parte identity esistono solo hostname/location/contact/uptime come campi del dispositivo (vendor = produttore del profilo; model, serial e firmware mancano, il serial c'è solo per le stampanti). Dalle sezioni hardware, network, storage_health, power (eccetto 4 scalari UPS-MIB) e virtualization **non esiste nulla**. printing è parziale (vedi §6).

## 6. Stampanti: cosa si legge e cosa manca

Letto oggi:
- `interroga_dispositivo` + `printer_snmp.leggi_stampante`:
  - `prtMarkerLifeCount` `43.10.2.1.4` + `prtMarkerCounterUnit` `.3` per indice;
  - supplies `.6` desc, `.8` max, `.9` level (−3 → "presente", −2/altro → "non comunicato");
  - seriale `43.5.1.1.17.1`.
- Macchine MFC (`Macchina`): 4 contatori Canon (`1602.1.11.1.3.1.4.N`, COUNTER_MAP validata su C5840i) e consumabili (`snmp.leggi_consumabili`).

Esposto da Printer-MIB/HOST-RESOURCES ma non letto:
- `prtMarkerSuppliesType` `.11.1.1.5`, `SuppliesUnit` `.7`, `prtMarkerColorantValue` `43.12.1.1.4`: colore e tipo del consumabile (oggi solo dalla descrizione testuale).
- `prtCoverStatus` `43.6.1.1.3`, cassetti `prtInputTable` `43.8.2.1` (.9 capacità, .10 livello, .13 nome), avvisi `prtAlertTable` `43.18.1.1` (.8 descrizione).
- `hrDeviceStatus` `25.3.2.1.5`, `hrPrinterStatus` `25.3.5.1.1`, `hrPrinterDetectedErrorState` `25.3.5.1.2` (bitmask: carta esaurita, inceppamento, toner basso…).
- Display console `43.16.5.1.2`, `prtGeneralPrinterName` `43.5.1.1.16`.
- Modello e firmware: `hrDeviceDescr` `25.3.2.1.3`, ENTITY-MIB.
- Contatori Canon per tipo oltre ai 4 contrattuali (totale, scansioni, A3 per colore…): la tabella `1602.1.11.1.3.1.4` viene percorsa con walk, ma vengono tenuti solo 4 indici.
- Il seriale è letto con indice fisso `.1`: su device con `hrDeviceIndex` diverso risulta vuoto.
- Ogni poll di 5 minuti rilegge anche dati da inventario.

## 7. Test esistenti

138 test circa, tutti offline con mock di puresnmp e delle funzioni di `snmp.py`. **Non ci sono fixture `.snmprec`, né snmpsim.**

| File | Test | Copertura |
|---|---|---|
| `tests.py` | 55 | riconciliazione, monotonia, Canon `leggi_macchina`, consumabili, viste |
| `tests_snmp_centrale.py` | 27 | profili, detection, sonde, soglie, interroga_dispositivo |
| `tests_discovery_background.py` | 27 | job discovery, catalogo community cifrato |
| `tests_schedules.py` | 10 | schedule django-q |
| `tests_snmp_discovery.py` | 7 | scansione rete |
| `tests_printer_autodetect.py` | 6 | Printer-MIB, autodetect stampante |
| `tests_snmp_timeout.py` | 6 | budget/timeout |
| `assets/tests_it_infrastructure.py`, `tests_reporting.py` | — | snapshot nella scheda asset |

Non esiste alcun test che vieti le SET. Oggi nel modulo non ci sono chiamate `set`/`multiset` (verificato con grep), ma puresnmp le espone.

## Conseguenze per le fasi successive

- **FASE 1**:
  - `snmp_capture` con `bulkwalk` di puresnmp: GETBULK c'è, ma va gestito il limite di righe, perché il walk da `.1` è senza cap;
  - per v3 serve prima `puresnmp-crypto`;
  - `retries` va passato esplicitamente a `send_udp`.
- **FASE 2**: proposta compatibile, da estendere senza riscrivere.
  - Moduli e campi come nuove tabelle (`ModuloSNMP`, `CampoSNMP` con `key`, `oids` JSON, `kind`, `transform`, `scope`, `verified`, `fonte`) collegate a `ProfiloSNMP`.
  - Restano `ColonnaProfiloSNMP`/`SondaSNMP` per le sonde manuali e per i contatori MFC.
  - Le osservazioni normalizzate vanno in una tabella nuova, non in `ValoreSNMP`.
- **FASE 4**: l'asset non viene mai scritto oggi → `AssetSnmpObservation` è additivo, senza rischio di regressione sui dati dichiarati.
- **FASE 5**: tre campi community in chiaro da migrare verso `CommunitySNMP`, più il default hardcoded da rimuovere.
- **Regressione stampanti**: bloccare con test l'output attuale di `interpreta_stampante`, `leggi_macchina` (Canon) e `leggi_consumabili` prima di toccare il motore.
