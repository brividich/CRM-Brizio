GUIDA = {
    "slug": "rentri",
    "titolo": "RENTRI · Registro rifiuti",
    "area": "Sicurezza sul lavoro",
    "sintesi": "Registro di carico e scarico dei rifiuti, scadenze e giacenze nel deposito temporaneo.",
    "parole": "rentri rifiuti cer eer carico scarico formulario fir deposito giacenza",
    "url": "rentri_menu",
    "prefissi": ("/rentri/",),
    "uso": [
        {
            "id": "tipi",
            "titolo": "I quattro tipi di registrazione",
            "blocchi": [
                ("def", [
                    ("C - Carico", "il rifiuto viene prodotto e messo nel deposito."),
                    ("O - Scarico originale", "il rifiuto parte con il formulario (quantità stimata)."),
                    ("M - Scarico effettivo", "la quantità vera pesata dal destinatario."),
                    ("R - Rettifica scarico", "correzione di uno scarico già registrato."),
                ]),
            ],
        },
        {
            "id": "registrare",
            "titolo": "Registrare un movimento",
            "blocchi": [
                ("passi", [
                    "Apri RENTRI e clicca la voce del tipo giusto (per esempio «C - Carico»).",
                    "Il modulo procede a passi: compila «Data» e clicca «Avanti →».",
                    "Cerca il «Codice CER» scrivendo il numero o il nome del rifiuto.",
                    "Per gli scarichi scegli il movimento collegato (Rif. Op): il portale mostra solo quelli collegabili.",
                    "Scrivi la «Quantità» e, se serve, «Pericolosità», «Note RENTRI» e l'«Allegato».",
                    "Conferma. Il numero di registrazione (anno/progressivo) lo assegna il portale.",
                ]),
                ("p", "Con «← Indietro» torni al passo prima senza perdere i dati."),
            ],
        },
        {
            "id": "consultare",
            "titolo": "Elenco, scadenze e giacenze",
            "blocchi": [
                ("ul", [
                    "«Elenco registrazioni»: ogni carico con i suoi scarichi, raggruppati in «famiglie» APERTA o CHIUSA. "
                    "Filtra per anno, tipo e «Stato famiglia»; «Espandi»/«Comprimi» apre o chiude tutto.",
                    "«Scadenzario»: formulari mancanti, da comunicare, bozze.",
                    "«Giacenze»: quanto rifiuto c'è per codice, con il semaforo del deposito temporaneo e l'export CSV.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "impostazioni",
            "titolo": "Impostazioni",
            "blocchi": [
                ("p", "RENTRI → «Impostazioni»: «Ragione sociale», «Codice iscrizione RENTRI», «Referenti operativi» e «Note operative». "
                      "Clicca «Salva impostazioni»."),
                ("p", "Le soglie in giorni del semaforo del deposito temporaneo sono nella configurazione del portale (SiteConfig)."),
            ],
        },
        {
            "id": "import",
            "titolo": "Importare lo storico",
            "blocchi": [
                ("passi", [
                    "Prepara il file CSV esportato (separato da ; oppure da ,).",
                    "Dal menu RENTRI usa l'import: prima compare l'anteprima, poi confermi.",
                    "In alternativa sul server: comando import_rentri_csv.",
                ]),
                ("p", "Per controllare eventuali numeri doppi c'è il comando di sola lettura rentri_id_duplicati --solo-anomalie."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Uno scarico non trova il carico da collegare",
            "fare": [
                "Controlla che il carico abbia lo stesso codice CER.",
                "Controlla che il carico non sia già completamente scaricato (famiglia CHIUSA).",
                "Se il carico manca, registralo prima con «C - Carico».",
            ],
        },
        {
            "sintomo": "Il numero di registrazione sembra sbagliato o doppio",
            "fare": [
                "Lancia rentri_id_duplicati --solo-anomalie dal terminale del Setup Wizard.",
                "I numeri non si riciclano: un movimento eliminato lascia un buco, ed è corretto così.",
            ],
        },
    ],
}
