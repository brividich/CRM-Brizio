GUIDA = {
    "slug": "procedure_refresh",
    "titolo": "CN-SGI · Procedure",
    "area": "Qualità e sistema di gestione",
    "sintesi": "La libreria delle procedure del sistema di gestione integrato (manuali, MT, MTSI, modelli, piani qualità): scaffali, ricerca nel testo, chi vede cosa e presa visione.",
    "parole": "cn-sgi sgi libreria procedura procedure presa visione lettura mt mtsi mod modelli manuale revisione ricerca scaffale piano qualità 9100 27001 45001 refresh",
    "url": "procedure_refresh:libreria",
    "prefissi": ("/procedure-refresh/",),
    "uso": [
        {
            "id": "libreria",
            "titolo": "Trovare una procedura",
            "blocchi": [
                ("passi", [
                    "Apri «CN-SGI» dal menu oppure da Sapere.",
                    "Scrivi nella ricerca un codice, un titolo o una frase (il tasto «/» ci porta il cursore), oppure clicca la copertina di uno scaffale.",
                    "Nello scaffale scegli la sezione a sinistra; «Copertine» o «Elenco» cambiano la vista.",
                    "Clicca un documento: la scheda si apre a destra. «Apri il PDF ↗» apre la revisione in vigore.",
                ]),
                ("p", "Nei risultati della ricerca «§ … · pag. N ↗» apre il PDF alla pagina dove c'è la parola cercata. Si vede solo la revisione in vigore; l'archivio SUPERATO non è mostrato."),
            ],
        },
        {
            "id": "leggere",
            "titolo": "Leggere una procedura assegnata",
            "blocchi": [
                ("passi", [
                    "In «CN-SGI» guarda la fila «Da leggere per te», oppure apri «Le mie letture».",
                    "Apri la procedura e leggi il documento.",
                    "Torna nella pagina della lettura e conferma.",
                    "Se c'è un quiz, rispondi e clicca «Invia quiz».",
                ]),
                ("p", "Se trovi un errore o qualcosa da migliorare apri la scheda del documento, scheda «Segnala», e clicca «Invia la segnalazione»: arriva a chi gestisce CN-SGI."),
            ],
        },
        {
            "id": "bacheca",
            "titolo": "Le procedure in Bacheca e in Sapere",
            "blocchi": [
                ("p", "Le procedure aperte a tutti sono anche nella Bacheca della home, categoria «CN-SGI · Procedure». Nella stanza Sapere ci sono la copertina di CN-SGI, le nuove revisioni e la ricerca."),
            ],
        },
    ],
    "admin": [
        {
            "id": "visibilita",
            "titolo": "Chi vede cosa",
            "blocchi": [
                ("passi", [
                    "Apri «Chi vede cosa».",
                    "Scegli lo scaffale e, se serve, una sezione o un documento.",
                    "In «Chi vede» scegli «Solo i ruoli scelti» e spunta i ruoli, oppure «Solo chi gestisce CN-SGI».",
                    "Clicca «Salva la regola». «Togli» la cancella.",
                ]),
                ("p", "Vince la regola più precisa (documento, sezione, scaffale); senza regole il documento è di tutti. I documenti riservati non compaiono in Bacheca e l'assistente AI non li cita. "
                      "In «Scaffali» si cambiano nome, sigla, colore e ordine delle copertine e si collega la certificazione (scadenza e sorveglianza sulla copertina)."),
            ],
        },
        {
            "id": "collegamenti-audit",
            "titolo": "Collegamenti ai moduli e pacchetto audit",
            "blocchi": [
                ("ul", [
                    "«Collegamenti ai moduli»: conferma le proposte o collega a mano un documento a un modulo dell'HUB; la procedura compare come etichetta «SGI» in alto a destra sulle pagine del modulo. «Si compila nell'HUB» aggiunge il pulsante sulla scheda del modello MOD.",
                    "«Pacchetto audit» (da uno scaffale): revisioni in vigore, processi e prese visione per certificazione, con «Scarica Excel».",
                ]),
            ],
        },
        {
            "id": "documenti",
            "titolo": "Documenti e revisioni",
            "blocchi": [
                ("ul", [
                    "«Documenti»: «+ Nuovo documento» crea la procedura con codice e tipo (MT, MTSI, ALTRO); «+ Rev.» aggiunge una revisione.",
                    "«Marca PV» / «Smarca PV» segna se il documento richiede la presa visione.",
                    "Ogni ora il portale controlla nomi, dimensioni e date dei file della cartella SGI e, se qualcosa è cambiato, sincronizza; "
                    "di notte (ore 03:00) fa la lettura completa. Le revisioni nuove hanno «NUOVA REV.». La cartella non viene mai modificata. "
                    "In «Impostazioni» c'è anche «Sincronizza ora». Ogni cambiamento finisce in «Log sync».",
                ]),
            ],
        },
        {
            "id": "sessioni",
            "titolo": "Far leggere una procedura (richieste di presa visione)",
            "blocchi": [
                ("passi", [
                    "Apri «Richieste di presa visione» e clicca «+ Nuova sessione»: titolo e scadenza, poi «Salva sessione».",
                    "Aggiungi i documenti da leggere.",
                    "Assegna le persone: ricevono tutti i documenti della sessione.",
                    "Clicca «Pubblica». Le persone ricevono una notifica.",
                    "A fine periodo clicca «Chiudi sessione».",
                ]),
                ("p", "Ogni mattina alle 06:45 il portale segna le letture scadute e, se i promemoria sono accesi, manda solleciti e il riepilogo ai gestori."),
            ],
        },
        {
            "id": "report",
            "titolo": "Report per gli audit",
            "blocchi": [
                ("ul", [
                    "«Report»: per utente, per documento, per sessione e «Matrice» (completamento per reparto).",
                    "«Export CSV audit» scarica le evidenze.",
                    "«Segnalazioni»: le proposte di modifica dei lettori, da portare a «in carico», «recepita» o «respinta».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": 'Una presa visione risulta «scaduta» prima che arrivi il sollecito',
            "fare": [
                'I contatori «Scadute» contano subito le assegnazioni da leggere con la scadenza passata; lo stato sulla riga diventa «Scaduta» con il controllo delle 06:45. Il filtro «Scadute» segue il contatore.',
            ],
        },
        {
            "sintomo": "Un documento non compare nella libreria",
            "fare": [
                "Apri «Chi vede cosa»: una regola può riservarlo ad alcuni ruoli.",
                "In «Scaffali» controlla che lo scaffale abbia «Mostrato» spuntato.",
                "Se il documento è segnato come sensibile (escluso dall'AI) lo vede solo chi gestisce CN-SGI.",
            ],
        },
        {
            "sintomo": "La ricerca apre il PDF alla pagina sbagliata",
            "fare": [
                "I testi estratti prima di CN-SGI non hanno l'inizio delle pagine: la pagina è stimata. Lancia una volta `manage.py sgi_estrai_testi --forza`.",
            ],
        },
        {
            "sintomo": "Una nuova revisione non compare",
            "fare": [
                "Controlla in alto a destra «Controllata alle …»: se è vecchia, la sincronizzazione automatica è spenta in Impostazioni.",
                "Apri «Log sync» e guarda l'ultima sincronizzazione.",
                "Clicca «Sincronizza ora» in Impostazioni.",
                "Controlla che il file sia nella cartella SGI con il nome nel formato atteso (codice e revisione).",
                "Il server legge la cartella con l'utente del servizio: se quell'utente non vede il file, il portale non lo trova.",
            ],
        },
        {
            "sintomo": "Non partono i solleciti",
            "fare": [
                "Controlla in Impostazioni che i promemoria siano attivi.",
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla il lavoro delle scadenze delle procedure.",
                "Controlla che i destinatari abbiano l'email di notifica in Anagrafica.",
            ],
        },
    ],
}
