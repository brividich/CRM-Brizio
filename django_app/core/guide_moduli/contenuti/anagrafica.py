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
                    ("Salute e sicurezza", "visite mediche, idoneità, mansioni di rischio."),
                    ("Report", "reportistica componibile ed export."),
                    ("Impostazioni", "cataloghi (ruoli, mansioni di rischio, aree, reparti) e permessi HR."),
                ]),
                ("p", "Vedi solo le voci per cui hai il permesso."),
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
                    ("Amministrazione", "una scheda per flusso (retribuzioni, cedolini, contratti) con righe abbinate e scartate dell'ultimo import."),
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
                ("p", "Un ruolo del catalogo può essere collegato a ruoli del portale (Amministrazione → «Ruoli e permessi», "
                      "matrice, «Dall'organigramma»): chi ricopre il ruolo riceve quei permessi da solo e li perde quando "
                      "lascia il ruolo. Assegnare o togliere un ruolo qui cambia quindi anche cosa la persona può fare nel portale."),
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
                    ("Scheda della mansione", "la barra conta le persone in lista per livello: verde autonomo o esperto, "
                                              "giallo intermedio, grigio in formazione. Il numero grande sono gli operativi "
                                              "(livello pari o sopra la soglia della skill matrix)."),
                    ("Ruoli", "ruoli sotto cui sta la mansione: di norma uno."),
                    ("Reparto", "per una macchina è quello dell'asset; per un processo si sceglie nella mansione."),
                    ("Mansioni di rischio", "quelle che comporta chi la svolge: da lì vengono DPI, visite e schede di "
                                            "sicurezza. Una mansione senza mansione di rischio è segnalata."),
                    ("Persone", "dalla pagina della mansione si mette una persona in lista con il suo livello, o la "
                                "si toglie. Ogni modifica resta nello storico delle abilitazioni."),
                    ("Competenze", "ogni mansione ha le sue competenze (es. set-up, programmazione), ciascuna con un "
                                   "livello minimo I/L/U/O, il segno «bloccante» e, se serve, un requisito formale: corso "
                                   "valido, qualifica o patentino valido, abilitazione MOD.128 operativa. Senza il "
                                   "requisito la persona non supera «I – in formazione» su quella competenza."),
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
                ("nota", "Le mansioni di rischio ricavate dalle mansioni sono per ora un'indicazione: DPI, visite e schede "
                         "di sicurezza seguono ancora la mansione di rischio scritta in anagrafica."),
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
                    ("report_ruoli_disallineati", "elenca i ruoli diversi tra anagrafica e account."),
                    ("importa_mansioni_idoneita", "assegna la mansione di rischio ai dipendenti che non l'hanno, dall'elenco "
                                                  "idoneità del medico (codice fiscale e «MANSIONE DI RISCHIO»). In prova di "
                                                  "default, --commit per scrivere."),
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
            "sintomo": "Scadenze di formazione o visite sbagliate",
            "fare": [
                "Controlla la mansione di rischio e i ruoli della persona: le scadenze dovute dipendono da lì.",
                "Lancia pulisci_scadenze_hr dal terminale del Setup Wizard.",
            ],
        },
    ],
}
