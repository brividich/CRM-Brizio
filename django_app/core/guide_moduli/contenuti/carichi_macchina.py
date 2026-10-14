GUIDA = {
    "slug": "carichi_macchina",
    "titolo": "Carichi macchina",
    "area": "Produzione e operations",
    "sintesi": "Il piano dei lavori sulle macchine, giorno per giorno: tabella stile Excel e Gantt con trascinamento.",
    "parole": "carichi macchina pianificazione piano gantt turni lavorazione commessa",
    "url": "gestione_carichi_macchina:excel",
    "prefissi": ("/carichi-macchina/",),
    "uso": [
        {
            "id": "leggere",
            "titolo": "Leggere il piano",
            "blocchi": [
                ("ul", [
                    "La vista tabella mostra le macchine in riga e i giorni in colonna. «‹ Prec.», «Oggi» e «Succ. ›» cambiano settimana.",
                    "Il Gantt mostra gli stessi lavori come barre colorate per commessa, famiglia o stato.",
                    "«Turni: ON» mostra i lavori divisi per turno (1°, 2°, notte).",
                ]),
            ],
        },
        {
            "id": "inserire",
            "titolo": "Inserire un lavoro",
            "blocchi": [
                ("passi", [
                    "Clicca «+ Aggiungi lavoro» (oppure clicca una cella vuota della tabella).",
                    "Scegli macchina, giorni, turno e tipo lavorazione (Finitura, Sgrossatura, Assieme, Ripristino).",
                    "Se compare l'avviso di sovrapposizione, usa «usa questo slot» per prendere il primo posto libero.",
                    "Salva.",
                ]),
                ("p", "«🔮 AI» propone durata e macchina più adatta guardando lo storico: è un suggerimento, decidi tu."),
            ],
        },
        {
            "id": "spostare",
            "titolo": "Spostare un lavoro",
            "blocchi": [
                ("passi", [
                    "Nel Gantt trascina la barra su un altro giorno o su un'altra macchina.",
                    "Se si sovrappone ad altri lavori compare un riepilogo di cosa verrà spostato: controlla e conferma.",
                    "Spunta «Sposta anche la coda» se vuoi spostare anche tutti i lavori successivi.",
                ]),
                ("nota", "Gli spostamenti contano solo i giorni lavorativi: sabato e domenica vengono saltati. Se sbagli c'è l'annulla."),
            ],
        },
    ],
    "admin": [
        {
            "id": "macchine",
            "titolo": "Impostazioni macchine",
            "blocchi": [
                ("p", "«Impostazioni» → Impostazioni macchine: per ogni macchina le ore al giorno e i turni ammessi (2° turno, notte). "
                      "La capacità è ore al giorno × numero di turni abilitati. Gli stessi interruttori sono nel pannello macchina del Gantt."),
            ],
        },
        {
            "id": "registro",
            "titolo": "Registro azioni e permessi",
            "blocchi": [
                ("ul", [
                    "«Registro»: chi ha creato, modificato, spostato o eliminato un lavoro e quando.",
                    "Per modificare serve il permesso «piano.edit»; con il solo «piano.view» non compaiono i pulsanti di modifica.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona vede il piano ma non può modificarlo",
            "fare": [
                "Amministrazione → Accessi: dai il permesso di modifica del piano (piano.edit) al suo ruolo o a lei.",
                "Falle ricaricare la pagina.",
            ],
        },
        {
            "sintomo": "Lavori segnati in rosso",
            "perche": "la macchina ha più lavori di quanti ne regge in quella fascia oraria.",
            "fare": [
                "Apri il pannello della macchina e controlla i turni abilitati.",
                "Sposta uno dei lavori o abilita un turno in più nelle Impostazioni macchine.",
            ],
        },
    ],
}
