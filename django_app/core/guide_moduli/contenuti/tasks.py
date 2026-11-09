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
            "id": "guida-completa",
            "titolo": "La guida completa del modulo",
            "blocchi": [
                ("p", "Dentro il modulo, «? Guida» apre la guida completa con le immagini, sulla pagina in cui ti trovi. Da lì ci sono le due guide rapide (chi gestisce la commessa, chi partecipa) e «Scarica PDF»."),
            ],
        },
        {
            "id": "creare",
            "titolo": "Creare un KICK-OFF",
            "blocchi": [
                ("passi", [
                    "Apri KICK-OFF e clicca «+ Nuovo kickoff».",
                    "Compila cliente e P/N: il nome viene proposto da solo (Cliente · P/N · KICK-OFF numero). Lascia vuoto il nome per usare la proposta.",
                    "Scegli il team: PM, capo commessa, programmatore, caporeparto (anche più persone per ruolo). Basta un referente per creare, ma per risultare pronta la commessa vuole PM, capo commessa e programmatore.",
                    "Salva con «Crea kickoff e convoca il primo incontro»: nasce l'incontro 1 e si apre la sua convocazione.",
                    "Dati e team si correggono poi da «Modifica kickoff» nella Panoramica.",
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
                ("p", "Il link «Correggi» accanto a ogni voce porta a dove si sistema; il team si cambia da «Modifica kickoff»."),
                ("p", "Il file VRF già pronto si carica con «Carica file esistente»: il portale legge da solo P/N, descrizione, cliente, preventivo e versione."),
                ("p", "In alternativa «Compila VRF online»: per i 9 rischi scegli la Probabilità (1-3 o N/A), la Gravità è quella del modulo; "
                      "R = P × D e il Totale Rischio è la somma (Basso fino a 35, Medio tra 35 e 50, Alto da 50: coinvolgimento CEO). "
                      "Si aggiungono fino a 4 azioni correttive e le firme IN1 / EM; «Conferma e genera xlsx» crea il file."),
                ("nota", "Dopo 7 giorni senza VRF compare un avviso; dopo 30 giorni non si possono più creare o modificare attività finché non lo carichi."),
            ],
        },
        {
            "id": "attivita-rapide",
            "titolo": "Creare attività al volo",
            "blocchi": [
                ("def", [
                    ("Nel Piano", "la riga sopra il Gantt: titolo, responsabile, Inizio, Fine, «Aggiungi»."),
                    ("Dettaglio ed esito dell'incontro", "«Attività di questo incontro»: scrivi il titolo e premi Invio; la pagina non si ricarica."),
                    ("Conduci incontro", "«Cattura rapida», sempre visibile in fondo allo schermo, con tipo Attività; o «+ Nuova attività» sul punto per collegarla al punto. Le attività entrano nel Piano, azioni e problemi rientrano nell'ordine del giorno del prossimo incontro, le decisioni nel registro di commessa."),
                ]),
                ("p", "L'inizio proposto è il giorno dopo l'ultima fine in piano. «Più opzioni» apre tipo, priorità e attrezzatura."),
            ],
        },
        {
            "id": "incontri",
            "titolo": "Gli incontri: prima la convocazione, poi l'esito",
            "blocchi": [
                ("passi", [
                    "«+ Nuovo incontro»: data, ora, sala, partecipanti e ordine del giorno. L'ordine del giorno si precompila con i problemi aperti.",
                    "Clicca «Invia convocazione» (o spunta l'invio nel form prima di salvare): parte la mail con l'invito da aggiungere al calendario. "
                    "Il dettaglio dice quando è partita; se dopo cambi data, luogo, convocati o ordine del giorno compare «Convocazione da reinviare», con l'elenco di cosa è cambiato. "
                    "L'evento in calendario dura quanto la somma dei punti all'ordine del giorno (un'ora se nessun punto ha una durata).",
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
                    ("Portfolio", "le commesse in card, board per fase (Bozza, VRF, In esecuzione, Completata) o timeline. Ogni card mostra l'avanzamento (attività completate sul totale, annullate escluse, come in Panoramica e nel Gantt) e la prossima scadenza fra le attività aperte («In ritardo di N gg» se è passata)."),
                    ("Da gestire", "VRF mancanti, commesse non pronte, attività critiche, incontri con problemi aperti. «Le mie» filtra su di te."),
                    ("Calendario / Incontri", "tutti gli incontri del mese o in elenco, con i filtri per commessa, esito/minuta e prossimi 7 giorni."),
                    ("Percorso del kickoff", "in Panoramica e nell'incontro: Arrivo materiali, Programma CAM, Programma CMM, Macchina, Terzista, Processi speciali, FAI. «Assegna» crea l'attività con responsabile e data; «Non serve» la toglie dal conteggio. Per la macchina mostra abilitati della skill matrix, assenze nel periodo e manutenzioni o verifiche dell'asset."),
                    ("Programmi e FAI", "scheda della commessa con codici e percorsi di rete di programmi CAM, programmi CMM e FAI, ognuno col suo responsabile. Si compila anche dentro l'incontro. Una riga con responsabile diventa un'attività del kickoff (tipo «Programmazione CAM», «Programmazione CMM» o «Esecuzione FAI»): chi la riceve ha notifica e mail e la porta avanti dalla scheda dell'attività."),
                    ("Programmi", "tutti i programmi CAM e CMM delle commesse, con cartella, responsabile e stato. L'attività di programmazione CAM o CMM chiede il suo programma e la riga nasce da sola; il legame si imposta nel tipo attività, campo «Richiede»."),
                    ("Report FAI", "articoli per situazione e per cliente, FAI per stato e per anno; file Excel e PDF di scadenze, controllo trimestrale, situazione, riepilogo per cliente e tutti i FAI (solo Excel)."),
                    ("Registro FAI", "qui si gestiscono tutti i FAI, importati dal file Situazione FAI-ISIR con «importa_situazione_fai»: la scheda «Tutti i FAI» ha una riga per FAI, l'altra una riga per articolo con il FAI più recente: propone FAI completo o Delta FAI secondo la MT CN 15 e segnala gli articoli da ripetere e quelli da segnalare. La proposta non è un obbligo: in «Programmi e FAI» chi gestisce il kickoff può segnarlo «Non richiesto per questo kickoff». Motivi, piani, stati e mesi si configurano in Impostazioni, scheda «FAI». Il campo OP della scheda propone gli OP dell'elenco unico di Gestione anomalie e mostra le anomalie dell'OP scelto."),
                    ("Le mie azioni", "tutto quello assegnato a te: attività del piano, azioni, problemi, programmi e FAI. Un'attività la prendi in carico con «Inizia» e la chiudi con «Fatta». Chi riceve un'attività ha la notifica nel portale e una mail che porta qui; il lunedì la mail «Scadenze KICK-OFF» elenca anche le attività scadute e quelle in scadenza."),
                    ("Registro azioni", "dalla commessa: problemi, azioni d'incontro, attività e sotto-attività in un solo elenco, filtrabile per tipo, responsabile e scadenza."),
                    ("Gantt", "le attività come barre: trascina il centro per spostarle, i bordi per allungarle; clic sulla riga per cambiare date, stato e avanzamento. Sotto ogni nome: responsabile, date, assenze e scostamento dalla baseline. Sul piano compaiono anche gli incontri (riga «Incontri», cerchi viola) e le scadenze aperte di azioni, problemi, programmi e FAI: sulla riga dell'attività collegata o in fondo, con un rombo sulla data."),
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
                "Compila la scheda dalla voce VRF della commessa, oppure caricane il file: resta possibile anche a kickoff bloccato.",
                "Se il VRF non serve, segnalo come «non richiesto».",
            ],
        },
        {
            "sintomo": "«Conferma e genera xlsx» non crea il file VRF",
            "fare": [
                "Il messaggio elenca i rischi senza Probabilità («Mancano: R…»): sceglila per tutti i 9, N/A se il rischio non si applica.",
                "La bozza resta salvata: non si perde niente.",
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
