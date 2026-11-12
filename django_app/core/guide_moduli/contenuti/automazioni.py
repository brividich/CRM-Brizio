GUIDA = {
    "slug": "automazioni",
    "titolo": "Automazioni",
    "area": "Amministrazione del portale",
    "sintesi": "Le regole che mandano mail, approvazioni e avvisi da sole quando succede qualcosa nei moduli.",
    "parole": "automazione automazioni regola regole mail approvazione flusso power automate coda",
    "url": "automazioni:automazioni_rule_list",
    "prefissi": ("/automazioni/",),
    "uso": [
        {
            "id": "cosa",
            "titolo": "Cosa sono",
            "blocchi": [
                ("p", "Le automazioni sono regole del tipo «quando succede X, fai Y»: per esempio «quando arriva una richiesta "
                      "di ferie, manda la mail al capo». Chi usa il portale non deve fare niente: le regole lavorano da sole."),
                ("p", "Se ricevi una mail di approvazione con i pulsanti Approva / Rifiuta, il collegamento è personale: "
                      "non inoltrarlo ad altri."),
                ("p", "Dopo «Conferma Approvazione» o «Conferma Rifiuto» compare «Richiesta Approvata» o «Richiesta "
                      "Rifiutata»: la decisione è registrata. Se riapri il link più tardi rivedi la tua decisione. "
                      "«Richiesta già Elaborata» compare solo se ha deciso un altro approvatore, indicato nel messaggio."),
                ("p", "La pagina registra la decisione subito; le azioni che seguono (mail al dipendente, aggiornamento "
                      "della richiesta) partono in background nei secondi successivi."),
            ],
        },
    ],
    "admin": [
        {
            "id": "regole",
            "titolo": "Le regole",
            "blocchi": [
                ("ul", [
                    "«Regole»: l'elenco di tutte le regole con lo stato (attiva / non attiva). Il codice (es. AU51) è citato nelle guide dei moduli.",
                    "Una regola ha: la sorgente (cosa la fa partire), le condizioni (quando) e le azioni (cosa fa).",
                    "Le regole importate dai pacchetti nascono in bozza e spente: vanno controllate e attivate a mano.",
                    "«Test» esegue la regola su un record vero o di esempio senza scrivere niente: usalo sempre prima di attivare.",
                ]),
            ],
        },
        {
            "id": "runlog",
            "titolo": "Vedere cosa è successo (run log)",
            "blocchi": [
                ("passi", [
                    "Apri il run log delle automazioni.",
                    "Filtra per regola o per «Sorgente» (i lavori di sistema compaiono come «Sistema: …»).",
                    "Apri un'esecuzione: vedi per ogni azione l'esito e l'eventuale errore.",
                    "«Ripeti» riapre il test della regola con gli stessi dati, per riprovare dopo aver corretto.",
                ]),
                ("p", "I run log più vecchi di 90 giorni si cancellano da soli (dati personali)."),
            ],
        },
        {
            "id": "mail-inviate",
            "titolo": "Mail inviate",
            "blocchi": [
                ("passi", [
                    "Apri Automazioni → «Mail inviate».",
                    "Cerca per «Destinatario o oggetto» (es. l'indirizzo della persona) o per «N. richiesta».",
                    "Restringi con «Tipo di mail», «Sorgente», «Esito» e le date «Dal» / «Al».",
                    "Ogni riga mostra quando è partita, a chi (e chi era in copia), l'oggetto, la regola e l'esito; "
                    "«Run log #…» apre l'esecuzione della regola.",
                ]),
                ("p", "Ci sono le mail delle regole (avvisi e richieste di approvazione, una riga per approvatore) e quelle "
                      "delle assenze che non passano dalle regole: «Richiesta modificata», eliminazione di una richiesta "
                      "approvata, solleciti ai capi. Ci sono anche tutte le mail del modulo Anomalie (link di decisione "
                      "al capocommessa, conferma aggiornamenti, resoconto escalation, P/N ricorrente, digest, OP "
                      "completato): «Tipo di mail» comincia con «Anomalie ·» e «Richiesta» mostra «OP #…». "
                      "«Errore» indica una mail non partita, con il motivo."),
                ("p", "Il testo della mail non si salva, solo destinatari e oggetto. Il registro parte dall'installazione della "
                      "pagina e le righe si cancellano da sole dopo gli stessi giorni dei run log (Impostazioni, default 90). "
                      "Le mail Anomalie partite prima si possono recuperare dal loro Log attività: lo fa l'amministratore "
                      "del server con il comando «recupera_mail_inviate_anomalie»."),
            ],
        },
        {
            "id": "pianificati",
            "titolo": "Lavori pianificati",
            "blocchi": [
                ("p", "«Pianificati» elenca i lavori che girano a orari fissi (sincronizzazioni, promemoria, pulizie): si accendono, "
                      "si spengono e per quelli con mail si configura il testo. Lo stato di salute di ognuno è in "
                      "Amministrazione → Monitoring → «Salute degli schedule»."),
                ("p", "In cima c'è il raccoglitore «Digest e promemoria»: i riepiloghi e i solleciti che arrivano alle persone, "
                      "in ordine di orario, con le colonne «Oggetto della mail» e «A chi». L'oggetto è quello che arriva in casella: «N» sta per un numero, ‹…› per un testo che cambia (reparto, codice, persona) e sotto, con «oppure:», ci sono le varianti; se l'oggetto è stato cambiato da «Configura mail» compare quello, con la scritta «personalizzato». Chi non manda mail ma solo una notifica nel portale lo dice nella stessa colonna. «Sospendi» con una data li ferma fino a quel giorno "
                      "compreso (al massimo 60 giorni) e il giorno dopo ripartono da soli; lo stato diventa «In pausa fino al …». "
                      "«Sospendi tutti fino al» ferma l'intero raccoglitore (ferie, chiusure), «Riprendi» e «Riprendi tutti» "
                      "tolgono la pausa subito. La pausa vale per tutti i destinatari; «Esegui ora» manda il digest comunque."),
                ("p", "Per fermare un digest a tempo indeterminato usa «Disattiva». Per smettere di riceverlo una persona sola, "
                      "toglila dai destinatari con «Configura mail»; il riepilogo personale delle scadenze si spegne invece "
                      "da Notifiche → Impostazioni di chi lo riceve."),
                ("p", "«Apri flusso» porta alla scheda del lavoro in cima al designer: stato (Attivo o Disattivato), "
                      "«Quando» (la cadenza in parole), «Prossima esecuzione» e la descrizione aggiornata dal codice. "
                      "Per cambiare l'orario scegli la Ricorrenza: «Ogni N minuti» chiede l'intervallo, «Calendario» "
                      "chiede i cinque campi minuto, ora, giorno, mese, giorno della settimana (es. 0 0 1 * * = il giorno 1 "
                      "del mese alle 00:00, fuso del portale), poi «Salva pianificazione»: vale subito, senza riavvii."),
                ("nota", "L'orario di un lavoro già installato resta quello salvato nel flusso: se cambia nel codice "
                         "di una nuova versione, va aggiornato qui a mano."),
                ("nota", "Tutte le automazioni e i lavori pianificati girano nel servizio «qcluster» sul server. Se è fermo, "
                         "non parte niente: vedi il Manuale di emergenza."),
            ],
        },
        {
            "id": "trigger",
            "titolo": "Trigger SQL",
            "blocchi": [
                ("p", "Alcune sorgenti (per esempio la tabella delle assenze) usano trigger sul database che mettono gli eventi nella coda. "
                      "Il «Trigger generator» li crea; dopo un'installazione nuova si applicano con il comando apply_sql_triggers."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Dopo aver approvato dalla mail compariva «Richiesta già Elaborata»",
            "perche": "fino al 02/11/2026 il secondo invio della conferma (doppio clic) o la riapertura del link mostravano "
                      "«già gestita» anche a chi aveva appena deciso; la decisione era comunque registrata.",
            "fare": [
                "Ora chi ha deciso rivede «Richiesta Approvata/Rifiutata» con data e casella registrate.",
                "Se il messaggio indica un altro indirizzo, la richiesta l'ha decisa quell'approvatore.",
            ],
        },
        {
            "sintomo": "Una mail automatica non è partita",
            "fare": [
                "Apri il run log e cerca l'esecuzione della regola nell'ora giusta.",
                "Se non c'è nessuna esecuzione: la regola è spenta, oppure le condizioni non erano vere, oppure il qcluster è fermo.",
                "Se c'è un errore nell'azione di invio mail: leggi il messaggio (indirizzo sbagliato, server di posta non raggiungibile).",
                "Se nessuna mail del portale parte: Manuale di emergenza → «Le mail non partono».",
            ],
        },
        {
            "sintomo": "Mail doppie",
            "perche": "di solito sono due regole attive sullo stesso evento, oppure due qcluster accesi insieme.",
            "fare": [
                "Nel run log controlla se le due mail vengono da due regole diverse: spegnine una.",
                "Se vengono dalla stessa regola, sul server controlla che ci sia un solo qcluster (Manuale di emergenza).",
            ],
        },
        {
            "sintomo": "Eventi fermi in coda",
            "fare": [
                "Gli eventi rimasti «in lavorazione» oltre 15 minuti tornano in coda da soli; dopo 5 tentativi vanno in errore.",
                "Dalla pagina della coda puoi «Stoppa» o «Elimina» un evento bloccato.",
                "«Riprova» accoda l'evento al qcluster: ricarica la pagina dopo qualche secondo per vedere l'esito.",
                "Controlla che il qcluster stia girando.",
            ],
        },
        {
            "sintomo": "Dopo «Riprova» temevo mail doppie",
            "fare": [
                "Riprovare un evento non ripete le azioni già riuscite: nel run log compaiono come "
                "«Già eseguita con successo in un tentativo precedente di questo evento: non ripetuta».",
                "Richiesta di approvazione arrivata solo ad alcuni approvatori: l'azione va in errore con "
                "«Recapito parziale della richiesta #…»; i link già inviati restano validi e il tentativo successivo "
                "manda la mail solo a chi mancava.",
            ],
        },
        {
            "sintomo": "Un'azione HTTP o Teams è in errore con «redirect verso … non seguito» o «non riesce a risolvere»",
            "fare": [
                "«redirect verso <host> non seguito (HTTP 3xx)»: l'indirizzo configurato rimanda altrove; per sicurezza il "
                "portale non segue i redirect. Correggi l'URL con quello finale.",
                "«il server non riesce a risolvere <host> (DNS)»: problema di nome o di rete del server, non un blocco "
                "delle regole di sicurezza.",
                "Nei messaggi e nel run log degli URL compare solo l'indirizzo del server (schema e host): la firma "
                "«sig=» dei flussi Power Automate e i webhook Teams non vengono più scritti.",
            ],
        },
        {
            "sintomo": "Una risposta alla casella approvazioni resta «Errore» nel log mailbox",
            "fare": [
                "Se la richiesta non esiste più o è scaduta il messaggio diventa «ignorato» e viene segnato come letto.",
                "Gli altri errori si ritentano al massimo 3 volte, poi il messaggio diventa «ignorato» con "
                "«Abbandonato dopo 3 tentativi non riusciti».",
            ],
        },
    ],
}
