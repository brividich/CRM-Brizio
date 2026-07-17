# Ciclo di vita degli alert

Un alert nasce dal motore regole quando una metrica soddisfa una condizione. Da lì attraversa una serie di stati che raccontano cosa sta facendo il team. Capire le differenze evita che un alert resti appeso o venga chiuso troppo presto.

## Stati

| Stato | Significato | Quando usarlo |
| --- | --- | --- |
| new | Appena creato, non ancora guardato | Stato iniziale, automatico |
| open | Preso in considerazione, in coda | Sei consapevole, non ci lavori ancora |
| acknowledged | Preso in carico | Qualcuno se ne sta occupando |
| in_progress | In lavorazione attiva | Remediation in corso |
| snoozed | Posticipato fino a una data | Non azionabile ora, ripresenta dopo |
| muted | Silenziato sul singolo alert | Rumore noto su questo specifico alert |
| suppressed | Soppresso da una regola | Neutralizzato prima di diventare lavoro |
| resolved | Risolto | La causa è stata sistemata |
| false_positive | Falso positivo | Non era un problema reale |
| closed | Chiuso | Terminato (risolto o non più rilevante) |

## Distinzioni che contano

- **Soppressione vs silenziamento.** La *soppressione* è una regola preventiva (sezione Soppressioni) che agisce su intere classi di eventi prima che diventino alert. Il *silenziamento* (muted) agisce sul singolo alert già creato. Usa la soppressione per rumore sistematico, il muting per il caso singolo.
- **Snooze vs close.** Lo *snooze* rimanda: l'alert torna a farsi vivo alla scadenza. La *chiusura* archivia. Non chiudere ciò che va solo rimandato, altrimenti perdi il promemoria.
- **Resolved vs false_positive.** *Resolved* = era reale ed è stato sistemato. *False positive* = non era un problema. La distinzione serve a tarare le regole: troppi falsi positivi = soglia da rivedere.

## Cooldown e deduplica

Due meccanismi impediscono le raffiche sullo stesso problema:

- Il **cooldown** (minuti configurati sulla regola) impedisce che la stessa regola scatti di nuovo subito dopo aver generato un alert.
- La **deduplica** garantisce, a livello database, un solo alert **attivo** per `(sorgente, dedup_hash)`. Lo stesso finding che arriva due volte non crea due alert. Un alert chiuso non blocca la riapertura se il problema si ripresenta.

## Ticket collegati

Un alert può creare (o alimentare) un **ticket di remediation**. Più alert correlati — per esempio più CVE dello stesso prodotto — confluiscono in un unico ticket secondo la strategia di aggregazione configurata (vedi [Ticketing nella guida configurazione](/soc/docs/08-configuration-guide/)).
