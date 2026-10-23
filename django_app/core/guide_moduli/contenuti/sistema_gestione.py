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
                    ("Registro OFI / NC", "opportunità di miglioramento e non conformità con azioni e verifica di efficacia (MOD.174)."),
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
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Un rilievo non compare nel registro OFI",
            "fare": [
                "Controlla che il rilievo sia stato classificato come OFI o NC e salvato.",
                "Apri il Registro OFI e togli i filtri di periodo.",
            ],
        },
    ],
}
