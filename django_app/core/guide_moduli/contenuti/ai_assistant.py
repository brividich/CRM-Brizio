GUIDA = {
    "slug": "ai_assistant",
    "titolo": "Assistente AI",
    "area": "Per tutti",
    "sintesi": "Domande in italiano sul portale e sulle procedure aziendali. Gira sui server dell'azienda.",
    "parole": "assistente ai chatbot chat domanda intelligenza artificiale",
    "url": "ai_assistant:chat",
    "prefissi": ("/assistente-ai/",),
    "dettaglio": [("Guida completa dell'Assistente AI", "ai_assistant:guida")],
    "uso": [
        {
            "id": "chiedere",
            "titolo": "Fare una domanda",
            "blocchi": [
                ("passi", [
                    "Clicca la stella in alto a destra (oppure premi Alt+A).",
                    "Scrivi la domanda come la diresti a un collega, per esempio «come chiedo un permesso di 2 ore?» o «cosa dice la procedura sui DPI?».",
                    "Leggi la risposta: quando usa un documento, ne indica la fonte. Aprila per controllare.",
                    "Se la risposta è sbagliata clicca 👎: aiuta a migliorarla.",
                ]),
                ("nota", "L'assistente può sbagliare: per le decisioni importanti controlla sempre la fonte. Non scrivere password o dati sanitari."),
            ],
        },
    ],
    "admin": [
        {
            "id": "config",
            "titolo": "Dove gira e come si configura",
            "blocchi": [
                ("ul", [
                    "Il modello di linguaggio gira su un server interno (Ollama); l'indirizzo è in OLLAMA_BASE_URL nel .env.",
                    "Le procedure SGI vengono indicizzate di notte: le risposte sulle procedure dipendono da questo indice.",
                    "Le FAQ suggerite dai 👎 si approvano in Amministrazione → «FAQ & Knowledge AI».",
                    "Il Setup Wizard (Server Dashboard → Assistente AI) ha la verifica completa e la modifica della configurazione AI.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "L'assistente non risponde o risponde «servizio non disponibile»",
            "fare": [
                "Controlla che il server AI sia acceso e raggiungibile dal server del portale.",
                "Setup Wizard → Server Dashboard → «Assistente AI»: lancia la verifica.",
                "Amministrazione → Monitoring → Centrale di comando: guarda lo stato del controllo AI.",
            ],
        },
        {
            "sintomo": "La prima risposta è lenta (decine di secondi)",
            "fare": [
                "Subito dopo un aggiornamento o un riavvio il portale prepara l'indice dei documenti: le prime risposte possono essere più lente, poi tornano normali.",
                "Dopo un aggiornamento che cambia l'indice lancia l'indicizzazione dal terminale del Setup Wizard (preset AI/RAG, index_sgi_documents).",
                "Se resta lenta: Centrale di comando → controllo AI (server AI spento o modello da ricaricare) e verifica che il qcluster giri (tiene caldo il modello).",
            ],
        },
        {
            "sintomo": "Non conosce una procedura nuova",
            "fare": [
                "Controlla in Presa visione procedure → «Log sync» che il documento sia stato letto.",
                "Aspetta l'indicizzazione notturna, oppure lanciala a mano dal terminale del Setup Wizard (preset AI/RAG).",
            ],
        },
    ],
}
