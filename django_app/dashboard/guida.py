"""Guida d'uso della home di NOVICROM HUB (pulsante «? Guida» nella barra delle stanze).

Testo semplice, niente HTML: il template lo mostra con l'autoescape e
l'assistente AI lo indicizza da qui (``ai_assistant.guide_portale``).

Blocchi di una sezione: ("p", testo) paragrafo, ("ul", [voci]) elenco,
("nota", testo) riquadro di attenzione, ("def", [(termine, spiegazione)]).
Le etichette citate sono quelle visibili nella home: se ne cambia una, va
aggiornata anche qui.
"""
from __future__ import annotations

from dashboard.views_home_portale import SELF_HELP_NUOVA_GIORNI

DOC_TITOLO = "Home del portale"

SEZIONI: list[dict] = [
    {
        "id": "struttura",
        "titolo": "Come è fatta la home",
        "blocchi": [
            ("p", "La home ha due parti. A sinistra c'è una colonna fissa con il tuo riepilogo; "
                  "a destra ci sono quattro stanze, che si aprono dalle schede in alto: "
                  "Oggi, Sapere, Persone & sicurezza e Moduli."),
            ("ul", [
                "Il numero accanto al nome della stanza conta cosa c'è dentro: le attività per «Oggi», "
                "le risorse self-help per «Sapere», i moduli disponibili per «Moduli».",
                "La home riapre l'ultima stanza che hai usato su questo browser, oppure quella scelta in «⚙ Personalizza».",
                "Ogni stanza ha un indirizzo diretto da salvare o condividere: aggiungi #oggi, #sapere, "
                "#persone o #moduli all'indirizzo della home.",
                "Con la tastiera, le frecce sinistra e destra passano da una stanza all'altra.",
            ]),
        ],
    },
    {
        "id": "polso",
        "titolo": "La colonna di sinistra",
        "blocchi": [
            ("p", "La colonna resta visibile in tutte le stanze."),
            ("def", [
                ("Saluto e ruolo", "il tuo nome, il ruolo attivo e il reparto."),
                ("Ora e data", "l'ora si aggiorna da sola; sotto, il riepilogo delle attività assegnate "
                 "e delle richieste in approvazione."),
                ("Priorità", "Anomalie aperte, Ticket attivi, Task in corso e Approvazioni. "
                 "Un clic apre il modulo."),
                ("I miei preferiti", "i moduli che hai segnato con ☆ nella stanza «Moduli», nell'ordine in cui li hai scelti. "
                 "Al massimo 12."),
                ("Azioni rapide", "Le mie attività, Scadenzario, Nuovo ticket, Segnala anomalia e Richiedi permesso."),
                ("Emergenza", "il numero unico 112 e chi coordina le emergenze, preso dall'organigramma della sicurezza."),
            ]),
        ],
    },
    {
        "id": "personalizza",
        "titolo": "Personalizzare la home",
        "blocchi": [
            ("p", "Pulsante «⚙ Personalizza», a destra delle stanze. Le scelte valgono per te, su qualsiasi computer o telefono."),
            ("def", [
                ("Stanza di apertura", "«L'ultima che ho aperto» (comportamento normale) oppure sempre Oggi, Sapere, "
                 "Persone & sicurezza o Moduli. Un indirizzo con #stanza vince comunque."),
                ("Riquadri da mostrare", "togli la spunta ad Azioni rapide, Il tuo brief di oggi o News aziendali per nasconderli. "
                 "Emergenza e Priorità restano sempre visibili."),
                ("Preferiti", "nella stanza «Moduli» tocca ☆ su una tessera: diventa ★ e il modulo compare in «I miei preferiti». "
                 "Tocca ★ per toglierlo. Un modulo che non puoi più aprire sparisce dai preferiti da solo."),
                ("Rifai il tour", "rivede il giro di benvenuto della barra in alto e della home."),
            ]),
            ("nota", "Il giro di benvenuto parte da solo la prima volta che apri la home; chiudendolo non ricompare."),
        ],
    },
    {
        "id": "oggi",
        "titolo": "Stanza «Oggi»",
        "blocchi": [
            ("ul", [
                "«Le mie attività» raccoglie le cose che aspettano una tua azione: approvazioni assenze, ticket aperti, "
                "anomalie aperte, non conformità, procedure da leggere, richieste DPI in corso, corsi e-learning da "
                "completare e refresh abilitazioni macchina. Per ogni gruppo si vedono le prime 5; «Apri →» porta al modulo, "
                "«Vedi tutte →» alla pagina completa.",
                "«Il tuo brief di oggi» è un riepilogo preparato dall'assistente AI. Il pulsante ↻ lo rigenera.",
                "«News aziendali» mostra le ultime comunicazioni; «Vedi tutte →» apre l'archivio.",
            ]),
        ],
    },
    {
        "id": "sapere",
        "titolo": "Stanza «Sapere»",
        "blocchi": [
            ("p", "Qui ci sono le risorse da consultare in autonomia."),
            ("ul", [
                "«Risorse self-help» è uno scaffale di guide, manuali e video. Ogni risorsa ha una copertina con il colore "
                "della sua categoria e una sigla (per esempio VPN o 2FA). I pulsanti in alto filtrano per categoria.",
                f"La scritta «NUOVA» segna le risorse pubblicate negli ultimi {SELF_HELP_NUOVA_GIORNI} giorni.",
                "«Documenti & Collegamenti» elenca documenti aziendali, collegamenti esterni e scorciatoie del portale, "
                "divisi per categoria. «Apri tutti →» apre la bacheca completa.",
            ]),
            ("p", "Vedi solo le risorse aperte al tuo ruolo: una risorsa senza ruoli assegnati è visibile a tutti."),
        ],
    },
    {
        "id": "persone",
        "titolo": "Stanza «Persone & sicurezza»",
        "blocchi": [
            ("p", "Mostra chi si occupa della sicurezza sul lavoro. I dati vengono dall'organigramma della sicurezza "
                  "in Anagrafica (ambito «Sicurezza ISO 45001» del catalogo ruoli): non si inseriscono a mano nella home."),
            ("def", [
                ("Le tue persone di riferimento", "il preposto del tuo reparto, evidenziato in arancione, e una persona "
                 "per ciascuna figura di servizio e di rappresentanza (RSPP, ASPP, medico competente, RLS)."),
                ("Organigramma della sicurezza", "una scheda per ogni persona e incarico, con reparto ed email aziendale."),
                ("Responsabilità", "una tessera per ruolo. Un clic la apre e mostra i compiti, presi dalla descrizione "
                 "del ruolo, e le persone che lo ricoprono. «Posizione scoperta» indica un ruolo senza persone."),
            ]),
            ("nota", "Il tuo preposto è trovato confrontando il tuo reparto in anagrafica con il reparto dei preposti "
                     "(o con il nome del ruolo, per esempio «Preposto CNC»). Se non compare, il reparto in anagrafica "
                     "è vuoto o diverso: chiedi all'ufficio personale di correggerlo."),
            ("p", "Si vedono solo nome, ruolo, reparto ed email aziendale. Gli ex dipendenti non compaiono."),
        ],
    },
    {
        "id": "moduli",
        "titolo": "Stanza «Moduli»",
        "blocchi": [
            ("p", "Elenca i moduli del portale a cui hai accesso, divisi per area (Operations, Persone & sicurezza, "
                  "Stabilimento, Compliance, Automazione & sistema, SOC IT - CN)."),
            ("ul", [
                "Il riquadro a destra della tessera mostra il numero principale del modulo, per esempio le anomalie aperte. "
                "Conta solo i dati che puoi vedere: i tuoi (o del tuo team) se il tuo ruolo non vede tutto; "
                "una tessera senza numero vuol dire che il totale è riservato a chi vede tutta l'azienda.",
                "Un clic sulla tessera apre un pannello con tutti i numeri del modulo e «Vai al modulo →». "
                "«Anomalie» invece apre subito la gestione anomalie, senza pannello.",
                "Le tessere non si aggiungono a mano: con «Ruoli e permessi» attivo compare ogni modulo che uno dei "
                "tuoi ruoli ti lascia «Vedere» (lo stesso elenco di «Cosa vede questa persona»). "
                "«Nessun modulo disponibile» vuol dire che nessun tuo ruolo concede «Vedere» su un modulo della home.",
            ]),
        ],
    },
    {
        "id": "gestione",
        "titolo": "Per chi gestisce i contenuti",
        "blocchi": [
            ("def", [
                ("Risorse self-help e documenti", "Admin portale → Documenti & Collegamenti. Ogni categoria ha una "
                 "«Sezione della home»: «Documenti & collegamenti» (elenco) o «Risorse self-help» (scaffale), e un "
                 "«Colore copertine». Ogni voce può avere una «Sigla copertina» fino a 8 caratteri; se è vuota, la sigla "
                 "nasce dalle iniziali del titolo."),
                ("Figure della sicurezza", "Anagrafica → Ruoli: i ruoli dell'ambito «Sicurezza ISO 45001» e le persone "
                 "assegnate. La descrizione del ruolo diventa il testo della tessera «Responsabilità»."),
                ("News", "modulo Notizie aziendali."),
            ]),
        ],
    },
]
