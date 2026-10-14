GUIDA = {
    "slug": "automazioni",
    "titolo": "Automazioni",
    "area": "Amministrazione del portale",
    "sintesi": "Le regole che mandano mail, approvazioni e avvisi da sole quando succede qualcosa nei moduli.",
    "parole": "automazione automazioni regola regole mail approvazione flusso power automate coda",
    "url": "automazioni:automazioni_rule_list",
    "prefissi": ("/automazioni/",),
    "uso": [
        {
            "id": "cosa",
            "titolo": "Cosa sono",
            "blocchi": [
                ("p", "Le automazioni sono regole del tipo «quando succede X, fai Y»: per esempio «quando arriva una richiesta "
                      "di ferie, manda la mail al capo». Chi usa il portale non deve fare niente: le regole lavorano da sole."),
                ("p", "Se ricevi una mail di approvazione con i pulsanti Approva / Rifiuta, il collegamento è personale: "
                      "non inoltrarlo ad altri."),
            ],
        },
    ],
    "admin": [
        {
            "id": "regole",
            "titolo": "Le regole",
            "blocchi": [
                ("ul", [
                    "«Regole»: l'elenco di tutte le regole con lo stato (attiva / non attiva). Il codice (es. AU51) è citato nelle guide dei moduli.",
                    "Una regola ha: la sorgente (cosa la fa partire), le condizioni (quando) e le azioni (cosa fa).",
                    "Le regole importate dai pacchetti nascono in bozza e spente: vanno controllate e attivate a mano.",
                    "«Test» esegue la regola su un record vero o di esempio senza scrivere niente: usalo sempre prima di attivare.",
                ]),
            ],
        },
        {
            "id": "runlog",
            "titolo": "Vedere cosa è successo (run log)",
            "blocchi": [
                ("passi", [
                    "Apri il run log delle automazioni.",
                    "Filtra per regola o per «Sorgente» (i lavori di sistema compaiono come «Sistema: …»).",
                    "Apri un'esecuzione: vedi per ogni azione l'esito e l'eventuale errore.",
                    "«Ripeti» riapre il test della regola con gli stessi dati, per riprovare dopo aver corretto.",
                ]),
                ("p", "I run log più vecchi di 90 giorni si cancellano da soli (dati personali)."),
            ],
        },
        {
            "id": "pianificati",
            "titolo": "Lavori pianificati",
            "blocchi": [
                ("p", "«Pianificati» elenca i lavori che girano a orari fissi (sincronizzazioni, promemoria, pulizie): si accendono, "
                      "si spengono e per quelli con mail si configura il testo. Lo stato di salute di ognuno è in "
                      "Amministrazione → Monitoring → «Salute degli schedule»."),
                ("nota", "Tutte le automazioni e i lavori pianificati girano nel servizio «qcluster» sul server. Se è fermo, "
                         "non parte niente: vedi il Manuale di emergenza."),
            ],
        },
        {
            "id": "trigger",
            "titolo": "Trigger SQL",
            "blocchi": [
                ("p", "Alcune sorgenti (per esempio la tabella delle assenze) usano trigger sul database che mettono gli eventi nella coda. "
                      "Il «Trigger generator» li crea; dopo un'installazione nuova si applicano con il comando apply_sql_triggers."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una mail automatica non è partita",
            "fare": [
                "Apri il run log e cerca l'esecuzione della regola nell'ora giusta.",
                "Se non c'è nessuna esecuzione: la regola è spenta, oppure le condizioni non erano vere, oppure il qcluster è fermo.",
                "Se c'è un errore nell'azione di invio mail: leggi il messaggio (indirizzo sbagliato, server di posta non raggiungibile).",
                "Se nessuna mail del portale parte: Manuale di emergenza → «Le mail non partono».",
            ],
        },
        {
            "sintomo": "Mail doppie",
            "perche": "di solito sono due regole attive sullo stesso evento, oppure due qcluster accesi insieme.",
            "fare": [
                "Nel run log controlla se le due mail vengono da due regole diverse: spegnine una.",
                "Se vengono dalla stessa regola, sul server controlla che ci sia un solo qcluster (Manuale di emergenza).",
            ],
        },
        {
            "sintomo": "Eventi fermi in coda",
            "fare": [
                "Gli eventi rimasti «in lavorazione» oltre 15 minuti tornano in coda da soli; dopo 5 tentativi vanno in errore.",
                "Dalla pagina della coda puoi «Stoppa» o «Elimina» un evento bloccato.",
                "Controlla che il qcluster stia girando.",
            ],
        },
    ],
}
