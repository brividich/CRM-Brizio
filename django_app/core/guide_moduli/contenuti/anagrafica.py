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
                ("p", "In fondo, «I tuoi dati personali»: «⬇ Scarica i miei dati» scarica un file ZIP con tutto quello che "
                      "il portale ha su di te (dati.json, una tabella CSV per sezione da aprire con Excel e LEGGIMI.txt): "
                      "dati anagrafici e bancari, rapporto di lavoro, figli a carico, visite (tipo, date, giudizio), "
                      "formazione, voci del cedolino, saldi, assenze confermate, elenco dei documenti, DPI e le tue "
                      "segnalazioni. Non contiene i file dei documenti né prescrizioni e note del medico: si chiedono all'ufficio HR."),
                ("p", "«Segnala un dato errato»: scegli che dato riguarda, scrivi cosa è sbagliato e come dovrebbe essere, "
                      "invia. L'ufficio HR risponde entro un mese; la risposta arriva come notifica e resta nella tabella "
                      "sotto il modulo («In lavorazione» / «Chiusa»)."),
                ("nota", "Se dice «Account non collegato», chiedi all'ufficio HR di collegare il tuo utente alla tua scheda."),
            ],
        },
        {
            "id": "rettifiche",
            "titolo": "Richieste di rettifica (ufficio HR)",
            "blocchi": [
                ("p", "Impostazioni → «Richieste di rettifica» (HR e amministratori dell'anagrafica) elenca le segnalazioni "
                      "dei dipendenti fatte da «La mia scheda», con la data entro cui rispondere (un mese, in rosso se "
                      "scaduta). Correggi il dato nella scheda del dipendente (il nome è un link), poi scrivi la risposta "
                      "e «Chiudi e rispondi»: il dipendente riceve la notifica. Apertura e chiusura vanno nel registro attività."),
                ("p", "Per ricevere una mail a ogni nuova richiesta, imposta la casella dell'ufficio HR nella SiteConfig "
                      "«anagrafica_rettifiche_email». La mail non contiene il testo della segnalazione."),
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
            "id": "leggi-attestato",
            "titolo": "Registrare l'attestato di un ente esterno",
            "blocchi": [
                ("p", "Formazione → «Leggi un attestato» (serve il permesso di modifica della formazione): carichi il PDF o la foto, "
                      "«Leggi il documento» propone dipendente, corso, date, ore, ente e numero; controlli e premi «Registra il completamento». "
                      "Il corso va a libretto e nello scadenzario, il file nel box documenti. Passi e limiti nella guida «Formazione d'aula»."),
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
                    ("Cedolini", "solo i cedolini: ultima mensilità, mensilità in archivio, dipendenti, righe e le righe dell'ultimo import (arancione se ne ha scartate; il clic porta alla sezione «Importazione»), poi la vista globale. Contratti e scadenze stanno nello Scadenzario, i saldi in «Ferie e permessi»."),
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
            "id": "mod128-attrezzature",
            "titolo": "MOD.128: attrezzature dei processi qualificati",
            "blocchi": [
                ("p", "Nel dettaglio di un processo qualificato la sezione «Attrezzature» elenca gli asset usati nel "
                      "processo. Per collegarne uno scrivi il tag o il numero interno e premi «＋ Collega "
                      "attrezzatura»; «Scollega» lo toglie. Serve il permesso di gestione MOD.128. Per un processo "
                      "PART 145 compaiono anche gli asset con «Rientra in PART 145» (si tolgono dal form dell'asset)."),
                ("p", "Quando un'attrezzatura del processo cambia stato arriva una mail agli stessi destinatari dei "
                      "timbri sospesi. Il riepilogo per l'audit è il Dossier PART 145 del modulo Asset."),
                ("p", "Un processo speciale autorizzato per le attività Part 145 (es. i processi con DQP "
                      "dell'Annesso 2 dell'accordo con l'organizzazione di manutenzione) va marcato con la casella "
                      "«Rientra nel perimetro Part 145» nel form del processo: così entra nel Dossier PART 145 con "
                      "persone, attrezzature e scadenze. Il contratto quadro si registra come requisito del processo "
                      "PART 145 di tipo «Contratto / accordo», con la sua scadenza: compare nelle scadenze del "
                      "Dossier e nella mail settimanale «[PART 145] Scadenze entro 90 giorni»."),
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
                ("p", "Negli import vale la stessa regola. L'import dipendenti crea una scheda nuova per un omonimo con "
                      "un codice fiscale diverso (prima aggiornava la scheda del collega). Gli import di retribuzioni e "
                      "contratti abbinano per codice fiscale; per nome solo se il nome è unico in anagrafica e quella "
                      "persona non ha già un codice fiscale: altrimenti la riga resta «non abbinata» negli scarti, da "
                      "sistemare inserendo il codice fiscale nella scheda giusta."),
            ],
        },
        {
            "id": "retention",
            "titolo": "Conservazione dei dati (retention)",
            "blocchi": [
                ("p", "Ogni lunedì alle 06:30 il portale conta, senza cancellare nulla, i documenti dei dipendenti cessati "
                      "oltre gli anni di conservazione, i dipendenti cessati da oltre 10 anni che hanno ancora dati "
                      "personali da togliere e i candidati chiusi (non idonei, rinunce, annullati) o tenuti «in database» "
                      "fermi da oltre 24 mesi. Se ce ne sono apre in Monitoraggio la segnalazione «Retention HR» con i "
                      "soli numeri; quando non ce ne sono più la chiude."),
                ("p", "Per cancellare: Impostazioni → «Conservazione dei dati» (solo amministratori dell'anagrafica). "
                      "Scegli le righe, scrivi ELIMINA e conferma. Ogni riga è ricontrollata al momento e va nel "
                      "registro attività, senza i dati tolti. Un dipendente in forza non perde mai nulla."),
                ("ul", [
                    "Documenti dei dipendenti cessati: eliminati, file compreso.",
                    "Dipendenti cessati da oltre 10 anni, «Ripulisci»: si tolgono dati civili e bancari, recapiti "
                    "privati, foto, figli a carico, taglie e telefono, voci retributive e saldi del cedolino, "
                    "prescrizioni e note delle visite. Restano nome, rapporto di lavoro, formazione, DPI e visite con "
                    "date ed esito: è lo storico. Chi è stato riassunto dopo la cessazione non compare.",
                    "Candidati: resi anonimi. Spariscono nome, contatti, note e storico delle modifiche; restano "
                    "stato, date ed esiti per le statistiche del recruiting. Gli assunti non compaiono mai.",
                ]),
                ("p", "I termini (10 anni per i cessati, 24 mesi per i candidati) sono la proposta del 21/10/2026, da "
                      "confermare con il DPO."),
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
                      "mansioni. Clic su una mansione: si apre l'editor con le pastiglie di completezza (ruolo, reparto, "
                      "mansione di rischio, competenze, persone), nome, ruoli e mansioni di rischio (elenchi con ricerca: "
                      "si spunta, niente Ctrl+clic), reparto (solo per i processi; per le macchine vale quello della "
                      "macchina), «Mansione attiva» e la tabella delle competenze (livello minimo I/L/U/O, bloccante, "
                      "corso, qualifica, abilitazione MOD.128, ordine). «Aggiungi competenza» aggiunge una riga, «Togli» "
                      "spegne. Finché non salvi compare «● modifiche non salvate». «Salva la mansione» registra tutto "
                      "insieme: se una riga è sbagliata non si salva niente e il messaggio dice quale."),
                ("passi", [
                    "«Nuova mansione» (dalla Struttura o dalla home del Mansionario) apre la procedura guidata in cinque "
                    "passi: 1 Nome (avvisa se esiste già) · 2 Ruoli e reparto · 3 Mansioni di rischio · 4 Competenze "
                    "(nome, livello minimo, bloccante e un requisito formale: corso, qualifica o MOD.128; «Aggiungi "
                    "competenza» per altre righe) · 5 Riepilogo, con l'elenco di cosa manca.",
                    "«Avanti»/«Indietro» o il clic sul numero del passo spostano tra i passi; si va avanti solo con un "
                    "nome valido. Si crea tutto insieme con «Crea la mansione»: se qualcosa non va non si crea niente e "
                    "si torna al passo da correggere con i dati già scritti.",
                    "Dopo la creazione si apre la scheda della mansione per aggiungere le persone. Il wizard crea "
                    "processi: le macchine nascono dalla skill matrix.",
                ]),
                ("p", "Rinominare una mansione è sicuro: persone, competenze, mansioni di rischio, ruoli e permessi sono "
                      "legati alla mansione, non al nome, e la «Chiave» non cambia. Il vecchio nome resta tra i «Nomi "
                      "precedenti» (scheda → «Impostazioni»): un file Excel preparato prima, senza chiave, si abbina "
                      "ancora; un nome attuale vince sempre su un vecchio nome. Due mansioni non possono avere lo stesso "
                      "nome. Si rinomina dall'editor, da «Impostazioni» o in blocco con l'Excel (cambia la colonna "
                      "«Mansione» e lascia la «Chiave»). Il caricamento del catalogo MOD.187 non rimette più i nomi di "
                      "partenza."),
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
            "id": "struttura-organizzativa",
            "titolo": "Struttura organizzativa (struttura della Qualità)",
            "blocchi": [
                ("p", "Persone → «Struttura organizzativa» mette in una pagina la struttura voluta dalla Qualità: "
                      "processi → reparti → aree → ruoli → mansioni. Le aree sono i «reparti» del file della Qualità "
                      "(MEGA SKILL MATRIX): per esempio il reparto AGG/MONT ha le aree AGGIUSTAGGIO, MONTAGGIO, "
                      "MASCHERATURA…; il reparto UT ha le aree DIREZIONE, COMMERCIALE, UFFICIO TECNICO, OPERATIONS, "
                      "ACQUISTI, QUALITA, RISORSE UMANE, HSE e IT."),
                ("def", [
                    ("Reparti e aree", "un blocco per reparto con il ruolo responsabile (es. CAR), il caporeparto, le "
                                       "aree e, per ogni area, i ruoli con le loro mansioni. Gli amministratori "
                                       "dell'anagrafica cambiano qui il ruolo responsabile del reparto e dell'area "
                                       "(vuoto = come il reparto). Il caporeparto (la persona) resta in «Reparti e aree»."),
                    ("Responsabilità del reparto", "ogni reparto con un ruolo responsabile ha la sua mansione "
                                                   "«Responsabilità del reparto <nome>», creata e aggiornata da sola: "
                                                   "serve per scrivere le competenze del responsabile. Chi la ricopre è "
                                                   "il caporeparto; se togli il ruolo responsabile la mansione si spegne."),
                    ("Processi", "i processi del Sistema di Gestione con tipo (principale/ausiliario), owner (un ruolo), "
                                 "numero di mansioni e ruoli coinvolti. «Cambia» modifica tipo e owner: serve il motivo e "
                                 "si salva come nuova revisione della scheda processo, la stessa che si vede in Sistema di "
                                 "Gestione → Catalogo processi."),
                    ("Ruoli", "sigla (ACO, IN1, MSM, CAR…, unica), diretto/indiretto, organigramma, persone e mansioni. "
                              "Sigla e diretto/indiretto si cambiano in linea. «accorpa N» indica i ruoli di prima "
                              "confluiti in questo (passa col mouse per vederli)."),
                    ("Da completare", "mansioni senza area, senza processo, senza ruolo o senza mansione di rischio "
                                      "confermata; reparti senza caporeparto o senza ruolo responsabile; ruoli della "
                                      "struttura senza nessuno assegnato."),
                ]),
                ("p", "Nell'editor della mansione (Mansionario → Struttura) ci sono anche «Area» (il reparto segue "
                      "l'area e vince sul reparto scritto sulla macchina), «Processo SGI» e «Abilitazione con validità o "
                      "scadenza». Una mansione nata dalla divisione di un'altra (es. Marcatura → laser, manuale, a "
                      "punti, elettrolitica) lo dice: il livello registrato sulla vecchia è solo un suggerimento, le "
                      "persone si valutano di nuovo."),
                ("p", "Scheda dipendente → «Posizione nella struttura»: ruolo (sigla, diretto/indiretto, principale), "
                      "reparto e area, ruolo responsabile, processi, mansioni svolte con livello e «Mansioni previste dal "
                      "ruolo, non ancora assegnate»: si assegnano una per una scegliendo il livello e «Assegna». Lo stesso "
                      "riquadro c'è nella pratica di onboarding («Assegna (I)», livello in formazione) e la checklist ha "
                      "la voce «Assegnare ruolo, area e mansioni della struttura»."),
                ("nota", "Rinominare un ruolo dal catalogo dei ruoli ora riscrive anche il «Ruolo aziendale» delle schede "
                         "e tiene il nome di prima fra i nomi precedenti."),
            ],
        },
        {
            "id": "struttura-revisioni",
            "titolo": "Revisioni della struttura (solo MSM)",
            "blocchi": [
                ("p", "La struttura che si modifica nelle pagine è la bozza. Quando la Qualità la approva, chi ricopre il "
                      "ruolo MSM (Management System Manager) apre «Revisioni», legge le modifiche rispetto alla revisione "
                      "in vigore, scrive il motivo e preme «Emetti la Rev. N». Nessun altro può emetterla, nemmeno "
                      "l'amministratore del portale. Se non è cambiato niente il portale non emette."),
                ("p", "Ogni revisione è una fotografia non modificabile: processi, reparti, aree, ruoli, mansioni con "
                      "competenze richieste e mansioni di rischio. Non contiene nominativi né livelli delle persone. "
                      "Dalla revisione: confronto con un'altra («Confronta con») e «Scarica PDF», il mansionario "
                      "ufficiale da conservare come documento controllato. La pagina della struttura dice in alto quale "
                      "revisione è in vigore e quante modifiche la bozza ha in più."),
            ],
        },
        {
            "id": "struttura-rischi",
            "titolo": "Mansioni di rischio da confermare (HSE)",
            "blocchi": [
                ("p", "Per le mansioni nuove il portale propone la mansione di rischio: impiegati → ADDETTO UFFICI, "
                      "macchine → ADDETTO MACCHINE UTENSILI, magazzino, pulizie, manutenzione, lavaggio, verniciatura, "
                      "prova pressione, liquidi penetranti, ritocchi dal nome, il resto dall'area. La proposta non vale "
                      "per DPI, visite e schede di sicurezza finché HSE (ruoli ESM/ESO, o chi gestisce i requisiti delle "
                      "mansioni di rischio) non la conferma in «Rischi da confermare»."),
                ("passi", [
                    "Cerca per mansione, area o mansione di rischio; spunta le righe giuste (o «seleziona tutte quelle "
                    "visibili») e premi «Conferma le selezionate»: valgono le proposte così come sono.",
                    "Per una riga diversa apri «Correggi»: scegli le mansioni di rischio giuste (anche più d'una) e "
                    "premi «Conferma»; valgono da subito e la proposta si chiude.",
                    "«Scarta la proposta»: non si conferma niente; la mansione resta senza mansione di rischio e "
                    "compare in «Da completare».",
                ]),
                ("nota", "La «Responsabilità del reparto» non riceve proposte: il rischio del caporeparto viene dalle "
                         "mansioni che svolge davvero."),
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
                    ("Impostazioni", "in testa le pastiglie di completezza (verde = a posto, arancio = manca, con il "
                                     "perché). Sotto quattro sezioni: 1 Identità (nome, tipo e chiave, nomi "
                                     "precedenti), 2 Dove sta nell'organizzazione (ruoli e reparto), 3 Sicurezza "
                                     "(mansioni di rischio), 4 Stato e regole («Mansione attiva» e le regole di calcolo "
                                     "in vigore). Cambiando il nome o spegnendo una mansione con persone in lista compare "
                                     "un avviso prima di salvare."),
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
                    ("Valuta", "per ogni persona si indica il livello su ogni competenza. Il livello sulla mansione si "
                               "calcola con la regola in vigore (di base: media delle competenze, arrotondata per "
                               "difetto, mai sopra la competenza bloccante più bassa); si aggiorna da solo anche nella "
                               "skill matrix."),
                    ("Regole", "Mansionario → «Regole» (amministrazione anagrafica o gestione skill matrix): «Da che "
                               "livello si è operativi» (I/L/U/O, di base U), «Come si calcola il livello dalle "
                               "competenze» (media con tetto sulla bloccante · minimo · media · minimo sulle bloccanti) e "
                               "«Operativi minimi per mansione» per il rischio uomo solo (di base 2). «Prova il calcolo» "
                               "mostra l'effetto su un esempio. «Prova» calcola senza salvare cosa cambierebbe: persone "
                               "operative, mansioni senza operativi o a rischio uomo solo, e chi cambia livello o esito. "
                               "«Applica le regole» salva e ricalcola i livelli, con una riga nello storico delle "
                               "abilitazioni. Sono gli stessi valori delle impostazioni della skill matrix."),
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
                    ("carica_struttura_v8", "carica la struttura della Qualità (MEGA SKILL MATRIX v8): reparti e aree "
                                            "(rinomine, aree che confluiscono con le persone), area delle persone che "
                                            "non ce l'hanno ricavata dal ruolo di oggi, ruoli con sigla (rinomine e "
                                            "accorpamenti: storico chiuso ieri, permessi e collegamenti al ruolo nuovo, "
                                            "nessuno perde accessi), processi con owner, mansioni (rinomine, nuove, "
                                            "divisioni), responsabilità di reparto, rischi proposti. In prova di "
                                            "default (rapporto riga per riga, nulla salvato), --applica per scrivere, "
                                            "--solo-da-decidere per i soli punti da guardare, --senza-aree-persone. "
                                            "Si può rilanciare: un secondo giro non cambia niente."),
                ]),
                ("p", "Prima di ogni comando che scrive, lancialo in prova (--dry-run) se l'opzione esiste."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "«Emetti la revisione» non c'è o dice che solo l'MSM può emetterla",
            "perche": "la revisione della struttura la emette solo chi ricopre oggi il ruolo con sigla MSM.",
            "fare": [
                "Struttura organizzativa → «Ruoli»: controlla che il ruolo MSM abbia la sigla MSM e la persona giusta.",
                "Assegna il ruolo alla persona dalla sua scheda (o con «Cambio ruoli in blocco»), poi riprova.",
            ],
        },
        {
            "sintomo": "Nella scheda dipendente non compaiono «Mansioni previste dal ruolo»",
            "perche": "la persona non ha un ruolo della struttura, oppure le mansioni del suo ruolo sono di un'altra "
                      "area, oppure le ha già tutte.",
            "fare": [
                "Controlla in «Posizione nella struttura» ruolo e area (se c'è «area da indicare», assegnala con uno "
                "spostamento).",
                "In Struttura organizzativa verifica che le mansioni dell'area abbiano quel ruolo.",
            ],
        },
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
