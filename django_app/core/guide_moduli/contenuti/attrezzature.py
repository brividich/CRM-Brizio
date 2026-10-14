GUIDA = {
    "slug": "attrezzature",
    "titolo": "Attrezzature",
    "area": "Produzione e operations",
    "sintesi": "Attrezzi per P/N: richiesta, verifica disponibilità, avanzamento fino a «pronta produzione», collegati ai KICK-OFF.",
    "parole": "attrezzatura attrezzature attrezzo pn part number pronta produzione",
    "url": "attrezzature:list",
    "prefissi": ("/attrezzature/",),
    "uso": [
        {
            "id": "elenco",
            "titolo": "Trovare un'attrezzatura",
            "blocchi": [
                ("passi", [
                    "Apri Attrezzature: vedi l'elenco con i filtri.",
                    "Filtra per P/N, stato o commessa e clicca «Filtra». «Reset» toglie i filtri.",
                    "Clicca la riga per aprire la scheda.",
                ]),
            ],
        },
        {
            "id": "avanzamento",
            "titolo": "Far avanzare un'attrezzatura",
            "blocchi": [
                ("p", "Nella scheda trovi i pulsanti del passo successivo:"),
                ("def", [
                    ("Avvia verifica disponibilita", "controllare se l'attrezzo esiste già."),
                    ("Segna disponibile / Segna da creare", "esito della verifica."),
                    ("Aggiorna avanzamento", "a che punto è la costruzione."),
                    ("Blocca con motivo", "fermo per un problema (il motivo è obbligatorio)."),
                    ("Conferma pronta produzione", "l'attrezzo è pronto: chi aspetta nel KICK-OFF viene avvisato."),
                ]),
            ],
        },
        {
            "id": "task",
            "titolo": "I task delle attrezzature",
            "blocchi": [
                ("p", "«Task» elenca i lavori da fare sulle attrezzature: aprili e usa «Completa» oppure «Blocca»."),
            ],
        },
    ],
    "admin": [
        {
            "id": "import",
            "titolo": "Importare da Excel",
            "blocchi": [
                ("passi", [
                    "Clicca «Import Excel» e scegli il file.",
                    "Clicca «Avvia preview» e controlla cosa verrà creato o aggiornato.",
                    "Clicca «Conferma import». Con «Carica un altro file» ricominci.",
                ]),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Permessi",
            "blocchi": [
                ("p", "L'eliminazione (anche multipla con «Elimina selezionate») richiede il permesso «attrezzature.attrezzature.delete» (Amministrazione → Accessi)."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "L'attrezzatura non compare nel KICK-OFF",
            "fare": [
                "Nell'attività del KICK-OFF controlla il campo attrezzatura (collega esistente o richiedi nuovo attrezzo).",
                "Controlla che il P/N sia scritto uguale nei due moduli.",
            ],
        },
    ],
}
