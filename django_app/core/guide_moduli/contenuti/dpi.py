GUIDA = {
    "slug": "dpi",
    "titolo": "DPI",
    "area": "Sicurezza sul lavoro",
    "sintesi": "Dispositivi di protezione individuale: si chiedono, il responsabile approva, il magazzino consegna con firma.",
    "parole": "dpi guanti scarpe occhiali casco protezione consegna firma magazzino taglia",
    "url": "dpi:dashboard",
    "prefissi": ("/dpi/",),
    "uso": [
        {
            "id": "chiedere",
            "titolo": "Chiedere un DPI",
            "blocchi": [
                ("passi", [
                    "Apri DPI e clicca «+ Nuova richiesta».",
                    "In «Richiesta per» lascia «Me stesso». Se sei un responsabile puoi scegliere un tuo dipendente.",
                    "Clicca sulla scheda del DPI (per esempio scarpe, guanti, occhiali). Puoi anche scrivere il nome o il codice del modello in «Cerca». "
                    "Sulla scheda vedi se è «In dotazione», «In scadenza», «Scaduto» o «Già richiesto».",
                    "Compaiono solo le domande che servono. Se c'è una scelta sola è già compilata. Se non sai il tipo o il modello lascia "
                    "«Non lo so, decide il magazzino»; la «Taglia» si chiede dopo il modello, altrimenti «Da scegliere al ritiro».",
                    "Se hai già ricevuto quel DPI, «Uguale all'ultima volta» riprende tipo, modello e taglia.",
                    "Indica la «Quantità» e il «Motivo»: clicca Usura, Rotto, Perso, Prima dotazione o Cambio taglia, oppure scrivilo. "
                    "Per un DPI fuori dal profilo della tua mansione il motivo è obbligatorio.",
                    "Clicca «Invia richiesta». Il numero della richiesta ha la forma DPI-anno-numero.",
                ]),
                ("p", "La richiesta passa per questi stati: inviata → approvata → pronta al ritiro → consegnata "
                      "(oppure rifiutata o annullata)."),
                ("p", "Quando il DPI è pronto ricevi una mail e una notifica nel portale: passa in magazzino a ritirarlo e firma la ricevuta."),
                ("p", "Se sei un CAR o un preposto la tua richiesta (anche quella per un tuo dipendente) è approvata da sola e "
                      "va subito al magazzino."),
                ("p", "Finché non è approvata puoi ritirarla: apri la richiesta e clicca «Annulla richiesta»."),
            ],
        },
        {
            "id": "storico",
            "titolo": "Vedere i DPI che hai in carico",
            "blocchi": [
                ("p", "«La mia dotazione», nella Dashboard DPI, mette in cima quello che richiede attenzione: i DPI previsti dalla tua mansione "
                      "e non ancora consegnati («Richiedi»), le richieste in corso con il passo a cui sono, i DPI scaduti o che scadono entro 30 giorni "
                      "(«Richiedi il ricambio» apre la richiesta già compilata). Per un DPI ancora valido usa «Rotto o perso?»."),
                ("p", "«Il mio storico» elenca le consegne fatte a te, con la data di scadenza di ogni DPI."),
                ("ul", [
                    "Il pallino colorato dice se il DPI è in regola, in scadenza o scaduto.",
                    "Quando ricevi un nuovo DPI dello stesso tipo, quello vecchio esce dai conteggi ma resta nello storico.",
                ]),
            ],
        },
        {
            "id": "approvare",
            "titolo": "Approvare e consegnare (responsabili e magazzino)",
            "blocchi": [
                ("passi", [
                    "Nella Dashboard DPI il riquadro «Da fare» mostra «In attesa di approvazione», «Da consegnare», «Da riordinare», «DPI scaduti» e "
                    "«In scadenza (30 gg)»: ogni numero apre la lista corrispondente. Clicca «In attesa di approvazione» e poi la richiesta.",
                    "Nel riquadro «Prima di decidere» guarda le consegne precedenti della persona e la media del reparto. "
                    "«Proponi con l'AI» suggerisce una decisione: è solo un consiglio.",
                    "Clicca «Approva» oppure «Rifiuta» (scrivi il motivo). Con «Aggiungi nota» lasci un commento.",
                    "Il magazzino riceve la mail «Da consegnare», prepara il DPI e clicca «Pronto per il ritiro»: il dipendente "
                    "riceve mail e notifica. «Avvisa di nuovo» ripete l'avviso. Più veloce: dal «Banco consegne» (vedi sotto).",
                    "Quando il DPI viene consegnato, il magazzino clicca «Registra consegna», fa firmare il dipendente "
                    "nel riquadro firma e salva. «Cancella firma» ripulisce il riquadro se serve rifarla.",
                ]),
                ("nota", "Nessuno può approvare la propria richiesta. Il responsabile vede solo le richieste dei suoi dipendenti."),
            ],
        },
        {
            "id": "scarpe",
            "titolo": "Scarpe: in convenzione o fuori convenzione",
            "blocchi": [
                ("p", "Chiedendo le scarpe scegli dove ritirarle. «In convenzione»: entrano nell'ordine al negozio, che parte ogni 15 giorni "
                      "(si cambia in Impostazioni), e le ritiri in ufficio amministrativo quando ti avvisiamo. «Fuori convenzione»: le ritiri al negozio."),
                ("p", "Dopo l'approvazione la mail va all'operatore incaricato, non al magazzino. L'operatore lavora in DPI → «Scarpe»:"),
                ("passi", [
                    "«Convenzione: da ordinare»: controlla le righe e clicca «Invia l'ordine». Se scrivi tu al negozio usa «Copia il testo» e poi "
                    "«Ho già scritto io al negozio». Se sono passati i giorni del riepilogo arriva un promemoria.",
                    "«Convenzione: ordinate, da consegnare»: quando arrivano spunta e clicca «Arrivate: avvisa di passare in ufficio». "
                    "La consegna si chiude come per gli altri DPI, con «Registra la consegna».",
                    "«Fuori convenzione: ritiro al negozio»: avvisa il negozio, spunta e clicca «Negozio avvisato: avvisa i dipendenti».",
                    "Quando arriva la fattura: spunta gli ordini che copre, carica il file con «Numero» e «Data» e clicca «Carica e chiudi gli ordini spuntati». "
                    "La data della fattura diventa la data di consegna, da cui parte la scadenza.",
                ]),
                ("nota", "Le scarpe ordinate al negozio non scaricano il magazzino. La fattura la vede solo chi gestisce i DPI."),
            ],
        },
        {
            "id": "banco",
            "titolo": "Banco consegne (magazzino)",
            "blocchi": [
                ("p", "DPI → «Banco consegne» è la pagina di lavoro del magazzino: tutte le richieste approvate da "
                      "preparare e consegnare, raggruppate per persona. In alto i numeri: «Persone in attesa», «Da preparare», "
                      "«Pronti al ritiro» e «Giacenza insufficiente»."),
                ("passi", [
                    "Quando la persona arriva scrivi il nome in «Cerca la persona al banco» (vale anche il reparto, il numero della richiesta o il codice del modello; il badge si passa solo sul lettore). "
                    "Se resta una sola persona la sua scheda si apre da sola; altrimenti cliccala nell'elenco.",
                    "Nella scheda tutti i DPI sono già spuntati: togli la spunta a quelli che non consegni adesso («Tutti» e «Nessuno» fanno prima). "
                    "Accanto a ogni DPI vedi quanti pezzi ci sono «in magazzino» (in rosso se non bastano). Se non bastano registra il carico, oppure scrivi "
                    "il «Motivo della consegna senza giacenza»: senza non si consegna, e il motivo resta nella richiesta e nel movimento di magazzino.",
                    "Se manca quel modello o quella taglia clicca «Cambia» (o «Scegli modello») accanto al DPI: la modifica resta scritta nella richiesta.",
                    "Clicca «Consegna N DPI a…»: il pulsante dice quanti DPI e a chi. Il cursore torna sulla ricerca, pronto per la persona dopo. "
                    "La consegna è registrata subito. In basso una barra conta 6 secondi prima di mail e PDF: «Annulla» (o Esc) riporta i DPI da consegnare "
                    "e rimette i pezzi a magazzino, «Invia ora» non aspetta. Se chiudi la pagina la consegna resta salva e gli avvisi partono comunque. "
                    "Non serve la firma: parte da sola la mail di conferma della ricevuta (vedi sotto).",
                    "Se al banco c'è un tablet o hai la ricevuta su carta, apri «Firma sul tablet o ricevuta su carta»: con la firma "
                    "(o la spunta «Ricevuta firmata su carta») la mail di conferma non parte.",
                ]),
                ("ul", [
                    "Da tastiera: / va alla ricerca, frecce su e giù scelgono la persona, Invio porta sul pulsante di consegna e un secondo Invio registra, Esc pulisce la ricerca.",
                    "I riquadri in alto («Da preparare», «Pronti al ritiro», «Giacenza insufficiente») filtrano l'elenco: un secondo clic toglie il filtro.",
                    "L'elenco si aggiorna da solo ogni minuto se non stai lavorando su una persona.",
                    "Con un lettore di badge (o di un QR che contiene il codice del badge) leggi il badge nella ricerca: il codice è quello della scheda in Anagrafica. "
                    "Se la persona non ha DPI da ritirare lo dice e offre «Consegna diretta».",
                    "«Lista di prelievo» raccoglie tutto ciò che è da preparare, sommato per modello e taglia con le persone: si stampa e con «Pronti: avvisa gli spuntati» manda l'avviso di ritiro in blocco.",
                ]),
                ("p", "Conferma della ricevuta via mail: una sola mail per tutti i DPI consegnati insieme, con i pulsanti "
                      "«Confermo, ricevuti» e «Non li ho ricevuti». Va al dipendente se ha la mail aziendale (i domini si scrivono "
                      "in Impostazioni, «Domini della mail aziendale»), altrimenti al suo caporeparto/responsabile; se non c'è "
                      "nessuno dei due, ai referenti DPI. Il link si apre anche dal telefono, senza entrare nel portale, e vale una volta."),
                ("ul", [
                    "«Non li ho ricevuti» (con una nota facoltativa) manda la mail «Consegna contestata» al Magazzino.",
                    "Senza risposta dopo 3 giorni parte un solo promemoria con un link nuovo (il vecchio non vale più).",
                    "In fondo al banco il riquadro «Conferme di ricevuta» elenca quelle da confermare e le contestate degli ultimi 30 giorni.",
                    "La consegna vale subito per magazzino e scadenze; l'esito della conferma compare nella scheda della richiesta e nel PDF del modulo di consegna.",
                ]),
                ("p", "«Pronto per il ritiro (avvisa)» manda in un colpo l'avviso di ritiro per tutti i DPI spuntati della persona "
                      "(chi era già avvisato non riceve un secondo avviso). Non compare se in Impostazioni l'avviso parte già all'approvazione."),
                ("p", "Lettore di badge: con Chrome o Edge clicca «Collega lettore badge» e scegli la porta CP210x (solo la prima volta, poi si "
                      "ricollega da solo). Passando il badge il portale verifica subito di chi è e apre la sua scheda. Controlla i DPI spuntati e scegli: "
                      "«Conferma con badge», poi la persona passa di nuovo il proprio badge entro 60 secondi: vale come ricevuta, senza mail (per qualche secondo puoi ancora «Annulla»); "
                      "«Conferma con mail», per chi non ha il badge con sé: ritira subito e la conferma arriva per mail. Un badge di un'altra persona non conferma nulla. "
                      "Il numero del badge non si può scrivere a mano e la ricerca non lo cerca: funziona solo la lettura dal lettore. "
                      "Nel Registro consegne la ricevuta risulta «Confermata con badge». Se la persona non ha DPI da ritirare lo dice; «Badge non riconosciuto» vuol dire "
                      "che il numero non è nell'Anagrafica, è su due persone o la persona è fuori dal tuo perimetro: cerca per nome. Dopo 20 badge non riconosciuti in 10 minuti la lettura si sospende per qualche minuto. Se il lettore è pronto ma al passaggio non succede nulla, sul lettore 3022L controlla la levetta 2 del blocchetto SW1 sulla piastra: con quella in posizione originale non trasmette."),
                ("p", "Ogni consegna fatta dal banco vale come quella dalla scheda richiesta: PDF nei documenti del dipendente, "
                      "scarico del magazzino, sostituzione del DPI precedente dello stesso tipo, report al responsabile."),
                ("p", "«Consegna diretta al banco» (solo se qualche categoria ha la spunta «Consegna diretta dal banco»): scegli "
                      "dipendente, DPI, taglia e quantità e clicca «Aggiungi al banco». La richiesta nasce già approvata, senza "
                      "passare dal responsabile, e si apre subito la sua scheda. Il riquadro è chiuso finché non serve; «+ Consumabile» nella scheda lo apre con la persona già scelta."),
                ("p", "In home, stanza «Oggi», chi gestisce le consegne trova il riquadro «Banco consegne DPI»: i numeri del banco "
                      "(persone in attesa, da preparare, pronti al ritiro, giacenza insufficiente, conferme in attesa e contestate), "
                      "le prime 6 persone con il pulsante «Consegna» che apre direttamente la loro consegna, la casella «Chi è al banco?» "
                      "(se il nome trova una sola persona si apre subito la sua consegna) e «Consegna diretta». "
                      "Si nasconde da «⚙ Personalizza» togliendo la spunta «Banco consegne DPI»."),
                ("p", "Il PDF del modulo di consegna riporta numero della richiesta, DPI, modello con codice, taglia, quantità e "
                      "scadenza; nel riquadro «Ricevuta» la firma del banco, oppure l'esito della conferma via mail (chi ha "
                      "confermato e quando). La riga per la firma su carta compare solo se non c'è né firma né conferma."),
                ("nota", "Il banco mostra solo le categorie con «La consegna la fa il magazzino». Le altre (per esempio le scarpe) "
                         "si vedono con «Mostra anche gli altri DPI»."),
            ],
        },
        {
            "id": "documenti",
            "titolo": "Documenti dei DPI",
            "blocchi": [
                ("p", "«Documenti» raccoglie certificati, attestati e manuali d'uso di ogni DPI del catalogo. Tutti possono "
                      "consultarli; solo i gestori possono caricarli («Carica documenti») o eliminarli."),
            ],
        },
    ],
    "admin": [
        {
            "id": "catalogo",
            "titolo": "Il catalogo DPI",
            "blocchi": [
                ("p", "DPI → «Impostazioni». Il catalogo ha quattro livelli, dal generale al particolare:"),
                ("def", [
                    ("Categoria", "per esempio «Calzature». Ha l'icona, la vita utile in mesi, il flag «obbligatorio da mansionario», "
                                  "«Alla consegna avvisa l'Amministrazione», «La consegna la fa il magazzino» (togli la spunta per le "
                                  "scarpe: escono dal Banco consegne e la mail «Da consegnare» va ai referenti DPI) e «Consegna diretta "
                                  "dal banco, senza approvazione» (consumabili come guanti e tappi). «+ Nuova categoria»."),
                    ("Tipo", "sottocategoria, per esempio «Scarpe S3». «+ Nuovo tipo»."),
                    ("Modello", "prodotto preciso con codice, produttore e foto. Se ha una vita utile propria vince su quella della categoria. «+ Nuovo modello»."),
                    ("Taglia", "valore della taglia. «+ Nuova taglia»."),
                ]),
                ("nota", "Cambiando la vita utile di una categoria o di un modello, le scadenze delle consegne in uso si ricalcolano da sole "
                         "(tranne quelle scritte a mano)."),
            ],
        },
        {
            "id": "notifiche",
            "titolo": "Chi viene avvisato",
            "blocchi": [
                ("ul", [
                    "Nuova richiesta: mail al responsabile del dipendente (capo dell'area o caporeparto), ai co-responsabili e al "
                    "preposto dell'area. Se nessuno di loro ha un'email di notifica, va agli indirizzi di ripiego «dpi_car_emails».",
                    "Con la spunta «Email ai referenti (responsabili + email aggiuntive) per ogni nuova richiesta» la mail va "
                    "anche ai «Responsabili» e alle «Email notifiche aggiuntive» delle Impostazioni.",
                    "Richiesta di un CAR o di un preposto (per sé o per un suo dipendente): approvata da sola, nessuna mail «da approvare».",
                    "Richiesta approvata: mail «Da consegnare» al Magazzino; per le categorie senza «La consegna la fa il "
                    "magazzino» (per esempio le scarpe) va invece ai referenti DPI («Responsabili» + «Email notifiche aggiuntive»). "
                    "Il pulsante «Apri il Banco consegne» della mail apre il banco sulla scheda della persona (con l'accesso "
                    "Windows attivo, dai PC del dominio si entra senza password).",
                    "Consegna diretta al banco: nessuna mail di approvazione né «Da consegnare»; alla consegna parte il report come sempre.",
                    "Consegna registrata senza firma né ricevuta su carta: mail «Conferma la ricevuta dei DPI» al dipendente (mail "
                    "aziendale) o al caporeparto; «Non li ho ricevuti» → mail «Consegna contestata» al Magazzino; dopo 3 giorni "
                    "senza risposta un promemoria (task delle 07:10). Le due mail sono le regole «DPI consegnato - conferma "
                    "della ricevuta via mail» e «DPI - consegna contestata» in Automazioni: spegnendo la prima la mail non "
                    "parte e il banco lo segnala.",
                    "«Pronto per il ritiro» (dal magazzino): mail e notifica nel portale al dipendente. Con la spunta «Avvisa il "
                    "dipendente di ritirare il DPI subito all'approvazione» l'avviso parte già all'approvazione e il passaggio del "
                    "magazzino non serve.",
                    "Richiesta rifiutata dopo l'approvazione: mail «Consegna annullata» a chi consegna (Magazzino o referenti), così non consegna.",
                    "Consegna registrata: report con il PDF del modulo di consegna al responsabile/preposto del dipendente e, "
                    "solo per le categorie con la spunta «Alla consegna avvisa l'Amministrazione», all'Amministrazione.",
                    "Il dipendente riceve la notifica nel portale (campanella) ad approvazione, rifiuto, ritiro e consegna.",
                    "Ogni mattina feriale alle 07:00 il riepilogo (regola AU51) elenca le richieste DPI ancora da approvare: lo "
                    "ricevono il caporeparto e chi le deve approvare (responsabile dell'area, preposto).",
                    "Nuovo assunto con mansione che richiede DPI: mail «Da distribuire» al Magazzino e «Controllo uso» al suo "
                    "CAR/preposto.",
                ]),
                ("p", "Gli indirizzi si scrivono in DPI → Impostazioni, uno per riga. Salva con «Salva impostazioni». "
                      "L'intero ciclo è l'automazione AU14 del modulo Automazioni (flussi «managed-dpi_…»)."),
            ],
        },
        {
            "id": "bozza-ordine",
            "titolo": "Bozza d'ordine ai fornitori",
            "blocchi": [
                ("p", "Da DPI → «Magazzino» → report, «Bozza d'ordine» propone cosa riordinare, diviso per il fornitore dell'ultimo carico, con le quantità suggerite dai consumi "
                      "del periodo scelto. Correggi le quantità (zero esclude la riga), poi «Copia il testo» o «Apri nella posta». Il portale non invia nulla."),
            ],
        },
        {
            "id": "magazzino",
            "titolo": "Magazzino e scorte",
            "blocchi": [
                ("ul", [
                    "«Magazzino»: la giacenza di ogni modello è la somma dei movimenti. «Carica a magazzino» registra un arrivo (DDT); "
                    "la consegna scarica da sola; «Imposta giacenza» corregge dopo un inventario.",
                    "«Leggi un DDT»: scegli il PDF o la foto del DDT e premi «Leggi il DDT». Il portale propone numero, data e fornitore "
                    "e una riga per ogni codice DPI del catalogo che trova nel documento, con la quantità letta sulla stessa riga "
                    "(«da controllare» se non l'ha letta con sicurezza). Spunta le righe giuste, correggi le quantità e premi "
                    "«Carica le righe spuntate». I codici che non sono nel catalogo non vengono proposti: caricali a mano.",
                    "Con la scorta minima il modello diventa «Da riordinare» o «Esaurito».",
                    "«Report e consumi» mostra i consumi per mese, reparto e modello, la quantità suggerita da riordinare e le «Consegne senza giacenza» con il motivo; «Esporta movimenti (CSV)». "
                    "Clicca un reparto per vedere le sue consegne nel Registro.",
                ]),
            ],
        },
        {
            "id": "report",
            "titolo": "Report: conformità, consegne e consumi",
            "blocchi": [
                ("p", "DPI → «Report» ha tre schede. Lo vede chi ha il permesso di gestire i DPI, sulle persone del proprio perimetro."),
                ("ul", [
                    "«Conformità»: tutti i dipendenti attivi con l'esito «Mancante», «Scaduto», «In scadenza» (entro 30 giorni), «In regola» o «Nessun DPI dovuto». "
                    "Una persona conta in ogni stato che ha: con un DPI scaduto e uno mancante è in entrambi i numeri, e l'esito mostra il più grave. Clicca un numero in alto per filtrare, un nome per aprire il dettaglio. «Da sistemare» dice cosa manca e se c'è già una richiesta in corso.",
                    "Un DPI è dovuto se la categoria ha «Obbligatoria nel report conformità» oppure se lo prevede la mansione di rischio della persona. "
                    "Nel dettaglio, la colonna «Perché» dice quale delle due: «Per tutti» o «Dalla mansione».",
                    "«Registro consegne»: cosa è stato consegnato, a chi e quando, con la ricevuta: «Firmata», «Confermata con badge», «Confermata via mail», «Da confermare», «Contestata» o «Senza firma». "
                    "Senza date scelte mostra gli ultimi 90 giorni.",
                    "Conformità, Registro consegne e Gestione richieste si filtrano anche per centro di costo; negli export di Conformità e Registro c'è la colonna.",
                    "«Consumi e magazzino»: consumi, coperture, cosa riordinare e consegne senza giacenza.",
                    "«Esporta Excel» ed «Esporta PDF» scaricano tutte le righe filtrate, non solo la pagina a video. Ogni scaricamento resta registrato.",
                    "Gli amministratori possono farli inviare da soli: Centro report → Pianificazioni, «Persone da sistemare» e «Ultimi 90 giorni».",
                ]),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Permessi",
            "blocchi": [
                ("ul", [
                    "Gestire (consegne, Banco consegne, magazzino, catalogo, impostazioni): ruoli RSPP e Amministrazione.",
                    "Il link della mail di conferma della ricevuta non chiede il login: vale solo per chi l'ha ricevuto e una volta.",
                    "Approvare: caporeparto e preposti, solo per i loro dipendenti (team dell'organigramma).",
                    "Si assegnano in Amministrazione → «Accessi» o in «Ruoli e permessi».",
                ]),
            ],
        },
        {
            "id": "scadenze",
            "titolo": "Promemoria delle scadenze",
            "blocchi": [
                ("p", "Ogni mattina alle 07:10 il task «dpi_expiry_reminders» controlla le consegne scadute o che scadono entro 30 "
                      "giorni (le consegne già sostituite da una nuova non contano)."),
                ("ul", [
                    "Referenti DPI («Responsabili» + «Email notifiche aggiuntive» delle Impostazioni) e indirizzi del task in "
                    "Automazioni → Task pianificati → «Configura mail»: ogni mattina l'elenco completo. Se non c'è nessun indirizzo, "
                    "va agli amministratori del portale.",
                    "Responsabile e preposto del dipendente: una mail con i DPI della propria squadra, solo nei giorni di avviso.",
                    "Dipendente: notifica nel portale, solo nei giorni di avviso.",
                    "Giorni di avviso: 30 giorni prima, 7 giorni prima, il giorno prima, il giorno della scadenza; se è scaduto, il "
                    "giorno dopo e poi ogni 7 giorni finché non viene sostituito.",
                ]),
                ("p", "A mano: comando send_dpi_expiry_reminders, prima con --dry-run."),
                ("p", "DPI → «Report» → «Conformità» mostra chi deve sistemare qualcosa."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": '«DPI scaduti» e «In scadenza» della dashboard non tornano con le richieste',
            "fare": [
                'Contano le consegne attive delle richieste della tua coda in «Gestione richieste»: clicca il numero e vedi la stessa lista '
                '(filtro «Scadenza»). Le consegne già sostituite non contano.',
            ],
        },
        {
            "sintomo": "Le scarpe non compaiono nel Banco consegne",
            "perche": "quelle fuori convenzione si chiudono con la fattura, quelle in convenzione entrano nel banco solo dopo l'ordine al negozio.",
            "fare": [
                "Apri DPI → «Scarpe»: la riga è in una delle tre sezioni.",
            ],
        },
        {
            "sintomo": "Il responsabile non vede la richiesta da approvare",
            "perche": "l'approvazione segue il team dell'organigramma (o il preposto del reparto).",
            "fare": [
                "Apri Anagrafica → Organigramma e controlla che il dipendente sia nel team del responsabile.",
                "Controlla che il responsabile abbia il permesso di approvare i DPI (Accessi o Ruoli e permessi).",
                "In alternativa un gestore Sicurezza può approvare dalla «Gestione richieste».",
            ],
        },
        {
            "sintomo": "La data di scadenza di un DPI è sbagliata",
            "fare": [
                "Apri Impostazioni e controlla la vita utile del modello: se è valorizzata vince su quella della categoria.",
                "Correggi e salva: le consegne in uso si riallineano subito.",
                "Se la scadenza era stata scritta a mano nella consegna, va corretta a mano.",
            ],
        },
        {
            "sintomo": "Un responsabile non riceve i promemoria delle scadenze della sua squadra",
            "perche": "arriva solo nei giorni di avviso e solo se il responsabile ha l'email di notifica nella sua scheda.",
            "fare": [
                "Controlla che il dipendente sia nell'area giusta (il responsabile è quello che approva le sue richieste).",
                "Controlla l'email di notifica nella scheda anagrafica del responsabile.",
                "Prova il comando send_dpi_expiry_reminders --dry-run: elenca i responsabili che riceverebbero la mail.",
            ],
        },
        {
            "sintomo": "La conferma di ricevuta va al caporeparto anche se il dipendente ha la mail",
            "perche": "la mail di notifica del dipendente non è di un dominio aziendale.",
            "fare": [
                "DPI → Impostazioni: controlla «Domini della mail aziendale» (es. azienda.it).",
                "Controlla la mail di notifica nella scheda anagrafica del dipendente.",
            ],
        },
        {
            "sintomo": "Il link della mail di conferma dice «Link non valido»",
            "perche": "dopo il promemoria vale solo l'ultimo link, oppure il link è stato copiato a metà.",
            "fare": ["Usa il link dell'ultima mail ricevuta («Promemoria: conferma la ricevuta dei DPI»)."],
        },
        {
            "sintomo": "Il magazzino non riceve la mail di consegna",
            "fare": [
                "DPI → Impostazioni: controlla che l'indirizzo email di Magazzino sia scritto bene.",
                "Amministrazione → «Log notifiche» per vedere se la notifica è partita.",
                "Se nessuna mail del portale parte, segui «Le mail non partono» nel Manuale di emergenza.",
            ],
        },
    ],
}
