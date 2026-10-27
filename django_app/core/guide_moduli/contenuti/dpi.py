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
                ("ul", [
                    "Nuova richiesta: mail al responsabile del dipendente (capo dell'area o caporeparto), ai co-responsabili e al "
                    "preposto dell'area. Se nessuno di loro ha un'email di notifica, va agli indirizzi di ripiego «dpi_car_emails».",
                    "Con la spunta «Email ai referenti (responsabili + email aggiuntive) per ogni nuova richiesta» la mail va "
                    "anche ai «Responsabili» e alle «Email notifiche aggiuntive» delle Impostazioni.",
                    "Richiesta approvata: avviso di consegna a Magazzino e Amministrazione.",
                    "Richiesta rifiutata dopo l'approvazione: mail «Consegna annullata» a Magazzino e Amministrazione, così non "
                    "consegnano.",
                    "Consegna registrata: report all'Amministrazione con il PDF del modulo di consegna.",
                    "Il dipendente riceve la notifica nel portale (campanella) ad approvazione, rifiuto e consegna.",
                ]),
                ("p", "Gli indirizzi si scrivono in DPI → Impostazioni, uno per riga. Salva con «Salva impostazioni»."),
            ],
        },
        {
            "id": "magazzino",
            "titolo": "Magazzino e scorte",
            "blocchi": [
                ("ul", [
                    "«Magazzino»: la giacenza di ogni modello è la somma dei movimenti. «Carica a magazzino» registra un arrivo (DDT); "
                    "la consegna scarica da sola; «Imposta giacenza» corregge dopo un inventario.",
                    "«Leggi un DDT»: scegli il PDF o la foto del DDT e premi «Leggi il DDT». Il portale propone numero, data e fornitore "
                    "e una riga per ogni codice DPI del catalogo che trova nel documento, con la quantità letta sulla stessa riga "
                    "(«da controllare» se non l'ha letta con sicurezza). Spunta le righe giuste, correggi le quantità e premi "
                    "«Carica le righe spuntate». I codici che non sono nel catalogo non vengono proposti: caricali a mano.",
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
                    "Gestire (consegne, magazzino, catalogo, impostazioni): ruoli RSPP e Amministrazione.",
                    "Approvare: caporeparto e preposti, solo per i loro dipendenti (team dell'organigramma).",
                    "Si assegnano in Amministrazione → «Accessi» o in «Ruoli e permessi».",
                ]),
            ],
        },
        {
            "id": "scadenze",
            "titolo": "Promemoria delle scadenze",
            "blocchi": [
                ("p", "Ogni mattina alle 07:10 il task «dpi_expiry_reminders» controlla le consegne scadute o che scadono entro 30 "
                      "giorni (le consegne già sostituite da una nuova non contano)."),
                ("ul", [
                    "Referenti DPI («Responsabili» + «Email notifiche aggiuntive» delle Impostazioni) e indirizzi del task in "
                    "Automazioni → Task pianificati → «Configura mail»: ogni mattina l'elenco completo. Se non c'è nessun indirizzo, "
                    "va agli amministratori del portale.",
                    "Responsabile e preposto del dipendente: una mail con i DPI della propria squadra, solo nei giorni di avviso.",
                    "Dipendente: notifica nel portale, solo nei giorni di avviso.",
                    "Giorni di avviso: 30 giorni prima, 7 giorni prima, il giorno prima, il giorno della scadenza; se è scaduto, il "
                    "giorno dopo e poi ogni 7 giorni finché non viene sostituito.",
                ]),
                ("p", "A mano: comando send_dpi_expiry_reminders, prima con --dry-run."),
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
            "sintomo": "Un responsabile non riceve i promemoria delle scadenze della sua squadra",
            "perche": "arriva solo nei giorni di avviso e solo se il responsabile ha l'email di notifica nella sua scheda.",
            "fare": [
                "Controlla che il dipendente sia nell'area giusta (il responsabile è quello che approva le sue richieste).",
                "Controlla l'email di notifica nella scheda anagrafica del responsabile.",
                "Prova il comando send_dpi_expiry_reminders --dry-run: elenca i responsabili che riceverebbero la mail.",
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
