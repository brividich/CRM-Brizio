# Impostazioni e AI

Gli avvisi automatici su mail e Teams, il report che parte da solo e le funzioni dell'AI aziendale nel SOC.

## Avvisi automatici

La scheda **Avvisi e automatismi** di **Impostazioni › Configurazione** raccoglie gli avvisi che il SOC manda da solo. Tutti si vedono; per modificarli serve il permesso di configurazione del SOC.

Gli avvisi partono verso i **canali** (mail o Teams) definiti in **Configurazione › Notifiche**: se non ce n'è nessuno, la pagina lo dice e porta a crearne uno. Ogni sezione sceglie i suoi canali.

| Sezione | Cosa fa | Default |
| --- | --- | --- |
| Scadenze incidenti NIS2 e GDPR | Avvisa quando una notifica entra nell'anticipo scelto e quando scade | Spenta, anticipo 6 ore |
| Backup dei PC e dei server | Avvisa per i PC senza backup riuscito oltre la soglia e, se scelto, quando l'ultimo backup è fallito | Spenta, soglia 3 giorni |
| Report periodico automatico | Manda il report settimanale (il lunedì, sulla settimana prima) o mensile (il giorno 1, sul mese prima), dalle 7 | Spento |
| Soppressione appresa | Vedi [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#soppressione-appresa) | Accesa |
| Impatto CVE sugli asset | Vedi [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#impatto-cve-sugli-asset) | Arricchimento spento |
| Alert di Microsoft Defender | Vedi [Alert di Microsoft Defender](#alert-di-microsoft-defender) qui sotto | Spenta, severità minima Media |
| Microsoft Entra ID (account, modifiche amministrative, accessi) | Vedi [Microsoft Entra ID](#microsoft-entra-id) qui sotto | Tutti spenti, primo giro 7 giorni, Paesi ammessi IT, 10 tentativi falliti |

## Alert di Microsoft Defender

Con **Leggi gli alert di Defender** acceso, ogni 15 minuti il SOC chiede a Microsoft Graph gli alert di Defender aggiornati dall'ultimo giro (la prima volta: gli ultimi giorni scelti in **Primo giro**, default 7).

- Ogni alert di Defender diventa un evento della sorgente **Microsoft Defender (Graph Security)**. Un nuovo evento nasce solo quando cambia lo **stato** o la **severità** in Defender.
- Dalla **Severità minima per l'alert** in su (default Media) nasce un alert del SOC «Defender: <titolo> su <PC>», **uno per alert di Defender**: se Defender lo aggiorna, si aggiorna lo stesso alert.
- Sotto la soglia l'evento resta nei KPI, senza alert. Gli alert «informativi» di Defender non aprono mai un alert.
- Quando Defender dà l'alert **risolto**, l'alert del SOC si chiude da solo («Risolto in Microsoft Defender») e i casi collegati seguono le regole di sempre.
- Si tengono titolo, severità, stato, categoria, tecniche MITRE, i nomi dei **dispositivi** e il link all'alert nel portale Defender. Degli **utenti** coinvolti solo il numero: i dettagli si leggono in Defender.

Serve il permesso applicativo **SecurityAlert.Read.All** (Microsoft Graph, con consenso amministratore) sull'app del portale. Prova dal terminale del server: `manage.py defender_alerts --prova`. L'esito dell'ultimo giro: `manage.py defender_alerts`. Se manca il permesso, il giro registra «Graph ha risposto 403» e il resto del ciclo SOC prosegue.

Nella stessa sezione, tre interruttori in più (spenti di default):

- **Raggruppa per incidente**: Defender correla gli alert dello stesso attacco in un **incidente**. Con l'interruttore acceso nasce **un solo alert del SOC per incidente** («Defender: incidente «<nome>»»), dalla stessa severità minima, chiuso da solo quando Defender risolve l'incidente; gli alert singoli dello stesso incidente restano eventi (KPI). Serve **SecurityIncident.Read.All**.
- **Leggi il software dei PC**: ogni mattina alle 06:20 il software installato sui PC collegati a Defender entra nell'inventario del SOC come fonte **Microsoft Defender for Endpoint**, con la stessa procedura dei file caricati a mano: collegamento ai CPE, regole «non applicabile», impatti CVE e catalogo software si aggiornano da soli; il software che sparisce da un PC diventa «non più rilevato». I PC non collegati a Defender restano agli import da file. Serve **Software.Read.All** dell'API **WindowsDefenderATP** (non Graph: in Entra si trova in «API usate dall'organizzazione»).
- **Mostra il Secure Score**: in cima alla Panoramica compare il riquadro **Microsoft Secure Score** con la percentuale, i punti, la variazione in 30 giorni e **le 5 azioni che valgono di più**, con il link alla pagina di Microsoft. Letto ogni 12 ore. Serve **SecurityEvents.Read.All**.

## Backup letti direttamente da Veeam

Con **Leggi i backup dall'API di Veeam** acceso, ogni 15 minuti il SOC si collega all'API REST di **Veeam Backup & Replication** (versione 12 o successive) e legge:

- le **sessioni di backup concluse** dopo l'ultimo giro (la prima volta: gli ultimi giorni scelti in **Primo giro**, default 7), con l'esito, i dati trasferiti e la durata di **ogni macchina**. Le sessioni ancora in corso si leggono al giro dopo; ripristini, manutenzioni e backup della configurazione restano fuori;
- lo **spazio dei repository**, mostrato nel riquadro **Lettura diretta da Veeam** della pagina Backup.

Ogni sessione diventa un'esecuzione della sorgente **Veeam Backup & Replication (API)**, uguale a quelle lette dalle mail: KPI, «Da controllare», alert «backup fallito» e rientri funzionano come prima. Se arriva anche la mail di esito, **la stessa esecuzione conta una volta sola** (stesso job, inizio entro due minuti). Una sessione annullata a mano risulta «con avvisi».

Con **Avvisa quando un repository si riempie** acceso (default), un repository con lo spazio libero sotto lo **Spazio libero minimo** (default 15%) apre l'alert «Repository di backup quasi pieno», uno per repository; si chiude da solo quando lo spazio torna sopra.

Le credenziali si inseriscono nel riquadro **Credenziali API Veeam** in fondo alla pagina Impostazioni: **Indirizzo** (es. `https://srv-veeam:9419`), **Utente** e **Password** di un utente con il solo ruolo **Veeam Backup Viewer**, **Revisione API** (facoltativa, default 1.1-rev0) e, se il certificato del server Veeam è firmato dalla CA interna, il **Certificato della CA** incollato in formato PEM. La password è salvata cifrata e non si rivede: per cambiare solo l'indirizzo lasciala vuota. **Prova la connessione** legge le ultime 24 ore e lo spazio dei repository senza salvare nulla; **Cancella le credenziali** ferma la lettura. Se nel file `.env` del server ci sono ancora le vecchie variabili `VEEAM_API_*`, valgono finché non si salvano le credenziali qui (il riquadro dice «Dal file .env»). Lo stesso si può fare dal terminale: `manage.py veeam_api --prova`, `manage.py veeam_api` (esito dell'ultimo giro).

## Microsoft Entra ID

Tre controlli su Microsoft 365, ciascuno con il suo interruttore nella sezione **«Microsoft Entra ID (account, modifiche amministrative, accessi)»**. Gli eventi hanno la sorgente **Microsoft Entra ID (Graph)**.

- **Controlla gli account degli ex dipendenti**: ogni 6 ore il SOC confronta gli account di Microsoft 365 con l'anagrafica (per email aziendale o di notifica e per nome di accesso). Per ogni account **ancora abilitato** di una persona con **data di cessazione passata** nasce un alert alto «Account Microsoft 365 attivo di un ex dipendente: <nome>». Quando l'account viene disattivato in Active Directory / Entra, l'alert si chiude da solo («Account disattivato in Microsoft 365»). Lo stesso elenco, con anche gli account inattivi e quelli non collegati, è in Amministrazione › Ruoli e permessi › «Account Microsoft 365».
- **Leggi le modifiche amministrative di Entra**: ogni 15 minuti il SOC legge l'audit di Entra dal giro precedente (la prima volta: i giorni di **Primo giro dell'audit**, default 7) e apre un alert solo per le attività sensibili: autenticazione o federazione di un dominio (critico), ruoli di amministratore assegnati, criteri di accesso condizionale, credenziali/segreti delle app, MFA disattivata (alto), consensi e permessi concessi alle app, proprietari delle app, metodi MFA modificati (medio). Titolo: «Entra: <attività> (<su chi>) da <chi>». Le altre righe dell'audit non vengono salvate.

- **Segnala gli accessi sospetti a Microsoft 365**: ogni 15 minuti il SOC legge gli accessi dal giro precedente e apre un alert per: **tentativi falliti a raffica** sullo stesso account (almeno **Tentativi falliti**, default 10, in un giro; medio), **accesso riuscito da un Paese non ammesso** (**Paesi ammessi**, codici a due lettere separati da virgole, default IT; alto), **accesso riuscito con un protocollo vecchio** senza MFA (IMAP4, POP3, SMTP autenticato, Exchange ActiveSync, altri client; medio). Al massimo un alert al giorno per account e motivo. I singoli accessi non vengono salvati nel portale: si guardano in Entra.

Servono i permessi applicativi **User.Read.All** e **AuditLog.Read.All** (Microsoft Graph, con consenso amministratore). Prova dal terminale del server: `manage.py entra_signals --prova` (conta gli account, dice se l'ultimo accesso è leggibile, quante righe di audit sensibili ci sono nelle ultime 24 ore e quante anomalie di accesso nell'ultima ora). L'esito dell'ultimo giro: `manage.py entra_signals`.

Come si comportano:

- ogni avviso parte **una volta sola** per canale e per situazione: un PC senza backup non viene segnalato a ogni giro, ma di nuovo solo dopo che è tornato a posto e si è riguastato;
- la soglia dei giorni senza backup è la stessa usata dalla pagina Backup e dalla barra di stato;
- via mail il report arriva con il **PDF allegato**, su Teams con un riassunto e il link;
- i controlli girano da soli **ogni 15 minuti**; **Esegui i controlli ora** li lancia subito, utile dopo aver acceso una sezione;
- per scadenze e backup la riga **Adesso** dice cosa verrebbe segnalato in questo momento;
- **Ultimi avvisi inviati** elenca gli invii con canale ed esito (inviato o non inviato).

## Letture automatiche

Pagina **Impostazioni › Letture automatiche**: tutte le letture che il SOC fa da solo, una scheda per lettura, raggruppate per fonte (Report via mail, Microsoft 365, WatchGuard, Backup, Vulnerabilità, Rete). Ci sono anche **Backup da Veeam (API)** e **DHCP e DNS di Windows Server** (Rete): «Da configurare» finché mancano i dati nel file .env del server.

Ogni scheda dice:

- **cosa legge** e **quando gira** (ogni 15 minuti, ogni mattina alle 06:20…);
- lo **stato**: Riuscita (bordo verde), Riuscita in parte (arancione: una parte ha letto, un'altra ha dato errore), Non riuscita (rosso), In coda / In corso (blu), Spenta, Da configurare (mancano le credenziali o la casella), Mai eseguita;
- l'**ultimo giro**: quando, se automatico o a mano (e da chi), quanto è durato e **cosa ha letto** in numeri («312 PC», «18 patch», «4 vulnerabilità»…); in rosso il messaggio d'errore così come arriva dalla fonte (permesso mancante, credenziali non valide…);
- l'**ultimo giro riuscito**, se l'ultimo è andato male;
- lo **storico** degli ultimi giri (Storico) e il link ai dati letti.

**Esegui ora** fa partire subito un giro (serve il permesso di configurazione del SOC). Il giro va nella coda dei lavori in background: la pagina si aggiorna da sola ogni pochi secondi finché non ha finito. Il pulsante è spento se la lettura è spenta, se manca la configurazione o se un giro è già in corso (anche un doppio clic non fa partire due giri). Un giro a mano rispetta gli interruttori: una lettura spenta si accende in **Avvisi e automatismi**.

Se un giro resta «Interrotta» il servizio dei lavori in background (qcluster) è fermo o è stato riavviato a metà: va controllato in Amministrazione › Monitoring.

In fondo alla pagina **Ultimi giri, tutte le letture** elenca gli ultimi 30 giri. I giri automatici con la lettura spenta non si registrano; per ogni lettura si tengono gli ultimi 300 giri.

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

### Sintesi del giorno già pronta

La «Sintesi del giorno» della Panoramica viene preparata dall'AI ogni 30 minuti, dalle 6 alle 19 da lunedì a sabato, e solo quando i punti «da guardare» cambiano. Chi apre la Panoramica la trova già scritta, con l'ora in cui è stata preparata («preparata alle 08:30»); il pulsante **Rigenera** la riscrive subito. Se i punti sono cambiati dopo l'ultima sintesi compare di nuovo **Chiedi all'AI**. Si spegne in **Impostazioni › Sintesi del giorno già pronta**; il flusso è **security_ai_sintesi** nel designer di Automazioni (cadenza modificabile).

### Lettura assistita

Quando un parser legge una mail solo in parte («Da verificare») o nessun parser la riconosce, l'AI locale può proporre i dati mancanti o dire che tipo di mail è (report di backup, antivirus, firewall, newsletter…).

- **Si accende** in **Impostazioni › Lettura assistita dall'AI** (spenta di serie), con il massimo di elementi per giro (3 di serie: ogni lettura impegna l'AI per 15-40 secondi) e, se vuoi, i canali su cui avvisare quando ci sono proposte nuove.
- **Gira da sola** con il flusso **security_ai_lettura** (ogni 30 minuti), visibile nel designer di **Automazioni** tra i processi dei moduli: lì puoi cambiare la cadenza, spegnerlo o aggiungere azioni. L'avviso «letture proposte dall'AI da controllare» è l'evento **security_lettura_ai_pronta**, anch'esso modificabile nel designer.
- **Si vede** in **Configurazione › Parser**: nel riquadro «Letture da verificare» e accanto agli elementi non elaborati compare la «Proposta AI». In «Prova i parser» il pulsante **Prova e chiedi all'AI** fa la stessa cosa su una mail incollata o su un file caricato, senza salvare nulla.
- **È solo una proposta**: non crea e non chiude alert, non cambia esiti di backup né conteggi. Ogni valore viene confrontato con il testo: se non compare, il badge rosso **non nel testo** avverte che l'AI potrebbe averlo inventato; «dedotto» indica un valore interpretato (es. l'esito).
- Il testo del report è trattato come un dato: eventuali istruzioni scritte nella mail («ignora le istruzioni…») non possono cambiare nulla nel SOC. Se il testo ne contiene, la proposta porta il badge rosso **Testo sospetto** (la mail va guardata: può essere un tentativo di inganno); se l'esito proposto dall'AI contraddice quello scritto in chiaro nel testo compare **in contrasto con il testo**.
- Per misurare tempi e precisione sul server: `python manage.py soc_ai_lettura_prova` (campioni sintetici, nessun salvataggio).

### Proposte su CPE ed esiti da verificare

La stessa AI può esaminare i casi «da verificare» del calcolo CVE: a quale CPE collegare un software (scelto solo fra quelli delle CVE già nel sistema) e se una CVE riguarda davvero un PC quando la versione non si confronta. **Si accende** in **Impostazioni › Proposte AI su CPE ed esiti da verificare** (spenta di serie), con il massimo di casi per giro (5) e la confidenza minima (60) sotto cui la risposta viene scartata; **gira** con la lettura **cpe_ai** ogni 6 ore e con **Proponi con l'AI ora** in Software e CPE. Riceve solo dati del sistema (nomi dei programmi, versioni, numero di PC, range delle CVE): mai testi di mail. Le proposte si accettano o rifiutano in Software e CPE e nella scheda CVE: i dettagli sono nel capitolo «Automatismi e vulnerabilità».

### Come impara

- Quando promuovi un evento ad alert o confermi che è a posto, la scelta viene ricordata: la volta dopo l'AI tiene conto di come avete deciso su eventi simili.
- Gli alert chiusi, scartati e i motivi scritti diventano lo storico che l'AI usa per i consigli successivi. Motivi chiari ("job di test spento il 12/03") rendono i consigli migliori.

### Limiti

- Le risposte richiedono qualche secondo; se l'AI non è raggiungibile, la pagina lo dice e il resto funziona normalmente.
- Le risposte vengono conservate per un po' (da 30 minuti a qualche giorno, secondo la funzione): finché i dati non cambiano, ripetere la richiesta dà la stessa risposta, segnata «risposta già pronta».
- L'AI può sbagliare: verifica sempre i fatti prima di agire, soprattutto prima di chiudere o notificare.
- Ogni richiesta all'AI viene registrata (chi, quando, su cosa, con quale esito) per la tracciabilità; il testo della risposta non viene archiviato nel registro.
- Sotto ogni risposta c'è il promemoria: testo generato dall'AI, da verificare prima di agire.
