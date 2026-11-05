"""Guide rapide per ruolo del modulo KICK-OFF: chi gestisce la commessa e chi partecipa.

Brevi e dirette (un compito = pochi passi numerati, con l'immagine della pagina), da
consegnare a chi usa il modulo. La guida completa resta ``tasks/guida.py``. Stessa forma
delle sezioni di ``guida.py``. Si aprono con ``/tasks/guida/?per=<chiave>``, PDF con
``?per=<chiave>&pdf=1``.
"""
from __future__ import annotations

_IMG = "tasks/guida/"

SEZIONI_GESTIONE: list[dict] = [
    {
        "id": "g-crea",
        "titolo": "Creare la commessa",
        "blocchi": [
            ("passi", [
                "KICK-OFF › Kickoff › «+ Nuovo kickoff».",
                "Scrivi «Cliente» e P/N. Lascia vuoto il nome: si compone da solo.",
                "Nel Team cerca e spunta Project manager, Capocommessa e Programmatore.",
                "Premi «Crea kickoff e convoca il primo incontro».",
            ]),
            ("img", (_IMG + "nuovo_kickoff.jpg", "Il form «Nuovo kickoff»")),
            ("ul", ["Hai sbagliato qualcosa? «Modifica kickoff» nella Panoramica."]),
        ],
    },
    {
        "id": "g-convoca",
        "titolo": "Convocare l'incontro",
        "blocchi": [
            ("passi", [
                "Nella convocazione scrivi data, ora e luogo.",
                "Aggiungi i partecipanti e i punti all'ordine del giorno.",
                "Salva.",
                "Nel dettaglio dell'incontro premi «Invia convocazione»: salvare da solo non manda email.",
            ]),
            ("img", (_IMG + "convocazione.jpg", "La convocazione")),
        ],
    },
    {
        "id": "g-vrf",
        "titolo": "Compilare la scheda VRF",
        "blocchi": [
            ("passi", [
                "Commessa › scheda «VRF».",
                "Per ogni rischio scegli la Probabilità: 1, 2, 3 o N/A.",
                "Guarda il Totale Rischio: da 50 in su serve il coinvolgimento del CEO.",
                "Scrivi le azioni correttive, nome e data di IN1 e EM.",
                "Premi «Conferma e genera xlsx». Non hai finito? «Salva bozza».",
            ]),
            ("img", (_IMG + "vrf_scheda.jpg", "La scheda VRF")),
        ],
    },
    {
        "id": "g-piano",
        "titolo": "Scrivere il piano",
        "blocchi": [
            ("passi", [
                "Commessa › scheda «Piano».",
                "Nella riga sopra il Gantt scrivi titolo, responsabile, Inizio e Fine.",
                "Premi «Aggiungi» e passa alla riga dopo.",
                "Sposta le date trascinando le barre.",
            ]),
            ("img", (_IMG + "piano.jpg", "Il Piano con la riga rapida")),
        ],
    },
    {
        "id": "g-conduci",
        "titolo": "Condurre l'incontro",
        "blocchi": [
            ("passi", [
                "Dettaglio incontro › «Conduci incontro».",
                "Spunta i presenti.",
                "Su ogni punto scrivi la nota e premi «Segna trattato».",
                "Quello che emerge va in «Cattura rapida»: scegli Attività, Azione, Decisione o Problema, scrivi, Invio.",
                "Alla fine «Termina incontro e registra l'esito».",
            ]),
            ("img", (_IMG + "conduci.jpg", "Conduci incontro")),
        ],
    },
    {
        "id": "g-esito",
        "titolo": "Chiudere l'incontro",
        "blocchi": [
            ("passi", [
                "Nella pagina esito controlla presenze, problemi, decisioni e azioni.",
                "Premi «Registra esito».",
                "Nel dettaglio premi «Invia minuta».",
                "Quando è tutto giusto, «Approva e chiudi minuta».",
                "Per il successivo: «Pianifica prossimo incontro».",
            ]),
            ("img", (_IMG + "esito.jpg", "La pagina esito")),
        ],
    },
    {
        "id": "g-controllo",
        "titolo": "Tenere sotto controllo",
        "blocchi": [
            ("ul", [
                "«Da gestire»: VRF, commesse non pronte, attività critiche, incontri da chiudere.",
                "Panoramica › «Prontezza all'avvio»: il link «Correggi» porta dove si sistema.",
                "Commessa pronta: nel portfolio, vista Board, portala «In esecuzione».",
            ]),
            ("img", (_IMG + "da_gestire.jpg", "La pagina «Da gestire»")),
        ],
    },
]

