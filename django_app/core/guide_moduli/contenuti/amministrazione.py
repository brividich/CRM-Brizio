GUIDA = {
    "slug": "amministrazione",
    "titolo": "Amministrazione del portale",
    "area": "Amministrazione del portale",
    "sintesi": "Utenti, permessi, menu, notifiche, monitoraggio e strumenti per chi amministra il portale.",
    "parole": "amministrazione admin utenti permessi accessi ruoli menu monitoring backup database",
    "url": "admin_portale:index",
    "prefissi": ("/admin-portale/",),
    "dettaglio": [
        ("Guida Accessi", "admin_portale:accessi", "?guida=1"),
        ("Guida Ruoli e permessi", "admin_portale:ruoli_portale", "?tab=guida"),
    ],
    "uso": [
        {
            "id": "cosa",
            "titolo": "A cosa serve",
            "blocchi": [
                ("p", "L'Amministrazione è riservata a chi gestisce il portale. Chi usa solo i moduli non ne ha bisogno: "
                      "se vedi «Accesso negato» qui, è normale."),
            ],
        },
    ],
    "admin": [
        {
            "id": "mappa",
            "titolo": "Dove si trova cosa",
            "blocchi": [
                ("def", [
                    ("Utenti", "elenco account, disattivazione, impersonazione («vedi come»), import da Active Directory (Import Utenti LDAP)."),
                    ("Accessi", "i permessi di pagina per gruppo, ruolo o singola persona. Ha la sua guida."),
                    ("Ruoli e permessi", "il sistema unico: matrice ruolo × modulo × azione. Un ruolo si può collegare ai ruoli dell'organigramma: chi li ricopre lo riceve da solo. Ha la sua guida."),
                    ("Accessi negati", "ogni «Accesso negato» ricevuto dagli utenti, con «Consenti» / «Non consentire»."),
                    ("Navigation Builder", "le voci dei menu."),
                    ("Branding", "logo, favicon, nome e colori."),
                    ("Gestione notifiche / Log notifiche", "accendere o spegnere categorie di notifica; vedere cosa è partito e a chi."),
                    ("Audit / Attività utenti", "chi ha fatto cosa (ultimi 30 giorni), con export."),
                    ("Monitoring", "Centrale di comando, salute degli schedule, segnalazioni degli utenti."),
                    ("Hub", "moduli accesi/spenti, database (statistiche, backup), Schema DB, guide."),
                    ("Crea Release", "pacchetto di rilascio (per lo sviluppo)."),
                ]),
            ],
        },
        {
            "id": "permesso",
            "titolo": "Dare un permesso a una persona (il caso più frequente)",
            "blocchi": [
                ("passi", [
                    "Chiedi alla persona il nome della pagina bloccata, oppure apri «Accessi negati»: trovi la riga con persona, pagina e motivo.",
                    "Decidi se il permesso vale per tutto il suo ruolo o solo per lei.",
                    "Clicca «Consenti» sulla scelta giusta. Il portale scrive il permesso, lo verifica e lascia traccia nell'audit.",
                    "Falle ricaricare la pagina.",
                ]),
                ("nota", "Per vedere il portale come lo vede la persona usa l'impersonazione da «Utenti». Ricordati di uscirne (banner in alto)."),
            ],
        },
        {
            "id": "monitoring",
            "titolo": "Controllare che il portale stia bene",
            "blocchi": [
                ("ul", [
                    "Monitoring → «Centrale di comando»: versione e commit in esecuzione, migrazioni mancanti, qcluster, lavori falliti, servizi.",
                    "Monitoring → «Salute degli schedule»: ogni lavoro pianificato con l'ultimo esito. Stati: In regola, In ritardo, Ultimo run fallito, Non registrato, Mai eseguito, Disabilitato. «▶ Esegui ora» lo lancia subito.",
                    "Monitoring → segnalazioni: i problemi inviati dagli utenti con «Segnala un problema».",
                ]),
            ],
        },
        {
            "id": "database",
            "titolo": "Database",
            "blocchi": [
                ("ul", [
                    "Hub → «Database»: dimensione delle tabelle, backup, pulizia di log e sessioni.",
                    "Hub → «Schema DB»: tutte le tabelle del portale con campi e collegamenti, e le connessioni verso l'esterno. "
                    "Si genera da solo dal codice, quindi è sempre aggiornato.",
                ]),
            ],
        },
        {
            "id": "audit-politica",
            "titolo": "Cosa registra l'audit automatico",
            "blocchi": [
                ("p", "Oltre alle azioni degli utenti, il portale registra da solo inserimenti, modifiche ed eliminazioni dei dati. "
                      "Quanto registra lo decide una politica scritta nel codice (core/audit_policy.py, documento docs/dr/AUDIT_POLICY.md)."),
                ("def", [
                    ("Dati di business", "anagrafica, visite, formazione, asset, DPI, ticket, anomalie, assenze, permessi e menu: audit completo, come prima."),
                    ("Registri tecnici", "esecuzioni delle automazioni, job del Monitoraggio, letture SNMP, impatti CVE: non entrano nell'audit perché hanno già il loro registro."),
                    ("Contenuti di file e mail", "file e messaggi del Security Center, testi estratti dai documenti SGI: l'audit dice chi, quando e quali campi sono cambiati, mai il contenuto."),
                    ("Campi tecnici", "«ultima esecuzione» di una regola, «letta» di una notifica, stato SNMP di un dispositivo: da soli non generano righe."),
                ]),
                ("ul", [
                    "Un salvataggio senza modifiche reali non scrive nulla. I testi oltre 500 caratteri sono troncati: la riga riporta lunghezza e impronta del valore.",
                    "Terminale, solo lettura: hub_backup_doctor mostra spazio del database rispetto al limite di SQL Express, crescita dell'audit, previsione di saturazione e i modelli che scrivono di più.",
                    "audit_archive --plan mostra cosa si può archiviare e liberare. audit_archive --run archivia su NAS (file verificati) e poi pulisce: in produzione lo lancia solo il responsabile, dopo aver letto il --plan.",
                    "L'audit dei dati di business resta online 5 anni; gli archivi si conservano 10 anni.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "«Accesso negato» per una persona che dovrebbe entrare",
            "fare": [
                "Apri «Accessi negati» e trova la riga: il motivo è scritto in chiaro.",
                "Clicca «Consenti» sul ruolo o sulla persona.",
                "Se la riga non c'è, impersona la persona e riproduci il problema.",
                "Per i casi difficili, dal terminale: acl_diagnose --user <email> --path </pagina/> spiega la decisione passo per passo.",
            ],
        },
        {
            "sintomo": "Dopo un aggiornamento manca una voce di menu o una pagina dà errore",
            "fare": [
                "Centrale di comando: ci sono migrazioni da applicare? Se sì, il rilascio non è completo (Manuale di emergenza → «Dopo un aggiornamento»).",
                "Svuota la cache del browser (Ctrl+F5).",
            ],
        },
        {
            "sintomo": "Il database cresce troppo o il Monitoraggio segnala «audit_growth»",
            "fare": [
                "Dal terminale: hub_backup_doctor. Guarda «Top modelli»: un modello tecnico con molte righe va proposto per l'esclusione (modifica di core/audit_policy.py tramite PR).",
                "audit_archive --plan per vedere quanto spazio si libera; il --run lo lancia il responsabile.",
                "Non fare SHRINK del database: lo spazio liberato viene riusato.",
            ],
        },
    ],
}
