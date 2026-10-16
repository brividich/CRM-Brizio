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
                    "persona» metti in copia altri colleghi presenti in anagrafica.",
                    "Invia: il capocommessa riceve la mail e decide dal portale o dal collegamento nella mail.",
                    "Nel portale e nella pagina della mail «Applica la stessa decisione anche alle altre … anomalie aperte "
                    "di questi seriali» copia la decisione su tutto il blocco.",
                ]),
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
                    "La mail al capocommessa parte una sola volta, a fine controllo; dopo 15 minuti dall'ultimo "
                    "salvataggio senza invio il controllore riceve un promemoria (notifica + mail con riepilogo), dopo 4 "
                    "ore parte da sola.",
                    "La mail del controllo la spedisce il modulo stesso: al capocommessa dell'OP, con il CAR in copia "
                    "più le persone che l'operatore aggiunge (solo dall'anagrafica, con email di notifica, max 10). "
                    "Tutte le mail del modulo stanno in Configurazione → Notifiche: quando partono, chi le riceve, "
                    "interruttori, orari, liste di destinatari fissi e indirizzo della mail «nuova anomalia fuori da "
                    "un controllo». La stessa vista è in Automazioni → Notifiche di sistema: un dato solo, due pagine.",
                    "La vecchia regola Automazioni «AU-MAIL-ANOMALIE anomalia modificata» è spenta: il riepilogo "
                    "delle modifiche lo manda il modulo, 5 minuti dopo l'ultima modifica sull'OP.",
                ]),
            ],
        },
    ],
    "problemi": [
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
            "sintomo": "Il collegamento nella mail dice che non è più valido",
            "perche": "i collegamenti sono monouso e scadono.",
            "fare": ["Il capocommessa può decidere dal portale, aprendo l'OP in Gestione anomalie."],
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
