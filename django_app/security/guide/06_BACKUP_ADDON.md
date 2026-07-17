# Modulo Backup/NAS

Il modulo Backup elabora i report dei job di backup (tipicamente Synology Active Backup su NAS) e sorveglia che i backup vengano eseguiti, riescano e rientrino nei parametri attesi.

## Cosa monitora

| Segnale | Descrizione |
| --- | --- |
| Backup mancante | Un job atteso non è stato visto oltre le ore limite |
| Backup fallito | Il job è terminato in errore |
| Durata anomala | Il job ha impiegato più del massimo atteso |
| Dimensione anomala | I dati trasferiti sono fuori dall'intervallo atteso |

## Job attesi

La sezione Backup della Configuration Studio definisce i **job attesi**: nome job, dispositivo/NAS, giorni attesi, finestra oraria, ore limite per considerarlo mancante, e le soglie opzionali di durata e dimensione. Un job può essere marcato **critico** perché la sua assenza allerti subito.

## Logica del "mancante"

Il backup mancante è il caso più insidioso: non c'è un evento di errore da leggere, c'è un'**assenza**. Per questo il sistema confronta i job attesi con quelli effettivamente visti entro le ore limite: se un job atteso non compare, scatta un alert. È l'unico controllo che rileva ciò che **non** arriva.

## Salute dei backup

Dalla configurazione puoi attivare selettivamente gli alert su: mancante, fallito, durata anomala, dimensione anomala. Rivedi periodicamente le soglie: un job che cresce nel tempo può far scattare falsi allarmi di dimensione.

## Consiglio operativo

Schedula il controllo insieme all'ingestione, così l'assenza di un report di backup viene notata rapidamente. Vedi il [Runbook operativo](/soc/docs/11-operations-runbook/).
