# Lavoro quotidiano

Come si usa il SOC ogni giorno: da dove partire, come si lavorano alert, eventi e ticket, come si trova un PC. Le impostazioni e la configurazione sono in altri capitoli.

## Da dove partire

1. Apri **Panoramica**. In alto c'è il verdetto della giornata e l'elenco **Da guardare adesso**, ordinato dal più grave: notifiche NIS2/GDPR in scadenza, alert critici, PC senza backup, computer senza protezione, sorgenti che non mandano più report. Ogni voce porta al dettaglio.
2. Se ti serve un riassunto, in **Sintesi del giorno** premi **Chiedi all'AI**: l'AI aziendale riassume in poche frasi cosa è più urgente e da dove partire. Nessun dato esce dall'azienda.
3. Apri **Il mio lavoro** (in alto a destra nel menu del SOC): incidenti di cui sei responsabile, ticket assegnati a te e alert che hai preso in carico, con le scadenze più vicine in alto. Sopra compaiono anche i ticket e gli incidenti senza responsabile.
4. Guarda i riquadri per area della Panoramica (firewall, computer, backup, accessi VPN, vulnerabilità): se la data dell'ultimo report è segnata come **dati vecchi**, quella sorgente non sta arrivando e il resto della pagina va letto con prudenza.

## La barra di stato

Sotto il menu del SOC c'è una barra che si aggiorna da sola ogni minuto. Ogni numero è un link:

| Voce | Cosa conta |
| --- | --- |
| critici e alti | Alert critici o alti ancora da gestire |
| scadenze NIS2 | Notifiche di incidenti scadute o in scadenza |
| PC backup ko | PC e server senza backup riuscito oltre la soglia, o con l'ultimo backup fallito |
| sorgenti mute | Sorgenti che non mandano report nei tempi attesi |
| senza responsabile | Ticket e incidenti aperti senza un responsabile |
| miei | Ticket e incidenti assegnati a te |

Il colore dice la situazione: verde a posto, giallo da guardare, rosso urgente. A destra c'è l'ora dell'ultimo report arrivato.

## Cercare qualcosa

La casella **Cerca** nel menu del SOC trova incidenti, ticket, alert, PC e server, vulnerabilità. Basta un pezzo di nome: un nome PC, un codice `INC-…`, un numero di ticket, una CVE. Servono almeno due caratteri.

## Anteprime e selezione multipla

- **Anteprima**: nelle liste (alert, ticket, incidenti, eventi, PC) un clic sulla riga (non sul link né sulla casella) apre il dettaglio in un pannello laterale, senza perdere la lista. Con le frecce **←** e **→** passi alla riga precedente o successiva, con **Esc** chiudi. Le azioni del pannello (prendere in carico, chiudere…) restano sulla lista.
- **Selezione multipla**: la casella in testa alla riga seleziona; la casella nell'intestazione seleziona tutte le righe della pagina. In fondo compare la barra con le azioni possibili e il conto dei selezionati. Le righe in uno stato non compatibile vengono saltate e il messaggio finale lo dice.

## Alert

La **Coda alert** è l'elenco di ciò che il motore ha giudicato un problema. Filtra per stato (di default «Da gestire»), severità e sorgente.

### Leggere un alert

La scheda dell'alert risponde a quattro domande:

- **In parole semplici**: premi **Spiega con l'AI** per avere cosa è successo, perché è scattato, quanto è urgente e cosa fare. L'AI tiene conto dello storico mostrato nella pagina.
- **Perché è stato generato**: la regola che è scattata e i valori che l'hanno fatta scattare.
- **Cosa sappiamo dagli altri dati del portale**: gli stessi indirizzi, utenti, PC o job incrociati con lo storico (accessi VPN, backup, asset), i precedenti e gli alert simili già chiusi o scartati.
- **Come rispondere**: la procedura consigliata per quel tipo di alert. **Apri ticket con questi passi** crea il ticket con i passi già come attività.

Più in basso: il ticket collegato, la timeline di tutto ciò che è successo all'alert, le occorrenze, le evidenze e il report da cui è nato.

### Le azioni

| Azione | Quando usarla |
| --- | --- |
| Prendi in carico | Te ne occupi tu: l'alert compare nel tuo «Il mio lavoro» |
| Posticipa | Non si può fare nulla adesso: l'alert torna da gestire alla data scelta |
| Chiudi con esito «Risolto» | Il problema era vero ed è stato sistemato |
| Chiudi con esito «Non rilevante» o «Rischio accettato» | Il problema c'è ma non va gestito, con il motivo |
| Falso positivo | Non era un problema |
| Silenzia | Rumore noto su questo alert |
| Riapri | Un alert chiuso va ripreso in mano |

