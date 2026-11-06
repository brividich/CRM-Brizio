GUIDA = {
    "slug": "tickets",
    "titolo": "Ticket IT e manutenzione",
    "area": "Produzione e operations",
    "sintesi": "Per segnalare un guasto o chiedere aiuto all'IT o alla manutenzione, e seguire la risposta.",
    "parole": "ticket guasto pc stampante rete manutenzione macchina rotta assistenza mappa planimetria condizionatore",
    "url": "tickets:dashboard",
    "prefissi": ("/tickets/",),
    "uso": [
        {
            "id": "aprire",
            "titolo": "Aprire un ticket",
            "blocchi": [
                ("passi", [
                    "Apri Ticket e clicca «+ Ticket IT» (computer, stampanti, rete, telefoni, programmi) oppure "
                    "«+ Ticket MAN» (macchine, impianti, attrezzature).",
                    "Scrivi il «Titolo / oggetto» in poche parole, per esempio «Stampante ufficio tecnico non stampa».",
                    "Scegli la categoria «Da catalogo», oppure «Libera» se non trovi quella giusta.",
                    "Se riguarda una macchina o un PC, scegli l'«Asset coinvolto»: «Da catalogo» cerca anche per n. interno o reparto e mostra n. interno, tag e reparto di ogni asset. "
                    "Cerca anche con le parole di tutti i giorni (per esempio «condizionatore» trova i «Chiller»).",
                    "Ticket di manutenzione: se non riconosci l'asset dal nome, clicca «Sulla mappa» (o «Cercalo sulla mappa»). "
                    "Scegli la planimetria in alto: i punti colorati sono gli asset del tuo reparto, quelli grigi degli altri reparti. "
                    "Tocca il punto giusto per sceglierlo; «Solo il mio reparto» nasconde gli altri, «+» e «−» ingrandiscono.",
                    "Se scegli l'asset dalla lista, sotto compare la pianta con il punto rosso: «È questo?». Controlla che sia quello giusto.",
                    "Se l'asset non è sulla pianta, tocca il punto in cui si trova: il ticket parte con «Punto indicato sulla …» "
                    "e chi lo gestisce collega l'asset giusto.",
                    "Scegli la «Priorita» e descrivi il problema in «Descrizione»: cosa succede, da quando, cosa hai già provato.",
                    "Clicca «Invia richiesta».",
                ]),
                ("p", "Puoi aprire un ticket anche inquadrando il QR attaccato alla macchina."),
                ("p", "Manutentori e IT: c'è «Per conto di». Scegli il collega che ha segnalato il problema: il "
                      "ticket risulta aperto da lui (lo trova in «I miei ticket» e riceve gli aggiornamenti) "
                      "e nella scheda compare «Compilato da» con il tuo nome. Tu continui a vederlo nei tuoi ticket. "
                      "Il campo c'è solo per chi gestisce quel tipo di ticket e, per la manutenzione, per chi è nel "
                      "ruolo della squadra manutenzione (Assets › Impostazioni › Configurazione)."),
                ("p", "Problema già sistemato al volo: spunta «Già risolto: registra l'intervento e chiudi il ticket», "
                      "scrivi «Cosa è stato fatto» (obbligatorio) e, se serve, «Concluso il» (vuoto = adesso) e «Ore "
                      "di lavoro», poi clicca «Registra e chiudi». Il ticket nasce «Chiuso» con l'intervento "
                      "registrato; per la manutenzione con asset entra nel registro. Il team non riceve l'avviso di "
                      "nuovo ticket, tranne quando incide sulla sicurezza. Vale anche senza «Per conto di». "
                      "Apertura e chiusura del ticket, intervento e registro manutenzione riportano le date del lavoro "
                      "(«Concluso il» meno le «Ore di lavoro»): l'ora in cui hai registrato resta nello storico."),
                ("p", "Se l'invio torna con un errore i dati restano nei campi: correggi e invia di nuovo. "
                      "Gli allegati vanno riscelti (il browser non li conserva)."),
            ],
        },
        {
            "id": "seguire",
            "titolo": "Seguire il tuo ticket",
            "blocchi": [
                ("passi", [
                    "Clicca «I miei ticket»: ci sono solo i ticket aperti da te.",
                    "Apri il ticket per vedere lo stato e i commenti del tecnico.",
                    "Per rispondere scrivi nel riquadro e clicca «Invia commento».",
                    "Per aggiungere una foto o un file usa «Carica allegati».",
                ]),
                ("def", [
                    ("Aperto", "ricevuto, nessuno l'ha ancora preso."),
                    ("In carico", "un tecnico ci sta lavorando."),
                    ("In attesa", "si aspetta qualcosa (un pezzo, una tua risposta)."),
                    ("Risolto / Chiuso", "il problema è sistemato."),
                    ("Ticket", "la voce accanto a «I miei ticket», per chi in base al ruolo vede anche i ticket di altri "
                               "(per esempio il caporeparto): tutti i ticket che puoi vedere. Su quelli aperti da altri sei "
                               "in sola lettura: niente commenti, si agisce solo sui propri da «I miei ticket». "
                               "Chi gestisce i ticket lavora da «Gestione ticket»."),
                ]),
            ],
        },
        {
            "id": "gestire",
            "titolo": "Lavorare i ticket (tecnici)",
            "blocchi": [
                ("passi", [
                    "Apri «Gestione ticket». Puoi selezionare più ticket e usare «Assegna a…», «Cambia stato» o «Prendi in carico».",
                    "Apri un ticket: «Prendi in carico» lo assegna a te.",
                    "Ogni volta che lavori sul ticket clicca «+ Aggiungi intervento», scrivi cosa hai fatto e il tempo, poi «Registra intervento».",
                    "Compila i dati tecnici (componente guasto, causa, ore di fermo macchina) e clicca «Salva dati tecnici».",
                    "A lavoro finito clicca «Segna come risolto», poi «Chiudi ticket».",
                ]),
                ("ul", [
                    "Ticket di manutenzione fatto da una ditta esterna: nella scheda «Interventi» il riquadro «Presenze in azienda della ditta» propone gli ingressi della ditta delegata registrati al chiosco della reception; «Collega» li lega al ticket e confronta le ore registrate con la presenza in azienda (guida Fornitori, «Collegare l'ingresso della ditta»).",
                    "Per un lavoro di manutenzione programmato usa «+ Apri OdL» (ordine di lavoro nel modulo Asset).",
                    "Gli allegati caricati dal QR della macchina vanno controllati: «Valida» oppure «Rifiuta» con motivo.",
                    "Per cambiare l'asset del ticket (riquadro «Asset collegato» → «Da catalogo») scrivi nome, n. interno, tag, modello o reparto: ogni risultato mostra n. interno, tag e il badge «Reparto …» per distinguere asset con lo stesso nome.",
                    "Ticket di manutenzione, scheda «Asset e KPI»: il riquadro «Dove si trova» mostra l'asset sulla planimetria "
                    "(o il punto indicato dal richiedente). Tocca un altro punto per scegliere un asset diverso e premi «Salva»; "
                    "«Apri la mappa completa» porta alla mappa officina.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "impostazioni",
            "titolo": "Impostazioni dei ticket",
            "blocchi": [
                ("p", "Ticket → «Impostazioni». Ci sono due schede separate, IT e MAN: ognuna si salva con il suo pulsante («Salva IT», «Salva MAN»)."),
                ("ul", [
                    "Categorie: «Aggiungi», attiva/disattiva, «Elimina». Ogni categoria ha il suo tempo di risposta (SLA).",
                    "Import dei ticket da file («Importa Ticket da CSV»): scegli IT o MAN, «Scarica template CSV», "
                    "poi «Scegli file CSV/Excel…» e «Importa». Il CSV va separato da virgole: dall'Excel italiano "
                    "conviene caricare direttamente il file .xlsx.",
                    "L'import non manda mail: le automazioni (avvisi «nuovo ticket», escalation) non partono per i ticket importati.",
                    "Un ticket importato risulta chiuso se la colonna «Chiuso» vale 1, Sì, Vero o x, oppure se ha una "
                    "«Data chiusura ticket» / «Data fine lavori». Per correggere ticket già importati come aperti, "
                    "reimporta lo stesso file con «Aggiorna ticket esistenti» spuntato (serve la colonna «ID»).",
                    "Escalation dei ticket urgenti: accesa o spenta, soglia in ore (predefinita 4) e ora del resoconto (predefinita 8). «Salva escalation».",
                    "«Mappa asset nei ticket di manutenzione»: scegli come si riconosce il «tuo reparto» sulla pianta — "
                    "«Reparto scritto sull'asset» (predefinito, usa anche i collegamenti di Impostazioni asset → «Reparti e capi») "
                    "oppure «Aree dei reparti disegnate sulla planimetria» (una pianta senza aree usa comunque il reparto scritto). "
                    "Per ogni categoria di manutenzione puoi fissare la planimetria che si apre; «Automatica» apre quella con più asset del reparto. «Salva mappa».",
                    "Le parole comuni per la ricerca si scrivono in Impostazioni asset, sulla categoria: «Sinonimi per la ricerca».",
                ]),
            ],
        },
        {
            "id": "sharepoint-man",
            "titolo": "Ticket manutenzione sincronizzati con SharePoint",
            "blocchi": [
                ("p", "I ticket MAN possono vivere insieme sul portale e sulla lista «Ticket» del sito SharePoint "
                      "CNManutenzioni: chi apre, modifica o chiude da una parte lo ritrova dall'altra entro 5 minuti."),
                ("ul", [
                    "Si accende in Ticket → «Impostazioni», scheda Manutenzione: «List ID SharePoint», «Site ID SharePoint», "
                    "spunta «Sincronizza con SharePoint in entrambe le direzioni», poi «Salva MAN». «Test SP» controlla che la lista risponda.",
                    "Dal portale a SharePoint: titolo, descrizione, priorità, stato, tipologia, macchinario, note, impatto su sicurezza, "
                    "«Chiuso» e «Data chiusura ticket».",
                    "Da SharePoint al portale: gli stessi campi; un elemento nuovo della lista diventa un ticket MAN (richiedente = chi l'ha "
                    "creato su SharePoint) e se il «Macchinario» corrisponde a un asset viene collegato.",
                    "Chiudere su SharePoint («Chiuso» o «Data chiusura ticket») chiude il ticket sul portale: niente più promemoria SLA ed escalation.",
                    "Stati: Aperta = Nuovo, In carico = In corso, In attesa = Bloccato (anche «Da progettazione»), Risolto = Completato, "
                    "Chiuso = Completato con «Chiuso», Annullato = Non implementabile (anche «Duplica»).",
                    "Su SharePoint lo «Stato» resta quasi sempre «Nuovo»: per un ticket aperto sul portale «Nuovo» non cambia niente, "
                    "conta la spunta «Chiuso». Togliere «Chiuso» su SharePoint riapre il ticket.",
                    "Il primo giro dopo l'accensione porta sul portale solo gli elementi nuovi della lista: i ticket già collegati "
                    "(importati con l'ID SharePoint) restano come sono, e da lì in poi passano solo le modifiche.",
                    "Se lo stesso ticket viene cambiato su entrambi i lati prima del giro, vince la modifica del portale.",
                    "Commenti, allegati, interventi, SLA ed escalation restano solo sul portale. Le modifiche arrivate da SharePoint "
                    "non mandano mail; i cambi di stato finiscono nello storico del ticket con autore «SharePoint».",
                    "Un elemento eliminato su SharePoint non cancella il ticket: resta sul portale, scollegato dalla lista.",
                ]),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Chi gestisce cosa",
            "blocchi": [
                ("ul", [
                    "Ticket IT e Ticket manutenzione sono due permessi separati: chi gestisce l'IT non gestisce la manutenzione.",
                    "Tutti vedono i propri ticket; i responsabili anche quelli del loro team; la Direzione tutti.",
                    "Con il sistema «Ruoli e permessi» acceso il ruolo base Operatore apre solo ticket di manutenzione; "
                    "i ticket IT li aprono le posizioni dell'organigramma (Direzione, Qualità, IT, Manutenzione, Ingegneria, "
                    "Amministrazione, Caporeparto, Controllo qualità).",
                    "I permessi si danno in Amministrazione → «Accessi» o «Ruoli e permessi».",
                ]),
            ],
        },
        {
            "id": "automatismi",
            "titolo": "Automatismi",
            "blocchi": [
                ("def", [
                    ("Escalation urgenti", "ogni ora: i ticket URGENTI aperti e senza assegnatario oltre la soglia generano un promemoria al team e al richiedente."),
                    ("Promemoria SLA", "comando send_sla_reminders: avvisa l'assegnatario dei ticket con SLA scaduto."),
                    ("Sincronizzazione SharePoint MAN", "ogni 5 minuti (lavoro «tickets_man_sharepoint_sync»): manda le modifiche del portale alla lista e porta sul portale quelle fatte sulla lista."),
                    ("Registro manutenzione", "i ticket MAN collegati a un asset compaiono nel registro manutenzione dell'asset."),
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": 'I numeri in testa alla gestione ticket comprendono tipi che non gestisco',
            "fare": [
                'Ora contano solo i tipi che gestisci (IT, manutenzione o entrambi), come le liste sotto.',
            ],
        },
        {
            "sintomo": "Un asset non compare sulla mappa del ticket",
            "perche": "sulla mappa ci sono solo gli asset non IT collocati su una planimetria attiva, in servizio e non dismessi.",
            "fare": [
                "Apri la mappa officina (Asset → mappa) e collocalo dall'editor sulla planimetria giusta.",
                "I PC, le stampanti e gli altri apparati IT non vanno sulla mappa dei ticket.",
            ],
        },
        {
            "sintomo": "Sulla mappa gli asset del mio reparto sono grigi",
            "fare": [
                "Il reparto scritto sull'asset non è riconosciuto: collegalo in Impostazioni asset → «Reparti e capi».",
                "Se in Impostazioni ticket hai scelto «Aree dei reparti», controlla che le aree siano disegnate e abbiano il reparto.",
            ],
        },
        {
            "sintomo": "Il tecnico non vede i ticket in «Gestione ticket»",
            "fare": [
                "Controlla che abbia il permesso di gestione del tipo giusto (IT oppure MAN).",
                "Fagli ricaricare la pagina e togliere i filtri.",
            ],
        },
        {
            "sintomo": "Non arrivano i promemoria dell'escalation",
            "fare": [
                "Ticket → Impostazioni: controlla che l'escalation sia accesa e la soglia corretta.",
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla il lavoro di escalation dei ticket.",
                "Se il cluster è fermo segui «Le automazioni non partono» nel Manuale di emergenza.",
            ],
        },
        {
            "sintomo": "Un ticket manutenzione non compare su SharePoint (o viceversa)",
            "fare": [
                "Ticket → Impostazioni, scheda Manutenzione: controlla che la sincronizzazione sia spuntata e premi «Test SP».",
                "Sotto la spunta leggi «In coda verso SharePoint» e l'eventuale «Ultimo errore».",
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla «tickets_man_sharepoint_sync».",
                "Aspetta il giro successivo: la sincronizzazione passa ogni 5 minuti.",
            ],
        },
        {
            "sintomo": "Un allegato non si carica",
            "perche": "il portale controlla il contenuto vero del file, non solo l'estensione, e ha un limite di dimensione.",
            "fare": [
                "Prova a salvarlo come PDF o JPG.",
                "Controlla che sia sotto il limite di caricamento (100 MB).",
            ],
        },
    ],
}
