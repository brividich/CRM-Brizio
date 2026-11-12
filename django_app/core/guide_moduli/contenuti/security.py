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
                    "«Proponi la soluzione» dà causa probabile, passi e verifica, e prepara il modulo di chiusura con esito e motivo: chiudi tu, dopo aver controllato.",
                    "Per correggere una CVE: Vulnerabilità › scheda della CVE › «Apri il lavoro di correzione» crea un caso con un'attività per PC, che si spunta e si chiude da solo quando l'inventario vede la correzione.",
                    "In Segnalazioni › «Tutte» seleziona più righe con le caselle (un tipo alla volta: alert, ticket o incidenti) e usa la barra in basso: prendi in carico, chiudi, falso positivo, apri un ticket; per i ticket assegna o cambia stato. Dall'anteprima di un alert il riquadro «Alert simili» dice quanti altri alert aperti hanno la stessa CVE, lo stesso software o lo stesso PC, e come sono già stati chiusi gli altri (esito, chi, quando, motivo): con «Chiudi insieme» li chiudi tutti con un motivo solo.",
                    "Apri Segnalazioni › «Proposte AI»: gli alert aperti sono raggruppati per tipo e per PC, job o utente, e con «Chiudi i N alert» decidi una volta per tutto il gruppo, con il motivo. Ogni 15 minuti l'AI confronta gli alert aperti con i report arrivati dopo e con le vostre decisioni, "
                    "e propone come chiuderli. «Conferma e chiudi» o «Scarta» (scrivendo perché): ogni decisione le insegna, e i tipi di alert "
                    "con 5 conferme di fila li chiude da sola (mai critici, minacce o CVE sfruttate). Se ne chiude uno per sbaglio, «Riapri».",
                    "Decidi: prendi in carico, chiudi come risolto o scarta come falso allarme (scrivendo il perché).",
                ]),
                ("p", "La guida completa del Security Center ha un capitolo per ogni pagina: i collegamenti sono in cima."),
            ],
        },
        {
            "id": "iso_incidenti",
            "titolo": "Incidenti secondo ISO 27001: tempi, riesame, prove, ripristini",
            "blocchi": [
                ("ul", [
                    "Ogni alert va preso in carico entro un tempo per gravità (critica 1 ora, alta 4, media 24, bassa 72): oltre, l'alert mostra «oltre il tempo di presa in carico» e, se acceso, parte un avviso.",
                    "Incidente risolto o chiuso: compila «Lezioni apprese» (causa, cosa ha funzionato, cosa migliorare) e le azioni correttive con responsabile e scadenza. Finché manca, l'incidente dice «Riesame mancante» e dopo 7 giorni arriva un promemoria; nessuna chiusura viene bloccata.",
                    "Evidenze di un alert: «Verifica integrità» ricalcola l'impronta SHA-256 e dice se sono integre o alterate; «Esporta» scarica tutto con la catena di custodia.",
                    "Backup › Prove di ripristino: registra ogni prova di ripristino; una fallita apre un alert, una in ritardo oltre i 90 giorni manda un promemoria.",
                    "Backup: clic su un PC o su un job apre il pannello laterale con gli alert di backup aperti, «Prendo in carico» e «Chiudi» (esito e motivo); "
                    "seleziona più PC, job o righe del Log per aprire un ticket, prendere in carico o chiudere insieme i loro alert.",
                    "Dispositivi e Installazioni non riuscite: seleziona più PC e «Apri un ticket per questi PC» (un'attività per PC). "
                    "Soppressioni e Rischi accettati: seleziona e revoca insieme con un motivo unico. Accessi VPN: clic su una riga = pannello dell'utente; "
                    "«Tutti i suoi accessi» filtra sul nome esatto.",
                    "Dispositivi: «Collega gli asset proposti» collega all'asset proposto solo i PC selezionati (serve il permesso di configurazione). "
                    "Tempi delle patch › Patch ferme e Vulnerabilità › Asset più esposti: seleziona e «Apri un ticket per questi PC».",
                    "Scheda CVE, tabella «Esito per host»: clic sulla riga = pannello del PC; seleziona più PC per aprire un ticket, «Accetta il rischio» "
                    "(stessi campi e permesso dell'accettazione singola) o «Conferma le proposte dell'AI».",
                    "Alert: nella barra della selezione «Rimanda fino al…» rimanda gli alert al giorno scelto. Proposte AI › Chiusi dall'AI: "
                    "«Riapri le selezionate» con il perché obbligatorio. Da fare: alert e ticket per gravità, clic sulla riga = pannello.",
                    "Pannelli: nel ticket «Cambia stato» (per chiudere serve l'esito), nell'incidente «Assegna a me», nel PC «Apri un ticket per questo PC». "
                    "Storico › Falsi positivi ricorrenti: «Crea soppressione» apre il modulo già compilato, da rivedere prima di salvare.",
                    "«Scarica CSV» accanto ai filtri di Segnalazioni, Alert, Ticket, Incidenti, Eventi, Accessi VPN, Dispositivi, Backup › Log "
                    "completo e Vulnerabilità (sul registro in Prove di ripristino): tutte le righe dei filtri scelti, anche oltre la pagina o il "
                    "taglio a video, colonne in italiano, celle protette dalle formule di Excel; ogni scarico resta nell'audit.",
                    "Soppressioni: 14 giorni prima della scadenza di una soppressione nasce un alert «Soppressione … in scadenza», uno per "
                    "regola e scadenza. I giorni (Impostazioni › «Soppressioni in scadenza») valgono anche per il filtro «In scadenza» della pagina.",
                ]),
                ("p", "Ruoli e contatti per gli incidenti (responsabile, sostituto, CSIRT/ACN, fornitore) si scrivono in Impostazioni › Gestione degli incidenti e compaiono nella scheda e nel PDF dell'incidente."),
            ],
        },
        {
            "id": "dispositivi",
            "titolo": "Un PC o server: fonti, backup, CVE e asset in una riga",
            "blocchi": [
                ("p", "«Dispositivi › Elenco» è l'elenco unico dei PC e dei server (prima erano due pagine, «PC e fonti» e «Asset»). "
                      "Ogni riga dice quali fonti vedono il dispositivo (Intune, WatchGuard, Defender), l'esito dell'ultimo backup, "
                      "quante CVE uniche lo colpiscono (inventario più Defender, ogni CVE una volta; e quante gravi) e a quale asset del registro è collegato. "
                      "Lo stesso numero di CVE compare nella scheda e nel pannello del PC; «Backup ko» guarda gli ultimi 90 giorni come il numero sul menu."),
                ("passi", [
                    "Usa i filtri «Backup ko», «Con CVE» e «Senza asset» per trovare cosa sistemare: il numero accanto è uguale alle righe.",
                    "La colonna «Sistema» dice la release di Windows (verde supportata, rosso fuori supporto, giallo in scadenza); la striscia gialla sotto i filtri «N PC con Windows da aggiornare» ha il pulsante «Apri il piano» e, a caso aperto, la barra «N su M PC aggiornati».",
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
                ("p", "In «Patch e protezione» si cerca per KB, CVE, patch, programma o PC. Una patch Microsoft già compresa in un "
                      "aggiornamento più recente che manca sullo stesso PC dice «Compresa in KB…» e va in fondo; quella più recente "
                      "dice «Comprende anche» e quante CVE in più chiude. Si riconosce dal build di Windows nel nome e, con "
                      "l'interruttore «Cerca le patch comprese in una più recente (Microsoft)», dal Security Update Guide di Microsoft."),
                ("p", "Aprendo una patch e nel pannello di una CVE, «Spiega con l'AI» dice cosa corregge, quanto è urgente e come "
                      "procedere. Con «Cerca anche sul web» (Impostazioni › «Ricerca sul web per l'AI», spenta di serie) l'AI legge anche "
                      "l'articolo Microsoft della KB con i problemi noti e gli avvisi del produttore della CVE; escono solo codici pubblici "
                      "(CVE, KB, codici d'errore), mai nomi di PC o utenti, e le fonti lette compaiono sotto la risposta."),
                ("p", "Dispositivi › «Patch installate»: lo storico delle patch chiuse, con PC, CVE corrette e motivo "
                      "(«Installata» se lo dice un task WatchGuard, «Non più segnalata da WatchGuard», «PC non più in WatchGuard»). "
                      "Filtri per periodo, motivo e testo; «Scarica CSV» esporta tutte le righe del filtro."),
                ("p", "Dispositivi › «Installazioni da console»: lo storico dei task di installazione patch lanciati dalla console "
                      "WatchGuard, con PC, riuscite, errori e in attesa; aprendo un task, l'esito per PC. Si legge ogni ora dalle 07:40 "
                      "alle 19:40 (lun-ven) con l'interruttore «Patch»; i task restano nel SOC anche se cancellati dalla console. "
                      "Quando un task finisce si rileggono subito patch e software: le CVE si ricalcolano e gli alert si chiudono "
                      "con le solite prove. Aprendo il task, per ogni PC le CVE della patch: Corretta, Ancora vulnerabile, Da "
                      "verificare, Non nel calcolo del SOC."),
                ("p", "Dispositivi › «Tempi delle patch»: ogni patch mancante ha un termine da «pubblicata il» secondo la classe "
                      "(corregge una CVE sfruttata 7 giorni, critica 14, importante 30, moderata e altre 90; si cambiano in Impostazioni › "
                      "«Patch: tempi di installazione»). La pagina mostra il tempo medio di installazione e quante entro il termine per "
                      "classe, l'andamento settimanale di installate e mancanti, e le patch ferme (oltre il termine o con l'installazione "
                      "fallita) con CSV. Con l'interruttore acceso (spento di default) ogni patch oltre il termine apre un alert che si chiude "
                      "da solo. Gli stessi numeri sono nel report periodico, nel controllo ISO 8.8 e nel riquadro «Patch» della scheda asset."),
                ("p", "Dispositivi › «Librerie del portale»: le vulnerabilità note nelle librerie Python del portale, confrontate ogni "
                      "mattina alle 06:50 con il database pubblico OSV (lo stesso di pip-audit). Per ogni libreria: versione installata, "
                      "gravità, vulnerabilità e «Aggiornare almeno a». Si chiudono da sole dopo l'aggiornamento nell'ambiente del portale "
                      "(pip install -r requirements.txt e riavvio); un alert per libreria, acceso di default. Se OSV non risponde la "
                      "lettura va in errore, mai «nessuna vulnerabilità»."),
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
            "id": "windows-per-build",
            "titolo": "Windows: release riconosciuta dalla build",
            "blocchi": [
                ("p", "Le CVE di Windows sono descritte per release (Windows 10 21H2, Windows 11 24H2, Server 2022…). Con «Riconosci "
                      "la release di Windows dalla build» acceso (Impostazioni › Avvisi e automatismi › Impatto CVE sugli asset) ogni PC "
                      "Windows è confrontato solo con i criteri della sua release, letta dalla build (10.0.26200 = Windows 11 25H2; client "
                      "e server separati dal nome): impatta o non impatta come gli altri programmi; se la CVE non elenca la sua release, "
                      "non impatta; nel dubbio resta da verificare, con il motivo."),
                ("p", "Senza, ogni CVE di Windows lascia tutti i PC Windows «da verificare» e i PC con il nome lungo di WatchGuard non "
                      "vengono confrontati. Prima di accenderla: manage.py cve_windows_anteprima (non scrive niente) dice quanti esiti "
                      "cambiano e quante CVE apriranno un alert al primo ricalcolo."),
            ],
        },
        {
            "id": "correzioni-cve",
            "titolo": "Correzioni CVE: cosa si è chiuso con gli aggiornamenti",
            "blocchi": [
                ("p", "Dispositivi › «Correzioni CVE» (o il pulsante in cima all'elenco delle Vulnerabilità) elenca ogni PC uscito da una "
                      "CVE: programma, versione prima → dopo, «Programma aggiornato» o «Programma disinstallato», da quando era esposto, "
                      "in quanti giorni e se nel termine. In cima: PC corretti, CVE chiuse su tutti i PC, CVE ancora aperte su altri PC, "
                      "giorni medi e percentuale nel termine."),
                ("p", "Conta l'ultima uscita di ogni PC; un PC di nuovo esposto alla stessa CVE non è corretto. Stato di oggi per CVE: "
                      "«Chiusa con gli aggiornamenti» (nessun PC esposto e ogni uscita è un aggiornamento o una disinstallazione), "
                      "«Nessun PC esposto» (qualche PC è uscito senza correzione verificata: da guardare), «Ancora aperta». Vista «PC per "
                      "PC», filtri per periodo, motivo e testo; «Scarica CSV» esporta tutte le righe e resta nell'audit."),
                ("p", "L'elenco delle Vulnerabilità ora mostra anche gravità, programmi coinvolti, «esposta dal», termine (PC oltre o in "
                      "scadenza, rischi accettati) e PC corretti negli ultimi 90 giorni, con filtri; clic sulla riga apre il pannello della CVE."),
            ],
        },
        {
            "id": "tempi-di-correzione",
            "titolo": "Tempi di correzione e accettazione del rischio (ISO 27001 8.8)",
            "blocchi": [
                ("p", "Ogni PC esposto a una CVE ha un termine di correzione che parte da «esposto dal»: sfruttata (CISA KEV) la data "
                      "chiesta da CISA o 14 giorni, critica 15, alta 30, media 90, bassa 180 (si cambiano in Impostazioni › «Vulnerabilità: "
                      "tempi di correzione»). Lo vedi nella scheda CVE (colonna «Termine»), nel pannello della CVE e nel riquadro «Tempi di "
                      "correzione» della pagina Vulnerabilità, con la percentuale di PC corretti nel termine per classe."),
                ("p", "Passato il termine nasce da solo un alert «Oltre il termine di correzione» (uno per CVE, PC e termine; alto per "
                      "sfruttate e critiche, medio per le altre), che si chiude da solo quando il PC non risulta più esposto."),
                ("p", "Se la correzione non si può fare nel termine, chi configura il SOC accetta il rischio dalla scheda CVE: PC o tutti i "
                      "PC, motivo (almeno 20 caratteri), misure compensative, scadenza entro 12 mesi. Finché è attiva l'alert non scatta; 30 "
                      "giorni prima arriva un promemoria e alla scadenza l'esposizione torna a contare. Elenco e revoca in Dispositivi › "
                      "«Rischi accettati». Tutto, comprese le decisioni a mano sugli alert, resta nel registro audit sigillato del portale."),
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
                    "Le caselle di posta che ricevono i report (antivirus, firewall, backup) si configurano in «Caselle mail»: creazione, anteprima, lettura manuale, importazione dello storico. "
                    "La colonna «Report» dice se ogni casella manda i report nei tempi attesi; il riquadro «sorgenti in ritardo» apre l'elenco filtrato «In ritardo».",
                    "Un report arrivato per altra via si carica da Impostazioni › «Carica report».",
                    "Le caselle si leggono ogni 15 minuti con il lavoro «security_caselle». Defender, Entra, Veeam, regole, battito e "
                    "KPI girano nel lavoro «security_cycle», anch'esso ogni 15 minuti: se le letture esterne richiedono troppo "
                    "tempo vengono rimandate al giro dopo, ma regole, battito e notifiche girano comunque.",
                    "Chi apre la voce «Impostazioni» (Configurazione, Avvisi e automatismi, Battito, Letture, Soppressioni, "
                    "Caselle mail, Inventario software, Autoconfigurazione): in Ruoli e permessi la sotto-riga «↳ Impostazioni e "
                    "configurazione del SOC». «Chiudere / gestire» non la apre più: resta la gestione operativa (CVE, rischi "
                    "accettati, soppressioni dagli alert). La Guida resta visibile a tutti.",
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
                    "utente con il solo ruolo «Veeam Backup Viewer», password cifrata, certificato della CA se serve; con il certificato autofirmato di Veeam «Fidati del certificato del server»), «Prova la connessione», "
                    "poi l'interruttore «Leggi i backup dall'API di Veeam». Le mail di esito possono restare: la stessa esecuzione conta una volta sola.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Tanti alert uguali: stesso PC (Endpoint Security «devices blocked»), stesso backup, stessa CVE",
            "fare": [
                "Ora i report via mail aprono un alert solo per PC (Endpoint Security) o per job di backup: le mail successive aggiornano lo stesso alert, con il conteggio dell'ultima mail; nel dettaglio, «Occorrenze» elenca tutte le mail.",
                "Con Impostazioni › «Meno rumore» acceso (di serie) i dispositivi bloccati dalla policy (chiavette USB) non aprono alert: il conteggio per PC è in Dispositivi › Elenco, riquadro «Dispositivi bloccati dalla policy»; alert solo sopra la soglia scelta. Le minacce vere aprono sempre l'alert.",
                "CVE oltre il termine: un alert per CVE (non per PC), oppure una riga nella timeline dell'alert «PC con versione vulnerabile» se c'è già; ogni PC corretto lascia «PC rientrato nel termine» e l'alert si chiude da solo quando non ne resta nessuno.",
                "Un backup completato dopo i fallimenti chiude l'alert del suo job da solo, anche se è un nuovo tentativo («Job (Retry 2)»). Le mail di Veeam sul malware nei backup aprono un solo alert alto «Veeam: malware nei backup», separato dai job.",
                "Modifiche di Entra fatte da amministratori del portale o dagli autori fidati scritti in «Meno rumore»: niente alert, restano negli eventi.",
                "Alert senza nuove occorrenze da 30 giorni (impostabile): proposta «Risolto» da confermare in Segnalazioni › Proposte AI.",
                "«Vulnerabilità critica esposta CVE-…» (mail di Defender) non si apre se la CVE è già seguita PC per PC dall'inventario («Oltre il termine di correzione», «PC con versione vulnerabile»); se era già aperta, il ciclo del SOC la chiude come doppione, con il rimando all'alert dell'inventario.",
                "Per i doppioni aperti prima di questa regola: python manage.py security_unisci_doppioni (prova, mostra cosa farebbe), poi con --apply. Chiude il rumore già aperto (blocchi USB, «oltre il termine» di CVE già seguite, Entra di autori fidati: stato «Chiuso» con il motivo), tiene l'alert più recente di ogni PC, job o CVE e chiude gli altri come «Unito all'alert #…». Con --rinomina-fonte \"VECCHIO\" \"NUOVO\" rinomina anche una fonte mail (es. una casella che si chiama come una persona).",
            ],
        },
        {
            "sintomo": "Accessi VPN: lo stesso accesso compare due volte, a un'ora di distanza",
            "fare": [
                "Succede quando WatchGuard Cloud manda due report programmati dello stesso giorno, uno in ora italiana e uno in UTC. Il portale ricava il fuso di ogni report dal periodo scritto nella mail («Reports for Fireboxes … from … to …») e salva l'accesso una volta sola, all'ora vera.",
                "Per lo storico salvato prima della correzione: python manage.py vpn_riallinea_fuso (prova a vuoto, mostra i doppioni) e poi con --apply; ricalcola anche i KPI VPN dei giorni toccati.",
                "Se basta un report solo, eliminare in WatchGuard Cloud il report programmato in più.",
            ],
        },
        {
            "sintomo": "Il numero sul filtro è più alto delle righe dell'elenco",
            "fare": [
                "L'elenco di Segnalazioni mostra le 300 più recenti per tipo e, quando taglia, lo dice con l'avviso «Elenco tagliato: mostrate N di M»; i numeri dei filtri (calcolati con lo stato, la gravità e la ricerca scelti), «Solo urgenti» e la barra di stato contano tutto. Usa ricerca o gravità per restringere, o «Scarica CSV» per averle tutte. Alert, Ticket e Registro incidenti non tagliano: cento righe per pagina, con i numeri di pagina in fondo.",
                "Proposte AI conta gli alert «da decidere» (senza rimandati e silenziati): può essere più basso degli alert aperti di Segnalazioni.",
                '«PC con backup ko» guarda gli ultimi 90 giorni: un PC i cui backup si sono fermati da settimane resta tra i ko.',
                '«Scadenze NIS2/GDPR» comprende anche gli incidenti chiusi con una notifica di legge ancora dovuta.',
            ],
        },
        {
            "sintomo": "Librerie del portale: la lettura è in errore «OSV non raggiungibile»",
            "fare": [
                "Il server del portale deve poter aprire https://api.osv.dev (porta 443): verificare firewall e proxy (variabile HTTPS_PROXY dell'utente del qcluster).",
                "Poi Impostazioni › «Letture automatiche» › «Librerie Python del portale (OSV)» › «Esegui ora».",
            ],
        },
        {
            "sintomo": "Librerie del portale: ho aggiornato requirements.txt ma la vulnerabilità resta aperta",
            "fare": [
                "Il controllo guarda le librerie installate, non il file: in produzione pip install -r requirements.txt nel venv del portale, poi riavvio di sito e qcluster.",
                "Al controllo successivo (06:50 o «Esegui ora») la vulnerabilità passa fra le risolte e l'alert si chiude.",
            ],
        },
        {
            "sintomo": "Patch e protezione: una patch .NET, SQL Server o Office non dice «Compresa in» anche se ce n'è una più recente",
            "fare": [
                "Per queste serve il Security Update Guide di Microsoft: Impostazioni › «WatchGuard Endpoint Security (API)», interruttore «Cerca le patch comprese in una più recente (Microsoft)» acceso.",
                "Il server deve poter uscire su HTTPS verso api.msrc.microsoft.com; l'esito è in «Letture automatiche» › WatchGuard (voce «msrc»).",
                "La KB nel nome arriva alla lettura delle patch successiva (06:10 e 13:10). Gli aggiornamenti fuori ciclo non di sicurezza non sono nel Security Update Guide: per Windows vale il build nel nome.",
                "Si leggono al massimo 2 documenti mensili per giro (pesano decine di MB): alla prima accensione servono alcuni giri per l'ultimo anno; l'esito dice «documenti_rimandati».",
            ],
        },
        {
            "sintomo": "Letture automatiche › WatchGuard: un passo è in errore «Lettura troncata» o «elenco … vuoto»",
            "fare": [
                "È voluto: se WatchGuard non restituisce tutte le pagine, o restituisce un elenco vuoto quando PC o patch sono già nel portale, il passo si salta e nessun PC viene segnato come sparito né alcuna patch chiusa. Al giro successivo (06:10 e 13:10) o con «Esegui ora» si riprova.",
                "Se l'errore parla del proxy (407, «il proxy del server ha rifiutato», «certificato HTTPS non attendibile») o dice «La risposta non arriva dall'API di WatchGuard»: il proxy del server blocca o ispeziona *.cloud.watchguard.com; serve un'eccezione sul proxy, le credenziali API non c'entrano.",
            ],
        },
        {
            "sintomo": "CVE: le letture NVD dicono «NVD ha risposto 404 (o 403) con l'API key impostata»",
            "fare": [
                "La API key NVD salvata non è valida o è stata revocata: nella pagina «Software e CPE», riquadro «API key NVD», incolla quella della mail di NVD (è un codice come 1a2b3c4d-1a2b-1a2b-1a2b-1a2b3c4d5e6f) oppure «Rimuovi la key» per leggere senza chiave, più lentamente.",
                "Una CVE la cui lettura va in errore si riprova dopo 24 ore, così non toglie posto alle altre a ogni giro.",
            ],
        },
        {
            "sintomo": "«Proposte AI» è vuota, oppure l'AI non chiude mai da sola un tipo di alert",
            "fare": [
                "Le proposte arrivano per gli alert aperti da almeno 2 ore (impostazione «Attesa prima di proporre»); un alert si riesamina solo quando arriva un report nuovo o una decisione nuova.",
                "In Impostazioni › Letture automatiche › «Proposte di chiusura dell'AI» c'è l'esito di ogni giro: «AI locale non raggiungibile» vuol dire Ollama spento o modello non caricato.",
                "Chiude da sola solo dopo 5 conferme di fila per quel tipo di alert ed esito (tabella «Cosa ha imparato»), con confidenza almeno 80%, mai per alert critici, minacce o CVE sfruttate. Una proposta scartata o un alert riaperto azzerano il conteggio.",
            ],
        },
        {
            "sintomo": "La casella «Cerca anche sul web» non c'è, oppure la risposta dice «Nessuna pagina utile letta»",
            "fare": [
                "La casella compare solo con Impostazioni › «Ricerca sul web per l'AI» › «Permetti all'AI di consultare le fonti ufficiali sul web» acceso.",
                "«Nessuna pagina utile letta»: il server del portale deve poter uscire su HTTPS (porta 443) verso i siti ammessi (nvd.nist.gov, support.microsoft.com, cisa.gov…); verificare firewall e proxy. Il registro AI del SOC riporta l'errore per sito (azione «web_pagina»).",
                "«Nessun identificativo pubblico»: l'alert non contiene codici CVE, KB o d'errore, quindi il web non viene consultato. Per cercare codici d'errore ed Event ID serve il motore di ricerca interno (campo SearXNG in Impostazioni).",
            ],
        },
        {
            "sintomo": "Tempi delle patch: il grafico «Patch mancanti a fine settimana» è vuoto o parte da poco",
            "fare": [
                "La fotografia si scrive a ogni lettura delle patch WatchGuard (06:10 e 13:10): prima dell'installazione della funzione non c'è.",
                "Se resta vuoto: Impostazioni › «WatchGuard Endpoint Security (API)», interruttore «Leggi le patch mancanti» acceso, poi «Letture automatiche» › WatchGuard › «Esegui ora».",
            ],
        },
        {
            "sintomo": "Un incidente mostra «Riesame mancante» o arrivano promemoria sul riesame",
            "fare": [
                "Apri la scheda dell'incidente e compila «Lezioni apprese»: basta la causa per togliere l'avviso.",
                "Aggiungi le azioni correttive con responsabile e scadenza e segnale fatte quando concluse: le scadute mandano un promemoria.",
            ],
        },
        {
            "sintomo": "Un'evidenza risulta «Alterata»",
            "fare": [
                "Il contenuto non corrisponde più all'impronta calcolata alla nascita: guarda la catena di custodia nell'esportazione per capire chi l'ha toccata.",
                "Non si ripara da sola: segnalala a chi gestisce il SOC; se le prove servono a un'indagine è un fatto da registrare come incidente.",
            ],
        },
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
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla «security_caselle» (caselle mail) e «security_cycle» (Defender, Entra, Veeam, regole).",
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
                "«Accesso al portale bloccato per troppe password sbagliate»: blocco di un'ora per quel nome utente da quell'IP "
                "(si toglie da Amministrazione → «Accessi bloccati»). "
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
                "SecurityAlert.Read.All (o il consenso amministratore) sull'app del portale in Entra ID; «ha risposto 401» = token "
                "rifiutato: segreto dell'app scaduto o sbagliato, oppure l'orologio del server fuori sincronia.",
                "«alert_troncati» nell'esito: in un giro sono arrivati più alert del limite; il giro dopo riparte dall'ultimo letto, "
                "nessuno si perde.",
                "Software o vulnerabilità di Defender con «lettura troncata» nell'esito: Defender ha più pagine del limite e il giro "
                "non ha toccato i dati (niente «non più rilevato», niente CVE cancellate); succede solo con inventari molto grandi.",
                "Arriva l'evento ma non l'alert: la severità è sotto la «Severità minima per l'alert» (l'evento resta nei KPI).",
            ],
        },
        {
            "sintomo": "Il riquadro «Lettura diretta da Veeam» della pagina Backup dice «errore»",
            "fare": [
                "Il messaggio sotto il titolo dice cosa non va; Impostazioni › «Credenziali API Veeam» › «Prova la connessione» lo ripete.",
                "«Server Veeam non raggiungibile»: controlla l'indirizzo nelle credenziali e che dal server del portale la porta 9419 sia aperta.",
                "«Non c'è l'API REST di Veeam Backup & Replication (404)»: l'indirizzo risponde ma non è l'API giusta. Va scritto solo https://<server>:9419, senza /api o altri percorsi; la porta 9398 è Enterprise Manager, non va bene. Se il messaggio aggiunge «la risposta non arriva dall'API di Veeam», a quell'indirizzo risponde un altro servizio (per esempio IIS): l'indirizzo o la porta sono sbagliati. Se l'indirizzo è giusto, sul server Veeam controlla che il servizio «Veeam Backup Server RESTful API» sia avviato. Il portale chiama Veeam direttamente, senza passare dal proxy di HTTPS_PROXY.",
                "«Veeam non accetta la versione API»: nelle credenziali scrivi la versione che il server supporta (la mostra la pagina Swagger, https://<server>:9419/swagger).",
                "«Certificato del server Veeam non attendibile»: se Veeam usa il suo certificato autofirmato (il caso di serie) premi «Fidati del certificato del server» e confronta l'identificazione personale (SHA-1) mostrata con quella del certificato sul server Veeam; se è firmato dalla CA interna, incolla il certificato della CA (formato PEM). Il messaggio dice il motivo: nome diverso da quello dell'indirizzo, scaduto, non firmato dal certificato incollato. «Il certificato del server Veeam è cambiato»: rinnovato o sostituito in Veeam; se è normale, premi di nuovo «Fidati del certificato del server».",
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
