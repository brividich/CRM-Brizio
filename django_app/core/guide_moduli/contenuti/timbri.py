GUIDA = {
    "slug": "timbri",
    "titolo": "Registro timbri",
    "area": "Persone e HR",
    "sintesi": "Timbri, firme e sigle assegnati al personale (MOD.130-RTF), con le immagini.",
    "parole": "timbro timbri firma firme sigla sigle",
    "url": "timbri:index",
    "prefissi": ("/timbri/",),
    "dettaglio": [("Guida completa del Registro timbri", "timbri:index", "?guida=1")],
    "uso": [
        {
            "id": "consultare",
            "titolo": "Trovare il timbro di una persona",
            "blocchi": [
                ("passi", [
                    "Apri Registro timbri.",
                    "Scrivi il nome o il codice del timbro nella ricerca (anche senza spazi: «cnoq101»).",
                    "Clicca la riga per vedere i timbri attivi; «Copia» e «Scarica» compaiono solo se hai il permesso.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "gestire",
            "titolo": "Gestire il registro",
            "blocchi": [
                ("ul", [
                    "I dipendenti non si creano qui: devono esistere in Anagrafica.",
                    "Creare, modificare e archiviare record: ruoli admin e amministrazione.",
                    "Chi può copiare o scaricare le immagini si decide in Impostazioni → Permessi del registro.",
                    "Il reset del registro è solo per i superutenti.",
                ]),
                ("p", "Tutti i dettagli sono nella guida completa (collegamento in cima)."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona non compare nel registro",
            "fare": ["Controlla che esista in Anagrafica e sia in forza.", "Ricarica il registro."],
        },
        {
            "sintomo": "Il pulsante «Copia» o «Scarica» non c'è",
            "fare": ["Registro timbri → Impostazioni → Permessi: aggiungi il ruolo o la persona."],
        },
    ],
}
