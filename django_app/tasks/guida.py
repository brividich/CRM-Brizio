"""Guida d'uso del modulo KICK-OFF (pulsante «? Guida» in testa alle pagine).

Testo semplice, niente HTML: il template lo mostra con l'autoescape.
Blocchi di una sezione: ("p", testo) paragrafo, ("ul", [voci]) elenco,
("nota", testo) riquadro di attenzione, ("def", [(termine, spiegazione)]).
Le etichette citate sono quelle visibili nelle pagine: se ne cambia una, va
aggiornata anche qui. Il testo alimenta anche l'assistente AI del portale.
"""
from __future__ import annotations

SEZIONI: list[dict] = [
    {
        "id": "scopo",
        "titolo": "A cosa serve il KICK-OFF",
        "blocchi": [
            ("p", "Il modulo KICK-OFF segue una commessa dall'avvio all'esecuzione: la scheda di commessa con "
                  "il documento VRF, il team, le attività pianificate sul Gantt e gli incontri con il loro esito."),
            ("def", [
                ("Commessa (kickoff)", "la scheda «Cliente · P/N · KICK-OFF n» con team, fase e VRF."),
                ("Attività", "lavoro pianificato con data inizio, data fine, responsabile e avanzamento. Compare sul Gantt."),
                ("Incontro", "riunione di commessa: convocazione, conduzione, esito e minuta."),
                ("Azione", "impegno deciso in un incontro: chi fa cosa entro quando."),
                ("Problema", "criticità emersa in un incontro, seguita finché non è risolta."),
                ("Decisione", "scelta presa in un incontro, conservata nel registro decisioni della commessa."),
            ]),
        ],
    },
    {
        "id": "attivita",
        "titolo": "Le attività",
        "blocchi": [
            ("ul", [
                "Gli stati sono Da fare, In corso, Completata e Annullata; le priorità Bassa, Media e Alta.",
                "Data inizio e data fine possono coincidere: un'attività di una sola giornata è ammessa. "
                "La data fine non può precedere la data inizio.",
                "Chi riceve un'attività, alla creazione o quando cambia il responsabile, riceve una notifica nel portale. "
                "Chi si assegna un'attività da solo non viene avvisato.",
                "Portando un'attività a «Completata» l'avanzamento passa al 100%.",
                "Un'attività completata chiude da sola le azioni e i problemi d'incontro collegati a lei.",
                "Su una commessa bloccata per VRF mancante non si creano attività, nemmeno dalle scorciatoie degli incontri.",
            ]),
        ],
    },
    {
        "id": "convocazione",
        "titolo": "Pianificare e convocare un incontro",
        "blocchi": [
            ("p", "Dalla scheda di commessa, sezione Incontri, «Nuovo incontro» apre la convocazione: dettagli, "
                  "partecipanti, ordine del giorno e Outlook."),
            ("ul", [
                "L'ordine del giorno parte già con i problemi e le azioni ancora aperti e con i punti non trattati nell'incontro precedente.",
                "«Pianifica prossimo incontro», dal dettaglio di un incontro svolto, riprende convocati, persone in copia, luogo, "
                "ora e impostazioni Outlook del precedente, con la data una settimana dopo.",
                "Salvare l'incontro non invia email. La convocazione parte con il pulsante «Invia convocazione» del dettaglio, "
                "oppure spuntando «Invia la convocazione ai partecipanti dopo il salvataggio» in fondo al form.",
                "Il dettaglio dice se la convocazione è stata inviata e quando. Se dopo l'invio cambiano data, ora, luogo, "
                "convocati o ordine del giorno compare «Convocazione da reinviare»; il pulsante diventa "
                "«Invia aggiornamento convocazione» e la mail esce come «Aggiornamento convocazione».",
                "Se l'incontro viene spostato a un'altra data, il promemoria del giorno prima riparte sulla data nuova.",
                "L'evento Outlook è un canale separato dalla mail: si attiva con «Calendario Outlook» nel form.",
            ]),
        ],
    },
    {
        "id": "annullamento",
        "titolo": "Annullare o eliminare un incontro",
        "blocchi": [
            ("ul", [
                "«Annulla incontro» (solo per incontri pianificati) chiede il motivo, toglie l'evento dal calendario Outlook "
                "e, se la casella «Avvisa i convocati via email» resta spuntata, manda ai convocati l'avviso di annullamento con il motivo.",
                "Un incontro annullato si riprogramma da «Convocazione», riportando lo stato a «Pianificato»: "
                "la convocazione torna «da inviare», perché i convocati hanno ricevuto l'annullamento.",
                "«Elimina» compare solo per gli incontri mai svolti e senza decisioni. Un incontro svolto non si elimina: "
                "con lui sparirebbero verbale e decisioni.",
            ]),
        ],
    },
    {
        "id": "conduzione",
        "titolo": "Condurre l'incontro",
        "blocchi": [
            ("p", "«Conduci incontro» apre la schermata da usare durante la riunione."),
            ("ul", [
                "Appello: si spunta chi è presente; il dato si salva subito e vale anche per l'esito e la minuta.",
                "Per ogni punto: nota, «Segna trattato», tempo effettivo e attività collegata (esistente o «+ Nuova attività»). "
                "Ogni modifica si salva da sola e solo sul punto toccato.",
                "Cattura rapida: registra al volo un'azione, una decisione o un problema, con responsabile e scadenza. "
                "Il responsabile riceve subito una notifica.",
                "«Termina incontro e registra l'esito» porta alla pagina dell'esito.",
            ]),
        ],
    },
    {
        "id": "esito",
        "titolo": "Registrare l'esito e la minuta",
        "blocchi": [
            ("ul", [
                "La pagina esito raccoglie presenze, note generali, problemi, decisioni e azioni. Salvando, l'incontro passa a «Svolto».",
                "Problemi e azioni hanno responsabile e scadenza; finché restano aperti tornano nell'ordine del giorno degli incontri successivi.",
                "I vecchi campi di testo libero (ordine del giorno testuale, problemi aperti, next steps) restano consultabili "
                "negli incontri storici ma non si compilano più.",
                "«Approva e chiudi minuta» la segna come approvata; «Riapri minuta» chiede un motivo, che resta a registro.",
                "«Invia minuta» la manda ai presenti, con gli assenti in copia e il PDF allegato.",
            ]),
        ],
    },
    {
        "id": "azioni-problemi",
        "titolo": "Azioni, problemi e attività: come si legano",
        "blocchi": [
            ("p", "Un'azione o un problema restano voci dell'incontro; quando servono date e pianificazione vi si collega un'attività."),
            ("ul", [
                "Il responsabile di un'azione o di un problema li chiude da sé, dal dettaglio incontro o da «Le mie azioni», "
                "senza passare da chi gestisce la commessa.",
                "Se l'attività collegata viene completata, l'azione o il problema si chiudono da soli.",
                "Il lunedì il promemoria KICK-OFF elenca le azioni e i problemi scaduti e quelli in scadenza nei 7 giorni.",
            ]),
        ],
    },
    {
        "id": "mie-azioni",
        "titolo": "Le mie azioni",
        "blocchi": [
            ("p", "La pagina «Le mie azioni» raccoglie le azioni e i problemi di cui sei responsabile, su tutte le commesse che puoi vedere. "
                  "Nella dashboard la colonna «Le mie azioni» mostra le prime, scadute in testa."),
            ("ul", [
                "Filtri: Aperte, Chiuse, Tutte; tipo (azioni o problemi); scadenza (Scadute, In scadenza entro 7 giorni, Senza scadenza); "
                "commessa; ricerca nel testo.",
                "«Fatta» o «Risolto» chiudono la voce, «Riapri» la riporta aperta.",
            ]),
        ],
    },
    {
        "id": "registro-azioni",
        "titolo": "Registro azioni della commessa",
        "blocchi": [
            ("p", "Dalla scheda di commessa, «Azioni» mostra in un solo elenco problemi, azioni d'incontro, attività e sotto-attività."),
            ("ul", [
                "«Solo aperte» o «Includi chiuse».",
                "Filtri per tipo, responsabile («Non assegnate» per quelle senza nessuno), scadenza e testo. "
                "I riquadri in alto contano sempre tutto il registro, la tabella mostra il filtrato.",
            ]),
        ],
    },
    {
        "id": "elenco-incontri",
        "titolo": "Elenco e calendario incontri",
        "blocchi": [
            ("ul", [
                "«I miei» comprende gli incontri in cui sei convocato, in copia, presente, che hai creato o della cui commessa fai parte del team.",
                "Filtri: stato, periodo (Prossimi 7 giorni, Da oggi in poi, Passati), esito e minuta "
                "(Esito da registrare, Minuta da approvare, Minuta approvata), commessa e ricerca nel verbale.",
            ]),
        ],
    },
    {
        "id": "promemoria",
        "titolo": "Promemoria automatici",
        "blocchi": [
            ("ul", [
                "I convocati ricevono il promemoria dell'incontro il giorno lavorativo precedente: il venerdì per un incontro del lunedì, "
                "prima di un festivo per il giorno dopo.",
                "Il lunedì arriva il riepilogo di azioni e problemi scaduti e in scadenza nella settimana.",
                "Più avvisi per la stessa persona nello stesso giorno arrivano in una sola email.",
            ]),
            ("nota", "Le notifiche nel portale rispettano le preferenze dell'utente e l'interruttore generale delle notifiche."),
        ],
    },
]
