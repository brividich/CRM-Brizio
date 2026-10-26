GUIDA = {
    "slug": "sistema_gestione",
    "titolo": "Sistema di gestione e audit",
    "area": "Qualità e sistema di gestione",
    "sintesi": "Audit interni EN 9100, registro OFI / non conformità (MOD.174) e dichiarazione di applicabilità ISO 27001.",
    "parole": "audit auditor ofi non conformita nc mod174 soa 27001 sistema gestione",
    "url": "sistema_gestione:index",
    "prefissi": ("/sistema-gestione/", "/ofi-registro/"),
    "dettaglio": [
        ("Guida Audit interni", "sistema_gestione:audit_guida"),
        ("Guida Registro OFI", "registro_ofi:guida"),
    ],
    "uso": [
        {
            "id": "cosa",
            "titolo": "Cosa c'è nel modulo",
            "blocchi": [
                ("def", [
                    ("Audit interni", "programma annuale (MOD.034), piano (MOD.035A), checklist, rilievi e rapporto con PDF. "
                     "Con «Perimetro Part 145» nel piano l'audit compare nel Dossier PART 145 del modulo Asset."),
                    ("Registro OFI / NC", "opportunità di miglioramento e non conformità con azioni e verifica di efficacia (MOD.174). "
                     "Ogni voce ha un responsabile, un avanzamento PDCA passo passo, evidenze allegate e la cronologia; "
                     "«Le mie voci» e il «Cruscotto» mostrano cosa è aperto, scaduto o ricorrente."),
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
                    "Registro OFI: chi ha «Registro OFI - Inserisci/Modifica» gestisce tutte le voci; il responsabile di una "
                    "voce può farla avanzare, riaprirla e caricare evidenze anche senza quel permesso, purché possa leggere il registro.",
                    "I solleciti delle voci scadute vanno al responsabile e agli indirizzi di GESTIONE_SPECIFICHE "
                    "«OFI_REMINDER_EMAILS».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il rilievo di un ente non alza la priorità del processo",
            "fare": [
                "Nel rilievo il campo «Processo / area» deve riportare il codice o il nome del processo del catalogo "
                "(il modulo lo propone mentre scrivi); correggilo dalla voce del Registro OFI.",
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
        {
            "sintomo": "Il pulsante «Passa a …» non compare o la voce non si chiude",
            "fare": [
                "Il pulsante compare a chi gestisce il registro e al responsabile della voce: controlla il campo «Responsabile (utente)».",
                "Per chiudere una fase va scritto cosa è stato fatto in quella fase.",
                "Se c'è una CAR aperta la voce si chiude chiudendo la CAR, dopo la verifica di efficacia.",
            ],
        },
    ],
}
