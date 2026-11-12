# Lavoro quotidiano

Come si usa il SOC ogni giorno: da dove partire, come si lavorano alert, eventi e ticket, come si trova un PC. Le impostazioni e la configurazione sono in altri capitoli.

## Il menu del SOC

In cima a ogni pagina c'è l'intestazione blu con il nome della pagina, la casella **Cerca** e il «?» che apre la guida della pagina. Sotto, il menu ha cinque voci con un'icona; un numero rosso o arancione accanto a una voce dice che lì c'è qualcosa da guardare (Segnalazioni: alert critici e alti più scadenze NIS2; Dispositivi: PC con backup ko; Impostazioni: sorgenti mute). La voce aperta mostra le sue pagine in una seconda riga:

| Voce | Pagine |
| --- | --- |
| **Da fare** | Panoramica (pagina di partenza), Tutto ciò che è aperto |
| **Segnalazioni** | Tutte, Alert, Proposte AI, Ticket, Incidenti, Eventi |
| **Dispositivi** | Elenco (fonti, backup, CVE e asset di ogni dispositivo), Backup, Patch, Software, Rete (IP), Vulnerabilità, Accessi VPN |
| **Report** | Report, Storico, KPI |

Due pagine di Dispositivi raccolgono più pagine, che si scelgono da una terza riga sotto il menu: **Patch** (Da installare e protezione, Installate, Installazioni da console, Tempi) e **Vulnerabilità** (CVE sui PC, Correzioni, Rischi accettati, Librerie del portale).
| **Impostazioni** | Panoramica, Avvisi e automatismi, Letture automatiche, Soppressioni, Guida |

La **Panoramica** delle impostazioni (solo con il permesso di configurazione) apre tutte le altre pagine, divise per compito: *Da dove arrivano i dati* (caselle mail, letture automatiche, sorgenti e parser, inventario software, software e CVE), *Cosa diventa un alert* (regole, soppressioni, automatismi di rientro, backup attesi), *Chi viene avvisato* (avvisi e automatismi, canali di notifica, ticket), *Controllo e manutenzione* (diagnostica, autoconfigurazione, elaborazione, registro modifiche, impostazioni tecniche). Ogni voce dice a cosa serve e com'è messa («2 caselle attive · ultima lettura oggi alle 12:10»; pallino verde, arancione o rosso). In cima **Da sistemare** elenca solo le cose concrete da fare (nessuna casella attiva, letture con errore, nessun canale di notifica, software da collegare alle CVE, sorgenti in ritardo, job di backup non configurati), ognuna con il link. Nelle pagine aperte dalla Panoramica, sotto il menu, «← Configurazione» riporta indietro.

## Da dove partire

1. Apri **Panoramica**. In alto c'è il verdetto della giornata con il numero delle segnalazioni aperte (le urgenti sono nella barra di stato), sotto l'elenco **Da guardare adesso**, ordinato dal più grave: notifiche NIS2/GDPR in scadenza, alert critici, PC con backup ko, computer senza protezione, CVE gravi sui nostri PC, sorgenti che non mandano più report. Ogni voce porta al dettaglio. A destra la sintesi dell'AI e le **Fonti dati**, con l'ora dell'ultimo report di ogni casella.
2. Se ti serve un riassunto, in **Sintesi del giorno** premi **Chiedi all'AI**: l'AI aziendale riassume in poche frasi cosa è più urgente e da dove partire. Nessun dato esce dall'azienda.
3. Apri **Da fare › Tutto ciò che è aperto** (seconda riga del menu): tutti gli incidenti, i ticket e gli alert ancora aperti, per tutto il team, con le scadenze più vicine in alto. Non c'è un elenco «per persona»: chi è libero prende la voce in cima.
4. Guarda **Postura dei PC**: un riquadro per PC con il suo **indice di postura** (0-100, la stessa regola e lo stesso numero della scheda del dispositivo), dal peggiore. In alto l'indice medio e i filtri **A rischio** (sotto 50), **Da migliorare** (50-79), **Postura buona** (80 e oltre), più la ricerca per nome. Passando sopra a un riquadro si vede il motivo principale; un clic apre la scheda del PC. Accanto al numero una freccia dice di quanto è cambiato in 7 giorni (▼ rossa se peggiora, ▲ verde se migliora). Il calcolo resta in memoria 10 minuti: **Ricalcola** lo rifà subito.
5. Guarda **Le aree** della Panoramica (firewall, computer, backup, accessi VPN, vulnerabilità, Secure Score). Sotto ogni numero è scritto se è l'**ultimo valore letto**, il **totale degli ultimi 7 giorni** o lo stato di **adesso**. Le aree senza dati stanno in fondo. Se la data dell'ultimo dato è segnata come **dati vecchi**, quella fonte non sta arrivando e i suoi numeri vanno letti con prudenza. L'area **Vulnerabilità** conta le CVE che colpiscono i nostri PC secondo l'inventario software e la quota di software controllabili (collegati a un CPE). In fondo, **Andamento**: il grafico degli ultimi 7 giorni con i totali del periodo.

