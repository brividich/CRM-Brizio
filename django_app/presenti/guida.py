"""Guida d'uso del modulo Presenti in azienda (pulsante «? Guida» e PDF).

Testo semplice, stessi blocchi di ``core/guida_pdf.py``. Le etichette e i tempi
citati sono quelli del codice (``views.AGGIORNA_LISTA``, ``views.AGGIORNA_APPELLO``,
``services.DURATA_CACHE``, ``uscite.GIORNI_INDIETRO``, schedule in
``automazioni/schedules.py``): se cambiano, va aggiornata anche questa guida e
``core/guide_moduli/contenuti/presenti.py``.
"""
from __future__ import annotations

TITOLO = "Presenti in azienda"
SOTTOTITOLO = "Chi è in azienda adesso, appello di evacuazione e uscite non timbrate, dalle timbrature Solari."

SEZIONI: list[dict] = [
    {
        "id": "cosa",
        "titolo": "A cosa serve",
        "blocchi": [
            ("p", "Il modulo mostra chi è in azienda in questo momento leggendo le timbrature del sistema Solari. "
                  "Una persona è presente quando la sua ultima timbratura di oggi è un'entrata."),
            ("p", "Sostituisce il PDF «CN-PRESENZE» che uno script generava ogni ora: qui la lista si aggiorna da "
                  "sola e il PDF si può ancora scaricare o pubblicare su SharePoint."),
            ("def", [
                ("Presenti adesso", "la lista live con turno, matricola, nome, reparto, ora di entrata e incarichi di sicurezza."),
                ("Appello di evacuazione", "l'elenco per contare le persone al punto di raccolta, condiviso fra chi conta."),
                ("Uscite non timbrate", "le giornate chiuse con un'entrata e senza uscita."),
                ("Pallino «In azienda»", "il pallino verde accanto al nome nell'elenco dipendenti e nella scheda dipendente; "
                 "grigio quando la persona non è in azienda."),
            ]),
        ],
    },
    {
        "id": "lista",
        "titolo": "La lista dei presenti",
        "blocchi": [
            ("ul", [
                "La tabella si ricarica da sola ogni 30 secondi, senza ricaricare la pagina. In fondo c'è l'ora "
                "dell'ultima lettura delle timbrature.",
                "Le timbrature vengono lette al massimo una volta al minuto per tutto il portale: una timbratura "
                "appena fatta può comparire con un minuto di ritardo.",
                "In alto ci sono i contatori: presenti in totale e, per ogni incarico di sicurezza, quante persone con "
                "quell'incarico sono in azienda.",
                "Cerca per nome, matricola o reparto; filtra per reparto o per incarico. I filtri restano attivi "
                "anche durante gli aggiornamenti.",
                "«PDF» scarica la lista nel formato del vecchio report CN-PRESENZE.",
                "Il nome porta alla scheda dipendente. Le persone senza link non sono collegate all'anagrafica del "
                "portale (codice fiscale diverso o mancante): il numero è indicato in fondo alla lista.",
            ]),
            ("p", "Gli incarichi (Preposto, Squadra Antincendio, Addetto Primo Soccorso, RLS, ASPP, RSPP…) vengono "
                  "dall'organigramma della sicurezza ISO 45001 in Anagrafica: si aggiornano lì, non in questo modulo."),
        ],
    },
    {
        "id": "appello",
        "titolo": "L'appello di evacuazione",
        "blocchi": [
            ("passi", [
                "Apri «Appello di evacuazione» e premi «Avvia appello adesso». Segna «È un'esercitazione» se è una prova.",
                "L'elenco è la fotografia di chi risulta in azienda in quel momento: chi entra dopo non compare.",
                "Al punto di raccolta tocca ogni persona trovata: diventa verde con l'ora e il nome di chi l'ha contata. "
                "Toccala di nuovo per togliere la spunta.",
                "Più persone possono contare insieme dal telefono: le spunte degli altri compaiono entro 3 secondi. "
                "In cima restano sempre le persone «Da trovare».",
                "Quando hai finito premi «Chiudi appello». «Stampa» produce il PDF con la colonna «CONTATO».",
            ]),
            ("nota", "Se il database delle timbrature non risponde, l'appello parte dall'ultima lista letta. "
                     "Tieni comunque a portata di mano il registro visitatori e l'elenco dei fornitori in azienda: "
                     "l'appello comprende solo chi timbra."),
            ("p", "Gli appelli conclusi restano nello storico in fondo alla pagina, con il PDF."),
        ],
    },
    {
        "id": "uscite",
        "titolo": "Uscite non timbrate",
        "blocchi": [
            ("p", "Elenca le giornate passate in cui l'ultima timbratura è un'entrata: la persona è uscita senza "
                  "timbrare. Chi è capo vede le persone della sua squadra (organigramma); l'amministratore vede tutti."),
            ("p", "Ogni mattina alle 7:30 (lunedì-sabato) il portale controlla gli ultimi 3 giorni e manda al capo una "
                  "notifica e una mail con le giornate nuove. La stessa giornata non viene segnalata due volte. "
                  "La colonna «Capo avvisato» dice quando e come è partito l'avviso."),
        ],
    },
    {
        "id": "permessi",
        "titolo": "Chi può fare cosa",
        "blocchi": [
            ("def", [
                ("Lista dei presenti e pallino", "tutti gli utenti del portale."),
                ("Appello di evacuazione", "tutti: in emergenza chiunque deve poter aprire l'appello e contare."),
                ("Uscite non timbrate", "ogni capo per la sua squadra; tutta l'azienda con il permesso «Uscite non "
                 "timbrate (tutti)», di default solo admin."),
                ("Impostazioni", "solo admin, salvo diversa assegnazione in Accessi."),
            ]),
        ],
    },
    {
        "id": "admin",
        "titolo": "Amministratore: configurazione",
        "blocchi": [
            ("p", "Il collegamento al database Solari sta nel file .env del server, chiavi SOLARI_DB_SERVER, "
                  "SOLARI_DB_USER, SOLARI_DB_PASSWORD (login con la sola lettura), SOLARI_DB_DRIVER, "
                  "SOLARI_DB_ANAGRAFICO, SOLARI_DB_TIMBRATURE e SOLARI_TURNO_NORMALE_ELEM. Dopo la modifica va "
                  "riavviato il portale."),
            ("p", "In «Impostazioni» si attiva la pubblicazione del PDF su SharePoint (ogni 30 minuti, stesso file "
                  "CN-PRESENZE.pdf della raccolta «CN Documentazione») e l'avviso mattutino delle uscite non timbrate. "
                  "«Pubblica il PDF adesso» prova subito la pubblicazione e mostra l'esito."),
            ("p", "Gli incarichi del vecchio config.ini si importano una volta con il comando "
                  "«importa_incarichi_presenze» (prima senza --apply per vedere le differenze)."),
        ],
    },
    {
        "id": "problemi",
        "titolo": "Se qualcosa non va",
        "blocchi": [
            ("def", [
                ("«Il database delle timbrature non risponde»", "il server Solari è irraggiungibile: la pagina riprova da "
                 "sola. Se dura, controlla la rete verso il server Solari e il login nel .env."),
                ("«Database timbrature Solari non configurato»", "mancano le chiavi SOLARI_DB_* nel .env del server."),
                ("Una persona presente non ha il link alla scheda", "il codice fiscale in Solari e in Anagrafica non "
                 "coincide: correggilo in uno dei due."),
                ("Un incarico non compare", "manca il ruolo nell'organigramma della sicurezza ISO 45001, oppure "
                 "l'assegnazione ha una data di fine passata."),
                ("Il pallino non compare", "il pallino si nasconde quando le timbrature non sono leggibili, per non "
                 "mostrare un «Fuori» sbagliato."),
            ]),
        ],
    },
]
