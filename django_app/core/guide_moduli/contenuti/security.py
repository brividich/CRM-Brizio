GUIDA = {
    "slug": "security",
    "titolo": "Security Center (SOC)",
    "area": "IT e sicurezza informatica",
    "sintesi": "Allarmi di sicurezza informatica, vulnerabilità, backup e incidenti NIS2, letti dai report che arrivano per mail.",
    "parole": "soc sicurezza informatica alert allarme vulnerabilita cve backup antivirus incidente nis2 "
              "registro accessi log amministratori di sistema garante 27001 esxi syslog active directory",
    "url": "security:dashboard",
    "prefissi": ("/soc/",),
    "dettaglio": [
        ("Inizia da qui", "/soc/docs/00-start-here/"),
        ("Lavoro quotidiano", "/soc/docs/13-lavoro-quotidiano/"),
        ("Risoluzione problemi", "/soc/docs/09-troubleshooting/"),
        ("Registro accessi", "/soc/docs/18-registro-accessi/"),
        ("Conformità ISO 27001", "/soc/docs/19-conformita-iso27001/"),
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
                    "Sotto il nome c'è l'indirizzo IP letto dal DHCP/DNS e, se noto, lo switch e la porta: un clic apre «Rete (IP)».",
                ]),
            ],
        },
        {
            "id": "rete-ip",
            "titolo": "Rete (IP): dispositivi non censiti e senza antivirus",
            "blocchi": [
                ("p", "Dispositivi › «Rete (IP)» è la stessa vista di Asset › Indirizzi IP: ogni indirizzo del DHCP e del DNS di Windows "
                      "Server con switch e porta, fonti che lo vedono (DHCP, DNS, Switch, WatchGuard, Intune) e asset del registro."),
                ("passi", [
                    "Riquadro «Non censiti»: nessun asset ha quel MAC, IP o nome. «Crea asset» lo censisce con i dati già compilati.",
                    "Riquadro «Senza antivirus»: WatchGuard lo vede senza agente, o è un PC del registro assente da WatchGuard e Defender.",
                    "Riquadro «Da collegare»: premi «Conferma» per collegare l'indirizzo all'asset proposto (serve il permesso di modificare l'asset).",
                ]),
                ("p", "Un MAC mai visto prima, senza asset né proposta, apre l'evento «Dispositivo sconosciuto nuovo in rete» "
                      "(esclusi i MAC privati dei telefoni, al massimo 10 per lettura, uno per MAC). L'alert si accende o spegne in "
                      "Impostazioni › Avvisi e automatismi. I server DHCP e DNS si configurano in Asset › Indirizzi IP."),
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
        {
            "id": "cve-chiusura",
            "titolo": "Quando l'aggiornamento ha corretto la CVE: l'alert si chiude con le prove",
            "blocchi": [
                ("p", "L'alert «PC con versione vulnerabile» di una CVE critica o sfruttata segue i PC a ogni ricalcolo: il titolo dice "
                      "«3 PC su 5 ancora con versione vulnerabile» e ogni PC che esce lascia una voce nella timeline (aggiornato da 1.2 a 1.4 "
                      "il tal giorno, con le prove). Il riquadro «Chiusura con prove» nella scheda dell'alert mostra lo stato di ogni PC."),
                ("p", "Si chiude da solo (regola «CVE critica corretta con prove», accesa) quando nessun PC è più impattato né da verificare "
                      "e ogni PC che era esposto ha due prove concordi tra: inventario recente con la versione corretta o il programma "
                      "rimosso; patch WatchGuard non più mancante o installata; Defender che non la segnala più. Con una prova sola il PC "
                      "è «in attesa di conferma» e l'alert resta aperto; un PC non più visto è «non verificabile» finché chi ha il permesso "
                      "di configurazione non lo esclude dalla verifica, con motivo scritto in timeline. Il ticket si chiude con l'alert."),
                ("p", "Se la versione vulnerabile ricompare entro 90 giorni, lo stesso alert si riapre come «Recidiva», con la sua storia. "
                      "La pagina Vulnerabilità mostra i numeri degli ultimi 90 giorni: PC corretti, giorni medi dall'esposizione alla "
                      "correzione, chiusure da sole e a mano, recidive."),
            ],
        },
        {
            "id": "registro-accessi",
            "titolo": "Registro accessi: log dei server e amministratori di sistema",
            "blocchi": [
                ("p", "Menu del SOC › «Registro accessi». Raccoglie i log dei server Windows, dei controller di dominio, di ESXi, "
                      "degli switch, del firewall e del NAS in un archivio sigillato che vale come registro degli accessi degli "
                      "amministratori di sistema (Garante) e come evidenza ISO 27001."),
                ("passi", [
                    "«Panoramica»: pallino verde = raccolta attiva; «Come iniziare» dice i passi che mancano.",
                    "«Eventi»: viste rapide «Accessi degli amministratori», «Fuori orario», «Non riusciti», «Modifiche ad account e "
                    "gruppi», «Critici». Clic sulla data per l'evento originale.",
                    "«Amministratori di sistema»: elenco con account usati, sistemi, nomina in PDF, revisione e revoca.",
                    "«Account AD»: «Da sistemare» mostra ex dipendenti con l'account attivo, amministratori senza nomina, account senza persona.",
                    "«Verifica annuale»: lista di controllo dell'anno, PDF del verbale, esito da registrare.",
                    "«Archivio e integrità»: un sigillo per giorno; le interruzioni della raccolta si giustificano qui.",
                    "«Indagini» (solo chi configura il SOC): accessi ai file, stampe e chiavette USB si consultano solo "
                    "aprendo un'indagine con motivo, persone e periodo (es. sospetto furto di file); tutto resta nell'audit. "
                    "Si raccolgono solo dopo la conferma «Informativa ai dipendenti e accordi verificati» in Fonti.",
                ]),
            ],
        },
        {
            "id": "iso27001",
            "titolo": "Conformità ISO 27001: controlli verificati dai dati e pacchetto mensile",
            "blocchi": [
                ("p", "Menu del SOC › Report › «Conformità ISO 27001». Un riquadro per ogni controllo dell'Annex A che il SOC copre "
                      "(5.7, 8.8, 8.7, 6.8, 5.24-5.28, 8.13, 5.30, 8.15, 8.16, 8.17, 9.1): cosa si aspetta l'audit, l'esito calcolato "
                      "dai dati del SOC, i numeri, cosa fare e i collegamenti alle pagine che fanno da evidenza. Un dato che manca "
                      "non vale mai come conforme."),
                ("passi", [
                    "Scegli il periodo in alto (mese corrente, mese scorso, 3 mesi, 12 mesi, libero).",
                    "«Da sistemare» elenca i controlli non conformi o da guardare, dal più grave: ogni riga dice cosa fare.",
                    "Il giorno 1 di ogni mese alle 06:30 il SOC archivia da solo il PDF «Evidenze SOC – ISO/IEC 27001» del mese "
                    "prima (controlli, CVE corrette con versione prima e dopo, esposizioni scadute, incidenti con lezioni apprese), "
                    "con impronta SHA-256 nell'audit; «Genera ora» lo fa subito per il periodo scelto (serve il permesso di configurazione).",
                    "«Scarica PDF» in fondo alla pagina: ogni download è registrato nell'audit.",
                ]),
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
                    "licenze M365, WatchGuard, CVE, proposte AI, switch) con ultimo giro, cosa ha letto, errore, storico e «Esegui ora» "
                    "(serve il permesso di configurazione; la pagina si aggiorna da sola finché il giro è in corso).",
                    "Impostazioni › «Battito del SOC»: tutto quello che il SOC fa da solo in una schermata. Coda dei lavori "
                    "(qcluster) viva o ferma, letture in ritardo o in errore con la spiegazione, prossimi giri e mappa degli "
                    "ultimi 14 giorni (un quadretto per giorno: verde tutti i giri riusciti, arancione qualcuno no, rosso "
                    "nessuno, bordo tratteggiato non ha girato).",
                    "Proposte AI su CPE ed esiti da verificare: Impostazioni › «Proposte AI su CPE ed esiti da verificare» (spenta di serie; "
                    "massimo 5 casi per giro, confidenza minima 60). L'AI locale propone a quale CPE collegare un software (solo fra quelli "
                    "delle CVE già nel sistema) o l'esito di una CVE su un PC quando la versione non si confronta; si accetta o rifiuta in "
                    "Configurazione › Inventario software › Software e CPE (filtro «Proposte AI», pulsante «Proponi con l'AI ora») e nella "
                    "scheda CVE. Accettare equivale a una conferma a mano, con audit; nulla viene deciso dall'AI da solo.",
                    "Registro accessi: SOC › Registro accessi › «Fonti». Server Windows letti senza agent (account del raccoglitore nel "
                    "gruppo «Event Log Readers», regola firewall «Gestione remota registro eventi»), oppure Windows Event Forwarding; "
                    "ESXi, switch, firewall e NAS via syslog verso il server del portale (porta 514, solo gli IP scritti nella fonte). "
                    "Il raccoglitore è un servizio di Windows: deployment/scripts/install-registro-log-task.ps1 (stesso account del "
                    "qcluster). Conservazione minima 6 mesi, seconda copia su cartella di rete o SharePoint. Alert nel SOC: sezione "
                    "«Registro accessi» di Avvisi e automatismi. ESXi/vCenter e iLO/iDRAC in «Server e virtualizzazione».",
                    "Registro accessi come BusinessLog: fonte «Tutti i PC del dominio» (elenco da Active Directory, ogni PC "
                    "acceso letto ogni 10 minuti, pagina «PC» per stato ed esclusioni), «Cartelle sorvegliate» sul file server "
                    "(percorso | letture, scritture, eliminazioni), file copiati su chiavetta con «Controlla Archivio rimovibile». "
                    "Valgono le voci di controllo già messe per BusinessLog. Durante il passaggio: in BusinessLog spegnere "
                    "«Cancella Registro» e scrivere il suo account in Fonti › Impostazioni › «Account dei raccoglitori di log».",
                    "Conformità ISO 27001: Impostazioni › Avvisi e automatismi › «Conformità ISO 27001» ha due voci che il SOC non può "
                    "decidere da solo: il canale con cui il personale segnala un sospetto (controllo 6.8; vuoto = «da definire») e "
                    "l'interruttore per copiare il pacchetto mensile nella cartella SharePoint dell'audit (sottocartella soc-iso27001, "
                    "spento di serie). Schedule security_pacchetto_iso (1° del mese, 06:30), lettura «pacchetto_iso».",
                    "Backup letti direttamente da Veeam: Impostazioni › riquadro «Credenziali API Veeam» (indirizzo https://<server>:9419, "
                    "utente con il solo ruolo «Veeam Backup Viewer», password cifrata, certificato della CA se serve), «Prova la connessione», "
                    "poi l'interruttore «Leggi i backup dall'API di Veeam». Le mail di esito possono restare: la stessa esecuzione conta una volta sola.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Sembra che il SOC non legga più niente (alert, backup, CVE fermi)",
            "fare": [
                "Apri Impostazioni › «Battito del SOC»: in alto lo stato della coda dei lavori (qcluster).",
                "«Il qcluster sembra fermo»: riavvia il servizio dei lavori in background sul server del portale; dopo pochi minuti la mappa torna verde.",
                "Coda regolare ma una lettura «In ritardo» o rossa: aprila in «Letture automatiche», premi «Esegui ora» e leggi l'errore.",
                "«Schedule non registrato»: dopo un aggiornamento manca setup_q_schedules sul server.",
            ],
        },
        {
            "sintomo": "Registro accessi: «Raccoglitore fermo» o una fonte in errore",
            "fare": [
                "Raccoglitore fermo: sul server del portale avvia il task «RegistroLog_<ambiente>» (cartella PortaleNovicrom dell'Utilità di pianificazione; log in logs/registro_log.log).",
                "«Accesso negato al registro eventi»: l'account del raccoglitore non è nel gruppo «Event Log Readers» del server.",
                "«Server non raggiungibile per la lettura remota (RPC)»: regola firewall «Gestione remota registro eventi» sul server.",
                "Syslog muto: porta 514 non aperta nel firewall di Windows del server del portale o IP dell'apparato diverso da quello della fonte.",
                "Ogni periodo senza raccolta resta tra le interruzioni (Archivio e integrità): scrivi la giustificazione.",
            ],
        },
        {
            "sintomo": "La lettura «Proposte AI su CPE ed esiti» non riesce o non propone nulla",
            "fare": [
                "«AI locale non raggiungibile» o «modello non caricato»: il server Ollama è spento o il modello non c'è. Setup Wizard › Assistente AI › verifica; Centrale di comando.",
                "«Risposte scartate» alte: l'AI ha proposto CPE fuori dai candidati o versioni non presenti nei dati; abbassa con cautela la «Confidenza minima» solo se le motivazioni che vedi sono buone.",
                "Nessun caso esaminato: i software in «Da decidere» hanno già una proposta aperta o rifiutata con gli stessi dati; decidi quelle aperte o aspetta nuove CVE/inventari.",
                "Un software senza CPE candidati o con inventario più vecchio di 30 giorni non viene chiesto all'AI: serve un inventario nuovo o una decisione a mano.",
            ],
        },
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
                "Il messaggio sotto il titolo dice cosa non va; Impostazioni › «Credenziali API Veeam» › «Prova la connessione» lo ripete.",
                "«Server Veeam non raggiungibile»: controlla l'indirizzo nelle credenziali e che dal server del portale la porta 9419 sia aperta.",
                "«Certificato del server Veeam non attendibile»: incolla nelle credenziali il certificato della CA interna (formato PEM).",
                "«Veeam ha rifiutato l'accesso»: utente o password sbagliati, oppure l'utente non ha il ruolo «Veeam Backup Viewer».",
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
