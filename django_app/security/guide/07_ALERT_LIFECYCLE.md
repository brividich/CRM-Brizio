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

## Chiusura automatica quando il problema rientra

Se un report successivo dimostra che l'anomalia non c'è più, l'alert si chiude da solo come **Risolto**, con il motivo e il riferimento al report che lo prova (voce «Risolto automaticamente» nella timeline). Le regole sono prudenti: nel dubbio l'alert resta aperto.

| Alert | Si chiude quando |
| --- | --- |
| Backup fallito | Lo stesso job sullo stesso dispositivo viene completato **dopo** il fallimento |
| CVE critica esposta | La stessa CVE sullo stesso prodotto viene riletta con **0 dispositivi esposti** (l'assenza dal report non basta) |
| Sorgente silenziosa | La sorgente torna a inviare report nei tempi attesi |

Picchi VPN, segnalazioni WatchGuard, spoofing del mittente e dati illeggibili non hanno un segnale di rientro affidabile: restano da chiudere a mano. Per disattivare la chiusura automatica impostare `SECURITY_AUTO_RESOLVE_ENABLED` a `false` nelle impostazioni del Security Center.

## Ticket

Il **ticket** è il caso su cui si lavora: raccoglie uno o più alert e porta responsabile, stato, attività spuntabili, note di lavoro e una timeline unica (azioni sul ticket, sugli alert collegati e note).

- **Automatici**: CVE critiche (aggregate per prodotto) e backup falliti aprono o alimentano un ticket da soli.
- **A mano**: dalla scheda di un alert («Apri ticket») o dalla coda alert, selezionando più alert e scegliendo «Apri un ticket con i selezionati» o «Aggiungi a un ticket aperto». Gli alert nuovi inseriti in un ticket passano a «Preso in carico».
- **Stati**: Aperto → In lavorazione (automatico quando si assegna un responsabile o si aggiunge un'attività) → Risolto / Chiuso / Falso positivo. Per chiudere serve l'esito; si può chiudere insieme anche gli alert ancora aperti.
- **Chiusura automatica**: quando tutti gli alert del ticket sono rientrati, il ticket si chiude da solo come Risolto. Se ha ancora attività da fare resta aperto e la timeline lo segnala.

## Azioni massive

Nella coda alert si selezionano più alert (casella in testa alla riga, o «seleziona tutti») e si applica: presa in carico, chiusura, falso positivo, apertura di un ticket o aggiunta a un ticket aperto. Gli alert in uno stato non compatibile (per esempio già chiusi) vengono saltati e il conteggio lo dice.
