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
            ],
        },
        {
            "id": "manutentori",
            "titolo": "Per i manutentori",
            "blocchi": [
                ("ul", [
                    "«Manutenzione» mostra lo scadenzario unico, dal più urgente.",
                    "Un ordine di lavoro (OdL) si registra e si chiude dalla sua scheda; si possono chiudere più OdL insieme.",
                    "Una manutenzione che non si riesce a fare in tempo si rinvia («Rinvia» nella pagina «Registra», "
                    "o trascinandola nel Calendario): la scadenza originale resta e, eseguita, la successiva riparte "
                    "dalla data di esecuzione.",
                    "Dalle verifiche periodiche i rilievi si segnalano senza creare ordini di lavoro.",
                    "Dalla scheda asset, menu «Altro»: «Dismetti» toglie la macchina dagli elenchi senza perdere lo "
                    "storico (si annulla con «Riattiva»); «Elimina» cancella solo un asset creato per errore, senza storico.",
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
    ],
    "problemi": [
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
            "sintomo": "Il QR della macchina apre una pagina di errore",
            "fare": [
                "Controlla che l'asset esista ancora e non sia stato eliminato.",
                "Ristampa l'etichetta QR dalla scheda dell'asset.",
            ],
        },
    ],
}
