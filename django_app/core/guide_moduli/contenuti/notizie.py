GUIDA = {
    "slug": "notizie",
    "titolo": "Notizie e comunicazioni",
    "area": "Per tutti",
    "sintesi": "Le comunicazioni aziendali: si leggono qui e, quando è richiesto, si conferma di averle lette.",
    "parole": "notizia notizie comunicazione comunicazioni avviso circolare conferma lettura",
    "url": "notizie_lista",
    "prefissi": ("/notizie/",),
    "uso": [
        {
            "id": "leggere",
            "titolo": "Leggere le comunicazioni",
            "blocchi": [
                ("passi", [
                    "Apri Notizie: vedi «Notizie e comunicazioni».",
                    "Clicca una notizia per leggerla. Gli allegati sono in fondo.",
                    "Se la notizia è obbligatoria, in fondo clicca «Confermo di aver letto e compreso».",
                ]),
                ("p", "«Obbligatorie» mostra le comunicazioni che devi ancora confermare: clicca «Leggi e conferma» su ognuna."),
            ],
        },
    ],
    "admin": [
        {
            "id": "pubblicare",
            "titolo": "Pubblicare una notizia",
            "blocchi": [
                ("passi", [
                    "Apri «Dashboard Notizie» e clicca «Nuova Notizia».",
                    "Scrivi titolo e testo in «Contenuto».",
                    "In «Audience Ruoli» scegli chi la deve vedere. Se non scegli nessuno la vedono tutti.",
                    "Aggiungi eventuali file in «Allegati e Documenti».",
                    "Indica se la lettura è obbligatoria.",
                    "Clicca «Salva bozza» per finirla dopo, oppure «Salva e pubblica».",
                ]),
            ],
        },
        {
            "id": "report",
            "titolo": "Chi ha letto",
            "blocchi": [
                ("p", "«Report Letture» mostra per ogni notizia chi l'ha letta e confermata; «Esporta CSV» scarica l'elenco."),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Chi può pubblicare",
            "blocchi": [
                ("p", "Notizie → «Impostazioni» (Centro impostazioni comunicazioni): «Salva permessi dashboard» decide chi entra nella "
                      "dashboard di gestione. Con il sistema «Ruoli e permessi» acceso conta il permesso «gestire» su Notizie "
                      "(ruoli Gestione personale, Amministrazione e RSPP)."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona non vede la notizia",
            "fare": [
                "Apri la notizia in modifica e controlla «Audience Ruoli»: la persona deve avere uno dei ruoli scelti.",
                "Controlla che la notizia sia pubblicata e non archiviata.",
            ],
        },
        {
            "sintomo": "Un allegato non si scarica",
            "fare": [
                "Gli allegati si scaricano solo dal portale e solo da chi vede la notizia.",
                "Se l'errore è «file non trovato», controlla nel .env il percorso PRIVATE_ATTACHMENTS_ROOT e che la cartella esista sul server.",
            ],
        },
    ],
}
