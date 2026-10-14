GUIDA = {
    "slug": "suggestion_corner",
    "titolo": "Suggestion Corner",
    "area": "Qualità e sistema di gestione",
    "sintesi": "Segnalazioni e idee di miglioramento, gestite con il ciclo PDCA (pianifica, fai, verifica, agisci).",
    "parole": "suggerimento suggerimenti idea miglioramento segnalazione sms pdca",
    "url": "suggestion_corner:home",
    "prefissi": ("/suggestion-corner/",),
    "uso": [
        {
            "id": "segnalare",
            "titolo": "Inviare una segnalazione o un'idea",
            "blocchi": [
                ("passi", [
                    "Apri Suggestion Corner e clicca «+ Nuova segnalazione».",
                    "Scegli da quale reparto o area nasce e a quale è rivolta.",
                    "Descrivi il problema o l'idea con parole semplici. Se vuoi, allega una foto.",
                    "Invia. Il team miglioramento riceve una mail.",
                ]),
                ("p", "Si può segnalare anche senza account, dal modulo pubblico (per esempio da un QR in reparto)."),
            ],
        },
        {
            "id": "seguire",
            "titolo": "Seguire la segnalazione",
            "blocchi": [
                ("p", "Nell'elenco vedi le tue segnalazioni e quelle in cui sei incaricato. Ogni segnalazione mostra lo stato del ciclo:"),
                ("def", [
                    ("PLAN", "si decide cosa fare («Definisci PLAN»)."),
                    ("DO", "si fa («Avvia DO», poi «Completa DO»)."),
                    ("CHECK", "si controlla se ha funzionato («Check positivo», «Check negativo (riapre DO)» o «Rinvia check»)."),
                    ("ACT", "si rende stabile la soluzione («Inserisci ACT»), poi «Chiudi»."),
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "team",
            "titolo": "Il team miglioramento",
            "blocchi": [
                ("p", "«⚙ Gestione»: con «Aggiungi» e «Rimuovi» si decide chi fa parte del team (gruppo SMS_TEAM). "
                      "Il team vede tutte le segnalazioni; gli altri solo le proprie e quelle dove sono incaricati. «Salva configurazione»."),
            ],
        },
        {
            "id": "classificare",
            "titolo": "Classificare e gestire",
            "blocchi": [
                ("ul", [
                    "«Classifica» decide se è una segnalazione «SMS Sì» (da comunicare al cliente) o «SMS No».",
                    "Per gli «SMS Sì»: «✉ Apri nel client di posta» prepara la mail al cliente; poi «Segna come comunicato».",
                    "«Modifica» (solo team) corregge reparti, persone e testi: ogni correzione resta nello storico.",
                    "L'assistente AI può proporre la classificazione, una bozza di PLAN e le segnalazioni simili: propone, non decide.",
                ]),
                ("p", "Solleciti ed escalation di DO e CHECK partono da soli dal servizio automazioni."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il modulo pubblico risponde «Troppe richieste»",
            "perche": "c'è un limite di invii per indirizzo e un limite generale di 50 invii all'ora contro lo spam.",
            "fare": ["Attendi un'ora e riprova, oppure invia la segnalazione dal portale con il tuo account."],
        },
        {
            "sintomo": "Un membro del team non vede tutte le segnalazioni",
            "fare": [
                "«⚙ Gestione»: controlla che sia nell'elenco del team.",
                "Falle uscire e rientrare nel portale.",
            ],
        },
    ],
}
