GUIDA = {
    "slug": "anagrafica",
    "titolo": "Anagrafica HR",
    "area": "Persone e HR",
    "sintesi": "Dipendenti, organigramma, formazione, visite mediche, documenti e skill matrix.",
    "parole": "anagrafica dipendente dipendenti organigramma reparto area mansione formazione corso visita medica skill matrix",
    "url": "anagrafica:index",
    "prefissi": ("/anagrafica/", "/organigramma", "/rubrica"),
    "dettaglio": [
        ("Persone e account", "anagrafica:guida_persone_account"),
        ("Formazione d'aula", "anagrafica:formazione_guida"),
        ("Formazione online", "anagrafica:formazione_online_guida"),
    ],
    "uso": [
        {
            "id": "menu",
            "titolo": "Come è organizzato il menu",
            "blocchi": [
                ("def", [
                    ("Persone", "elenco dipendenti, nuovo dipendente, ex dipendenti, documenti, organigramma, reparti."),
                    ("Competenze", "formazione (corsi, sessioni, e-learning, copertura) e skill matrix."),
                    ("Salute e sicurezza", "visite mediche, idoneità, mansioni di rischio."),
                    ("Report", "reportistica componibile ed export."),
                    ("Impostazioni", "cataloghi (ruoli, mansioni, aree, reparti) e permessi HR."),
                ]),
                ("p", "Vedi solo le voci per cui hai il permesso."),
            ],
        },
        {
            "id": "cercare",
            "titolo": "Trovare un dipendente",
            "blocchi": [
                ("passi", [
                    "Apri Anagrafica → «Persone».",
                    "Scrivi cognome o nome nella ricerca: l'elenco si filtra mentre scrivi.",
                    "Clicca la riga per aprire la scheda.",
                ]),
                ("p", "I nomi sono scritti COGNOME NOME in maiuscolo. Sotto il nome vedi i ruoli che la persona ricopre."),
            ],
        },
        {
            "id": "pagine-sezione",
            "titolo": "Le pagine d'ingresso delle sezioni",
            "blocchi": [
                ("p", "Ogni sezione si apre con lo stesso schema: in alto i numeri di oggi (quelli cliccabili aprono "
                      "l'elenco già filtrato), poi una scheda per ogni «oggetto» della sezione con una barra colorata, "
                      "in basso l'elenco di lavoro e a destra le altre pagine della sezione."),
                ("def", [
                    ("Persone", "una scheda per reparto con l'organico per tipo di contratto; il clic filtra l'elenco."),
                    ("Ingressi (Cruscotto recruiting)", "una scheda per posizione aperta con i candidati per fase dell'iter; sotto, gli onboarding aperti."),
                    ("Formazione", "una scheda per corso obbligatorio con la copertura e la prossima sessione."),
                    ("Qualifiche", "una scheda per tipo di qualifica: valide, entro 60 e 30 giorni, scadute; il clic apre lo scadenzario del tipo."),
                    ("Salute e sicurezza", "una scheda per mansione di rischio; con il permesso HR la barra dice quante persone sono in regola con tutti gli obblighi."),
                    ("Visite mediche", "una scheda per tipo di visita: in regola, entro 60 giorni, scadute, senza visita. Mai esiti o giudizi."),
                    ("Amministrazione", "una scheda per flusso (retribuzioni, cedolini, contratti) con righe abbinate e scartate dell'ultimo import."),
                    ("Report", "una scheda per modello con le generazioni degli ultimi 30 giorni e i pulsanti Genera, Modifica, Duplica."),
                ]),
                ("p", "Sopra le schede, i pulsanti filtrano (per categoria, livello di rischio, norma…) e cambiano l'ordine. "
                      "Le schede contano solo i dati che il tuo profilo può vedere."),
            ],
        },
        {
            "id": "dettaglio",
            "titolo": "Le guide di dettaglio",
            "blocchi": [
                ("p", "Per nuovo dipendente, account, uscita dall'azienda e formazione ci sono guide passo passo dedicate: "
                      "i collegamenti sono in cima a questa pagina."),
            ],
        },
    ],
    "admin": [
        {
            "id": "organizzazione",
            "titolo": "Reparti, aree aziendali e responsabili",
            "blocchi": [
                ("ul", [
                    "Ogni dipendente sta in un'area aziendale; ogni area sta in un reparto.",
                    "Il responsabile dell'area è chi approva ferie e permessi dei suoi dipendenti; se manca, li approva il caporeparto.",
                    "Lo stesso collegamento decide chi vede i dati del proprio team in Assenze, DPI, Ticket e negli altri moduli.",
                ]),
                ("nota", "Prima di cambiare responsabile o area di un gruppo di persone, avvisa: le richieste già inviate restano al vecchio responsabile."),
            ],
        },
        {
            "id": "cataloghi",
            "titolo": "Cataloghi e impostazioni",
            "blocchi": [
                ("p", "Anagrafica → «Impostazioni» raccoglie in un'unica pagina: ruoli (catalogo unico, con «riporta a»), mansioni e "
                      "mansioni di rischio, aree, reparti, tipi documento, campi di ingresso e uscita, permessi HR."),
            ],
        },
        {
            "id": "account",
            "titolo": "Dipendente e account non sono la stessa cosa",
            "blocchi": [
                ("ul", [
                    "Il dipendente è la scheda HR (anagrafica). L'account è l'utente con cui si entra nel portale.",
                    "I due vanno collegati: senza collegamento la persona non vede i propri dati (ferie, DPI, formazione).",
                    "L'email di notifica in anagrafica è quella a cui arrivano le mail del portale: può essere diversa dall'email di accesso.",
                ]),
            ],
        },
        {
            "id": "comandi",
            "titolo": "Comandi utili (sul server)",
            "blocchi": [
                ("def", [
                    ("normalizza_nomi_dipendenti", "riscrive i nomi nel formato COGNOME NOME maiuscolo."),
                    ("pulisci_scadenze_hr", "ricalcola le scadenze di formazione e visite."),
                    ("report_ruoli_disallineati", "elenca i ruoli diversi tra anagrafica e account."),
                ]),
                ("p", "Prima di ogni comando che scrive, lancialo in prova (--dry-run) se l'opzione esiste."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona entra nel portale ma non vede i suoi dati",
            "perche": "il suo account non è collegato alla sua scheda anagrafica.",
            "fare": [
                "Apri la scheda del dipendente in Anagrafica.",
                "Nella parte account collega l'utente del portale (cerca per nome utente o email).",
                "Fai uscire e rientrare la persona.",
            ],
        },
        {
            "sintomo": "Le mail del portale non arrivano a una persona",
            "fare": [
                "Controlla nella scheda l'«email di notifica».",
                "Amministrazione → «Log notifiche»: verifica se la notifica è partita e a quale indirizzo.",
            ],
        },
        {
            "sintomo": "Scadenze di formazione o visite sbagliate",
            "fare": [
                "Controlla la mansione e i ruoli della persona: le scadenze dovute dipendono da lì.",
                "Lancia pulisci_scadenze_hr dal terminale del Setup Wizard.",
            ],
        },
    ],
}
