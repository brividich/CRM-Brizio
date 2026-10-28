GUIDA = {
    "slug": "diario_preposto",
    "titolo": "Diario preposto",
    "area": "Sicurezza sul lavoro",
    "sintesi": "Il registro del preposto: segnalazioni di sicurezza con foto e le ispezioni periodiche.",
    "parole": "preposto diario segnalazione ispezione ispezioni sicurezza reparto",
    "url": "diario_preposto:lista",
    "prefissi": ("/diario-preposto/",),
    "uso": [
        {
            "id": "segnalare",
            "titolo": "Registrare una segnalazione",
            "blocchi": [
                ("passi", [
                    "Apri Diario preposto e clicca «+ Nuova segnalazione».",
                    "Controlla la «Data segnalazione» (è già quella di adesso).",
                    "Scrivi un «Titolo» breve, per esempio «Carrello senza cintura in reparto 2».",
                    "Nella «Descrizione» scrivi cosa hai visto, dove e chi era coinvolto.",
                    "Aggiungi le foto o i documenti negli allegati.",
                    "Clicca «Salva segnalazione».",
                ]),
                ("p", "Ogni segnalazione riceve un codice. Dal dettaglio puoi «Modifica», «Elimina» o «Apri PDF» per stamparla."),
                ("nota", "Al salvataggio parte una mail a RSPP, preposti e RLS con titolo, descrizione e il link alla segnalazione."),
            ],
        },
        {
            "id": "ispezioni",
            "titolo": "Registrare un'ispezione periodica",
            "blocchi": [
                ("passi", [
                    "Clicca «Ispezioni periodiche», poi «Nuova ispezione».",
                    "Scegli l'area o la macchina da controllare: compaiono le voci della checklist.",
                    "Per ogni voce indica l'esito e, se serve, una nota.",
                    "Clicca «Registra ispezione».",
                ]),
            ],
        },
        {
            "id": "cercare",
            "titolo": "Cercare ed esportare",
            "blocchi": [
                ("ul", [
                    "Usa la ricerca e il filtro per preposto, poi «Filtra».",
                    "«Esporta Excel» scarica l'elenco con i filtri attivi.",
                    "Il preposto vede le proprie segnalazioni, il responsabile quelle del suo team, la Sicurezza tutte.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "scrittura",
            "titolo": "Chi può scrivere",
            "blocchi": [
                ("p", "Diario preposto → «Impostazioni» → «Autorizzazioni scrittura» (solo amministratori)."),
                ("passi", [
                    "Cerca la persona per nome, username o email e aggiungila all'elenco.",
                    "Clicca «Salva impostazioni».",
                ]),
                ("nota", "Elenco vuoto = tutti quelli che hanno fatto l'accesso possono scrivere. Gli amministratori possono sempre. "
                         "Se il sistema «Ruoli e permessi» è acceso, conta la matrice e non questo elenco."),
            ],
        },
        {
            "id": "checklist",
            "titolo": "Voci delle ispezioni",
            "blocchi": [
                ("p", "Nelle Impostazioni si definiscono le voci della checklist per area o macchina e la frequenza delle ispezioni."),
            ],
        },
        {
            "id": "mail",
            "titolo": "Mail automatiche",
            "blocchi": [
                ("p", "Le mail partono dalle Automazioni (Amministrazione → Automazioni → Regole), non dal modulo."),
                ("ul", [
                    "AU57: a ogni nuova segnalazione, mail a rspp@, preposti@ e rls@costruzioninovicrom.it.",
                    "AU34: 14 giorni dopo la segnalazione, promemoria al RSPP per verificare il seguito.",
                    "Una regola importata nasce in bozza e spenta: va aperta, controllata e attivata.",
                ]),
            ],
        },
        {
            "id": "allegati",
            "titolo": "Dove stanno gli allegati",
            "blocchi": [
                ("p", "Gli allegati sono in un archivio privato sul server (cartella indicata da DIARIO_PREPOSTO_PRIVATE_ROOT nel .env) "
                      "e si scaricano solo dal portale, dopo il login. Non sono raggiungibili da un link diretto."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Un preposto non riesce a creare segnalazioni",
            "fare": [
                "Impostazioni → «Autorizzazioni scrittura»: se l'elenco non è vuoto, aggiungi la persona.",
                "Controlla che abbia l'accesso al modulo (Amministrazione → Accessi).",
            ],
        },
        {
            "sintomo": "Dopo una nuova segnalazione non arriva nessuna mail",
            "fare": [
                "Automazioni → Regole: la regola AU57 deve essere attiva e non in bozza.",
                "Nello storico esecuzioni della regola leggi l'esito dell'invio.",
            ],
        },
        {
            "sintomo": "Un allegato non si apre («file non trovato»)",
            "perche": "la cartella privata degli allegati non è raggiungibile o è stata spostata.",
            "fare": [
                "Controlla nel .env di produzione (config\\.env) il percorso DIARIO_PREPOSTO_PRIVATE_ROOT.",
                "Controlla che la cartella esista sul server e che l'utente del sito IIS la possa leggere.",
            ],
        },
    ],
}
