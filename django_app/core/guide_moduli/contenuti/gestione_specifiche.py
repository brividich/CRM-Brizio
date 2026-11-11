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
            "id": "catalogo",
            "titolo": "Il catalogo per cartella e la sincronizzazione",
            "blocchi": [
                ("p", "Il cruscotto mostra una copertina per ogni cartella della share delle specifiche (di solito una per cliente). "
                      "Clicca la copertina per l'elenco della cartella: la ricerca cerca solo lì e «Nuova per …» ha già il cliente. "
                      "La ricerca e i filtri mostrano l'elenco su tutte le cartelle; «Copertine» / «Elenco» cambia la vista."),
                ("p", "Ogni 15 minuti il portale legge la cartella senza modificarla: un PDF nuovo diventa una specifica in bozza (codice e revisione dal nome «15500 REV.1.pdf», cliente dalla cartella) "
                      "con l'avviso a chi prende in carico; una revisione più recente diventa la nuova revisione; un file spostato viene ricollegato. "
                      "Il primo giro fotografa l'archivio: i PDF già presenti entrano in validità senza avvisi."),
            ],
        },
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
            "id": "sincronizzazione",
            "titolo": "Sincronizzazione con la cartella",
            "blocchi": [
                ("passi", [
                    "Apri «Amministrazione» → «Sincronizzazione con la cartella».",
                    "Controlla le spunte: sincronizzazione accesa, cartella raggiungibile dal sito, ultimo controllo recente.",
                    "«Sincronizza ora» fa subito il giro; «Spegni la sincronizzazione» la ferma.",
                    "In «Ultimo giro» trovi i numeri e i file lasciati fuori con il motivo: di solito basta correggere il nome del file (codice e «REV.N»).",
                ]),
            ],
        },
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
            "sintomo": "Un PDF messo nella cartella non compare nel catalogo",
            "fare": [
                "«Amministrazione» → «Sincronizzazione con la cartella»: la sincronizzazione deve essere accesa e la cartella raggiungibile; l'ultimo controllo dev'essere di pochi minuti fa (altrimenti sul server servono «manage.py setup_q_schedules» e il riavvio del qcluster).",
                "Guarda i file lasciati fuori: MOD.133 compilati, nomi senza codice, revisione non più recente o stesso codice e revisione già collegati a un altro file.",
                "Il nome del file deve essere «<codice> REV.<revisione>.pdf» e il file non deve stare in «_SUPERATO».",
            ],
        },
        {
            "sintomo": "Il pulsante «Approva» non c'è",
            "perche": "chi ha compilato la scheda non può approvarla (separazione dei ruoli).",
            "fare": ["Fai approvare a un'altra persona con il permesso di approvazione."],
        },
    ],
}
