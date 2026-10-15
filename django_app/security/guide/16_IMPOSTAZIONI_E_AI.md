# Impostazioni e AI

Gli avvisi automatici su mail e Teams, il report che parte da solo e le funzioni dell'AI aziendale nel SOC.

## Avvisi automatici

La scheda **Avvisi e automatismi** di **Configurazione** (gruppo Gestione del menu) raccoglie gli avvisi che il SOC manda da solo. Tutti si vedono; per modificarli serve il permesso di configurazione del SOC.

Gli avvisi partono verso i **canali** (mail o Teams) definiti in **Configurazione › Notifiche**: se non ce n'è nessuno, la pagina lo dice e porta a crearne uno. Ogni sezione sceglie i suoi canali.

| Sezione | Cosa fa | Default |
| --- | --- | --- |
| Scadenze incidenti NIS2 e GDPR | Avvisa quando una notifica entra nell'anticipo scelto e quando scade | Spenta, anticipo 6 ore |
| Backup dei PC e dei server | Avvisa per i PC senza backup riuscito oltre la soglia e, se scelto, quando l'ultimo backup è fallito | Spenta, soglia 3 giorni |
| Report periodico automatico | Manda il report settimanale (il lunedì, sulla settimana prima) o mensile (il giorno 1, sul mese prima), dalle 7 | Spento |
| Soppressione appresa | Vedi [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#soppressione-appresa) | Accesa |
| Impatto CVE sugli asset | Vedi [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#impatto-cve-sugli-asset) | Arricchimento spento |

Come si comportano:

- ogni avviso parte **una volta sola** per canale e per situazione: un PC senza backup non viene segnalato a ogni giro, ma di nuovo solo dopo che è tornato a posto e si è riguastato;
- la soglia dei giorni senza backup è la stessa usata dalla pagina Backup e dalla barra di stato;
- via mail il report arriva con il **PDF allegato**, su Teams con un riassunto e il link;
- i controlli girano da soli **ogni 15 minuti**; **Esegui i controlli ora** li lancia subito, utile dopo aver acceso una sezione;
- per scadenze e backup la riga **Adesso** dice cosa verrebbe segnalato in questo momento;
- **Ultimi avvisi inviati** elenca gli invii con canale ed esito (inviato o non inviato).

## L'AI nel SOC

Il SOC usa l'**AI aziendale**, installata sui server dell'azienda: nessun dato esce dalla rete. L'AI non decide e non cambia nulla da sola: propone, e decide sempre una persona.

| Dove | Pulsante | Cosa fa |
| --- | --- | --- |
| Panoramica | Chiedi all'AI | Riassume i punti da guardare adesso e dice da dove partire |
| Scheda alert | Spiega con l'AI | Cosa è successo, perché è scattato, quanto è urgente, cosa fare |
| Scheda evento | Chiedi all'AI («È un allarme?») | Propone se l'evento giudicato a posto è in realtà un allarme |
| Ticket | Proponi con l'AI | Suggerisce i prossimi passi; scegli tu quali diventano attività |
| Ticket | Scrivi l'esito con l'AI | Prepara una bozza dell'esito da rivedere prima di chiudere |
| Incidente | Controlla l'incidente | Cosa manca per notifiche e audit, stato delle scadenze, prossimi passi |
| Scheda PC | Controlla il dispositivo | Cosa rischia il dispositivo e cosa fare |
| Storico | Analizza con l'AI | Fino a 5 azioni di miglioramento: soppressioni, cause alla radice, ticket da chiudere |

### Cosa legge

L'AI riceve solo quello che serve per la domanda: l'alert o il ticket, lo storico collegato (accessi, backup, precedenti, alert chiusi o scartati), le procedure del SOC. Per spiegare gli alert non riceve mai il testo delle mail originali, che è contenuto di terzi e può contenere dati personali. L'unica eccezione è la **lettura assistita** (sotto), se la accendi: riceve l'oggetto e l'inizio del report (al massimo 3000 caratteri), con gli indirizzi email mascherati.

### Lettura assistita

Quando un parser legge una mail solo in parte («Da verificare») o nessun parser la riconosce, l'AI locale può proporre i dati mancanti o dire che tipo di mail è (report di backup, antivirus, firewall, newsletter…).

- **Si accende** in **Impostazioni › Lettura assistita dall'AI** (spenta di serie), con il massimo di elementi per giro (5 di serie) e, se vuoi, i canali su cui avvisare quando ci sono proposte nuove.
- **Gira da sola** con il flusso **security_ai_lettura** (ogni 30 minuti), visibile nel designer di **Automazioni** tra i processi dei moduli: lì puoi cambiare la cadenza, spegnerlo o aggiungere azioni. L'avviso «letture proposte dall'AI da controllare» è l'evento **security_lettura_ai_pronta**, anch'esso modificabile nel designer.
- **Si vede** in **Configurazione › Parser**: nel riquadro «Letture da verificare» e accanto agli elementi non elaborati compare la «Proposta AI». In «Prova i parser» il pulsante **Prova e chiedi all'AI** fa la stessa cosa su una mail incollata o su un file caricato, senza salvare nulla.
- **È solo una proposta**: non crea e non chiude alert, non cambia esiti di backup né conteggi. Ogni valore viene confrontato con il testo: se non compare, il badge rosso **non nel testo** avverte che l'AI potrebbe averlo inventato; «dedotto» indica un valore interpretato (es. l'esito).
- Il testo del report è trattato come un dato: eventuali istruzioni scritte nella mail («ignora le istruzioni…») non possono cambiare nulla nel SOC.
- Per misurare tempi e precisione sul server: `python manage.py soc_ai_lettura_prova` (campioni sintetici, nessun salvataggio).

### Come impara

- Quando promuovi un evento ad alert o confermi che è a posto, la scelta viene ricordata: la volta dopo l'AI tiene conto di come avete deciso su eventi simili.
- Gli alert chiusi, scartati e i motivi scritti diventano lo storico che l'AI usa per i consigli successivi. Motivi chiari ("job di test spento il 12/03") rendono i consigli migliori.

### Limiti

- Le risposte richiedono qualche secondo; se l'AI non è raggiungibile, la pagina lo dice e il resto funziona normalmente.
- Le risposte vengono conservate per un po' (da 30 minuti a qualche giorno, secondo la funzione): finché i dati non cambiano, ripetere la richiesta dà la stessa risposta, segnata «risposta già pronta».
- L'AI può sbagliare: verifica sempre i fatti prima di agire, soprattutto prima di chiudere o notificare.
- Ogni richiesta all'AI viene registrata (chi, quando, su cosa, con quale esito) per la tracciabilità; il testo della risposta non viene archiviato nel registro.
- Sotto ogni risposta c'è il promemoria: testo generato dall'AI, da verificare prima di agire.
