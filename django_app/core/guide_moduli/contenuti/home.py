GUIDA = {
    "slug": "home",
    "titolo": "Primi passi nel portale",
    "area": "Per tutti",
    "sintesi": "Come entrare, muoversi tra i moduli, trovare le cose e chiedere aiuto.",
    "parole": "accesso login password home menu notifiche cerca profilo",
    "url": "dashboard_home",
    "prefissi": ("/dashboard", "/hub/home/", "/profilo", "/notifiche/", "/bacheca/", "/scadenze"),
    "dettaglio": [("Guida della home a stanze", "home_portale:guida")],
    "uso": [
        {
            "id": "entrare",
            "titolo": "Entrare nel portale",
            "blocchi": [
                ("passi", [
                    "Apri il browser (Chrome o Edge) e vai all'indirizzo del portale.",
                    "Scrivi il tuo nome utente aziendale (lo stesso del PC) e la password del PC.",
                    "Se ti viene chiesto un codice, inserisci quello che ti arriva per mail o sull'app (verifica in due passaggi).",
                ]),
                ("nota", "Dopo 5 tentativi sbagliati l'accesso si blocca per un'ora: aspetta e riprova, oppure chiedi all'amministratore di sbloccarti."),
            ],
        },
        {
            "id": "muoversi",
            "titolo": "Muoversi tra i moduli",
            "blocchi": [
                ("ul", [
                    "La barra in alto contiene i moduli divisi per area. Vedi solo quelli che puoi usare.",
                    "Sotto la barra c'è il menu del modulo in cui ti trovi.",
                    "Il logo in alto a sinistra riporta sempre alla home.",
                    "«Cerca o vai a…» (oppure Ctrl+K) trova una pagina, una persona o un documento scrivendo il nome.",
                ]),
            ],
        },
        {
            "id": "icone",
            "titolo": "Le icone in alto a destra",
            "blocchi": [
                ("def", [
                    ("?", "apre la guida del modulo in cui ti trovi (questa pagina)."),
                    ("Stella", "l'Assistente AI: fai una domanda in italiano, per esempio «come chiedo un permesso?»."),
                    ("Campanella", "le notifiche. Il numero rosso dice quante non hai ancora letto."),
                    ("Il tuo nome", "profilo, preferenze, tema chiaro/scuro, «Segnala un problema» ed «Esci»."),
                ]),
            ],
        },
        {
            "id": "home",
            "titolo": "La home",
            "blocchi": [
                ("p", "La home ti mostra cosa devi fare oggi (richieste da approvare, scadenze, letture), i documenti utili e i collegamenti ai moduli. "
                      "La guida completa della home è nel collegamento qui sopra."),
            ],
        },
        {
            "id": "scadenzario",
            "titolo": "Lo Scadenzario globale",
            "blocchi": [
                ("p", "Dalla home, pulsante «Scadenzario» (indirizzo /scadenze): tutte le scadenze del portale in una tabella sola, "
                      "le scadute in cima. Contiene le scadute e quelle dei prossimi 90 giorni."),
                ("def", [
                    ("Personale (HR)", "qualifiche, visite mediche, corsi obbligatori, contratti a termine e periodi di prova. Le stesse voci dello Scadenzario di Anagrafica."),
                    ("Asset", "scadenze amministrative (revisioni, certificati), licenze software e contratti di assistenza."),
                    ("Verifiche impianti", "la prossima verifica di ogni tipo attivo (estintori, luci di emergenza, quadri…)."),
                    ("DPI", "i DPI consegnati e non ancora sostituiti, alla data di fine vita utile."),
                    ("RENTRI", "FIR mancanti e depositi temporanei vicini al limite."),
                    ("Azioni CAPA", "le azioni aperte con una scadenza; chi non gestisce le CAPA vede solo le proprie."),
                ]),
                ("ul", [
                    "Vedi solo le fonti che puoi aprire: se non hai accesso alle visite mediche, le visite non compaiono.",
                    "Filtri: Sorgente, Stato (Scadute, Entro 30, 60 o 90 giorni) e Reparto; «⬇ CSV» scarica le righe filtrate.",
                    "Il nome nella colonna Soggetto apre la pagina dove la scadenza si gestisce. Qui si guarda soltanto: niente si modifica.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "home-admin",
            "titolo": "Personalizzare la home e il menu",
            "blocchi": [
                ("ul", [
                    "Moduli visibili: Amministrazione → Hub → «Moduli» (accendi o spegni un modulo per tutti).",
                    "Voci del menu: Amministrazione → «Navigation Builder».",
                    "Logo, nomi e colori: Amministrazione → «Branding portale».",
                    "Cosa vede ogni persona dipende dai permessi: vedi la guida «Amministrazione del portale».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona non riesce a entrare",
            "fare": [
                "Chiedi il messaggio esatto che vede.",
                "«Credenziali non valide»: la password è quella del PC; se l'ha appena cambiata, attenda qualche minuto.",
                "Accesso bloccato dopo 5 tentativi sbagliati: il blocco dura un'ora. Per sbloccare subito, dal terminale del Setup Wizard: axes_reset_username <nome utente>.",
                "L'utente non esiste: va creato o importato da Active Directory (Amministrazione → Import Utenti LDAP).",
                "Se nessuno riesce a entrare, apri il Manuale di emergenza → «Nessuno riesce a entrare».",
            ],
        },
        {
            "sintomo": "Nello Scadenzario globale manca una scadenza (o una fonte intera)",
            "fare": [
                "Controlla che la persona possa aprire la pagina del modulo da cui arriva la scadenza: ogni fonte compare solo con quel permesso.",
                "Verifiche impianti: il tipo di verifica deve essere attivo e avere una «Prossima scadenza».",
                "DPI: compare solo la consegna in essere (richiesta «Consegnata», non sostituita da una consegna successiva).",
                "Personale: valgono le regole dello Scadenzario di Anagrafica (solo la qualifica e la visita in vigore, ex dipendenti esclusi).",
                "Se una fonte intera manca anche per un amministratore, cerca nel log «Scadenzario globale: provider … fallito».",
            ],
        },
        {
            "sintomo": "Una persona non vede un modulo nel menu",
            "fare": [
                "Controlla che il modulo sia acceso (Amministrazione → Hub → «Moduli»).",
                "Controlla i suoi permessi: Amministrazione → «Accessi negati» mostra ogni pagina bloccata con il motivo e i pulsanti «Consenti» / «Non consentire».",
            ],
        },
    ],
}
