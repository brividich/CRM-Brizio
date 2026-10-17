"""Manuale di emergenza: cosa fare quando il portale non funziona e chi lo segue di solito è assente.

Solo per amministratori. Nessun segreto: password, chiavi e indirizzi riservati stanno
nel file .env del server, qui si dice solo dove guardare.
"""

GUIDA = {
    "slug": "emergenza",
    "titolo": "Manuale di emergenza",
    "area": "Amministrazione del portale",
    "sintesi": "Per l'amministratore di turno: dove stanno le cose sul server e cosa fare, passo per passo, quando il portale non funziona.",
    "parole": "emergenza server iis qcluster riavvio log backup rollback errore 500 502 database",
    "url": "monitoring_admin:system_status",
    "solo_admin": True,
    "uso": [
        {
            "id": "regole",
            "titolo": "Tre regole prima di toccare qualcosa",
            "blocchi": [
                ("passi", [
                    "Guarda prima, tocca dopo: apri la Centrale di comando (Amministrazione → Monitoring) e leggi cosa è rosso.",
                    "Un passo alla volta: dopo ogni azione ricarica il portale e controlla se il problema è sparito.",
                    "Scrivi cosa hai fatto e a che ora (anche su un foglio): servirà a chi rientra.",
                ]),
                ("nota", "Non cancellare file o cartelle sul server, non modificare il database a mano e non lanciare comandi che non sono in questa guida. "
                         "Se non sei sicuro, fermati: un portale fermo per un'ora è meno grave di dati persi."),
            ],
        },
        {
            "id": "mappa",
            "titolo": "Dove stanno le cose",
            "blocchi": [
                ("def", [
                    ("Server", "il server di produzione del portale (pclogsys). Si entra in Desktop remoto con un account amministratore."),
                    ("Cartella del portale", "C:\\PortaleNovicrom\\prod. Dentro: current (la versione attiva, è un collegamento a releases\\<data>), "
                                             "releases (le versioni installate), config (la configurazione), logs (i registri), venv (Python)."),
                    ("Configurazione", "C:\\PortaleNovicrom\\prod\\config\\.env. È l'UNICO file da modificare. Quello dentro current\\django_app viene "
                                       "riscritto a ogni aggiornamento: non toccarlo."),
                    ("Sito web", "IIS, sito «PortaleNovicrom-PROD», pool di applicazioni «PortaleNovicrom-PROD». IIS avvia il portale (Waitress)."),
                    ("Servizio automazioni", "attività pianificata di Windows «QCluster_PROD» nella cartella \\PortaleNovicrom\\ dell'Utilità di pianificazione, "
                                             "con il suo controllore («watchdog»). Fa girare mail, sincronizzazioni, promemoria."),
                    ("Database", "SQL Server sullo stesso server (istanza SQLEXPRESS), database di produzione."),
                    ("Registri (log)", "C:\\PortaleNovicrom\\prod\\logs: app.log (portale), qcluster.log (automazioni), automation_queue.log, waitress_stdout.log_*."),
                    ("Setup Wizard", "il programma SetupWizard.exe in C:\\PortaleNovicrom\\shared\\packages. La sua «Server Dashboard» fa quasi tutto "
                                     "senza comandi: avvia/ferma IIS e servizi, Centrale di comando, terminale con comandi pronti."),
                ]),
            ],
        },
        {
            "id": "non-si-apre",
            "titolo": "Il portale non si apre (pagina bianca, errore 500, 502 o 503)",
            "blocchi": [
                ("passi", [
                    "Prova da un altro PC e con l'indirizzo interno: se si apre, il problema è la rete o il PC dell'utente, non il portale.",
                    "Entra sul server. Apri il Setup Wizard → Server Dashboard → «Stato servizi IIS»: il sito e il pool devono essere avviati.",
                    "Se sono fermi: «Avvia». Se sono avviati: «Riavvia» il pool (in PowerShell da amministratore: Restart-WebAppPool -Name 'PortaleNovicrom-PROD').",
                    "Aspetta un minuto e ricarica il portale.",
                    "Se ancora non va: apri C:\\PortaleNovicrom\\prod\\logs\\app.log e leggi le ultime righe. Cerca «Error» o «Traceback».",
                    "Se l'errore parla di database («ODBC», «SQL Server», «10061»), vai al capitolo «Il database non risponde».",
                    "Se il problema è iniziato subito dopo un aggiornamento, vai al capitolo «Dopo un aggiornamento».",
                ]),
            ],
        },
        {
            "id": "database",
            "titolo": "Il database non risponde",
            "blocchi": [
                ("passi", [
                    "Setup Wizard → Server Dashboard → «Servizi Windows»: il servizio SQL Server (MSSQL…) deve essere «in servizio».",
                    "Se è arrestato: «Avvia». Se non parte, guarda il Visualizzatore eventi di Windows → Applicazione.",
                    "Controlla lo spazio libero sul disco C: (sotto 5 GB SQL Server può fermarsi).",
                    "Quando SQL Server è di nuovo su: riavvia il pool IIS e l'attività QCluster_PROD (capitolo «Le automazioni non partono»).",
                ]),
            ],
        },
        {
            "id": "login",
            "titolo": "Nessuno riesce a entrare",
            "blocchi": [
                ("passi", [
                    "Prova con un account amministratore locale del portale: se funziona, il problema è Active Directory (LDAP).",
                    "Amministrazione → «LDAP» (diagnostica): esegui il test. Se fallisce, controlla che il controller di dominio risponda e che la password "
                    "dell'account di servizio LDAP non sia scaduta o cambiata.",
                    "Se la password dell'account di servizio è cambiata: aggiornala con il Setup Wizard (sezione LDAP), poi riavvia il pool IIS.",
                    "Se nessuno entra, nemmeno l'amministratore: è il database o il sito (capitoli precedenti).",
                ]),
                ("p", "Un singolo utente bloccato dopo 5 tentativi sbagliati si sblocca da solo dopo un'ora, oppure subito con il comando axes_reset_username <utente>."),
            ],
        },
        {
            "id": "qcluster",
            "titolo": "Le automazioni non partono (niente mail, niente sincronizzazioni)",
            "blocchi": [
                ("passi", [
                    "Amministrazione → Monitoring → Centrale di comando: se il riquadro qcluster è rosso, il servizio automazioni è fermo.",
                    "Sul server apri l'Utilità di pianificazione → cartella PortaleNovicrom → attività «QCluster_PROD».",
                    "Se è «Pronto» (non in esecuzione): clic destro → «Esegui». Se è «In esecuzione» ma la Centrale lo dà fermo: «Termina», aspetta 30 secondi, poi «Esegui».",
                    "In alternativa: Setup Wizard → Server Dashboard → «Automazioni django-q» → riavvio.",
                    "Dopo 2 minuti ricarica la Centrale di comando: il qcluster deve risultare attivo.",
                    "I lavori saltati si possono rilanciare da Monitoring → «Salute degli schedule» → «▶ Esegui ora».",
                ]),
                ("nota", "Deve esserci UN SOLO qcluster. Due insieme mandano mail doppie. Se dopo il riavvio vedi mail doppie, termina l'attività, "
                         "chiudi in Gestione attività i processi python.exe del portale rimasti, poi riavviala una volta sola."),
                ("p", "L'attività deve girare con un account che non richiede di essere collegati (non «solo se l'utente è connesso»): "
                      "altrimenti dopo un riavvio del server non riparte. Il controllore (watchdog) lo segnala nel registro eventi."),
            ],
        },
        {
            "id": "mail",
            "titolo": "Le mail non partono",
            "blocchi": [
                ("passi", [
                    "Prima controlla che il qcluster sia attivo (capitolo precedente): molte mail partono da lì.",
                    "Amministrazione → «Log notifiche» e run log delle automazioni: c'è un errore di invio? Leggilo.",
                    "Dalla pagina delle impostazioni mail (SMTP) dell'Amministrazione invia una mail di prova.",
                    "Se la prova fallisce: il server di posta o le credenziali SMTP sono cambiati. Si correggono con il Setup Wizard (sezione SMTP), poi riavvia pool IIS e qcluster.",
                ]),
            ],
        },
        {
            "id": "graph",
            "titolo": "SharePoint, Outlook o le caselle di posta non si sincronizzano",
            "blocchi": [
                ("p", "Assenze, Rilevazione incidenti, calendario degli incontri e Security Center parlano con Microsoft 365 tramite un'app registrata su Entra ID."),
                ("passi", [
                    "Se gli errori parlano di 401, 403 o «invalid_client», il segreto dell'app è scaduto.",
                    "Su portale Azure (Entra ID) → Registrazioni app → app del portale → Certificati e segreti: crea un nuovo segreto.",
                    "Inseriscilo con il Setup Wizard (sezione Microsoft Graph / SharePoint) e salva.",
                    "Riavvia il pool IIS e il qcluster.",
                ]),
                ("nota", "Annota la data di scadenza del nuovo segreto in calendario, un mese prima."),
            ],
        },
        {
            "id": "aggiornamento",
            "titolo": "Dopo un aggiornamento qualcosa non va",
            "blocchi": [
                ("passi", [
                    "Centrale di comando: guarda «migrazioni pendenti». Se ce ne sono, l'aggiornamento non è completo.",
                    "Setup Wizard → terminale → preset di migrazione (migrate), poi riavvia pool IIS e qcluster. Il qcluster va SEMPRE riavviato dopo un migrate, "
                    "altrimenti continua a usare il codice vecchio.",
                    "Se il problema resta e il portale era a posto prima: torna alla versione precedente (capitolo successivo).",
                ]),
            ],
        },
        {
            "id": "rollback",
            "titolo": "Tornare alla versione precedente",
            "blocchi": [
                ("passi", [
                    "Apri PowerShell come amministratore sul server.",
                    "Vai in C:\\PortaleNovicrom\\prod\\current\\deployment\\scripts.",
                    "Lancia: .\\rollback-release.ps1 -Environment prod",
                    "Lo script ferma il sito, punta current alla versione precedente, riavvia e fa un controllo. Conferma quando lo chiede.",
                    "Riavvia il qcluster.",
                ]),
                ("nota", "Se l'aggiornamento aveva modificato il database (migrazioni), la versione vecchia potrebbe non funzionare del tutto. "
                         "In quel caso lascia la versione nuova e aspetta il rientro di chi segue lo sviluppo."),
            ],
        },
        {
            "id": "config",
            "titolo": "Cambiare una configurazione",
            "blocchi": [
                ("passi", [
                    "Usa il Setup Wizard quando può farlo lui (database, LDAP, SMTP, Graph, AI): scrive il file giusto.",
                    "Se devi proprio modificare a mano: SOLO C:\\PortaleNovicrom\\prod\\config\\.env. Fai prima una copia del file.",
                    "Dopo ogni modifica riavvia pool IIS e qcluster: la configurazione si legge solo all'avvio.",
                ]),
                ("nota", "Il file .env contiene password: non copiarlo, non mandarlo per mail, non incollarlo nelle chat o nell'assistente AI."),
            ],
        },
        {
            "id": "disco",
            "titolo": "Disco pieno o portale lentissimo",
            "blocchi": [
                ("passi", [
                    "Controlla lo spazio su C:. I log sono in C:\\PortaleNovicrom\\prod\\logs.",
                    "Amministrazione → Hub → «Database»: usa la pulizia di log e sessioni.",
                    "Le versioni vecchie in C:\\PortaleNovicrom\\prod\\releases si possono togliere solo se non sono «current» né la precedente: nel dubbio non toccarle.",
                ]),
            ],
        },
        {
            "id": "backup",
            "titolo": "Backup",
            "blocchi": [
                ("ul", [
                    "I backup girano da soli con i task PortaleNovicrom-Backup-PROD-* (database ogni notte alle 02:00, file alle 02:30, "
                    "fotografia della macchina alle 03:00, pulizia alle 05:00). Finiscono sulla share del NAS indicata in BACKUP_TARGET.",
                    "Per sapere se sono a posto, dal terminale: manage.py hub_backup_doctor. Righe CRIT = da sistemare subito.",
                    "Backup fuori programma (es. prima di un intervento): manage.py hub_backup --type all, poi manage.py hub_backup_verify --latest.",
                    "Lo stato si vede anche da Monitoring → «Backup e ripristino» (ultimo backup, catena dei log, prova di ripristino della domenica).",
                    "Un backup dal pulsante di Amministrazione → Hub → «Database» si può ancora fare; il ripristino da lì invece è disattivato.",
                    "Lo script deployment\\scripts\\backup-environment.ps1 -Environment prod esegue lo stesso backup verificato. Il file .env completo non va mai nel backup dei dati: sta nel Recovery Kit.",
                    "Il ripristino di un backup del database sovrascrive i dati: si fa solo dopo aver parlato con la Direzione.",
                ]),
            ],
        },
    ],
}
