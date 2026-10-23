GUIDA = {
    "slug": "assets",
    "titolo": "Asset e manutenzione",
    "area": "Produzione e operations",
    "sintesi": "Inventario di macchine, impianti e dispositivi IT, ordini di lavoro, manutenzioni e verifiche periodiche.",
    "parole": "asset macchina macchine inventario manutenzione odl ordine lavoro verifica periodica qr pc stampante",
    "url": "assets:asset_dashboard",
    "prefissi": ("/assets/",),
    "dettaglio": [("Guida completa Asset e manutenzione", "assets:guida")],
    "uso": [
        {
            "id": "trovare",
            "titolo": "Trovare una macchina o un PC",
            "blocchi": [
                ("passi", [
                    "Apri Asset: si apre il cruscotto.",
                    "Clicca «Inventario completo» oppure una categoria nel menu a sinistra.",
                    "Cerca per nome, numero interno, seriale o IP e apri la scheda.",
                ]),
                ("p", "Dal telefono basta inquadrare il QR sulla macchina: si apre la scheda con manutenzioni e documenti."),
                ("p", "Sotto il cruscotto della scheda, «Lo stesso apparato in» porta alla stampante in Contatori e al dispositivo nel SOC; "
                      "lì trovi la stessa testata dell'asset, con il link «Scheda asset» per tornare."),
            ],
        },
        {
            "id": "rete",
            "titolo": "Correggere IP, switch e porta di un PC; vedere chi è collegato a uno switch",
            "blocchi": [
                ("passi", [
                    "Apri la scheda dell'asset, tab «Tecnica e rete».",
                    "Premi «Modifica rete» (o «+ Aggiungi interfaccia» se non ce n'è nessuna).",
                    "Compila IP, MAC, VLAN, Switch (matricola dello switch), Porta SW e Porta patch panel; premi «Salva rete».",
                ]),
                ("p", "Nella scheda dello switch, «Mappa porte dello switch» mostra le porte occupate colorate per VLAN. "
                      "Per collegare lo switch al suo stack scrivi il «Prefisso porte di questo switch» (es. A0) e premi «Salva prefisso»: "
                      "le porte A0.x.x senza switch indicato, anche quelle censite dopo, appartengono a quello switch."),
            ],
        },
        {
            "id": "planimetria",
            "titolo": "Vedere dove si trova una macchina; collocarla sulla planimetria",
            "blocchi": [
                ("p", "Nella scheda della macchina il riquadro «Posizione in officina» mostra la zona ingrandita e il reparto; "
                      "«Pianta intera» apre tutta la planimetria, «Vedi sulla mappa» la mappa officina con lo stato delle macchine."),
                ("passi", [
                    "Dalla scheda premi «Posiziona ora» (o «Sposta»): si apre l'editor con la macchina già scelta.",
                    "Clicca sulla pianta il punto in cui si trova la macchina; usa la rotellina per ingrandire.",
                    "Premi «Salva».",
                ]),
            ],
        },
        {
            "id": "report",
            "titolo": "Estrarre un report (rete, licenze, costi, schede incomplete)",
            "blocchi": [
                ("passi", [
                    "Apri il «Catalogo report» (icona dei grafici nell'elenco asset, o la scheda «Catalogo report» "
                    "in cima alle pagine dei report) e cerca il report per nome.",
                    "Imposta i filtri; con «Cerca nelle righe» tieni solo le righe che contengono le parole scritte.",
                    "Clicca un'intestazione per ordinare; in «Colonne» scegli cosa vedere; premi «Aggiorna».",
                    "«Scarica Excel» o «Scarica PDF» producono esattamente quello che vedi; «Salva report» lo "
                    "conserva (anche condiviso o inviato via email).",
                ]),
                ("p", "Report disponibili: Inventario per stato e reparto, Qualità dei dati, Parco IT e rete, "
                      "Licenze software, Modifiche di rete e assegnazioni, Scadenze, Costi e ore di manutenzione, "
                      "MFC. In testa a ogni report ci sono riquadri di riepilogo e un grafico."),
            ],
        },
        {
            "id": "guasto",
            "titolo": "Segnalare un guasto",
            "blocchi": [
                ("p", "Per un guasto apri un ticket di manutenzione (modulo Ticket, «+ Ticket MAN») scegliendo la macchina, "
                      "oppure dal QR della macchina."),
                ("p", "Dal QR, «Segnala guasto ora» apre una pagina per il telefono: la macchina è già indicata, "
                      "scegli quanto è urgente e allega fino a 3 foto. La categoria è facoltativa."),
                ("p", "Quando il manutentore crea l'intervento la segnalazione passa a «In carico»; chiudendo l'intervento "
                      "con esito «Risolto» può segnarla anche come «Risolto»."),
            ],
        },
        {
            "id": "manutentori",
            "titolo": "Per i manutentori",
            "blocchi": [
                ("ul", [
                    "«Manutenzione» mostra lo scadenzario unico, dal più urgente.",
                    "In «Da fare», «✓ Fatta oggi» registra con un tap le manutenzioni semplici (interne, senza documento "
                    "obbligatorio): hai 5 secondi per annullare. Con più righe selezionate: «Segna come fatte oggi».",
                    "«Il mio turno» è la scheda «Il mio lavoro» di Da fare; i KPI sono nella Panoramica, sotto "
                    "«Dettaglio indicatori».",
                    "Ricambi: in un intervento, riquadro «Ricambi usati» → cerca, quantità, «Aggiungi» (la giacenza "
                    "scende subito). «Manutenzione → Ricambi» con il filtro «Sotto scorta» mostra cosa sta finendo.",
                    "Contatori (ore, km, cicli): si aggiornano dalla scheda asset o dal QR; l'etichetta dice quanto è "
                    "fresca la lettura. Un valore non può scendere: per un azzeramento serve la nota. I piani «a "
                    "contatore» chiedono il valore letto quando si registra la manutenzione.",
                    "Un ordine di lavoro (OdL) si registra e si chiude dalla sua scheda; si possono chiudere più OdL insieme.",
                    "Chiudendo un intervento nato da una segnalazione, con esito «Risolto» la casella «Segna anche la "
                    "segnalazione … come Risolta» si spunta da sola (solo per chi gestisce i ticket di manutenzione); "
                    "con «Risolto temporaneamente» o «Non risolto» la segnalazione non cambia. Il fermo parte da quello "
                    "indicato nella segnalazione.",
                    "Una manutenzione che non si riesce a fare in tempo si rinvia («Rinvia» nella pagina «Registra», "
                    "o trascinandola nel Calendario): la scadenza originale resta e, eseguita, la successiva riparte "
                    "dalla data di esecuzione.",
                    "Dalle verifiche periodiche i rilievi si segnalano senza creare ordini di lavoro.",
                    "Dalla scheda asset, menu «Altro»: «Dismetti» toglie la macchina dagli elenchi senza perdere lo "
                    "storico (si annulla con «Riattiva»); «Elimina» cancella solo un asset creato per errore, senza storico.",
                    "Le attrezzature PART 145 si marcano con «Rientra in PART 145» nel form dell'asset. La voce "
                    "«PART 145» del menu apre il Dossier PART 145 (processi, contratti, attrezzature, personale, "
                    "scadenze, situazioni aperte, documenti SGI) con export Excel e PDF; se un'attrezzatura cambia stato "
                    "Qualità riceve una mail.",
                    "Scheda di una macchina, scheda «Operatori»: chi è abilitato dalla skill matrix, quanti operativi, "
                    "in addestramento e sospesi, «Uomo solo» con un solo operativo e le soglie di copertura AS/EN 9100. "
                    "Nomi e livelli solo per chi ha accesso alla skill matrix o ai dati HR.",
                    "Nel Dossier la colonna «Controllo» dice come si tiene sotto controllo l'attrezzo (MOE §2.4): "
                    "«Taratura» se ha un piano di taratura, «Manutenzione periodica» se ha altri piani, «A vista» se "
                    "non ne ha. Una taratura scaduta compare tra le situazioni aperte: l'attrezzo va segregato.",
                    "Nel Dossier la sezione «Da sistemare» è in cima con la priorità (Alta / Media); i riquadri in "
                    "testa sono rossi, ambra o verdi e portano alla sezione; una sola ricerca filtra tutte le sezioni. "
                    "Il menu «↓ Scarica» ha Dossier PDF ed Excel, «Strumenti tarati» (Excel, da comunicare "
                    "all'organizzazione di manutenzione) e «Controllo semestrale» (PDF per reparto da firmare, MT CN 17).",
                    "Il Dossier mostra anche, a chi ha il permesso del modulo, la formazione richiesta dai processi "
                    "(MOD.128), gli audit interni Part 145 (Sistema di gestione) e le NC Part 145 aperte (Anomalie).",
                    "Nel Catalogo report, area «Qualità e PART 145»: tarature delle attrezzature, da sistemare, scadenze.",
                    "Nei Documenti della scheda si caricano anche intere cartelle con sottocartelle e video .avi: "
                    "i file non ammessi vengono scartati ed elencati, gli altri entrano.",
                ]),
            ],
        },
        {
            "id": "mtconnect",
            "titolo": "Stato reale delle CNC (collector OPC UA, MTConnect) sulla mappa officina",
            "blocchi": [
                ("passi", [
                    "Apri la mappa officina: una macchina con il pallino rosso scuro è «In allarme» sul suo controllo.",
                    "Clicca la macchina: «Dal controllo della macchina» dice stato e da quando, programma, pezzi, ore in lavoro di oggi e gli allarmi attivi.",
                    "Elenco di tutte le macchine collegate, con stato e contatori: Configurazione → «Macchine collegate».",
                    "Scheda della macchina, scheda Panoramica: riquadro «Stato della CNC» con stato e da quando, ore in lavoro di oggi, "
                    "programma, pezzi, avvisi e allarmi e gli ultimi 10 cambi di stato con la durata.",
                ]),
                ("p", "Le DMG MORI arrivano dal collector OPC UA dell'officina (a ogni cambio di stato e almeno ogni minuto); "
                      "le macchine con un agent MTConnect si leggono ogni 2 minuti. «Dato non aggiornato» = nessuna lettura negli "
                      "ultimi 15 minuti (collector o agent fermo): in quel caso la macchina non conta come in allarme."),
            ],
        },
        {
            "id": "rete-indirizzi",
            "titolo": "Indirizzi IP e dispositivi non censiti (DHCP e DNS)",
            "blocchi": [
                ("passi", [
                    "Apri Asset → «Indirizzi IP» (o Security Center → Dispositivi → «Rete (IP)»): una riga per indirizzo, letta ogni ora "
                    "dal DHCP e dal DNS di Windows Server e incrociata con switch, WatchGuard e Intune.",
                    "I riquadri in testa contano Indirizzi attivi, Non censiti, Da collegare, Senza antivirus e DNS da pulire: un clic = quel filtro.",
                    "Gli ambiti DHCP hanno un anello con l'occupazione: rosso «Quasi pieno» dal 90%; «Disattivato» = non assegna indirizzi.",
                    "«Non censiti»: nessun asset riconosce MAC, IP o nome; contano anche gli IP fissi presenti solo nel DNS. "
                    "Premi «Crea asset»: il modulo arriva già compilato (nome, IP, MAC, switch e porta) e l'indirizzo resta collegato.",
                    "«Da collegare»: il portale propone l'asset (con il motivo); premi «Conferma» sulla riga. «Scollega» lo stacca.",
                    "«Senza antivirus»: WatchGuard lo vede senza agente, o è un PC del registro assente da WatchGuard e Defender.",
                    "La colonna «Switch» dice switch, porta e VLAN dove si vede il MAC: serve a trovare fisicamente un dispositivo.",
                ]),
                ("p", "Il riconoscimento usa il MAC del punto rete dell'asset, i MAC di Intune e WatchGuard, l'IP e il nome (anche se lo "
                      "stesso nome è già collegato in Intune, WatchGuard o nel SOC). Un indirizzo collegato compare nella riga «Visto da» "
                      "della scheda asset come fonte «Rete» e fa trovare la porta dello switch. Il pulsante «Excel» scarica le righe mostrate."),
            ],
        },
    ],
    "admin": [
        {
            "id": "planimetrie",
            "titolo": "Preparare la planimetria dell'officina",
            "blocchi": [
                ("ul", [
                    "Editor planimetrie (mappa officina → «Apri editor mappa»): carica la pianta in PNG, JPG o PDF (prima pagina).",
                    "«Ruota» raddrizza una pianta di traverso; «Ritaglia» e «Margini automatici» tolgono i bordi inutili. "
                    "Reparti e macchine seguono la pianta; le macchine fuori dal ritaglio tornano «da collocare».",
                    "Disegna i reparti e scrivi il codice reparto uguale al campo reparto delle macchine.",
                    "Una sola planimetria per categoria è «Attiva»: le altre restano bozze finché non le pubblichi.",
                ]),
            ],
        },
        {
            "id": "config",
            "titolo": "Configurazione",
            "blocchi": [
                ("ul", [
                    "Asset → «Impostazioni»: categorie, menu laterale, piani di manutenzione.",
                    "Impostazioni → «Codici guasto»: problema, causa e rimedio per la chiusura degli interventi "
                    "(senza categoria = validi per tutti). Un codice usato non si elimina: si disattiva.",
                    "Impostazioni → «Studio inventario»: campi personalizzati, valori delle liste, pulsanti della scheda, "
                    "dati del dettaglio asset e strumenti della lista (prima nello «Studio amministratore» della lista).",
                    "Dopo aver cambiato le categorie, rigenera il menu laterale con il comando sync_sidebar_categories.",
                    "Il numero interno si assegna solo a mano («Assegna progressivo»).",
                    "Le scadenze amministrative (revisioni, verifiche di legge, certificati, garanzie) sono separate dai "
                    "piani di manutenzione. Con «Si ripete ogni (mesi)» basta una voce: «Registra» la rinnova da sola. "
                    "Le manutenzioni finite nel registro si spostano nei piani con il comando "
                    "riordina_scadenze_amministrative (prima in prova, poi con --apply; --mesi \"Titolo=12\" per i "
                    "titoli senza serie).",
                    "«Dismetti / riattiva asset» ed «Elimina asset (senza storico)» sono già concessi ai ruoli della "
                    "manutenzione; ad altri ruoli si danno da Amministrazione → Accessi.",
                    "Un piano va applicato ai singoli asset che lo fanno davvero, non a un'intera categoria. Per allineare "
                    "i piani allo scadenziario X-MINE c'è il comando riallinea_manutenzioni_xmine (prima in prova, "
                    "poi con --applica).",
                ]),
                ("p", "Tutti i dettagli sono nella guida completa (collegamento in cima)."),
            ],
        },
        {
            "id": "licenze-m365",
            "titolo": "Abbonamenti Microsoft 365 nelle licenze",
            "blocchi": [
                ("p", "Ogni mattina alle 06:40 il portale legge gli abbonamenti Microsoft 365 e tiene una licenza per abbonamento in "
                      "«Licenze software» (categoria Office, riferimento m365:…): posti acquistati, posti usati, stato e, se Microsoft la "
                      "fornisce, la scadenza. Nome, assegnatario e note restano quelli scritti nel portale; le licenze inserite a mano non "
                      "vengono toccate. Permessi Graph Organization.Read.All e, per le date, LicenseAssignment.Read.All. "
                      "Prova dal terminale: m365_licenze --prova."),
            ],
        },
        {
            "id": "cve",
            "titolo": "Vedere le CVE di un programma o di un PC",
            "blocchi": [
                ("passi", [
                    "Catalogo software: nella colonna CVE premi il bottone «N CVE» (lo vede solo chi ha accesso al Security Center).",
                    "Si apre un pannello a destra con le CVE in ordine di pericolo: prima le sfruttate attivamente, poi per punteggio CVSS.",
                    "Premi una CVE: vedi «Cosa fare» (la versione da installare, se nota) e i PC colpiti. «Torna all'elenco» per tornare, Esc per chiudere.",
                    "Scheda di un PC: il riquadro «Vulnerabilità» mostra le cinque CVE più pericolose; «Vedi tutte le CVE» apre il pannello per software.",
                ]),
                ("p", "Nella scheda del programma la tabella «Versioni presenti» dice quante CVE colpiscono ogni versione: "
                      "quelle con «nessuna nota» sono le versioni a cui aggiornare."),
                ("p", "Quando un PC viene aggiornato (a mano o dal patch management) non si chiude niente a mano: al primo inventario "
                      "con la versione nuova la CVE esce dal PC e finisce in «Risolte negli ultimi 90 giorni», con versione prima e dopo. "
                      "Il riquadro «Vulnerabilità» del PC conta le «risolte (90 gg)»."),
            ],
        },
        {
            "id": "intune",
            "titolo": "PC gestiti da Microsoft Intune",
            "blocchi": [
                ("p", "Ogni mattina alle 06:45 il portale legge da Microsoft Intune i PC gestiti: nome, seriale, produttore, modello, "
                      "Windows e versione, conformità ai criteri, cifratura del disco (BitLocker), ultima sincronizzazione, utente principale, "
                      "RAM, disco (totale e libero) e MAC Wi-Fi/Ethernet. La RAM Intune la dà un PC alla volta: arriva nei primi giorni "
                      "(50 PC per giro). Il processore Intune non lo espone."),
                ("ul", [
                    "Collegamento all'asset: Asset → «Riconciliazione dispositivi», righe «Intune». La proposta viene dal numero di serie, poi dal nome; "
                    "si conferma con il permesso di modificare quell'asset.",
                    "Sull'asset collegato compare il riquadro «Microsoft Intune» (scheda Panoramica). Produttore, modello, seriale, sistema operativo, "
                    "RAM e disco vuoti vengono completati da Intune; quelli già scritti non si toccano.",
                    "In cima alla Panoramica di un PC la riga «Visto da» dice quali fonti lo vedono (Intune, WatchGuard, Defender, Security Center, SNMP) "
                    "e quando: pallino verde = visto di recente, arancione = non di recente, rosso = problema; tratteggiata = la fonte non lo vede. "
                    "Con l'API WatchGuard accesa dice anche lo stato della protezione e le patch mancanti; con la tabella MAC degli switch "
                    "la voce «Rete» dice a quale switch e porta è collegato il PC.",
                    "Il riquadro Intune ha «Aggiornamenti Windows»: «Indietro» se altri PC con la stessa versione di Windows hanno già "
                    "una cumulativa più recente (il riferimento è il PC più aggiornato in azienda).",
                    "Gli avvisi IT del mattino (07:15) riportano i PC non cifrati, non conformi o che non si sincronizzano da oltre 30 giorni; "
                    "la notifica in app arriva solo per i problemi nuovi.",
                    "Serve il permesso Graph «DeviceManagementManagedDevices.Read.All» (applicazione, consenso amministratore). "
                    "Prova dal terminale: intune_sync --prova; sincronizza subito: intune_sync.",
                ]),
            ],
        },
        {
            "id": "collector-server",
            "titolo": "Far girare il collector delle CNC sul server del portale",
            "blocchi": [
                ("passi", [
                    "Dal server del portale verifica che le macchine rispondano sulla porta OPC UA: Test-NetConnection <IP macchina> -Port 4840.",
                    "Sul server apri il Setup Wizard come amministratore → Server Dashboard → riquadro «Collector CNC» → «Installa task» "
                    "(stesso account del qcluster; se l'account ha una password il wizard la chiede e non la salva).",
                    "Configurazione → «Macchine collegate» → «Dove gira il collector» → «Sul server del portale» → «Salva».",
                    "Entro un minuto il riquadro dice «Attivo» con il numero di macchine in lettura; niente token né PC dedicato.",
                ]),
                ("p", "Le due modalità si escludono: con il collector sul server, quello di un PC non riceve più macchine da leggere. "
                      "Se il servizio si ferma, il riquadro dice «Fermo» e il controllo «collector_cnc» della Centrale di comando avvisa. "
                      "Dopo un aggiornamento del portale il collector riparte da solo col codice nuovo: non serve nessun passo. "
                      "Senza wizard: deployment/scripts/install-collector-cnc-task.ps1. Prova senza leggere: manage.py collector_cnc --prova."),
            ],
        },
        {
            "id": "collector-collega",
            "titolo": "Collegare le CNC al collector OPC UA (tutto dal portale)",
            "blocchi": [
                ("passi", [
                    "Configurazione → «Macchine collegate» → «Collega una macchina» → «Collector OPC UA»: scegli la macchina, scrivi "
                    "l'indirizzo OPC UA (IP), la porta (4840), il codice breve (es. DM6) e, se serve, utente e password OPC UA. «Salva». "
                    "Nel menu ci sono solo le macchine di lavoro (con la scheda macchina).",
                    "Riquadro «Collector» (amministratori del modulo Asset): «Crea il collector e il token» con l'IP del PC del collector. "
                    "Copia il token: si vede una volta sola.",
                    "Sul PC del collector imposta PORTALE_URL (lo mostra la pagina) e PORTALE_TOKEN e avvia il collector: scarica da solo "
                    "l'elenco delle macchine e lo rilegge ogni 5 minuti.",
                    "Token perso o compromesso: «Nuovo token» (il vecchio smette subito di funzionare). Collector dismesso: «Disattiva».",
                ]),
            ],
        },
        {
            "id": "mtconnect-collega",
            "titolo": "Collegare una CNC con MTConnect",
            "blocchi": [
                ("passi", [
                    "Serve un agent MTConnect raggiungibile dal server del portale (sul PC della macchina o su un gateway dell'officina).",
                    "Configurazione → «Macchine collegate»: scegli la macchina, scrivi l'indirizzo dell'agent (es. http://10.0.5.21:5000) e premi «Prova».",
                    "Se la prova legge ore e pezzi, lascia spuntati «Aggiorna i contatori» e «Crea i contatori Ore e Cicli se mancano».",
                    "Premi «Salva»: lo stato arriva sulla mappa entro 2 minuti (schedule mtconnect_poll).",
                ]),
                ("p", "Solo indirizzi della rete interna; il portale legge e basta. Collegare, sospendere o togliere una macchina "
                      "richiede il permesso di modificarla. I contatori avanzano per differenza, al massimo una volta all'ora."),
            ],
        },
        {
            "id": "rete-windows",
            "titolo": "Collegare il DHCP e il DNS di Windows Server",
            "blocchi": [
                ("passi", [
                    "Sul server del portale installa gli strumenti RSAT: Install-WindowsFeature RSAT-DHCP, RSAT-DNS-Server.",
                    "Metti l'utente che fa girare il qcluster nel gruppo «DHCP Users» del server DHCP (sola lettura).",
                    "Apri Asset → «Indirizzi IP», riquadro «Server DHCP e DNS» (solo amministratori del modulo Asset): scrivi i server DHCP "
                    "(separati da virgole), il server DNS e le zone (es. dominio.local) e premi «Salva».",
                    "Premi «Leggi adesso»: la lettura va in coda e l'esito compare in cima alla pagina (e in SOC › Letture automatiche). "
                    "Poi si ripete da sola ogni ora (schedule rete_windows_sync).",
                ]),
                ("p", "Il portale lancia in locale due script PowerShell fissi che leggono soltanto: nessuna modifica a DHCP e DNS. "
                      "Gli errori di un server (permessi, RSAT mancanti, server non raggiungibile) compaiono in cima alla pagina Indirizzi IP."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una scadenza amministrativa compare due volte nello Scadenzario o «Registra» crea un doppione",
            "fare": [
                "Se la stessa verifica ha anche un piano di manutenzione sull'asset, registrala solo dal piano e "
                "disattiva la voce amministrativa (lo fa anche riordina_scadenze_amministrative).",
                "Le serie inserite una riga per data si sostituiscono con una sola voce e «Si ripete ogni (mesi)».",
            ],
        },
        {
            "sintomo": "Una macchina collegata risulta «Non raggiungibile», «Offline» o «Dato non aggiornato»",
            "fare": [
                "Fonte «Collector OPC UA»: «Offline» = il collector non raggiunge il controllo della macchina; «Dato non aggiornato» = "
                "il collector non invia da oltre 15 minuti: controlla che giri sul suo PC e il suo log (token, rete ammessa).",
                "«Agent non raggiungibile»: l'agent è spento o la rete non passa. Dal server del portale apri l'indirizzo dell'agent seguito da /current: deve rispondere un XML.",
                "«Dato non aggiornato»: nessuna lettura da oltre 15 minuti; controlla che il qcluster giri (Centrale di comando, schedule mtconnect_poll).",
                "«Dispositivo non trovato»: l'agent serve più macchine; scrivi nel collegamento il nome giusto (la «Prova» elenca i dispositivi dell'agent).",
            ],
        },
        {
            "sintomo": "«Dove gira il collector» dice «Fermo» o «Mai partito»",
            "fare": [
                "Sul server il task CollectorCnc non gira: Setup Wizard → riquadro «Collector CNC» → «Avvia collector», o «Installa task» se dice «Non installato».",
                "Log: <ambiente>\\logs\\collector_cnc.log. «Manca la libreria asyncua»: pip install -r requirements.txt nel venv del portale.",
                "Macchine «Offline» con il servizio «Attivo»: il server non raggiunge la macchina sulla porta 4840 (firewall o rete d'officina).",
            ],
        },
        {
            "sintomo": "Il contatore Ore o Cicli di una macchina collegata non avanza",
            "fare": [
                "La «Prova» del collegamento dice se l'agent espone ore e pezzi: se scrive «non le espone», il controllo non pubblica quel dato.",
                "Il collegamento deve avere la spunta del contatore e l'asset deve avere un contatore «Ore» o «Cicli» (creato dalla scheda); poi salva di nuovo il collegamento.",
                "Il contatore avanza al massimo una volta all'ora e la prima lettura fa solo da base.",
            ],
        },
        {
            "sintomo": "La pagina Indirizzi IP dice «Accesso negato» o «Mancano i moduli PowerShell»",
            "fare": [
                "«Mancano i moduli»: sul server del portale installa RSAT-DHCP e RSAT-DNS-Server (Install-WindowsFeature).",
                "«Accesso negato»: l'utente che fa girare il qcluster deve stare nel gruppo «DHCP Users» del server DHCP; dopo l'aggiunta va riavviato il qcluster.",
                "«Server non raggiungibile»: controlla i nomi nel riquadro «Server DHCP e DNS» della pagina e il firewall (RPC) tra i due server.",
                "Prova dal terminale con manage.py rete_windows --prova: dice quanti ambiti, indirizzi e record legge.",
            ],
        },
        {
            "sintomo": "Un dispositivo risulta «non censito» ma l'asset c'è",
            "fare": [
                "L'abbinamento usa MAC, IP e nome: scrivi il MAC nel punto rete dell'asset (scheda › Rete) o dai all'asset lo stesso nome del PC.",
                "Se due asset hanno lo stesso MAC, IP o nome la proposta resta vuota (ambigua): correggi il doppione.",
                "Le proposte si ricalcolano a ogni lettura (ogni ora).",
            ],
        },
        {
            "sintomo": "Un PC risulta «Senza antivirus» ma l'antivirus c'è",
            "fare": [
                "Il PC deve comparire in WatchGuard con l'agente o nell'inventario WatchGuard/Defender del SOC, collegato allo stesso asset.",
                "Controlla in Security Center → Dispositivi che il PC abbia l'asset collegato: senza collegamento il portale non può incrociare.",
                "«WatchGuard lo vede in rete senza agente»: l'agente non è installato o non comunica; si verifica dalla console WatchGuard.",
            ],
        },
        {
            "sintomo": "Il SOC non segnala un dispositivo nuovo in rete (o ne segnala troppi)",
            "fare": [
                "La prima lettura in assoluto non segnala niente; poi un evento per MAC mai visto, senza asset né proposta, al massimo 10 per lettura.",
                "I MAC «privati» dei telefoni (seconda cifra 2, 6, A o E) non si segnalano: cambiano da soli.",
                "L'alert si accende o spegne in Security Center → Impostazioni → Avvisi e automatismi («Dispositivo sconosciuto nuovo in rete»).",
            ],
        },
        {
            "sintomo": "Nella scheda della macchina compare «Posizione da definire» o la planimetria sbagliata",
            "fare": [
                "«Posizione da definire»: la macchina è sulla pianta ma nessuno l'ha collocata. Premi «Posiziona ora» e clicca il punto giusto.",
                "Se il reparto della macchina ha una planimetria dedicata (categoria uguale al reparto o reparto disegnato con quel codice) "
                "la scheda usa quella: controlla il campo reparto della macchina e il codice dei reparti disegnati.",
                "Se la pianta è di traverso o con grandi margini bianchi, raddrizzala e ritagliala nell'editor.",
            ],
        },
        {
            "sintomo": "Un PC di Intune non viene proposto per nessun asset",
            "fare": [
                "La proposta usa il numero di serie dell'asset, poi il nome: controlla che l'asset abbia il seriale giusto (o lo stesso nome del PC).",
                "Seriali di comodo come «To be filled by O.E.M.» non vengono usati: in quel caso conta solo il nome.",
                "Se due asset hanno lo stesso seriale o nome, la riga resta «ambigua»: correggi il doppione.",
            ],
        },
        {
            "sintomo": "La mappa porte dello switch è vuota",
            "fare": [
                "I dispositivi devono indicare lo switch: in «Modifica rete» scrivi la matricola dello switch nel campo Switch.",
                "Nella scheda dello switch indica il «Prefisso porte di questo switch» (es. A0) e premi «Salva prefisso».",
                "Se il prefisso è già su un altro switch (es. un doppione), toglilo da lì lasciando il campo vuoto.",
            ],
        },
        {
            "sintomo": "Un report del catalogo risponde «Serve anche l'accesso alla pagina da cui vengono i dati»",
            "fare": [
                "MFC, Licenze software e Costi e ore di manutenzione mostrano dati di altre pagine: servono anche "
                "Consumabili (Contatori IT), Licenze oppure Ordini di lavoro.",
                "Chiedi il permesso da Amministrazione → Accessi.",
            ],
        },
        {
            "sintomo": "Una categoria nuova non compare nel menu a sinistra",
            "fare": ["Lancia sync_sidebar_categories dal terminale del Setup Wizard.", "Ricarica la pagina."],
        },
        {
            "sintomo": "Una macchina ha manutenzioni che non le spettano",
            "fare": [
                "Il piano è applicato a tutta la categoria: in «Piani» applicalo ai singoli asset, oppure escludi l'asset.",
                "Per le macchine presenti in X-MINE chiedi all'amministratore il riallineamento "
                "(riallinea_manutenzioni_xmine), che annulla anche le scadenze aperte non dovute.",
            ],
        },
        {
            "sintomo": "«Elimina» è grigio: «non disponibile: ha storico»",
            "fare": [
                "L'asset ha già ordini di lavoro, scadenze, documenti o altri collegamenti: il suggerimento li elenca.",
                "Usa «Dismetti»: l'asset esce dagli elenchi e lo storico resta.",
            ],
        },
        {
            "sintomo": "Caricando una cartella alcuni file non entrano",
            "fare": [
                "Leggi l'elenco sotto il riquadro: formato non ammesso, file oltre il limite o vuoto.",
                "Converti i file (es. video in .avi o documenti in PDF) e caricali di nuovo.",
            ],
        },
        {
            "sintomo": "«Il contatore non può scendere» aggiornando ore o km",
            "fare": [
                "Controlla il valore: deve essere uguale o maggiore dell'ultimo letto.",
                "Se il contatore è stato azzerato o sostituito, apri «Contatore azzerato o sostituito?» e scrivi una nota.",
            ],
        },
        {
            "sintomo": "Una CNC non compare nel menu di «Collega una macchina»",
            "fare": [
                "Il menu mostra solo le macchine di lavoro: la CNC è finita in una categoria che non è di macchine (es. la categoria padre «CNC», tipo «Altro»).",
                "Apri la scheda dell'asset → «Modifica» → Categoria asset: scegli quella delle altre CNC (es. «Macchine CNC») → «Salva».",
                "Si apre il form della macchina di lavoro: controlla i dati e premi «Salva». Ora la CNC è nel menu.",
            ],
        },
        {
            "sintomo": "Il collector delle CNC non aggiorna le ore",
            "fare": [
                "Asset › Configurazione › «Macchine collegate» › Collector: il collector deve essere attivo e avere un «ultimo contatto» recente.",
                "Negli «IP o reti ammessi» del collector ci deve essere l'IP del suo PC; sulla macchina devono esistere i contatori Ore e Cicli («Crea contatori»).",
            ],
        },
        {
            "sintomo": "«Giacenza insufficiente» scaricando un ricambio",
            "fare": [
                "A magazzino ce n'è meno della quantità indicata: controlla il numero.",
                "Se il magazzino reale è diverso, chiedi a un amministratore una rettifica di inventario dalla scheda del ricambio.",
            ],
        },
        {
            "sintomo": "In «Da fare» una manutenzione non ha «✓ Fatta oggi»",
            "fare": [
                "Richiede il documento allegato, è affidata a un fornitore oppure è a contatore: usa «Registra».",
                "Il pulsante compare solo a chi può registrare le manutenzioni.",
            ],
        },
        {
            "sintomo": "Chiudendo l'intervento non compare «Segna anche la segnalazione come Risolta»",
            "fare": [
                "La casella compare solo se la segnalazione è ancora aperta e solo a chi gestisce i ticket di manutenzione.",
                "Chiudi l'intervento e chiedi a un gestore dei ticket di risolvere la segnalazione dal modulo Ticket.",
            ],
        },
        {
            "sintomo": "Chiudendo un intervento compare «risulta già chiuso: nessuna modifica registrata»",
            "fare": [
                "Il modulo era stato inviato due volte: la prima chiusura è valida, la seconda è stata ignorata.",
                "Apri l'intervento per controllare esito e storico.",
            ],
        },
        {
            "sintomo": "Il QR della macchina apre una pagina di errore",
            "fare": [
                "Controlla che l'asset esista ancora e non sia stato eliminato.",
                "Ristampa l'etichetta QR dalla scheda dell'asset.",
            ],
        },
    ],
}
