"""Guida d'uso del modulo KICK-OFF (pulsante «? Guida» in testa alle pagine).

Guida completa: stessa forma della guida del modulo Anomalie. Le guide rapide per
ruolo stanno in ``tasks/guida_ruoli.py``. Si apre su ``/tasks/guida/``; ``?per=<ruolo>``
apre una guida rapida, ``?pdf=1`` (con o senza ``per``) scarica il PDF.

Testo semplice, niente HTML: il template lo mostra con l'autoescape e il PDF lo passa
da ``escape()``. Blocchi di una sezione: ("p", testo) paragrafo, ("passi", [voci])
passi numerati, ("ul", [voci]) elenco, ("nota", testo) riquadro di attenzione,
("def", [(termine, spiegazione)]) definizioni, ("img", (percorso static, didascalia)).
Le immagini sono in ``tasks/static/tasks/guida/`` e mostrano dati di esempio.
Le etichette citate sono quelle visibili nelle pagine: se ne cambia una, va
aggiornata anche qui. Il testo alimenta anche l'assistente AI del portale.
"""
from __future__ import annotations

DOC_TITOLO = "KICK-OFF"
DOC_SOTTOTITOLO = "Guida completa del modulo nel portale NOVICROM HUB"

_IMG = "tasks/guida/"

