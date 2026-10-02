# Catalogo preset SNMP verificati

Ogni OID qui elencato è stato **letto su un walk reale** (`snmp_capture`). La fixture pseudonimizzata è in `django_app/contatori/fixtures/snmp/`, i test in `contatori/tests_snmp_preset.py`. Le colonne compaiono nel profilo con **Verificata** e la fonte.

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

## Ancora da verificare

Servono i walk di: switch Aruba/HPE (stack VSF), Cisco SG250, WatchGuard, ESXi, Canon (per modello), UPS, iDRAC/iLO, Windows. Procedura in [CATTURA.md](CATTURA.md).
