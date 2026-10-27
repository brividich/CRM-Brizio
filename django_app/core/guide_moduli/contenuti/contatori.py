GUIDA = {
    "slug": "contatori",
    "titolo": "Contatori IT",
    "area": "IT e sicurezza informatica",
    "sintesi": "Contatori delle stampanti multifunzione, fatture del fornitore e monitoraggio di rete, UPS e apparati via SNMP.",
    "parole": "contatori mfc stampante stampanti copie toner snmp ups switch fattura copylab canon",
    "url": "contatori:dashboard",
    "prefissi": ("/contatori/",),
    "dettaglio": [("Guida di Contatori IT", "contatori:riconciliazione_guida")],
    "uso": [
        {
            "id": "consultare",
            "titolo": "Consultare contatori e apparati",
            "blocchi": [
                ("ul", [
                    "Il cruscotto mostra le multifunzione (MFC) con le ultime letture, i toner e lo stato degli apparati monitorati.",
                    "Clicca una MFC per la scheda: letture trimestrali con le copie e i trimestri mancanti, letture mensili, fatture del contratto, consumabili, asset collegato; «Esporta storico» scarica tutto in Excel.",
                    "«Letture» → Registro letture: tutte le MFC per trimestre, con le letture mancanti e i cali in evidenza. «Tutte le MFC di un trimestre» inserisce le letture di più stampanti in una pagina.",
                    "Scheda di un dispositivo SNMP: uptime e «Risposte ultime 24 ore / 7 giorni», cioè quante interrogazioni hanno avuto risposta (sotto il 95% in rosso).",
                    "Le letture si fanno da sole ogni mese il giorno 1 a mezzanotte, con un secondo tentativo alle 08:00 per le macchine spente.",
                    "«? Guida» nella barra del modulo apre la guida completa da qualunque pagina.",
                ]),
            ],
        },
        {
            "id": "asset-soc",
            "titolo": "Asset e sicurezza di un apparato",
            "blocchi": [
                ("ul", [
                    "Nella scheda di un apparato, «Asset collegato» mostra l'asset dell'inventario; se apparato e asset hanno seriale, modello, IP o posizione diversi compare «Apparato e inventario non dicono la stessa cosa»: «Allinea dalla scheda asset» porta dove si applica la correzione.",
                    "Apparato senza asset: «Collega» (asset proposto) o «Crea l'asset», che lo crea con i dati letti e il punto rete con l'IP.",
                    "Riquadro «Sicurezza»: SNMP senza cifratura o community predefinita; con accesso al SOC anche firmware, CVE e alert aperti.",
                    "Firewall, switch, server, storage, UPS e videoregistratori che non rispondono per due controlli aprono un alert nel SOC, che si chiude da solo quando tornano raggiungibili.",
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
        {
            "id": "stampanti-avvisi",
            "titolo": "Una stampante: avvisi, cassetti e quando finisce il toner",
            "blocchi": [
                ("passi", [
                    "Apri la scheda della MFC (o la stampante dal Monitor SNMP): il pannello è lo stesso.",
                    "«La stampante adesso» dice lo stato, cosa c'è scritto sul display e cosa va sistemato (carta inceppata, sportello aperto, cassetto vuoto).",
                    "«Registro avvisi» elenca gli avvisi con quando sono comparsi, quando sono spariti e quanto sono durati.",
                    "Sotto ogni toner «Finisce verso il» dice la data prevista di esaurimento, calcolata sul consumo dall'ultima sostituzione.",
                    "«Sostituzioni consumabili» elenca i cambi di toner e degli altri consumabili (riconosciuti quando il livello risale di più di 5 punti), con quanto è durato il precedente e quanti cambi negli ultimi 12 mesi.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "dispositivo",
            "titolo": "Aggiungere un apparato (MFC o dispositivo SNMP)",
            "blocchi": [
                ("passi", [
                    "Clicca «+ Nuovo» → «+ Apparato». In alternativa, dalla scheda di un asset IT non monitorato: «Monitora via SNMP».",
                    "Apparato: scegli l'asset del registro; nome, matricola, modello, reparto e IP vengono presi da lì. "
                    "Il tipo «Stampante MFC a contratto» crea una MFC, gli altri un dispositivo del Monitor SNMP.",
                    "Connessione: indirizzo, versione SNMP e credenziali (con SNMPv3 la community non serve).",
                    "Verifica: un solo pulsante legge identità, modello e valori. Scegli qui il modello.",
                    "Riepilogo: se viene proposto l'asset trovato per matricola o IP, clicca «Collega questo asset», poi conferma.",
                ]),
                ("nota", "La community SNMP non è scritta nel codice: si imposta in «Configurazione» → «Impostazioni» o per apparato e resta cifrata."),
            ],
        },
        {
            "id": "fatture",
            "titolo": "Fatture del fornitore",
            "blocchi": [
                ("p", "«Fatture» → nuova fattura: si può caricare la fattura elettronica (XML o PDF di stampa) e il portale compila le righe. "
                      "La «Riconciliazione» confronta per trimestre le letture fatturate con quelle interne. I dettagli sono nella guida della riconciliazione."),
                ("passi", [
                    "Più fatture insieme (es. i trimestri passati): «Fatture» → «Importa più fatture», scegli tutti i file e premi «Leggi le fatture».",
                    "Controlla l'anteprima: le «pronte» sono già selezionate, le «da verificare» si aprono una alla volta.",
                    "«Salva le fatture selezionate»: ognuna passa gli stessi controlli della pagina singola.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Un apparato è in errore SNMP",
            "perche": "il codice dell'errore dice la causa.",
            "fare": [
                "Leggi il codice nella scheda: SNMP-001 indirizzo non valido, 002 nome non risolto, 003 nessuna risposta (spesso community sbagliata), "
                "004 credenziali v3 rifiutate, 005 dato non disponibile, 006 valore non valido, 007 permessi/gestori ammessi sull'apparato, 008 credenziali mancanti, "
                "009 SNMPv3: apparato raggiungibile ma credenziali scartate (protocollo o chiave di cifratura), 010 nessuna risposta SNMPv3 (rete, firewall, SNMPv3 non attivo).",
                "Per 003: controlla che l'apparato sia acceso e raggiungibile (ping) e che la community sia quella giusta.",
                "Per 007: sull'apparato va autorizzato l'indirizzo del server del portale come gestore SNMP.",
            ],
        },
        {
            "sintomo": "La scheda dello switch non dice chi è collegato alle porte",
            "perche": "la tabella MAC si legge ogni notte alle 05:30 solo dagli apparati di categoria «Rete» attivi e raggiungibili.",
            "fare": [
                "Controlla che lo switch sia di categoria «Rete» e risponda via SNMP.",
                "L'interruttore è nel SOC: «Impostazioni» → «Apparati di rete» → «Leggi la tabella MAC degli switch». A mano: manage.py soc_api_sync --solo switch.",
                "Un PC «non riconosciuto» ha un MAC che il portale non conosce: arriva da Intune, da WatchGuard o dal punto rete dell'asset.",
                "Gli switch Cisco con tabella MAC separata per VLAN (community@vlan) non sono coperti.",
            ],
        },
        {
            "sintomo": "Il SOC segnala «Apparato non raggiungibile»",
            "perche": "un apparato di rete non ha risposto per più controlli di fila.",
            "fare": [
                "Apri la scheda dell'apparato da Contatori IT: l'errore SNMP dice se è rete, credenziali o apparato spento.",
                "Quando l'apparato risponde di nuovo l'alert si chiude da solo; se è stato tolto, disattivalo dalla sua scheda.",
                "Il numero di controlli o l'interruttore si cambiano nel SOC: «Impostazioni» → «Apparati di rete (Contatori IT)».",
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
