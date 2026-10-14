GUIDA = {
    "slug": "contatori",
    "titolo": "Contatori MFC e SNMP",
    "area": "IT e sicurezza informatica",
    "sintesi": "Contatori delle stampanti multifunzione, fatture del fornitore e monitoraggio di rete, UPS e apparati via SNMP.",
    "parole": "contatori mfc stampante stampanti copie toner snmp ups switch fattura copylab canon",
    "url": "contatori:dashboard",
    "prefissi": ("/contatori/",),
    "dettaglio": [("Guida della riconciliazione fatture", "contatori:riconciliazione_guida")],
    "uso": [
        {
            "id": "consultare",
            "titolo": "Consultare contatori e apparati",
            "blocchi": [
                ("ul", [
                    "Il cruscotto mostra le multifunzione (MFC) con le ultime letture, i toner e lo stato degli apparati monitorati.",
                    "Clicca una MFC per la scheda: letture mensili, consumabili, asset collegato.",
                    "Le letture si fanno da sole ogni mese il giorno 1 a mezzanotte, con un secondo tentativo alle 08:00 per le macchine spente.",
                ]),
            ],
        },
        {
            "id": "lettura",
            "titolo": "Inserire una lettura a mano",
            "blocchi": [
                ("passi", [
                    "Apri la scheda della MFC e scegli il trimestre.",
                    "Scrivi i contatori letti sul display della macchina e salva.",
                    "Se un contatore è più basso del precedente il portale si ferma e chiede conferma (azzeramento o sostituzione macchina).",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "dispositivo",
            "titolo": "Aggiungere un apparato SNMP",
            "blocchi": [
                ("passi", [
                    "Apri il wizard «Nuovo dispositivo SNMP».",
                    "Scegli tipo e modello, poi l'indirizzo IP o il nome.",
                    "Scegli le credenziali (community o utente SNMPv3) dal catalogo cifrato.",
                    "Esegui il test di connessione: è obbligatorio.",
                    "Controlla la mappatura (i valori letti compaiono accanto a ogni campo; in rosso quelli che non rispondono).",
                    "Collega l'asset e il reparto e conferma.",
                ]),
                ("nota", "La community SNMP non è scritta nel codice: si imposta in configurazione globale o per apparato e resta cifrata."),
            ],
        },
        {
            "id": "fatture",
            "titolo": "Fatture del fornitore",
            "blocchi": [
                ("p", "«Fatture» → nuova fattura: si può caricare la fattura elettronica (XML o PDF di stampa) e il portale compila le righe. "
                      "La «Riconciliazione» confronta per trimestre le letture fatturate con quelle interne. I dettagli sono nella guida della riconciliazione."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Un apparato è in errore SNMP",
            "perche": "il codice dell'errore dice la causa.",
            "fare": [
                "Leggi il codice nella scheda: SNMP-001 indirizzo non valido, 002 nome non risolto, 003 nessuna risposta (spesso community sbagliata), "
                "004 credenziali v3 rifiutate, 005 dato non disponibile, 006 valore non valido, 007 permessi/gestori ammessi sull'apparato, 008 credenziali mancanti.",
                "Per 003: controlla che l'apparato sia acceso e raggiungibile (ping) e che la community sia quella giusta.",
                "Per 007: sull'apparato va autorizzato l'indirizzo del server del portale come gestore SNMP.",
            ],
        },
        {
            "sintomo": "Le letture mensili non sono arrivate",
            "fare": [
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla i lavori dei contatori.",
                "Se il cluster è fermo segui «Le automazioni non partono» nel Manuale di emergenza.",
                "Inserisci la lettura a mano dalla scheda MFC.",
            ],
        },
    ],
}
