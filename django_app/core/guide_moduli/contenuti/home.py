GUIDA = {
    "slug": "home",
    "titolo": "Primi passi nel portale",
    "area": "Per tutti",
    "sintesi": "Come entrare, muoversi tra i moduli, trovare le cose e chiedere aiuto.",
    "parole": "accesso login password home menu notifiche push telefono cerca profilo scadenzario calendario outlook ics preferiti personalizza tour tabelle viste colonne filtri",
    "url": "dashboard_home",
    "prefissi": ("/dashboard", "/hub/home/", "/profilo", "/notifiche/", "/bacheca/", "/scadenze", "/report/"),
    "dettaglio": [("Guida della home a stanze", "home_portale:guida"), ("Guida I miei report", "miei_report", "?guida=1")],
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
            "id": "postazione-condivisa",
            "titolo": "Entrare da un PC condiviso (es. «zeiss») con il PIN",
            "blocchi": [
                ("p", "Su alcuni PC si lavora a turno con un solo account del PC. Il portale lì mostra «Chi sei?»: "
                      "ognuno entra con il proprio nome e un PIN personale, e quello che fa resta registrato a sé."),
                ("passi", [
                    "Tocca il tuo nome nell'elenco «Chi sei?».",
                    "La prima volta premi «Imposta il PIN»: scrivi nome utente e password del tuo account (gli stessi di Windows / "
                    "Microsoft 365) e un PIN da 4 a 8 cifre, due volte. «Salva il PIN ed entra».",
                    "Le volte dopo digita il PIN sul tastierino e premi «Entra».",
                    "Quando hai finito premi «Cambio operatore» nella fascia blu in alto (anche «Esci» riporta lì). Dopo i minuti di inattività "
                    "della postazione (di solito 10) si torna comunque a «Chi sei?».",
                ]),
                ("nota", "Niente cifre tutte uguali né sequenze come 1234. Dopo 5 PIN sbagliati il PIN si blocca e ti arriva una mail: "
                         "impostane uno nuovo con «Imposta un nuovo PIN» (serve la password) o chiedi all'amministratore. "
                         "Se il tuo nome non c'è, chiedi all'amministratore di abilitarti su quel PC."),
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
                ("p", "Dal telefono:"),
                ("ul", [
                    "Il pulsante con le tre linee in alto a sinistra apre i moduli. In cima c'è «Cerca nel menu»: "
                    "scrivi parte del nome e restano solo le voci che corrispondono. L'area del modulo in cui sei è già aperta.",
                    "Il menu del modulo è un pulsante sotto la barra: mostra dove sei (es. «Anagrafica · Dashboard»). "
                    "Toccandolo si apre dal basso l'elenco di tutte le voci del modulo, divise per gruppo; "
                    "con più di 8 voci c'è anche «Filtra le voci».",
                    "Il pannello si chiude con la X, toccando fuori o trascinandolo verso il basso.",
                ]),
            ],
        },
        {
            "id": "cerca-domande",
            "titolo": "Cercare scrivendo una domanda",
            "blocchi": [
                ("p", "In «Cerca o vai a…» puoi scrivere anche una frase intera, per esempio «come chiedo un DPI?» o «chi ha la visita in scadenza?»."),
                ("def", [
                    ("Dalle guide e procedure", "i capitoli delle guide, delle procedure e delle schede di sicurezza che parlano di quello che hai scritto. "
                                                "Vedi solo quelli che puoi aprire; la guida si apre al suo capitolo."),
                    ("Chiedi all'Assistente", "apre l'Assistente AI con la tua frase già inviata: risponde con i dati del portale che puoi vedere. "
                                              "Compare in cima quando la frase sembra una domanda (comincia con chi, come, dove, quando… o finisce con «?»)."),
                ]),
                ("nota", "Subito dopo un riavvio del portale «Dalle guide e procedure» può non comparire: l'indice dei documenti si sta caricando, riprova tra poco."),
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
            "id": "notifiche",
            "titolo": "Scegliere le notifiche (portale, telefono, mail)",
            "blocchi": [
                ("p", "Campanella → «Impostazioni» (indirizzo /notifiche/impostazioni/). Per ogni categoria scegli dove riceverla."),
                ("def", [
                    ("Portale", "la notifica nella campanella. Se la spegni, la categoria non ti arriva da nessuna parte."),
                    ("Push", "la notifica compare anche sul telefono o sul PC, a portale chiuso. Si spunta solo se «Portale» è acceso."),
                ]),
                ("passi", [
                    "Apri le Impostazioni notifiche dal telefono o dal PC su cui vuoi le push.",
                    "In «Notifiche push su telefono e PC» premi «Attiva su questo dispositivo» e consenti le notifiche quando il browser lo chiede.",
                    "Spunta «Push» sulle categorie che ti interessano e premi «Salva preferenze».",
                    "Premi «Invia una prova»: entro qualche secondo arriva «NOVICROM HUB · prova».",
                ]),
                ("ul", [
                    "Ogni dispositivo si attiva a parte; l'elenco «Dispositivi attivi» mostra dove sono attive, «Togli» le spegne.",
                    "Le push si possono attivare già nel primo accesso al portale (passo «Preferenze notifiche»): "
                    "«Attiva su questo dispositivo» e, per ogni categoria, «anche come notifica sul telefono o sul PC».",
                    "«Sicurezza dell'account»: quando entri da un browser o da un PC che non avevi mai usato ti arriva l'avviso "
                    "«🔐 Accesso da un nuovo dispositivo» (campanella, push se la scegli, mail se «Avvisami anche per mail» è acceso). "
                    "Il primo dispositivo che usi non fa scattare avvisi.",
                    "«I miei accessi» (in fondo alla pagina): browser e PC da cui sei entrato, con primo e ultimo accesso e IP. "
                    "Su un accesso che non è tuo premi «Non ero io»: la sessione di quel dispositivo viene chiusa, la sicurezza IT "
                    "riceve un allarme e tu devi cambiare subito la password.",
                    "Su iPhone serve prima «Condividi → Aggiungi alla schermata Home» e aprire il portale da lì (iOS 16.4 o successivo).",
                    "Fuori dalla rete aziendale la push arriva lo stesso ma mostra un testo generico: il dettaglio si legge aprendo il portale.",
                    "«Le mie scadenze nel calendario Outlook»: ogni mattina alle 6:30 il portale aggiorna nel tuo Outlook il calendario "
                    "«Scadenze NOVICROM HUB» (scadute e prossimi 90 giorni). Se cancelli un evento in Outlook non viene rimesso, "
                    "a meno che la scadenza cambi data; togliendo la spunta il calendario si svuota la mattina dopo.",
                    "«Riepilogo scadenze via mail»: ogni mattina dei giorni feriali alle 7:30 le scadenze dello Scadenzario globale che puoi vedere "
                    "(scadute e prossimi 7 o 30 giorni). Se non c'è niente non parte; al massimo una al giorno.",
                ]),
            ],
        },
        {
            "id": "home",
            "titolo": "La home",
            "blocchi": [
                ("p", "La home ti mostra cosa devi fare oggi (richieste da approvare, scadenze, letture), i documenti utili e i collegamenti ai moduli. "
                      "La guida completa della home è nel collegamento qui sopra."),
                ("ul", [
                    "«⚙ Personalizza»: stanza di apertura, riquadri da mostrare (Azioni rapide, Il tuo brief di oggi, News aziendali) e «Rifai il tour».",
                    "Preferiti: nella stanza «Moduli» tocca ☆ su una tessera; il modulo compare in «I miei preferiti» nella colonna di sinistra (massimo 12).",
                    "La prima volta che entri parte un giro di benvenuto: barra di ricerca, notifiche, assistente, guida, stanze e preferiti.",
                ]),
            ],
        },
        {
            "id": "tabelle-viste",
            "titolo": "Tabelle: ordinare, filtrare, allargare, schermo intero",
            "blocchi": [
                ("p", "Le tabelle del portale funzionano tutte allo stesso modo. Sopra c'è una barra con «Cerca…», "
                      "«Colonne ▾», «Viste ▾», «Reset», «Schermo intero» e il numero di righe "
                      "(«45 / 1.340» = righe trovate / righe totali). In Anagrafica la casella di ricerca è quella della pagina."),
                ("def", [
                    ("↕ nell'intestazione", "ordina la colonna (crescente, decrescente, nessun ordine). Con Maiusc+clic ordini su più colonne."),
                    ("Imbuto nell'intestazione", "filtra la colonna: testo contenuto, un valore dall'elenco, una data, oppure «≥ valore» per i numeri. "
                     "L'imbuto pieno indica un filtro attivo; «Pulisci» lo toglie."),
                    ("Bordo destro dell'intestazione", "trascinalo per allargare o stringere la colonna; doppio clic la adatta al contenuto. "
                     "Da tastiera: Tab fino al bordo, poi frecce ← →. Le larghezze restano salvate per te."),
                    ("Colonne ▾", "scegli le colonne da vedere e trascinale per cambiarne l'ordine. Il portale lo ricorda da solo."),
                    ("Viste ▾", "«＋ Salva la vista attuale…» dà un nome a colonne, filtri, ricerca e ordinamento di adesso; "
                     "un clic sul nome la richiama, × la elimina. Fino a 12 viste per tabella, solo tue. "
                     "Quando una vista è attiva il pulsante dice «Vista: nome»."),
                    ("Reset", "torna alle colonne e alle larghezze di partenza della tabella. Le viste salvate restano."),
                    ("Schermo intero", "porta la tabella a tutto lo schermo, con la sua barra. Esc o «Esci (Esc)» per tornare alla pagina."),
                ]),
                ("p", "Tabelle lunghe: quando la tabella è più alta dello schermo scorre dentro il suo riquadro e "
                      "l'intestazione resta sempre in vista. Oltre 150 righe circa se ne mostrano 100 alla volta: "
                      "in fondo alla tabella il piede dice «Visualizzate 100 di 1.340 righe»; scorrendo fino in fondo "
                      "arrivano le successive, oppure usa «Mostra altre 100» o «Mostra tutte». Gli elenchi divisi in pagine "
                      "caricano la pagina successiva allo stesso modo."),
                ("nota", "Ricerca, filtri e ordinamento valgono sempre su tutte le righe, anche quelle non ancora "
                         "disegnate: alla prima ricerca il portale carica l'elenco completo (fino a 5.000 righe). "
                         "Senza una vista, filtri e ricerca valgono solo finché resti sulla pagina: ricaricando la tabella torna completa."),
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
                    "«⬇ Calendario (.ics)» scarica le stesse righe come file di calendario: aprilo con Outlook (o un altro calendario) "
                    "e ogni scadenza diventa un evento di un giorno con promemoria il giorno prima alle 9. È una copia: non si aggiorna da sola.",
                    "Per averle sempre aggiornate in Outlook: Impostazioni notifiche → «Le mie scadenze nel calendario Outlook».",
                    "Il nome nella colonna Soggetto apre la pagina dove la scadenza si gestisce. Qui si guarda soltanto: niente si modifica.",
                ]),
            ],
        },
        {
            "id": "miei-report",
            "titolo": "I miei report",
            "blocchi": [
                ("p", "Menu con il tuo nome → «I miei report»: tutti i report che puoi generare, raccolti dai vari moduli. "
                      "Vedi solo quelli dei moduli che puoi già aprire; «Apri» porta alla pagina da cui si scaricano."),
                ("ul", [
                    "«Cerca tra i tuoi report» filtra mentre scrivi.",
                    "L'etichetta «Dati personali» segna i report con dati di colleghi: usali solo per lavoro e non inoltrarli fuori dall'azienda.",
                    "«Ricevi per mail»: i report pianificati che ti arrivano da soli, con frequenza e prossimo invio.",
                    "In fondo, «I miei scaricamenti»: i tuoi ultimi 30 file di report degli ultimi 90 giorni. Il file non viene conservato.",
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
        {
            "id": "push-admin",
            "titolo": "Attivare le notifiche push sul server",
            "blocchi": [
                ("passi", [
                    "Dal terminale del server: manage.py genera_chiavi_vapid. Stampa due righe, VAPID_PRIVATE_KEY e VAPID_SUBJECT.",
                    "Copiale nel .env del server (è un segreto come gli altri: niente mail o ticket) e riavvia il sito e il qcluster.",
                    "Controllo: manage.py genera_chiavi_vapid --verifica deve dire «VAPID_PRIVATE_KEY valida».",
                ]),
                ("ul", [
                    "Il portale deve essere in https (le push non funzionano in http).",
                    "Il server deve poter uscire su internet in https (porta 443) verso fcm.googleapis.com, *.push.services.mozilla.com, "
                    "*.notify.windows.com e *.push.apple.com. Il traffico contiene solo il segnale, mai il testo della notifica.",
                    "Gli invii partono dal qcluster (django-q): senza qcluster attivo le push non partono, la campanella sì.",
                    "Il riepilogo scadenze è il task «scadenze_digest_personale» (lun-ven 7:30), disattivabile dalla Centrale di comando.",
                    "Il calendario Outlook delle scadenze è il task «scadenze_outlook_sync» (ogni giorno 6:30): scrive nelle caselle con il "
                    "permesso Graph Calendars.ReadWrite (applicazione), lo stesso degli incontri KICK-OFF. L'ultimo errore di ogni persona "
                    "compare nella sua pagina Impostazioni notifiche.",
                    "Cambiare la chiave spegne le push già attivate: ogni utente deve riattivarle.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Mi arriva «Accesso da un nuovo dispositivo» ma ero io",
            "fare": [
                "Capita quando entri da un browser nuovo, dopo aver cancellato i cookie o in navigazione anonima: va bene così.",
                "Se non eri tu: Impostazioni notifiche → «I miei accessi» → «Non ero io» su quell'accesso, poi cambia la password.",
            ],
        },
        {
            "sintomo": "Una vista salvata non mostra quello che mi aspettavo",
            "fare": [
                "Le viste sono legate a quella tabella di quella pagina: su un'altra pagina non compaiono.",
                "Se la tabella ha cambiato colonne, le colonne nuove compaiono comunque e quelle tolte vengono ignorate: risalva la vista.",
                "«Vista non salvata»: troppi filtri lunghi o connessione assente. Riprova con meno filtri.",
            ],
        },
        {
            "sintomo": "In una tabella mancano righe o il testo è tagliato con «…»",
            "fare": [
                "Guarda il piede della tabella: «Visualizzate 100 di 1.340 righe» vuol dire che le altre arrivano scorrendo "
                "fino in fondo o con «Mostra tutte».",
                "Il numero sulla barra («45 / 1.340») dice quante righe passano ricerca e filtri: un imbuto pieno "
                "nell'intestazione è un filtro ancora attivo.",
                "Testo tagliato: la colonna è stata stretta. Doppio clic sul bordo destro dell'intestazione la riadatta al "
                "contenuto; «Reset» riporta tutte le larghezze di partenza.",
                "Oltre 5.000 righe la barra mostra «Limite 5000 righe raggiunto»: restringi con i filtri della pagina.",
            ],
        },
        {
            "sintomo": "La home non si apre sulla stanza scelta",
            "fare": [
                "Un indirizzo che finisce con #oggi, #sapere, #persone o #moduli ha la precedenza: apri la home dal logo o dal menu.",
                "Controlla in «⚙ Personalizza» la voce «Stanza di apertura» e premi «Salva».",
            ],
        },
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
            "sintomo": "Le notifiche push non arrivano sul telefono",
            "fare": [
                "In Impostazioni notifiche, dal telefono: «Questo dispositivo» deve dire «attive», e la categoria deve avere «Push» spuntato.",
                "«bloccate nelle impostazioni del browser»: sblocca le notifiche per il sito del portale dalle impostazioni del browser.",
                "«Invia una prova»: se risponde «servizio push non raggiungibile», il server non esce su internet verso i servizi push (vedi «Attivare le notifiche push sul server»).",
                "«non sono ancora attive sul server»: manca VAPID_PRIVATE_KEY nel .env.",
                "Arriva la prova ma non le notifiche vere: controlla che il qcluster sia attivo (Centrale di comando).",
                "Dopo 5 invii falliti di fila o se il browser revoca il permesso, il dispositivo si toglie da solo: va riattivato.",
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
