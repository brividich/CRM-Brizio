GUIDA = {
    "slug": "security",
    "titolo": "Security Center (SOC)",
    "area": "IT e sicurezza informatica",
    "sintesi": "Allarmi di sicurezza informatica, vulnerabilità, backup e incidenti NIS2, letti dai report che arrivano per mail.",
    "parole": "soc sicurezza informatica alert allarme vulnerabilita cve backup antivirus incidente nis2",
    "url": "security:dashboard",
    "prefissi": ("/soc/",),
    "dettaglio": [
        ("Inizia da qui", "/soc/docs/00-start-here/"),
        ("Lavoro quotidiano", "/soc/docs/13-lavoro-quotidiano/"),
        ("Risoluzione problemi", "/soc/docs/09-troubleshooting/"),
    ],
    "uso": [
        {
            "id": "giorno",
            "titolo": "Il controllo di ogni mattina",
            "blocchi": [
                ("passi", [
                    "Apri il Security Center: la «Panoramica IT» dice in una riga se va tutto bene.",
                    "Guarda «Da guardare adesso»: le cose più gravi sono in cima.",
                    "Apri un allarme: «Spiega con l'AI» lo spiega in parole semplici, «Cosa sappiamo» mostra lo storico.",
                    "Decidi: prendi in carico, chiudi come risolto o scarta come falso allarme (scrivendo il perché).",
                ]),
                ("p", "La guida completa del Security Center ha un capitolo per ogni pagina: i collegamenti sono in cima."),
            ],
        },
        {
            "id": "dispositivi",
            "titolo": "Un PC o server: fonti, backup, CVE e asset in una riga",
            "blocchi": [
                ("p", "«Dispositivi › Elenco» è l'elenco unico dei PC e dei server (prima erano due pagine, «PC e fonti» e «Asset»). "
                      "Ogni riga dice quali fonti vedono il dispositivo (Intune, WatchGuard, Defender), l'esito dell'ultimo backup, "
                      "quante CVE lo colpiscono (e quante gravi) e a quale asset del registro è collegato."),
                ("passi", [
                    "Usa i filtri «Backup ko», «Con CVE» e «Senza asset» per trovare cosa sistemare: il numero accanto è uguale alle righe.",
                    "Se nella colonna «Asset del registro» c'è «Proposto», controlla e premi «Conferma» (serve il permesso di configurazione del SOC).",
                    "Il nome del dispositivo apre la sua scheda con backup, alert, vulnerabilità e protezione endpoint.",
                ]),
            ],
        },
        {
            "id": "cve-pannello",
            "titolo": "Le CVE di un programma o di un PC in un pannello",
            "blocchi": [
                ("p", "Nel Catalogo software e nella scheda di un PC (modulo Asset) il numero di CVE è un bottone: apre un pannello a destra "
                      "con le CVE dalla più pericolosa, quanti PC colpiscono e da quale versione sono corrette. Un clic su una CVE mostra "
                      "«Cosa fare» e i PC colpiti, senza lasciare la pagina. I numeri sono gli stessi del catalogo e contano solo i software "
                      "ancora presenti sui PC."),
                ("p", "Dopo un aggiornamento non si chiude niente a mano: al primo inventario con la versione nuova la CVE esce dal PC "
                      "e compare in «Risolte negli ultimi 90 giorni» con versione prima → dopo. «Programma aggiornato» e «disinstallato» "
                      "sono correzioni; «PC non più nell'inventario» e «Rivalutata» no."),
                ("p", "Ogni CVE ha una priorità: «Subito» se sfruttata (CISA KEV) o con probabilità di attacco alta (EPSS 10% o più), "
                      "«Presto» se CVSS 9 o più (o CVSS 7 con EPSS almeno 1%), altrimenti «Normale». Le CVE sono in quest'ordine."),
                ("p", "Dispositivi › «Patch e protezione»: patch mancanti per PC lette da WatchGuard (prima quelle che correggono CVE "
                      "sfruttate), installazioni non riuscite, PC con la protezione da sistemare e dispositivi in rete senza agente. "
                      "Le patch si installano dalla console WatchGuard; il pannello CVE dice su quali PC la patch è pronta."),
            ],
        },
    ],
    "admin": [
        {
            "id": "fonti",
            "titolo": "Da dove arrivano i dati",
            "blocchi": [
                ("ul", [
                    "Le caselle di posta che ricevono i report (antivirus, firewall, backup) si configurano in «Caselle mail»: creazione, anteprima, lettura manuale, importazione dello storico.",
                    "Il ciclo di lettura gira ogni 15 minuti (lavoro «security_cycle»).",
                    "Regole, soglie e AI si configurano nelle Impostazioni del Security Center (capitolo «Impostazioni e AI» della guida completa).",
                    "Alert di Microsoft Defender: Impostazioni › «Alert di Microsoft Defender». Serve il permesso Graph SecurityAlert.Read.All "
                    "con consenso amministratore sull'app del portale; prova con manage.py defender_alerts --prova.",
                    "Nella stessa sezione: «Raggruppa per incidente» (SecurityIncident.Read.All), «Leggi il software dei PC» "
                    "(Software.Read.All dell'API WindowsDefenderATP, ogni mattina alle 06:20 nell'inventario software; lo stesso software già importato da WatchGuard non si duplica: è una riga con due fonti) e «Mostra il "
                    "Secure Score» nella Panoramica (SecurityEvents.Read.All).",
                    "Microsoft Entra ID: Impostazioni › «Microsoft Entra ID». Tre interruttori: account degli ex dipendenti ancora attivi "
                    "(alert che si chiude quando l'account viene disattivato), modifiche amministrative sensibili e accessi sospetti (falliti a raffica, Paesi non ammessi, protocolli vecchi). Permessi User.Read.All e "
                    "AuditLog.Read.All; prova con manage.py entra_signals --prova.",
                    "«Confronta le CVE con Defender» (riquadro Microsoft Defender): ogni mattina alle 06:25 le CVE che Defender vede sui PC "
                    "vanno accanto al calcolo del SOC nel pannello CVE. Permessi Vulnerability.Read.All e Machine.Read.All dell'API "
                    "WindowsDefenderATP; a mano: manage.py soc_api_sync --solo defender.",
                    "WatchGuard Cloud (API): credenziali nel riquadro «Credenziali API WatchGuard» delle Impostazioni (da Managed Access: URL API, "
                    "Access ID e password di sola lettura, API Key; ID account da My Account), poi «Prova la connessione» e gli interruttori "
                    "«WatchGuard Endpoint Security (API)»: PC e protezione, software (al posto dell'export), patch. Girano alle 06:10 e 13:10; "
                    "a mano: manage.py soc_api_sync --solo watchguard.",
                    "Impostazioni › «Panoramica»: tutte le pagine di configurazione divise per compito (dati, alert, avvisi, controllo), "
                    "ognuna con il suo stato, e in cima «Da sistemare» con le cose da fare.",
                    "Impostazioni › «Letture automatiche»: una scheda per ogni lettura (caselle, Defender, Entra, Secure Score, Intune, "
                    "licenze M365, WatchGuard, CVE, switch) con ultimo giro, cosa ha letto, errore, storico e «Esegui ora» "
                    "(serve il permesso di configurazione; la pagina si aggiorna da sola finché il giro è in corso).",
                    "Backup letti direttamente da Veeam: Impostazioni › «Backup letti direttamente da Veeam». Nel .env del server "
                    "VEEAM_API_URL (https://<server>:9419), VEEAM_API_USERNAME e VEEAM_API_PASSWORD di un utente con il solo ruolo "
                    "«Veeam Backup Viewer»; se il certificato del server Veeam non è di una CA attendibile, VEEAM_API_CA_BUNDLE. "
                    "Prova con manage.py veeam_api --prova. Le mail di esito possono restare: la stessa esecuzione conta una volta sola.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una lettura resta «In coda» o diventa «Interrotta»",
            "fare": [
                "Il giro aspetta il servizio dei lavori in background (qcluster): se resta in coda il servizio è fermo.",
                "Amministrazione › Monitoring: controlla qcluster e riavvialo; poi rilancia «Esegui ora» dalla scheda.",
            ],
        },
        {
            "sintomo": "«Prova la connessione» a WatchGuard non riesce",
            "fare": [
                "«Access ID o password non validi»: ricopiali da Managed Access (attenzione a quelli di sola lettura vs lettura/scrittura).",
                "401/403 sulle letture: l'API Key non è quella dell'account o l'account non ha Endpoint Security.",
                "404: l'ID account è sbagliato (My Account, formato ACC-… o WGC-…). L'URL API deve essere quello della regione dell'account.",
                "Errore di rete: il server del portale deve raggiungere https://api.<regione>.cloud.watchguard.com (porta 443).",
            ],
        },
        {
            "sintomo": "Il Security Center non mostra dati recenti",
            "fare": [
                "Nella Panoramica guarda la «freschezza» di ogni area: quale fonte è ferma?",
                "«Caselle mail»: prova l'anteprima della casella di quella fonte.",
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla «security_cycle».",
                "Se la lettura della casella dà 401/403 il segreto dell'app Graph è scaduto: rinnovalo su Entra ID e aggiornalo dal Setup Wizard.",
                "Altri casi: capitolo «Risoluzione problemi» della guida completa.",
            ],
        },
        {
            "sintomo": "Alert «Accesso al portale non riconosciuto»",
            "fare": [
                "La persona ha premuto «Non ero io» su un accesso da un dispositivo nuovo: la sessione di quel dispositivo è già chiusa.",
                "Verifica che abbia cambiato la password; se l'account è AD, controlla anche gli accessi in Entra (stesso IP).",
                "Gli accessi da dispositivi nuovi senza segnalazione restano eventi della sorgente «Portale · accessi» (KPI), senza alert.",
            ],
        },
        {
            "sintomo": "Alert dalla sorgente «Portale · accessi» (PIN bloccato, accesso bloccato, sessione da un altro PC, 2FA bloccata)",
            "fare": [
                "«PIN di una postazione condivisa bloccato»: cinque PIN sbagliati di fila sul PC condiviso. Chiedi alla persona se era lei; "
                "il PIN si sblocca solo con uno nuovo (dalla postazione con la sua password, o «Azzera PIN» in admin-portale → Postazioni condivise).",
                "«Sessione di una postazione condivisa usata da un altro PC»: la sessione è già chiusa. Nel titolo c'è l'IP da cui è arrivata: "
                "se non è un PC aziendale noto, tratta l'account del PC condiviso come compromesso (cambio password).",
                "«Accesso al portale bloccato per troppe password sbagliate»: blocco di un'ora per quel nome utente da quell'IP. "
                "Tanti blocchi da IP diversi o su molti nomi = tentativo a tappeto.",
                "«Verifica in due passaggi bloccata»: la password era giusta, il codice no. Se non era la persona, la password è nota a qualcun altro.",
                "Ogni tipo si può lasciare solo come evento (KPI) spegnendo il suo interruttore in Impostazioni → «Eventi di sicurezza del portale».",
            ],
        },
        {
            "sintomo": "Alert «Accesso a Microsoft 365 da un Paese non ammesso»",
            "fare": [
                "Apri l'accesso in Entra (Utenti › Log di accesso) con l'IP indicato nell'alert e chiedi alla persona se era lei (viaggio, VPN).",
                "Se non era lei: cambia la password, revoca le sessioni e verifica i metodi MFA dell'account.",
                "Paesi frequenti e legittimi: aggiungili in Impostazioni › «Paesi ammessi» (es. IT, CH).",
            ],
        },
        {
            "sintomo": "Alert «Accesso con un protocollo vecchio (senza MFA)»",
            "fare": [
                "Un programma o un dispositivo usa IMAP, POP, SMTP autenticato o ActiveSync: questi protocolli non chiedono l'MFA.",
                "Individua il programma (stampante/scanner che manda mail, vecchio client di posta) e passalo a un metodo moderno.",
                "Quando non serve più, blocca l'autenticazione legacy con l'accesso condizionale in Entra.",
            ],
        },
        {
            "sintomo": "Alert «Account Microsoft 365 attivo di un ex dipendente»",
            "fare": [
                "La persona ha una data di cessazione passata in anagrafica ma il suo account Microsoft 365 è ancora abilitato.",
                "Disattiva l'account in Active Directory (o in Entra): al controllo successivo, entro 6 ore, l'alert si chiude da solo.",
                "Se la persona è ancora in forza, correggi la data di cessazione in Anagrafica: l'alert va chiuso a mano.",
                "Elenco completo: Amministrazione › Ruoli e permessi › «Account Microsoft 365».",
            ],
        },
        {
            "sintomo": "Gli alert di Microsoft Defender non arrivano nel SOC",
            "fare": [
                "Impostazioni › «Alert di Microsoft Defender»: «Leggi gli alert di Defender» deve essere acceso.",
                "Dal terminale: manage.py defender_alerts mostra l'esito dell'ultimo giro. «Graph ha risposto 403» = manca il permesso "
                "SecurityAlert.Read.All (o il consenso amministratore) sull'app del portale in Entra ID.",
                "Arriva l'evento ma non l'alert: la severità è sotto la «Severità minima per l'alert» (l'evento resta nei KPI).",
            ],
        },
        {
            "sintomo": "Il riquadro «Lettura diretta da Veeam» della pagina Backup dice «errore»",
            "fare": [
                "Il messaggio sotto il titolo dice cosa non va; lo stesso esito dal terminale con manage.py veeam_api.",
                "«Server Veeam non raggiungibile»: controlla VEEAM_API_URL e che dal server del portale la porta 9419 sia aperta.",
                "«Certificato del server Veeam non attendibile»: metti in VEEAM_API_CA_BUNDLE il percorso del certificato della CA (file .pem).",
                "«Veeam ha rifiutato l'accesso»: utente o password sbagliati, oppure l'utente non ha il ruolo «Veeam Backup Viewer».",
                "Dopo ogni modifica al .env riavvia il portale e il qcluster, poi prova con manage.py veeam_api --prova.",
            ],
        },
        {
            "sintomo": "Alert «Repository di backup quasi pieno»",
            "fare": [
                "Lo spazio libero del repository Veeam è sotto la soglia scelta in Impostazioni (default 15%).",
                "Libera spazio (retention più corta, vecchi punti di ripristino, spostamento su un altro repository) o aumentalo.",
                "L'alert si chiude da solo al primo giro in cui lo spazio libero torna sopra la soglia.",
            ],
        },
        {
            "sintomo": "Un parser è segnato «Letture da verificare» o un report ha cifre a zero",
            "perche": "Il parser riconosce il report ma non trova più un dato necessario: di solito il fornitore ha cambiato il formato della mail o del PDF.",
            "fare": [
                "Configurazione › Parser › «Prova i parser»: incolla la mail o carica il file recente.",
                "Nel riquadro «Cosa ha letto» i campi con «Manca» sono quelli che non trova più: segnalali con un esempio (dati anonimizzati).",
                "Finché non è corretto, un dato illeggibile non chiude da solo nessun alert e non conta come «tutto ok».",
                "Con la «Lettura assistita dall'AI» accesa (Impostazioni del Security Center) accanto a queste letture compare "
                "la proposta dell'AI: utile per capire cosa è cambiato, ma va confrontata con il documento.",
            ],
        },
    ],
}