## La barra di stato

Sotto il menu ci sono quattro riquadri che si aggiornano da soli ogni minuto: verde se è tutto a posto, arancione o rosso se c'è da intervenire. Ogni riquadro è un link:

| Voce | Cosa conta |
| --- | --- |
| segnalazioni urgenti | Alert, ticket e incidenti aperti critici o alti, più gli incidenti con una notifica di legge scaduta o in scadenza. Apre **Segnalazioni › Solo urgenti** |
| scadenze NIS2/GDPR | Incidenti con una notifica scaduta o in scadenza entro 12 ore |
| PC con backup ko | PC e server con l'ultimo backup fallito o senza un backup riuscito oltre la soglia. Apre **Backup › Solo backup ko** |
| sorgenti in ritardo | Caselle che non mandano report nei tempi attesi. Apre **Impostazioni › Caselle mail** filtrato su **In ritardo**: la colonna **Report** dice «Nessun report» o «Lettura ferma», con l'ultimo report e la cadenza attesa |

Il colore dice la situazione: verde a posto, arancione da guardare, rosso urgente. A destra c'è l'ora dell'ultimo report arrivato.

### Un numero, un significato

Ogni numero del SOC ha una sola definizione e si legge allo stesso modo ovunque compaia: riquadri, numeri sul menu, Panoramica ed elenchi. Il numero rosso su **Segnalazioni** nel menu è lo stesso dei riquadri «segnalazioni urgenti» e del chip **Solo urgenti**; il numero su **Dispositivi** è quello dei PC con backup ko, uguale al riquadro della barra e al filtro **Backup ko** dell'elenco Dispositivi (tutti guardano gli ultimi 90 giorni di report). Il clic su un numero apre un elenco con esattamente quelle righe. I backup si contano sempre **per PC**: i singoli job falliti si vedono nella scheda del PC e nella pagina Backup.

## Cercare qualcosa

La casella **Cerca** in alto trova anche i **programmi installati** (con quanti PC li hanno: un clic apre Dispositivi › Software filtrato) e i PC per **indirizzo IP**, **MAC** o **seriale** (da DHCP/DNS, Intune e WatchGuard).

La casella **Cerca** nel menu del SOC trova incidenti, ticket, alert, PC e server, vulnerabilità. Basta un pezzo di nome: un nome PC, un codice `INC-…`, un numero di ticket, una CVE. Servono almeno due caratteri.

## Anteprime e selezione multipla

