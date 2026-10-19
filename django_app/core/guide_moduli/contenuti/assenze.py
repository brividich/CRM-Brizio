GUIDA = {
    "slug": "assenze",
    "titolo": "Assenze",
    "area": "Persone e HR",
    "sintesi": "Ferie, permessi, malattia e flessibilità: si chiedono qui, il capo le approva, il calendario le mostra.",
    "parole": "ferie permesso permessi malattia flessibilita calendario approvare capo reparto",
    "url": "assenze_menu",
    "prefissi": ("/assenze/",),
    "uso": [
        {
            "id": "chiedere",
            "titolo": "Chiedere ferie o un permesso",
            "blocchi": [
                ("passi", [
                    "Apri Assenze e clicca «Nuova richiesta» nella barra del modulo.",
                    "In «Tipo assenza» scegli Ferie, Permesso, Malattia, Flessibilità o Altro.",
                    "Scegli le date in «Data inizio» e «Data fine». Per un solo giorno metti la stessa data.",
                    "In «Durata rapida» scegli l'orario già pronto (per esempio «Normale (08:00-17:00)» o "
                    "«Mezza mattina (08:00-12:00)»). Se ti serve un orario diverso scegli «Personalizzato» e scrivi "
                    "«Ora inizio» e «Ora fine».",
                    "Controlla il riquadro «Bozza live» a destra: è il riassunto di quello che stai inviando.",
                    "Clicca «Conferma invio». La richiesta arriva al tuo capo, che riceve una mail.",
                ]),
                ("def", [
                    ("Permesso", "da 30 minuti a 8 ore, sempre nello stesso giorno."),
                    ("Ferie di più giorni", "contano a giornata intera."),
                    ("Flessibilità", "solo per chi è abilitato, solo negli orari fissati dall'Amministrazione, massimo 2 a settimana."),
                    ("Capo reparto", "è proposto in automatico dall'organigramma. Puoi sceglierne un altro dall'elenco: "
                     "in quel caso la richiesta la vede e la approva solo il capo che hai scelto."),
                ]),
                ("nota", "Se l'ora di fine è prima dell'ora di inizio il portale la corregge da solo a inizio + 30 minuti e te lo dice: controlla prima di inviare."),
            ],
        },
        {
            "id": "controllare",
            "titolo": "Vedere se la richiesta è stata approvata",
            "blocchi": [
                ("passi", [
                    "Clicca «Le mie richieste».",
                    "Le schede in alto (In attesa, Approvate, Rifiutate, Tutte) filtrano l'elenco.",
                    "Una richiesta ancora «In attesa» si può correggere con «Modifica» o togliere con «Elimina».",
                ]),
                ("p", "Quando il capo decide ricevi una notifica (campanella in alto) e, se attiva, una mail."),
                ("nota", "Le richieste con l'etichetta «Gestita su SharePoint» sono nate nella vecchia app SharePoint: "
                         "si vedono qui ma si modificano solo là."),
            ],
        },
        {
            "id": "approvare",
            "titolo": "Approvare le richieste dei tuoi dipendenti (capi)",
            "blocchi": [
                ("passi", [
                    "In alto nella barra compare il numero «da approvare»: cliccalo. In alternativa apri «Assenze del reparto».",
                    "In «Richieste in attesa» trovi le richieste da decidere. Puoi filtrare per tipo e per periodo "
                    "(«Inizia oggi», «Entro 7 giorni», «Gia iniziate»).",
                    "Clicca «Approva» per approvare.",
                    "Per rifiutare clicca «Rifiuta», scrivi il motivo e clicca «Conferma rifiuto».",
                ]),
                ("p", "Il dipendente riceve subito l'esito. Le richieste già decise restano in «Le mie richieste» → "
                      "«Richieste dei miei dipendenti», nel blocco «Già decise»."),
                ("p", "Con il sistema «Ruoli e permessi» acceso nessuno approva o rifiuta una propria richiesta, nemmeno "
                      "in blocco o modificando l'evento: compare «Non puoi approvare o rifiutare una tua richiesta» e "
                      "decide un altro responsabile."),
                ("p", "Dalla dashboard del reparto, «Il mio team» apre in Anagrafica l'elenco delle persone di cui sei "
                      "responsabile con il semaforo di conformità alla mansione (nessun dato sanitario)."),
            ],
        },
        {
            "id": "calendario",
            "titolo": "Il calendario",
            "blocchi": [
                ("p", "«Calendario» mostra le assenze approvate con un colore per tipo. Con le frecce cambi mese."),
                ("ul", [
                    "Cosa vedi dipende dal tuo ruolo: tutta l'azienda, solo il tuo reparto oppure solo le tue richieste.",
                    "Vedere le assenze degli altri non vuol dire poterle approvare.",
                ]),
            ],
        },
        {
            "id": "presenza",
            "titolo": "Certificare una presenza",
            "blocchi": [
                ("p", "Serve quando eri al lavoro ma la timbratura manca (per esempio una trasferta)."),
                ("passi", [
                    "Clicca «Certifica presenza».",
                    "Compila data e orari e clicca «Salva certificazione».",
                    "Per correggerla usa «Modifica» nella tabella «Certificazioni registrate».",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "dove",
            "titolo": "Dove si configura",
            "blocchi": [
                ("p", "Tutto è in Assenze → «Impostazioni» (voce visibile solo agli amministratori del modulo)."),
                ("def", [
                    ("Chi vede le assenze altrui", "riepilogo in sola lettura di chi vede tutta l'azienda, solo il reparto o solo le proprie richieste."),
                    ("Flessibilità", "elenco delle persone abilitate e orari ammessi di entrata e uscita (predefiniti 07:00/08:00/09:00 e 16:00/17:00/18:00). Si salva con «Salva flessibilità»."),
                    ("Gestione admin · Tutte le assenze", "tutte le richieste con filtri, ordinamento, approvazione o rifiuto in blocco (fino a 200 alla volta, nota obbligatoria) ed «Export CSV»."),
                    ("Sincronizzazione SharePoint", "coda delle modifiche da mandare alla lista SharePoint, eventuali errori e pulsante «Sincronizza ora»."),
                ]),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Chi vede e chi approva",
            "blocchi": [
                ("ul", [
                    "Il capo proposto è il capo del dipendente in Anagrafica: con la «regola unica capi» accesa "
                    "(pagina Organigramma → Coerenza capi) vale eccezione sulla persona → responsabile dell'area → "
                    "caporeparto del reparto → gerarchia dei ruoli; spenta, responsabile dell'area e poi caporeparto del reparto. "
                    "Si cambia in Anagrafica, non qui.",
                    "Tutti possono scegliere un altro capo nella richiesta. Se lo fanno, la richiesta compare in coda "
                    "e si approva solo dal capo scelto (oltre che dall'Amministrazione); il capo dell'organigramma la vede "
                    "ancora nel calendario ma non la approva.",
                    "La visibilità si assegna in Amministrazione → «Accessi» con i permessi «view_all_assenze» "
                    "(tutta l'azienda) e «view_reparto_assenze» (solo il reparto), a un ruolo o a una singola persona.",
                    "Se il sistema unico «Ruoli e permessi» è acceso, valgono le righe Assenze della matrice (vedere, approvare, esportare).",
                    "Caporeparto e Amministrazione possono inserire richieste per conto di qualsiasi dipendente.",
                ]),
                ("nota", "Un dipendente senza ruoli non vede il calendario: prima assegna il ruolo, poi controlla."),
            ],
        },
        {
            "id": "sharepoint",
            "titolo": "Convivenza con SharePoint",
            "blocchi": [
                ("ul", [
                    "Il lavoro «assenze_sharepoint_sync» gira ogni 5 minuti in background: manda le modifiche del portale "
                    "alla lista SharePoint e legge quelle fatte su SharePoint.",
                    "Ogni richiesta la gestisce il sistema dove è nata: quelle nate su SharePoint le approva il flusso Power Automate.",
                    "Le credenziali Graph e l'ID della lista sono nel file .env (Setup Wizard → Microsoft Graph / SharePoint).",
                ]),
            ],
        },
        {
            "id": "comandi",
            "titolo": "Comandi utili (sul server)",
            "blocchi": [
                ("def", [
                    ("sync_assenze_sharepoint --force", "rilegge tutta la lista SharePoint."),
                    ("import_assenze_xlsx <file> --dry-run", "carica uno storico da Excel; prima prova, poi senza --dry-run."),
                ]),
                ("p", "I comandi si lanciano dal terminale del Setup Wizard (Server Dashboard) o con "
                      "python django_app\\manage.py <comando> nella cartella della release."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "La richiesta va al capo sbagliato",
            "perche": "il capo si ricava dall'Anagrafica, oppure il dipendente ne ha scelto un altro nella richiesta.",
            "fare": [
                "Se il dipendente ha scelto un altro capo, la richiesta va a quello: è voluto (registro «assenza_caporeparto_scelto»).",
                "Apri Anagrafica e cerca il dipendente: controlla «Area aziendale» e «Reparto».",
                "Apri l'area aziendale e controlla il «Responsabile». Se manca, vale il caporeparto del reparto.",
                "Correggi e fai reinviare la richiesta (le richieste già inviate restano al vecchio capo).",
            ],
        },
        {
            "sintomo": "Il capo riceve due mail per la stessa richiesta, o dopo l'approvazione la mailbox assenza@ non riceve nulla",
            "perche": "due regole di approvazione Assenze erano accese insieme; dalla versione successiva alla 1.6.8 "
                      "l'aggiornamento le unisce da solo nella regola «Assenze — approvazione unificata».",
            "fare": [
                "Apri Automazioni → Regole, sorgente Assenze: sull'inserimento deve essere attiva solo «Assenze — approvazione unificata».",
                "Se sono ancora attive «assenze-pa-richiesta-approvazione-caporeparto» e «au-assenze-unico-branch-per-tipo», "
                "lancia sul server merge_assenze_flows (anteprima) e poi con --apply --workers-stopped.",
                "Le richieste approvate prima della correzione possono essere rimaste «In attesa»: approvale da «Gestione admin».",
            ],
        },
        {
            "sintomo": "Un capo non vede le richieste dei suoi dipendenti",
            "fare": [
                "Controlla in Anagrafica che sia il capo del dipendente (Organigramma → Coerenza capi).",
                "Se il dipendente ha scelto un altro capo nella richiesta, la vede e la approva solo quello.",
                "Controlla che abbia un ruolo che apre «Assenze del reparto» (Amministrazione → Accessi, oppure Ruoli e permessi).",
                "Fagli ricaricare la pagina: il conteggio «da approvare» si aggiorna al caricamento.",
            ],
        },
        {
            "sintomo": "Le assenze non arrivano su SharePoint (o da SharePoint)",
            "perche": "la sincronizzazione gira in background con il servizio django-q (qcluster).",
            "fare": [
                "Apri Assenze → Impostazioni → «Sincronizzazione SharePoint» e leggi l'errore della coda.",
                "Apri Amministrazione → Monitoring → «Salute degli schedule» e controlla «assenze_sharepoint_sync».",
                "Se il cluster è fermo segui «Le automazioni non partono» nel Manuale di emergenza.",
                "Se l'errore parla di autorizzazione (401/403) il segreto dell'app Graph è scaduto: rinnovalo su Entra ID e aggiornalo dal Setup Wizard.",
                "Clicca «Sincronizza ora».",
            ],
        },
        {
            "sintomo": "Il dipendente non può chiedere la flessibilità",
            "fare": [
                "Assenze → Impostazioni → «Flessibilità»: aggiungi la persona agli abilitati.",
                "Controlla che sia collegata a un'anagrafica: senza collegamento la richiesta viene rifiutata.",
                "Ricorda i limiti: tra 9 e 10 ore, massimo 2 a settimana, solo negli orari ammessi.",
            ],
        },
    ],
}
