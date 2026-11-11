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
                    "Clicca un documento: la scheda si apre a destra. «Leggi qui» mostra il PDF nel pannello, «Apri il PDF ↗» in una nuova scheda.",
                    "La stella ☆ mette il documento tra «I miei documenti»; «Cosa cambia» mostra i paragrafi cambiati rispetto alla revisione precedente; «QR» stampa l'etichetta da affiggere in reparto.",
                ]),
                ("p", "La ricerca è flessibile: parole in qualunque ordine, singolare o plurale, con o senza accenti, codici con o senza zeri («MT 6» = MT CN 06); una parola scritta male si corregge da sola. "
                      "Nei risultati «§ … · pag. N ↗» apre il PDF alla pagina dove c'è la parola cercata. Si vede solo la revisione in vigore; l'archivio SUPERATO non è mostrato."),
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
                ("p", "Le procedure aperte a tutti sono anche nella Bacheca della home, categoria «CN-SGI · Procedure». Nella stanza Sapere ci sono la copertina di CN-SGI, le nuove revisioni e la ricerca. "
                      "Le procedure si trovano anche con «Cerca o vai a…» (Ctrl+K), e le fonti dell'assistente AI aprono la scheda nella libreria. "
                      "Nella panoramica di un KICK-OFF c'è il piano qualità del cliente."),
            ],
        },
    ],
    "admin": [
        {
            "id": "modifiche",
            "titolo": "Modifiche ai documenti",
            "blocchi": [
                ("passi", [
                    "Apri «Modifiche» → «Nuova modifica» (o «Avvia una modifica» dalla scheda, da una segnalazione o da «Da rivedere»).",
                    "Scrivi cosa si modifica e perché, scegli chi redige, verifica e approva, spunta le segnalazioni da recepire e clicca «Apri la modifica».",
                    "Chi redige carica la bozza Word e la invia in verifica; chi verifica la passa in approvazione o la rimanda; chi approva firma con «Approva».",
                    "Salva il PDF nella cartella SGI e sposta la revisione vecchia in SUPERATO: al controllo orario la modifica diventa «Emessa», le segnalazioni «Recepita» e parte la rilettura.",
                ]),
                ("p", "«Chi firma cosa» fissa le persone proposte per tipo di documento. Il registro di ogni modifica (chi, ruolo, quando, impronta della bozza) è l'evidenza per gli audit e non si può modificare."),
            ],
        },
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
                      "In «Scaffali» si cambiano nome, sigla, colore, icona, logo e ordine delle copertine e si collega la certificazione (scadenza e sorveglianza sulla copertina)."),
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
                    "Ogni 15 minuti il portale controlla nomi, dimensioni e date dei file della cartella SGI e, se qualcosa è cambiato, importa documenti nuovi, revisioni nuove e file spostati; di notte (ore 03:00) fa la lettura completa. Se qualcosa non si aggiorna, «Impostazioni» → «Sincronizzazione con la cartella SGI» dice quale controllo non va e quali file sono rimasti fuori, con il motivo."
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
                    "«Segnalazioni»: le proposte di modifica dei lettori, da portare a «in carico», «recepita» o «respinta». Le nuove arrivano come notifica a chi gestisce; chi ha segnalato è avvisato a ogni cambio di stato e le segue in «Le mie letture».",
                    "Nuova revisione di un documento già fatto leggere: nella scheda, «Cosa cambia» → «Chiedi la rilettura».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Le procedure non si aggiornano quando cambia la cartella",
            "fare": [
                "Apri «Impostazioni» → «Sincronizzazione con la cartella SGI»: ogni riga con ✕ dice cosa fare (accendere l'interruttore, dare la lettura all'account del sito, lanciare «manage.py setup_q_schedules», riavviare il qcluster).",
                "Apri «File non sincronizzati»: di solito basta correggere il nome del file (codice e «Rev.N») o togliere il doppione dalla cartella.",
                "«Sincronizza ora» fa subito il giro senza aspettare i 15 minuti.",
            ],
        },
        {
            "sintomo": "Una modifica approvata non diventa «Emessa»",
            "fare": [
                "L'HUB la chiude quando la revisione in vigore del documento cambia: controlla che il nuovo PDF sia nella cartella SGI con il numero di revisione nel nome e che la vecchia sia in SUPERATO.",
                "La sincronizzazione oraria deve essere accesa (flag pr_sgi_auto_sync_attivo); in «Impostazioni» c'è «Sincronizza ora».",
                "Per un documento nuovo il codice nella cartella deve essere quello scritto nella modifica (spazi e punti non contano).",
                "Se la revisione è già in libreria, nella modifica usa «Segna come emessa».",
            ],
        },
        {
            "sintomo": "In una modifica «Cosa cambia» non mostra il confronto",
            "fare": [
                "Il confronto usa il testo della bozza e quello estratto dalla revisione in vigore: un file protetto o scansionato non ha testo, e una revisione appena arrivata ha il testo dopo l'estrazione.",
            ],
        },
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
