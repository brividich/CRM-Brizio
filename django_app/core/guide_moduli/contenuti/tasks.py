GUIDA = {
    "slug": "tasks",
    "titolo": "KICK-OFF",
    "area": "Produzione e operations",
    "sintesi": "L'avvio delle commesse: VRF, team, incontri con convocazione e minuta, attività e Gantt.",
    "parole": "kickoff kick-off commessa progetto vrf incontro riunione minuta convocazione attivita task gantt",
    "url": "tasks:project_list",
    "prefissi": ("/tasks/",),
    "uso": [
        {
            "id": "creare",
            "titolo": "Creare un KICK-OFF",
            "blocchi": [
                ("passi", [
                    "Apri KICK-OFF e clicca «+ Nuovo kickoff».",
                    "Compila cliente e P/N: il nome viene proposto da solo (Cliente · P/N · KICK-OFF numero). Lascia vuoto il nome per usare la proposta.",
                    "Scegli il team: PM, capo commessa, programmatore, caporeparto (anche più persone per ruolo).",
                    "Salva. Nasce in automatico l'incontro 1 e si apre la sua convocazione.",
                ]),
            ],
        },
        {
            "id": "pronto",
            "titolo": "Quando una commessa è pronta a partire",
            "blocchi": [
                ("p", "Il semaforo nella testata della commessa controlla quattro cose:"),
                ("ul", [
                    "VRF (MOD.073) caricato, o segnato come non richiesto;",
                    "incontro di kickoff svolto (non solo pianificato);",
                    "team assegnato: almeno un PM, un capo commessa e un programmatore;",
                    "piano attività con le scadenze.",
                ]),
                ("p", "Il VRF si carica dalla scheda VRF della commessa: il portale legge da solo P/N, descrizione, cliente, preventivo e versione."),
                ("nota", "Dopo 7 giorni senza VRF compare un avviso; dopo 30 giorni non si possono più creare o modificare attività finché non lo carichi."),
            ],
        },
        {
            "id": "incontri",
            "titolo": "Gli incontri: prima la convocazione, poi l'esito",
            "blocchi": [
                ("passi", [
                    "«+ Nuovo incontro»: data, ora, sala, partecipanti e ordine del giorno. L'ordine del giorno si precompila con i problemi aperti.",
                    "Clicca «Invia convocazione» (o spunta l'invio nel form prima di salvare): parte la mail con l'invito da aggiungere al calendario. "
                    "Il dettaglio dice quando è partita; se dopo cambi data, luogo, convocati o ordine del giorno compare «Convocazione da reinviare».",
                    "Durante la riunione puoi usare «Conduci incontro»: appello dei convocati, un punto alla volta, con il tempo e le note.",
                    "Dopo la riunione registra l'esito: presenti, note per ogni punto, decisioni e azioni (chi fa cosa entro quando).",
                    "Clicca «Invia minuta» (o «Scarica minuta PDF»).",
                    "Quando è tutto giusto: «Approva e chiudi minuta». Riaprirla richiede un motivo.",
                    "«Pianifica prossimo incontro» crea il successivo con gli stessi convocati, persone in copia, luogo e ora.",
                ]),
                ("nota", "Un incontro che non si tiene si annulla con «Annulla incontro»: serve il motivo, l'evento Outlook viene tolto e i convocati avvisati. "
                         "Si eliminano solo gli incontri mai svolti e senza decisioni."),
            ],
        },
        {
            "id": "viste",
            "titolo": "Dove guardare",
            "blocchi": [
                ("def", [
                    ("Portfolio", "le commesse in card, board per fase (Bozza, VRF, In esecuzione, Completata) o timeline."),
                    ("Da gestire", "VRF mancanti, commesse non pronte, attività critiche, incontri con problemi aperti. «Le mie» filtra su di te."),
                    ("Calendario / Incontri", "tutti gli incontri del mese o in elenco, con i filtri per commessa, esito/minuta e prossimi 7 giorni."),
                    ("Le mie azioni", "le azioni e i problemi degli incontri assegnati a te: li chiudi da qui. Quando completi l'attività collegata si chiudono da soli."),
                    ("Registro azioni", "dalla commessa: problemi, azioni d'incontro, attività e sotto-attività in un solo elenco, filtrabile per tipo, responsabile e scadenza."),
                    ("Gantt", "le attività come barre: trascina il centro per spostarle, i bordi per allungarle."),
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "impostazioni",
            "titolo": "Impostazioni del modulo",
            "blocchi": [
                ("p", "KICK-OFF → «Impostazioni», con le schede:"),
                ("def", [
                    ("Configurazione", "giorni di avviso e di blocco del VRF (predefiniti 7 e 30), sale riunioni."),
                    ("Modelli", "modelli di ordine del giorno: un punto per riga, «Titolo | 15» per la durata in minuti."),
                    ("Ruoli operativi e Accessi", "chi vede tutto, chi modifica solo le proprie attività, chi modifica tutto."),
                    ("Promemoria", "i promemoria automatici."),
                    ("Record", "eliminare un kickoff o un'attività: la motivazione è obbligatoria e resta nell'audit."),
                    ("Log attivita", "chi ha fatto cosa."),
                ]),
            ],
        },
        {
            "id": "mail",
            "titolo": "Mail automatiche",
            "blocchi": [
                ("p", "Convocazione e minuta si possono mandare anche in automatico con le regole AU53 e AU52 del modulo Automazioni; "
                      "AU54 avvisa dei progetti con impatto sulla sicurezza, AU55 del VRF non caricato."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona non vede un KICK-OFF",
            "fare": [
                "Controlla che sia nel team della commessa, oppure convocata a un suo incontro.",
                "Controlla i suoi permessi in KICK-OFF → Impostazioni → «Accessi» (o nella matrice «Ruoli e permessi»).",
            ],
        },
        {
            "sintomo": "Non si possono creare attività: «VRF mancante»",
            "fare": [
                "Carica il VRF dalla scheda VRF della commessa.",
                "Se il VRF non serve, segnalo come «non richiesto».",
            ],
        },
        {
            "sintomo": "«Elimina» non compare su un incontro",
            "fare": [
                "Un incontro svolto, o con decisioni registrate, non si elimina: verbale e decisioni sparirebbero.",
                "Se non si è tenuto davvero, riapri la minuta e correggi l'esito; se non si terrà, usa «Annulla incontro».",
            ],
        },
        {
            "sintomo": "L'invito non compare in Outlook",
            "fare": [
                "Controlla che i partecipanti abbiano un'email in Anagrafica.",
                "La casella organizzatrice usata per il calendario deve avere una licenza Exchange: vedi la configurazione Outlook nelle Impostazioni.",
            ],
        },
    ],
}
