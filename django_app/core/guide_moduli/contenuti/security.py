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
                ]),
            ],
        },
    ],
    "problemi": [
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