SEZIONI_TEAM: list[dict] = [
    {
        "id": "t-mio",
        "titolo": "Vedere cosa devo fare",
        "blocchi": [
            ("passi", [
                "Menu KICK-OFF › «Dashboard».",
                "«Le mie azioni»: azioni e problemi a tuo nome, scaduti in testa.",
                "«Le tue attività»: le attività assegnate a te.",
                "«Prossimi incontri»: dove sei atteso.",
            ]),
            ("img", (_IMG + "dashboard.jpg", "La dashboard")),
        ],
    },
    {
        "id": "t-attivita",
        "titolo": "Aggiornare un'attività",
        "blocchi": [
            ("passi", [
                "Clicca l'attività.",
                "In «Aggiorna stato» scegli In corso o Completata.",
                "Se cambiano le date, correggile con «Aggiorna».",
                "Lascia una nota in «Commenti» o carica un file in «Allegati».",
            ]),
            ("img", (_IMG + "attivita_scheda.jpg", "La scheda di un'attività")),
        ],
    },
    {
        "id": "t-azioni",
        "titolo": "Chiudere un'azione o un problema",
        "blocchi": [
            ("passi", [
                "Apri «Le mie azioni» dalla dashboard.",
                "Premi «Fatta» sull'azione, «Risolto» sul problema.",
                "Sbagliato? Filtra su «Chiuse» e premi «Riapri».",
            ]),
            ("img", (_IMG + "mie_azioni.jpg", "Le mie azioni")),
        ],
    },
    {
        "id": "t-programmi",
        "titolo": "Programmi CAM, CMM e FAI assegnati a te",
        "blocchi": [
            ("passi", [
                "Apri «Le mie azioni»: la voce ha l'etichetta CAM, CMM o FAI.",
                "Cliccala per aprire «Programmi e FAI» della commessa.",
                "Con «Modifica» scrivi il codice e il percorso di rete, poi premi Invio.",
                "Premi «Fatto» quando hai finito.",
            ]),
            ("p", "Cliccando un percorso il portale lo copia: premi Win+E, poi Ctrl+L, Ctrl+V e Invio."),
        ],
    },
    {
        "id": "t-incontro",
        "titolo": "Partecipare a un incontro",
        "blocchi": [
            ("passi", [
                "Ti arriva la mail di convocazione con l'invito da aggiungere al calendario.",
                "Il giorno lavorativo prima ti arriva il promemoria.",
                "Vuoi discutere qualcosa? Nel dettaglio dell'incontro proponi un punto: chi gestisce la commessa lo accetta o lo rifiuta.",
                "Dopo la riunione ricevi la minuta: le azioni a tuo nome compaiono in «Le mie azioni».",
            ]),
            ("img", (_IMG + "incontro.jpg", "Il dettaglio di un incontro")),
        ],
    },
]

GUIDE_RUOLI: dict[str, dict] = {
    "gestione": {
        "etichetta": "Guida rapida · Chi gestisce la commessa",
        "titolo": "KICK-OFF · Chi gestisce la commessa",
        "sottotitolo": "Guida rapida per Project manager e capocommessa",
        "file": "Guida_KickOff_Gestione.pdf",
        "sezioni": SEZIONI_GESTIONE,
    },
    "team": {
        "etichetta": "Guida rapida · Chi partecipa",
        "titolo": "KICK-OFF · Chi partecipa",
        "sottotitolo": "Guida rapida per chi ha attività, azioni e incontri",
        "file": "Guida_KickOff_Team.pdf",
        "sezioni": SEZIONI_TEAM,
    },
}
