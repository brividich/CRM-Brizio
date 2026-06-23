# Anomalie di produzione

## A cosa serve il modulo Anomalie?

Il modulo **Anomalie** raccoglie le segnalazioni di non conformità della
produzione. Ogni anomalia è legata a un **ordine di produzione (OP)** e può
riportare il part number, il seriale del pezzo, lo stato sintetico, l'avanzamento
della lavorazione, se il pezzo è stato recuperato e se è prevista una segnalazione
al cliente. È lo strumento per tracciare i problemi di qualità e seguirne la
risoluzione.

## Come chiedo le anomalie all'assistente AI?

Puoi chiedere ad esempio "anomalie aperte nel mio reparto", "anomalie dell'OP X"
o "anomalie con part number Y". La risposta usa i dati live filtrati dai tuoi
permessi: gli utenti operativi vedono le anomalie di cui sono capocommessa o
incaricati, mentre i gestori autorizzati hanno una visione più ampia. L'assistente
riporta solo i campi sintetici, mai descrizioni libere, note interne o allegati.

## Cosa significano "aprire RDC" e "segnalare al cliente"?

Alcune anomalie richiedono di **aprire una RDC** (la gestione formale della non
conformità) oppure di **segnalare l'anomalia al cliente**. Sono passi del flusso
di gestione che indirizzano la comunicazione alle persone giuste. Quando un
aggiornamento contiene anomalie con questi flag, il portale avvisa anche la lista
dedicata, così la non conformità non resta senza presa in carico.

## Cos'è l'avanzamento di un'anomalia?

L'**avanzamento** è lo stato del percorso di gestione dell'anomalia (ad esempio
"in attesa", "in lavorazione", "chiusa"). Gli stati seguono un catalogo
configurato: questo evita ambiguità e fa funzionare correttamente i promemoria di
escalation e i raggruppamenti dei KPI. Le anomalie ferme da troppo tempo possono
generare un'escalation verso i supervisori.
