# Catalogo preset SNMP verificati

Ogni OID qui elencato è stato **letto su un walk reale** (`snmp_capture`). La fixture pseudonimizzata è in `django_app/contatori/fixtures/snmp/`, i test in `contatori/tests_snmp_preset.py`. Le colonne compaiono nel profilo con **Verificata** e la fonte.

I valori dell'ultima rilevazione compaiono anche nella **scheda asset** collegata al dispositivo, sezione «Dati dal monitoraggio». I codici di stato si leggono come testo grazie al campo **Etichette** della colonna (`1=Normale, 2=Guasto`).

Gli OID non ancora verificati restano nei profili originali (migrazione 0009) con "Da verificare".

## Synology DSM — profilo `synology`

Fonte: walk di un RS2423RP+ con DSM 7.4-90080, 2026-10-02. Fixture: `synology_rs2423rp_dsm74.snmprec`.

**Riconoscimento.** DSM si presenta con `sysObjectID` net-snmp (`1.3.6.1.4.1.8072.3.2.10`) e con `sysDescr` "Linux …": col solo prefisso il NAS finiva nel profilo Linux. Il profilo ha ora un **OID di riconoscimento**, `1.3.6.1.4.1.6574.1.5.1.0` (modello): se risponde, vince il profilo Synology.

| Colonna | OID | Lettura | Soglie (avviso / critico) | Note |
|---|---|---|---|---|
| Modello | `1.3.6.1.4.1.6574.1.5.1.0` | GET testo | — | es. RS2423RP+ |
| Seriale | `1.3.6.1.4.1.6574.1.5.2.0` | GET testo | — | |
| Versione DSM | `1.3.6.1.4.1.6574.1.5.3.0` | GET testo | — | |
| Stato sistema | `1.3.6.1.4.1.6574.1.1.0` | GET | — / > 1 | 1 normale, 2 guasto |
| Temperatura sistema | `1.3.6.1.4.1.6574.1.2.0` | GET °C | > 55 / > 65 | |
| Alimentazione | `1.3.6.1.4.1.6574.1.3.0` | GET | — / > 1 | 1 normale, 2 guasto |
| Ventola sistema | `1.3.6.1.4.1.6574.1.4.1.0` | GET | — / > 1 | |
| Ventola CPU | `1.3.6.1.4.1.6574.1.4.2.0` | GET | — / > 1 | |
| Aggiornamento DSM disponibile | `1.3.6.1.4.1.6574.1.5.4.0` | GET | — | 1 disponibile, 2 nessuno |
| Stato peggiore dischi | `1.3.6.1.4.1.6574.2.1.1.5` | WALK massimo | > 1 / > 3 | 1 normale … 5 guasto |
| Salute peggiore dischi | `1.3.6.1.4.1.6574.2.1.1.13` | WALK massimo | > 1 / > 2 | 1 normale, 2 attenzione, 3 critico, 4 in guasto |
| Temperatura massima dischi | `1.3.6.1.4.1.6574.2.1.1.6` | WALK massimo °C | > 50 / > 60 | |
| Stato peggiore volumi/RAID | `1.3.6.1.4.1.6574.3.1.1.3` | WALK massimo | > 1 / > 10 | 2–10 operazioni in corso, 11 degradato, 12 guasto |
| + 4 colonne net-snmp | vedi sotto | | | |

Le enumerazioni di stato seguono la Synology MIB Guide; nel walk tutti i valori sono 1 (normale).

**Visti nel walk ma non ancora nel preset**: richiedono una lettura per riga, che il motore attuale non ha.
- Tabella dischi `6574.2.1.1`: `.2` nome, `.3` modello, `.4` tipo, `.7` ruolo, `.9` settori danneggiati, `.11` vita residua (−1 = non comunicata), `.12` nome slot.
- Volumi/RAID `6574.3.1.1`: `.2` nome, `.4` byte liberi, `.5` byte totali. Il totale coincide con hrStorage `/volume1`. Uno spazio libero "minimo" sull'intera tabella darebbe falsi allarmi, perché lo storage pool risulta normalmente quasi tutto allocato.
- SMART `6574.5.1.1` (144 righe), I/O dischi `6574.101.1.1` (`.14` seriale disco), servizi attivi `6574.6.1.1`.
- `6574.1.7.1`, `6574.1.7.2`, `6574.1.8`: presenti ma con significato non confermato, quindi **non usati**.

## Linux / Net-SNMP — profili `net-snmp` e `synology`

Fonte: l'agente net-snmp dello stesso NAS. Sono OID standard HOST-RESOURCES-MIB e UCD-SNMP-MIB.