- **Anteprima**: nelle liste (alert, ticket, incidenti, eventi, PC, Da fare, alert collegati a un ticket o a un incidente, chiusi dall'AI) un clic sulla riga (non sul link né sulla casella) apre il dettaglio in un pannello laterale, senza perdere la lista. Con le frecce **←** e **→** passi alla riga precedente o successiva, con **Esc** chiudi. Le azioni del pannello (prendere in carico, chiudere…) restano sulla lista. Nel pannello del **ticket** c'è anche **Cambia stato** (per chiudere scrivi l'esito, come nella scheda); in quello dell'**incidente** **Assegna a me**; in quello del **PC** **Apri un ticket per questo PC**. Nelle tabelle delle patch e nella scheda CVE il nome del PC apre il suo pannello (Ctrl+clic: la scheda PC).
- **Raggruppa**: sopra ogni tabella del SOC, **Raggruppa ▾** divide le righe per una colonna (per PC, per patch, per CVE, per stato, per responsabile…). Ogni gruppo mostra quante righe ha e si apre o chiude con un clic; la sua casella seleziona tutte le righe del gruppo per le azioni multiple. Una patch che corregge più CVE compare sotto ognuna (le copie sono più chiare e non selezionabili). La scelta resta salvata per te.
- **Dove si selezionano più righe**: Segnalazioni, Alert, Ticket, Incidenti, Eventi, Backup (PC, job, log), **Dispositivi** (ticket per i PC scelti, e **Collega gli asset proposti** per chi configura il SOC), **Patch e protezione › Installazioni non riuscite**, **Tempi delle patch › Patch ferme** (un ticket con un'attività per ogni PC delle patch scelte), **Vulnerabilità › Asset più esposti** e la tabella **Esito per host** della scheda CVE (ticket, **Accetta il rischio** sui PC scelti, **Conferma le proposte dell'AI**), **Proposte AI › Chiusi dall'AI** (**Riapri le selezionate**, con il perché obbligatorio), **Soppressioni** e **Rischi accettati** (revoca insieme, con un motivo unico). In Rischi accettati un clic sulla riga apre il pannello della CVE.
- **Selezione multipla**: la casella in testa alla riga seleziona; la casella nell'intestazione seleziona tutte le righe della pagina. In fondo compare la barra con le azioni possibili e il conto dei selezionati. Le righe in uno stato non compatibile vengono saltate e il messaggio finale lo dice.

## Scaricare gli elenchi (CSV)

Accanto ai filtri di **Segnalazioni**, **Alert**, **Ticket**, **Incidenti**, **Eventi**, **Accessi VPN**, **Dispositivi**, **Backup › Log completo**, **Vulnerabilità** (elenco CVE), **Correzioni CVE**, **Patch installate** e **Tempi delle patch** c'è **Scarica CSV**; in **Prove di ripristino** il pulsante sta sul registro. Il file contiene **tutte** le righe dei filtri scelti, non solo quelle a video: anche oltre la pagina, oltre il taglio delle 300 segnalazioni per tipo, delle 300 esecuzioni di backup e delle 500 CVE. Colonne in italiano, separatore «;» (si apre con Excel), date «gg/mm/aaaa hh:mm», stati e gravità come a video. Una cella che inizia con «=», «+», «-» o «@» viene protetta con un apice, così Excel non la esegue come formula. Lo scarico richiede l'accesso al SOC, come la pagina, e resta nell'audit del portale con il numero di righe e i filtri.

## Le segnalazioni

**Segnalazioni › Tutte** mette in un elenco solo gli alert, i ticket e gli incidenti. L'ordine è quello di lavoro: prima le notifiche NIS2/GDPR scadute o in scadenza, poi la gravità (critico, alto, attenzione, medio, basso, info), poi le più vecchie. In alto i chip **Tutte / Alert / Ticket / Incidenti** mostrano quante ce ne sono con lo stato, la gravità e il testo scelti; sotto si filtra per **Stato** (Da gestire, Chiuse, Tutte), **Gravità** e testo (titolo, PC, CVE, sorgente). L'elenco si ferma alle 300 più recenti per tipo: quando succede (capita soprattutto con «Chiuse» o «Tutte») un avviso giallo dice «Elenco tagliato: mostrate N di M» e **Scarica CSV** le contiene tutte.

Ogni riga dice il tipo, la gravità, che cosa è, dove (il PC o la sorgente), lo stato, da quanto tempo è aperta e chi se ne occupa. Un clic sulla riga apre l'anteprima laterale con le azioni; il titolo apre la pagina completa.

**Più righe insieme.** Ogni riga ha una casella: selezionane quante vuoi (Maiusc+clic per un intervallo, la casella in testa per tutte quelle visibili) e in basso compare la barra con il numero dei selezionati e le azioni del tipo scelto: per gli alert **Prendi in carico**, **Chiudi**, **Segna falso positivo** (il motivo è obbligatorio) e **Apri un ticket con i selezionati**; per i ticket **Assegna a me** e **Cambia stato** (per chiudere serve l'esito); per gli incidenti **Diventa responsabile** e **Cambia stato**. Si lavora un tipo alla volta: appena selezioni un alert, le caselle dei ticket e degli incidenti si spengono finché non premi **Annulla**.

**Alert simili dall'anteprima.** Nel pannello di un alert, sotto le azioni, il riquadro **Alert simili** dice quanti altri alert aperti riguardano la **stessa CVE** sugli altri PC, lo **stesso software** (tutte le CVE di quel programma) e lo **stesso PC**; per gli alert non legati a una CVE vale lo stesso problema sullo stesso PC, job o utente. Per ogni criterio vedi anche quanti sono **già stati chiusi e come**: l'esito (risolto, non rilevante, rischio accettato, falso positivo), chi ha deciso, quando e il motivo scritto; il nome del PC apre quell'alert nel pannello. Con **Chiudi insieme** scegli il criterio, l'esito e scrivi il motivo: chiude questo alert e tutti i simili aperti in un colpo, il motivo resta su ognuno e un alert arrivato dopo che avevi aperto il pannello resta aperto. **Chiudi solo questo** chiude il singolo alert come prima. Per gli alert CVE il pannello mostra anche CVE (con link alla scheda), CVSS, il segno **Sfruttata (KEV)**, il software e il termine di correzione con i giorni di ritardo; il dispositivo viene dai dati dell'alert anche quando non è collegato a un asset. Gli **Eventi** letti dai report non sono nell'elenco: sono molti e per lo più già giudicati a posto, quindi hanno la loro scheda.

## Alert

La **Coda alert** è l'elenco di ciò che il motore ha giudicato un problema. Filtra per stato (di default «Da gestire»), severità e sorgente. Il chip **Tutte** dice quanti alert trovano i filtri; l'elenco li mostra tutti, cento per pagina, con i numeri di pagina in fondo e il totale delle righe (lo stesso vale per **Ticket** e **Registro incidenti**).

### Leggere un alert

La scheda dell'alert risponde a quattro domande:

- **In parole semplici**: premi **Spiega con l'AI** per avere cosa è successo, perché è scattato, quanto è urgente e cosa fare. L'AI tiene conto dello storico mostrato nella pagina.
- **Come risolverlo**: se l'AI ha già esaminato l'alert in automatico, in cima c'è la sua **Proposta automatica** (esito, motivo, prove) con **Conferma e chiudi** e **Scarta** (sezione «Proposte di chiusura dell'AI» qui sotto). **Proponi la soluzione** dà la causa probabile, i passi per risolvere (dalla procedura standard e da come sono stati chiusi gli alert simili) e come verificare. Sotto arriva il modulo di chiusura già compilato con l'esito proposto (Risolto, Non rilevante, Rischio accettato o Falso positivo) e il motivo: correggilo se serve e chiudi solo dopo aver fatto i passi. Con **Cerca anche sul web** l'AI legge anche gli avvisi ufficiali sui codici CVE, KB o d'errore dell'alert (capitolo «Impostazioni e AI»).
- **Perché è stato generato**: la regola che è scattata e i valori che l'hanno fatta scattare.
- **Cosa sappiamo dagli altri dati del portale**: gli stessi indirizzi, utenti, PC o job incrociati con lo storico (accessi VPN, backup, asset), i precedenti e gli alert simili già chiusi o scartati.
- **Come rispondere**: la procedura consigliata per quel tipo di alert. **Apri ticket con questi passi** crea il ticket con i passi già come attività.

Più in basso: il ticket collegato, la timeline di tutto ciò che è successo all'alert, le occorrenze, le evidenze e il report da cui è nato.

### Le azioni

| Azione | Quando usarla |
| --- | --- |
| Prendi in carico | Te ne occupi tu: nell'alert resta scritto chi l'ha preso in carico |
| Posticipa (in coda: **Rimanda fino al…**) | Non si può fare nulla adesso: l'alert torna da gestire alla data scelta. Dalla coda si rimandano più alert insieme fino al giorno scelto |
| Chiudi con esito «Risolto» | Il problema era vero ed è stato sistemato |
| Chiudi con esito «Non rilevante» o «Rischio accettato» | Il problema c'è ma non va gestito, con il motivo |
| Falso positivo | Non era un problema |
| Silenzia | Rumore noto su questo alert |
| Riapri | Un alert chiuso va ripreso in mano |

Falso positivo, «Non rilevante», «Rischio accettato» e Silenzia chiedono un motivo e contano per la **soppressione appresa**: dopo tre volte lo stesso alert non viene più aperto. Vedi il capitolo [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#soppressione-appresa). Le differenze tra gli stati sono spiegate in [Ciclo di vita degli alert](/soc/docs/07-alert-lifecycle/).

## Proposte di chiusura dell'AI

**Segnalazioni › Proposte AI** è il punto da cui smaltire gli alert aperti: sono raggruppati, e l'AI locale lavora sui gruppi. In testa conta gli alert **da decidere**: gli aperti senza i rimandati e i silenziati, che hanno già una decisione a tempo; per questo il numero può essere più basso degli alert aperti di Segnalazioni.

**Gruppi.** Lo stesso problema sullo stesso PC, job di backup o utente è un gruppo; le CVE stanno tutte nel gruppo del loro tipo. La pagina mostra i tipi di alert dal più grave e, dentro, i gruppi: scegli l'esito, scrivi il motivo e premi **Chiudi i N alert**. **Chiudi tutti i N** fa lo stesso per tutto il tipo. Il motivo è obbligatorio e resta su ogni alert; un alert arrivato mentre avevi la pagina aperta resta aperto. Una chiusura di gruppo conta come una decisione sola, anche per quello che impara l'AI.

Ogni 15 minuti (lettura «ai_proposte»), per i gruppi dal più grande, l'AI esamina l'alert più recente, purché aperto da almeno 2 ore e non più vecchio di 60 giorni:

1. il portale raccoglie le **prove** dai report arrivati dopo l'alert: se lo stesso evento si è ripetuto o no, l'ultima esecuzione del job di backup, gli altri report sullo stesso PC, utente o IP;
2. aggiunge le **decisioni passate** su alert dello stesso tipo (stessa sorgente e stesso tipo di evento, prima quelli sullo stesso PC/job/utente): come li avete chiusi o riaperti e con quale motivo, e le proposte che avete scartato con la vostra nota;
3. l'AI propone l'esito (Risolto, Non rilevante, Rischio accettato, Falso positivo o «Lasciare aperto»), la confidenza, il motivo e le prove che lo dimostrano. Se non cita nessuna prova vera, la proposta diventa «Lasciare aperto».

Un alert viene riesaminato solo quando cambia qualcosa: un report nuovo, una decisione nuova sullo stesso soggetto, l'evento che non si ripete da 1, 3, 7, 14 o 30 giorni.

| Azione | Cosa succede |
| --- | --- |
| **Conferma e chiudi** | L'alert si chiude a tuo nome con l'esito proposto e il motivo (che puoi correggere). Conta come conferma |
| Chiudere l'alert in un altro modo | Dalla scheda dell'alert, con un altro esito: la proposta risulta «chiusa con un altro esito» e conta come errore |
| **Scarta** | L'alert resta aperto. Scrivi perché: la nota entra nelle decisioni passate dei prossimi alert dello stesso tipo |
| **Riapri** (tra i chiusi dall'AI) | L'alert torna aperto; anche la riapertura dalla scheda dell'alert vale. Conta come errore grave. Con **Riapri le selezionate** se ne riaprono più insieme: il perché è obbligatorio e resta su ognuno |

### Quando chiude da sola

Quando l'AI chiude da sola, chiude anche gli alert più vecchi dello stesso gruppo, ognuno con gli stessi limiti: un critico nel gruppo resta aperto.

Per ogni tipo di alert ed esito la tabella **Cosa ha imparato** conta le conferme di fila. Quando le ultime **5** (impostazione «Conferme per chiudere da sola») sono tutte conferme, le proposte successive con quell'esito chiudono l'alert da sole: nella timeline compare «Chiuso dall'AI (appreso da N conferme di fila)» con il motivo e le prove, attore `system:ai`. Non succede mai se:

- la confidenza è sotto l'**80%** (impostazione «Confidenza minima per chiudere da sola»);
- l'alert è critico, parla di minacce o malware, riguarda una CVE sfruttata attivamente (KEV) o un tipo escluso dalla soppressione appresa;
- l'AI non cita prove;
- la chiusura automatica è spenta.

Una correzione, una proposta scartata o un alert riaperto azzerano le conferme di quel tipo ed esito: l'AI torna a proporre soltanto finché non le riguadagna. Le chiusure fatte dall'AI non contano per la soppressione appresa. Le proposte di alert chiusi dalle regole di rientro, posticipati o silenziati diventano «superate».

Si regola in **Impostazioni › Avvisi e automatismi › Proposte di chiusura dell'AI**; tempi ed errori di ogni giro sono in **Letture automatiche** («Esegui ora» fa un giro più lungo subito).

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
- **Attività**: i passi da fare per chiudere il ticket, da spuntare man mano. Se c'è una procedura consigliata per quel tipo di problema, la aggiungi con un clic. **Proponi con l'AI** in «Prossimi passi» suggerisce cosa fare dopo (con **Cerca anche sul web** anche dagli avvisi ufficiali su CVE, KB e codici d'errore del ticket); scegli tu quali passi diventano attività.
- **Note di lavoro**: tutto quello che serve a chi verrà dopo. Finisce nella timeline insieme alle azioni sugli alert collegati.
- **Chiusura**: in **Cambia stato** scegli l'esito (Risolto, Chiuso, Falso positivo) e scrivi il motivo; con la spunta chiudi insieme gli alert ancora aperti. **Scrivi l'esito con l'AI** prepara una bozza da rivedere.
- **Chiusura automatica**: quando tutti gli alert del ticket rientrano da soli, il ticket si chiude come Risolto, a meno che abbia attività ancora da fare.
- **Incidente**: se il problema ha avuto un impatto reale, **Apri incidente** dal ticket. Vedi [Incidenti e report](/soc/docs/14-incidenti-e-report/).

Nella lista ticket il filtro **Responsabile › Non assegnati** mostra i ticket che nessuno sta seguendo.

## Analisi dello storico

La pagina **Storico** (Analisi dello storico) guarda indietro di 30, 90 o più giorni e mostra cosa migliorare:

- **Alert che si ripetono** e come sono finiti;
- **Falsi positivi ricorrenti**: candidati a una regola di soppressione; **Crea soppressione** (per chi configura il SOC) apre il modulo della soppressione manuale già compilato con nome, sorgente, tipo di evento e motivo, da rivedere prima di salvare;
- **Scartati dal motore** e **Allarmi mancati** (eventi promossi a mano);
- **Fermi**: alert aperti da più di 7 giorni, ticket fermi da più di 14;
- **Come sono stati chiusi**: i motivi scritti da chi li ha gestiti.

**Analizza con l'AI** propone fino a 5 azioni (soppressioni, cause da risolvere alla radice, ticket da chiudere o riassegnare). Non cambia nulla: decidi tu.

## Caricare un report a mano

Di solito i report arrivano da soli dalle caselle mail. Quando un report non è arrivato, oppure ne hai uno da un'altra fonte, lo carichi da **Impostazioni › Carica report** ([apri](/soc/inbox/)).

1. In **Carica o incolla un report** scegli il **File del report** (PDF, CSV, TXT, EML o LOG), oppure incolla il contenuto in **Testo**.
2. Compila **Mittente** e **Oggetto** come nella mail originale: servono a riconoscere la sorgente.
3. In **Sorgente** lascia **Riconoscimento automatico**, oppure scegli tu la sorgente e il parser se sai da dove viene il report.
4. **Tipo di contenuto** si lascia vuoto, salvo casi particolari (per esempio `text/plain` per un testo incollato).
5. Premi **Elabora report**.

Il report viene elaborato subito, come se fosse arrivato per mail: gli alert e i ticket che ne nascono sono veri. In **Ultimo risultato** vedi l'esito (**Riuscita**, **Scartato** se il report non è stato elaborato, per esempio perché già arrivato, **Errore**), la sorgente riconosciuta, il parser usato e quante metriche, eventi, alert, evidenze e ticket ha prodotto, con gli avvisi e gli errori.

Se la sorgente risulta «Nessuna» o il parser è vuoto, il report non è stato letto: scegli la sorgente a mano e riprova, oppure verifica con la [Diagnostica](/soc/docs/17-moduli-diagnostica-documentazione/#provare-se-una-mail-viene-riconosciuta).

Sotto ci sono **Ultimi 10 report**, **Ultimi 10 messaggi ricevuti** e **Ultimi 10 file caricati**, con il loro stato, e l'elenco **Sorgenti e parser** configurati.

## Scheda PC e server

Dall'elenco Dispositivi, da un risultato di ricerca, dalla pagina Backup o Vulnerabilità o da un alert si apre la **scheda PC**. Mostra solo quello che sanno le fonti del SOC e le caratteristiche della macchina: niente manutenzione né altro del registro asset (per quello c'è il pulsante **Scheda asset**). Si apre anche per i PC visti solo da Intune o dall'inventario software.

- **Testata**: nome, produttore e modello, utente, verdetto, release di Windows (rossa se fuori supporto, gialla se in scadenza), quante fonti su 4 vedono il PC, seriale, IP, MAC, switch e porta, asset collegato. A destra l'**Indice di postura** e i pulsanti **Controlla con l'AI**, **Scheda asset**, **Patch e protezione**, **Log backup**.
- **Indice di postura (0-100)**: è lo stesso numero della mappa **Postura dei PC** in Panoramica. In Panoramica, sopra «Cosa abbassa il punteggio», la linea dell'**andamento** (una fotografia per notte, con minimo, massimo e differenza sugli ultimi 7 giorni). In testata c'è anche **Apri un ticket per questo PC**. Si parte da 100 e si toglie: ultimo backup fallito −25, non recente o assente −10; alert aperti −20 per i critici e −5 per gli altri (al massimo −30); CVE gravi (KEV o CVSS ≥ 9) −5 ciascuna (al massimo −25), altre CVE −1 ciascuna (al massimo −10); senza agente WatchGuard −15, protezione non attiva −20, agente che non si collega da più di 7 giorni −5; ogni problema Intune −10; Windows fuori supporto −20, in scadenza −5; patch mancanti −3 per le critiche più −1 ogni 5 altre (al massimo −15). Verde da 80, giallo da 50, rosso sotto. È una sintesi dei fatti in pagina: non cambia altri numeri del SOC.
- **Riquadri**: Backup (con le ultime 14 esecuzioni), Alert aperti, CVE (le **CVE uniche**: una CVE vista sia dall'inventario sia da Defender conta una volta, stesso numero del pannello laterale e dell'elenco Dispositivi), Patch mancanti, Protezione EDR, Conformità Intune. Un clic apre la sezione giusta.
- **Panoramica**: il **flusso dei dati** (a sinistra le fonti Intune, WatchGuard, Defender, Backup, DHCP/DNS; al centro il PC; a destra alert, vulnerabilità, patch, software, minacce), **Cosa abbassa il punteggio** (ogni riga apre la sua sezione), la tabella delle fonti con l'ultimo contatto e l'esito del controllo AI.
- **Caratteristiche**: produttore, modello, seriale, RAM, disco (barra gialla dall'80% usato, rossa dal 90%), sistema, versione, fine supporto, agente WatchGuard, utente e account, data di registrazione e ultima sincronizzazione Intune, indirizzi di rete dal DHCP/DNS.
- **Protezione**: stato WatchGuard (protezione, motore e firme, riavvio, isolamento, ultima connessione, agente), Intune (criteri, BitLocker, sincronizzazione, problemi aperti) e rilevamenti endpoint.
- **Vulnerabilità e patch**: anello per gravità (clic sulla legenda per filtrare: sfruttate KEV, critiche ≥ 9, alte 7-9, medie e basse; fino a 60 CVE), patch mancanti WatchGuard per criticità (le prime 25) e installazioni fallite degli ultimi 14 giorni.
- **Software**: in alto quattro riquadri che filtrano l'elenco (tutti i programmi con il numero di produttori, con vulnerabilità note, con CVE gravi, non visti da più di 7 giorni) e i conteggi per fonte (WatchGuard, Defender: un clic filtra). Sotto: ricerca (tasto **/** per andarci, **Esc** per svuotare), produttori a pulsante (clic di nuovo per togliere), **Togli i filtri**. I filtri si combinano. Ogni riga ha il produttore, la versione, le CVE che colpiscono quel programma (es. «2 CVE · 1 grave», un clic apre Vulnerabilità e patch; «✓ nessuna» se non ce ne sono), le fonti (WG, DEF) e quando è stato visto l'ultima volta (in giallo se più di 7 giorni fa). Clic sull'intestazione di Programma, Versione, CVE o Visto per ordinare.
  Sotto l'elenco: **Storico delle versioni** (ultimi 6 mesi, i programmi che hanno cambiato versione sul PC, con la data di ogni versione; «non più installato» se è stato tolto) e **Aggiornamenti installati (KB)** letti da WatchGuard, che non sono programmi e non contano nelle CVE.
- **Backup**: esito, ultimo riuscito, percentuale di riuscite, dati, striscia delle esecuzioni e ultime 15 righe.
- **Timeline**: gli ultimi 30 fatti da tutte le fonti (backup, alert, protezione, patch fallite, eventi), raggruppati per giorno (Oggi, Ieri, data) con icona e colore per gravità. Sopra c'è il grafico dell'attività degli ultimi 14 giorni: l'altezza è il numero di fatti, il colore il fatto più grave del giorno; un clic porta a quel giorno. I filtri per tipo mostrano quanti fatti ci sono e sono spenti se zero. Un evento che ha già il suo alert compare una volta sola, come alert.

La sezione aperta resta nell'indirizzo (es. `#software`): si può mandare il link già sulla sezione giusta.

## Software

Pagina **Dispositivi › Software**: tutti i programmi installati sui PC, una riga per programma. Le versioni e i nomi diversi dello stesso programma (es. «7-Zip 25.01 (x64)» e «7-Zip 26.05») sono una riga sola, come nel catalogo di Asset: stesse righe e stessi numeri. Le fonti sono WatchGuard (letto tre volte al giorno) e Microsoft Defender.

- **Riquadri in alto** (un clic filtra): programmi installati, con CVE (e quante in tutto), non autorizzati o da rimuovere, sotto la versione minima, comparsi di recente.
- **Ricerca**: scrivi una o più parole del nome o del produttore; trattini e spazi non contano («7zip» trova «7-Zip», «acro writer» trova «CutePDF Writer» di Acro Software). L'elenco si filtra mentre scrivi; con **Invio** la ricerca resta nell'indirizzo e si può mandare il link. Il tasto **/** porta alla ricerca.
- **Filtri**: Tutti, Con CVE, CVE non controllate (programma non collegato a un CPE), Nuovi, Da classificare, Non autorizzati, Da rimuovere, Versioni vecchie, A pagamento senza licenza. Il numero accanto è uguale alle righe.
- **Colonne**: programma e produttore, quanti PC lo hanno, quante versioni (e quante sotto la minima), CVE, decisione, licenza. Clic sull'intestazione di Programma, PC, Versioni o CVE per ordinare.
- **Clic su una riga**: si apre il pannello laterale con le versioni installate (quanti PC per versione) e i PC che hanno il programma, con versione, CVE di quella installazione, fonti (WG, DEF) e ultimo avvistamento. Il nome del PC apre la sua scheda sulla sezione Software. In fondo il link al catalogo di Asset per decisione, licenza e versione minima.

**Doppioni tra le fonti**: lo stesso programma visto da WatchGuard e da Defender con nomi diversi («onedrive» e «Microsoft OneDrive») diventa una riga sola. Ogni ora, senza nessuno: prima si uniscono le righe con stesso PC, stessa versione e nome equivalente; poi le coppie dal nome simile passano all'AI locale. Se l'AI è sicura almeno quanto la soglia (85% di base) e la versione coincide su almeno metà dei PC in comune, l'unione si fa da sola; altrimenti la coppia compare nel riquadro **Doppioni tra le fonti** in cima alla pagina, con le versioni delle due fonti, la confidenza e il motivo dell'AI: **Unisci** o **Sono diversi** (serve il permesso di configurazione del SOC). «Unite negli ultimi 30 giorni» elenca chi ha unito (una persona o «in automatico») con **Annulla**: al giro successivo delle due fonti le righe tornano separate. Ogni unione e annullamento resta nell'audit.

I programmi che WatchGuard elenca senza versione ora compaiono nell'inventario (prima venivano scartati), ma restano fuori dal confronto con le CVE: senza versione non c'è niente da confrontare. Gli aggiornamenti di sistema (KB) che WatchGuard elenca insieme ai programmi non sono programmi e non compaiono qui: le patch installate sono in **Dispositivi › Patch › Installate**.
