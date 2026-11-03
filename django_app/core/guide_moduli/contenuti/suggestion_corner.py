GUIDA = {
    "slug": "suggestion_corner",
    "titolo": "Suggestion Corner",
    "area": "Qualità e sistema di gestione",
    "sintesi": "Segnalazioni e idee di miglioramento, gestite con il ciclo PDCA (pianifica, fai, verifica, agisci).",
    "parole": "suggerimento suggerimenti idea miglioramento segnalazione sms pdca",
    "url": "suggestion_corner:home",
    "prefissi": ("/suggestion-corner/",),
    "uso": [
        {
            "id": "segnalare",
            "titolo": "Inviare una segnalazione o un'idea",
            "blocchi": [
                ("passi", [
                    "Apri Suggestion Corner e clicca «+ Nuova segnalazione».",
                    "Scegli da quale reparto o area nasce e a quale è rivolta.",
                    "Descrivi il problema o l'idea con parole semplici. Se vuoi, allega una foto.",
                    "Invia. Il team miglioramento riceve una mail.",
                ]),
                ("p", "Si può segnalare anche senza account, dal modulo pubblico: basta inquadrare il QR della locandina in bacheca."),
            ],
        },
        {
            "id": "qr",
            "titolo": "Dal QR in bacheca, con il telefono",
            "blocchi": [
                ("passi", [
                    "Inquadra il QR con la fotocamera del telefono e apri il link.",
                    "Scegli il reparto (e, se serve, l'area) e scrivi l'idea o il problema.",
                    "Se vuoi, aggiungi una foto: «Foto — facoltativa» (JPG, PNG o WEBP, massimo 15 MB).",
                    "Scegli «Anonimo» oppure «Mi identifico». Con «Mi identifico» scrivi «Nome e cognome»; se sei già entrato nel portale, invii col tuo nome («Invierai come …»).",
                    "«Invia segnalazione».",
                ]),
                ("nota", "Con «Anonimo» non si registra chi sei: né l'account né il nome. Dalla foto vengono tolti posizione e dati del telefono."),
            ],
        },
        {
            "id": "seguire",
            "titolo": "Seguire la segnalazione",
            "blocchi": [
                ("p", "Nell'elenco vedi le tue segnalazioni e quelle in cui sei incaricato. Ogni segnalazione mostra lo stato del ciclo:"),
                ("def", [
                    ("PLAN", "si decide cosa fare («Definisci PLAN»)."),
                    ("DO", "si fa («Avvia DO», poi «Completa DO»)."),
                    ("CHECK", "si controlla se ha funzionato («Check positivo», «Check negativo (riapre DO)» o «Rinvia check»)."),
                    ("ACT", "si rende stabile la soluzione («Inserisci ACT»), poi «Chiudi»."),
                ]),
            ],
        },
        {
            "id": "locandine",
            "titolo": "Locandine QR per le bacheche",
            "blocchi": [
                ("p", "«Locandine QR» (in elenco e in «⚙ Gestione», per il team miglioramento) prepara il foglio da stampare. Il QR è sempre al centro e porta al modulo pubblico."),
                ("passi", [
                    "Scegli un preset in alto: «Standard», «Sicurezza», «Idee per migliorare», «Essenziale» o uno salvato da voi (★ = predefinito).",
                    "Cambia i testi: «Titolo», «Sottotitolo», «Testo sopra il QR», «Passi (uno per riga, massimo 3)», «Riquadro in basso», «Piè di pagina»; poi «Colori» e «Formato di stampa» (A4 o A3). L'anteprima a destra si aggiorna da sola.",
                    "«Salva preset» aggiorna quello scelto; per tenerlo a parte scrivi un nome e «Salva come nuovo».",
                    "«Scarica PDF» e stampa. «Elimina preset» toglie quello scelto (l'ultimo rimasto non si elimina).",
                ]),
                ("p", "«Dove porta il QR» mostra l'indirizzo codificato. «Indirizzo nel QR» vuoto = indirizzo del portale; cambialo solo se da fuori il modulo si apre con un altro indirizzo. Le locandine già stampate restano col vecchio indirizzo."),
                ("p", "Nel dettaglio di ogni segnalazione «Segnalata da» dice «Anonima», il nome dell'account o il nome scritto («nome dichiarato», non verificato). La foto si apre cliccandola."),
            ],
        },
    ],
    "admin": [
        {
            "id": "team",
            "titolo": "Il team miglioramento",
            "blocchi": [
                ("p", "«⚙ Gestione»: con «Aggiungi» e «Rimuovi» si decide chi fa parte del team (gruppo SMS_TEAM). "
                      "Il team vede tutte le segnalazioni; gli altri solo le proprie e quelle dove sono incaricati. «Salva configurazione»."),
            ],
        },
        {
            "id": "classificare",
            "titolo": "Classificare e gestire",
            "blocchi": [
                ("ul", [
                    "«Classifica» decide se è una segnalazione «SMS Sì» (da comunicare al cliente) o «SMS No».",
                    "Per gli «SMS Sì»: «✉ Apri nel client di posta» prepara la mail al cliente; poi «Segna come comunicato».",
                    "«Modifica» (solo team) corregge reparti, persone e testi: ogni correzione resta nello storico.",
                    "L'assistente AI può proporre la classificazione, una bozza di PLAN e le segnalazioni simili: propone, non decide.",
                ]),
                ("p", "Solleciti ed escalation di DO e CHECK partono da soli dal servizio automazioni."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il QR della locandina non apre la pagina dal telefono",
            "perche": "il telefono non raggiunge l'indirizzo stampato, oppure l'indirizzo è cambiato dopo la stampa.",
            "fare": [
                "«Locandine QR» → «Dove porta il QR»: controlla l'indirizzo e aprilo dal telefono fuori dalla rete aziendale.",
                "Se va corretto, salva il nuovo «Indirizzo nel QR» e ristampa le locandine.",
            ],
        },
        {
            "sintomo": "La foto non viene accettata",
            "perche": "formato diverso da JPG, PNG o WEBP, oltre 15 MB o file non leggibile come immagine.",
            "fare": ["Scatta di nuovo dalla fotocamera o invia senza foto."],
        },
        {
            "sintomo": "Il modulo pubblico risponde «Troppe richieste»",
            "perche": "c'è un limite di invii per indirizzo e un limite generale di 50 invii all'ora contro lo spam.",
            "fare": ["Attendi un'ora e riprova, oppure invia la segnalazione dal portale con il tuo account."],
        },
        {
            "sintomo": "Un membro del team non vede tutte le segnalazioni",
            "fare": [
                "«⚙ Gestione»: controlla che sia nell'elenco del team.",
                "Falle uscire e rientrare nel portale.",
            ],
        },
    ],
}
