GUIDA = {
    "slug": "fornitori",
    "titolo": "Fornitori",
    "area": "Produzione e operations",
    "sintesi": "Anagrafica fornitori con documenti a scadenza, requisiti di sicurezza per chi lavora in sede, ordini, valutazioni, asset, e per ogni ditta manutenzione, copie delle multifunzioni, scadenze e tecnici.",
    "parole": "durc duvri visura idoneità tecnico professionale polizza rct art 26 appalto requisiti fornitore fornitori ordine ordini valutazione albo partita iva accessi esterni visitatori ospiti consulenti guestportal reception badge tecnici tecnico ditta manutenzione ordinaria scadenza amministrativa odl ticket contratto assistenza ricambi fattura fatture copie mfc multifunzione stampanti scadenze esporta csv",
    "url": "fornitori:index",
    "prefissi": ("/fornitori/",),
    "uso": [
        {
            "id": "cercare",
            "titolo": "Cercare un fornitore",
            "blocchi": [
                ("passi", [
                    "Apri Fornitori e clicca «📋 Elenco fornitori».",
                    "Cerca per ragione sociale, partita IVA o città e clicca «Filtra».",
                    "Clicca «Apri →» per la scheda.",
                ]),
            ],
        },
        {
            "id": "requisiti",
            "titolo": "Requisiti per lavorare in sede (art. 26 D.Lgs. 81/2008)",
            "blocchi": [
                ("p", "In «Modifica» spunta «Lavora nei nostri locali» per appalti, manutenzioni e servizi in azienda. "
                      "Servono visura camerale, idoneità tecnico-professionale, DURC e DUVRI (obbligatori) e la polizza "
                      "RCT/RCO (consigliata), caricati in «Documenti» con la scadenza."),
                ("def", [
                    ("Documenti in regola", "tutti gli obbligatori validi."),
                    ("Documenti in scadenza", "un obbligatorio scade entro 30 giorni."),
                    ("Documenti non in regola", "un obbligatorio manca o è scaduto."),
                ]),
                ("p", "Se una ditta non in regola entra dal GuestPortal compare l'avviso in «Accessi esterni» e nella lista "
                      "«Presenti in azienda»; RSPP e ASPP dell'organigramma ricevono una notifica (mai una mail), una "
                      "volta per ingresso. Le scadenze sono anche nello Scadenzario."),
            ],
        },
        {
            "id": "scheda",
            "titolo": "La scheda del fornitore",
            "blocchi": [
                ("def", [
                    ("Documenti", "certificati e contratti con tipo e scadenza (DURC, visura, DUVRI, polizza…): «Carica» per aggiungerne (PDF, Office o immagini, massimo 15 MB)."),
                    ("Ordini", "con stato e importo: la somma è la spesa totale. «Salva ordine»."),
                    ("Valutazioni", "qualità, puntualità e comunicazione da 1 a 5 stelle. «Salva valutazione»."),
                    ("Asset", "macchine o contratti assegnati al fornitore. «Assegna» / «Rimuovi»."),
                ]),
            ],
        },
        {
            "id": "scheda-collegamenti",
            "titolo": "Manutenzione, copie, scadenze e tecnici della ditta",
            "blocchi": [
                ("p", "Nella scheda del fornitore queste schede mostrano ciò che esiste già negli altri moduli: non c'è niente da compilare e una scheda vuota lo dice senza errori."),
                ("def", [
                    ("Manutenzione", "ordini di lavoro, ticket delegati, contratti di assistenza, verifiche impianti, ricambi e rinnovi di licenze. «Scheda manutenzione completa →» apre la pagina di Asset, con gli stessi numeri."),
                    ("Copie MFC", "macchine e fatture delle copie, con l'esito della Riconciliazione e i trimestri senza fattura della ditta."),
                    ("Scadenze", "documenti, contratti, verifiche periodiche e attività dello Scadenzario della ditta, in ordine di data; «In scadenza» = entro 30 giorni."),
                    ("Tecnici", "il registro dei tecnici della ditta: si registrano da soli quando entrano dal GuestPortal o quando un ingresso viene collegato a un intervento, oppure con «+ Nuovo tecnico». Se la ditta non è ancora tra i fornitori, in «Accessi esterni» il pulsante «+ Crea fornitore» crea il fornitore dal nome scritto nel GuestPortal e ci registra la persona. Il tecnico non riceve accesso al portale. «Modifica» per qualifica, contatti e attestati (facoltativi). Con il permesso di «Accessi esterni» si vedono anche ingressi, ore e chi è dentro ora."),
                ]),
                ("p", "«Copie MFC» compare da sola se il nome del fornitore è quello di Contatori; altrimenti collega il fornitore dal riquadro «Multifunzioni» della scheda con «Collega»."),
            ],
        },
        {
            "id": "elenco-filtri",
            "titolo": "Elenco: documenti ed esportazione",
            "blocchi": [
                ("ul", [
                    "Nell'elenco il filtro «Documenti di sicurezza» mostra le ditte in sede in regola, in scadenza o non in regola.",
                    "«Esporta CSV» scarica tutte le righe filtrate, non solo la pagina che vedi.",
                    "Nella pagina iniziale «Da guardare» elenca ditte non in regola, documenti e contratti in scadenza, OdL aperti affidati a una ditta: compare solo se c'è qualcosa.",
                ]),
            ],
        },
        {
            "id": "accessi-esterni",
            "titolo": "Accessi esterni (GuestPortal)",
            "blocchi": [
                ("p", "Visitatori, fornitori e consulenti che si registrano al chiosco della reception (GuestPortal). "
                      "Apri Fornitori → «Accessi esterni»."),
                ("def", [
                    ("Presenti ora", "chi ha fatto il check-in e non ancora il check-out, dal più vecchio: con badge, referente e da quanto tempo è in azienda."),
                    ("Storico", "le visite con ingresso nel periodo «Dal» / «Al» (di base gli ultimi 7 giorni), filtrabili per «Tipo» e con «Cerca» su nome, azienda, referente e motivo. Si vedono al massimo 500 visite: se sono di più la pagina lo dice e va ristretto il periodo."),
                    ("Azienda in blu", "la ditta è abbinata, oppure ha lo stesso nome di un fornitore attivo dell'HUB a meno di maiuscole, punteggiatura e forma giuridica (S.r.l., S.p.A., Snc…): il link apre la sua scheda."),
                    ("Ospite anonimizzato", "il GuestPortal ha già anonimizzato l'ospite per il GDPR: nome e azienda non si vedono più."),
                ]),
                ("p", "«Apri GuestPortal ↗» (e la voce di menu «Accessi azienda») apre il pannello del GuestPortal già "
                      "collegato con il tuo utente, senza ridigitare la password, se sei abilitato nel pannello."),
                ("nota", "I dati si leggono dal GuestPortal ogni volta che apri la pagina e non vengono copiati nell'HUB: "
                         "quando il GuestPortal cancella le visite vecchie (pulizia GDPR) spariscono anche qui."),
                ("p", "La colonna «Incaricato per» mostra i ticket e gli ordini di lavoro a cui l'ingresso è stato collegato; "
                      "«Collega…» (o «+ altro») apre la scelta dell'intervento."),
            ],
        },
        {
            "id": "presenze-interventi",
            "titolo": "Collegare l'ingresso della ditta a ticket, OdL, manutenzione o scadenza",
            "blocchi": [
                ("p", "Si può partire da due parti: dall'ingresso (Fornitori → «Accessi esterni» → «Collega…» sulla riga "
                      "dell'esterno: si sceglie il ticket MAN, l'OdL, la manutenzione ordinaria o la scadenza e si clicca «Collega») oppure dall'intervento, "
                      "con il riquadro «Presenze in azienda della ditta» nei ticket di manutenzione (scheda «Interventi» "
                      "della gestione), in ogni ordine di lavoro aperto, in «Registra l'esecuzione» delle manutenzioni affidate a una ditta, "
                      "nella pagina di modifica delle scadenze degli asset e nella scheda delle attività dello Scadenzario."),
                ("p", "Il collegamento è una prova di presenza: non registra la manutenzione e non rinnova la scadenza. "
                      "Se la manutenzione, la scadenza o l'attività non ha ancora una ditta, prende quella dell'ingresso; "
                      "un ente già scritto a mano su una scadenza dell'asset non viene cambiato. "
                      "Una manutenzione già eseguita si può collegare anche dopo."),
                ("p", "Se il ticket o l'OdL non ha ancora una ditta e quella dell'ingresso si riconosce, collegando la si "
                      "imposta: il ticket diventa «Delegato a fornitore» (con un commento interno), l'OdL passa a esecuzione "
                      "«Esterna» con quella ditta (scritto nel registro dell'OdL). Una ditta già impostata non viene cambiata. "
                      "Se la ditta non era ancora tra i fornitori dell'HUB il riquadro lo dice: crea il fornitore (o abbina la ditta in «Ditte GuestPortal»), "
                      "riapri il ticket/OdL e clicca «Imposta come ditta» nel riquadro, senza ricollegare l'ingresso."),
                ("passi", [
                    "Imposta la ditta: «Delegato a fornitore» nel ticket, il fornitore nell'OdL.",
                    "Il riquadro propone gli ingressi della ditta dal giorno prima dell'apertura fino alla chiusura (al massimo 90 giorni): sotto «Ingressi della ditta da collegare» clicca «Collega» su quelli giusti.",
                    "Se la ditta non compare (azienda scritta in modo diverso al chiosco), usa «Collega a mano un ingresso del giorno»: scegli il giorno, «Mostra ingressi», poi «Collega».",
                    "«Togli» annulla un collegamento sbagliato finché l'intervento è aperto.",
                ]),
                ("def", [
                    ("Totale in azienda", "somma del tempo tra entrata e uscita degli ingressi collegati."),
                    ("Avviso giallo sulle ore", "nei ticket: le ore registrate negli interventi superano di oltre 15 minuti la presenza in azienda. Controlla il rapportino prima di approvare la fattura."),
                    ("Ancora dentro", "il tecnico non ha ancora fatto il check-out: l'uscita si completa da sola alla prossima apertura del riquadro."),
                ]),
                ("nota", "Al collegamento l'HUB salva giorno, entrata, uscita e nome del tecnico: restano nel ticket/OdL come prova "
                         "dell'intervento anche dopo la pulizia GDPR del GuestPortal. Il riquadro lo usano i gestori del ticket e chi "
                         "esegue le manutenzioni; un intervento chiuso non si modifica più."),
            ],
        },
        {
            "id": "presenze-docenti",
            "titolo": "Collegare l'ingresso del docente esterno alla sessione formativa",
            "blocchi": [
                ("p", "Lo stesso collegamento vale per la formazione: nel dettaglio di un'edizione (Anagrafica → Formazione → "
                      "sessione) il riquadro «Presenze in azienda del docente» propone gli ingressi con il nome del docente "
                      "(anche in ordine inverso) o con l'azienda dell'ente di formazione, dal giorno prima dell'inizio alla fine. "
                      "Da Accessi esterni, «Collega…» elenca anche le sessioni in corso il giorno dell'ingresso, prima quelle del docente."),
                ("def", [
                    ("Anche dopo", "si collega anche a edizione completata o approvata; non a un'edizione annullata."),
                    ("Ore in aula a registro", "somma delle giornate dell'edizione con la pausa: se superano di oltre 15 minuti la presenza in azienda compare l'avviso giallo."),
                    ("Chi lo usa", "chi può modificare la formazione; nessuna ditta viene impostata."),
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "gestire",
            "titolo": "Creare e disattivare",
            "blocchi": [
                ("ul", [
                    "«+ Nuovo fornitore», compila i dati e clicca «Salva fornitore».",
                    "Un fornitore che non si usa più si disattiva («Disattiva»), non si elimina: i suoi ordini e le manutenzioni restano collegati.",
                    "I permessi del modulo Fornitori sono separati da quelli di Anagrafica HR (Amministrazione → Accessi).",
                ]),
            ],
        },
        {
            "id": "guestportal",
            "titolo": "Collegare il GuestPortal",
            "blocchi": [
                ("ul", [
                    "Chi vede «Accessi esterni»: il permesso «Portale esterno ospiti» (legacy.portale_esterno.portale_esterno) in Amministrazione → Accessi. Mostra dati personali dei visitatori: darlo solo a reception, sicurezza e responsabili.",
                    "Il link «Apri GuestPortal» / «Accessi azienda» è aperto a chi ha fatto l'accesso all'HUB, come il vecchio link diretto: chi entra nel pannello lo decide il GuestPortal (Utenti admin del pannello).",
                    "Database: sul MySQL del GuestPortal crea un utente con solo SELECT su Visits, Guests e Suppliers e metti host, nome database, utente e password in GUESTPORTAL_DB_* del .env dell'HUB (vedi docs/integrazioni/guestportal/README.md). Dal server HUB deve essere aperta la porta 3306.",
                    "Accesso automatico: GUESTPORTAL_SSO_SECRET nel .env dell'HUB deve essere uguale a GP_SSO_SECRET in config/sso.php del GuestPortal. Senza segreto il link apre il login normale del pannello.",
                    "Dopo aver cambiato il .env riavvia il portale (sito IIS).",
                    "Ditte: in Fornitori → «Ditte GuestPortal» scegli per ogni fornitore del GuestPortal il fornitore dell'HUB e clicca «Salva» (con lo stesso nome a meno di maiuscole, punteggiatura e forma giuridica è già proposto: «Rossi Impianti» = «ROSSI IMPIANTI S.R.L.»). Senza abbinamento l'ingresso si riconosce solo con lo stesso nome a meno di quelle differenze, e solo se un unico fornitore HUB ha quel nome; con nomi davvero diversi (sigle, nomi commerciali) serve l'abbinamento. La pagina usa il permesso di «Modifica fornitore».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "La scheda «Tecnici» è vuota o non elenca tutti",
            "fare": [
                "Se nel GuestPortal la ditta ha un altro nome, abbinala in Fornitori → «Ditte GuestPortal».",
                "Chi è già uscito prima del controllo ogni 10 minuti si registra da «Entrati ma non ancora registrati» («Registra» / «Registra tutti»).",
                "Il registro resta anche dopo la pulizia GDPR del GuestPortal; ingressi e ore delle visite cancellate non si vedono più.",
            ],
        },
        {
            "sintomo": "Non vedo la scheda «Copie MFC» o «Tecnici»",
            "fare": [
                "«Copie MFC»: collega il fornitore dal riquadro «Multifunzioni» della scheda; serve il permesso delle fatture di Contatori.",
                "Nei «Tecnici» ingressi e ore richiedono il permesso di «Accessi esterni»; aggiungere e modificare richiedono quello di modifica del fornitore.",
            ],
        },
        {
            "sintomo": "Il fornitore non compare nelle manutenzioni degli asset",
            "fare": ["Controlla che il fornitore sia attivo.", "Nella scheda fornitore assegna l'asset o il contratto."],
        },
        {
            "sintomo": "Accessi esterni: avviso giallo «Collegamento al database del GuestPortal non configurato»",
            "perche": "Mancano GUESTPORTAL_DB_HOST, GUESTPORTAL_DB_USER o GUESTPORTAL_DB_PASSWORD nel .env.",
            "fare": ["Compila le chiavi GUESTPORTAL_DB_* nel .env persistente e riavvia il portale."],
        },
        {
            "sintomo": "Accessi esterni: «Il database del GuestPortal non risponde»",
            "perche": "MySQL fermo, porta 3306 chiusa dal server HUB, password cambiata o utente senza SELECT.",
            "fare": [
                "Dal server HUB prova la porta: Test-NetConnection <host MySQL> -Port 3306.",
                "Controlla che l'utente MySQL esista e abbia SELECT su Visits, Guests, Suppliers.",
            ],
        },
        {
            "sintomo": "Il riquadro «Presenze in azienda» non propone gli ingressi della ditta",
            "perche": "Ditta non impostata nel ticket/OdL, fornitore del GuestPortal non abbinato e azienda scritta diversamente al chiosco, oppure ingresso fuori dal periodo dell'intervento.",
            "fare": [
                "Imposta «Delegato a fornitore» (ticket) o il fornitore (OdL).",
                "Abbina la ditta in Fornitori → «Ditte GuestPortal».",
                "In alternativa usa «Collega a mano un ingresso del giorno».",
            ],
        },
        {
            "sintomo": "«Apri GuestPortal» porta alla pagina di login invece che dentro il pannello",
            "perche": "Segreto SSO assente o diverso tra HUB e GuestPortal, utente non presente o disattivato fra gli utenti admin del pannello, oppure orologi dei due server sfasati di oltre 30 secondi.",
            "fare": [
                "Sul server GuestPortal leggi le righe «[SSO] accesso rifiutato: …» in C:\\Windows\\Temp\\guestportal.log: il motivo è scritto lì.",
                "«firma non valida» = segreti diversi; «utente non abilitato in AdminUsers» = aggiungi l'utente nel pannello; «token scaduto o orologi non allineati» = sincronizza l'ora dei server.",
            ],
        },
    ],
}
