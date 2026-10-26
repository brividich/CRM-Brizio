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
                    ("Registro OFI / NC", "modulo a sé («Registro OFI» nel menu Qualità, con la sua guida): i rilievi "
                     "degli audit diventano voci del registro, che si legano ai processi del catalogo. Nella scheda del "
                     "processo la scheda «OFI / NC» mostra le voci del processo."),
                    ("Certificazioni e audit esterni", "certificati con scadenze e sorveglianze, audit di enti, clienti e "
                     "autorità con rapporto e rilievi che entrano nel Registro OFI; riepilogo settimanale a RSGI. Prima "
                     "dell'audit, «Preparazione all'audit» controlla copertura delle clausole, programma interno, NC e "
                     "voci MOD.174 aperte e rilievi dell'audit precedente; dopo, il piano azioni per l'ente si scarica "
                     "dalle voci del registro e si registra la data di invio."),
                    ("SoA", "dichiarazione di applicabilità dei controlli ISO 27001."),
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
            "sintomo": "Un rilievo non compare nel registro OFI",
            "fare": [
                "Controlla che il rilievo sia stato classificato come OFI o NC e salvato.",
                "Apri il Registro OFI e togli i filtri di periodo.",
            ],
        },
    ],
}
