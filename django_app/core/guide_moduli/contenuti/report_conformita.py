GUIDA = {
    "slug": "report_conformita",
    "titolo": "Report conformità",
    "area": "Qualità e sistema di gestione",
    "sintesi": "I report pronti per gli audit ISO 9001, EN 9100, ISO 45001 e ISO 27001, in PDF ed Excel.",
    "parole": "report conformita audit iso 9001 9100 45001 27001 riesame direzione evidenze",
    "url": "report_conformita:index",
    "prefissi": ("/report-conformita/",),
    "uso": [
        {
            "id": "aprire",
            "titolo": "Aprire e scaricare un report",
            "blocchi": [
                ("passi", [
                    "Apri Report conformità: i report sono divisi per area (Qualità, Competenze, Salute e sicurezza, Sicurezza delle informazioni).",
                    "Clicca il report che ti serve.",
                    "Scegli il periodo (di solito gli ultimi 12 mesi) e clicca «Aggiorna».",
                    "Clicca «PDF» o «Excel» per scaricarlo.",
                ]),
                ("p", "Le righe critiche sono evidenziate. I numeri sono gli stessi a video, nel PDF e nell'Excel."),
            ],
        },
        {
            "id": "riesame",
            "titolo": "Riesame della direzione",
            "blocchi": [
                ("p", "«Apri il riesame» raccoglie gli indicatori di tutti i report che puoi vedere in un unico documento; «PDF riesame» lo scarica."),
            ],
        },
        {
            "id": "dati",
            "titolo": "Un dato è sbagliato?",
            "blocchi": [
                ("p", "«Dati e fonti» dice da quale modulo arriva ogni numero e spiega i due modi per correggerlo: correggere il dato "
                      "nel modulo di origine (la via giusta), oppure registrare una rettifica motivata con «Salva operazione»."),
            ],
        },
    ],
    "admin": [
        {
            "id": "permessi",
            "titolo": "Chi vede quale area",
            "blocchi": [
                ("def", [
                    ("Accesso al modulo", "report_conformita.modulo.view"),
                    ("Qualità e processi", "report_conformita.qualita.view"),
                    ("Competenze e qualifiche", "report_conformita.persone.view"),
                    ("Salute e sicurezza", "report_conformita.sicurezza.view"),
                    ("Sicurezza delle informazioni", "report_conformita.it.view (va assegnato a mano)"),
                ]),
                ("p", "Si assegnano in Amministrazione → Accessi. Ogni download PDF/Excel resta registrato nel registro di audit."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Un report mostra zero o numeri strani",
            "perche": "il report legge i dati dei moduli: se lì mancano, manca anche qui.",
            "fare": [
                "Apri «Dati e fonti» del report e guarda da quale modulo arriva il numero.",
                "Controlla il dato nel modulo di origine (per esempio Formazione o DPI) e correggilo lì.",
                "Clicca «Aggiorna» nel report.",
            ],
        },
    ],
}
