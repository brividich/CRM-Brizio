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
                  "letture da confermare, fatture da riconciliare, licenze degli apparati), sotto tre colonne che scorrono ognuna per "
                  "conto suo: «Da fare», «Parco MFC» e «SNMP». Ogni indicatore e ogni voce aprono la pagina "
                  "dove si interviene; nel Parco MFC il dettaglio A4/A3 compare passando il mouse sul totale."),
        ],
    },
    {
        "id": "tvcc",
        "titolo": "Videosorveglianza (NVR e telecamere TVT)",
        "blocchi": [
            ("p", "NVR e telecamere IP si aggiungono come dispositivi SNMP («+ Nuovo» → «+ Dispositivo SNMP») "
                  "con tipo «TVCC - Videoregistratore (NVR)» o «TVCC - Telecamera IP», e si collegano "
                  "all'asset di videosorveglianza già censito. Il portale legge solo dati tecnici via SNMP: "
                  "nessuna immagine e nessun flusso video."),
            ("def", [
                ("Profilo «TVT NVR (videoregistratore)»", "velocità e stato delle due schede di rete (eth0, "
                                                          "eth1): una scheda non attiva mette l'NVR in "
                                                          "«Attenzione». Modello e firmware compaiono nella "
                                                          "scheda del dispositivo. L'NVR non espone via SNMP "
                                                          "MAC, dischi né risorse."),
                ("Profilo «TVT telecamera IP»", "solo controllo di raggiungibilità: «Operativo» se la "
                                                "telecamera risponde, «Errore» se non risponde. Le telecamere "
                                                "non espongono interfacce, MAC né risorse."),
                ("Attivare SNMP", "sulla telecamera va abilitato SNMP (v2c con community di sola lettura, "
                                  "oppure v3) dalla sua pagina web. La community di scrittura non serve: "
                                  "il portale legge e basta."),
            ]),
            ("p", "Nel Monitor SNMP il pulsante «Videosorveglianza» (o la categoria «Videosorveglianza (NVR e "
                  "telecamere)» nel filtro) mostra solo NVR e telecamere, con l'asset collegato."),
            ("p", "In «Stampanti MFC» → «Configurazione SNMP globale» (link «Impostazioni SNMP e TVCC» nel "
                  "Monitor SNMP) si impostano: «TVCC - Intervallo NVR (minuti)» (predefinito 5), «TVCC - "
                  "Intervallo telecamere (minuti)» (predefinito 30) e «TVCC - Storico rilevazioni (giorni)» "
                  "(predefinito 14). Ogni notte le rilevazioni TVCC più vecchie vengono cancellate; stampanti "
                  "e altri apparati conservano tutto lo storico."),
            ("p", "Nella lista asset un pallino accanto al nome riassume lo stato SNMP dei dispositivi "
                  "collegati: verde «Operativo», giallo «Attenzione», rosso «Errore» (non risponde), grigio "
                  "«Mai interrogato»; con più dispositivi vince il peggiore. Passando il mouse si vede il "
                  "dettaglio. Il pallino si vede solo con accesso al Monitor SNMP."),
            ("p", "Nella scheda dell'asset, tab «Monitoraggio», compaiono stato, ultimo controllo, da quanti "
                  "giorni è acceso (non per le telecamere: il loro dato riguarda il servizio SNMP) e gli "
                  "ultimi valori letti. Il MAC letto è confrontato con quello "
                  "dichiarato nel campo «MAC» dell'asset: «= dichiarato», «diverso dal dichiarato» oppure "
                  "«non dichiarato». Il monitoraggio non modifica mai i dati dell'asset."),
        ],
    },
    {
        "id": "licenze",
        "titolo": "Licenze e software degli apparati",
        "blocchi": [
            ("p", "Le licenze stanno nel modulo Asset («Licenze software»): la Centrale e le schede le leggono "
                  "dall'asset collegato all'MFC o al dispositivo SNMP, senza duplicarle."),
            ("ul", [
                "Indicatore «Licenze degli apparati»: licenze scadute e in scadenza (entro 30 giorni) degli asset "
                "collegati ad apparati attivi, più il numero di apparati senza asset. Apre l'elenco licenze filtrato.",
                "Nella colonna «Da fare», elenco «Apparati senza asset collegato»: MFC e dispositivi senza asset. Senza collegamento "
                "non si vedono licenze, software installato e scadenze: apri l'apparato e collegalo dalla modifica.",
                "Nella scheda MFC e dispositivo, riquadro «Asset collegato»: nome, tipo, seriale e codice "
                "dell'asset, numero di licenze e di software rilevati dall'inventario del SOC, poi ogni licenza "
                "con scadenza, giorni mancanti (o trascorsi) e stato (valida, in scadenza, scaduta, disattiva). "
                "Pulsanti «Gestisci licenze» e «Apri scheda asset». Se negli ultimi 12 mesi sull'asset ci sono "
                "importi registrati (rinnovi licenze, interventi chiusi, adempimenti) compare il totale con il link "
                "«dettaglio» al riquadro «Costi registrati» della scheda asset.",
                "Apparato senza asset: se il portale trova un solo asset con la stessa matricola/seriale o lo stesso "
                "IP lo propone («Asset trovato per seriale», «per indirizzo IP», …) e chi gestisce il modulo lo collega "
                "con «Collega» (registrato nell'audit). Con «Scegli un altro», o se non c'è una proposta univoca, "
                "«Collega un asset» apre la modifica dell'apparato.",
            ]),
        ],
    },
    {
        "id": "firmware",
        "titolo": "Firmware dei dispositivi SNMP",
        "blocchi": [
            ("p", "A ogni interrogazione riuscita il portale legge la versione firmware: prima da una sonda di testo "
                  "il cui nome contiene «Firmware» (es. preset Kyocera, HPE iLO), altrimenti dal sysDescr "
                  "(«Version 15.2(4)E10», «Firmware 2.5.1»)."),
            ("ul", [
                "Nella scheda del dispositivo, riga «Firmware» in «Identità SNMP»: versione, fonte e data di lettura; "
                "con più versioni viste, l'elenco «N versioni viste» con le date di inizio e fine.",
                "Il firmware compare anche nel tab «Monitoraggio» della scheda asset collegata.",
                "Se il dispositivo ha produttore e modello, il firmware entra nell'inventario software del SOC "
                "come «<modello> firmware» (fonte «Firmware da monitoraggio SNMP»): il SOC lo confronta con le CVE "
                "come il software dei PC. Una versione nuova sostituisce la precedente.",
                "Le MFC del modulo (letture contatori) non leggono il sysDescr: per il firmware di una stampante "
                "aggiungila anche in Monitor SNMP.",
            ]),
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