| Colonna | OID | Lettura | Soglie | Note |
|---|---|---|---|---|
| Carico CPU medio | `1.3.6.1.2.1.25.3.3.1.2` | WALK **media** % | > 85 / > 95 | media sui core |
| RAM totale | `1.3.6.1.4.1.2021.4.5.0` | GET, kB→MiB | — | |
| RAM disponibile | `1.3.6.1.4.1.2021.4.27.0` | GET, kB→MiB | — | memSysAvail: coincide con hrStorage "Available memory". `.4.6` (memAvailReal) esclude la cache e sottostima. |
| Uptime sistema | `1.3.6.1.2.1.25.1.1.0` | GET TimeTicks → s | — | `sysUpTime` misura il servizio SNMP e si azzera quando riparte |

## Stampanti — profili `canon-ir-adv`, `kyocera`, `hp-printer`, `zebra-printer`

Fonte: walk della flotta del 2026-10-02. Comprende Canon iR-ADV C5840 (2), C3822, C5535 III (2, firmware 48.16 e 16.12), Kyocera TASKalfa 5054ci e 3554ci, HP DesignJet T730, Zebra ZD421. Fixture: `canon_ir_adv_*`, `kyocera_taskalfa_5054ci`, `hp_designjet_t730`, `zebra_zd421`.

**Colonne comuni** (HOST-RESOURCES-MIB / Printer-MIB):

| Colonna | OID | Lettura | Soglie | Presente su |
|---|---|---|---|---|
| Modello | `1.3.6.1.2.1.25.3.2.1.3.1` | GET testo | — | tutte |
| Stato dispositivo | `1.3.6.1.2.1.25.3.2.1.5.1` | GET | avviso > 2 / critico > 4 | tutte (2 in funzione, 3 attenzione, 5 fermo) |
| Errori rilevati | `1.3.6.1.2.1.25.3.5.1.2.1` | **Errori stampante** (bitmask) | da tabella | tutte |
| Messaggio display | `1.3.6.1.2.1.43.16.5.1.2.1.1` | GET testo | — | tutte tranne Zebra |
| Totale impressioni | `1.3.6.1.2.1.43.10.2.1.4` | WALK massimo | — | tutte tranne Zebra (lì disattivata) |

**Errori stampante.** Il nuovo tipo di valore decodifica `hrPrinterDetectedErrorState` in testo italiano:
- **critico**: toner esaurito, sportello aperto, carta inceppata, fuori linea, assistenza richiesta;
- **avviso**: carta o toner in esaurimento, carta esaurita, cassetti/vassoi mancanti, pieni o vuoti, manutenzione scaduta.

Verificato sui walk: Canon con display "toner is low" → bit *toner in esaurimento*; DesignJet senza rotolo → *carta esaurita*.

**Consumabili** (scheda dispositivo):
- ogni consumabile riporta ora anche **tipo** (toner, tamburo, fusore, toner di scarto…) e **colore** (`prtMarkerSuppliesType`, `prtMarkerColorantValue`);
- un consumabile con percentuale nota **sotto il 10%** porta la stampante in "Attenzione".

**Canon** (`1.3.6.1.4.1.1602`). I nomi dei contatori sono letti dalla tabella stessa (`1602.1.11.1.{3,4}.1.3.N`).

| Colonna | OID | Note |
|---|---|---|
| A4/A3 B/N e colore (contratto) | `1602.1.11.1.3.1.4.{113,112,123,122}` | ora "verificati" su C5840, C3822, C5535 III |
| Firmware | `1602.1.1.1.4.0` | |
| Totale (Total 1) | `1602.1.11.1.4.1.4.101` | coincide con `prtMarkerLifeCount` |
| Copie | `…4.1.4.201` | |
| Stampe | `…4.1.4.301` | |
| Scansioni | `…4.1.4.501` | |
| Fronte-retro | `…4.1.4.114` | |

Il walk espone 39 contatori, tutti con nome: per esempio copie/stampe a colori, grande formato, ricezione fax. Si possono aggiungere come colonne dalla UI.

**Kyocera** (`1.3.6.1.4.1.1347`). La tabella `1347.42.3.1` non riporta i nomi dei contatori. `…1.1.1.1.1` e `…1.1.1.1.2` sono coerenti con la somma per funzione e sembrano totale B/N e totale colore. Sono nel profilo come **"da confermare", disattivate**: vanno confrontate con la pagina contatori del pannello prima di attivarle.
- TASKalfa 5054ci: 347.299 / 13.564;
- TASKalfa 3554ci: 39.109 / 48.095.

Lo storico lavori (`1347.47`) contiene i nomi dei documenti: è escluso dalle fixture.

**HP.** Il prefisso è ora `1.3.6.1.4.1.11.2.3.9` (stampanti HP, verificato su DesignJet) e il pattern non contiene più il solo "HP". Prima un sysDescr "HP J9729A … Switch" di uno switch HPE/Aruba poteva finire nel profilo stampanti.

**Zebra ZD421.** Espone stato ed errori, ma non contatori, consumabili, seriale né display.

## Ancora da verificare

Servono i walk di: switch Aruba/HPE (stack VSF), Cisco SG250, WatchGuard, ESXi, UPS, iDRAC/iLO, Windows. Hanno community diverse da `public`/`novicromprinter`. Procedura in [CATTURA.md](CATTURA.md).
