GUIDA = {
    "slug": "dpi",
    "titolo": "DPI",
    "area": "Sicurezza sul lavoro",
    "sintesi": "Dispositivi di protezione individuale: si chiedono, il responsabile approva, il magazzino consegna con firma.",
    "parole": "dpi guanti scarpe occhiali casco protezione consegna firma magazzino taglia",
    "url": "dpi:dashboard",
    "prefissi": ("/dpi/",),
    "uso": [
        {
            "id": "chiedere",
            "titolo": "Chiedere un DPI",
            "blocchi": [
                ("passi", [
                    "Apri DPI e clicca «+ Nuova richiesta».",
                    "In «Richiesta per» lascia «Me stesso». Se sei un responsabile puoi scegliere un tuo dipendente.",
                    "Clicca sulla scheda della categoria (per esempio scarpe, guanti, occhiali).",
                    "Se lo sai, scegli «Tipo DPI», «Modello DPI» e «Taglia DPI». Se non lo sai lascia «Solo categoria»: ci pensa il magazzino.",
                    "Indica la «Quantità» e, se serve, il motivo in «Motivazione / Note».",
                    "Clicca «Invia richiesta». Il numero della richiesta ha la forma DPI-anno-numero.",
                ]),
                ("p", "La richiesta passa per questi stati: creata → approvata → consegnata (oppure rifiutata o annullata)."),
                ("p", "Finché non è approvata puoi ritirarla: apri la richiesta e clicca «Annulla richiesta»."),
            ],
        },
        {
            "id": "storico",
            "titolo": "Vedere i DPI che hai in carico",
            "blocchi": [
                ("p", "«Il mio storico» elenca le consegne fatte a te, con la data di scadenza di ogni DPI."),
                ("ul", [
                    "Il pallino colorato dice se il DPI è in regola, in scadenza o scaduto.",
                    "Quando ricevi un nuovo DPI dello stesso tipo, quello vecchio esce dai conteggi ma resta nello storico.",
                ]),
            ],
        },
        {
            "id": "approvare",
            "titolo": "Approvare e consegnare (responsabili e magazzino)",
            "blocchi": [
                ("passi", [
                    "Apri «Gestione richieste» dalla Dashboard DPI e clicca la richiesta.",
                    "Nel riquadro «Prima di decidere» guarda le consegne precedenti della persona e la media del reparto. "
                    "«Proponi con l'AI» suggerisce una decisione: è solo un consiglio.",
                    "Clicca «Approva» oppure «Rifiuta» (scrivi il motivo). Con «Aggiungi nota» lasci un commento.",
                    "Quando il DPI viene consegnato, il magazzino clicca «Registra consegna», fa firmare il dipendente "
                    "nel riquadro firma e salva. «Cancella firma» ripulisce il riquadro se serve rifarla.",
                ]),
                ("nota", "Nessuno può approvare la propria richiesta. Il responsabile vede solo le richieste dei suoi dipendenti."),
            ],
        },
        {
            "id": "documenti",
            "titolo": "Documenti dei DPI",
            "blocchi": [
                ("p", "«Documenti» raccoglie certificati, attestati e manuali d'uso di ogni DPI del catalogo. Tutti possono "
                      "consultarli; solo i gestori possono caricarli («Carica documenti») o eliminarli."),
            ],
        },
    ],
    "admin": [
        {
            "id": "catalogo",
            "titolo": "Il catalogo DPI",
            "blocchi": [
                ("p", "DPI → «Impostazioni». Il catalogo ha quattro livelli, dal generale al particolare:"),
                ("def", [
                    ("Categoria", "per esempio «Calzature». Ha l'icona, la vita utile in mesi e il flag «obbligatorio da mansionario». «+ Nuova categoria»."),
                    ("Tipo", "sottocategoria, per esempio «Scarpe S3». «+ Nuovo tipo»."),
                    ("Modello", "prodotto preciso con codice, produttore e foto. Se ha una vita utile propria vince su quella della categoria. «+ Nuovo modello»."),
                    ("Taglia", "valore della taglia. «+ Nuova taglia»."),
                ]),
                ("nota", "Cambiando la vita utile di una categoria o di un modello, le scadenze delle consegne in uso si ricalcolano da sole "
                         "(tranne quelle scritte a mano)."),
            ],
        },
        {
            "id": "notifiche",
            "titolo": "Chi viene avvisato",
            "blocchi": [
                ("p", "In Impostazioni si scrivono le email di Magazzino e Amministrazione: ricevono l'avviso quando una richiesta è "
                      "approvata e il report di consegna con il PDF firmato. Salva con «Salva impostazioni»."),
            ],
        },
        {
            "id": "magazzino",
            "titolo": "Magazzino e scorte",
            "blocchi": [
                ("ul", [
                    "«Magazzino»: la giacenza di ogni modello è la somma dei movimenti. «Carica a magazzino» registra un arrivo (DDT); "
                    "la consegna scarica da sola; «Imposta giacenza» corregge dopo un inventario.",
                    "Con la scorta minima il modello diventa «Da riordinare» o «Esaurito».",
                    "«Report e consumi» mostra i consumi per mese, reparto e modello e la quantità suggerita da riordinare; «Esporta movimenti (CSV)».",
                ]),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Permessi",
            "blocchi": [
                ("ul", [
                    "Gestire (consegne, magazzino, catalogo, impostazioni): ruoli Sicurezza e Magazzino.",
                    "Approvare: responsabili e preposti, solo per i loro dipendenti (team dell'organigramma).",
                    "Si assegnano in Amministrazione → «Accessi» o in «Ruoli e permessi».",
                ]),
            ],
        },
        {
            "id": "scadenze",
            "titolo": "Promemoria delle scadenze",
            "blocchi": [
                ("p", "Il comando send_dpi_expiry_reminders avvisa delle consegne in scadenza. Prova prima con --dry-run."),
                ("p", "«Report conformità» mostra per ogni dipendente se ha i DPI obbligatori: OK, scaduto o mancante, con «Esporta Excel»."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il responsabile non vede la richiesta da approvare",
            "perche": "l'approvazione segue il team dell'organigramma (o il preposto del reparto).",
            "fare": [
                "Apri Anagrafica → Organigramma e controlla che il dipendente sia nel team del responsabile.",
                "Controlla che il responsabile abbia il permesso di approvare i DPI (Accessi o Ruoli e permessi).",
                "In alternativa un gestore Sicurezza può approvare dalla «Gestione richieste».",
            ],
        },
        {
            "sintomo": "La data di scadenza di un DPI è sbagliata",
            "fare": [
                "Apri Impostazioni e controlla la vita utile del modello: se è valorizzata vince su quella della categoria.",
                "Correggi e salva: le consegne in uso si riallineano subito.",
                "Se la scadenza era stata scritta a mano nella consegna, va corretta a mano.",
            ],
        },
        {
            "sintomo": "Il magazzino non riceve la mail di consegna",
            "fare": [
                "DPI → Impostazioni: controlla che l'indirizzo email di Magazzino sia scritto bene.",
                "Amministrazione → «Log notifiche» per vedere se la notifica è partita.",
                "Se nessuna mail del portale parte, segui «Le mail non partono» nel Manuale di emergenza.",
            ],
        },
    ],
}
