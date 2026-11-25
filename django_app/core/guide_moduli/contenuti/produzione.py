"""Centro guide: Ordini di produzione (OP e documenti di produzione)."""

GUIDA = {
    "slug": "produzione",
    "titolo": "Ordini di produzione",
    "area": "Produzione e operations",
    "sintesi": "Ogni P/N con i suoi OP e i suoi FAI; ogni OP con documenti di produzione, programmi CAM e CMM e anomalie.",
    "parole": "ctrl+k cerca op ordine di produzione ordini documenti di produzione fai programmi cam cmm ciclo disegno dip "
              "piano di controllo certificato materiale collaudo conformità coc anomalie p/n part number articolo scheda p/n",
    "url": "produzione:elenco",
    "prefissi": ("/produzione/",),
    "dettaglio": [
        ("Guida Ordini di produzione", "produzione:guida"),
    ],
    "uso": [
        {
            "id": "elenco",
            "titolo": "Elenco degli OP",
            "blocchi": [
                ("p", "«Ordini di produzione» nel menu Produzione. Gli OP sono quelli di Gestione anomalie, letti e non "
                      "copiati, dal più recente. Per ogni OP: P/N, capocommessa, CAR, stato e quanti documenti, FAI e "
                      "anomalie aperte ha. Cerca per OP, P/N, capocommessa o CAR, filtra per stato."),
                ("p", "«+ Nuovo OP» apre un pannello a lato (causale, anno, numero, P/N, fase, capocommessa, CAR, collaudo "
                      "di benestare, note): stesse regole di Gestione anomalie, titolo causale/anno/numero non ripetibile. "
                      "Lo stesso pannello si apre dalla scheda FAI e mette l'OP creato nel campo OP."),
            ],
        },
        {
            "id": "pn",
            "titolo": "P/N",
            "blocchi": [
                ("p", "Il P/N è l'articolo principale: ha più OP e i FAI sono suoi, non del singolo OP. La scheda «P/N» "
                      "elenca i P/N degli OP con numero di OP, ultimo OP, capocommessa, FAI, «Situazione FAI» e anomalie "
                      "aperte; «Da sistemare» filtra «Con anomalie aperte», «Senza FAI» e «FAI da ripetere o verificare»."),
                ("p", "La scheda del P/N (indirizzo fisso /produzione/pn/<P/N>/) ha in alto la striscia del percorso "
                      "(KICK-OFF, programmi CAM e CMM, FAI, OP) e sotto le sezioni Panoramica («Da fare», pezzi misurati per "
                      "mese, quote da tenere d'occhio, OP), OP, Report CMM, Programmi e FAI."),
            ],
        },
        {
            "id": "percorso",
            "titolo": "Il percorso dell'OP",
            "blocchi": [
                ("p", "La scheda segue cinque passi: KICK-OFF del P/N, programmi CAM e CMM, documenti di produzione, FAI, "
                      "anomalie. Ognuno è «Fatto», «Da fare», «In attesa» o «Da gestire» e ha un solo pulsante con l'azione "
                      "già compilata (Nuovo KICK-OFF col P/N, Aggiungi documento, Nuovo FAI con OP e P/N…). Il passo «FAI del P/N» guarda "
                      "il FAI più recente del P/N, anche se fatto su un altro OP. «Prossimo passo» "
                      "in cima dice da dove ripartire; a fine giro compare «Percorso completo»."),
                ("p", "Nell'elenco «Da sistemare» filtra gli OP con anomalie aperte, senza documenti o senza FAI, e «Manca» "
                      "nelle colonne porta al passo giusto della scheda."),
            ],
        },
        {
            "id": "scheda",
            "titolo": "La scheda dell'OP",
            "blocchi": [
                ("ul", [
                    "«Documenti registrati»: cicli, disegni, DIP, piani di controllo, certificati, rapporti di collaudo e "
                    "gli altri tipi decisi in Impostazioni, con revisione, data e cartella di rete. «Aggiungi documento», "
                    "«Modifica», «Elimina».",
                    "«FAI del P/N»: dal Registro FAI, gli ultimi dieci del P/N con il loro OP; «Scheda del P/N» per "
                    "tutti, «+ Nuovo FAI del P/N» apre la scheda FAI con OP e P/N già compilati.",
                    "«Programmi CAM e CMM»: dalle righe del KICK-OFF dello stesso P/N.",
                    "«Anomalie»: conteggi e link a Gestione anomalie filtrata sull'OP.",
                    "«KICK-OFF del P/N» e «Altri OP dello stesso P/N» a lato.",
                ]),
                ("p", "Nel Registro FAI il campo OP propone gli OP dello stesso elenco e il nome dell'OP porta a questa scheda."),
            ],
        },
        {
            "id": "quote",
            "titolo": "Analisi quote dai report CMM",
            "blocchi": [
                ("p", "I report CMM in PDF della cartella Collaudo si leggono da soli ogni ora. Dalla scheda del P/N, "
                      "«Analisi quote»: filtri per programma, periodo, OP e S/N da evidenziare; elenco delle quote con "
                      "filtri (andate fuori, Cpk < 1,33, vicine al limite, da verificare) e ordinamenti; quattro viste: "
                      "Quota (statistiche Cp/Cpk, grafico con zona di tolleranza, zoom, distribuzione, tabella), Mappa "
                      "(tutte le quote × tutti i report, colore = tolleranza usata), Confronto (fino a 6 quote in % "
                      "della tolleranza) e Pezzo (tutte le quote di un S/N, confrontabile con un altro). «Esporta CSV» "
                      "con i filtri attivi; l'indirizzo conserva la vista."),
                ("p", "Filtri anche per misure (ultima per S/N o tutte), report scelti a mano ed esclusi. Quote in deriva "
                      "(retta sugli ultimi 20 pezzi, stima dei pezzi al limite), segnali di controllo (oltre 3σ, 9 dallo stesso "
                      "lato, 6 in salita/discesa), eventi (cambio revisione, note), bandierine delle anomalie, quote unite fra "
                      "programmi, «PDF di capacità». «Quote CMM» elenca tutti i P/N dal più grave; Impostazioni › «Avvisi delle "
                      "quote CMM» sceglie chi riceve gli avvisi."),
                ("p", "La scheda del P/N mostra le «Quote da tenere d'occhio». Dal report di un S/N: tutte le quote con "
                      "barra nella tolleranza, tolleranza usata, differenza dal pezzo prima e Cpk; filtri Fuori, Al limite, "
                      "Diverse dal pezzo prima; «‹ Pezzo prima / Pezzo dopo ›», «Apri il PDF», «Apri segnalazione anomalia» "
                      "con il pannello «📄 Dal report CMM (PDF)» già pronto."),
                ("p", "Confronto report: spunta da 2 a 6 righe negli elenchi dei report e premi «Confronta». Quote "
                      "allineate (anche quelle unite fra programmi), differenza fra ultimo e primo in % della tolleranza, "
                      "confronti pronti (stesso S/N in tutte le fasi, primo articolo e ultimi pezzi, pezzo prima e dopo), "
                      "export CSV."),
            ],
        },
    ],
    "admin": [
        {
            "id": "config",
            "titolo": "Configurazione",
            "blocchi": [
                ("def", [
                    ("Permessi", "«Elenco e scheda OP» a tutti i ruoli; «Documenti», «Impostazioni» e «Nuovo OP» solo admin "
                     "(Accessi › permessi del modulo Ordini di produzione). FAI, programmi e KICK-OFF seguono i "
                     "permessi del KICK-OFF."),
                    ("Tipi di documento", "Ordini di produzione › Impostazioni: nome, descrizione, ordine, attivo."),
                    ("Quote CMM", "permesso «Gestire le quote CMM» (escludere report, unire quote; di default solo admin); "
                     "avvisi in Impostazioni (destinatari, fuori tolleranza, deriva)."),
                    ("Report CMM", "cartella PRODUZIONE_REPORT_CMM_ROOT (di default \\\\novisrv\\Area Controllo\\Collaudo), "
                     "letta ogni ora dal lavoro pianificato «produzione_report_cmm_giro» per al massimo "
                     "PRODUZIONE_REPORT_CMM_MINUTI minuti (15). L'utente del portale e quello di qcluster devono poter "
                     "leggere la share. Primo caricamento lungo: «manage.py leggi_report_cmm --minuti 120»."),
                    ("Elenco OP", "tabella ordini_produzione, la stessa di Gestione anomalie; gli OP nuovi si creano qui, "
                     "dalla scheda FAI o da Gestione anomalie, con la stessa funzione."),
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Gli avvisi delle quote CMM non arrivano",
            "perche": "nessun destinatario scelto, interruttori spenti, oppure il report era già stato letto prima (avvisa solo i "
                      "report nuovi; una quota in deriva al massimo una volta al mese).",
            "fare": ["Ordini di produzione › Impostazioni › «Avvisi delle quote CMM»: scegli chi riceve gli avvisi."],
        },
        {
            "sintomo": "«Analisi quote» non mostra report o dice «Cartella non leggibile»",
            "perche": "la cartella del P/N non è ancora stata letta, ha un nome diverso dal P/N, oppure l'utente del "
                      "portale non ha la lettura sulla share Collaudo.",
            "fare": ["Premi «Leggi i report» e ricarica dopo qualche minuto.",
                     "Controlla che la cartella in Collaudo si chiami come il P/N.",
                     "Dai la lettura sulla share all'utente del portale e di qcluster."],
        },
        {
            "sintomo": "Una quota compare due volte o l'andamento ha pochi punti",
            "perche": "le quote si uniscono per nome e nominale: se il programma l'ha rinominata o ha cambiato il "
                      "nominale, o il report è di un altro programma, sono quote diverse.",
            "fare": ["Controlla il programma scelto e il nome della quota nei report."],
        },
        {
            "sintomo": "«L'elenco degli OP non è disponibile»",
            "perche": "nel database manca la tabella ordini_produzione.",
            "fare": ["Controlla lo schema legacy con «manage.py ensure_legacy_schema»."],
        },
        {
            "sintomo": "Nella scheda dell'OP non compaiono FAI né programmi",
            "perche": "manca il permesso del KICK-OFF, oppure l'OP non ha P/N o il P/N del FAI è scritto diverso.",
            "fare": ["Controlla i permessi del modulo KICK-OFF.",
                     "Nella scheda FAI controlla che il P/N sia uguale a quello dell'OP (maiuscole e spazi non contano)."],
        },
    ],
}
