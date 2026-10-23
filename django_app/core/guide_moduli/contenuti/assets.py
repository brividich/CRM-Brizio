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
    ],
    "admin": [
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
                    "Le scadenze amministrative (assicurazioni, contratti) sono separate dai piani di manutenzione.",
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
    ],
    "problemi": [
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
            "sintomo": "Il collector delle CNC non aggiorna le ore",
            "fare": [
                "Admin Django → «Collector letture contatori»: il collector deve essere attivo e avere un «ultimo contatto» recente.",
                "L'IP della macchina del collector deve essere in ASSETS_METER_INGEST_ALLOWED_IPS; il contatore deve esistere sull'asset.",
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
