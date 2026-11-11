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
                    "quando cambi codice e ogni voce mostra il carico da cui parte il filo. Nello scarico originale (O) compaiono "
                    "i carichi con qualcosa «da scaricare»; nello scarico effettivo (M) gli scarichi originali senza M; nella "
                    "rettifica (R) gli scarichi effettivi senza rettifica. Il codice vale per le sei cifre: «12 01 01» trova "
                    "anche i carichi scritti «12.01.01 Sfridi Ferro Kg».",
                    "Il collegamento è facoltativo: se non spunti niente lo scarico si salva «non collegato» e la «Verifica» lo "
                    "elenca. «Mostra anche i già collegati» fa vedere anche i fili già completi per quel passo.",
                    "I movimenti sono divisi in «Da collegare» e «Già collegati» (questi solo con «Mostra anche i già "
                    "collegati»), dal più recente; sui carichi il bollino verde «Da scaricare» dice quanto resta.",
                    "Negli scarichi O e M, se la «Quantità» supera quanto resta dei carichi spuntati, sotto la quantità "
                    "compare l'avviso giallo con i chili disponibili: il salvataggio verrebbe rifiutato.",
                    "Con molti movimenti usa la casella di ricerca sopra l'elenco: filtra mentre scrivi per numero, data, FIR "
                    "o quantità (più parole = tutte presenti, per esempio «/1850» o «03 2025»). Il numero accanto dice quanti "
                    "ne vedi; i movimenti già spuntati restano sempre visibili. Esc svuota la ricerca.",
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
                ("nota", "Il portale rifiuta uno scarico originale che porta fuori più di quanto resta nei carichi collegati "
                         "(o, se non è collegato, nella giacenza del codice), uno scarico datato prima del movimento a cui si "
                         "collega e un carico già scaricato per intero. Un carico si può scaricare in più volte finché ha un residuo. "
                         "Lo scarico effettivo dopo uno scarico originale è il peso verificato a destino: può essere diverso dalla "
                         "stima e non viene confrontato con la giacenza. Il messaggio dice cosa correggere."),
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
                     "uno scarico effettivo. «Scarica (O)» resta finché il carico ha un residuo; gli altri spariscono quando il "
                     "seguito è già registrato. La scheda mostra anche lo stato del «Filo del carico»."),
                    ("Duplica", "nella scheda apre un nuovo movimento dello stesso tipo con lo stesso codice e la stessa unità, "
                     "con la data di oggi."),
                    ("Dalle Giacenze", "«Scarica» sulla riga di un codice apre lo scarico originale con quel codice."),
                    ("Seleziona i visibili", "nella sezione «Collegato a» spunta i movimenti che vedi (quelli rimasti dopo la "
                     "ricerca); la «Quantità» "
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
                    "«Consolida bozze complete». Quelle senza data, codice o quantità restano bozze.",
                    "«Segna trasmessa» indica che il movimento è stato trasmesso al RENTRI.",
                    "«Annulla registrazione» chiede il motivo, obbligatorio. Se ci sono movimenti collegati restano a registro con "
                    "il riferimento come traccia, ma non risultano più collegati: nell'elenco compare «COLLEGATO A ANNULLATO». "
                    "Li ricolleghi con «Modifica» (se sono bozze) o li lasci così.",
                    "Un collegamento tolto in modifica non si perde: la scheda lo mostra in «Collegamenti tolti (traccia)».",
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
                    "«Elenco registrazioni»: ogni carico con i suoi scarichi (il filo). Lo stato è IN DEPOSITO (con il residuo), "
                    "MANCA SCARICO EFFETTIVO, CHIUSA o SENZA CARICO. In alto i fili da completare; sotto «Fili chiusi, per codice» "
                    "un gruppo per ogni codice CER, da aprire con un clic. «Espandi»/«Comprimi» apre o chiude tutto.",
                    "Filtri dell'elenco: «Cerca» (numero, codice, rif. op, FIR, note), «Codice CER», «Tipo», «Stato del filo», "
                    "«Dal»/«Al», «RENTRI» (trasmessi o da trasmettere), «Consolidamento» (bozze o consolidati), «Solo pericolosi» "
                    "e «Mostra annullati». Nella casella «Cerca» un codice CER vale per le cifre: «12.01.01», «12 01 01» e "
                    "«120101» trovano lo stesso codice (e non 12.01.09); «12 01» trova tutti i 12 01 xx.",
                    "Sopra i fili c'è la ricerca immediata: filtra mentre scrivi e tiene insieme ogni filo (carico e scarichi), "
                    "aprendo i gruppi dei chiusi che contengono risultati. Cerca codice CER (come sopra), numero, FIR, data, "
                    "chi ha inserito e note; più parole = tutte presenti; Esc svuota.",
                    "«Esporta» (in alto nell'elenco) apre la finestra con Excel e PDF: «Con i filtri attivi» scarica quello che "
                    "vedi (stato del filo compreso), «Registro completo, annullati compresi» tutto il registro. L'Excel ha anche "
                    "«Collegato a», «Stato del filo», «Annullato» con il motivo e «Collegamenti tolti».",
                    "«Scadenzario»: formulari mancanti sugli scarichi O e M, movimenti da comunicare, bozze da consolidare.",
                    "«Giacenze»: quanto rifiuto c'è per codice, con l'unità, il semaforo del deposito temporaneo e il totale in m³ "
                    "(limite 30 m³, di cui 10 pericolosi). La giacenza è la somma di quanto resta dei carichi: lo scarico "
                    "originale (O) la riduce, la coppia scarico effettivo/rettifica (M/R) corregge il peso a destino e non la "
                    "tocca. I «Giorni dep.» contano dal carico più vecchio non ancora scaricato.",
                    "«Verifica»: controllo di sola lettura del registro con export CSV (vedi sotto).",
                    "«Riepilogo annuale»: scegli l'anno; per ogni codice CER «Giacenza 1/1», «Caricato», «Scaricato», "
                    "«Giacenza 31/12», numero di carichi e scarichi e formulari. È la base per compilare il MUD; «Non torna» "
                    "segnala i codici con scarichi oltre il carico (controllali nella Verifica). Export «Excel» e «PDF».",
                    "«Registro cronologico» (dal Riepilogo annuale): il PDF dell'anno con tutte le registrazioni in ordine di "
                    "data, le annullate in grigio con il motivo, l'intestazione con ragione sociale e codice di iscrizione "
                    "RENTRI (dalle Impostazioni) e «Pagina N di M».",
                ]),
            ],
        },
        {
            "id": "verifica",
            "titolo": "La pagina Verifica",
            "blocchi": [
                ("p", "Elenca quello che nel registro non torna. Ogni riga ha «Apri» per andare al movimento."),
                ("def", [
                    ("Scarichi senza carico d'origine", "il Rif. Op scritto non arriva a nessun carico valido."),
                    ("Collegati a un movimento annullato", "il movimento collegato è stato annullato: il riferimento resta come traccia."),
                    ("Scarichi senza collegamento", "registrati senza Rif. Op: è ammesso, controlla che sia voluto."),
                    ("Catene con codici CER diversi", "lo scarico ha un codice diverso dal suo carico."),
                    ("Scarichi oltre il carico", "lo scarico originale porta fuori più di quanto resta nei carichi collegati o del codice."),
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
                "Controlla che il carico abbia lo stesso codice CER (contano le sei cifre, non il testo).",
                "Spunta «Mostra anche i già collegati»: il carico potrebbe essere già scaricato per intero o avere già il suo seguito.",
                "Se il carico è annullato non compare: collega un altro carico o salva lo scarico senza collegamento.",
                "Se il carico manca, registralo prima con «C - Carico».",
            ],
        },
        {
            "sintomo": "«Quantità oltre la giacenza»",
            "fare": [
                "Apri «Giacenze» e cerca il codice: la giacenza è quanto resta dei carichi dopo gli scarichi originali.",
                "Se lo scarico è collegato, conta il residuo dei carichi spuntati: collega anche gli altri carichi o riduci la quantità.",
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
