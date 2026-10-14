GUIDA = {
    "slug": "fornitori",
    "titolo": "Fornitori",
    "area": "Produzione e operations",
    "sintesi": "Anagrafica fornitori con documenti, ordini, valutazioni di qualità e asset assegnati.",
    "parole": "fornitore fornitori ordine ordini valutazione albo partita iva",
    "url": "fornitori:index",
    "prefissi": ("/fornitori/",),
    "uso": [
        {
            "id": "cercare",
            "titolo": "Cercare un fornitore",
            "blocchi": [
                ("passi", [
                    "Apri Fornitori e clicca «📋 Elenco fornitori».",
                    "Cerca per ragione sociale, partita IVA o città e clicca «Filtra».",
                    "Clicca «Apri →» per la scheda.",
                ]),
            ],
        },
        {
            "id": "scheda",
            "titolo": "La scheda del fornitore",
            "blocchi": [
                ("def", [
                    ("Documenti", "certificati e contratti: «Carica» per aggiungerne (PDF, Office o immagini, massimo 15 MB)."),
                    ("Ordini", "con stato e importo: la somma è la spesa totale. «Salva ordine»."),
                    ("Valutazioni", "qualità, puntualità e comunicazione da 1 a 5 stelle. «Salva valutazione»."),
                    ("Asset", "macchine o contratti assegnati al fornitore. «Assegna» / «Rimuovi»."),
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "gestire",
            "titolo": "Creare e disattivare",
            "blocchi": [
                ("ul", [
                    "«+ Nuovo fornitore», compila i dati e clicca «Salva fornitore».",
                    "Un fornitore che non si usa più si disattiva («Disattiva»), non si elimina: i suoi ordini e le manutenzioni restano collegati.",
                    "I permessi del modulo Fornitori sono separati da quelli di Anagrafica HR (Amministrazione → Accessi).",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il fornitore non compare nelle manutenzioni degli asset",
            "fare": ["Controlla che il fornitore sia attivo.", "Nella scheda fornitore assegna l'asset o il contratto."],
        },
    ],
}
