GUIDA = {
    "slug": "procedure_refresh",
    "titolo": "Presa visione procedure",
    "area": "Qualità e sistema di gestione",
    "sintesi": "Le procedure aziendali (MT, MTSI) da leggere e confermare, con sessioni, scadenze e report per gli audit.",
    "parole": "procedura procedure presa visione lettura mt mtsi sgi revisione quiz",
    "url": "procedure_refresh:my_assignments",
    "prefissi": ("/procedure-refresh/",),
    "uso": [
        {
            "id": "leggere",
            "titolo": "Leggere una procedura assegnata",
            "blocchi": [
                ("passi", [
                    "Apri Presa visione procedure: si apre «Le mie letture».",
                    "Clicca la procedura da leggere. «Scadute» mostra quelle oltre la data.",
                    "Clicca «↗ Apri documento SharePoint» e leggi il documento.",
                    "Torna nella pagina e conferma la lettura.",
                    "Se c'è un quiz, rispondi e clicca «Invia quiz».",
                ]),
                ("p", "Se trovi un errore o qualcosa da migliorare nella procedura scrivilo e clicca «Invia segnalazione»: arriva a chi gestisce i documenti."),
            ],
        },
        {
            "id": "bacheca",
            "titolo": "Consultare le procedure in qualunque momento",
            "blocchi": [
                ("p", "Tutte le procedure correnti (tranne quelle riservate) sono anche nella Bacheca della home, categoria «Procedure SGI»."),
            ],
        },
    ],
    "admin": [
        {
            "id": "documenti",
            "titolo": "Documenti e revisioni",
            "blocchi": [
                ("ul", [
                    "«Documenti»: «+ Nuovo documento» crea la procedura con codice e tipo (MT, MTSI, ALTRO); «+ Rev.» aggiunge una revisione.",
                    "«Marca PV» / «Smarca PV» segna se il documento richiede la presa visione.",
                    "La sincronizzazione notturna con la cartella SGI (ore 03:00) aggiorna da sola le revisioni e segnala «nuova Rev.». "
                    "In «Impostazioni» c'è anche «Sincronizza ora». Ogni cambiamento finisce in «Log sync».",
                ]),
            ],
        },
        {
            "id": "sessioni",
            "titolo": "Far leggere una procedura (sessioni)",
            "blocchi": [
                ("passi", [
                    "Apri «Sessioni» e clicca «+ Nuova sessione»: titolo e scadenza, poi «Salva sessione».",
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
            "sintomo": "Una nuova revisione non compare",
            "fare": [
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
