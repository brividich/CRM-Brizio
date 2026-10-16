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
                    "L'invio delle mail può essere a ogni blocco o unico a fine controllo.",
                    "La mail del controllo la spedisce il modulo stesso: al capocommessa dell'OP, con il CAR in copia. "
                    "Gli altri destinatari fissi (conferma aggiornamenti, RDC / segnalazione cliente, supervisori) "
                    "si impostano in Configurazione → Liste, non in Automazioni.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il capocommessa non riceve la mail",
            "fare": [
                "Automazioni → «Regole»: controlla che la regola AU51 sia attiva.",
                "Automazioni → run log: cerca l'esecuzione e leggi l'errore.",
                "Controlla l'email di notifica del capocommessa in Anagrafica.",
                "Se nessuna mail del portale parte, Manuale di emergenza → «Le mail non partono».",
            ],
        },
        {
            "sintomo": "Il collegamento nella mail dice che non è più valido",
            "perche": "i collegamenti sono monouso e scadono.",
            "fare": ["Il capocommessa può decidere dal portale, aprendo l'OP in Gestione anomalie."],
        },
    ],
}
