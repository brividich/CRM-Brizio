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
                    "Il modulo procede a passi: compila «Data» e clicca «Avanti →». La data non può essere nel futuro.",
                    "Cerca il «Codice CER» scrivendo il numero o il nome del rifiuto: servono le sei cifre (per esempio 15 01 06).",
                    "Per gli scarichi scegli il movimento collegato (Rif. Op): il portale mostra solo quelli collegabili, "
                    "con lo stesso codice e non ancora usati.",
                    "Scrivi la «Quantità» (anche con la virgola, per esempio 12,5) e scegli l'«Unità di misura».",
                    "Per un codice pericoloso (con l'asterisco *) nel carico va indicata la «Pericolosità» (HP).",
                    "Negli scarichi O e M puoi allegare il formulario (FIR).",
                    "Conferma. Il numero di registrazione (anno/progressivo) lo assegna il portale e non cambia più.",
                ]),
                ("p", "Con «← Indietro» torni al passo prima senza perdere i dati."),
                ("nota", "Il portale rifiuta uno scarico che porta fuori più di quanto c'è in giacenza per quel codice, "
                         "uno scarico datato prima del movimento a cui si collega e un carico già scaricato. "
                         "Il messaggio dice cosa correggere."),
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
    ],
}
