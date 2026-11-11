GUIDA = {
    "slug": "rentri",
    "titolo": "RENTRI · Registro rifiuti",
    "area": "Sicurezza sul lavoro",
    "sintesi": "Registro di carico e scarico dei rifiuti, scadenze, giacenze nel deposito temporaneo e verifica di coerenza.",
    "parole": "rentri rifiuti rifiuto cer eer formulario fir deposito giacenza annulla consolida verifica",
    "url": "rentri_menu",
    "prefissi": ("/rentri/",),
    "uso": [
        {
            "id": "tipi",
            "titolo": "I quattro tipi di registrazione",
            "blocchi": [
                ("def", [
                    ("C - Carico", "il rifiuto viene prodotto e messo nel deposito."),
                    ("O - Scarico originale", "il rifiuto parte con il formulario (quantità stimata)."),
                    ("M - Scarico effettivo", "la quantità vera pesata dal destinatario."),
                    ("R - Rettifica scarico", "correzione di uno scarico già registrato: positiva o negativa."),
                ]),
            ],
        },
        {
            "id": "registrare",
            "titolo": "Registrare un movimento",
            "blocchi": [
                ("passi", [
                    "Apri RENTRI e clicca la voce del tipo giusto (per esempio «C - Carico»).",
                    "Il modulo è una pagina sola, divisa in sezioni numerate. Compila la «Data»: non può essere nel futuro.",
                    "Cerca il «Codice CER» scrivendo il numero o il nome del rifiuto: servono le sei cifre (per esempio 15 01 06). "
                    "Le frecce ↑ ↓ e Invio scelgono un suggerimento.",
                    "Per gli scarichi spunta il movimento collegato nella sezione «Collegato a»: l'elenco si aggiorna da solo "
                    "quando cambi codice e mostra solo i movimenti collegabili, con lo stesso codice e non ancora usati.",
                    "Scrivi la «Quantità» (anche con la virgola, per esempio 12,5) e scegli l'«Unità di misura». "
                    "Il carico è sempre positivo; negli scarichi il segno meno è ammesso (lo scarico effettivo M "
                    "può avere il valore in «Rettifica scarico», la rettifica R lo stesso valore positivo).",
                    "Per un codice pericoloso (con l'asterisco *) nel carico va indicata la «Pericolosità» (HP).",
                    "Negli scarichi O e M la prima sezione è «Formulario (FIR)»: scegli il PDF o la foto e clicca "
                    "«Leggi i dati dal FIR» per farti proporre i dati (vedi sotto).",
                    "Clicca «Salva registrazione» nel riquadro «Riepilogo». Il numero di registrazione (anno/progressivo) "
                    "lo assegna il portale e non cambia più. Se non hai spuntato «Scheda da inviare al RENTRI», il portale "
                    "chiede se segnarla da inviare.",
                ]),
                ("p", "Il «Riepilogo» a lato mostra i dati inseriti e spunta i campi obbligatori man mano che li compili. "
                      "Se ne manca uno, il salvataggio si ferma e il campo è evidenziato in rosso. «Svuota» ripulisce il modulo."),
                ("nota", "Il portale rifiuta uno scarico che porta fuori più di quanto c'è in giacenza per quel codice, "
                         "uno scarico datato prima del movimento a cui si collega e un carico già scaricato. "
                         "Il messaggio dice cosa correggere."),
            ],
        },
        {
            "id": "scorciatoie",
            "titolo": "Compilare più in fretta",
            "blocchi": [
                ("def", [
                    ("Dati proposti dal codice", "scelto il codice, il modulo propone l'«Unità di misura» (e nel carico la "
                     "«Pericolosità») dell'ultimo movimento con quel codice, con la scritta «Proposta dall'ultimo movimento». "
                     "Negli scarichi sotto il codice compare anche «In deposito:» con la giacenza attuale."),
                    ("Nome ufficiale del codice", "se il catalogo EER è caricato, sotto il codice compare il nome ufficiale "
                     "con ✓, oppure ⚠ se il codice non esiste nell'elenco europeo o se l'asterisco non corrisponde. "
                     "È solo un confronto: il salvataggio non si blocca. Nel carico la ricerca trova anche per nome "
                     "(per esempio «imballaggi»)."),
                    ("Dalla scheda", "nella scheda di un movimento il pulsante del passo dopo apre il modulo già compilato: "
                     "«Scarica (O)» da un carico, «Registra scarico effettivo (M)» da uno scarico originale, «Rettifica (R)» da "
                     "uno scarico effettivo. Il pulsante sparisce quando il seguito è già registrato."),
                    ("Duplica", "nella scheda apre un nuovo movimento dello stesso tipo con lo stesso codice e la stessa unità, "
                     "con la data di oggi."),
                    ("Dalle Giacenze", "«Scarica» sulla riga di un codice apre lo scarico originale con quel codice."),
                    ("Seleziona tutti", "nella sezione «Collegato a» spunta tutti i movimenti collegabili; la «Quantità» "
                     "viene proposta come somma dei movimenti spuntati finché non la cambi a mano."),
                ]),
            ],
        },
        {
            "id": "fir",
            "titolo": "Leggere i dati dal formulario (FIR)",
            "blocchi": [
                ("passi", [
                    "Nello scarico originale o effettivo, sezione «Formulario (FIR)», scegli il PDF o la foto del formulario.",
                    "Clicca «Leggi i dati dal FIR». Con una scansione può servire qualche secondo.",
                    "Il portale elenca cosa ha letto: numero FIR, data, codice EER, quantità, unità e destinatario. "
                    "Spunta i dati che vuoi usare e clicca «Usa i dati spuntati».",
                    "Controlla i campi e salva come sempre: il file resta allegato allo scarico.",
                ]),
                ("p", "Nello scarico effettivo la quantità proposta è il peso verificato a destino, se il formulario lo riporta; "
                      "il numero FIR va in «Arrivo FIR». Nello scarico originale numero FIR e destinatario finiscono nelle note."),
                ("nota", "I valori con l'etichetta «letto dall'AI: controlla» li ha trovati l'assistente AI del portale quando le "
                         "regole non bastavano: partono non spuntati, vanno verificati sul formulario. Il documento non esce dal server."),
            ],
        },
        {
            "id": "stati",
            "titolo": "Bozza, consolidata, annullata",
            "blocchi": [
                ("def", [
                    ("BOZZA", "appena registrata: si può ancora modificare con la matita ✎."),
                    ("CONSOLIDATA", "definitiva: non si modifica più. Si corregge con una «R - Rettifica scarico» o annullandola."),
                    ("ANNULLATA", "sbagliata: resta nel registro, barrata, con il motivo. Non conta nelle giacenze e il suo numero non viene riusato."),
                ]),
                ("passi", [
                    "Nell'«Elenco registrazioni» clicca la lente 🔍 della riga: si apre la scheda del movimento.",
                    "«Consolida» rende definitiva la registrazione (anche dallo «Scadenzario», sezione «Bozze da consolidare»).",
                    "Per consolidare tante bozze insieme: «Scadenzario» → «Bozze da consolidare» → scegli la data e clicca "
                    "«Consolida bozze complete». Quelle senza quantità o senza movimento collegato restano bozze.",
                    "«Segna trasmessa» indica che il movimento è stato trasmesso al RENTRI.",
                    "«Annulla registrazione» chiede il motivo, obbligatorio. Se ci sono movimenti collegati vanno annullati prima quelli.",
                ]),
                ("p", "La scheda mostra anche i movimenti collegati e lo «Storico modifiche»: chi ha cambiato cosa e quando."),
                ("p", "Nell'elenco gli annullati sono nascosti: spunta «Mostra annullati» per vederli. Nel PDF del registro compaiono in grigio con il motivo."),
            ],
        },
        {
            "id": "consultare",
            "titolo": "Elenco, scadenze, giacenze e verifica",
            "blocchi": [
                ("ul", [
                    "«Elenco registrazioni»: ogni carico con i suoi scarichi, raggruppati in «famiglie» APERTA o CHIUSA. "
                    "Filtra per anno, tipo e «Stato famiglia»; «Espandi»/«Comprimi» apre o chiude tutto.",
                    "«Scadenzario»: formulari mancanti sugli scarichi O e M, movimenti da comunicare, bozze da consolidare.",
                    "«Giacenze»: quanto rifiuto c'è per codice, con l'unità, il semaforo del deposito temporaneo e il totale in m³ "
                    "(limite 30 m³, di cui 10 pericolosi). I «Giorni dep.» contano dal carico più vecchio non ancora scaricato.",
                    "«Verifica»: controllo di sola lettura del registro con export CSV (vedi sotto).",
                ]),
            ],
        },
        {
            "id": "verifica",
            "titolo": "La pagina Verifica",
            "blocchi": [
                ("p", "Elenca quello che nel registro non torna. Ogni riga ha «Apri» per andare al movimento."),
                ("def", [
                    ("Scarichi senza carico d'origine", "la catena Rif. Op non arriva a nessun carico valido."),
                    ("Catene con codici CER diversi", "lo scarico ha un codice diverso dal suo carico."),
                    ("Saldo del deposito sotto zero", "in ordine di data è uscito più di quanto era entrato."),
                    ("Date incoerenti", "un movimento è datato prima di quello a cui si collega."),
                    ("Numeri di registrazione doppi", "lo stesso numero su più movimenti (le coppie R+M dello stesso giorno sono escluse)."),
                    ("Quarta copia FIR oltre 90 giorni", "scarico originale O senza lo scarico effettivo M dopo 90 giorni."),
                    ("Annotazioni oltre 10 giorni lavorativi", "movimento scritto nel portale troppo tempo dopo la sua data."),
                    ("Deposito temporaneo oltre soglia", "codici fermi in deposito oltre la soglia in giorni."),
                    ("Unità di misura miste", "lo stesso codice registrato con unità diverse."),
                    ("Copia SharePoint non allineata", "movimento salvato nel portale ma non arrivato alla lista SharePoint."),
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "impostazioni",
            "titolo": "Impostazioni",
            "blocchi": [
                ("p", "RENTRI → «Impostazioni»: «Ragione sociale», «Codice iscrizione RENTRI», «Referenti operativi» e «Note operative». "
                      "Clicca «Salva impostazioni»."),
                ("p", "I referenti ricevono l'avviso periodico (comando check_rentri_scadenze) con bozze, movimenti da comunicare "
                      "e i conteggi della «Verifica»."),
                ("p", "Le soglie del deposito temporaneo sono nella configurazione del portale (SiteConfig): rentri_deposito_giorni_max (90), "
                      "rentri_deposito_giorni_warn (75), rentri_deposito_m3_max (30), rentri_deposito_m3_pericolosi_max (10)."),
            ],
        },
        {
            "id": "catalogo-eer",
            "titolo": "Catalogo EER",
            "blocchi": [
                ("passi", [
                    "Apri su EUR-Lex la Decisione 2000/532/CE (elenco dei rifiuti) nel testo consolidato in italiano.",
                    "Salvala dal browser (File → Salva pagina, formato HTML) oppure scarica il PDF.",
                    "RENTRI → «Impostazioni» → riquadro «Catalogo EER» → scegli il file → «Carica catalogo».",
                ]),
                ("p", "Il riquadro mostra quanti codici sono caricati e quanti pericolosi. Il caricamento sostituisce il catalogo precedente; "
                      "un file con meno di 500 codici viene rifiutato perché non è l'elenco completo (sono circa 840). "
                      "Va bene anche un CSV «codice;descrizione» con l'asterisco nei pericolosi. Da terminale: rentri_catalogo_eer <file> "
                      "(con --dry-run conta senza salvare)."),
            ],
        },
        {
            "id": "promemoria",
            "titolo": "Promemoria dello scarico effettivo",
            "blocchi": [
                ("p", "Ogni mattina alle 7:25 il portale cerca gli scarichi originali (O) senza scarico effettivo da più di "
                      "60 giorni e manda una notifica a chi li ha inseriti e ai «Referenti operativi» (quelli con un utente del portale "
                      "collegato alla stessa email). La notifica dice quanti giorni mancano ai 90 della quarta copia e apre lo "
                      "scarico effettivo già compilato. Per lo stesso scarico si ripete al massimo una volta a settimana."),
                ("p", "La soglia è nella configurazione del portale (SiteConfig): rentri_promemoria_m_giorni (60, al massimo 90). "
                      "Schedule: rentri_promemoria_scarico_effettivo. Prova da terminale: rentri_promemoria --dry-run."),
                ("nota", "Gli scarichi inseriti prima di questa versione, importati o arrivati da SharePoint non hanno l'autore "
                         "collegato: per quelli la notifica va solo ai referenti."),
            ],
        },
        {
            "id": "import",
            "titolo": "Importare lo storico",
            "blocchi": [
                ("passi", [
                    "Prepara il file CSV esportato (separato da ; oppure da ,).",
                    "Dal menu RENTRI usa l'import: prima compare l'anteprima, poi confermi.",
                    "In alternativa sul server: comando import_rentri_csv.",
                ]),
                ("p", "L'import è tutto o niente: se una riga non è valida non viene importato nulla e l'elenco degli errori dice quali righe correggere. "
                      "I riferimenti Rif. Op che non trovano un movimento sono segnalati come avvisi."),
                ("nota", "import_rentri_csv --clear cancella il registro prima di importare: scrive sempre una copia CSV (--backup percorso)."),
                ("p", "Consolidamento in blocco da terminale: rentri_consolida_bozze --fino-al AAAA-MM-GG mostra l'anteprima, "
                      "con --applica consolida."),
                ("p", "Per controllare eventuali numeri doppi c'è il comando di sola lettura rentri_id_duplicati --solo-anomalie; "
                      "per tutto il resto rentri_verifica (stessi controlli della pagina)."),
            ],
        },
        {
            "id": "sharepoint",
            "titolo": "Copia su SharePoint",
            "blocchi": [
                ("p", "Il registro del portale fa fede; la lista SharePoint RENTRI è una copia. Se SharePoint non risponde il movimento resta "
                      "salvato, la scheda mostra l'avviso e la riga dell'elenco il segno «SP»."),
                ("p", "Il comando rentri_sync_riprova reinvia i movimenti non allineati. La lettura da SharePoint porta nel portale solo i "
                      "movimenti nuovi con un tipo C/O/M/R riconoscibile e non tocca quelli consolidati o annullati."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Avviso «Accesso a Microsoft 365 non riuscito» sulla copia SharePoint",
            "fare": [
                "Il codice tra parentesi viene da Entra ID: AADSTS7000215 = segreto dell'app sbagliato o scaduto, "
                "AADSTS700016 = ID applicazione non trovato, AADSTS90002 = tenant sbagliato.",
                "Corretto il .env, il comando rentri_sync_riprova reinvia i movimenti rimasti indietro.",
            ],
        },
        {
            "sintomo": "Uno scarico non trova il carico da collegare",
            "fare": [
                "Controlla che il carico abbia lo stesso codice CER.",
                "Controlla che il carico non sia già scaricato o annullato.",
                "Se il carico manca, registralo prima con «C - Carico».",
            ],
        },
        {
            "sintomo": "«Quantità oltre la giacenza»",
            "fare": [
                "Apri «Giacenze» e cerca il codice: la giacenza è carichi meno scarichi effettivi e rettifiche.",
                "Se manca un carico, registralo prima dello scarico.",
                "Se un carico ha la quantità sbagliata ed è una bozza, correggilo; se è consolidato, annullalo e registralo di nuovo.",
            ],
        },
        {
            "sintomo": "Non riesco a modificare una registrazione",
            "fare": [
                "È consolidata o annullata: la matita non compare e la scheda si apre in sola lettura.",
                "Registra una «R - Rettifica scarico» oppure annullala con il motivo e registrala di nuovo.",
            ],
        },
        {
            "sintomo": "Il numero di registrazione sembra sbagliato o doppio",
            "fare": [
                "Lancia rentri_id_duplicati --solo-anomalie dal terminale del Setup Wizard, oppure apri «Verifica».",
                "I numeri non si riciclano: un movimento annullato tiene il suo numero, ed è corretto così.",
            ],
        },
        {
            "sintomo": "«Leggi i dati dal FIR» non trova niente",
            "fare": [
                "Con una scansione sbiadita o storta il testo non si legge: rifai la foto dritta e con buona luce, o usa il PDF.",
                "Il pulsante si attiva solo con PDF o immagini (JPG, PNG, WEBP), non con Word o Excel.",
                "Sul server serve Tesseract per le scansioni; senza, il messaggio lo dice. Compila i campi a mano.",
            ],
        },
        {
            "sintomo": "Sotto il codice non compare il nome ufficiale",
            "fare": [
                "Il catalogo EER non è caricato: un amministratore lo carica da RENTRI → «Impostazioni» → «Catalogo EER».",
            ],
        },
    ],
}
