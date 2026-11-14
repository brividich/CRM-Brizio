GUIDA = {
    "slug": "anomalie",
    "titolo": "Gestione anomalie",
    "area": "Produzione e operations",
    "sintesi": "Controllo degli ordini di produzione per blocchi di seriali, anomalie con foto e decisione del capocommessa.",
    "parole": "anomalia anomalie seriale seriali op ordine produzione capocommessa collaudo",
    "url": "gestione_anomalie_page",
    "prefissi": ("/gestione-anomalie", "/api/anomalie/"),
    "dettaglio": [("Guida completa Gestione anomalie", "/gestione-anomalie", "?guida=1")],
    "uso": [
        {
            "id": "flusso",
            "titolo": "Il percorso in breve",
            "blocchi": [
                ("passi", [
                    "Apri Gestione anomalie e cerca l'ordine di produzione (OP).",
                    "Crea un blocco di seriali da controllare (singoli, elenco o intervallo).",
                    "Per ogni problema trovato aggiungi un'anomalia: descrizione e foto (trascina il file o incollalo con Ctrl+V).",
                    "Indica se l'anomalia riguarda tutti i seriali del blocco o solo alcuni.",
                    "All'avvio del controllo vedi a chi andrà la mail; con «+ Aggiungi altro capocommessa» o «+ Aggiungi "
                    "persona» metti in copia altri colleghi presenti in anagrafica; nello stesso riquadro compaiono le "
                    "liste di Configurazione → Notifiche che ricevono il riepilogo, e il riquadro torna nel riepilogo "
                    "finale.",
                    "Invia: il capocommessa riceve la mail e decide dal portale o dal collegamento nella mail.",
                    "Nella mail del controllo e nel riepilogo «Apri nel portale» apre l'OP in Gestione anomalie: dai PC "
                    "aziendali entri in automatico con l'utente Windows, altrove si apre il login e poi l'OP.",
                    "Nel portale e nella pagina della mail «Applica la stessa decisione anche a» copia la decisione sullo "
                    "stesso blocco, su tutte le anomalie aperte o su quelle scelte a mano (le già decise solo se "
                    "spuntate), con un riepilogo da confermare prima del salvataggio.",
                ]),
                ("p", "Stesse anomalie su un altro OP? In Gestione anomalie premi «Clona» nella scheda dell'OP, spunta "
                      "le anomalie da copiare e «Continua»: il nuovo OP arriva con P/N, capocommessa e CAR già scritti "
                      "(manca il numero) e i blocchi copiati si caricano uno alla volta, da controllare e salvare. Gli "
                      "allegati si copiano solo se lo scegli sull'anomalia."),
                ("p", "OP sbagliato? Nella pagina di inserimento clicca sul numero dell'OP o sul P/N nella barra in alto (hanno la matita ✎), cerca l'OP giusto per numero, P/N, capocommessa o CAR e premi «Passa a …». Il controllo continua sul nuovo OP: le anomalie già salvate passano con lui (solo se nessuna è stata ancora gestita dal capocommessa) e il blocco che stai scrivendo resta com'è. Quelle già comunicate arrivano al capocommessa del nuovo OP nel riepilogo delle modifiche. A controllo terminato si spostano le singole anomalie con «✂ Taglia»."),
                ("p", "Un'anomalia inserita per sbaglio la elimina solo chi l'ha inserita («Elimina»); «✂ Taglia» "
                      "la sposta su un altro S/N dello stesso OP o di un altro OP (anche chi può modificare l'OP). "
                      "Si fanno dal controllo (anomalia aperta nel blocco) o dalla card «Segnalazione» di Gestione "
                      "anomalie, e si può solo finché nessuno ci ha lavorato: niente decisione del capocommessa, niente presa in carico dal link della mail, niente risposte del cliente o azioni registrate."),
                ("p", "Dati dell'OP scritti male (P/N, fase, capocommessa, CAR, note, collaudo di benestare)? In "
                      "Gestione anomalie, nella scheda dell'OP in cima alla colonna Anomalie, «Modifica OP» apre una finestra per correggerli: il "
                      "pulsante c'è solo per il controllore che ha creato l'OP dal portale e chiede il «Motivo della "
                      "modifica». Il numero dell'OP non si cambia (per un OP sbagliato c'è «✂ Taglia»); la modifica "
                      "resta nella «Cronologia azioni» dell'OP."),
                ("p", "Guide rapide con le immagini delle pagine, da scaricare in PDF: dal pulsante «? Guida» di "
                      "qualunque pagina Anomalie scegli «Guida del controllore» o «Guida del capocommessa / CAR»."),
                ("p", "Un OP nuovo (da «+ Nuovo OP» o da «Clona») si crea solo quando salvi il primo blocco di "
                      "anomalie: chi esce prima non lascia OP vuoti. Se il numero è già usato la pagina lo dice prima "
                      "di andare avanti. Quello che scrivi si salva comunque in bozza, e una bozza ferma da 15 minuti "
                      "manda al controllore una mail con il contenuto e il link per riprendere."),
                ("p", "Gestione anomalie mostra solo gli OP che ti riguardano: quelli di cui sei capocommessa o CAR, "
                      "quelli dove hai aperto un'anomalia e quelli che il tuo ruolo ti fa vedere (team o tutti). Di "
                      "partenza il filtro è «Con aperte»; «In carico a me» tiene gli OP di cui sei capocommessa o CAR "
                      "(e, per i referenti RDC di Configurazione, quelli con anomalie aperte da aprire RDC o da "
                      "segnalare al cliente), "
                      "«Tutti» mostra anche quelli con sole anomalie chiuse."),
                ("p", "Se scrivi una nota nella decisione, l'avanzamento non può restare «In attesa»: va scelto uno "
                      "stato diverso, nel portale come nella pagina della mail."),
                ("p", "«Tempi ed esiti», nel dettaglio dell'anomalia, mostra i tempi in ore lavorate, 08:00–18:00 dei giorni "
                      "lavorativi (risposta "
                      "del capocommessa, attesa del cliente, esecuzione, risoluzione) e serve a registrare la risposta "
                      "del cliente e l'azione effettuata (rilavorazione, scarto…) con mail, foto e documenti allegati. "
                      "Con «Azione di recupero» l'anomalia si chiude solo registrando l'azione effettuata; dopo una "
                      "rilavorazione o riparazione serve «Pezzo riverificato conforme». In Statistiche i tempi per "
                      "capocommessa, nella scheda NC quelli delle sue anomalie."),
                ("p", "«Non voglio più aggiornamenti su questo OP», in fondo alla mail di decisione e al riepilogo, "
                      "chiede conferma nel portale e vale solo per chi è collegato e solo per quell'OP. La mail con il "
                      "link di decisione continua ad arrivare a chi deve decidere. «Aggiornamenti per OP» nel Menu "
                      "Anomalie elenca gli OP silenziati e permette di riattivarli."),
                ("p", "Le decisioni prese nel portale partono in un'unica mail di riepilogo dopo 5 minuti senza "
                      "salvataggi sull'OP (Configurazione → Notifiche); la barra «N decisioni in attesa di invio» in "
                      "Gestione anomalie permette di mandarle subito con «Invia ora»."),
                ("p", "Il dettaglio dell'anomalia ha tre blocchi: «Controllore · segnalazione» (con «Dove sono i "
                      "pezzi?»), «Capocommessa» (flag RDC, cliente, terzista, CAR, pezzi precedenti; «Segnalato» se la "
                      "segnalazione l'ha fatta lui, automatico per il CAR; avanzamento, note, allegati) e «Decisione "
                      "qualità» (numero RDC, «Avanzamento qualità» configurabile, note, allegati, «Segnalato» se il "
                      "capocommessa non l'ha fatto, «Chiudi l'anomalia», «Richiedi info aggiuntive»). Senza RDC le "
                      "segnalazioni fatte chiudono l'anomalia; con RDC la chiude il numero RDC. «In carico a me» mostra "
                      "solo gli OP e le anomalie che toccano a te (capocommessa, qualità, CAR segnalato, controllore a "
                      "cui sono chieste informazioni). Il link della mail fa lo stesso e accetta allegati, anche .msg ed "
                      ".eml; un secondo link permette di rispondere alle richieste della qualità senza accesso."),
                ("p", "La riga «In carico» del dettaglio dice a chi tocca l'anomalia. Capocommessa e CAR dell'OP, i CAR "
                      "segnalati e gli amministratori possono «Cambia incaricato»: scelgono la persona e l'anomalia "
                      "passa subito a lei al posto di chi la aveva (notifica e mail, «In carico a me», può fare quello "
                      "che faceva lui, compresa la decisione qualità); «Torna di serie» lo toglie. A chi passa "
                      "l'anomalia in ogni momento lo decide la tabella «Chi ha in carico l'anomalia» (Configurazione → "
                      "Qualità): per fase, avanzamento qualità, «Aprire RDC», da segnalare / segnalato (cliente, "
                      "terzista, CAR) e avanzamento (c'è sempre anche «Azione di recupero») si sceglie un ruolo "
                      "o una persona; vale la prima riga che corrisponde."),
                ("p", "La «Storia» di un'anomalia la vede chi vede l'OP: oltre agli eventi permette «Aggiungi passo» "
                      "(un'attività scritta a mano), «Aggiungi nota» sotto un evento e «Cambia incaricato». Gli eventi "
                      "registrati non cambiano."),
                ("p", "Il menu «Vista» delle colonne Ordini (Elenco, Coda di lavoro, Per capocommessa, Tabella) e "
                      "Anomalie (Per S/N, Per stato, Per fase, Per ruolo, Tabella, Pezzi) cambia il modo di vederle. "
                      "«Registro attività» (amministratori e «Supervisori») elenca in frasi chi ha fatto cosa: "
                      "inserimenti, clonazioni, modifiche con i campi cambiati, chiusure, allegati, cambi di incaricato "
                      "ed eliminazioni, con filtri; «Storia» nel dettaglio lo apre sull'anomalia."),
                ("p", "Il controllore, per ogni blocco, indica «Dove sono i pezzi?» e, per ogni anomalia, può scegliere "
                      "«Che cosa hai trovato?» (misura fuori tolleranza, difetto sul pezzo, marcatura/documenti): si "
                      "aprono solo i campi di quel caso, con l'esito della misura calcolato subito, i pulsanti dei "
                      "simboli e il riferimento a disegno, sezione e fase. Le misure si possono anche "
                      "proporre da uno screenshot delle righe del protocollo ZEISS incollato con Ctrl+V nel riquadro "
                      "«Dal report ZEISS» (l'immagine non viene allegata; le righe proposte si confermano a mano). Il capocommessa li vede nella mail e nel "
                      "riquadro «Dal controllore». Se sull'OP c'è già un controllo aperto il portale propone di "
                      "riprenderlo; i controlli vuoti si chiudono da soli dopo 24 ore."),
                ("p", "Nella decisione ci sono anche «Segnala a terzista», gli «Allegati della "
                      "decisione» e «Segnala a CAR»: scelti uno o più CAR in «A quale CAR?», al salvataggio ricevono "
                      "una mail con l'anomalia e il link (Configurazione → Notifiche → «Segnala a CAR»). Data e "
                      "nome di «Segnalato…» li riporta il riepilogo successivo. In «A quale CAR?» nessun CAR è scelto di serie: la mail va "
                      "solo a quelli spuntati, il CAR dell'OP riceve già il riepilogo. Gli "
                      "allegati della decisione si caricano anche ad anomalia chiusa."),
                ("p", "Un'anomalia chiusa la riapre chi ne è incaricato (capocommessa, CAR, controllore che l'ha "
                      "segnalata, chi può modificare l'OP) con «Riapri anomalia»: torna «In attesa». Accanto al "
                      "numero dell'OP, in cima al dettaglio, c'è il P/N."),
                ("p", "Nella scheda di una NC aperta «Segna come Part 145» indica che riguarda un componente lavorato per "
                      "l'organizzazione di manutenzione: la NC compare nel Dossier PART 145 del modulo Asset."),
                ("p", "La guida completa, con ogni schermata, è nel collegamento in cima."),
            ],
        },
    ],
    "admin": [
        {
            "id": "config",
            "titolo": "Configurazione",
            "blocchi": [
                ("ul", [
                    "Chi è capocommessa e chi riceve le mail si decide con i ruoli del modulo e in Anagrafica.",
                    "«Campi del blocco del controllore» (Configurazione, in cima): per ogni parte nuova di Apertura "
                    "segnalazione «Visibile: Sempre / Mai / Solo se…» con gruppi di controllori («Chi fa cosa»: CMM, visivo…), "
                    "persone, ruoli operativi, parole della fase "
                    "(es. CMM) e tipo di difetto dell'anomalia; l'«Anteprima dal vivo» mostra la scheda come la vedrebbe un "
                    "controllore scelto in «Vedi come»; vale subito, senza rilasci.",
                    "«Referenti RDC / segnalazione cliente» (Configurazione, un nome o email per riga, con «Aggiungi» "
                    "dall'anagrafica): queste persone vedono in «In carico a me» gli OP con anomalie aperte da aprire "
                    "RDC o da segnalare al cliente e possono modificarne le anomalie (decisione, numero RDC, allegati). "
                    "Sono la «Qualità»: prendono la decisione qualità e chiudono. «Avanzamento qualità» e «Il "
                    "capocommessa può chiudere le anomalie» si impostano nella stessa pagina. Con lo "
                    "stato «In attesa di ulteriori informazioni» il referente la rimanda al capocommessa, spunte comprese.",
                    "La mail «Segnala a CAR» va al CAR solo se il nominativo corrisponde a un solo utente e ha l'email "
                    "di notifica in anagrafica; si spegne in Configurazione → Notifiche.",
                    "Con «Ruoli e permessi» acceso l'ambito delle celle anomalie decide chi vede e modifica: «Tutti» "
                    "ogni OP, «Team» gli OP del team (capocommessa, CAR o autori delle anomalie nel team), «Propri» "
                    "solo i suoi. Capocommessa e CAR modificano sempre i propri OP (regole CC/CAR del modulo). Di "
                    "serie: Qualità modifica tutto, Caporeparto il suo team, Ingegneria e Controllo qualità aprono "
                    "segnalazioni ovunque ma modificano solo i propri OP (migrazione core 0106 del 02/11/2026).",
                    "Configurazione → Notifiche → «OP silenziati dalle persone» elenca chi ha chiesto di non ricevere "
                    "più gli aggiornamenti di un OP, con «Riattiva». Il silenzio non ferma la mail di decisione a chi "
                    "deve decidere, la lista RDC e «Segnala a CAR». Un indirizzo delle liste senza utente nel portale "
                    "non può silenziarsi da solo: si toglie dalla lista.",
                    "La mail al capocommessa parte una sola volta, a fine controllo; se il controllo resta fermo il "
                    "controllore riceve un promemoria (notifica + mail con riepilogo, default 15 minuti) e la mail parte "
                    "da sola dopo il tempo di invio automatico (default 1 ora). I due tempi si cambiano in "
                    "Configurazione → Notifiche → «Orari e soglie».",
                    "Il blocco che il controllore sta scrivendo si salva da solo come bozza e torna con «Riprendi» "
                    "(senza gli allegati).",
                    "Gruppo qualità: chi ha il ruolo «Controllo qualità» o «Qualità» vede i controlli in sospeso dei "
                    "colleghi dello stesso gruppo (riquadro in cima ad «Apertura segnalazione», ultimi 14 giorni) e li "
                    "prosegue con «Prendi in carico»: il controllo, bozza compresa, passa a lui, il collega riceve un "
                    "avviso e il passaggio resta nel controllo e nel log. Il gruppo segue i ruoli assegnati in "
                    "«Ruoli e permessi» (anche da organigramma).",
                    "La mail del controllo la spedisce il modulo stesso: al capocommessa dell'OP, con il CAR in copia "
                    "più le persone che l'operatore aggiunge (solo dall'anagrafica, con email di notifica, max 10). "
                    "Tutte le mail del modulo stanno in Configurazione → Notifiche: quando partono, chi le riceve, "
                    "interruttori, orari, liste di destinatari fissi e indirizzo della mail «nuova anomalia fuori da "
                    "un controllo». La stessa vista è in Automazioni → Notifiche di sistema: un dato solo, due pagine.",
                    "La vecchia regola Automazioni «AU-MAIL-ANOMALIE anomalia modificata» è spenta: il riepilogo "
                    "delle modifiche lo manda il modulo, 5 minuti dopo l'ultima modifica sull'OP.",
                    "I pulsanti «Apri nel portale» delle mail puntano all'indirizzo del portale (SITE_URL) passando "
                    "dall'accesso Windows (/login/windows/) quando LDAP è attivo e il pulsante «Accedi con credenziali "
                    "Windows» è visibile nel login; altrimenti puntano direttamente alla pagina, che chiede il login.",
                ]),
            ],
        },
        {
            "id": "svuota",
            "titolo": "Svuotare i dati di collaudo",
            "blocchi": [
                ("ul", [
                    "Dal portale chi ha inserito un'anomalia la elimina solo finché nessuno l'ha gestita (resta nel "
                    "registro attività); per togliere i dati di prova si usa, sul server, il "
                    "comando «manage.py svuota_anomalie». Da solo conta quante righe toccherebbe; con «--esegui» "
                    "cancella davvero.",
                    "Cancella tutte le anomalie e gli OP, le NC con azioni e allegati, i controlli, le schede "
                    "qualità, le richieste di informazioni, gli incaricati, il registro delle mail e delle azioni e "
                    "le cartelle degli allegati. Con "
                    "«--mantieni-op» gli OP restano.",
                    "Non tocca la configurazione: tipi difetto, ruoli, regole di accesso e impostazioni delle "
                    "notifiche restano come sono.",
                    "Non si torna indietro: fai prima il backup del database.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Nella scheda dell'OP non compare «Modifica OP»",
            "fare": [
                "Il pulsante c'è solo per chi ha creato l'OP dal portale («+ Nuovo OP»): gli OP del gestionale non "
                "si modificano da qui, li corregge chi gestisce il gestionale.",
                "Il pulsante è nella scheda dell'OP in cima alla colonna Anomalie, accanto a «Clona», non sulla riga a sinistra.",
                "Il numero dell'OP non si cambia: per anomalie sull'OP sbagliato usa «✂ Taglia».",
            ],
        },
        {
            "sintomo": "Il capocommessa non riceve la mail",
            "fare": [
                "Configurazione → Notifiche: guarda «Ultimo invio» della mail e se il processo risulta spento.",
                "Configurazione → Log attività: cerca la mail, leggi l'errore e usa «Reinvia».",
                "Controlla l'email di notifica del capocommessa in Anagrafica.",
                "Se nessuna mail del portale parte, Manuale di emergenza → «Le mail non partono».",
            ],
        },
        {
            "sintomo": "Una persona in copia non riceve più le mail di un OP",
            "fare": [
                "Configurazione → Notifiche → «OP silenziati dalle persone»: se c'è, l'ha chiesto lei dalla mail.",
                "«Riattiva» sulla sua riga, oppure lo fa da sé da Menu Anomalie → «Aggiornamenti per OP».",
            ],
        },
        {
            "sintomo": "«Apri nel portale» apre il login invece di entrare da solo",
            "perche": "l'accesso Windows automatico funziona solo dai PC del dominio con il portale tra i siti "
                      "intranet del browser; da telefono o fuori rete serve il login.",
            "fare": [
                "Accedi con nome utente e password: dopo l'accesso si apre comunque l'OP.",
                "Se succede da un PC aziendale, prova «Accedi con credenziali Windows» nella pagina di login: se "
                "fallisce anche lì il problema è l'accesso Windows (IT), non la mail.",
            ],
        },
        {
            "sintomo": "Il collegamento nella mail dice che non è più valido",
            "perche": "i collegamenti sono monouso e scadono.",
            "fare": ["Il capocommessa può decidere dal portale, aprendo l'OP in Gestione anomalie."],
        },
        {
            "sintomo": "Salvando la pagina della mail compare «Token di sessione non valido» (HTTP 403, Origin null)",
            "perche": "difetto del portale corretto il 17/10/2026: la pagina pubblica bloccava l'invio del modulo.",
            "fare": [
                "Dopo l'aggiornamento basta riaprire il link della mail e salvare di nuovo.",
                "Nel frattempo la decisione si può prendere dal portale, aprendo l'OP in Gestione anomalie.",
            ],
        },
        {
            "sintomo": "Dopo un aggiornamento del portale capi reparto, capi commessa, liste, logo o modello del Report OP sono tornati vuoti",
            "perche": "fino a ottobre 2026 la configurazione stava in un file dentro la cartella del programma, "
                      "che ogni aggiornamento sostituisce. Ora è salvata nel database e resta.",
            "fare": [
                "Apri Configurazione: al primo accesso il portale recupera da solo l'ultima copia salvata.",
                "Se manca ancora qualcosa, chiedi all'amministratore di sistema di ripristinare la copia del "
                "file della versione precedente.",
            ],
        },
    ],
}
