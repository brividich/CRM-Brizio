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
                  "procedure guidate «+ Apparato» (stampanti MFC e dispositivi SNMP) e «+ Profilo SNMP» sono "
                  "nel menu «+ Nuovo» (solo con il permesso di gestione)."),
            ("p", "La Centrale sta in una schermata: in alto gli indicatori (letture del trimestre, copie, "
                  "riconciliazione del trimestre precedente, stato flotta SNMP, consumabili sotto soglia, "
                  "letture da confermare, fatture da riconciliare, licenze degli apparati), sotto tre colonne che scorrono ognuna per "
                  "conto suo: «Da fare», «Parco MFC» e «SNMP». Ogni indicatore e ogni voce aprono la pagina "
                  "dove si interviene; nel Parco MFC il dettaglio A4/A3 compare passando il mouse sul totale."),
        ],
    },
    {
        "id": "mensili",
        "titolo": "Letture mensili automatiche",
        "blocchi": [
            ("p", "Il giorno 1 alle 00:00 il portale legge i contatori di ogni MFC attiva con IP, allineati "
                  "alla chiusura del fornitore. Le MFC spente o in sospensione vengono riprovate ogni 15 minuti "
                  "fino al giorno 7: la lettura arriva entro un quarto d'ora da quando la macchina si riaccende."),
            ("ul", [
                "Nella scheda MFC, «Letture mensili automatiche», il badge giallo (es. «+31 h» o «+3 gg») indica "
                "che la lettura è arrivata dopo la chiusura: i contatori includono le copie fatte nel frattempo.",
                "Dal giorno 2 al 7 la Centrale mostra «N letture mensili in attesa»; dal giorno 8 diventa "
                "«N letture mensili saltate»: la MFC non ha mai risposto, controlla che sia accesa e in rete.",
                "La prima lettura riuscita del mese non viene più sovrascritta.",
            ]),
            ("p", "MFC Kyocera (TASKalfa): ogni contatore è la somma di stampe e copie dello stesso colore e "
                  "formato. In un profilo SNMP una colonna può sommare più OID scrivendoli uniti da + "
                  "(solo modalità GET)."),
        ],
    },
    {
        "id": "tvcc",
        "titolo": "Videosorveglianza (NVR e telecamere TVT)",
        "blocchi": [
            ("p", "NVR e telecamere IP si aggiungono con «+ Nuovo» → «+ Apparato» "
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
        "id": "nuovo-apparato",
        "titolo": "Aggiungere un apparato (MFC o dispositivo SNMP)",
        "blocchi": [
            ("p", "Un solo percorso guidato per stampanti MFC e dispositivi SNMP: «+ Nuovo» → «+ Apparato» "
                  "(anche «+ Nuova MFC» in Stampanti MFC, «+ Apparato» nel Monitor SNMP e «Aggiungi» nei "
                  "risultati del Discovery, che precompilano i dati). Quattro passi:"),
            ("def", [
                ("1 · Apparato", "«Asset collegato (registro HUB)»: se l'apparato è già nel registro sceglilo, "
                                 "i campi lasciati vuoti prendono nome, matricola, modello, reparto e IP "
                                 "dall'asset. «Tipo di apparato»: «Stampante MFC a contratto (contatori e "
                                 "fattura)» chiede anche contratto e fornitore e la matricola è obbligatoria; "
                                 "gli altri tipi (rete, UPS, TVCC…) vanno nel Monitor SNMP."),
                ("2 · Connessione", "indirizzo, porta, «Versione SNMP» e credenziali nella stessa pagina. "
                                    "Con v1/v2c: una credenziale del catalogo o una nuova community. Con SNMPv3 "
                                    "la community sparisce e compare il riquadro «Credenziali SNMPv3»."),
                ("3 · Verifica", "un solo pulsante «Verifica»: legge identità, riconosce il modello e legge "
                                 "i valori (per le MFC i quattro contatori). «Modello (profilo SNMP)» si può "
                                 "scegliere qui; vuoto = riconosciuto dalla verifica. Una MFC prosegue solo "
                                 "con i quattro contatori letti e numerici."),
                ("4 · Riepilogo", "controlla e «Conferma e crea». Se non hai scelto un asset e il registro "
                                  "ne ha uno con la stessa matricola o lo stesso IP, il portale lo propone: "
                                  "«Collega questo asset»."),
            ]),
            ("p", "Un dispositivo (non una MFC) si può salvare come bozza «non verificata» dal passo "
                  "«Connessione» in poi: viene verificato alla prima lettura SNMP riuscita."),
        ],
    },
    {
        "id": "snmpv3",
        "titolo": "SNMPv3 e verifica",
        "blocchi": [
            ("p", "Con «SNMPv3 (utente e chiavi)» al passo «Connessione» si compilano solo "
                  "«SNMPv3 - utente», «SNMPv3 - autenticazione» (SHA o MD5) con la sua chiave e «SNMPv3 - "
                  "cifratura» (AES o DES) con la sua chiave, oppure una credenziale v3 del catalogo. "
                  "La community non serve. Il portale supporta AES-128 e DES, SHA-1 e MD5: "
                  "AES-192/256 e SHA-224/256/384/512 non sono supportati."),
            ("p", "Se la verifica va in timeout con SNMPv3, il portale invia all'apparato una richiesta di "
                  "identificazione senza credenziali e mostra il codice giusto:"),
            ("def", [
                ("SNMP-009 · apparato raggiungibile, credenziali scartate", "la rete funziona: l'apparato "
                 "risponde a SNMPv3 (si vede il suo engine ID) ma ignora la lettura. Quasi sempre è la "
                 "cifratura: protocollo diverso (AES/DES, oppure AES-192/256 sull'apparato) o chiave di "
                 "cifratura errata. Ricontrolla l'utente sull'apparato e reinserisci tutte le chiavi."),
                ("SNMP-010 · nessuna risposta SNMPv3", "l'apparato non risponde nemmeno all'identificazione: "
                 "spento, IP errato, SNMPv3 non attivo, firewall o VLAN che bloccano UDP 161 dal server del "
                 "portale, oppure l'apparato accetta solo gestori autorizzati."),
                ("SNMP-004 · credenziali SNMPv3 rifiutate", "l'apparato risponde con un errore esplicito: "
                 "utente sconosciuto o chiave/protocollo di autenticazione errati."),
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