SEZIONI: list[dict] = [
    {
        "id": "scopo",
        "titolo": "A cosa serve il KICK-OFF",
        "blocchi": [
            ("p", "Il modulo KICK-OFF segue una commessa dall'avvio all'esecuzione: la scheda di commessa con "
                  "il documento VRF, il team, le attività pianificate sul Gantt e gli incontri con il loro esito."),
            ("def", [
                ("Commessa (kickoff)", "la scheda «Cliente · P/N · KICK-OFF n» con team, fase e VRF."),
                ("Scheda VRF", "il modulo MOD.073 «Scheda valutazione rischi e fornitura»: 9 rischi con probabilità, gravità e Totale Rischio."),
                ("Attività", "lavoro pianificato con data inizio, data fine, responsabile e avanzamento. Compare sul Gantt."),
                ("Incontro", "riunione di commessa: convocazione, conduzione, esito e minuta."),
                ("Azione", "impegno deciso in un incontro: chi fa cosa entro quando."),
                ("Problema", "criticità emersa in un incontro, seguita finché non è risolta."),
                ("Decisione", "scelta presa in un incontro, conservata nel registro decisioni della commessa."),
            ]),
            ("p", "In alto, le voci del modulo: «Dashboard» (il tuo quadro), «Da gestire» (cosa richiede intervento), "
                  "«Kickoff» (l'elenco delle commesse), «Calendario» (gli incontri) e, per chi le gestisce, «Impostazioni». "
                  "Dentro una commessa le schede sono «Panoramica», «Azioni», «Incontri», «Piano» e «VRF»."),
            ("nota", "Non vedi un pulsante descritto qui? Dipende dai permessi: vedi «Chi può fare cosa»."),
        ],
    },
    {
        "id": "percorso",
        "titolo": "Il percorso di una commessa",
        "blocchi": [
            ("p", "Il giro completo, dall'inizio alla fine. Ogni passo ha il suo capitolo più avanti."),
            ("passi", [
                "Crea la commessa con «+ Nuovo kickoff»: cliente, P/N e team. Nasce da sola l'incontro 1.",
                "Si apre la convocazione dell'incontro 1: data, luogo, partecipanti e ordine del giorno. Salva e premi «Invia convocazione».",
                "Compila la scheda VRF dalla scheda «VRF» della commessa, oppure carica il file Excel del modulo.",
                "Scrivi il piano nella scheda «Piano», con la riga rapida sopra il Gantt.",
                "Il giorno dell'incontro usa «Conduci incontro»; alla fine registra l'esito, invia la minuta e approvala.",
                "Quando il semaforo di prontezza è verde («Pronto»), porta la commessa «In esecuzione».",
                "Durante il lavoro aggiorna le attività e tieni i successivi incontri: problemi e azioni aperti tornano da soli nell'ordine del giorno.",
                "A lavoro finito porta la commessa in «Completata».",
            ]),
        ],
    },
    {
        "id": "dashboard",
        "titolo": "Dashboard: il tuo quadro",
        "blocchi": [
            ("p", "«Dashboard» è la pagina «Control room KICK-OFF». Si legge dall'alto verso il basso."),
            ("ul", [
                "I riquadri in alto contano le attività nel tuo perimetro: In scope, In corso, Da fare, Overdue (scadute e ancora aperte), Completate, Annullate.",
                "«Prossimi incontri»: data, commessa e quanto manca.",
                "«Incontri da gestire»: esito mai registrato per un incontro passato, minuta da approvare, problemi rimasti aperti, con il pulsante per farlo subito.",
                "«Le mie azioni»: le azioni e i problemi a tuo nome, scaduti in testa.",
                "«Alert operativi»: attività non assegnate, senza data fine, in scadenza a 7 giorni, ferme da oltre 7 giorni; quante commesse sono Pronte, Quasi pronte, Non pronte.",
                "«Le tue attività»: l'elenco, con «Le mie» o «Tutto lo scope» e i filtri «In corso» e «Overdue».",
            ]),
            ("img", (_IMG + "dashboard.jpg", "La dashboard del modulo")),
        ],
    },
    {
        "id": "portfolio",
        "titolo": "Kickoff: l'elenco delle commesse",
        "blocchi": [
            ("p", "La voce «Kickoff» apre il «Portfolio kickoff», con tutte le commesse che puoi vedere."),
            ("ul", [
                "Filtri: «Cerca» (nome, P/N, cliente), «Cliente», «Stato VRF» (Caricato, In attesa, Bloccato, Da caricare).",
                "«Ordina per»: Nome, Scadenza più vicina, Avanzamento, Criticità. Premi «Filtra» per applicare, «Reset» per togliere tutto.",
                "Sulla card trovi numero, cliente, P/N, data di inizio (il primo incontro non annullato), fase, semaforo di prontezza, team e stato del documento VRF.",
                "Pulsanti della card: «Attivita», «Gantt», «Incontri», «Copia VRF», «Copia senza P/N».",
            ]),
            ("img", (_IMG + "portfolio.jpg", "Il portfolio nella vista Card")),
            ("p", "«Vista» cambia il modo di leggere le stesse commesse:"),
            ("def", [
                ("Card", "una scheda per commessa, la vista predefinita."),
                ("Board", "una colonna per fase: Bozza, VRF, In esecuzione, Completata. Chi può modificare trascina la card, o usa il menu sulla card, per cambiare fase."),
                ("Timeline", "una barra per commessa sul calendario, colorata in base alla prontezza, con il segno di oggi."),
            ]),
            ("img", (_IMG + "board.jpg", "La vista Board: le commesse per fase")),
        ],
    },
    {
        "id": "nuovo-kickoff",
        "titolo": "Creare una commessa",
        "blocchi": [
            ("passi", [
                "Premi «+ Nuovo kickoff».",
                "Identificazione: «Cliente» è l'unico campo obbligatorio; i suggerimenti propongono clienti e P/N già usati. Aggiungi P/N, revisione, versione, metodo di controllo e descrizione.",
                "Lascia vuoto «Nome del kickoff»: viene composto da solo come «Cliente · P/N · KICK-OFF n». Scrivilo solo se quella formula non basta.",
                "Spunta «Impatto sulla sicurezza» se il lavoro lo richiede: la commessa viene evidenziata nelle viste.",
                "Dati scheda VRF: preventivo ed Esp., se li hai. La «Descrizione» scritta sopra finisce anche nella scheda VRF.",
                "Team di progetto: cerca la persona nel riquadro di ogni ruolo e spuntala. Le persone scelte appaiono come etichette, con × per toglierle. Ogni ruolo può avere più persone.",
                "Cosa serve a questa commessa: togli la spunta alle tappe che non servono (per esempio Terzista o Processi speciali). Si può cambiare dopo da «Modifica kickoff» o dal Percorso.",
                "Primo incontro: data, ora e sala.",
                "Premi «Crea kickoff e convoca il primo incontro»: nasce l'incontro 1 con il team tra i partecipanti e, come ordine del giorno, le tappe che servono. Si apre la convocazione, con la disponibilità delle sale e l'invito Outlook.",
            ]),
            ("img", (_IMG + "nuovo_kickoff.jpg", "Il form «Nuovo kickoff»")),
            ("ul", [
                "Basta un referente del team per creare la commessa; per risultare pronta all'avvio servono Project manager, Capocommessa e Programmatore.",
                "Revisione e versione valgono solo con un P/N.",
            ]),
            ("nota", "Se P/N, revisione e versione corrispondono a un kickoff che esiste già, non ne nasce uno doppio: il portale apre quello esistente e lo dice con un messaggio."),
        ],
    },
    {
        "id": "modifica-kickoff",
        "titolo": "Correggere dati e team",
        "blocchi": [
            ("passi", [
                "Apri la commessa e premi «Modifica kickoff» (in Panoramica, nel Piano o nella scheda VRF).",
                "Correggi i dati o il team.",
                "Premi «Salva modifiche»: torni alla Panoramica.",
            ]),
            ("img", (_IMG + "modifica_kickoff.jpg", "«Modifica kickoff»: gli stessi campi della creazione")),
            ("ul", [
                "Il portale rifiuta un P/N, revisione e versione già usati da un altro kickoff.",
                "Il nome della commessa non cambia da solo se cambi cliente o P/N: se serve, correggilo.",
                "Il file VRF già generato non si aggiorna: se cambiano i dati, riapri la scheda e conferma di nuovo.",
            ]),
        ],
    },
    {
        "id": "panoramica",
        "titolo": "Panoramica e semaforo di prontezza",
        "blocchi": [
            ("p", "Cliccando una commessa arrivi alla «Panoramica»: team, data di inizio, prossimo incontro, azioni aperte, attività a piano, le prossime azioni e gli ultimi incontri."),
            ("p", "In alto «Prossimi passi» dice cosa fare adesso, nell'ordine del filo commessa → incontro → attività: pianificare il primo incontro, convocarlo, condurlo se è oggi, registrarne l'esito se è passato, approvare e inviare la minuta, assegnare le tappe del Percorso, pianificare l'incontro successivo. Ogni riga porta dove si fa. Il riquadro del prossimo incontro mostra ora, sala e stato della prenotazione."),
            ("img", (_IMG + "panoramica.jpg", "La Panoramica di una commessa")),
            ("p", "«Prontezza all'avvio» controlla quattro cose. Ogni voce non a posto ha il link «Correggi», che porta dove si sistema."),
            ("def", [
                ("VRF a posto", "scheda confermata o file caricato, oppure VRF segnato come non richiesto."),
                ("Incontro kickoff fatto", "un incontro svolto: non basta pianificarlo."),
                ("Team assegnato", "almeno un Project manager, un Capocommessa e un Programmatore."),
                ("Piano attività definito", "almeno un'attività con la scadenza."),
            ]),
            ("p", "Il semaforo dice «Pronto» con 4 su 4, «Quasi pronto» con 2 o 3, «Non pronto» con meno. È un'indicazione: non blocca niente da solo."),
        ],
    },
    {
        "id": "vrf",
        "titolo": "La scheda VRF (MOD.073)",
        "blocchi": [
            ("p", "La «Scheda valutazione rischi e fornitura» si apre dalla scheda «VRF» della commessa e si compila online; "
                  "in alternativa «Carica file esistente» prende il file Excel del modulo, da cui il portale legge preventivo, "
                  "versione, P/N, descrizione, Esp. e cliente."),
            ("passi", [
                "Apri la scheda «VRF» della commessa.",
                "Per ognuno dei 9 rischi (R1-R9) apri «Checklist» se ti serve e scegli la Probabilità P: 1 Bassa, 2 Media, 3 Alta, oppure N/A se il rischio non riguarda la fornitura.",
                "Guarda il Totale Rischio in fondo alla tabella: si aggiorna mentre scegli.",
                "Scrivi le azioni correttive (fino a 4) e nome e data di IN1 e EM.",
                "Premi «Conferma e genera xlsx»: nasce il file del modulo e il VRF risulta a posto.",
            ]),
            ("img", (_IMG + "vrf_scheda.jpg", "La scheda VRF: probabilità, gravità, Totale Rischio, azioni e firme")),
            ("ul", [
                "La Gravità D è fissata dal modulo: 3 per R1, R2, R3, R8 e R9; 2 per R4, R5, R6 e R7.",
                "Il rischio R = P × D è verde da 1 a 3, giallo a 4, rosso da 6 a 9.",
                "Il Totale Rischio (TR) è la somma delle R, al massimo 69: Basso fino a 35, Medio tra 35 e 50, Alto da 50 in su. Con TR Alto serve il coinvolgimento del CEO: il portale lo segnala a video.",
                "«Salva bozza» conserva i valori. «Prosegui e ricordami VRF» salva e torna al Piano lasciando il VRF da fare.",
                "«Conferma e genera xlsx» vuole la Probabilità di tutti i 9 rischi: se ne manca una, il messaggio dice quali e la bozza resta salvata.",
                "Una bozza salvata si vede nel Piano, con Totale Rischio e rischi mancanti: «Riprendi la scheda VRF» la riapre.",
            ]),
            ("p", "La pagina «Carica file esistente» serve anche a scaricare il documento, a sostituirlo («Sostituisci documento VRF»), a rimandare («Carica in seguito») o a segnare «Non richiesto per questo kickoff». Il file caricato viene mostrato in anteprima prima di confermare."),
            ("img", (_IMG + "vrf_carica.jpg", "Caricare il file Excel del modulo, oppure segnarlo come non richiesto")),
        ],
    },
    {
        "id": "blocco-vrf",
        "titolo": "Avviso e blocco per VRF mancante",
        "blocchi": [
            ("p", "Finché il VRF non è a posto, il portale conta i giorni dalla creazione della commessa."),
            ("ul", [
                "Dopo 7 giorni compare l'avviso nel Piano e sul portfolio.",
                "Dopo 30 giorni il kickoff è bloccato: non si creano né si modificano attività, nemmeno dalle scorciatoie degli incontri.",
                "La scheda VRF resta compilabile anche a kickoff bloccato: è proprio quello che lo sblocca.",
                "Se il VRF non serve, «Non richiesto per questo kickoff» toglie avviso e blocco.",
            ]),
            ("nota", "7 e 30 giorni sono i valori predefiniti: chi gestisce il modulo può cambiarli in Impostazioni › Configurazione."),
        ],
    },
    {
        "id": "piano",
        "titolo": "Il Piano e il Gantt",
        "blocchi": [
            ("p", "La scheda «Piano» è il posto dove si scrive e si aggiorna il lavoro della commessa."),
            ("passi", [
                "Nella riga sopra il Gantt scrivi il titolo dell'attività.",
                "Scegli il responsabile (prima il team della commessa, poi gli altri), controlla «Inizio» e indica «Fine».",
                "Premi «Aggiungi». La barra compare nel Gantt e sei pronto per la riga dopo, con lo stesso responsabile.",
            ]),
            ("img", (_IMG + "piano.jpg", "Il Piano: numeri, riga rapida e Gantt")),
            ("p", "L'inizio proposto è il giorno dopo l'ultima fine già in piano. Sul Gantt:"),
            ("ul", [
                "Trascina il centro di una barra per spostare inizio e fine insieme.",
                "Trascina un bordo per allungare o accorciare.",
                "Clicca una riga (in qualsiasi punto) per aprire «Modifica rapida»: date, stato e avanzamento. «Responsabile e dettagli» apre il form completo.",
                "«Sposta anche le successive» acceso: spostando un'attività si spostano anche quelle che dipendono da lei.",
                "Una sola barra sopra il Gantt: «Finestra» cambia il periodo mostrato, «Zoom» la larghezza dei giorni.",
                "Sotto il nome di ogni attività: responsabile («da assegnare» in rosso se manca), date, giorni di assenza del responsabile nel periodo e, con la baseline, lo scostamento della data fine.",
                "Riga «Incontri» sotto i giorni: un cerchio viola per ogni incontro della commessa (pieno se pianificato, vuoto se svolto) e una linea tratteggiata che attraversa il piano; cliccando si apre l'incontro. Gli incontri annullati non compaiono.",
                "Azioni, problemi, programmi CAM/CMM e FAI aperti collegati a un'attività ancora aperta compaiono come etichetta sotto il nome di quell'attività (rossa se scaduta).",
                "Quelli non collegati, o collegati a un'attività già chiusa, stanno in fondo in «Scadenze da incontri, programmi e FAI», una riga ciascuno con un rombo sulla data: azzurro per le azioni, arancio per i problemi, verde per programmi e FAI, rosso se scaduti. Il pulsante «N scadenze … ↓» nella barra porta lì.",
                "Il periodo mostrato si allarga da solo per comprendere incontri e scadenze.",
            ]),
            ("def", [
                ("Dipendenze tra attività", "pannello richiudibile sotto il Gantt: scegli predecessore e successore per numero (WBS), il tipo e l'eventuale ritardo «Lag (gg)». Tipi: Fine → Inizio (FS), Inizio → Inizio (SS), Fine → Fine (FF), Inizio → Fine (SF)."),
                ("Fissa baseline", "salva le date di oggi come riferimento. Da quel momento sotto ogni riga compare di quanti giorni si è spostata la data fine (+N gg in rosso se in ritardo)."),
                ("Commenti kickoff", "note di coordinamento della commessa, con notifica a una persona se serve."),
            ]),
            ("p", "I riquadri in alto contano Attività, Avanzamento, Scadute, In 7 giorni, Senza responsabile e Da controllare (conflitti con assenze e date non valide). Con un piano vuoto non compaiono."),
        ],
    },
    {
        "id": "attivita",
        "titolo": "Le attività",
        "blocchi": [
            ("p", "Un'attività si crea in quattro modi. Scegli il più corto che basta."),
            ("def", [
                ("Riga del Piano", "titolo, responsabile, Inizio, Fine. Per scrivere un piano intero."),
                ("«Attività di questo incontro»", "nel dettaglio e nell'esito dell'incontro: Invio salva senza ricaricare la pagina."),
                ("Conduci incontro", "«Cattura rapida» con tipo Attività, o «+ Nuova attività» sul punto, che la collega al punto."),
                ("Form completo", "«+ Attività completa» nel Piano, «+ Nuova attività» in Panoramica. A sinistra «Cosa va fatto», Responsabile, Priorità, Stato, Inizio → Fine (con i giorni calcolati), «Note per il responsabile» e Tipo; a destra il kickoff, le «Persone in copia» da spuntare (con ricerca) e il pulsante di salvataggio. Etichette, prossimo passo, impegni sovrapposti, attrezzatura, Outlook e promemoria stanno in «Altre opzioni». Fuori da una commessa il form chiede prima «In quale kickoff?»."),
            ]),
            ("img", (_IMG + "attivita_form.jpg", "Il form completo: attrezzatura, Outlook e promemoria stanno in «Altre opzioni»")),
            ("ul", [
                "Gli stati sono Da fare, In corso, Completata e Annullata; le priorità Bassa, Media e Alta.",
                "Data inizio e data fine possono coincidere: un'attività di una sola giornata è ammessa. "
                "La data fine non può precedere la data inizio.",
                "Chi riceve un'attività, alla creazione o quando cambia il responsabile, riceve una notifica nel portale e una mail "
                "(all'indirizzo di notifica dell'anagrafica) con il collegamento a «Le mie azioni». "
                "Chi si assegna un'attività da solo non viene avvisato.",
                "Il responsabile gestisce le sue attività da «Le mie azioni»: «Inizia» la porta In corso, «Fatta» la chiude, «Riapri» la riporta Da fare.",
                "Ogni lunedì la mail «Scadenze KICK-OFF» elenca anche le attività scadute e quelle che scadono nei 7 giorni.",
                "Se la persona ha altri impegni nello stesso periodo, il form completo lo segnala e «Se l'operatore ha altri impegni nello stesso periodo» decide cosa fare della priorità.",
                "Portando un'attività a «Completata» l'avanzamento passa al 100%.",
                "Un'attività completata chiude da sola le azioni e i problemi d'incontro collegati a lei; "
                "un'azione o un problema collegati a un'attività già completata nascono chiusi.",
                "Su una commessa bloccata per VRF mancante non si creano attività, nemmeno dalle scorciatoie degli incontri.",
            ]),
        ],
    },
    {
        "id": "percorso-kickoff",
        "titolo": "Percorso del kickoff: le attività base",
        "blocchi": [
            ("p", "In «Panoramica» e nel dettaglio dell'incontro il riquadro «Percorso del kickoff» elenca le attività che ogni commessa deve avere a posto: Arrivo materiali, Programma CAM, Programma CMM, Macchina, Terzista, Processi speciali e FAI. In alto il conteggio «N/7 a posto»: una tappa è a posto quando la sua attività è completata o quando è segnata «Non serve»."),
            ("passi", [
                "Premi «Assegna» sulla tappa.",
                "Per la Macchina scegli la macchina (CNC e macchine di lavoro), per il Terzista il fornitore, per i Processi speciali il processo: l'elenco propone i fornitori attivi e i processi qualificati, ma puoi scrivere un nome.",
                "Scegli il responsabile, «Inizio» (già su oggi) ed «Entro il» dal calendario, poi «Salva» o Invio. «Entro il» non può venire prima dell'inizio.",
                "Mentre compili, sotto la riga compare subito se il responsabile è assente nel periodo e, per la macchina, quanti abilitati sono disponibili e quali manutenzioni o impegni ha.",
            ]),
            ("p", "Ogni tappa assegnata è un'attività normale: chi la riceve ha la notifica e la mail, la trova in «Le mie azioni» e nel Gantt e la porta avanti con «Inizia» e «Fatta». Se la assegni dentro un incontro compare anche tra le «Attività di questo incontro». Programma CAM, Programma CMM e FAI creano anche la loro riga in «Codici, cartelle e schede FAI», dove si scrivono codice e percorso."),
            ("p", "Per la Macchina il riquadro controlla il periodo dall'inizio alla scadenza dell'attività (senza scadenza, due settimane): quanti abilitati operativi ha la macchina nella skill matrix e quanti sono disponibili, chi è assente (solo il periodo, mai il motivo; i nomi li vede solo chi può leggere la skill matrix), e gli impegni dell'asset: ordini di lavoro aperti, verifiche periodiche, ticket, altre attività sulla stessa macchina, carichi macchina."),
            ("def", [
                ("Da assegnare", "nessuna attività per la tappa."),
                ("Da fare / In corso", "attività aperta."),
                ("In ritardo", "un'attività aperta ha la scadenza passata."),
                ("Fatto", "tutte le attività della tappa completate."),
                ("Non serve", "deciso da chi gestisce la commessa; «Serve» torna indietro. Non si può dire «Non serve» a una tappa che ha già un'attività: prima va annullata."),
            ]),
            ("p", "Con una data «Entro il» l'attività entra anche nello scadenzario personale del responsabile. Il promemoria nel portale qualche giorno prima della scadenza e l'evento nel calendario Outlook del responsabile (spunta «Anche in Outlook») sono flussi di automazione spenti finché un amministratore non li accende: la spunta compare solo con il flusso acceso."),
            ("p", "Macchina, Terzista e Processi speciali ammettono più attività («+ Altra»), le altre tappe una sola. Le tappe sono tipi attività: in Impostazioni → Tipi attività il campo «Tappa del kickoff» dice quale tipo rappresenta ogni tappa; un tipo disattivato toglie la tappa dal percorso."),
        ],
    },
    {
        "id": "programmi-fai",
        "titolo": "Programmi CAM, CMM e FAI",
        "blocchi": [
            ("p", "La scheda «Programmi e FAI» della commessa raccoglie i codici e i percorsi di rete, con il responsabile di ognuno. "
                  "Non è obbligatoria e si può usare solo per quello che serve. Le stesse righe si vedono e si aggiungono anche nel dettaglio dell'incontro e in «Registra esito»: non vanno inserite due volte."),
            ("p", "Un'attività di tipo «Programmazione CAM» richiede il programma CAM, «Programmazione CMM» il programma CMM, «Esecuzione FAI» la scheda FAI: la scheda dell'attività chiede subito codice e cartella, e la stessa riga compare in «Programmi e FAI» con il responsabile e la data dell'attività. "
                  "Vale anche al contrario: una riga di «Programmi e FAI» con un responsabile, aggiunta dalla commessa o dentro l'incontro, crea da sola l'attività del tipo che la richiede (per esempio «Programmazione CAM»), con lo stesso responsabile e la stessa data. Chi la riceve ha la notifica e la mail, la trova in «Le mie azioni», nel Gantt e tra le «Attività di questo incontro»; la porta avanti con «Inizia» e «Fatta» dalla scheda dell'attività, dove scrive anche codice e cartella. Una riga senza responsabile resta una semplice riga finché non la assegni. "
                  "Se l'attività si chiude senza programma, si può chiudere, ma la riga resta «Da inserire» nelle attività del responsabile. Se il programma viene cancellato, torna «Da inserire». Eliminare il tipo o togliere «Richiede» stacca le righe: quelle vuote spariscono, i programmi già inseriti e le righe assegnate in riunione restano. Una scheda FAI chiesta da un'attività ha lo stesso responsabile dell'attività. La voce di menu «Programmi» mostra tutti i programmi CAM e CMM, con filtri, ricerca ed esportazione CSV."),
            ("passi", [
                "Scegli il tipo: «Programma CAM», «Programma CMM» o «FAI».",
                "Scrivi il codice e, se serve, il percorso, per esempio \\\\server\\cartella\\file.",
                "Scegli il responsabile. Per CAM e CMM il portale propone il Programmatore, se la commessa ne ha uno solo.",
                "Premi Invio. Tipo e responsabile restano, così scrivi subito il codice successivo.",
            ]),
            ("img", (_IMG + "programmi_fai.jpg", "La scheda Programmi e FAI con la riga di inserimento")),
            ("ul", [
                "Basta uno tra codice, percorso e responsabile: in riunione puoi assegnare «Programma CAM» a una persona, e il codice lo scrive poi lei con «Modifica».",
                "Il responsabile riceve la notifica e trova la voce in «Le mie azioni» e in «Le mie attività» del portale. Con «Fatto» la chiude.",
                "Le lettere di unità come Y:\\ non si accettano, perché cambiano da PC a PC: serve il percorso di rete.",
                "Cliccando un percorso di rete il portale lo copia. I browser non aprono direttamente le cartelle da una pagina web: premi Win+E, poi Ctrl+L, Ctrl+V e Invio.",
                "«Modifica» è per chi gestisce la commessa e per il responsabile della riga; «Elimina» solo per chi gestisce la commessa. Il responsabile non può passare la riga a un altro.",
            ]),
        ],
    },
    {
        "id": "report-fai",
        "titolo": "Report FAI",
        "blocchi": [
            ("p", "«Report FAI» del menu riassume il registro: articoli per situazione, per cliente, FAI per stato e per anno di invio, con i giorni medi fra invio e chiusura. Il filtro «Cliente» vale per tutta la pagina e per i file."),
            ("def", [
                ("Da ripetere e in scadenza", "articoli da ripetere o con la ripetizione entro 6 mesi, i più urgenti prima. Excel e PDF."),
                ("Controllo trimestrale", "articoli oltre la soglia dall'ultima spedizione, da segnalare a IN1 e MSM (MT CN 15 §5.10). Excel e PDF; il Centro report può mandarlo in automatico."),
                ("Situazione degli articoli", "un articolo per riga, con il FAI più recente. Excel e PDF."),
                ("Riepilogo per cliente", "articoli per cliente e situazione. Excel e PDF."),
                ("Tutti i FAI", "le colonne del file Situazione FAI-ISIR. Solo Excel: nel PDF non starebbero."),
            ]),
        ],
    },
    {
        "id": "registro-fai",
        "titolo": "FAI e Registro FAI",
        "blocchi": [
            ("p", "In «Programmi e FAI» la parte FAI dice cosa prevede la procedura per il P/N della commessa. Il «Registro FAI» del menu tiene una riga per articolo con il FAI più recente: in alto quello che richiede una decisione."),
            ("p", "Tutti i FAI si gestiscono qui: la scheda «Tutti i FAI» del registro ha una riga per FAI, con filtri per cliente e stato, ricerca su P/N, piano, OP, OdA e FAI CN, ed esportazione CSV con le colonne del vecchio file «Situazione FAI-ISIR». "
                  "I FAI storici sono importati da quel file: nella scheda, in fondo, restano i dati originali. Un FAI storico si può salvare anche senza perché e senza tipo, che il file non indicava. Per la scadenza conta l'ultima produzione; finché non è indicata vale la chiusura del FAI e la nota lo dice."),
            ("passi", [
                "In «Programmi e FAI» premi «Apri un FAI». Se in riunione hai già assegnato una riga FAI, premi «Completa»: non si crea un doppione.",
                "Scegli «Perché serve»: il portale propone FAI completo o Delta FAI.",
                "È una proposta, non un obbligo: se per quella commessa il FAI non serve, chi gestisce il kickoff preme «Non richiesto per questo kickoff». Il portale registra chi l'ha deciso e quando; «Annulla» torna indietro.",
                "Indica il piano e, se c'è, il numero. Per i piani con numerazione automatica lascialo vuoto.",
                "Nel campo OP scrivi almeno due caratteri dell'OP o del P/N: il portale propone gli OP dell'elenco unico, lo stesso di Gestione anomalie. Sotto compaiono P/N, capocommessa, CAR, stato e le anomalie dell'OP, con il link per aprirle; se il P/N dell'OP è diverso da quello del FAI lo segnala. Un OP che non è nell'elenco si salva lo stesso; per crearlo, «+ Nuovo OP» accanto al campo apre un pannello a lato col P/N del FAI e mette l'OP creato nel campo (permesso «Ordini di produzione - Nuovo OP»).",
                "Aggiorna lo «Stato» man mano e inserisci le date dell'articolo: servono a calcolare la scadenza.",
            ]),
            ("ul", [
                "Se scegli un Delta FAI dove è previsto il completo il portale non ti ferma: chiede di scrivere il motivo.",
                "«Da ripetere»: superati i mesi dalla fine dell'ultima produzione (24 in partenza), oppure la data chiesta dal cliente.",
                "«Oltre 18 mesi»: ultima spedizione più vecchia della soglia. È l'elenco del controllo trimestrale da segnalare a IN1 e MSM; «Esporta CSV» lo scarica.",
                "Il responsabile trova il FAI in «Le mie attività». Con «Fatto» il FAI passa al primo stato «Eseguito, in attesa di esito».",
                "Vedi i FAI delle commesse a cui hai accesso. L'intero registro, compresi gli articoli senza commessa, è per chi gestisce il modulo.",
                "Motivi, piani, stati e mesi si cambiano in Impostazioni, scheda «FAI».",
            ]),
        ],
    },
    {
        "id": "scheda-attivita",
        "titolo": "La scheda di un'attività",
        "blocchi": [
            ("p", "Cliccando un'attività si apre la sua scheda: a sinistra il lavoro da fare, a destra responsabile, date, kickoff e allegati."),
            ("img", (_IMG + "attivita_scheda.jpg", "La scheda di un'attività")),
            ("def", [
                ("Stato", "i pulsanti in alto cambiano lo stato con un clic. Il responsabile senza permesso di modifica vede «Inizia», «Fatta» e «Riapri». Accanto: priorità, «In ritardo dal …» e la barra dell'avanzamento."),
                ("Completamento", "quando l'attività passa a Completata, chi l'ha creata riceve una notifica nel portale (non se la chiude da sé)."),
                ("Inizio e Fine richiesta", "si correggono in «Dettagli»: cambiando la data compare «Salva»."),
                ("Sotto-attività", "con responsabile, data e ordine, per spezzare il lavoro: si aggiungono con «+ Aggiungi sotto-attività»."),
                ("Commenti", "note sull'attività; «Avvisa» manda la notifica a una persona. Sotto, «Storico» elenca tutte le modifiche."),
                ("Allegati", "file dell'attività e del kickoff collegato; «+ Carica un file» e «Dove» scelgono su quale dei due salvarlo."),
                ("Eventi", "la storia delle modifiche: stato, date, assegnatari, subtask, allegati."),
                ("Modifica attivita", "apre il form completo."),
            ]),
        ],
    },
    {
        "id": "convocazione",
        "titolo": "Pianificare e convocare un incontro",
        "blocchi": [
            ("passi", [
                "Scheda «Incontri» della commessa, «+ Nuovo incontro». Per l'incontro 1 la convocazione è già aperta dopo la creazione.",
                "Informazioni base: «Data» è obbligatoria; poi titolo, ora, «Durata», «Sala» e, se serve, «Altro luogo o link» (sede del cliente, link Teams). «Durata» è quanto resta prenotata la sala e quanto dura l'evento Outlook; su «Dall'ordine del giorno» vale la somma dei punti, un'ora se non ce ne sono.",
                "Sotto, «Disponibilità del giorno» mostra le sale dalle 8 alle 19: in arancione gli incontri del portale, in rosso gli impegni Outlook della sala, in grigio i partecipanti occupati, con il bordo blu il tuo incontro. Clicca un orario libero su una sala per sceglierla: ora e sala si compilano da sole e il messaggio sotto dice se è libera.",
                "Partecipanti: cerca gli «Utenti del portale» e aggiungi le «Email aggiuntive (esterni)», una per riga. «Destinatari in copia» vale per convocazione e minuta.",
                "Ordine del giorno: aggiungi i punti, con durata e attività collegata se serve. Puoi usare un modello o «Duplica ODG dell'incontro precedente».",
                "«Prenota la sala e invita in Outlook» (già acceso se Outlook è configurato): al salvataggio l'incontro va nel tuo calendario, la sala riceve la richiesta di prenotazione e i partecipanti l'invito da accettare.",
                "Salva. Se serve anche la mail del portale con l'ordine del giorno, dal dettaglio dell'incontro premi «Invia convocazione».",
            ]),
            ("p", "Nel dettaglio dell'incontro, accanto al luogo, c'è lo stato della prenotazione: «Richiesta inviata alla sala», «Sala confermata», «Sala in forse», «Sala rifiutata: è già occupata». «Verifica» lo chiede di nuovo a Outlook. Una sala senza casella Microsoft 365 vale solo nel portale: si vede nella disponibilità ma non si prenota in Outlook. Se un'altra riunione del portale occupa la stessa sala nello stesso orario, al salvataggio compare un avviso."),
            ("img", (_IMG + "convocazione.jpg", "La convocazione: informazioni, partecipanti e ordine del giorno")),
            ("ul", [
                "L'ordine del giorno parte già con i problemi e le azioni ancora aperti, con i punti non trattati nell'incontro precedente e con le tappe del Percorso da assegnare, in corso o in ritardo.",
                "«Pianifica prossimo incontro», dal dettaglio di un incontro svolto, riprende convocati, persone in copia, luogo, "
                "ora e impostazioni Outlook del precedente, con la data una settimana dopo.",
                "Salvare l'incontro non invia email. La convocazione parte con il pulsante «Invia convocazione» del dettaglio, "
                "oppure spuntando «Invia la convocazione ai partecipanti dopo il salvataggio» in fondo al form.",
                "Il dettaglio dice se la convocazione è stata inviata e quando. Se dopo l'invio cambiano data, ora, luogo, "
                "convocati o ordine del giorno compare «Convocazione da reinviare»; il pulsante diventa "
                "«Invia aggiornamento convocazione» e la mail esce come «Aggiornamento convocazione». Sotto l'avviso "
                "c'è l'elenco di cosa è cambiato (per esempio «Data: 12-11-2026 → 14-11-2026», «Convocati aggiunti: …», "
                "«Punti dell'ordine del giorno tolti: …»); per le convocazioni inviate prima del 02/11/2026 l'avviso resta generico.",
                "Durata dell'evento (Outlook e invito .ics): la somma delle durate dei punti all'ordine del giorno; "
                "se nessun punto ha una durata, un'ora.",
                "Se l'incontro viene spostato a un'altra data, il promemoria del giorno prima riparte sulla data nuova.",
                "L'evento Outlook è un canale separato dalla mail: si attiva con «Calendario Outlook» nel form.",
                "L'invito .ics allegato alla mail usa l'ora italiana e l'organizzatore dell'evento Outlook (campo «Email organizzatore», "
                "altrimenti chi ha creato l'incontro); quello di annullamento elenca anche i convocati, così il calendario toglie l'evento.",
                "Ogni convocato può proporre un punto dal dettaglio di un incontro non ancora svolto: Project manager e capocommessa ricevono la notifica e lo accettano o lo rifiutano.",
                "«Prepara con l'AI», in «Dalle commesse simili», cerca le commesse dello stesso cliente o P/N e propone punti da aggiungere: li scegli tu.",
            ]),
        ],
    },
    {
        "id": "incontro",
        "titolo": "Il dettaglio dell'incontro",
        "blocchi": [
            ("p", "È la pagina di riferimento di un incontro: da qui parte tutto il resto."),
            ("img", (_IMG + "incontro.jpg", "Il dettaglio di un incontro pianificato")),
            ("def", [
                ("In alto", "«Conduci incontro», «Registra esito», «Modifica incontro» (data, ora, sala, partecipanti, ordine del giorno), «Annulla incontro», «Elimina»."),
                ("Attività di questo incontro", "scrivi il titolo e premi Invio: la pagina non si ricarica, il responsabile resta e si riparte dal titolo. Sotto, l'elenco delle attività nate dall'incontro. «Più opzioni» apre sotto la riga tipo, priorità e attrezzatura, oppure «Aggiorna un'attività già creata» per correggerne date e responsabile senza crearne un'altra."),
                ("Documenti", "«Invia convocazione», «Invia minuta», «Scarica minuta PDF», «Approva e chiudi minuta»."),
                ("Partecipanti", "convocati, email esterne e, a incontro svolto, presenti e assenti."),
                ("Ordine del giorno e verbale", "i punti, con la spunta di trattato e le note."),
                ("Problemi, Decisioni, Azioni", "quello che riguarda l'incontro, con «Segna risolto» e «Segna fatta»."),
            ]),
            ("img", (_IMG + "incontro_opzioni.jpg", "«Più opzioni» aperto sotto la riga: tipo, priorità, attrezzatura")),
        ],
    },
    {
        "id": "annullamento",
        "titolo": "Annullare o eliminare un incontro",
        "blocchi": [
            ("ul", [
                "«Annulla incontro» (solo per incontri pianificati) chiede il motivo, toglie l'evento dal calendario Outlook "
                "e, se la casella «Avvisa i convocati via email» resta spuntata, manda ai convocati l'avviso di annullamento con il motivo.",
                "Un incontro annullato si riprogramma da «Modifica incontro», riportando lo stato a «Pianificato»: "
                "la convocazione torna «da inviare», perché i convocati hanno ricevuto l'annullamento.",
                "«Elimina» compare solo per gli incontri mai svolti e senza decisioni. Un incontro svolto non si elimina: "
                "con lui sparirebbero verbale e decisioni.",
            ]),
        ],
    },
    {
        "id": "conduzione",
        "titolo": "Condurre l'incontro",
        "blocchi": [
            ("p", "«Conduci incontro» apre la schermata da usare durante la riunione, un punto alla volta. In alto il tempo pianificato, il trascorso e i punti trattati."),
            ("passi", [
                "Appello: spunta chi è presente. Il dato si salva subito e vale anche per l'esito e la minuta.",
                "Su ogni punto scrivi la nota: si salva da sola.",
                "Serve del lavoro? «+ Nuova attività» sul punto (parte dal titolo del punto, poi responsabile, inizio e fine; «Crea e collega»), oppure scegli un'attività già esistente in «Attività collegata».",
                "I punti che vengono dal Percorso del kickoff («Arrivo materiali: da assegnare», «Macchina: in ritardo»...) hanno «Assegna la tappa»: scegli la macchina, il fornitore o il processo se serve, poi responsabile e date. Nasce l'attività della tappa, collegata al punto, con notifica e mail a chi la riceve.",
                "Premi «Segna trattato» e, se vuoi, scrivi il «Tempo effettivo».",
                "Quello che emerge mentre si parla va in «Cattura rapida», sempre visibile in fondo allo schermo: scegli Attività, Azione, Decisione o Problema, scrivi e premi Invio.",
                "A fine riunione premi «Termina incontro e registra l'esito».",
            ]),
            ("img", (_IMG + "conduci.jpg", "Conduci incontro: i punti e, in fondo, la Cattura rapida")),
            ("ul", [
                "Ogni modifica si salva da sola e solo sul punto toccato.",
                "«Aggiungi un punto» inserisce un argomento nato in riunione: entra nell'ordine del giorno, quindi conta per spunte, tempi e minuta.",
                "Il responsabile di un'attività, di un'azione o di un problema catturati riceve subito una notifica.",
                "Le attività entrano nel Piano; azioni e problemi rientrano da soli nell'ordine del giorno del prossimo incontro; le decisioni finiscono nel registro di commessa.",
            ]),
        ],
    },
    {
        "id": "esito",
        "titolo": "Registrare l'esito e la minuta",
        "blocchi": [
            ("passi", [
                "Dal dettaglio premi «Registra esito».",
                "Presenze: togli la spunta a chi non si è presentato; aggiungi chi c'era e non era convocato.",
                "Ordine del giorno e verbale: spunta i punti trattati e scrivi cosa è emerso. Spunte e note si salvano subito.",
                "Problemi: spunta «risolto» su quelli chiusi e aggiungi i nuovi con «Aggiungi problema».",
                "Decisioni: «Aggiungi decisione», con motivazione, chi ha deciso e impatto.",
                "Azioni: spunta quelle completate e aggiungi le nuove con «Aggiungi azione»: chi fa cosa entro quando.",
                "Premi «Registra esito» in fondo: l'incontro passa a «Svolto».",
                "Nel dettaglio premi «Invia minuta», controlla e poi «Approva e chiudi minuta».",
            ]),
            ("img", (_IMG + "esito.jpg", "La pagina esito")),
            ("ul", [
                "«Attività di questo incontro» c'è anche qui: Invio salva l'attività e non registra l'esito.",
                "Problemi e azioni hanno responsabile e scadenza; finché restano aperti tornano nell'ordine del giorno degli incontri successivi.",
                "«Note generali» è solo per ciò che non riguarda un punto in particolare.",
                "Le decisioni non si riscrivono: se una è sbagliata, se ne registra una nuova che la supera.",
                "I vecchi campi di testo libero (ordine del giorno testuale, problemi aperti, next steps) restano consultabili "
                "negli incontri storici ma non si compilano più.",
                "«Approva e chiudi minuta» la segna come approvata e mette l'esito in sola lettura. Dopo l'approvazione solo il capocommessa della commessa (o l'amministratore del modulo) vede «Riapri minuta», che chiede un motivo a registro, e «Correggi ordine del giorno».",
                "Dopo «Invia minuta» il dettaglio dice quando è partita. Se poi cambiano verbale, ordine del giorno, decisioni o azioni compare «La minuta è cambiata dopo l'invio» e il pulsante diventa «Invia aggiornamento minuta»: la mail esce con oggetto «Aggiornamento minuta».",
                "Salvare l'esito due volte non raddoppia le azioni: un'azione aperta con lo stesso titolo e lo stesso responsabile nello stesso incontro non viene ricreata.",
                "«Invia minuta» la manda ai presenti, con gli assenti in copia e il PDF allegato.",
            ]),
            ("img", (_IMG + "incontro_svolto.jpg", "Un incontro svolto: minuta, problemi, decisioni e azioni")),
        ],
    },
    {
        "id": "azioni-problemi",
        "titolo": "Azioni, problemi e attività: come si legano",
        "blocchi": [
            ("p", "Un'azione o un problema restano voci dell'incontro; quando servono date e pianificazione vi si collega un'attività."),
            ("ul", [
                "Il responsabile di un'azione o di un problema li chiude da sé, dal dettaglio incontro o da «Le mie azioni», "
                "senza passare da chi gestisce la commessa.",
                "Se l'attività collegata viene completata, l'azione o il problema si chiudono da soli.",
                "Il lunedì il promemoria KICK-OFF elenca le azioni e i problemi scaduti e quelli in scadenza nei 7 giorni.",
            ]),
        ],
    },
    {
        "id": "mie-azioni",
        "titolo": "Le mie azioni",
        "blocchi": [
            ("p", "La pagina «Le mie azioni» raccoglie tutto quello di cui sei responsabile, su tutte le commesse che puoi vedere: "
                  "attività del piano, azioni e problemi degli incontri, programmi e FAI. È il punto dove chi riceve un'attività la gestisce; "
                  "ci porta il pulsante della mail di assegnazione. Nella dashboard la colonna «Le mie azioni» mostra le prime, scadute in testa."),
            ("ul", [
                "Filtri: Aperte, Chiuse, Tutte; tipo (attività del piano, azioni, problemi, programmi e FAI); scadenza (Scadute, In scadenza entro 7 giorni, Senza scadenza); "
                "commessa; ricerca nel testo.",
                "Per le attività: «Inizia» la porta In corso, «Fatta» la chiude con avanzamento al 100%, «Riapri» la riporta Da fare. Il titolo apre la scheda, «Gantt» il piano della commessa.",
                "«Fatta» o «Risolto» chiudono le azioni e i problemi, «Riapri» li riporta aperti.",
            ]),
            ("img", (_IMG + "mie_azioni.jpg", "Le mie azioni")),
        ],
    },
    {
        "id": "registro-azioni",
        "titolo": "Registro azioni della commessa",
        "blocchi": [
            ("p", "Dalla scheda di commessa, «Azioni» mostra in un solo elenco problemi, azioni d'incontro, attività e sotto-attività."),
            ("ul", [
                "«Solo aperte» o «Includi chiuse».",
                "Filtri per tipo, responsabile («Non assegnate» per quelle senza nessuno), scadenza e testo. "
                "I riquadri in alto contano sempre tutto il registro, la tabella mostra il filtrato.",
            ]),
            ("img", (_IMG + "registro_azioni.jpg", "Il registro azioni di una commessa")),
        ],
    },
    {
        "id": "decisioni",
        "titolo": "Registro decisioni",
        "blocchi": [
            ("p", "Raccoglie tutte le decisioni della commessa, con motivazione, chi ha deciso e impatto (Basso, Medio, Alto). Si apre dal link «Registro di commessa» nel dettaglio di un incontro."),
            ("p", "Le decisioni si registrano nella pagina esito o in Cattura rapida, finiscono nella minuta e non si riscrivono: una decisione si supera con una nuova."),
        ],
    },
    {
        "id": "elenco-incontri",
        "titolo": "Elenco e calendario incontri",
        "blocchi": [
            ("p", "La voce «Calendario» mostra gli incontri del mese; l'elenco raccoglie tutti gli incontri a cui hai accesso."),
            ("ul", [
                "«I miei» comprende gli incontri in cui sei convocato, in copia, presente, che hai creato o della cui commessa fai parte del team.",
                "Filtri: stato, periodo (Prossimi 7 giorni, Da oggi in poi, Passati), esito e minuta "
                "(Esito da registrare, Minuta da approvare, Minuta approvata), commessa e ricerca nel verbale.",
            ]),
            ("img", (_IMG + "elenco_incontri.jpg", "L'elenco degli incontri")),
        ],
    },
    {
        "id": "da-gestire",
        "titolo": "Da gestire",
        "blocchi": [
            ("p", "«Da gestire» riunisce quello che richiede un intervento. In alto scegli «Portfolio» (tutte le commesse) o «Le mie». Ogni riga porta dove si risolve."),
            ("def", [
                ("Azioni e problemi aperti", "quelli assegnati a te."),
                ("VRF da compilare", "commesse con il VRF non ancora a posto."),
                ("Commesse non pronte", "commesse con il semaforo di prontezza incompleto."),
                ("Attività critiche", "scadute, non assegnate, senza data o ferme."),
                ("Incontri da chiudere", "esito da registrare, minuta da approvare, problemi aperti."),
            ]),
            ("img", (_IMG + "da_gestire.jpg", "La pagina «Da gestire»")),
        ],
    },
    {
        "id": "copia",
        "titolo": "Copiare una commessa e importare da Excel",
        "blocchi": [
            ("def", [
                ("Copia VRF", "sulla card del portfolio: crea un nuovo kickoff con gli stessi dati, lo stesso team e il file VRF."),
                ("Copia senza P/N", "come sopra, ma svuota il P/N della commessa e del file VRF. Utile per un particolare simile."),
                ("Import Excel", "nel portfolio: «Scarica template .xlsx», compilalo e caricalo. L'anteprima mostra cosa verrà importato prima di confermare."),
            ]),
        ],
    },
    {
        "id": "promemoria",
        "titolo": "Promemoria automatici",
        "blocchi": [
            ("ul", [
                "I convocati ricevono il promemoria dell'incontro il giorno lavorativo precedente: il venerdì per un incontro del lunedì, "
                "prima di un festivo per il giorno dopo.",
                "Il lunedì arriva il riepilogo di azioni e problemi scaduti e in scadenza nella settimana.",
                "Più avvisi per la stessa persona nello stesso giorno arrivano in una sola email.",
            ]),
            ("nota", "Le notifiche nel portale rispettano le preferenze dell'utente e l'interruttore generale delle notifiche."),
        ],
    },
    {
        "id": "permessi",
        "titolo": "Chi può fare cosa",
        "blocchi": [
            ("p", "Vedi le commesse del tuo perimetro: quelle dove sei nel team o convocato a un incontro, più quelle che i tuoi permessi aprono."),
            ("def", [
                ("Chi gestisce la commessa", "chi l'ha creata, chi ha i permessi di amministrazione del modulo e i ruoli con «Modifica tutto»: modifica dati e team, VRF, incontri, minute e piano."),
                ("Chi ha un'attività", "con «Modifica solo i task assegnati» aggiorna le proprie attività e vede il resto."),
                ("Il responsabile di un'azione o di un problema", "li chiude da sé, anche senza gestire la commessa."),
                ("Un convocato", "vede l'incontro e può proporre un punto all'ordine del giorno."),
            ]),
            ("nota", "Se ti manca un pulsante che ti serve, chiedilo a chi gestisce il modulo: lo trova in Impostazioni › Accessi."),
        ],
    },
    {
        "id": "impostazioni",
        "titolo": "Impostazioni (per chi gestisce il modulo)",
        "blocchi": [
            ("def", [
                ("Configurazione", "email e preavviso delle notifiche di scadenza, «Giorni avviso» e «Giorni blocco» del VRF (9999 toglie il blocco), verifica disponibilità degli asset, destinatari in copia predefiniti."),
                ("Riepilogo", "il quadro del modulo."),
                ("Ruoli operativi", "catalogo dei ruoli e assegnazione delle persone: sono le liste del team. «Da anagrafica (Reparti)» legge i Caporeparto dai reparti; «Manuale» li assegna a mano."),
                ("Accessi", "per ogni ruolo e per la singola persona: Vede tutto, Modifica solo i task assegnati, Modifica tutto."),
                ("Promemoria", "i promemoria programmati delle attività: si eliminano, si rimandano o si inviano subito."),
                ("Tipi attivita", "le tipologie di attività e i campi extra del form, con il ruolo dedicato e «Richiede»: il programma CAM, il programma CMM o il FAI che l'attività deve produrre."),
                ("Modelli ODG", "punti ricorrenti da caricare nella convocazione. Un punto per riga; per la durata scrivi «Titolo | 15»."),
                ("FAI", "motivi per cui serve il FAI e tipo proposto, tipi di piano, stati e mesi delle scadenze. Una voce già usata non si elimina: si disattiva."),
                ("Record", "ricerca ed eliminazione di kickoff e attività: serve una motivazione e non si torna indietro."),
                ("Log attivita", "il registro delle operazioni del modulo."),
            ]),
            ("img", (_IMG + "impostazioni.jpg", "Le impostazioni del modulo")),
        ],
    },
    {
        "id": "problemi",
        "titolo": "Se qualcosa non va",
        "blocchi": [
            ("def", [
                ("Non vedo una commessa", "non sei nel team e non hai permessi su di lei: chiedi di essere aggiunto da «Modifica kickoff»."),
                ("Non riesco a creare attività: kickoff bloccato", "compila la scheda VRF o segnala «Non richiesto per questo kickoff»."),
                ("«Conferma e genera xlsx» non crea il file", "il messaggio elenca i rischi senza Probabilità: sceglila per tutti i 9, N/A se non si applica."),
                ("La persona non è nell'elenco del team", "le liste vengono dai ruoli operativi: chi gestisce il modulo la aggiunge in Impostazioni › Ruoli operativi."),
                ("Ho salvato l'incontro ma nessuno ha ricevuto niente", "salvare non invia email: premi «Invia convocazione» nel dettaglio."),
                ("Compare «La data fine non può precedere la data inizio»", "correggi anche l'Inizio: quello proposto è il giorno dopo l'ultima fine in piano."),
                ("«Elimina» non c'è su un incontro", "un incontro svolto o con decisioni non si elimina. Se non si terrà, usa «Annulla incontro»."),
                ("Non posso più modificare l'esito", "la minuta è approvata: la riapre il capocommessa con «Riapri minuta» e il motivo."),
            ]),
        ],
    },
]
