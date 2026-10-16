GUIDA = {
    "slug": "anagrafica",
    "titolo": "Anagrafica HR",
    "area": "Persone e HR",
    "sintesi": "Dipendenti, organigramma, formazione, visite mediche, documenti e skill matrix.",
    "parole": "anagrafica dipendente dipendenti organigramma reparto area mansione formazione corso visita medica skill matrix",
    "url": "anagrafica:index",
    "prefissi": ("/anagrafica/", "/organigramma", "/rubrica"),
    "dettaglio": [
        ("Persone e account", "anagrafica:guida_persone_account"),
        ("Formazione d'aula", "anagrafica:formazione_guida"),
        ("Formazione online", "anagrafica:formazione_online_guida"),
    ],
    "uso": [
        {
            "id": "menu",
            "titolo": "Come è organizzato il menu",
            "blocchi": [
                ("def", [
                    ("Persone", "elenco dipendenti, nuovo dipendente, ex dipendenti, documenti, organigramma, reparti."),
                    ("Competenze", "formazione (corsi, sessioni, e-learning, copertura) e skill matrix."),
                    ("Salute e sicurezza", "cruscotto sicurezza, visite mediche, idoneità, mansioni di rischio. Sulle pagine "
                                           "della sezione, sotto il menu compare una seconda riga con le sue parti "
                                           "(Operatività, Sorveglianza sanitaria, Rischi e mansioni, Formazione e DPI)."),
                    ("Amministrazione", "due pagine: «Cedolini» (voci retributive del mese, con l'importazione del CSV "
                                        "dello studio paghe in fondo) e «Ferie e permessi» (saldi ferie, ROL ed ex festività, "
                                        "con l'importazione del file cedolini, anche da SharePoint, in fondo). L'import dei "
                                        "contratti è in Impostazioni → Amministrazione e import."),
                    ("Report", "reportistica componibile ed export."),
                    ("Impostazioni", "cataloghi (ruoli, mansioni di rischio, aree, reparti) e permessi HR."),
                ]),
                ("p", "Vedi solo le voci per cui hai il permesso. Le voci con un codice di modulo (es. «Processi "
                      "qualificati» = MOD.128, «Abilitazioni macchina» = MOD.187) lo spiegano al passaggio del mouse."),
            ],
        },
        {
            "id": "scheda",
            "titolo": "La scheda del dipendente",
            "blocchi": [
                ("p", "In alto trovi lo stato della persona: «In forza», «Uscita in corso» o «Cessato il …», e il semaforo "
                      "di conformità alla mansione (In regola con la mansione / Adempimenti in scadenza / Non conforme — "
                      "verificare): un clic porta al dettaglio nel Riepilogo."),
                ("p", "«🔀 Cambia mansione» apre il modulo «Nuovo spostamento» nella scheda Anagrafica, con il cursore "
                      "sulla mansione. Le azioni che chiudono o sospendono il rapporto (Avvia uscita dipendente…, "
                      "Disattiva account, Rimetti in forza) sono nel menu «Azioni ▾»: l'uscita si compila in una finestra "
                      "con motivo, data e restituzioni."),
                ("p", "Le schede DPI, Visite mediche, Documenti e Asset mostrano accanto al nome quante voci contengono."),
            ],
        },
        {
            "id": "la-mia-scheda",
            "titolo": "La mia scheda (per ogni dipendente)",
            "blocchi": [
                ("p", "Dal menu utente in alto (o da «Il mio profilo») «La mia scheda» mostra solo i tuoi dati: ferie, ROL, "
                      "ex festività e permessi dall'ultimo cedolino; le tue visite mediche con scadenza e giudizio di "
                      "idoneità (il referto e le prescrizioni restano all'ufficio HR); i corsi completati con il PDF "
                      "dell'«Attestato»; le voci del cedolino (ultimi sei mesi importati); le ultime richieste DPI, con "
                      "«Tutti i miei DPI»."),
                ("nota", "Se dice «Account non collegato», chiedi all'ufficio HR di collegare il tuo utente alla tua scheda."),
            ],
        },
        {
            "id": "il-mio-team",
            "titolo": "Il mio team (capo reparto)",
            "blocchi": [
                ("p", "Anagrafica → Persone → «Il mio team» (anche dalla Dashboard reparto delle Assenze) elenca le persone "
                      "di cui sei responsabile: quelle della tua area aziendale, o del tuo reparto se l'area non ha un "
                      "responsabile. È la stessa regola che decide a chi arrivano le richieste di ferie."),
                ("p", "Per ognuno vedi area, mansione e il semaforo di conformità alla mansione; prima chi non è conforme, "
                      "poi chi ha adempimenti in scadenza. Nessun dato sanitario. Il nome apre la scheda solo se hai il "
                      "permesso di vederla."),
                ("nota", "Se l'elenco è vuoto ma sei capo, chiedi all'HR di indicarti come responsabile dell'area o "
                         "caporeparto nel catalogo Reparti; se dice «Account non collegato», il tuo utente va collegato "
                         "alla tua scheda."),
            ],
        },
        {
            "id": "organigramma-viste",
            "titolo": "Organigramma: una pagina, quattro viste",
            "blocchi": [
                ("def", [
                    ("Elenco", "reparti, aree, capi e persone in forza."),
                    ("Albero", "la gerarchia dei ruoli operativi («riporta a»)."),
                    ("Diagramma", "una tessera per posizione, da stampare."),
                    ("Rischi", "i gruppi omogenei del DVR per mansione di rischio."),
                ]),
                ("p", "Il selettore in alto passa da una vista all'altra; i collegamenti salvati continuano a funzionare."),
            ],
        },
        {
            "id": "scadenzario",
            "titolo": "Scadenzario: filtrare per periodo",
            "blocchi": [
                ("p", "Oltre a tipo, stato e reparto, il menu «Periodo» mostra solo le scadenze di «Questo mese», del "
                      "«Prossimo mese» o di un «Intervallo…» (dal / al, anche una sola data). Con un periodo scelto il "
                      "filtro di stato non conta; l'export Excel/PDF dei risultati filtrati usa lo stesso periodo."),
            ],
        },
        {
            "id": "cercare",
            "titolo": "Trovare un dipendente",
            "blocchi": [
                ("passi", [
                    "Apri Anagrafica → «Persone».",
                    "Scrivi cognome o nome nella ricerca: l'elenco si filtra mentre scrivi.",
                    "Clicca la riga per aprire la scheda.",
                ]),
                ("p", "I nomi sono scritti COGNOME NOME in maiuscolo. Sotto il nome vedi i ruoli che la persona ricopre."),
                ("p", "Ricerca: la casella della dashboard di Anagrafica cerca in tutto il modulo (persone, posizioni e "
                      "candidati, corsi, tipi di qualifica, mansioni di rischio, tipi di visita, modelli di report). Ogni "
                      "sezione ha la sua casella, che cerca solo lì: in Qualifiche e Visite, scrivendo un nome, vedi le "
                      "qualifiche o le scadenze delle visite di quella persona (mai l'esito). Mentre scrivi compare una "
                      "tendina; Invio apre tutti i risultati, dove puoi cambiare dove cercare. Vedi solo i risultati delle "
                      "sezioni che puoi aprire. Servono almeno due caratteri."),
            ],
        },
        {
            "id": "pagine-sezione",
            "titolo": "Le pagine d'ingresso delle sezioni",
            "blocchi": [
                ("p", "Ogni sezione si apre con lo stesso schema: in alto i numeri di oggi (quelli cliccabili aprono "
                      "l'elenco già filtrato), poi una scheda per ogni «oggetto» della sezione con una barra colorata, "
                      "in basso l'elenco di lavoro e a destra le altre pagine della sezione."),
                ("def", [
                    ("Persone", "una scheda per reparto con l'organico per tipo di contratto; il clic filtra l'elenco."),
                    ("Ingressi (Cruscotto recruiting)", "una scheda per posizione aperta con i candidati per fase dell'iter; sotto, gli onboarding aperti."),
                    ("Formazione", "una scheda per corso obbligatorio con la copertura e la prossima sessione."),
                    ("Qualifiche", "una scheda per tipo di qualifica: valide, entro 60 e 30 giorni, scadute; il clic apre lo scadenzario del tipo."),
                    ("Salute e sicurezza", "una scheda per mansione di rischio; con il permesso HR la barra dice quante persone sono in regola con tutti gli obblighi."),
                    ("Visite mediche", "una scheda per tipo di visita: in regola, entro 60 giorni, scadute, senza visita. Mai esiti o giudizi."),
                    ("Amministrazione", "una scheda per flusso (retribuzioni, ferie e permessi dal file cedolini, contratti) con righe abbinate e scartate dell'ultimo import; il clic porta alla sezione «Importazione» della pagina."),
                    ("Report", "una scheda per modello con le generazioni degli ultimi 30 giorni e i pulsanti Genera, Modifica, Duplica."),
                ]),
                ("p", "Sopra le schede, i pulsanti filtrano (per categoria, livello di rischio, norma…) e cambiano l'ordine. "
                      "Le schede contano solo i dati che il tuo profilo può vedere."),
            ],
        },
        {
            "id": "dettaglio",
            "titolo": "Le guide di dettaglio",
            "blocchi": [
                ("p", "Per nuovo dipendente, account, uscita dall'azienda e formazione ci sono guide passo passo dedicate: "
                      "i collegamenti sono in cima a questa pagina."),
            ],
        },
    ],
    "admin": [
        {
            "id": "organizzazione",
            "titolo": "Reparti, aree aziendali e responsabili",
            "blocchi": [
                ("ul", [
                    "Ogni dipendente sta in un'area aziendale; ogni area sta in un reparto.",
                    "Il responsabile dell'area è chi approva ferie e permessi dei suoi dipendenti; se manca, li approva il caporeparto.",
                    "Lo stesso collegamento decide chi vede i dati del proprio team in Assenze, DPI, Ticket e negli altri moduli.",
                    "Il «Caporeparto» nella scheda del dipendente si aggiorna da solo quando si salva il reparto o l'area: "
                    "il responsabile dell'area vince sul caporeparto, e il caporeparto non risulta mai capo di sé stesso.",
                    "Uno spostamento che cambia il ruolo (senza «Ruolo in parallelo») chiude il ruolo di prima il giorno "
                    "prima della decorrenza: resta nello storico dei ruoli come concluso, ma non dà più permessi né posto nel team.",
                    "Dopo uno spostamento, se la persona è ancora in lista su mansioni del Mansionario di un altro reparto o "
                    "previste per ruoli che non ricopre più, la card «Spostamenti organizzativi» le elenca in «Mansioni "
                    "lavorative da rivedere»: «Togli dalla lista» la toglie (lo storico resta). Finché resta in lista, "
                    "restano attive anche le mansioni di rischio che ne derivano.",
                ]),
                ("nota", "Prima di cambiare responsabile o area di un gruppo di persone, avvisa: le richieste già inviate restano al vecchio responsabile."),
            ],
        },
        {
            "id": "cataloghi",
            "titolo": "Cataloghi e impostazioni",
            "blocchi": [
                ("p", "Anagrafica → «Impostazioni» raccoglie in un'unica pagina: ruoli (catalogo unico, con «riporta a»), "
                      "mansioni di rischio, aree, reparti, tipi documento, campi di ingresso e uscita, permessi HR."),
                ("p", "La scheda «Mansioni» mostra le mansioni di rischio (con «Catalogo completo →» per livello di rischio "
                      "e requisiti) e il numero di mansioni lavorative, con «Apri il Mansionario →»: le mansioni lavorative "
                      "(macchine e processi della skill matrix) si gestiscono lì. Le ultime voci della barra (E-learning, "
                      "Viste elenco dipendenti, Amministrazione e import) aprono altre pagine."),
                ("p", "Un ruolo del catalogo può essere collegato a ruoli del portale (Amministrazione → «Ruoli e permessi», "
                      "matrice, «Dall'organigramma»): chi ricopre il ruolo riceve quei permessi da solo e li perde quando "
                      "lascia il ruolo. Assegnare o togliere un ruolo qui cambia quindi anche cosa la persona può fare nel portale."),
                ("p", "Fra gli ambiti dei ruoli c'è «Incarichi»: gestione del personale, gestione della formazione, auditor "
                      "interni, docenti. Sono ruoli che si aggiungono alla posizione della persona."),
                ("p", "Referti clinici: con i ruoli del portale attivi li apre solo chi ha l'azione «Referti clinici» delle "
                      "visite mediche (nei ruoli pronti, Gestione personale). Capi reparto e preposti vedono idoneità, "
                      "limitazioni e scadenze del loro team, non il referto."),
            ],
        },
        {
            "id": "visite-richiamo",
            "titolo": "Visite: il richiamo scritto dal medico",
            "blocchi": [
                ("p", "Nella registrazione o modifica di una visita, «Richiamo indicato dal medico» è la data entro cui il "
                      "medico competente vuole rivedere la persona. Se c'è, la scadenza della visita è quella (con la nota "
                      "«Scadenza indicata dal medico competente.») e il ricalcolo notturno non la cambia più; vuoto = "
                      "data della visita + periodicità del tipo, anticipata se la mansione chiede di più. Il richiamo deve "
                      "essere dopo la data della visita. L'import da Excel con una «data richiamo» diversa dalla durata "
                      "del tipo la scrive qui."),
                ("p", "L'export Excel dello scadenzario visite contiene la colonna «Prescrizioni» solo per chi può aprire "
                      "i referti clinici."),
            ],
        },
        {
            "id": "omonimi",
            "titolo": "Anagrafiche doppie e omonimi",
            "blocchi": [
                ("p", "Due righe con lo stesso nome e cognome vengono considerate la stessa persona (in elenchi, report e "
                      "scadenze) solo se codice fiscale e matricola non dicono il contrario: con CF o matricola diversi "
                      "restano due persone. Una riga senza CF né matricola si unisce alla prima compatibile."),
            ],
        },
        {
            "id": "retention",
            "titolo": "Conservazione dei dati (retention)",
            "blocchi": [
                ("p", "Ogni lunedì alle 06:30 il portale conta, senza cancellare nulla, i documenti dei dipendenti cessati "
                      "oltre gli anni di conservazione e i candidati chiusi (non idonei, rinunce, annullati) fermi da "
                      "oltre 24 mesi. Se ce ne sono apre in Monitoraggio la segnalazione «Retention HR» con i soli "
                      "numeri; quando non ce ne sono più la chiude."),
                ("p", "Per cancellare: Impostazioni → «Conservazione dei dati» (solo amministratori dell'anagrafica). "
                      "La pagina elenca i documenti dei cessati oltre la conservazione e i candidati chiusi da oltre 24 "
                      "mesi; scegli le righe, scrivi ELIMINA e conferma. I documenti vengono eliminati (file compreso); i "
                      "candidati resi anonimi: spariscono nome, contatti, note e storico delle modifiche, restano stato, "
                      "date ed esiti per le statistiche del recruiting. Ogni riga è ricontrollata al momento e va nel "
                      "registro attività. Un dipendente in forza non perde mai documenti."),
            ],
        },
        {
            "id": "capo-team",
            "titolo": "Capo e team: la regola unica e «Coerenza capi»",
            "blocchi": [
                ("p", "Il capo di una persona si cerca in quest'ordine: 1) eccezione indicata a mano sulla persona; "
                      "2) responsabile dell'area aziendale; 3) caporeparto del reparto; 4) organigramma: chi ha un ruolo "
                      "sopra quello della persona («riporta a») e lavora nella stessa area, poi nello stesso reparto, poi "
                      "chi non ha un reparto (ruolo trasversale); se nessuno, si sale di livello: chi guida un altro reparto "
                      "non diventa mai il capo. In cima vale la persona unica dell'ultimo livello. Nessuno è capo di sé stesso. "
                      "Il team è l'inverso: le persone di cui sei il capo, e i loro team."),
                ("p", "Organigramma → «Coerenza capi» (amministratori dell'anagrafica) mostra per ogni persona il capo di oggi "
                      "(quello che approva assenze e DPI), il capo con la regola unica e come è stato trovato, chi ha oggi la "
                      "persona nel team dei permessi. Filtri: «Il capo cambia», «Senza capo», «Più candidati», «Eccezioni»."),
                ("p", "«Indica un'eccezione» fissa il capo di una persona (distacco, interim…): serve il motivo, la modifica "
                      "va nel registro attività. «Nessuna eccezione» torna alla regola."),
                ("p", "Il pannello «Regola unica» in cima alla pagina la accende o la spegne per tutto il portale (serve "
                      "spuntare «Ho controllato i capi che cambiano»). Accesa: il team dei permessi, l'approvatore e il "
                      "team del capo nelle assenze, l'approvatore delle richieste DPI, i solleciti dei corsi online e il "
                      "«Caporeparto» della scheda (e del riepilogo mattutino) seguono la colonna «Capo con la regola unica». "
                      "Spenta: ogni modulo torna alla regola di prima (area → reparto; per i permessi, la gerarchia dei ruoli)."),
                ("nota", "Prima di accenderla guarda i filtri «Il capo cambia» e «Senza capo»: chi resta senza capo non ha "
                         "nessuno che gli approvi le assenze."),
            ],
        },
        {
            "id": "struttura-mansionario",
            "titolo": "Struttura ruoli → mansioni → competenze: editor, Excel e ruoli in blocco",
            "blocchi": [
                ("p", "Mansionario → «Struttura e import» (amministratori dell'anagrafica) mostra ogni ruolo con le sue "
                      "mansioni. Clic su una mansione: si apre l'editor con nome, ruoli, mansioni di rischio, reparto (solo "
                      "per i processi; per le macchine vale quello della macchina), «Mansione attiva» e la tabella delle "
                      "competenze (livello minimo I/L/U/O, bloccante, corso, qualifica, abilitazione MOD.128, ordine). Le "
                      "righe vuote in fondo aggiungono competenze, «Togli» le spegne. «Salva la mansione» registra tutto "
                      "insieme: se una riga è sbagliata non si salva niente e il messaggio dice quale. «Nuova mansione "
                      "(processo)» crea un processo; le macchine nascono dalla skill matrix."),
                ("passi", [
                    "«Scarica Excel»: fogli Ruoli, Mansioni e Competenze con i dati di oggi, più le istruzioni.",
                    "Correggi o completa il file. Cella vuota = il dato non cambia; NO in «Attiva»/«Attivo» spegne. "
                    "Più ruoli o rischi nella stessa cella si separano con ; e sostituiscono l'elenco di oggi.",
                    "Caricalo in «Importa ed esporta in Excel» e premi «Prova»: vedi per foglio le righe nuove, "
                    "modificate, invariate e scartate con il motivo. Non si salva niente.",
                    "«Applica» registra le righe buone; quelle scartate si correggono nel file e si ricaricano.",
                ]),
                ("p", "L'import non cancella mai e non crea mansioni di rischio, reparti, ambiti, corsi, qualifiche, "
                      "processi MOD.128 o macchine: un nome che non esiste è un errore della riga. La colonna «Chiave» "
                      "identifica la mansione; una riga senza chiave si abbina per nome, e un nome nuovo crea un processo. "
                      "Un «Riporta a» che creerebbe un giro nella gerarchia non si applica e compare negli avvisi. Una "
                      "competenza tolta e poi riaggiunta con lo stesso nome riprende i livelli già registrati."),
                ("p", "Ruoli → «Cambio ruoli in blocco»: filtra le persone (reparto, ruolo che hanno, nome), spuntale e "
                      "scegli: «Aggiungi il ruolo» (si somma; diventa principale solo se la persona non ne ha uno), "
                      "«Sostituisci il ruolo principale» (registra uno spostamento con la data: il ruolo di prima si chiude "
                      "il giorno precedente, reparto e mansione restano) o «Chiudi il ruolo» (la data è l'ultimo giorno, "
                      "di oggi o passata; se era il principale subentra il primo ruolo rimasto). «Anteprima» mostra cosa "
                      "succede a ciascuno senza salvare; «Registra» lo fa, al massimo 300 persone alla volta. Ogni "
                      "operazione va nel registro attività."),
                ("nota", "Un ruolo di un altro organigramma (per esempio ISO 45001) non diventa il ruolo principale: "
                         "si aggiunge con «Aggiungi il ruolo»."),
            ],
        },
        {
            "id": "mansioni-rischio",
            "titolo": "Mansioni di rischio",
            "blocchi": [
                ("p", "Il catalogo «Mansioni di rischio» (Salute e sicurezza → Rischi e mansioni) contiene i gruppi omogenei del "
                      "DVR, con gli stessi nomi usati dal medico competente nell'elenco idoneità (es. «ADDETTO MACCHINE UTENSILI»)."),
                ("def", [
                    ("Requisiti", "per ogni mansione di rischio: DPI, visite del protocollo sanitario, livello di rischio ASR "
                                  "(8, 12 o 16 ore di formazione), revisione e data del DVR. Le schede di sicurezza si collegano "
                                  "dalla scheda del prodotto chimico."),
                    ("Persone", "la mansione di rischio della persona è il campo «Mansione di rischio» della sua scheda. "
                                "Chi l'ha vuota non compare nell'organigramma rischi e non riceve DPI, visite e SDS dovute."),
                    ("Organigramma rischi", "persone raggruppate per mansione di rischio, per RSPP e medico; in testa il numero "
                                            "di dipendenti ancora senza mansione."),
                    ("Visita mancante", "in fondo al catalogo si sceglie cosa succede se alla decorrenza di uno spostamento "
                                        "manca la visita del cambio mansione."),
                ]),
                ("nota", "La mansione lavorativa (la macchina o il processo su cui si lavora) è un'altra cosa: "
                         "si gestisce nel Mansionario."),
            ],
        },
        {
            "id": "mansionario",
            "titolo": "Mansionario",
            "blocchi": [
                ("p", "Competenze → Skill Matrix → «Mansionario». La struttura è ruolo → mansione → persone. Una mansione "
                      "è una macchina o un processo: sono le colonne della skill matrix MOD.187."),
                ("def", [
                    ("Elenco per ruolo", "la pagina mostra un blocco per ruolo con le sue mansioni; si apre e si chiude "
                                         "cliccando il nome del ruolo («Apri tutti» / «Chiudi tutti» per tutti insieme). "
                                         "Una mansione che serve a più ruoli compare sotto ciascuno. In fondo, in "
                                         "arancione, «Da collegare a un ruolo» raccoglie le mansioni senza ruolo."),
                    ("Cerca e filtri", "la casella «Cerca» trova per nome della mansione, reparto, ruolo o mansione di "
                                       "rischio; «Macchine» e «Processi» filtrano per tipo. I riquadri «Senza operativi», "
                                       "«Senza ruolo» e «Senza mansione di rischio» filtrano le schede (clic di nuovo o "
                                       "«Mostra tutto» per togliere il filtro); «Persone non abilitate» e «In "
                                       "addestramento» aprono le Lacune di competenza."),
                    ("Scheda della mansione", "la barra conta le persone in lista per livello: verde autonomo o esperto, "
                                              "giallo intermedio, grigio in formazione. Il numero grande sono gli operativi "
                                              "(livello pari o sopra la soglia della skill matrix). Dentro un ruolo, prima "
                                              "le mansioni meno coperte."),
                    ("Pagina della mansione", "in testa tipo, reparto, ruoli e mansioni di rischio, poi i contatori "
                                              "abilitati · in addestramento · non abilitati · da valutare. Sotto, tre "
                                              "schede: «Persone», «Competenze richieste» e «Impostazioni» (il pulsante "
                                              "«Modifica» porta a quest'ultima)."),
                    ("Ruoli", "ruoli sotto cui sta la mansione: di norma uno. Si scelgono in «Impostazioni»."),
                    ("Reparto", "per una macchina è quello dell'asset; per un processo si sceglie in «Impostazioni»."),
                    ("Mansioni di rischio", "quelle che comporta chi la svolge: da lì vengono DPI, visite e schede di "
                                            "sicurezza. Una mansione senza mansione di rischio è segnalata."),
                    ("Persone", "nella scheda «Persone», riquadro «Aggiungi una persona alla mansione»: si scrive in "
                                "«Cerca» per restringere l'elenco, si sceglie la persona e il «Livello di partenza», poi "
                                "«Assegna». «Togli» chiede conferma. Ogni modifica resta nello storico delle abilitazioni."),
                    ("Da valutare", "chi è in lista su una mansione con competenze ma non ha ancora un livello su "
                                    "nessuna di esse: il pulsante «Valuta» è evidenziato. Finché non è valutato non "
                                    "risulta abilitato."),
                    ("Competenze", "ogni mansione ha le sue competenze (es. set-up, programmazione), ciascuna con un "
                                   "livello minimo I/L/U/O, il segno «bloccante» e, se serve, un requisito formale: corso "
                                   "valido, qualifica o patentino valido, abilitazione MOD.128 operativa. Senza il "
                                   "requisito la persona non supera «I – in formazione» su quella competenza. Nella "
                                   "scheda «Competenze richieste»: «Aggiungi competenza», «Modifica» (si corregge sulla "
                                   "riga, poi «Salva modifiche») e «Togli» (i livelli già registrati restano)."),
                    ("Valuta", "per ogni persona si indica il livello su ogni competenza. Il livello sulla mansione è "
                               "la media delle competenze, arrotondata per difetto, e mai sopra la competenza bloccante "
                               "più bassa; si aggiorna da solo anche nella skill matrix."),
                    ("Esito", "Abilitato (livello pari o sopra la soglia, nessuna competenza sotto il minimo, requisiti "
                              "presenti) · In addestramento (manca solo livello) · Non abilitato (manca un requisito "
                              "formale o una competenza bloccante è sotto il minimo: il livello sulla mansione resta "
                              "sotto la soglia, quindi la persona non conta tra gli operativi). Una mansione senza "
                              "competenze usa il livello assegnato a mano."),
                    ("Persona", "cliccando il nome si apre la scheda della persona nel Mansionario: mansioni con esito "
                                "e cosa manca, reparto principale (mansione con il livello più alto, poi la più vecchia) "
                                "e le mansioni di rischio che ne derivano."),
                    ("Lacune di competenza", "elenco di chi non è abilitato e cosa manca, filtrabile ed esportabile in "
                                             "CSV: base per il piano formativo e per il refresh dei caporeparto."),
                    ("Refresh caporeparto", "la qualità, da «Refresh caporeparto» (Scadenzario refresh), avvia il "
                                            "refresh di un reparto con «Avvia refresh»: il caporeparto riceve notifica "
                                            "ed email. Con la campagna aperta compare «Sollecita», che gli manda un "
                                            "promemoria. Le note del caporeparto si leggono sotto la data della campagna."),
                    ("Pagina del refresh", "il caporeparto vede tutte le persone in lista sulle mansioni del reparto, "
                                           "macchine e processi. Per ognuna conferma o cambia il livello, oppure la "
                                           "toglie; dove la mansione ha competenze usa «Valuta competenze» e torna al "
                                           "refresh. Può aggiungere una persona a una mansione del reparto, lasciare una "
                                           "nota per la qualità e chiudere la campagna con «Ho finito»."),
                    ("Coerenza con la mansione di rischio", "in fondo alla pagina del refresh: chi ha in anagrafica "
                                                            "una mansione di rischio diversa da quelle delle mansioni "
                                                            "che svolge, o non ne ha, e le mansioni del reparto senza "
                                                            "mansione di rischio. Serve all'RSPP; si corregge "
                                                            "dall'anagrafica o dalla scheda della mansione."),
                ]),
                ("nota", "Le mansioni di rischio di una persona sono quella scritta in anagrafica (del medico competente) "
                         "più quelle delle mansioni che svolge, più le aggiunte individuali e meno le esclusioni. "
                         "Contano tutte per DPI, visite, formazione e schede di sicurezza: assegnare una persona a una "
                         "mansione le porta subito i suoi obblighi; nessuna mansione toglie quella in anagrafica."),
            ],
        },
        {
            "id": "account",
            "titolo": "Dipendente e account non sono la stessa cosa",
            "blocchi": [
                ("ul", [
                    "Il dipendente è la scheda HR (anagrafica). L'account è l'utente con cui si entra nel portale.",
                    "I due vanno collegati: senza collegamento la persona non vede i propri dati (ferie, DPI, formazione).",
                    "L'email di notifica in anagrafica è quella a cui arrivano le mail del portale: può essere diversa dall'email di accesso.",
                ]),
            ],
        },
        {
            "id": "comandi",
            "titolo": "Comandi utili (sul server)",
            "blocchi": [
                ("def", [
                    ("normalizza_nomi_dipendenti", "riscrive i nomi nel formato COGNOME NOME maiuscolo."),
                    ("pulisci_scadenze_hr", "ricalcola le scadenze di formazione e visite."),
                    ("report_mansioni_catalogo", "sola lettura: per ogni mansione scritta nelle schede dice se "
                                                 "corrisponde al catalogo (esatta, per nome, simile, assente). "
                                                 "--report file.csv per l'elenco. Da guardare prima di collegare "
                                                 "le mansioni al catalogo."),
                    ("cleanup_expired_documents", "documenti dei cessati oltre la conservazione: in prova di default, "
                                                  "--apply per cancellare. Il report settimanale in Monitoraggio dice "
                                                  "quanti sono."),
                    ("report_ruoli_disallineati", "elenca i ruoli diversi tra anagrafica e account."),
                    ("importa_mansioni_idoneita", "assegna la mansione di rischio ai dipendenti che non l'hanno, dall'elenco "
                                                  "idoneità del medico (codice fiscale e «MANSIONE DI RISCHIO»). In prova di "
                                                  "default, --commit per scrivere."),
                    ("proponi_mansioni_rischio", "collega a ogni mansione del Mansionario ancora senza mansione di "
                                                 "rischio quella più frequente tra le persone in lista (almeno metà di "
                                                 "loro, a pari merito niente). Da lanciare dopo importa_mansioni_idoneita. "
                                                 "In prova di default, --commit per scrivere, --report file.csv per "
                                                 "l'elenco completo; le mansioni rimaste senza si collegano a mano."),
                ]),
                ("p", "Prima di ogni comando che scrive, lancialo in prova (--dry-run) se l'opzione esiste."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona entra nel portale ma non vede i suoi dati",
            "perche": "il suo account non è collegato alla sua scheda anagrafica.",
            "fare": [
                "Apri la scheda del dipendente in Anagrafica.",
                "Nella parte account collega l'utente del portale (cerca per nome utente o email).",
                "Fai uscire e rientrare la persona.",
            ],
        },
        {
            "sintomo": "Le mail del portale non arrivano a una persona",
            "fare": [
                "Controlla nella scheda l'«email di notifica».",
                "Amministrazione → «Log notifiche»: verifica se la notifica è partita e a quale indirizzo.",
            ],
        },
        {
            "sintomo": "Una persona non riceve le schede di sicurezza o non compare nell'organigramma rischi",
            "perche": "la sua scheda non ha la mansione di rischio, o il nome non coincide con una voce del catalogo.",
            "fare": [
                "Apri la scheda: il campo «Mansione di rischio» deve avere un valore del catalogo «Mansioni di rischio».",
                "Per molti dipendenti insieme usa il comando importa_mansioni_idoneita (prima in prova).",
            ],
        },
        {
            "sintomo": "Due colleghi con lo stesso nome compaiono come una persona sola",
            "perche": "nessuna delle due schede ha codice fiscale o matricola, quindi il portale non li distingue.",
            "fare": [
                "Inserisci il codice fiscale (scheda → Anagrafica civile) o la matricola in entrambe le schede.",
                "Ricarica la pagina: con codici diversi restano due persone.",
            ],
        },
        {
            "sintomo": "La scadenza di una visita non è quella scritta dal medico",
            "fare": [
                "Apri la visita → «Modifica visita» e scrivi la data in «Richiamo indicato dal medico».",
                "Salva: da quel momento la scadenza è quella, anche dopo il ricalcolo notturno.",
            ],
        },
        {
            "sintomo": "Scadenze di formazione o visite sbagliate",
            "fare": [
                "Controlla la mansione di rischio e i ruoli della persona: le scadenze dovute dipendono da lì.",
                "Lancia pulisci_scadenze_hr dal terminale del Setup Wizard.",
            ],
        },
    ],
}
