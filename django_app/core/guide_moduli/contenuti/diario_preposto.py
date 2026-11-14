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
                    "Controlla la «Data segnalazione» (è già quella di adesso; non può essere nel futuro).",
                    "Scrivi un «Titolo» breve, per esempio «Carrello senza cintura in reparto 2».",
                    "Nella «Descrizione» scrivi cosa hai visto, dove e chi era coinvolto.",
                    "Aggiungi le foto o i documenti negli allegati.",
                    "Clicca «Salva segnalazione».",
                ]),
                ("p", "Ogni segnalazione riceve un codice DP-anno-numero che non viene mai riusato. Dal dettaglio puoi «Modifica», «Elimina» o «Apri PDF» per stamparla."),
                ("nota", "Se un allegato non è valido (formato non ammesso, vuoto o troppo grande) non viene salvato niente: togli il file indicato e riprova."),
                ("nota", "Al salvataggio parte una mail a RSPP, preposti e RLS con titolo, descrizione e il link alla segnalazione."),
            ],
        },
        {
            "id": "integrita",
            "titolo": "Modifiche, eliminazione e storico",
            "blocchi": [
                ("ul", [
                    "Nella scheda la «Storia della segnalazione» mostra tutto in ordine dal fatto a oggi: registrazione, modifiche campo per campo, allegati aggiunti, tolti e scaricati, eliminazione e ripristino, notifiche partite o non partite.",
                    "In cima alla scheda «Situazione della segnalazione» dà l'esito dei controlli (registrata entro 2 giorni, allegati, impronte, download integri, notifiche, dati completi, presenza nel registro), il percorso Fatto → Registrata → Documentata → Notificata → Oggi con i giorni trascorsi e il confronto con le altre segnalazioni dello stesso preposto, con i link a precedente e successiva.",
                    "I riquadri in cima alla scheda dicono da quanti giorni c'è il fatto, quanto si è aspettato a registrarlo (giallo oltre 2 giorni), quanti allegati e modifiche ci sono e se le notifiche sono partite.",
                    "Se un collega salva la stessa segnalazione mentre la modifichi, il tuo salvataggio viene rifiutato: riapri la scheda e rifai la modifica.",
                    "«Elimina» chiede il motivo (almeno 5 caratteri). La segnalazione esce dall'elenco ma non viene cancellata: chi gestisce il modulo la ritrova e la può ripristinare.",
                    "La «X» su un allegato lo toglie dalla segnalazione; il file resta archiviato sul server.",
                    "Ogni allegato ha un'impronta digitale (SHA-256): se il file sul server viene alterato, il download si blocca con un avviso.",
                ]),
            ],
        },
        {
            "id": "ispezioni",
            "titolo": "Registrare un'ispezione periodica",
            "blocchi": [
                ("passi", [
                    "Clicca «Ispezioni periodiche», poi «Nuova ispezione».",
                    "Scrivi l'«Area» (obbligatoria) e, se serve, la «Macchina / impianto».",
                    "Spunta le voci della checklist conformi (le non spuntate contano come non conformi) e compila le voci di testo.",
                    "Clicca «Registra ispezione».",
                ]),
            ],
        },
        {
            "id": "cercare",
            "titolo": "Cercare ed esportare",
            "blocchi": [
                ("ul", [
                    "Usa la ricerca e il filtro per preposto, poi «Filtra»: anche il cruscotto sopra la tabella segue i filtri.",
                    "Il cruscotto mostra ultimi 7 e 30 giorni, segnalazioni senza allegati o registrate in ritardo, la prossima ispezione, l'andamento degli ultimi 12 mesi, i giorni della settimana, i preposti con più segnalazioni e le attività recenti.",
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
                ("p", "Nelle Impostazioni si sceglie la frequenza delle ispezioni (da 1 a 365 giorni, di base 7). Le voci della checklist sono quelle di partenza (area, protezioni macchina, DPI, note) e per ora non si modificano dal portale."),
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
            "id": "mail_scheda",
            "titolo": "Rimandare a mano la scheda di una segnalazione",
            "blocchi": [
                ("p", "Dal server si manda la scheda completa (codice, titolo, data, preposto, chi segnala, descrizione, "
                      "elenco allegati e link «Apri la segnalazione») nel formato delle mail NOVICROM HUB:"),
                ("passi", [
                    "Prova senza inviare: python manage.py invia_mail_preposto DP-2026-0012 --to rspp@costruzioninovicrom.it --dry-run",
                    "Invio: lo stesso comando senza --dry-run; --cc per la copia, più codici per più segnalazioni.",
                    "Con --allegati i file della segnalazione vanno anche in allegato, fino a 15 MB in tutto; quelli oltre restano solo in elenco.",
                ]),
                ("nota", "La mail compare in Automazioni → «Mail inviate»."),
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
            "sintomo": "Una segnalazione è sparita dall'elenco",
            "perche": "è stata eliminata: resta archiviata con il motivo.",
            "fare": [
                "Chi gestisce il modulo apre l'elenco e clicca «Eliminate».",
                "Nella scheda legge chi l'ha eliminata e perché e, se serve, clicca «Ripristina».",
            ],
        },
        {
            "sintomo": "Il download di un allegato dice «impronta diversa»",
            "perche": "il file sul server non è più quello caricato (sostituito, danneggiato o ripristinato da un backup diverso).",
            "fare": [
                "Non usare il file come prova: avvisa l'amministratore del portale.",
                "Nel Registro attività cerca «download_allegato» con esito integrita_ko.",
                "Recupera il file originale dal backup della cartella DIARIO_PREPOSTO_PRIVATE_ROOT.",
            ],
        },
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
