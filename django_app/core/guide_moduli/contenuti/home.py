GUIDA = {
    "slug": "home",
    "titolo": "Primi passi nel portale",
    "area": "Per tutti",
    "sintesi": "Come entrare, muoversi tra i moduli, trovare le cose e chiedere aiuto.",
    "parole": "accesso login password home menu notifiche cerca profilo",
    "url": "dashboard_home",
    "prefissi": ("/dashboard", "/hub/home/", "/profilo", "/notifiche/", "/bacheca/", "/scadenze", "/report/"),
    "dettaglio": [("Guida della home a stanze", "home_portale:guida"), ("Guida I miei report", "miei_report", "?guida=1")],
    "uso": [
        {
            "id": "entrare",
            "titolo": "Entrare nel portale",
            "blocchi": [
                ("passi", [
                    "Apri il browser (Chrome o Edge) e vai all'indirizzo del portale.",
                    "Scrivi il tuo nome utente aziendale (lo stesso del PC) e la password del PC.",
                    "Se ti viene chiesto un codice, inserisci quello che ti arriva per mail o sull'app (verifica in due passaggi).",
                ]),
                ("nota", "Dopo 5 tentativi sbagliati l'accesso si blocca per un'ora: aspetta e riprova, oppure chiedi all'amministratore di sbloccarti."),
            ],
        },
        {
            "id": "muoversi",
            "titolo": "Muoversi tra i moduli",
            "blocchi": [
                ("ul", [
                    "La barra in alto contiene i moduli divisi per area. Vedi solo quelli che puoi usare.",
                    "Sotto la barra c'è il menu del modulo in cui ti trovi.",
                    "Il logo in alto a sinistra riporta sempre alla home.",
                    "«Cerca o vai a…» (oppure Ctrl+K) trova una pagina, una persona o un documento scrivendo il nome.",
                ]),
            ],
        },
        {
            "id": "icone",
            "titolo": "Le icone in alto a destra",
            "blocchi": [
                ("def", [
                    ("?", "apre la guida del modulo in cui ti trovi (questa pagina)."),
                    ("Stella", "l'Assistente AI: fai una domanda in italiano, per esempio «come chiedo un permesso?»."),
                    ("Campanella", "le notifiche. Il numero rosso dice quante non hai ancora letto."),
                    ("Il tuo nome", "profilo, preferenze, tema chiaro/scuro, «Segnala un problema» ed «Esci»."),
                ]),
            ],
        },
        {
            "id": "home",
            "titolo": "La home",
            "blocchi": [
                ("p", "La home ti mostra cosa devi fare oggi (richieste da approvare, scadenze, letture), i documenti utili e i collegamenti ai moduli. "
                      "La guida completa della home è nel collegamento qui sopra."),
            ],
        },
        {
            "id": "miei-report",
            "titolo": "I miei report",
            "blocchi": [
                ("p", "Menu con il tuo nome → «I miei report»: tutti i report che puoi generare, raccolti dai vari moduli. "
                      "Vedi solo quelli dei moduli che puoi già aprire; «Apri» porta alla pagina da cui si scaricano."),
                ("ul", [
                    "«Cerca tra i tuoi report» filtra mentre scrivi.",
                    "L'etichetta «Dati personali» segna i report con dati di colleghi: usali solo per lavoro e non inoltrarli fuori dall'azienda.",
                    "«Ricevi per mail»: i report pianificati che ti arrivano da soli, con frequenza e prossimo invio.",
                    "In fondo, «I miei scaricamenti»: i tuoi ultimi 30 file di report degli ultimi 90 giorni. Il file non viene conservato.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "home-admin",
            "titolo": "Personalizzare la home e il menu",
            "blocchi": [
                ("ul", [
                    "Moduli visibili: Amministrazione → Hub → «Moduli» (accendi o spegni un modulo per tutti).",
                    "Voci del menu: Amministrazione → «Navigation Builder».",
                    "Logo, nomi e colori: Amministrazione → «Branding portale».",
                    "Cosa vede ogni persona dipende dai permessi: vedi la guida «Amministrazione del portale».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona non riesce a entrare",
            "fare": [
                "Chiedi il messaggio esatto che vede.",
                "«Credenziali non valide»: la password è quella del PC; se l'ha appena cambiata, attenda qualche minuto.",
                "Accesso bloccato dopo 5 tentativi sbagliati: il blocco dura un'ora. Per sbloccare subito, dal terminale del Setup Wizard: axes_reset_username <nome utente>.",
                "L'utente non esiste: va creato o importato da Active Directory (Amministrazione → Import Utenti LDAP).",
                "Se nessuno riesce a entrare, apri il Manuale di emergenza → «Nessuno riesce a entrare».",
            ],
        },
        {
            "sintomo": "Una persona non vede un modulo nel menu",
            "fare": [
                "Controlla che il modulo sia acceso (Amministrazione → Hub → «Moduli»).",
                "Controlla i suoi permessi: Amministrazione → «Accessi negati» mostra ogni pagina bloccata con il motivo e i pulsanti «Consenti» / «Non consentire».",
            ],
        },
    ],
}
