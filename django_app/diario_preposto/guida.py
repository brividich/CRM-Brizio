"""Guida d'uso del Diario preposto (pulsante «? Guida» e PDF).

Testo semplice, stessi blocchi di ``core/guida_pdf.py``. Etichette e soglie sono
quelle del codice (``forms.TOLLERANZA_DATA_FUTURA``, ``EliminaSegnalazioneForm``
motivo minimo 5 caratteri, ``views.DIARIO_ALLEGATO_EXTENSIONS``,
``DiarioPrepostoImpostazioni.ispezione_frequenza_giorni`` 1-365): se cambiano, va
aggiornata anche questa guida e ``core/guide_moduli/contenuti/diario_preposto.py``.
"""
from __future__ import annotations

TITOLO = "Diario preposto"
SOTTOTITOLO = "Registro delle segnalazioni di sicurezza del preposto e delle ispezioni periodiche."

SEZIONI: list[dict] = [
    {
        "id": "cosa",
        "titolo": "A cosa serve",
        "blocchi": [
            ("p", "Il Diario preposto è il registro delle segnalazioni di sicurezza (D.Lgs. 81/2008 art. 19): "
                  "comportamenti non sicuri, condizioni pericolose, interventi del preposto. Accanto c'è il "
                  "registro delle ispezioni periodiche di area o macchina."),
            ("def", [
                ("Codice", "ogni segnalazione riceve un codice DP-anno-numero (es. DP-2026-0012). Non cambia mai "
                 "e non viene mai riusato, neanche se la segnalazione è eliminata."),
                ("Preposto / Chi segnala", "la persona che ha inserito la segnalazione, presa dal tuo accesso."),
                ("Storia della segnalazione", "a destra nella scheda (sotto, da telefono): dal fatto a oggi, chi ha "
                 "registrato, modificato (campo per campo), eliminato o ripristinato la segnalazione, chi ha aggiunto, "
                 "tolto o scaricato allegati e quali notifiche sono partite o non sono partite."),
                ("Situazione della segnalazione", "in cima alla scheda: esito complessivo («Tutto in ordine», "
                 "«da controllare» o «problemi»), riquadri di sintesi, percorso e controlli."),
                ("Riquadri della scheda", "giorni dal fatto, giorni impiegati a registrarla (giallo oltre 2), allegati, "
                 "modifiche, notifiche e ultima attività."),
                ("Percorso", "le tappe Fatto → Registrata → Documentata → Notificata → Oggi (o Eliminata), con data e "
                 "giorni trascorsi dal fatto. ✓ fatto, ! da controllare, ✕ problema, – non avvenuto."),
                ("Controlli", "registrata in tempo (entro 2 giorni), documentata con allegati, impronta degli allegati, "
                 "allegati integri ai download, notifiche partite, dati completi, presenza nel registro."),
                ("Il preposto", "le altre segnalazioni dello stesso preposto che puoi vedere: ultimi 12 mesi, stesso "
                 "mese, posizione nel registro, grafico mensile col mese di questa segnalazione (▲) e i link a "
                 "precedente e successiva."),
            ]),
        ],
    },
    {
        "id": "cruscotto",
        "titolo": "Il cruscotto dell'elenco",
        "blocchi": [
            ("p", "Sopra la tabella il cruscotto riassume il registro. I numeri seguono la ricerca e il filtro "
                  "«Preposto»: filtrando un preposto si vedono solo i suoi."),
            ("def", [
                ("Ultimi 7 / 30 giorni", "segnalazioni per data del fatto; sotto i 30 giorni il confronto con i 30 precedenti."),
                ("Senza allegati", "segnalazioni senza foto o documenti (in giallo se ce ne sono)."),
                ("Registrate in ritardo", "inserite nel diario più di 2 giorni dopo il fatto."),
                ("Ispezione", "prossima scadenza dell'ispezione periodica; in rosso se scaduta o se non ce n'è nessuna."),
                ("Notifiche non partite", "solo per chi gestisce il modulo: mail automatiche del diario andate in errore negli ultimi 30 giorni."),
                ("Andamento ultimi 12 mesi", "segnalazioni per mese; passando sopra una barra si legge il numero, «Vedi i numeri» li mostra tutti."),
                ("Giorno della settimana", "in quali giorni si concentrano i fatti negli ultimi 12 mesi."),
                ("Segnalazioni per preposto", "i primi 6 degli ultimi 12 mesi; il nome porta all'elenco filtrato."),
                ("Attività recenti", "le ultime operazioni sulle segnalazioni che puoi vedere: nuove, modifiche, allegati, eliminazioni."),
            ]),
        ],
    },
    {
        "id": "segnalare",
        "titolo": "Registrare una segnalazione",
        "blocchi": [
            ("passi", [
                "Apri Diario preposto e clicca «+ Nuova segnalazione».",
                "Controlla la «Data segnalazione» (è già quella di adesso). Non può essere nel futuro: "
                "si accettano al massimo 10 minuti di scarto dall'orologio del server.",
                "Scrivi il «Titolo» e la «Descrizione della segnalazione»: sono obbligatori.",
                "Aggiungi foto o documenti negli allegati (PDF, immagini, Word, Excel, testo, CSV).",
                "Clicca «Salva segnalazione».",
            ]),
            ("nota", "Se anche un solo file non è valido (formato non ammesso, vuoto o troppo grande) non viene "
                     "salvato niente: il messaggio in cima al modulo dice quale file togliere. Va riselezionato "
                     "anche il resto degli allegati."),
        ],
    },
    {
        "id": "modificare",
        "titolo": "Modificare e allegati",
        "blocchi": [
            ("ul", [
                "Dalla scheda clicca «Modifica»: puoi correggere data, titolo e descrizione e aggiungere allegati.",
                "Se un collega ha salvato la stessa segnalazione mentre la stavi modificando, il salvataggio "
                "viene rifiutato con un messaggio: riapri la scheda per vedere la versione attuale e rifai la "
                "modifica. Così nessuno sovrascrive il lavoro dell'altro senza accorgersene.",
                "La «X» accanto a un allegato lo toglie dalla segnalazione. Il file non viene cancellato dal "
                "server e resta nello storico.",
                "Per ogni allegato il portale registra un'impronta digitale (SHA-256) al caricamento. Al "
                "download la ricontrolla: se il file sul server è stato alterato, il download viene bloccato "
                "con un avviso. L'impronta compare anche nel PDF della segnalazione.",
            ]),
        ],
    },
    {
        "id": "eliminare",
        "titolo": "Eliminare e ripristinare",
        "blocchi": [
            ("passi", [
                "Nella scheda clicca «Elimina».",
                "Scrivi il motivo (almeno 5 caratteri) e conferma.",
            ]),
            ("p", "La segnalazione sparisce dall'elenco, dagli export e dai conteggi, ma non viene cancellata: "
                  "chi gestisce il modulo la ritrova con il filtro «Eliminate» nell'elenco, vede chi l'ha "
                  "eliminata e perché, e può cliccare «Ripristina» per rimetterla nel registro."),
        ],
    },
    {
        "id": "ispezioni",
        "titolo": "Ispezioni periodiche",
        "blocchi": [
            ("passi", [
                "Clicca «Ispezioni periodiche», poi «Nuova ispezione».",
                "Scrivi l'«Area» (obbligatoria) e, se serve, la «Macchina / impianto».",
                "Spunta le voci della checklist che risultano conformi; quelle non spuntate contano come non conformi.",
                "Compila le voci di testo obbligatorie e le «Note generali», poi clicca «Registra ispezione».",
            ]),
            ("p", "La pagina mostra la prossima scadenza: data dell'ultima ispezione più la frequenza impostata "
                  "(di base 7 giorni). Oltre quella data l'ispezione risulta scaduta."),
            ("nota", "Le voci della checklist sono quattro, fisse: area ordinata e percorsi liberi, protezioni e ripari della macchina, DPI, anomalie o azioni correttive. Per ora non si modificano dal portale."),
        ],
    },
    {
        "id": "cercare",
        "titolo": "Cercare ed esportare",
        "blocchi": [
            ("ul", [
                "Usa «Cerca» (codice, titolo, descrizione, nominativo) e il filtro «Preposto», poi «Filtra».",
                "«Esporta Excel» scarica l'elenco con i filtri attivi; «Apri PDF» stampa la singola segnalazione.",
                "Con «Ruoli e permessi» acceso: il preposto vede le proprie segnalazioni, il responsabile quelle "
                "del suo team, la Sicurezza tutte.",
            ]),
        ],
    },
    {
        "id": "admin",
        "titolo": "Per chi gestisce il modulo",
        "blocchi": [
            ("ul", [
                "«Impostazioni»: elenco delle persone autorizzate a scrivere (vuoto = tutti quelli che hanno fatto "
                "l'accesso) e frequenza delle ispezioni, da 1 a 365 giorni. Ogni salvataggio finisce nel registro "
                "attività con i valori prima e dopo.",
                "Con «Ruoli e permessi» acceso conta la matrice dei permessi, non l'elenco delle Impostazioni.",
                "Filtro «Eliminate» nell'elenco e pulsante «Ripristina» nella scheda: solo per chi gestisce il modulo.",
            ]),
        ],
    },
]
