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
        ("Guida Centro report", "admin_portale:centro_report", "?tab=guida"),
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
                    ("Ruoli e permessi", "il sistema unico: matrice ruolo × modulo × azione. Un ruolo si può collegare ai ruoli dell'organigramma: chi li ricopre lo riceve da solo. Ogni ruolo pronto concede già login, home/dashboard, profilo, notifiche e notizie. Ha la sua guida."),
                    ("Accessi negati", "ogni «Accesso negato» ricevuto dagli utenti, con «Consenti» / «Non consentire»."),
                    ("Navigation Builder", "le voci dei menu."),
                    ("Branding", "logo, favicon, nome e colori."),
                    ("Gestione notifiche / Log notifiche", "accendere o spegnere categorie di notifica; vedere cosa è partito e a chi."),
                    ("Centro report", "tutti i report del portale per modulo (catalogo), chi ha scaricato quale file e con quali filtri "
                                      "(registro, con impronta SHA-256, senza conservare il file) e i profili di layout dei PDF. Ha la sua guida."),
                    ("Audit / Attività utenti", "chi ha fatto cosa (ultimi 30 giorni), con export."),
                    ("Monitoring", "Centrale di comando, salute degli schedule, segnalazioni degli utenti, «Backup e ripristino»."),
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
                    "Decidi se il permesso vale per tutto il suo ruolo o solo per lei. Con «Ruoli e permessi» attivo, «il ruolo» è il ruolo del portale che comanda per la persona (quello con ordine più alto), non il ruolo del gestionale. Se la persona ha solo il ruolo base, è proposta «Solo …»: consentire al ruolo base apre la pagina a tutti.",
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
                    "Hub → «Database»: dimensione delle tabelle, backup al volo, pulizia di log e sessioni. Il ripristino da qui è disattivato.",
                    "Backup automatici e verificati: task PortaleNovicrom-Backup-<ENV>-* registrati con deployment\\scripts\\register-backup-tasks.ps1. "
                    "Ogni backup ha un manifest con le impronte dei file e viene verificato; lo stato si legge con manage.py hub_backup_doctor "
                    "(spazio, recovery model, età dell'ultimo backup, task presenti, nomi del portale) e in logs\\backup-status.json anche a database spento.",
                    "Hub → «Schema DB»: tutte le tabelle del portale con campi e collegamenti, e le connessioni verso l'esterno. "
                    "Si genera da solo dal codice, quindi è sempre aggiornato.",
                ]),
            ],
        },
        {
            "id": "backup-ripristino",
            "titolo": "Backup e ripristino",
            "blocchi": [
                ("p", "Monitoring → «Centrale di comando» → «💾 Backup e ripristino». La pagina è solo per gli amministratori del portale "
                      "e non ripristina nulla: mostra lo stato, fa verificare i backup e prepara il piano di ripristino."),
                ("def", [
                    ("RPO attuale", "quanto tempo di lavoro si perderebbe se il server si rompesse adesso: minuti dall'ultimo punto ripristinabile. "
                                    "Con i backup orari del log resta sotto l'ora (07–21); senza, arriva fino a un giorno."),
                    ("Ultimo backup completo", "data dell'ultimo backup del database riuscito e verificato. Verde fino a 26 ore, giallo fino a 50, poi rosso."),
                    ("Catena dei log", "i backup orari del log devono essere continui: «Interrotta» vuol dire che serve subito un nuovo backup completo."),
                    ("Ultima prova di ripristino", "ogni domenica il portale ripristina l'ultimo backup su una copia (nome che finisce con _drill), "
                                                   "controlla integrità, migrazioni, numero di righe e che i documenti cifrati si aprano, poi cancella la copia. "
                                                   "Verde se l'ultima prova riuscita ha meno di 8 giorni, giallo fino a 35."),
                    ("Capacità database", "spazio usato rispetto al limite di SQL Server Express (10 GB fino al 2022, 50 GB con il 2025). Giallo dal 70%, rosso dall'85%."),
                    ("Recovery Kit", "il file cifrato con .env e chiavi, custodito fuori dal server. «Da rigenerare» se dopo l'ultima esportazione "
                                     "sono cambiati il .env o le chiavi."),
                ]),
                ("passi", [
                    "«Verifica ora l'ultimo backup»: ricontrolla le impronte dei file sul NAS e il backup con SQL Server. L'esito compare nella tabella «Esecuzioni» come «Verifica».",
                    "«Scarica il piano di ripristino»: scegli data e ora (vuoto = il momento più recente) e scarichi restore-plan.json, che dice quali backup usare. Serve al tool di ripristino.",
                    "Clic su un set nella tabella: manifest leggibile, file con impronta SHA-256 e pulsante per verificare solo quel backup.",
                ]),
                ("ul", [
                    "Recovery Kit (dal terminale): manage.py hub_recovery_kit export --out <file.hubkit> crea il file cifrato con .env e certificato; "
                    "la passphrase (almeno 5 parole) si digita a mano e va custodita in busta in Direzione, separata dal file. "
                    "manage.py hub_recovery_kit verify <file> controlla che il kit apra i documenti, senza scrivere nulla.",
                    "Macchina nuova: SetupWizard.exe → «♻ Ripristina da backup» (oppure deployment\\scripts\\restore-host.ps1). "
                    "Si sceglie la cartella dei backup e il momento, si vede il piano, si fa prima la simulazione e poi il ripristino reale; "
                    "alla fine c'è il report con il tempo impiegato e le azioni manuali rimaste. Procedura completa nel runbook "
                    "(deployment\\RUNBOOK_RIPRISTINO.pdf, da tenere stampato).",
                    "Dati cancellati per errore: manage.py hub_restore_drill --stopat \"AAAA-MM-GG HH:MM\" --keep crea una copia del database "
                    "a quel momento (nome che finisce con _drill) da cui recuperare le righe; poi la copia si elimina.",
                ]),
                ("nota", "I controlli girano da soli ogni 30 minuti: se uno diventa rosso si apre una segnalazione e parte una mail agli amministratori. "
                         "Il ripristino da Hub → «Database» è disattivato: si fa solo con il tool dedicato, dopo aver parlato con la Direzione."),
            ],
        },
        {
            "id": "centro-report",
            "titolo": "Report: catalogo, registro e layout",
            "blocchi": [
                ("p", "Amministrazione → «Centro report». I report si generano sempre dal loro modulo; qui si governano tutti insieme."),
                ("def", [
                    ("Catalogo", "i report per modulo con formati, veste grafica, etichetta «Dati personali» e scaricamenti degli ultimi 30 giorni. "
                                 "In fondo, «Route da catalogare»: file scaricati da pagine che il catalogo non conosce ancora."),
                    ("Registro emissioni", "ogni file di report scaricato: chi, quando, quale report, filtri, dimensione, impronta SHA-256 e IP. "
                                           "Il file non si conserva. «Cerca» accetta anche l'impronta: dice se un file in circolazione è uscito dal portale. "
                                           "Conservazione predefinita 730 giorni (0 = sempre), pulizia ogni notte alle 02:45."),
                    ("Pianificazioni", "report con l'etichetta «Pianificabile» generati da soli ogni settimana o ogni mese e inviati per mail "
                                       "come allegato (max 10 MB). Si generano con i permessi di chi crea la pianificazione; ogni destinatario "
                                       "li riceve solo se può aprire lo stesso report. «Invia ora», «Sospendi», esito dell'ultimo invio; controllo ogni ora."),
                    ("Layout", "profili con colori, logo, piè di pagina, filigrana, data e numero di pagina, assegnati a un modulo o a un singolo report "
                               "(il report vince sul modulo). Valgono per i PDF ed Excel costruiti con il template del portale; i modelli su misura non cambiano."),
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
                    ("Dati di business", "anagrafica aziendale, formazione, asset, ticket, anomalie, assenze, permessi e menu: audit completo, come prima."),
                    ("Dati personali sensibili", "visite e referti, dati civili e familiari, retribuzioni e cedolini, candidati, "
                                                 "certificazioni di presenza, consegne DPI con firma, chat dell'AI: dal 21/10/2026 "
                                                 "l'audit dice chi, quando e quali campi, mai i valori (GDPR). Il valore resta solo nella scheda."),
                    ("Registri tecnici", "esecuzioni delle automazioni, job del Monitoraggio, letture SNMP, impatti CVE: non entrano nell'audit perché hanno già il loro registro."),
                    ("Contenuti di file e mail", "file e messaggi del Security Center, testi estratti dai documenti SGI: l'audit dice chi, quando e quali campi sono cambiati, mai il contenuto."),
                    ("Campi tecnici", "«ultima esecuzione» di una regola, «letta» di una notifica, stato SNMP di un dispositivo: da soli non generano righe."),
                ]),
                ("ul", [
                    "Un salvataggio senza modifiche reali non scrive nulla. I testi oltre 500 caratteri sono troncati: la riga riporta lunghezza e impronta del valore.",
                    "Terminale, solo lettura: hub_backup_doctor mostra spazio del database rispetto al limite di SQL Express, crescita dell'audit, previsione di saturazione e i modelli che scrivono di più.",
                    "audit_archive --plan mostra cosa si può archiviare e liberare. audit_archive --run archivia su NAS (file verificati) e poi pulisce: in produzione lo lancia solo il responsabile, dopo aver letto il --plan.",
                    "L'audit dei dati di business resta online 5 anni; gli archivi si conservano 10 anni.",
                    "Le righe scritte prima del 21/10/2026 con i valori dei dati sensibili si riducono a soli metadati con "
                    "audit_archive --run --category contenuti: non toccano il sigillo mensile, che non contiene le righe automatiche.",
                ]),
            ],
        },
        {
            "id": "conservazione-archivi",
            "titolo": "Conservazione dei dati negli archivi tecnici (GDPR)",
            "blocchi": [
                ("p", "Ogni notte alle 03:15 il lavoro «gdpr_retention» cancella, o svuota dove la riga serve ancora, i dati "
                      "personali degli archivi tecnici oltre il loro termine. Il registro attività riporta quante righe per archivio."),
                ("def", [
                    ("Monitoraggio", "occorrenze degli errori 90 giorni; segnalazioni degli utenti 12 mesi, solo con la segnalazione chiusa; "
                                     "esecuzioni dei job 30 giorni, tenendo sempre l'ultima di ogni job."),
                    ("Assistente AI", "feedback della chat 90 giorni. Le conversazioni hanno già la loro pulizia a 90 giorni."),
                    ("Automazioni", "link e risposte di approvazione 6 mesi, solo per richieste già decise o scadute: chi ha deciso e quando resta."),
                    ("SOC", "dopo 12 mesi i messaggi della casella perdono mittente, corpo e originale (restano oggetto e collegamenti); "
                            "chat e log dell'AI del SOC cancellati."),
                    ("Accessi", "tentativi di accesso (blocco account) 90 giorni; sessioni scadute ogni notte."),
                ]),
                ("ul", [
                    "Ogni termine si cambia in SiteConfig con la chiave gdpr_ret_<archivio>_giorni (minimo 7, massimo 3650).",
                    "Dal terminale: gdpr_retention mostra quante righe toccherebbe, senza cambiare nulla; gdpr_retention --apply applica; "
                    "--solo <archivio> per uno solo.",
                    "I dati di dipendenti e candidati non si cancellano da soli: Anagrafica → Impostazioni → «Conservazione dei dati», con conferma.",
                    "L'elenco completo, con i termini, è in docs/audit/RETENTION_DATI_PERSONALI.md.",
                ]),
            ],
        },
        {
            "id": "protezione-dati",
            "titolo": "Protezione dei dati personali: cifratura, log, letture, invii esterni",
            "blocchi": [
                ("def", [
                    ("Campi cifrati", "IBAN, prescrizioni e note delle visite, giudizio letto dai referti e firma delle "
                                      "consegne DPI sono cifrati nel database con la chiave dei documenti (DOCUMENT_ENCRYPTION_KEY). "
                                      "Nel portale si vedono normalmente; non si possono cercare per valore. Dopo l'aggiornamento: "
                                      "cifra_campi_esistenti (anteprima), poi --apply; dopo un cambio di chiave --apply --ruota."),
                    ("Log", "codici fiscali e IBAN sono mascherati in ogni log (RSS***********01U) anche dentro gli errori."),
                    ("Letture", "aprire la scheda di un dipendente o di un candidato, i ratei e le retribuzioni va nel registro "
                                "attività, al più una riga all'ora per persona e pagina. Le visite erano già tracciate."),
                    ("Invii esterni", "l'azione «HTTP request» delle automazioni chiama solo i servizi Microsoft (Power Automate, "
                                      "webhook Teams, Outlook, Graph) e gli host aggiunti in SiteConfig «automazioni_http_host_esterni» "
                                      "(separati da virgola) o in AUTOMATION_HTTP_EXTERNAL_HOSTS. Prima di aggiungerne uno verifica "
                                      "che possa ricevere i dati del record. automazioni_http_host_report elenca le azioni e chi verrebbe bloccato."),
                ]),
            ],
        },
        {
            "id": "allarmi-server",
            "titolo": "Allarmi del server",
            "blocchi": [
                ("p", "Ogni 30 minuti (lavoro «infra_health_alert») il portale controlla quattro cose e le mostra nella Centrale di comando:"),
                ("def", [
                    ("qcluster", "l'ultimo lavoro pianificato completato. Oltre 40 minuti senza niente = qcluster fermo: automazioni, mail e SOC non girano."),
                    ("qcluster_coda", "lavori in attesa (oltre 50 = avviso) e lavori falliti nelle ultime 24 ore, con il nome."),
                    ("disk_space", "spazio libero dei dischi con log, file caricati, archivi privati e area dei backup: sotto il 15% avviso, sotto il 5% guasto."),
                    ("tls_cert", "giorni alla scadenza del certificato https del portale: 30 avviso, 7 guasto."),
                    ("m365_servizi", "servizi Microsoft 365 da cui dipende il portale (Exchange, SharePoint, OneDrive, Teams, Entra, Intune, "
                                     "Defender): avviso se Microsoft segnala un disservizio in corso, mai guasto. Spiega perché caselle, "
                                     "SharePoint o calendari non rispondono. Permesso Graph ServiceHealth.Read.All; letto ogni 15 minuti."),
                ]),
                ("ul", [
                    "Avvisi e guasti aprono una segnalazione nella Centrale, che si chiude da sola quando torna tutto a posto.",
                    "Solo i guasti mandano una mail agli amministratori, una volta per problema, mai di notte (stesse regole degli allarmi dei backup).",
                    "Se il qcluster è fermo, l'allarme dal qcluster non parte: registra anche il comando infra_health_alert in Utilità di pianificazione "
                    "(register-backup-tasks.ps1 -IncludeInfraAlert). Dal terminale: infra_health_alert --solo-mostra mostra lo stato senza avvisare.",
                ]),
            ],
        },
        {
            "id": "audit-sigillo",
            "titolo": "Audit sigillato (non modificabile)",
            "blocchi": [
                ("p", "Il giorno 1 di ogni mese (alle 3:40, lavoro «audit_sigilli») il portale chiude il mese appena finito con un sigillo: "
                      "un'impronta (SHA-256) di tutte le azioni registrate quel mese, legata all'impronta del mese prima. Se qualcuno cambia, "
                      "aggiunge o toglie una riga di un mese chiuso, il sigillo non torna più e la catena si rompe da lì in avanti."),
                ("def", [
                    ("Cosa copre", "le azioni esplicite: accessi, approvazioni, permessi, impostazioni, attivazioni e revoche. Le righe tecniche "
                                   "automatiche (inserimenti/modifiche dei dati) restano fuori, perché l'archiviazione le riduce per politica."),
                    ("Verifica", "a ogni giro tutta la catena viene ricalcolata; se è rotta parte una mail agli amministratori."),
                    ("Export", "per ogni mese due file nella cartella SharePoint configurata: le righe (audit-AAAA-MM.jsonl.gz) e il sigillo "
                               "(audit-AAAA-MM.sigillo.json). Un file già presente non viene mai sovrascritto."),
                ]),
                ("passi", [
                    "Scegli la cartella SharePoint (meglio una raccolta con etichetta di conservazione o in sola lettura per le persone).",
                    "Dai all'app Graph del portale il permesso di scrittura su quel sito (Sites.Selected con «write», o Sites.ReadWrite.All).",
                    "Apri la cartella in SharePoint, copia l'indirizzo dalla barra del browser (o «Copia collegamento») e dal terminale lancia: "
                    "audit_sigilli --cartella-sharepoint \"<link>\". Il portale ricava raccolta e percorso, scrive nella cartella "
                    "il file LEGGIMI-portale-audit.txt (prova del permesso di scrittura) e solo allora salva la destinazione.",
                    "Dal terminale: audit_sigilli --esporta carica subito i mesi in attesa; audit_sigilli senza opzioni mostra lo stato di ogni mese.",
                ]),
                ("nota", "audit_sigilli --verifica ricalcola tutto e segnala i mesi alterati. I mesi oltre i 5 anni, tolti dal database "
                         "dall'archiviazione, risultano «in archivio»: si controllano sui file esportati."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Mail «[SERVER CRITICO] qcluster»",
            "fare": [
                "Il qcluster non completa lavori da oltre 40 minuti: riavvialo (Manuale di emergenza → «qcluster»).",
                "Dopo il riavvio la segnalazione nella Centrale si chiude da sola al giro successivo.",
            ],
        },
        {
            "sintomo": "Mail «[SERVER CRITICO] disk_space» o «tls_cert»",
            "fare": [
                "disk_space: la mail dice quale disco e quali cartelle. Libera spazio (log vecchi, area di lavoro dei backup) o allarga il disco.",
                "tls_cert: il certificato https sta per scadere o è scaduto: rinnovalo e aggiornalo nel binding https di IIS.",
            ],
        },
        {
            "sintomo": "Mail «[AUDIT] Catena dei sigilli rotta»",
            "fare": [
                "Dal terminale: audit_sigilli --verifica dice quali mesi e perché (righe aggiunte o tolte, contenuto modificato, sigillo modificato).",
                "Confronta con i file esportati su SharePoint di quel mese (audit_sigilli --file AAAA-MM --out <cartella> ricrea quelli attuali).",
                "È un possibile evento di sicurezza: non correggere a mano le righe, apri un incidente nel Security Center e conserva le prove.",
            ],
        },
        {
            "sintomo": "«Accesso negato» per una persona che dovrebbe entrare",
            "fare": [
                "Apri «Accessi negati» e trova la riga: il motivo è scritto in chiaro.",
                "Clicca «Consenti» sul ruolo o sulla persona.",
                "Se dice «Salvato, ma … resta bloccato», leggi il motivo: prevale un'eccezione personale che nega o un ruolo di ordine più alto che nega. Usa «Solo …» oppure correggi quel ruolo in «Ruoli e permessi».",
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