Falso positivo, «Non rilevante», «Rischio accettato» e Silenzia chiedono un motivo e contano per la **soppressione appresa**: dopo tre volte lo stesso alert non viene più aperto. Vedi il capitolo [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#soppressione-appresa). Le differenze tra gli stati sono spiegate in [Ciclo di vita degli alert](/soc/docs/07-alert-lifecycle/).

## Eventi

**Eventi** mostra **tutto** quello che è arrivato dai report, anche ciò che il motore ha giudicato a posto e non ha trasformato in alert. Serve a due cose: capire cosa succede davvero e trovare gli **allarmi mancati**.

- Il grafico **Eventi per giorno** distingue gli eventi con alert da quelli senza. Un clic su un giorno filtra il registro su quel giorno.
- La colonna **Decisione del motore** dice cosa è stato fatto: alert creato, soppresso da una regola, solo statistica, da valutare.

### Un evento che doveva essere un allarme

1. Apri l'evento. Se vuoi un parere, premi **Chiedi all'AI** in «È un allarme?»: l'AI guarda l'evento, lo storico e gli allarmi che avete già promosso a mano e propone un verdetto.
2. Se è un allarme, compila **Titolo dell'alert**, **Gravità** e **Perché è un allarme**, poi **Crea l'alert**.
3. Con la spunta **Impara** il sistema crea una **regola appresa**: d'ora in poi crea da solo l'alert per gli eventi simili. «Simili» vuol dire stesso tipo di evento e stessi valori nei campi spuntati: togli una spunta per allargare (più alert), aggiungine una per restringere.
4. Se invece è a posto, **È a posto, nessun alert**: l'evento viene segnato come confermato da te.

Dalla lista si può fare lo stesso su più eventi insieme: **Sono a posto** oppure **Sono allarmi: crea gli alert**.

Le regole apprese sono elencate in cima alla pagina Eventi, con quante volte sono scattate: **Disattiva** le spegne senza perdere lo storico. Se un evento è stato fermato da una soppressione, promuoverlo ad alert spegne anche la soppressione appresa che lo aveva fermato.

## Ticket

Il **ticket** è il caso su cui si lavora: raccoglie uno o più alert e porta responsabile, stato, attività e note.

- **Come nasce**: da solo per le CVE critiche (raggruppate per prodotto) e per i backup falliti; a mano dalla scheda di un alert («Apri ticket») o dalla coda alert selezionando più alert.
- **Responsabile**: **Prendo io** oppure scegli una persona e **Assegna**. Assegnare un responsabile o aggiungere un'attività porta il ticket in lavorazione.
- **Attività**: i passi da fare per chiudere il ticket, da spuntare man mano. Se c'è una procedura consigliata per quel tipo di problema, la aggiungi con un clic. **Proponi con l'AI** in «Prossimi passi» suggerisce cosa fare dopo; scegli tu quali passi diventano attività.
- **Note di lavoro**: tutto quello che serve a chi verrà dopo. Finisce nella timeline insieme alle azioni sugli alert collegati.
- **Chiusura**: in **Cambia stato** scegli l'esito (Risolto, Chiuso, Falso positivo) e scrivi il motivo; con la spunta chiudi insieme gli alert ancora aperti. **Scrivi l'esito con l'AI** prepara una bozza da rivedere.
- **Chiusura automatica**: quando tutti gli alert del ticket rientrano da soli, il ticket si chiude come Risolto, a meno che abbia attività ancora da fare.
- **Incidente**: se il problema ha avuto un impatto reale, **Apri incidente** dal ticket. Vedi [Incidenti e report](/soc/docs/14-incidenti-e-report/).

Nella lista ticket il filtro **Responsabile › Non assegnati** mostra i ticket che nessuno sta seguendo.

## Analisi dello storico

La pagina **Storico** (Analisi dello storico) guarda indietro di 30, 90 o più giorni e mostra cosa migliorare:

- **Alert che si ripetono** e come sono finiti;
- **Falsi positivi ricorrenti**: candidati a una regola di soppressione;
- **Scartati dal motore** e **Allarmi mancati** (eventi promossi a mano);
- **Fermi**: alert aperti da più di 7 giorni, ticket fermi da più di 14;
- **Come sono stati chiusi**: i motivi scritti da chi li ha gestiti.

**Analizza con l'AI** propone fino a 5 azioni (soppressioni, cause da risolvere alla radice, ticket da chiudere o riassegnare). Non cambia nulla: decidi tu.

## Scheda PC e server

Da un risultato di ricerca, dalla pagina Backup o da un alert si apre la **scheda PC**: un riepilogo di backup, alert aperti, vulnerabilità, protezione endpoint e ultimi eventi di quel dispositivo, con il link all'asset del portale se è collegato. **Controlla il dispositivo** chiede all'AI cosa rischia e cosa fare.
