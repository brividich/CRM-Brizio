GUIDA = {
    "slug": "gestione_specifiche",
    "titolo": "Gestione specifiche",
    "area": "Qualità e sistema di gestione",
    "sintesi": "Specifiche tecniche dei clienti con MOD.133: ricezione, analisi, approvazione, distribuzione e verifica periodica.",
    "parole": "specifica specifiche cliente mod133 flow-down distribuzione revisione",
    "url": "gestione_specifiche:lista",
    "prefissi": ("/gestione-specifiche/",),
    "dettaglio": [("Guida completa Gestione specifiche", "gestione_specifiche:guida")],
    "uso": [
        {
            "id": "ciclo",
            "titolo": "Il ciclo di una specifica",
            "blocchi": [
                ("passi", [
                    "Si registra la specifica ricevuta (bozza) con il PDF.",
                    "Si compila la scheda MOD.133: requisiti, documenti interni impattati. L'assistente AI può precompilarla dal PDF: va sempre controllata.",
                    "Chi approva (diverso da chi ha compilato) approva.",
                    "Si distribuisce alle funzioni interessate, con le copie tracciate.",
                    "La verifica periodica ricorda di controllare se il cliente ha emesso una nuova revisione.",
                ]),
                ("p", "La guida completa con ogni schermata è nel collegamento in cima."),
            ],
        },
    ],
    "admin": [
        {
            "id": "config",
            "titolo": "Configurazione",
            "blocchi": [
                ("ul", [
                    "Promemoria, escalation e verifica periodica partono da soli (mail e notifica).",
                    "Gli allegati sono in archivio privato cifrato.",
                    "Ogni passaggio di stato resta nello storico, esportabile in PDF e CSV.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il pulsante «Approva» non c'è",
            "perche": "chi ha compilato la scheda non può approvarla (separazione dei ruoli).",
            "fare": ["Fai approvare a un'altra persona con il permesso di approvazione."],
        },
    ],
}
