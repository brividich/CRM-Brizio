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
                ("p", "La scheda del P/N segue quattro passi: KICK-OFF del P/N, programmi CAM e CMM, FAI del P/N (situazione "
                      "per cliente, tutti i FAI con il loro OP, «+ Nuovo FAI per questo P/N»), OP del P/N (documenti e "
                      "anomalie aperte di ciascuno)."),
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
            "titolo": "Andamento quote dai report CMM",
            "blocchi": [
                ("p", "I report CMM in PDF della cartella Collaudo si leggono da soli ogni ora. Dalla scheda del P/N, "
                      "«Andamento quote»: scegli programma (senza revisione) e quota, vedi la quota in tutti i S/N con "
                      "il grafico di rilevato, nominale e limiti. L'elenco delle quote dice quante volte ognuna è "
                      "andata fuori."),
                ("p", "Il S/N apre il report con le sole quote fuori, «Andamento» per ciascuna, «Apri il PDF» e «Apri "
                      "segnalazione anomalia»: Gestione anomalie si apre sull'OP e, avviato il controllo, il pannello "
                      "«📄 Dal report CMM (PDF)» ha già le righe del report. «Leggi i report» rilegge subito la cartella "
                      "del P/N."),
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
            "sintomo": "«Andamento quote» non mostra report o dice «Cartella non leggibile»",
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
