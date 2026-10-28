GUIDA = {
    "slug": "rilevazione_incidenti",
    "titolo": "Rilevazione incidenti",
    "area": "Sicurezza sul lavoro",
    "sintesi": "Segnalare incidenti, quasi incidenti (near miss) e situazioni pericolose, e analizzarli con l'RSPP.",
    "parole": "incidente infortunio near miss quasi incidente unsafe pericolo heatmap rspp",
    "url": "rilevazione_incidenti:lista",
    "prefissi": ("/rilevazione-incidenti/",),
    "uso": [
        {
            "id": "tipi",
            "titolo": "Che cosa si segnala",
            "blocchi": [
                ("def", [
                    ("Unsafe condition / atto non sicuro", "una situazione pericolosa in cui non è successo niente (per esempio olio a terra)."),
                    ("Near miss", "un quasi incidente: poteva farsi male qualcuno, ma non è successo."),
                    ("Incidente", "qualcuno si è fatto male o c'è stato un danno."),
                ]),
                ("nota", "In caso di infortunio prima si soccorre e si avvisa il preposto. La segnalazione si fa dopo."),
            ],
        },
        {
            "id": "segnalare",
            "titolo": "Fare una segnalazione",
            "blocchi": [
                ("passi", [
                    "Apri Rilevazione incidenti e clicca «+ Nuova rilevazione».",
                    "Scegli il tipo di evento, la «Data e ora rilevazione» e il «Reparto».",
                    "In «Descrizione avvenimento» racconta cosa è successo, con parole semplici.",
                    "Indica le «Persone coinvolte» e, se c'entra una macchina, il suo nome.",
                    "Se puoi, in «Dove è successo» scegli la pianta e clicca il punto (oppure scegli l'«Area planimetria»).",
                    "Clicca «Salva rilevazione».",
                ]),
                ("p", "Al salvataggio parte una mail di avviso a RSPP, preposti e RLS (senza nome della persona né descrizione). "
                      "Poi il RLS riceve la richiesta di approvazione; se approva, la riceve il RSPP. "
                      "Le decisioni si vedono nella rilevazione: «Approvazione RLS» con la data, poi la chiusura RSPP."),
            ],
        },
        {
            "id": "consultare",
            "titolo": "Consultare e analizzare",
            "blocchi": [
                ("ul", [
                    "La lista si filtra per tipo, reparto e periodo con «Filtra».",
                    "«Statistiche» mostra i numeri per reparto, causa e gravità; «Heatmap» mostra sulla piantina dove succedono più eventi.",
                    "La heatmap prende la posizione dal punto indicato, poi dalla macchina coinvolta, poi dal riquadro del reparto, "
                    "poi dalla zona delle macchine dello stesso reparto; sotto la pianta dice quante rilevazioni vengono da ogni fonte "
                    "e quante restano fuori (altre piante o senza indizi). Passando sul cerchio: reparti e tipi di evento.",
                    "Nel dettaglio: «Modifica», «PDF», «Gestisci RSPP» (analisi delle cause e misure da adottare, per l'RSPP).",
                    "«Export CSV» scarica l'elenco.",
                    "Il dipendente vede le proprie segnalazioni, preposto e responsabile quelle del team, la Sicurezza tutte.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "fonte",
            "titolo": "Dove stanno i dati",
            "blocchi": [
                ("p", "Rilevazione incidenti → «Impostazioni» → «SharePoint». Se sono compilati sia l'ID del sito sia l'ID della "
                      "lista SharePoint, i dati stanno sulla lista SharePoint; se uno dei due è vuoto, stanno nel database del portale. "
                      "«Stato modulo» dice quale modalità è attiva."),
                ("ul", [
                    "Con SharePoint il portale legge e scrive sulla lista tramite Microsoft Graph e tiene una copia locale per 60 secondi.",
                    "Credenziali Graph e ID della lista: Setup Wizard → Microsoft Graph / SharePoint.",
                    "«Liste personalizzate» definisce i valori dei menu a tendina (reparti, cause…).",
                    "«Info & Database» mostra lo stato delle tabelle.",
                ]),
            ],
        },
        {
            "id": "mail",
            "titolo": "Mail e approvazioni automatiche",
            "blocchi": [
                ("p", "Partono dalla regola AU3 delle Automazioni (Amministrazione → Automazioni → Regole), "
                      "solo con i dati nel database del portale: con la lista SharePoint la regola non scatta."),
                ("passi", [
                    "Nuova rilevazione: mail di avviso a rspp@, preposti@ e rls@costruzioninovicrom.it.",
                    "Richiesta di approvazione a rls@ (scade dopo 7 giorni). «Non approvo»: la rilevazione segna «Non approvato» e l'iter si ferma.",
                    "Se il RLS approva: «Approvazione RLS» = Approvato con la data, e richiesta di approvazione a rspp@.",
                    "Se il RSPP approva: la rilevazione risulta chiusa con la data di chiusura.",
                ]),
                ("nota", "Nome della persona e descrizione dell'avvenimento compaiono solo nelle mail di approvazione a RLS e RSPP."),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Permessi",
            "blocchi": [
                ("ul", [
                    "«Permessi ACL» nelle impostazioni porta alla pagina Accessi del modulo.",
                    "L'RSPP vede e chiude tutte le rilevazioni, l'RLS le legge tutte; le liste «preposti / RSPP» delle impostazioni valgono solo se il sistema «Ruoli e permessi» è spento.",
                    "Le rilevazioni storiche lette da SharePoint non hanno un autore sicuro: le vede solo chi ha visibilità su tutto.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "La lista è vuota o lentissima",
            "perche": "in modalità SharePoint i dati arrivano da Microsoft Graph.",
            "fare": [
                "Attendi un minuto e ricarica: la copia locale dura 60 secondi.",
                "Impostazioni → «SharePoint»: controlla l'ID della lista.",
                "Se l'errore parla di autorizzazione (401/403) il segreto dell'app Graph è scaduto: rinnovalo su Entra ID e aggiornalo dal Setup Wizard, poi riavvia il portale.",
            ],
        },
        {
            "sintomo": "Il RLS o il RSPP non ricevono la richiesta di approvazione",
            "fare": [
                "Automazioni → Regole: la regola AU3 deve essere attiva e non in bozza (e una sola: le vecchie copie vanno eliminate).",
                "Nello storico esecuzioni della regola AU3 controlla l'esito: in attesa di approvazione, scaduta (7 giorni) o già decisa.",
            ],
        },
        {
            "sintomo": "Un dipendente non vede la segnalazione che ha fatto",
            "fare": [
                "Le segnalazioni nuove registrano l'autore: controlla che abbia fatto l'accesso con il suo account.",
                "Se è una segnalazione storica (da SharePoint) la vede solo chi ha visibilità su tutto.",
            ],
        },
    ],
}
