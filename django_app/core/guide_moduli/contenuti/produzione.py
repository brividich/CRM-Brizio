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
                      "è il catalogo di tutti i P/N (OP, KICK-OFF e cartelle Collaudo) con cliente, stato, OP, report degli "
                      "ultimi 12 mesi, Cpk peggiore, quote non capaci, fuori nell'ultimo mese, anomalie e FAI; «Mostra» "
                      "filtra Attivi, «Da guardare», Con OP, «Con OP senza FAI» e «Solo archivio Collaudo»."),
                ("p", "Nella scheda del P/N «Anagrafica» apre il pannello con descrizione, cliente, disegno, revisione, "
                      "materiale, famiglia, stato e note (permesso «Anagrafica P/N»)."),
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
                    "In alto i numeri dell'OP e la striscia del percorso (KICK-OFF, programmi, documenti, FAI, anomalie).",
                    "«Pezzi»: matrice pezzi × fasi (una riga per S/N, una colonna per programma CMM; OK, al limite, "
                    "fuori, non misurato, ↻ rimisurato; clic = report) e «Cosa è successo».",
                    "«Report CMM»: i report dell'OP, da spuntare per il confronto.",
                    "«Documenti»: cicli, disegni, DIP, piani di controllo, certificati, rapporti di collaudo e "
                    "gli altri tipi decisi in Impostazioni, con revisione, data e cartella di rete. «Aggiungi documento», "
                    "«Modifica», «Elimina».",
                    "«FAI»: dal Registro FAI, gli ultimi dieci del P/N con il loro OP; «+ Nuovo FAI del P/N».",
                    "«Programmi»: dalle righe del KICK-OFF dello stesso P/N.",
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
                      "programmi, «PDF di capacità». «Quote CMM» ha la «Mappa qualità» (P/N × ultime 12 settimane, in ogni casella "
                      "report con quote fuori su report misurati, clic = i report di quella settimana) e le «Quote da guardare» "
                      "di tutti i P/N; Impostazioni › «Avvisi delle quote CMM» sceglie chi riceve gli avvisi."),
                ("p", "Scheda del P/N, sezione «Qualità CMM»: programmi e quote dalla peggiore per Cpk, carta di controllo "
                      "degli ultimi 30 pezzi con distribuzione, Cpk, Cp, media, σ, fuori, deriva e una «Lettura» scritta dai "
                      "numeri; «Tabella Cpk» con tutte le quote."),
                ("p", "Il report di un S/N è un protocollo: timbro «Esito» (NOK, DA VERIFICARE, OK, ESCLUSO), quote per "
                      "gruppo a sinistra, tabella con deviazione, grafico (tolleranza, fascia all'80%, barra verde/gialla/rossa), "
                      "«Fuori di» e «Usata», dettaglio della quota a destra con l'andamento sugli ultimi 30 pezzi (frecce ↑ ↓ "
                      "per scorrere); filtri Fuori, Al limite, Cambiate dal pezzo prima; «‹ S/N / S/N ›», «Compatta», «PDF "
                      "originale», «Apri segnalazione anomalia» con il pannello «📄 Dal report CMM (PDF)» già pronto."),
                ("p", "Pagina del pezzo (clic sul S/N nel titolo del report o nella tabella «Pezzi e fasi» dell'OP): timbro "
                      "«Stato pezzo» dall'ultimo report di ogni fase (la rimisura sostituisce la misura fuori), «Multi-protocollo» "
                      "quote × report colorato dalla tolleranza usata (% / deviazione / valore, clic = report alla quota), "
                      "report, anomalie e altri pezzi dello stesso OP, «Confronta le fasi» e «Scheda pezzo (PDF)». Nelle pagine "
                      "di dettaglio niente schede del modulo: percorso «Ordini di produzione › P/N › OP» e «? Guida»."),
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
                    ("Anagrafica P/N", "permesso «Ordini di produzione - Anagrafica P/N» (di default solo admin) per "
                     "cambiare l'anagrafica e usare «Aggiorna il catalogo». Il catalogo si aggiorna da solo alla fine di ogni "
                     "giro dei report CMM; al primo uso, se è vuoto, si crea all'apertura della pagina."),
                    ("Report CMM", "cartella PRODUZIONE_REPORT_CMM_ROOT (di default \\\\novisrv\\Area Controllo\\Collaudo), "
                     "letta ogni ora dal lavoro pianificato «produzione_report_cmm_giro» per al massimo "
                     "PRODUZIONE_REPORT_CMM_MINUTI minuti (15). L'utente del portale e quello di qcluster devono poter "
                     "leggere la share. Primo caricamento lungo: «manage.py leggi_report_cmm --minuti 120». Legge anche il "
                     "formato vecchio (fino al 2024); i report già in elenco senza quote si rileggono da soli, prima le "
                     "cartelle che ne hanno. Avvisi solo per i report degli ultimi 30 giorni. Alla fine del giro calcola Cpk, deriva e "
                     "fuori dei P/N cambiati (li legge «Quote CMM»)."),
                    ("Database", "lavoro pianificato «produzione_manutenzione_db» (ogni notte alle 03:10, solo SQL Server): "
                     "statistiche delle tabelle del modulo ricalcolate dove è cambiato più del 10% delle righe, indici "
                     "riorganizzati oltre il 10% di frammentazione e ricostruiti oltre il 30%; non parte durante un giro. Le "
                     "misure CMM sono ordinate per report e compresse (migrazione produzione 0009)."),
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
                      "report nuovi con data negli ultimi 30 giorni; una quota in deriva al massimo una volta al mese).",
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
