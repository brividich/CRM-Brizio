"""Guida d'uso della riconciliazione fatture MFC (pagina «? Guida» della Riconciliazione).

Testo semplice, niente HTML: il template lo mostra con l'autoescape. Blocchi di una
sezione: ("p", testo), ("ul", [voci]), ("nota", testo), ("def", [(termine, spiegazione)]).
Le etichette citate sono quelle visibili nelle pagine: se ne cambia una, va
aggiornata anche qui.
"""
from __future__ import annotations

SEZIONI: list[dict] = [
    {
        "id": "scopo",
        "titolo": "A cosa serve",
        "blocchi": [
            ("p", "La riconciliazione confronta, per ogni trimestre, le letture dei contatori stampate "
                  "nella fattura del fornitore con le letture interne delle stesse MFC. La lettura interna "
                  "è fatta qualche giorno dopo la chiusura del fornitore, quindi deve essere maggiore o "
                  "uguale: se è minore, il fornitore ha fatturato copie che la macchina non mostra."),
            ("def", [
                ("Scarto", "interno − fornitore. Negativo = da controllare."),
                ("OK esatto", "interno uguale al fornitore."),
                ("OK (stampe nel ritardo)", "interno maggiore: sono le copie fatte tra la chiusura del "
                                            "fornitore e la lettura interna."),
                ("Da controllare: fornitore > interno", "il fornitore dichiara più copie della macchina."),
                ("lettura interna mancante", "almeno una MFC del contratto non ha la lettura del trimestre."),
            ]),
        ],
    },
    {
        "id": "fattura",
        "titolo": "Caricare la fattura",
        "blocchi": [
            ("p", "Da Riconciliazione → «+ Nuova fattura» carica la fattura elettronica (XML, consigliato) "
                  "o la sua stampa PDF e premi «Leggi la fattura»: la pagina si compila da sola. Controlla "
                  "gli avvisi in giallo, poi «Salva fattura». Il file non viene conservato."),
            ("p", "Sono riconosciuti due tracciati:"),
            ("ul", [
                "BASE: blocchi «N. Contratto: …» con una riga per contatore A4/A3 B/N e colore. Il "
                "contatore si ricava dal prezzo per copia.",
                "Copylab: blocchi «Matricola:… Contratto:…» per ogni macchina, con le righe «COPIE "
                "EFFETTUATE B/N» e «COPIE EFFETTUATE COLORE». La fattura riporta solo i totali: viene "
                "salvata con «Letture in fattura» = «Solo totali B/N e colore».",
            ]),
            ("p", "Per Copylab il contratto della riga viene preso dall'anagrafica stampanti cercando la "
                  "matricola: se la macchina non ha il contratto in anagrafica compare un avviso con il "
                  "valore da impostare."),
            ("nota", "In una fattura «Solo totali» il totale B/N va nella colonna «B/N totale» e il totale "
                     "colore in «Colore totale»; le colonne A3 non si usano."),
        ],
    },
    {
        "id": "pool",
        "titolo": "Più MFC sullo stesso contratto (pool)",
        "blocchi": [
            ("p", "Se più MFC hanno lo stesso valore nel campo «Contratto» dell'anagrafica stampanti, sono "
                  "fatturate in pool: la fattura riporta una lettura unica e la riconciliazione la confronta "
                  "con la somma delle letture interne delle macchine. Il contratto mostra il badge "
                  "«pool · N MFC» e sotto il valore interno la parte di ogni macchina."),
            ("p", "Se manca la lettura anche di una sola macchina del pool il confronto non viene fatto "
                  "(una somma parziale darebbe un falso allarme): l'esito è «lettura interna mancante» e "
                  "accanto alla macchina c'è «+ Lettura»."),
            ("nota", "Il contratto deve essere scritto identico su tutte le MFC del pool. Una MFC dismessa "
                     "che conserva il contratto continua a contare: togli il contratto alla vecchia."),
        ],
    },
    {
        "id": "lettura",
        "titolo": "Leggere la pagina",
        "blocchi": [
            ("ul", [
                "Le schede in alto contano i contratti: «Allineati», «Da controllare» (con il numero di "
                "contatori in cui il fornitore supera l'interno) e «Letture interne mancanti».",
                "«Tutti» / «Da verificare» filtrano i contratti: «Da verificare» mostra solo quelli da "
                "controllare o incompleti.",
                "Ogni contratto ha la sua scheda: fattura, fornitore, data di chiusura e, per ogni MFC, la "
                "data della lettura interna e i giorni dopo la chiusura del fornitore. Una lettura fatta "
                "prima della chiusura viene segnalata: in quel caso uno scarto negativo è atteso.",
                "Nelle fatture «Solo totali» i contatori sono «BN totale» e «COL totale»: l'interno è A4 + A3.",
                "«Esporta .xlsx» scarica il confronto riga per riga.",
            ]),
        ],
    },
    {
        "id": "centrale",
        "titolo": "Barra del modulo e Centrale",
        "blocchi": [
            ("p", "La barra in alto raggruppa le pagine in Operatività, Economico e Configurazione. Le "
                  "procedure guidate «+ MFC», «+ Dispositivo SNMP» e «+ Profilo SNMP» sono nel menu «+ Nuovo» "
                  "(solo con il permesso di gestione)."),
            ("p", "La Centrale sta in una schermata: in alto gli indicatori (letture del trimestre, copie, "
                  "riconciliazione del trimestre precedente, stato flotta SNMP, consumabili sotto soglia, "
                  "letture da confermare, fatture da riconciliare), sotto tre colonne che scorrono ognuna per "
                  "conto suo: «Da fare», «Parco MFC» e «SNMP». Ogni indicatore e ogni voce aprono la pagina "
                  "dove si interviene; nel Parco MFC il dettaglio A4/A3 compare passando il mouse sul totale."),
        ],
    },
    {
        "id": "permessi",
        "titolo": "Chi può fare cosa",
        "blocchi": [
            ("def", [
                ("Consultare la riconciliazione", "permesso «Contatori - Consultazione»."),
                ("Caricare, modificare ed eliminare fatture e letture", "permesso «Contatori - Gestione»."),
            ]),
        ],
    },
]
