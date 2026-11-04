GUIDA = {
    "slug": "fornitori",
    "titolo": "Fornitori",
    "area": "Produzione e operations",
    "sintesi": "Anagrafica fornitori con documenti, ordini, valutazioni di qualità e asset assegnati.",
    "parole": "fornitore fornitori ordine ordini valutazione albo partita iva accessi esterni visitatori ospiti consulenti guestportal reception badge",
    "url": "fornitori:index",
    "prefissi": ("/fornitori/",),
    "uso": [
        {
            "id": "cercare",
            "titolo": "Cercare un fornitore",
            "blocchi": [
                ("passi", [
                    "Apri Fornitori e clicca «📋 Elenco fornitori».",
                    "Cerca per ragione sociale, partita IVA o città e clicca «Filtra».",
                    "Clicca «Apri →» per la scheda.",
                ]),
            ],
        },
        {
            "id": "scheda",
            "titolo": "La scheda del fornitore",
            "blocchi": [
                ("def", [
                    ("Documenti", "certificati e contratti: «Carica» per aggiungerne (PDF, Office o immagini, massimo 15 MB)."),
                    ("Ordini", "con stato e importo: la somma è la spesa totale. «Salva ordine»."),
                    ("Valutazioni", "qualità, puntualità e comunicazione da 1 a 5 stelle. «Salva valutazione»."),
                    ("Asset", "macchine o contratti assegnati al fornitore. «Assegna» / «Rimuovi»."),
                ]),
            ],
        },
        {
            "id": "accessi-esterni",
            "titolo": "Accessi esterni (GuestPortal)",
            "blocchi": [
                ("p", "Visitatori, fornitori e consulenti che si registrano al chiosco della reception (GuestPortal). "
                      "Apri Fornitori → «Accessi esterni»."),
                ("def", [
                    ("Presenti ora", "chi ha fatto il check-in e non ancora il check-out, dal più vecchio: con badge, referente e da quanto tempo è in azienda."),
                    ("Storico", "le visite con ingresso nel periodo «Dal» / «Al» (di base gli ultimi 7 giorni), filtrabili per «Tipo» e con «Cerca» su nome, azienda, referente e motivo. Si vedono al massimo 500 visite: se sono di più la pagina lo dice e va ristretto il periodo."),
                    ("Azienda in blu", "la ragione sociale coincide con un fornitore attivo dell'HUB: il link apre la sua scheda."),
                    ("Ospite anonimizzato", "il GuestPortal ha già anonimizzato l'ospite per il GDPR: nome e azienda non si vedono più."),
                ]),
                ("p", "«Apri GuestPortal ↗» (e la voce di menu «Accessi azienda») apre il pannello del GuestPortal già "
                      "collegato con il tuo utente, senza ridigitare la password, se sei abilitato nel pannello."),
                ("nota", "I dati si leggono dal GuestPortal ogni volta che apri la pagina e non vengono copiati nell'HUB: "
                         "quando il GuestPortal cancella le visite vecchie (pulizia GDPR) spariscono anche qui."),
                ("p", "La colonna «Incaricato per» mostra i ticket e gli ordini di lavoro a cui l'ingresso è stato collegato."),
            ],
        },
        {
            "id": "presenze-interventi",
            "titolo": "Collegare l'ingresso della ditta al ticket o all'OdL",
            "blocchi": [
                ("p", "Nei ticket di manutenzione (scheda «Interventi» della gestione) e negli ordini di lavoro eseguiti da una "
                      "ditta esterna c'è il riquadro «Presenze in azienda della ditta»."),
                ("passi", [
                    "Imposta la ditta: «Delegato a fornitore» nel ticket, il fornitore nell'OdL.",
                    "Il riquadro propone gli ingressi della ditta dal giorno prima dell'apertura fino alla chiusura (al massimo 90 giorni): sotto «Ingressi della ditta da collegare» clicca «Collega» su quelli giusti.",
                    "Se la ditta non compare (azienda scritta in modo diverso al chiosco), usa «Collega a mano un ingresso del giorno»: scegli il giorno, «Mostra ingressi», poi «Collega».",
                    "«Togli» annulla un collegamento sbagliato finché l'intervento è aperto.",
                ]),
                ("def", [
                    ("Totale in azienda", "somma del tempo tra entrata e uscita degli ingressi collegati."),
                    ("Avviso giallo sulle ore", "nei ticket: le ore registrate negli interventi superano di oltre 15 minuti la presenza in azienda. Controlla il rapportino prima di approvare la fattura."),
                    ("Ancora dentro", "il tecnico non ha ancora fatto il check-out: l'uscita si completa da sola alla prossima apertura del riquadro."),
                ]),
                ("nota", "Al collegamento l'HUB salva giorno, entrata, uscita e nome del tecnico: restano nel ticket/OdL come prova "
                         "dell'intervento anche dopo la pulizia GDPR del GuestPortal. Il riquadro lo usano i gestori del ticket e chi "
                         "esegue le manutenzioni; un intervento chiuso non si modifica più."),
            ],
        },
    ],
    "admin": [
        {
            "id": "gestire",
            "titolo": "Creare e disattivare",
            "blocchi": [
                ("ul", [
                    "«+ Nuovo fornitore», compila i dati e clicca «Salva fornitore».",
                    "Un fornitore che non si usa più si disattiva («Disattiva»), non si elimina: i suoi ordini e le manutenzioni restano collegati.",
                    "I permessi del modulo Fornitori sono separati da quelli di Anagrafica HR (Amministrazione → Accessi).",
                ]),
            ],
        },
        {
            "id": "guestportal",
            "titolo": "Collegare il GuestPortal",
            "blocchi": [
                ("ul", [
                    "Chi vede «Accessi esterni»: il permesso «Portale esterno ospiti» (legacy.portale_esterno.portale_esterno) in Amministrazione → Accessi. Mostra dati personali dei visitatori: darlo solo a reception, sicurezza e responsabili.",
                    "Il link «Apri GuestPortal» / «Accessi azienda» è aperto a chi ha fatto l'accesso all'HUB, come il vecchio link diretto: chi entra nel pannello lo decide il GuestPortal (Utenti admin del pannello).",
                    "Database: sul MySQL del GuestPortal crea un utente con solo SELECT su Visits, Guests e Suppliers e metti host, nome database, utente e password in GUESTPORTAL_DB_* del .env dell'HUB (vedi docs/integrazioni/guestportal/README.md). Dal server HUB deve essere aperta la porta 3306.",
                    "Accesso automatico: GUESTPORTAL_SSO_SECRET nel .env dell'HUB deve essere uguale a GP_SSO_SECRET in config/sso.php del GuestPortal. Senza segreto il link apre il login normale del pannello.",
                    "Dopo aver cambiato il .env riavvia il portale (sito IIS).",
                    "Ditte: in Fornitori → «Ditte GuestPortal» scegli per ogni fornitore del GuestPortal il fornitore dell'HUB e clicca «Salva» (con nome uguale è già proposto). Senza abbinamento l'ingresso si riconosce solo se l'azienda scritta al chiosco è uguale alla ragione sociale. La pagina usa il permesso di «Modifica fornitore».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il fornitore non compare nelle manutenzioni degli asset",
            "fare": ["Controlla che il fornitore sia attivo.", "Nella scheda fornitore assegna l'asset o il contratto."],
        },
        {
            "sintomo": "Accessi esterni: avviso giallo «Collegamento al database del GuestPortal non configurato»",
            "perche": "Mancano GUESTPORTAL_DB_HOST, GUESTPORTAL_DB_USER o GUESTPORTAL_DB_PASSWORD nel .env.",
            "fare": ["Compila le chiavi GUESTPORTAL_DB_* nel .env persistente e riavvia il portale."],
        },
        {
            "sintomo": "Accessi esterni: «Il database del GuestPortal non risponde»",
            "perche": "MySQL fermo, porta 3306 chiusa dal server HUB, password cambiata o utente senza SELECT.",
            "fare": [
                "Dal server HUB prova la porta: Test-NetConnection <host MySQL> -Port 3306.",
                "Controlla che l'utente MySQL esista e abbia SELECT su Visits, Guests, Suppliers.",
            ],
        },
        {
            "sintomo": "Il riquadro «Presenze in azienda» non propone gli ingressi della ditta",
            "perche": "Ditta non impostata nel ticket/OdL, fornitore del GuestPortal non abbinato e azienda scritta diversamente al chiosco, oppure ingresso fuori dal periodo dell'intervento.",
            "fare": [
                "Imposta «Delegato a fornitore» (ticket) o il fornitore (OdL).",
                "Abbina la ditta in Fornitori → «Ditte GuestPortal».",
                "In alternativa usa «Collega a mano un ingresso del giorno».",
            ],
        },
        {
            "sintomo": "«Apri GuestPortal» porta alla pagina di login invece che dentro il pannello",
            "perche": "Segreto SSO assente o diverso tra HUB e GuestPortal, utente non presente o disattivato fra gli utenti admin del pannello, oppure orologi dei due server sfasati di oltre 30 secondi.",
            "fare": [
                "Sul server GuestPortal leggi le righe «[SSO] accesso rifiutato: …» in C:\\Windows\\Temp\\guestportal.log: il motivo è scritto lì.",
                "«firma non valida» = segreti diversi; «utente non abilitato in AdminUsers» = aggiungi l'utente nel pannello; «token scaduto o orologi non allineati» = sincronizza l'ora dei server.",
            ],
        },
    ],
}
