"""Centro guide: Ordini di produzione (OP e documenti di produzione)."""

GUIDA = {
    "slug": "produzione",
    "titolo": "Ordini di produzione",
    "area": "Produzione e operations",
    "sintesi": "Ogni OP con i suoi documenti di produzione: FAI, programmi CAM e CMM, documenti registrati e anomalie.",
    "parole": "ctrl+k cerca op ordine di produzione ordini documenti di produzione fai programmi cam cmm ciclo disegno dip "
              "piano di controllo certificato materiale collaudo conformità coc anomalie p/n",
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
            "id": "percorso",
            "titolo": "Il percorso dell'OP",
            "blocchi": [
                ("p", "La scheda segue cinque passi: KICK-OFF del P/N, programmi CAM e CMM, documenti di produzione, FAI, "
                      "anomalie. Ognuno è «Fatto», «Da fare», «In attesa» o «Da gestire» e ha un solo pulsante con l'azione "
                      "già compilata (Nuovo KICK-OFF col P/N, Aggiungi documento, Nuovo FAI con OP e P/N…). «Prossimo passo» "
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
                    "«FAI»: dal Registro FAI, prima quelli dell'OP poi gli altri del P/N; «Nuovo FAI per questo OP» "
                    "apre la scheda FAI con OP e P/N già compilati.",
                    "«Programmi CAM e CMM»: dalle righe del KICK-OFF dello stesso P/N.",
                    "«Anomalie»: conteggi e link a Gestione anomalie filtrata sull'OP.",
                    "«KICK-OFF del P/N» e «Altri OP dello stesso P/N» a lato.",
                ]),
                ("p", "Nel Registro FAI il campo OP propone gli OP dello stesso elenco e il nome dell'OP porta a questa scheda."),
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
                    ("Elenco OP", "tabella ordini_produzione, la stessa di Gestione anomalie; gli OP nuovi si creano qui, "
                     "dalla scheda FAI o da Gestione anomalie, con la stessa funzione."),
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "«L'elenco degli OP non è disponibile»",
            "perche": "nel database manca la tabella ordini_produzione.",
            "fare": ["Controlla lo schema legacy con «manage.py ensure_legacy_schema»."],
        },
        {
            "sintomo": "Nella scheda dell'OP non compaiono FAI né programmi",
            "perche": "manca il permesso del KICK-OFF, oppure i FAI non citano l'OP e il P/N è diverso.",
            "fare": ["Controlla i permessi del modulo KICK-OFF.",
                     "Nel Registro FAI scegli l'OP dal campo OP della scheda FAI."],
        },
    ],
}
