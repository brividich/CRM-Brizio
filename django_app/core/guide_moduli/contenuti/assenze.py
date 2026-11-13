GUIDA = {
    "slug": "assenze",
    "titolo": "Assenze",
    "area": "Persone e HR",
    "sintesi": "Ferie, permessi, malattia e flessibilità: si chiedono qui, il capo le approva, il calendario le mostra.",
    "parole": "ferie permesso permessi malattia flessibilita calendario approvare capo reparto saldo residuo rol "
              "festivita chiusura aziendale contatori assemblea 104 copertura solleciti storico hr",
    "url": "assenze_menu",
    "prefissi": ("/assenze/",),
    "uso": [
        {
            "id": "chiedere",
            "titolo": "Chiedere ferie o un permesso",
            "blocchi": [
                ("passi", [
                    "Apri Assenze e clicca «Nuova richiesta» nella barra del modulo.",
                    "In «Tipo assenza» clicca una card: «Ferie / Permesso», «Malattia», «Flessibilità» o «Certifica presenza».",
                    "Scegli le date in «Data inizio» e «Data fine»: partono vuote, vanno sempre scelte. Per un solo giorno metti la stessa data. "
                    "Con «Ferie / Permesso» decidono le date: un solo giorno è un permesso a ore, più giorni sono ferie a giornata intera.",
                    "In «Durata rapida» scegli l'orario già pronto (per esempio «Normale (08:00-17:00)», «Giornata lunga (08:00-18:00)» per chi fa il turno 8-18 o "
                    "«Mezza mattina (08:00-12:00)»). Se ti serve un orario diverso scegli «Personalizzato» e scrivi "
                    "«Ora inizio» e «Ora fine».",
                    "Controlla il riquadro «Riepilogo» (a destra; su telefono e schermi stretti in fondo al form): tipo, dipendente, periodo, durata e chi approva. "
                    "Il bollino dice «Pronta» o «Da completare» e, finché manca qualcosa, sotto c'è «Manca: …».",
                    "Clicca «Conferma invio» in fondo al riepilogo, una volta sola: il pulsante diventa «Invio in corso…». "
                    "Se manca un dato non parte e l'errore compare in rosso accanto al campo da correggere.",
                    "Si apre il riquadro verde «Richiesta inviata» con dipendente, tipo, periodo, stato (per esempio "
                    "«In attesa di approvazione da …») e numero di riferimento: se lo vedi la richiesta è salvata e "
                    "il capo riceve la mail. Da lì vai a «Le mie richieste» oppure fai una «Nuova richiesta».",
                ]),
                ("def", [
                    ("Permesso", "almeno 30 minuti, senza un massimo di ore, sempre nello stesso giorno (anche con turni lunghi, es. 8-18)."),
                    ("Permesso su più giorni", "con lo stesso orario: compila il primo giorno e scegli la data in "
                     "«Ripeti lo stesso orario fino al». Si crea una richiesta per ogni giorno lavorativo (sabati, "
                     "domeniche, festività e chiusure aziendali esclusi), al massimo 31 giorni. Il capo riceve una sola mail "
                     "«Permesso ripetuto dal … al …» e decide per tutti i giorni; anche la conferma a te e ad "
                     "assenza@ arriva una volta sola, con le date. Un singolo giorno si può ancora cambiare o "
                     "decidere a parte da «Assenze del reparto»."),
                    ("Ferie di più giorni", "contano a giornata intera."),
                    ("Malattia", "il pulsante «Malattia» lo vede chi è abilitato in Impostazioni (se l'elenco è vuoto lo vedono tutti); "
                     "chi è abilitato può scegliere qualunque dipendente in «Dipendente in malattia». "
                     "Spunta «Certificato arrivato» se il certificato medico è già arrivato. Il numero del certificato non si scrive. "
                     "Se arriva dopo, apri la richiesta con «Modifica» e spunta la casella. "
                     "Se la malattia è già approvata, in «Le mie richieste» c'è il pulsante «Certificato arrivato»: vale come modifica "
                     "e avvisa assenza@ e il capo reparto. "
                     "Le mail della malattia (al capo, ad assenza@, esito, modifiche ed eliminazione) riportano «Certificato arrivato: Sì» o «No». "
                     "Se dopo 2 giorni dall'inizio il certificato non risulta arrivato, l'ufficio assenze riceve un avviso."),
                    ("Flessibilità", "solo per chi è abilitato, solo negli orari fissati dall'Amministrazione, massimo 2 a settimana."),
                    ("Capo reparto", "è proposto in automatico dall'organigramma e cambia da solo quando scegli un altro dipendente. Puoi sceglierne un altro dall'elenco: "
                     "in quel caso la richiesta la vede e la approva solo il capo che hai scelto. Se il capo del "
                     "tuo reparto sei tu, ti viene proposto chi ti sta sopra (es. l'Operations Manager)."),
                ]),
                ("nota", "Se l'ora di fine è prima dell'ora di inizio il portale la corregge da solo a inizio + 30 minuti e te lo dice: controlla prima di inviare."),
                ("nota", "Una richiesta identica a una già inviata (stessa persona, tipo, inizio e fine, non rifiutata) non parte due volte: "
                         "il portale dice «Questa richiesta è già stata inviata il …» e rimanda a «Le mie richieste»."),
            ],
        },
        {
            "id": "saldo",
            "titolo": "Il saldo di ferie e permessi e gli avvisi",
            "blocchi": [
                ("p", "Se in Anagrafica c'è il tuo ultimo cedolino, nel «Riepilogo» compare «Saldo stimato» (del dipendente scelto, se la inserisci per un altro): "
                      "le ore di ferie e di permessi che ti restano, partendo dal cedolino e togliendo le richieste già inviate "
                      "e le chiusure aziendali."),
                ("p", "Mentre compili, nel riepilogo possono comparire avvisi gialli, compreso «C'è 1 corso di formazione nei giorni richiesti» con il link al corso. Non bloccano l'invio: servono a te e al capo."),
                ("def", [
                    ("Saldo ferie (o permessi) insufficiente", "la richiesta vale più ore di quelle che ti restano."),
                    ("Contatore oltre il limite", "per esempio «Assemblea sindacale» oltre le ore annue o «Legge 104» oltre i giorni del mese."),
                    ("Giorni non lavorativi", "nel periodo ci sono festività o chiusure aziendali: quei giorni non contano nella richiesta."),
                ]),
                ("nota", "Il saldo è una stima: quello ufficiale resta il cedolino."),
            ],
        },
        {
            "id": "controllare",
            "titolo": "Vedere se la richiesta è stata approvata",
            "blocchi": [
                ("passi", [
                    "Clicca «Le mie richieste».",
                    "Le schede in alto (In attesa, Approvate, Rifiutate, Tutte) filtrano l'elenco.",
                    "Una richiesta ancora «In attesa» si può correggere con «Modifica» o togliere con «Elimina».",
                    "Se il capo non decide, con «Sollecita» gli rimandi la richiesta da approvare: la mail non dice che l'hai chiesto tu. Dopo l'invio "
                    "il pulsante diventa «Sollecitata» e resta fermo per i giorni di «Ripeti il sollecito ogni» (predefinito 2): "
                    "conta anche il promemoria automatico del mattino.",
                    "Ogni modifica (date, tipo, motivazione, «Certificato arrivato») manda una mail «Richiesta modificata» "
                    "ad assenza@ e al capo reparto, con cosa è cambiato prima e dopo.",
                ]),
                ("p", "Quando il capo decide ricevi una notifica (campanella in alto; sul telefono «Notifiche» nella barra in basso) "
                      "e una mail «Richiesta … approvata» o «Richiesta … rifiutata» all'indirizzo della richiesta, sia se decide dal "
                      "link nella mail sia se decide nel portale (con l'eventuale nota del rifiuto)."),
                ("nota", "Le richieste con l'etichetta «Gestita su SharePoint» sono nate nella vecchia app SharePoint: "
                         "si vedono qui ma si modificano solo là."),
            ],
        },
        {
            "id": "approvare",
            "titolo": "Approvare le richieste dei tuoi dipendenti (capi)",
            "blocchi": [
                ("passi", [
                    "In alto nella barra compare il numero «da approvare»: cliccalo. In alternativa apri «Assenze del reparto».",
                    "In «Richieste in attesa» trovi le richieste da decidere. Puoi filtrare per tipo e per periodo "
                    "(«Inizia oggi», «Entro 7 giorni», «Gia iniziate»).",
                    "Clicca «Approva» per approvare.",
                    "Per rifiutare clicca «Rifiuta», scrivi il motivo e clicca «Conferma rifiuto».",
                ]),
                ("p", "Il dipendente riceve subito l'esito, anche per mail. Se decidi dal portale, il link «Approva/Rifiuta» "
                      "della mail di approvazione si chiude: chi lo apre dopo legge «Questa richiesta è già stata gestita». "
                      "Le richieste già decise restano in «Le mie richieste» → "
                      "«Richieste dei miei dipendenti», nel blocco «Già decise»."),
                ("p", "Con il sistema «Ruoli e permessi» acceso nessuno approva o rifiuta una propria richiesta, nemmeno "
                      "in blocco o modificando l'evento: compare «Non puoi approvare o rifiutare una tua richiesta» e "
                      "decide un altro responsabile."),
                ("p", "Sotto il nome del dipendente possono comparire avvisi gialli: saldo insufficiente, contatore oltre il limite "
                      "(es. assemblea sindacale), oppure «Copertura …: il gg/mm sarebbero assenti N persone (soglia M)». "
                      "Sono informazioni: puoi approvare lo stesso."),
                ("p", "Nelle mail che arrivano a te come caporeparto (approvazione, avvisi, promemoria) c'è il pulsante "
                      "«Aggiungi al calendario Outlook»: apre Outlook web con l'assenza già compilata. L'evento è segnato "
                      "«libero»: non occupa la tua agenda. Non compare per le richieste rifiutate né nelle mail "
                      "all'ufficio assenze."),
                ("p", "Se l'ufficio HR ha acceso «Assenze approvate nel calendario Outlook», l'assenza va direttamente nel "
                      "calendario «Assenze del team (NOVICROM HUB)» (puoi mostrarlo o nasconderlo accanto al tuo calendario), "
                      "entro 10 minuti. Con «Solo quando lo si chiede» (il modo normale) scegli tu: nella mail di approvazione "
                      "c'è il pulsante «Approva e metti in calendario» (apre la conferma con la spunta «Metti nel mio calendario "
                      "Outlook» già messa; vale la casella a cui è arrivata la mail), nella pagina del capo la spunta «Metti nel "
                      "mio calendario Outlook le richieste che approvo», nella pagina di inserimento la spunta «Metti nel mio "
                      "calendario Outlook». Con «Tutte le assenze approvate» non devi fare niente: arrivano tutte nel calendario "
                      "del capo che le approva. Se una richiesta cambia l'evento si aggiorna, se viene rifiutata o eliminata "
                      "sparisce. Se cancelli tu un evento da Outlook, il portale non lo rimette. In questo caso le mail non "
                      "hanno più il pulsante «Aggiungi al calendario Outlook»."),
                ("p", "Se una richiesta resta «In attesa» ricevi nei giorni feriali alle 08:15 la mail «richieste di assenza da approvare» "
                      "con l'elenco (di norma dopo 2 giorni, poi ogni 2 giorni finché non decidi). Accanto a ogni richiesta ci sono "
                      "«Approva» e «Rifiuta»: si apre la conferma e con un clic hai deciso. Se la richiesta di approvazione è scaduta "
                      "i pulsanti non ci sono: decidi da «Assenze del reparto»."),
                ("p", "Dalla dashboard del reparto, «Il mio team» apre in Anagrafica l'elenco delle persone di cui sei "
                      "responsabile con il semaforo di conformità alla mansione (nessun dato sanitario)."),
                ("p", "La dashboard del reparto conta le stesse persone di «Il mio team»: «Oggi», «Settimana» e "
                      "«Gestite» sono le assenze di quel team (la pillola «N nel team» apre l'elenco). Se non risulti "
                      "responsabile di nessuno vale il capo indicato sulle richieste. Chi ha la vista aziendale trova "
                      "anche la scheda «Tutta l'azienda», con coda e riepiloghi di tutto il personale."),
                ("p", "La persona di una richiesta si riconosce dall'email o dal nome scritto sulla richiesta (anche "
                      "«COGNOME NOME» o «NOME COGNOME»), confrontati con l'Anagrafica e con l'utente del portale."),
                ("p", "«In attesa» e «Richieste in attesa» contano solo le richieste ancora da decidere: quelle rimaste "
                      "in attesa e finite da più di 30 giorni (in gran parte importate dal vecchio portale e mai decise) "
                      "escono dalla coda, ma restano nello storico e nel calendario."),
            ],
        },
        {
            "id": "calendario",
            "titolo": "Il calendario",
            "blocchi": [
                ("p", "«Calendario» mostra le assenze approvate con un colore per tipo. Con le frecce cambi mese."),
                ("p", "Nell'elenco del giorno, accanto a «Permesso» c'è il totale delle ore (es. «Permesso - 8h»): sono le stesse "
                      "ore che scala il saldo, quindi al massimo una giornata e zero se il giorno non è lavorativo."),
                ("p", "L'elenco degli assenti del giorno si ordina con i pulsanti «Nome» (predefinito), «Tipo», «Durata» "
                      "(le più lunghe prima) e «Inserita» (le richieste inserite più di recente prima); la scelta resta "
                      "memorizzata sul tuo browser. Il pannello «Colori calendario» è chiuso: cliccalo per aprirlo, e "
                      "l'elenco del giorno si accorcia per fargli spazio."),
                ("ul", [
                    "Cosa vedi dipende dal tuo ruolo: tutta l'azienda, solo il tuo reparto oppure solo le tue richieste.",
                    "Vedere le assenze degli altri non vuol dire poterle approvare.",
                    "Festività (rosa) e chiusure aziendali (grigio) sono colorate sullo sfondo, con il nome.",
                    "Cliccando una richiesta si apre il dettaglio con lo «Storico della richiesta»: chi l'ha creata, modificata, "
                    "approvata o rifiutata e quando, con i campi cambiati.",
                    "Per modificare una richiesta già approvata serve scrivere il «Motivo della modifica»: finisce nello storico "
                    "e nella mail «Richiesta modificata» che parte ad assenza@ e al capo reparto (non parte se cambia solo lo stato: "
                    "approvazione e rifiuto hanno già le loro mail).",
                    "Nelle malattie la casella «Certificato arrivato» si spunta anche da qui. Su una malattia già "
                    "approvata, se cambi solo quella spunta il «Motivo della modifica» sparisce: la spunta vale come motivo "
                    "(nello storico e nella mail compare «Certificato medico arrivato»). Se cambi anche date, tipo o "
                    "motivazione, oppure togli la spunta, il motivo torna obbligatorio.",
                ]),
            ],
        },
        {
            "id": "presenza",
            "titolo": "Certificare una presenza",
            "blocchi": [
                ("p", "Serve quando eri al lavoro ma la timbratura manca (per esempio una trasferta)."),
                ("passi", [
                    "Clicca «Certifica presenza».",
                    "Compila data e orari e clicca «Salva certificazione».",
                    "Per correggerla usa «Modifica» nella tabella «Certificazioni registrate».",
                ]),
                ("p", "La certificazione salvata da questa pagina è già approvata: parte subito la mail "
                      "«Certificazione presenza approvata» al dipendente e a chi l'ha inserita, con assenza@ in copia. "
                      "Se il nome corrisponde a più persone con indirizzi diversi, al dipendente non scrive."),
            ],
        },
    ],
    "admin": [
        {
            "id": "dove",
            "titolo": "Dove si configura",
            "blocchi": [
                ("p", "Tutto è in Assenze → «Impostazioni» (voce visibile solo agli amministratori del modulo)."),
                ("p", "Chi apre «Impostazioni» lo decide la matrice dei ruoli (Admin portale → Ruoli portale), "
                      "riga Assenze, sotto-riga «↳ Impostazioni del modulo»: Propri, Team o Tutti la aprono, «No» o «—» no. "
                      "Vale solo per la pagina Impostazioni: «Area HR», «Certifica presenza» e la gestione di tutte le "
                      "richieste restano a «Chiudere / gestire». Dopo la modifica premi «Salva matrice»."),
                ("def", [
                    ("Chi vede le assenze altrui", "riepilogo in sola lettura di chi vede tutta l'azienda, solo il reparto o solo le proprie richieste."),
                    ("Flessibilità", "elenco delle persone abilitate e orari ammessi di entrata e uscita (predefiniti 07:00/08:00/09:00 e 16:00/17:00/18:00). Si salva con «Salva flessibilità»."),
                    ("Inserimento malattia", "chi vede il pulsante «Malattia» nella nuova richiesta: le persone spuntate la "
                     "inseriscono per qualunque dipendente attivo, gli altri non la vedono e, se provano a inviarla o a "
                     "trasformare una loro richiesta in malattia, ricevono un errore. Elenco vuoto = tutti la vedono come prima "
                     "(per sé; per gli altri solo chi inserisce già per conto altrui). Si salva con «Salva inserimento malattia»."),
                    ("Cambio capo reparto", "chi può cambiare il capo proposto nella nuova richiesta: le persone spuntate "
                     "scelgono dall'elenco dei capi, gli altri vedono il capo assegnato e non possono modificarlo. Chi non ha un capo "
                     "assegnato può comunque sceglierlo. Elenco vuoto = tutti possono cambiarlo. Si salva con «Salva cambio capo reparto»."),
                    ("Gestione admin · Tutte le assenze", "tutte le richieste con filtri, ordinamento, approvazione o rifiuto in blocco (fino a 200 alla volta, nota obbligatoria) ed «Export CSV»."),
                    ("Certificati arrivati in blocco", "filtro «Certificato» = «Malattie senza certificato» (con «Tutti gli stati»), "
                                                       "seleziona le righe e premi «Certificato arrivato (senza mail)». Non parte nessuna mail; "
                                                       "nello storico della richiesta resta «Certificato medico arrivato (registrato in blocco, "
                                                       "senza mail)». Vale anche per le malattie nate sul vecchio SharePoint, che il certificato "
                                                       "non lo registravano. Le righe che non sono malattie o hanno già il certificato vengono saltate."),
                    ("Sincronizzazione SharePoint", "coda delle modifiche da mandare alla lista SharePoint, eventuali errori e pulsante «Sincronizza ora»."),
                ]),
                ("p", "Le mail del modulo si personalizzano in Automazioni (amministratori): in «Notifiche di sistema» le righe "
                      "«Assenze - esito della richiesta al dipendente», «Assenze - richiesta modificata», «Assenze - richiesta eliminata» e "
                      "«Assenze - certificazione di presenza confermata»; in «Pianificati» i solleciti ai capi (assenze_solleciti) e "
                      "l'avviso del certificato mancante (assenze_certificato_avviso). «Modifica» apre il passaggio «Invia un messaggio "
                      "di posta»: accendere o spegnere la mail, indirizzi in più in A o in CC, indirizzi da togliere, oggetto ({oggetto} = "
                      "quello del modulo), testo prima e nota in fondo. I destinatari normali (dipendente, capo, casella assenze) restano "
                      "decisi dal modulo."),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Chi vede e chi approva",
            "blocchi": [
                ("ul", [
                    "Il capo proposto è il capo del dipendente in Anagrafica: eccezione sulla persona → chi ha la "
                    "mansione del responsabile dell'area → chi ha la mansione del capo del reparto → gerarchia dei "
                    "ruoli (prima del passaggio alle mansioni: responsabile dell'area e poi caporeparto scelti a mano). "
                    "Si cambia in Anagrafica → Reparti, aree e capi, nel Mansionario («Responsabilità del reparto») "
                    "o in Impostazioni → Reparti, non qui: sono collegati, cambiarlo in uno lo cambia negli altri. "
                    "Il menu «Capo reparto» elenca caporeparto, responsabili delle aree e i loro co-capo.",
                    "Nessuno approva le proprie assenze: se il capo così trovato è il dipendente stesso (es. il CAR "
                    "capo del suo reparto), si propone chi gli sta sopra nella gerarchia dei ruoli, partendo dal suo "
                    "ruolo più alto (Caporeparto → Operations Manager, anche se lavora in un altro reparto).",
                    "Chi è abilitato in Impostazioni → «Cambio capo reparto» (se l'elenco è vuoto, tutti) può scegliere un "
                    "altro capo nella richiesta. Se lo fa, la richiesta compare in coda "
                    "e si approva solo dal capo scelto (oltre che dall'Amministrazione); il capo dell'organigramma la vede "
                    "ancora nel calendario ma non la approva.",
                    "La visibilità si assegna in Amministrazione → «Accessi» con i permessi «view_all_assenze» "
                    "(tutta l'azienda) e «view_reparto_assenze» (solo il reparto), a un ruolo o a una singola persona.",
                    "Se il sistema unico «Ruoli e permessi» è acceso, valgono le righe Assenze della matrice (vedere, approvare, esportare).",
                    "Caporeparto e Amministrazione possono inserire richieste per conto di qualsiasi dipendente.",
                ]),
                ("nota", "Un dipendente senza ruoli non vede il calendario: prima assegna il ruolo, poi controlla."),
            ],
        },
        {
            "id": "hr",
            "titolo": "Area HR: saldi, calendario aziendale, contatori, copertura",
            "blocchi": [
                ("p", "Assenze → «Area HR» (la vede chi vede «Impostazioni»). Nessun controllo blocca le richieste: "
                      "tutti producono avvisi per chi chiede e per chi approva."),
                ("def", [
                    ("Cruscotto", "richieste in attesa, saldi in negativo, persone con almeno 10 giornate di ferie residue, "
                                  "persone oltre un contatore, giornate di assenza degli ultimi 12 mesi e tabella per reparto. "
                                  "I reparti con meno di 5 persone non mostrano i numeri, per non far capire chi era assente."),
                    ("Saldi ferie e permessi", "sola lettura: le ore residue dell'ultimo cedolino di ogni dipendente, "
                                               "prese da Anagrafica → «Ratei ferie e permessi» (colonna «Cedolino al»). "
                                               "Permessi = ROL + ex festività. Per aggiornarli si caricano i cedolini in "
                                               "Anagrafica («Carica i cedolini»): qui non si inseriscono a mano."),
                    ("Calendario aziendale", "festività nazionali calcolate dal portale (Pasqua compresa, San Francesco il 4 ottobre "
                                             "dal 2026), il patrono e le chiusure aziendali. Una chiusura vale per tutta l'azienda; "
                                             "con «Scala dalle ferie» i suoi giorni lavorativi si tolgono dal saldo ferie di ognuno."),
                    ("Contatori", "un limite su una «Motivazione richiesta» (ore o giorni, al mese o all'anno). "
                                  "«Aggiungi i contatori consigliati» crea Assemblea sindacale (10 ore all'anno) e Permessi "
                                  "Legge 104 (3 giorni al mese): controlla che la motivazione sia scritta come nelle richieste."),
                    ("Copertura reparti", "per ogni reparto dell'anagrafica, quante persone possono essere assenti nello stesso "
                                          "giorno. Contano le assenze approvate a giornata intera; vuoto = nessun controllo."),
                    ("Calendario Outlook", "con «Assenze approvate nel calendario Outlook» acceso, il lavoro "
                                                    "«assenze_outlook_sync» (ogni 10 minuti) scrive le assenze approvate nel "
                                                    "calendario «Assenze del team (NOVICROM HUB)», via Microsoft Graph. «Quali "
                                                    "assenze»: «Solo quando lo si chiede» (spunte e pulsante «Approva e metti in "
                                                    "calendario»; casella di chi lo chiede, dalla mail quella che l'ha ricevuta) "
                                                    "oppure «Tutte le assenze approvate» (casella del capo che le approva). Serve il permesso applicativo «Calendars.ReadWrite» "
                                                    "con consenso amministratore (lo stesso del calendario dello Scadenzario). "
                                                    "Sotto l'interruttore: quanti eventi ci sono e gli ultimi errori."),
                    ("Orario, patrono e solleciti", "ore di una giornata (predefinite 8), sabato lavorativo, patrono e solleciti ai "
                                                    "capi: «Sollecita dopo» (predefinito 2 giorni) e «Ripeti il sollecito ogni» "
                                                    "(predefinito 2 giorni). Il lavoro «assenze_solleciti» gira nei giorni feriali alle 08:15. "
                                                    "Lo stesso interruttore e la stessa attesa valgono per il pulsante «Sollecita» "
                                                    "che il dipendente trova in «Le mie richieste»."),
                    ("Avviso certificato medico mancante", "acceso, ogni mattina feriale alle 08:30 (lavoro «assenze_certificato_avviso») "
                                                    "parte una mail ad assenza@ con le malattie iniziate da almeno «Avvisa se il certificato "
                                                    "manca dopo» giorni (predefinito 2) senza «Certificato arrivato». Ogni malattia compare in "
                                                    "un solo avviso; restano fuori le rifiutate e quelle iniziate da più di 30 giorni. La mail ha una riga "
                                                    "per dipendente con i periodi (giorno/mese) e il link «Segna i certificati arrivati», che apre "
                                                    "Gestione admin già filtrata sulle malattie senza certificato."),
                ]),
                ("p", "Come si conta: una richiesta a giornata intera vale i giorni lavorativi × le ore di una giornata; una "
                      "parziale vale le sue ore (al massimo una giornata). Contano le richieste non rifiutate che iniziano dopo "
                      "la data del cedolino, comprese quelle in attesa."),
            ],
        },
        {
            "id": "sharepoint",
            "titolo": "Convivenza con SharePoint",
            "blocchi": [
                ("ul", [
                    "Il lavoro «assenze_sharepoint_sync» gira ogni 5 minuti in background: manda le modifiche del portale "
                    "alla lista SharePoint e legge quelle fatte su SharePoint.",
                    "Ogni richiesta la gestisce il sistema dove è nata: quelle nate su SharePoint le approva il flusso Power Automate.",
                    "Le credenziali Graph e l'ID della lista sono nel file .env (Setup Wizard → Microsoft Graph / SharePoint).",
                ]),
            ],
        },
        {
            "id": "comandi",
            "titolo": "Comandi utili (sul server)",
            "blocchi": [
                ("def", [
                    ("sync_assenze_sharepoint --force", "rilegge tutta la lista SharePoint."),
                    ("import_assenze_xlsx <file> --dry-run", "carica uno storico da Excel; prima prova, poi senza --dry-run."),
                ]),
                ("p", "I comandi si lanciano dal terminale del Setup Wizard (Server Dashboard) o con "
                      "python django_app\\manage.py <comando> nella cartella della release."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Non so se la mia richiesta è partita",
            "perche": "dopo «Conferma invio» compare il riquadro verde «Richiesta inviata» con il numero di riferimento; "
                      "se invece resta il form con un riquadro rosso, la richiesta non è partita e il motivo è scritto lì.",
            "fare": [
                "Apri «Le mie richieste»: ogni richiesta inviata è lì con il suo stato.",
                "Non reinviarla: una richiesta identica viene comunque fermata con «Questa richiesta è già stata inviata».",
            ],
        },
        {
            "sintomo": "Non riesco a cambiare il capo reparto nella richiesta",
            "perche": "in Impostazioni → «Cambio capo reparto» c'è un elenco di persone abilitate e tu non ci sei.",
            "fare": [
                "Invia la richiesta al capo assegnato: se è assente quel giorno, l'approvazione passa al suo superiore.",
                "Chi amministra il modulo può aggiungerti in Impostazioni → «Cambio capo reparto» (serve un utente collegato all'anagrafica).",
            ],
        },
        {
            "sintomo": "Non vedo il pulsante «Malattia»",
            "perche": "in Impostazioni → «Inserimento malattia» c'è un elenco di persone abilitate e tu non ci sei.",
            "fare": [
                "Comunica la malattia all'ufficio del personale, che la inserisce per te.",
                "Chi amministra il modulo può aggiungerti in Impostazioni → «Inserimento malattia» (serve un utente collegato all'anagrafica).",
            ],
        },
        {
            "sintomo": "Un capo vede «Tutta l'azienda» e può approvare le richieste di tutti",
            "perche": "nella matrice dei permessi il suo ruolo ha «Vedere» o «Approvare» di Assenze con ambito «tutti».",
            "fare": [
                "Apri Amministrazione → Ruoli e permessi, ruolo «Caporeparto», modulo Assenze.",
                "Metti «Vedere», «Approvare», «Modificare» ed «Esportare» su «team»: il capo vede e approva solo il suo team.",
                "«Creare» può restare su «tutti»: inserire una richiesta per un altro non vuol dire approvarla.",
            ],
        },
        {
            "sintomo": "«Il mio team» della dashboard è vuoto anche se il capo ha delle persone",
            "perche": "le richieste si collegano alla persona da email o nome; se il nome sulla richiesta è scritto "
                      "diversamente dall'Anagrafica la richiesta non viene riconosciuta.",
            "fare": [
                "Controlla in Anagrafica → «Il mio team» del capo che le persone ci siano (team dall'organigramma).",
                "Controlla che nome e cognome in Anagrafica coincidano con il nome sulle richieste, oppure che la "
                "richiesta porti l'email della persona.",
            ],
        },
        {
            "sintomo": 'Il numero «In attesa» della dashboard segnalazioni è diverso dalla lista',
            "fare": [
                '«In attesa» conta tutte le richieste da decidere, con la stessa regola del badge in alto e del menu; la lista sotto ne mostra le prime e lo dice. «Gestite» conta la pagina dello storico aperta.',
            ],
        },
        {
            "sintomo": "La richiesta va al capo sbagliato",
            "perche": "il capo si ricava dall'Anagrafica, oppure il dipendente ne ha scelto un altro nella richiesta.",
            "fare": [
                "Se il dipendente ha scelto un altro capo, la richiesta va a quello: è voluto (registro «assenza_caporeparto_scelto»).",
                "Apri Anagrafica e cerca il dipendente: controlla «Area aziendale» e «Reparto».",
                "Apri l'area aziendale e controlla il «Responsabile». Se manca, vale il caporeparto del reparto.",
                "Se il dipendente è lui stesso il capo, la richiesta va al titolare del ruolo sopra il suo (in "
                "Anagrafica → Ruoli, campo «Riporta a»): controlla che quel ruolo abbia una persona assegnata.",
                "Correggi e fai reinviare la richiesta (le richieste già inviate restano al vecchio capo).",
            ],
        },
        {
            "sintomo": "Il capo riceve due mail per la stessa richiesta, o dopo l'approvazione la mailbox assenza@ non riceve nulla",
            "perche": "due regole di approvazione Assenze erano accese insieme; dalla versione successiva alla 1.6.8 "
                      "l'aggiornamento le unisce da solo nella regola «Assenze — approvazione unificata».",
            "fare": [
                "Apri Automazioni → Regole, sorgente Assenze: sull'inserimento deve essere attiva solo «Assenze — approvazione unificata».",
                "Se sono ancora attive «assenze-pa-richiesta-approvazione-caporeparto» e «au-assenze-unico-branch-per-tipo», "
                "lancia sul server merge_assenze_flows (anteprima) e poi con --apply --workers-stopped.",
                "Le richieste approvate prima della correzione possono essere rimaste «In attesa»: approvale da «Gestione admin».",
            ],
        },
        {
            "sintomo": "Con «Salta approvazione» assenza@ riceve due mail, o il caporeparto non è in copia",
            "perche": "con «Salta approvazione» parte una sola mail ad assenza@: il caporeparto del dipendente è in "
                      "copia se la richiesta l'ha inserita un'altra persona (es. l'ufficio assenze), non se l'ha "
                      "inserita lui stesso, anche quando ha il profilo Amministrazione.",
            "fare": [
                "Apri Automazioni → Regole, sorgente Assenze: «PA import - Avviso inserimento dopo approvazione» "
                "deve avere la condizione «Salta approvazione è falso».",
                "In «PA import - Inserimento con salta approvazione» ci sono due mail: una parte se «Inserita dal "
                "caporeparto» è vero (solo assenza@), l'altra negli altri casi (assenza@ + caporeparto in copia).",
                "«Inserita dal caporeparto» è vero se chi inserisce ha il profilo CAR oppure la sua email è quella "
                "del caporeparto del dipendente.",
                "Le richieste importate da SharePoint o dalla Certificazione presenze non hanno l'autore: "
                "vengono trattate come inserite dall'ufficio (caporeparto in copia).",
            ],
        },
        {
            "sintomo": "La certificazione presenza inserita dalla pagina dedicata non avvisa nessuno",
            "perche": "nasce già approvata e le regole delle automazioni non scattano: la mail parte dalla pagina "
                      "stessa al salvataggio (dal 11/11/2026).",
            "fare": [
                "Cerca l'oggetto «Certificazione presenza approvata» in Automazioni → Mail inviate.",
                "Se manca il dipendente fra i destinatari, controlla in Anagrafica l'email di notifica e che "
                "il nominativo non abbia omonimi.",
            ],
        },
        {
            "sintomo": "Con «Salta approvazione» il dipendente non riceve la mail di conferma",
            "perche": "con «Salta approvazione» il dipendente riceve «Richiesta … registrata dal … al …» solo se "
                      "l'ha inserita un caporeparto, il suo o un altro (capi e responsabili del menu «Capo reparto»). "
                      "Se la inserisce l'ufficio assenze, per esempio la malattia comunicata per telefono, no.",
            "fare": [
                "Apri Automazioni → Regole, sorgente Assenze, «PA import - Inserimento con salta approvazione»: "
                "deve esserci la mail «Avvisa il dipendente se l'ha inserita un caporeparto (suo o di un altro "
                "reparto)» con destinatario {dipendente_email} e condizione «Inserita da un caporeparto» "
                "(la aggiunge l'aggiornamento del 10/11/2026).",
                "Un caporeparto che non compare come capo o responsabile di nessun reparto o area in Anagrafica "
                "conta come ufficio assenze: aggiungilo lì.",
                "Il dipendente deve avere l'email nella richiesta: le righe senza email non ricevono niente.",
                "Le richieste che passano dall'approvazione del caporeparto avvisano il dipendente con "
                "«Richiesta … approvata/rifiutata», sia dal link nella mail sia dal portale.",
            ],
        },
        {
            "sintomo": "Per una malattia il caporeparto riceve due mail (da approvare e «Inserimento malattia»)",
            "perche": "la malattia passa dall'approvazione del caporeparto: deve arrivargli solo «Richiesta di Malattia da "
                      "approvare». La vecchia regola importata da Power Automate avvisava a ogni inserimento.",
            "fare": [
                "Apri Automazioni → Regole, sorgente Assenze: «PA import - Avviso malattia al responsabile» deve essere "
                "disattivata (lo fa l'aggiornamento del 04/11/2026). Resta attiva «Assenze — approvazione unificata».",
                "Con «Salta approvazione» il caporeparto è avvisato in copia dalla mail «Inserimento …» ad assenza@.",
            ],
        },
        {
            "sintomo": "Un capo non vede le richieste dei suoi dipendenti",
            "fare": [
                "Controlla in Anagrafica che sia il capo del dipendente (Reparti, aree e capi → Capo di ogni persona).",
                "Se il dipendente ha scelto un altro capo nella richiesta, la vede e la approva solo quello.",
                "Controlla che abbia un ruolo che apre «Assenze del reparto» (Amministrazione → Accessi, oppure Ruoli e permessi).",
                "Fagli ricaricare la pagina: il conteggio «da approvare» si aggiorna al caricamento.",
            ],
        },
        {
            "sintomo": "Le assenze non arrivano su SharePoint (o da SharePoint)",
            "perche": "la sincronizzazione gira in background con il servizio django-q (qcluster).",
            "fare": [
                "Apri Assenze → Impostazioni → «Sincronizzazione SharePoint» e leggi l'errore della coda.",
                "Apri Amministrazione → Monitoring → «Salute degli schedule» e controlla «assenze_sharepoint_sync».",
                "Se il cluster è fermo segui «Le automazioni non partono» nel Manuale di emergenza.",
                "Se l'errore parla di autorizzazione (401/403) il segreto dell'app Graph è scaduto: rinnovalo su Entra ID e aggiornalo dal Setup Wizard.",
                "Clicca «Sincronizza ora».",
            ],
        },
        {
            "sintomo": "Approvo o rifiuto dalla mail e compare «Richiesta già Elaborata»",
            "perche": "fino al 02/11/2026 un secondo clic su «Conferma» o la riapertura del link mostravano «già gestita» "
                      "anche a chi aveva appena deciso. La decisione era registrata.",
            "fare": [
                "Ora chi ha deciso rivede «Richiesta Approvata/Rifiutata»; «già Elaborata» resta solo se ha deciso un altro "
                "approvatore, e il messaggio dice chi.",
            ],
        },
        {
            "sintomo": "Una richiesta approvata dalla mail torna «In attesa»",
            "perche": "prima della correzione del 23/10/2026 l'approvazione dalla mail non arrivava a SharePoint, e la "
                      "lettura successiva da SharePoint rimetteva la richiesta in attesa.",
            "fare": [
                "Sul server lancia riallinea_assenze_decise_da_mail: mostra le richieste decise via mail ma ancora in attesa.",
                "Se l'elenco è giusto rilancialo con --applica: stato e consenso tornano quelli decisi e la modifica va a "
                "SharePoint. Le mail non ripartono.",
                "In alternativa, per una sola richiesta: Impostazioni → «Gestione admin · Tutte le assenze» → Approva.",
            ],
        },
        {
            "sintomo": "Il saldo stimato non torna con il cedolino",
            "perche": "il portale parte dall'ultimo cedolino in Anagrafica e toglie le richieste non rifiutate dopo quella data "
                      "e le chiusure che scalano le ferie.",
            "fare": [
                "Area HR → «Saldi ferie e permessi»: controlla la data «Cedolino al» del dipendente.",
                "Carica in Anagrafica il cedolino del mese più recente: le richieste fino a quella data non vengono più contate.",
                "Controlla in «Calendario aziendale» le chiusure con «Scala dalle ferie» e le ore di una giornata.",
                "Le richieste in attesa contano già: la colonna «di cui in attesa» dice quante ore sono.",
            ],
        },
        {
            "sintomo": "Le assenze approvate non compaiono nel calendario Outlook",
            "fare": [
                "Area HR → «Calendario aziendale» → «Orario, patrono e solleciti»: «Assenze approvate nel calendario Outlook» "
                "deve essere spuntato; sotto ci sono gli ultimi errori.",
                "Con «Solo quando lo si chiede» entrano solo le richieste per cui qualcuno ha usato la spunta o il pulsante "
                "«Approva e metti in calendario»; con il semplice «Approva» l'assenza non va in calendario.",
                "«manca il permesso Calendars.ReadWrite»: in Entra ID l'app del portale deve avere il permesso applicativo "
                "Calendars.ReadWrite con consenso amministratore; dopo averlo dato serve fino a un'ora (o il riavvio).",
                "«Capo senza email aziendale»: il capo deve avere l'email in anagrafica, e deve essere una casella "
                "personale con licenza (non una casella condivisa).",
                "Il lavoro gira ogni 10 minuti: Monitoring → «Salute degli schedule» → «assenze_outlook_sync».",
                "Un evento cancellato dal capo in Outlook non viene rimesso finché la richiesta non cambia.",
            ],
        },
        {
            "sintomo": "Un capo non riceve i solleciti",
            "fare": [
                "Area HR → «Calendario aziendale» → «Orario, patrono e solleciti»: «Solleciti ai capi attivi» deve essere spuntato.",
                "Il capo deve avere un'email in anagrafica: senza email la richiesta viene saltata.",
                "Oggetto della mail: «Richiesta di assenza da approvare» o «N richieste di assenza da approvare». I pulsanti "
                "«Approva» e «Rifiuta» compaiono se la richiesta di approvazione è ancora aperta (non scaduta) e il capo è fra i suoi approvatori.",
                "Le richieste nate su SharePoint non vengono sollecitate: le gestisce il flusso Power Automate.",
                "Monitoring → «Salute degli schedule»: controlla «assenze_solleciti».",
            ],
        },
        {
            "sintomo": "Con «Salta approvazione» per un'assemblea sindacale o una flessibilità assenza@ riceve due mail",
            "perche": "dalla migrazione automazioni 0032 le regole «PA import - Assemblea sindacale approvata» e "
                      "«PA import - Flessibilita approvata» non scrivono ad assenza@ quando c'è «Salta approvazione».",
            "fare": [
                "Apri le due regole: ogni mail ad assenza@ è divisa in due rami, uno con «Salta approvazione» (senza assenza@) "
                "e uno senza.",
                "Se la regola era già personalizzata la migrazione non l'ha toccata: nel log di deploy cerca «[automazioni.0032]».",
            ],
        },
        {
            "sintomo": "Il dipendente non può chiedere la flessibilità",
            "fare": [
                "Assenze → Impostazioni → «Flessibilità»: aggiungi la persona agli abilitati.",
                "Controlla che sia collegata a un'anagrafica: senza collegamento la richiesta viene rifiutata.",
                "Ricorda i limiti: tra 9 e 10 ore, massimo 2 a settimana, solo negli orari ammessi.",
            ],
        },
    ],
}
