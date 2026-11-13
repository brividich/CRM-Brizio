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
                ("p", "CN Automations è la vista con cui si apre il designer di una regola: i passaggi uno sotto l'altro come in Power Automate. "
                      "In alto «Quando un elemento …» (sorgente, quando, su quali modifiche), poi «Condizione · tutte vere» con le "
                      "condizioni e il pulsante «+ Nuova condizione», poi «Poi esegui, in ordine» con un riquadro per ogni azione: "
                      "icona e nome del tipo (es. «Invia un messaggio di posta», «Crea un record», «Pubblica in un canale Teams», "
                      "«Condizione (Se / Altrimenti)»), riassunto e «Modifica card» per i campi (per la mail: Mittente, A, Oggetto, Corpo, "
                      "e in «Opzioni avanzate» CC, CCN e HTML). «Esegui solo se…» limita un singolo passaggio. "
                      "La condizione è un elenco di righe «Campo | Operatore | Valore» unite da «E» (tutte devono essere vere), con "
                      "«+ Aggiungi riga»; sotto ci sono i due esiti: «✓ Se sì» esegue i passaggi, «✕ Se no» ferma la regola. Per fare "
                      "qualcosa anche nel caso no si aggiunge il passaggio «Condizione (Se / Altrimenti)»: due colonne «✓ Se sì» e «✕ Se no», "
                      "ognuna con i suoi passaggi. «Ripeti finché» ha tre colonne: «Ripeti questi passaggi», «Quando la condizione è vera» e "
                      "«Se finiscono i tentativi»; «Per ogni elemento» ha «Per ogni elemento esegui». Dentro le colonne «+ Log», «+ Delay», "
                      "«+ Email», «+ Aggiorna record», «+ Teams» aggiungono un passaggio; «Modifica» apre i suoi campi (A, CC, Oggetto, Corpo; "
                      "Messaggio; Quanto e Unità; Titolo e Testo; righe campo = valore), «Su», «Giù» e «Rimuovi» lo spostano o lo tolgono. "
                      "Gli operatori sono in italiano (è uguale a, contiene, è vuoto, è cambiato in, mancano al massimo N giorni…). "
                      "Il contenuto dinamico è "
                      "il riquadro «Contenuti / Colonne disponibili» a destra: clic in un campo della card, poi «Usa nel target» sul campo "
                      "del record da inserire ({nome_campo}). «Vista classica» torna al designer di prima (la scelta resta nel browser); "
                      "dati, salvataggio e test sono gli stessi."),
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
                ("p", "Dal 13/11/2026 c'è ogni mail che il portale manda: anche quelle dei moduli che non passano da una "
                      "regola (reception, KICK-OFF, sistema di gestione, avvisi IT, monitoraggio…) compaiono con «Tipo di mail» "
                      "«Mail dei moduli» e il modulo in «Sorgente» (dentro un flusso, il codice del flusso). Le mail di "
                      "sicurezza dell'accesso (codice 2FA, nuovo dispositivo) sono registrate ma non si modificano dai flussi."),
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
                      "si spengono e con «Modifica» si cambiano ricorrenza, destinatari, CC e testo della mail. Lo stato di salute di ognuno è in "
                      "Amministrazione → Monitoring → «Salute degli schedule»."),
                ("p", "In cima c'è il raccoglitore «Digest e promemoria»: i riepiloghi e i solleciti che arrivano alle persone, "
                      "in ordine di orario, con le colonne «Oggetto della mail» e «A chi». L'oggetto è quello che arriva in casella: «N» sta per un numero, ‹…› per un testo che cambia (reparto, codice, persona) e sotto, con «oppure:», ci sono le varianti; se l'oggetto è stato cambiato da «Modifica» compare quello, con la scritta «personalizzato». Chi non manda mail ma solo una notifica nel portale lo dice nella stessa colonna. «Sospendi» con una data li ferma fino a quel giorno "
                      "compreso (al massimo 60 giorni) e il giorno dopo ripartono da soli; lo stato diventa «In pausa fino al …». "
                      "«Sospendi tutti fino al» ferma l'intero raccoglitore (ferie, chiusure), «Riprendi» e «Riprendi tutti» "
                      "tolgono la pausa subito. La pausa vale per tutti i destinatari; «Esegui ora» manda il digest comunque."),
                ("p", "Per fermare un digest a tempo indeterminato usa «Disattiva». Per smettere di riceverlo una persona sola, "
                      "toglila dai destinatari con «Modifica»; il riepilogo personale delle scadenze si spegne invece "
                      "da Notifiche → Impostazioni di chi lo riceve."),
                ("p", "«Modifica» apre di lato il flusso come in Power Automate: tre passaggi uno sotto l'altro, ognuno si apre e "
                      "si chiude con un clic. Lo stesso pulsante c'è su ogni riga di «Pianificati» e di «Notifiche di sistema» "
                      "(i flussi che partono da un evento del modulo)."),
                ("p", "1) «Ricorrenza» (solo lavori pianificati): Frequenza «Ogni N minuti», «Ogni giorno, nei giorni scelti» "
                      "(orario + pulsanti lun…dom), «Ogni mese, in un giorno» (giorno 1-31 + orario) o «Personalizzato (cron)» "
                      "con i cinque campi minuto, ora, giorno, mese, giorno della settimana (es. 40 7-19 * * 1-5). Sotto c'è la "
                      "«Prossima esecuzione». Per un flusso su evento il primo passaggio è «Quando accade nel modulo» e dice cosa lo fa partire."),
                ("p", "2) «Esegui processo del modulo»: raccoglie i dati e decide cosa mandare con le regole del modulo; non si modifica."),
                ("p", "3) «Invia un messaggio di posta»: «Invia la mail» spenta = il flusso gira ma non manda mail. «A»: per i "
                      "lavori con elenco fisso (visite, contratti, idoneità, cambio mansione, formazione, e-learning, DPI, "
                      "manutenzioni, letture MFC) è l'elenco stesso, vuoto = amministratori di sistema (MFC: la mail non parte); "
                      "per gli altri c'è l'etichetta dei destinatari che sceglie il modulo (assegnatari, capireparto, dipendente…) "
                      "e sotto si aggiungono altri indirizzi. «CC»: indirizzi in copia a ogni mail del flusso. «Oggetto»: vuoto = "
                      "quello del modulo; il pulsante «＋ Oggetto del modulo» inserisce {oggetto}, che riprende l'oggetto originale "
                      "dentro il tuo (es. [HR] {oggetto}). «Corpo»: testo prima del contenuto generato dal modulo e nota in fondo. "
                      "«Mostra opzioni avanzate»: «Non inviare a» toglie indirizzi da A e CC; «Manda solo agli indirizzi scritti in A» "
                      "sostituisce i destinatari del modulo (serve almeno un indirizzo)."),
                ("p", "«Impostazioni del modulo» (dentro «Invia un messaggio di posta», solo per i flussi che le hanno): sono "
                      "gli stessi elenchi e testi della pagina del modulo, e la riga sotto il titolo dice dove. Cambiarli qui "
                      "o nel modulo è la stessa cosa: DPI (email Magazzino, Amministrazione, negozio, operatore scarpe, referenti), "
                      "Reception (oggetto e testo delle mail di invito, conferma e rifiuto), avviso IT nuovi ingressi, idoneità e "
                      "cambio mansione, report scadenze settimanale, riepilogo CN-SGI, RSGI del sistema di gestione, responsabile "
                      "escalation Suggestion Corner, CC predefiniti KICK-OFF. Le liste MOD.128 (Qualità) e monitoraggio IT "
                      "non hanno una pagina nel modulo e si cambiano solo qui. Un indirizzo non valido blocca il salvataggio."),
                ("p", "Sono flussi su evento anche le mail dei moduli che prima partivano senza automazione: sollecito al capo "
                      "chiesto dal dipendente (Assenze), invito, conferma, richiesta al referente e rifiuto (Reception), piano e "
                      "rapporto di audit (Sistema di gestione), nuova attività assegnata, convocazione, minuta e annullamento "
                      "incontro (KICK-OFF), avviso IT per un nuovo ingresso (Anagrafica), comunicazione al cliente (Suggestion "
                      "Corner). Con «Invia la mail» spenta il modulo lo dice (es. «Il sollecito non è partito»)."),
                ("p", "«Salva» vale subito, senza riavvii. «Invia prova a me» manda un'anteprima con righe di esempio, «Esegui ora» "
                      "fa partire il lavoro pianificato, «Storico» apre le sue esecuzioni. Indirizzi separati da virgola, punto e "
                      "virgola o a capo. Le regole valgono per ogni mail che il processo manda dentro il flusso, anche le mail delle assenze (esito, "
                      "richiesta modificata o eliminata, certificazione di presenza, solleciti, certificato mancante), del controllo RENTRI, "
                      "del report scadenze settimanale e del SOC; restano fuori le mail delle anomalie, che si configurano in Gestione anomalie. "
                      "Le mail che non partono per una regola («Invia la mail» spenta, nessun destinatario rimasto) compaiono in «Mail inviate» con il motivo."),
                ("p", "«Apri flusso» mostra in cima la stessa vista; il designer tecnico con condizioni e azioni resta sotto "
                      "«Designer completo». Lì la card «Esegui processo del modulo» riassume quando parte, a chi arriva, CC e oggetto."),
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
