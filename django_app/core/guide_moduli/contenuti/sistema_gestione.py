GUIDA = {
    "slug": "sistema_gestione",
    "titolo": "Sistema di gestione e audit",
    "area": "Qualità e sistema di gestione",
    "sintesi": "Audit interni EN 9100, registro OFI / non conformità (MOD.174) e dichiarazione di applicabilità ISO 27001.",
    "parole": "audit auditor ofi non conformita nc mod174 soa 27001 sistema gestione",
    "url": "sistema_gestione:index",
    "prefissi": ("/sistema-gestione/",),
    "dettaglio": [
        ("Guida Audit interni", "sistema_gestione:audit_guida"),
    ],
    "uso": [
        {
            "id": "cosa",
            "titolo": "Cosa c'è nel modulo",
            "blocchi": [
                ("def", [
                    ("Audit interni", "programma annuale (MOD.034), piano (MOD.035A), checklist, rilievi e rapporto con PDF. "
                     "Con «Perimetro Part 145» nel piano l'audit compare nel Dossier PART 145 del modulo Asset."),
                    ("Checklist per norma", "EN 9100, ISO 45001 e UNI/PdR 125 hanno ciascuna una checklist a revisioni; "
                     "quella attiva si carica negli audit con la norma spuntata. Per ISO 45001 e PdR 125 il portale "
                     "propone una bozza da verificare e attivare."),
                    ("Audit ISMS", "con «Modulistica: Audit ISMS» nel piano l'audit usa il MOD.171 e il rapporto MOD.168: "
                     "requisiti ISO/IEC 27001 e i 93 controlli ISO/IEC 27002 con il livello 0-4 già preso dalla SoA "
                     "approvata. NC e AP vanno nel Registro OFI, i COM restano nel rapporto; dopo la chiusura i livelli "
                     "diversi possono aprire una nuova revisione della SoA in bozza."),
                    ("Registro OFI / NC", "modulo a sé («Registro OFI» nel menu Qualità, con la sua guida): i rilievi "
                     "degli audit diventano voci del registro, che si legano ai processi del catalogo. Nella scheda del "
                     "processo la scheda «OFI / NC» mostra le voci del processo."),
                    ("Certificazioni e audit esterni", "certificati con scadenze e sorveglianze, audit di enti, clienti e "
                     "autorità con rapporto e rilievi che entrano nel Registro OFI; riepilogo settimanale a RSGI. Prima "
                     "dell'audit, «Preparazione all'audit» controlla copertura delle clausole, programma interno, NC e "
                     "voci MOD.174 aperte e rilievi dell'audit precedente; dopo, il piano azioni per l'ente si scarica "
                     "dalle voci del registro e si registra la data di invio."),
                    ("SoA", "dichiarazione di applicabilità dei controlli ISO 27001. Da ogni revisione «Analisi del "
                     "rischio» apre il registro del MOD.165: rischio residuo per minaccia ricalcolato dalle vulnerabilità "
                     "della SoA, monitoraggio dei controlli e piano di trattamento OT."),
                ]),
                ("p", "Ogni parte ha la sua guida passo passo: i collegamenti sono in cima."),
            ],
        },
    ],
    "admin": [
        {
            "id": "permessi",
            "titolo": "Permessi e ruoli",
            "blocchi": [
                ("ul", [
                    "Auditor interni ed esterni qualificati si gestiscono nell'elenco auditor del modulo.",
                    "Programma e piano vanno approvati da chi ha il permesso di approvazione (Qualità).",
                    "La scheda processo mostra chi ricopre il ruolo owner e chi è operativo sulle mansioni del processo "
                    "(Struttura organizzativa dell'Anagrafica); il piano di audit propone queste persone come "
                    "responsabili e auditati, da aggiungere con «Aggiungi».",
                    "Permessi di pagina: Amministrazione → Accessi, modulo Sistema di gestione.",
                    "Registro OFI: permessi e solleciti sono nella guida del modulo Registro OFI / NC.",
                    "«Checklist per norma» (EN 9100, ISO 45001, UNI/PdR 125): la consultazione segue il permesso di "
                    "consultazione audit, creazione bozze, modifica e attivazione il permesso di modifica audit.",
                    "Audit ISMS: compila il rapporto solo il team assegnato all'audit; la proposta di revisione della SoA "
                    "dopo la chiusura richiede il permesso di modifica della SoA.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il rilievo di un ente non alza la priorità del processo",
            "fare": [
                "La voce del Registro OFI deve essere collegata al processo: apri la voce e controlla «Collegamenti → "
                "Processo del catalogo»; se manca, «Modifica» e scegli il processo. Senza scelta vale il «Processo / "
                "area» uguale al codice o al nome del processo.",
                "Contano solo i rilievi degli ultimi 24 mesi.",
            ],
        },
        {
            "sintomo": "Un audit con ISO 45001 o PdR 125 non ha le domande della norma",
            "fare": [
                "In «Audit interni» › «Checklist per norma» la norma deve avere una revisione «Attiva»: crea la bozza di "
                "base, falla verificare a RSGI e attivala.",
                "La checklist si carica all'avvio: per un audit già avviato aggiungi le verifiche con «Domanda aggiuntiva».",
            ],
        },
        {
            "sintomo": "Nell'audit ISMS i controlli non hanno il livello della SoA",
            "fare": [
                "Il livello di partenza viene dalla SoA approvata in vigore al momento della creazione dei dati ISMS: se "
                "non c'era una SoA approvata i livelli restano «da valutare» e l'auditor li inserisce.",
                "Un COM (commento) non crea voci nel Registro OFI: solo NC e AP.",
            ],
        },
        {
            "sintomo": "Un rilievo non compare nel registro OFI",
            "fare": [
                "Controlla che il rilievo sia stato classificato come OFI o NC e salvato.",
                "Apri il Registro OFI e togli i filtri di periodo.",
            ],
        },
    ],
}
