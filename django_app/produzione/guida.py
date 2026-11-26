"""Guida d'uso della sezione Ordini di produzione (pulsante «? Guida» e PDF).

Le etichette sono quelle dei template ``produzione/elenco.html`` e ``produzione/scheda.html``;
se cambiano, va aggiornata anche ``core/guide_moduli/contenuti/produzione.py``.
"""
from __future__ import annotations

TITOLO = "Ordini di produzione"
SOTTOTITOLO = "Ogni P/N con i suoi OP e i suoi FAI; ogni OP con i documenti di produzione, i programmi CAM e CMM e le anomalie."

SEZIONI: list[dict] = [
    {
        "id": "cosa",
        "titolo": "A cosa serve",
        "blocchi": [
            ("p", "Gli OP sono un elenco unico, lo stesso di Gestione anomalie: la sezione non li copia, li legge. "
                  "Per ogni OP la scheda raccoglie quello che gli altri moduli sanno di quell'OP, così non serve "
                  "cercarlo modulo per modulo."),
            ("def", [
                ("Documenti registrati", "cicli, disegni, DIP, piani di controllo, certificati, rapporti di collaudo e "
                 "gli altri tipi decisi in Impostazioni, con revisione, data e cartella di rete."),
                ("FAI", "dal Registro FAI. Il FAI è del P/N, non del singolo OP: tutti gli OP dello stesso P/N "
                 "condividono gli stessi FAI e la stessa situazione (in regola, da verificare, da ripetere)."),
                ("Programmi CAM e CMM", "dalle righe del KICK-OFF dello stesso P/N, con codice, cartella e stato."),
                ("Anomalie", "quante sono e quante aperte, con il link a Gestione anomalie già filtrata sull'OP."),
            ]),
            ("p", "FAI, programmi e KICK-OFF seguono i permessi del modulo KICK-OFF: chi non li ha non li vede."),
        ],
    },
    {
        "id": "elenco",
        "titolo": "Elenco degli OP",
        "blocchi": [
            ("p", "«Ordini di produzione» nel menu Produzione. La tabella mostra gli OP dal più recente, con P/N, "
                  "capocommessa, CAR, stato e quanti documenti, FAI e anomalie aperte hanno. Cerca per OP, P/N, "
                  "capocommessa o CAR e filtra per stato; un clic sull'OP apre la sua scheda."),
            ("p", "«+ Nuovo OP» apre un pannello a lato: causale (OP, OG…), anno, numero, P/N, fase, capocommessa, CAR, "
                  "collaudo di benestare e note. Il titolo è causale/anno/numero e non può esistere già. Creato l'OP, si apre "
                  "la sua scheda. Le regole e le liste di capicommessa e CAR sono quelle di Gestione anomalie, che crea "
                  "nello stesso elenco. Serve il permesso «Ordini di produzione - Nuovo OP» (di default solo admin)."),
        ],
    },
    {
        "id": "pn",
        "titolo": "P/N",
        "blocchi": [
            ("p", "La scheda «P/N» è il catalogo di tutti i P/N: quelli degli OP, dei KICK-OFF e delle cartelle della share "
                  "Collaudo, anche senza OP nel portale. Per ogni P/N: descrizione e revisione, cliente, stato, OP (e quanti "
                  "aperti), ultimo OP, report CMM degli ultimi 12 mesi con la linea dei report per mese, Cpk peggiore, quote non "
                  "capaci (Cpk sotto 1,33), report con quote fuori negli ultimi 30 giorni, anomalie aperte, FAI e ultimo report. "
                  "I numeri dei report si aggiornano ogni ora con il giro dei report CMM; OP, anomalie e FAI sono sempre attuali."),
            ("p", "Stato: «Attivo» con report o OP aperti negli ultimi 12 mesi, «Fermo» senza attività recente, «Solo archivio» "
                  "se c'è solo la cartella Collaudo; si può fissare a mano (anche «Obsoleto») nell'anagrafica."),
            ("p", "«Mostra»: Tutti, Attivi, «Da guardare» (quote non capaci, report con fuori nell'ultimo mese, anomalie aperte, "
                  "FAI da ripetere o verificare; segnati con una riga rossa a sinistra), Con OP, «Con OP senza FAI», «Solo "
                  "archivio Collaudo». In più il filtro per cliente e l'ordine (più problemi prima, attività più recente, P/N). "
                  "La ricerca trova P/N, descrizione, cliente e anche un OP del P/N. I riquadri in alto sono cliccabili."),
            ("p", "«Aggiorna il catalogo» (con il permesso «Anagrafica P/N») crea subito gli articoli nuovi e ricalcola i "
                  "numeri, senza aspettare il giro."),
            ("p", "Anagrafica: nella scheda del P/N il pulsante «Anagrafica» apre il pannello con descrizione, cliente, "
                  "disegno, revisione, materiale, famiglia, stato e note. Descrizione, cliente e revisione vuoti si completano "
                  "da soli dal KICK-OFF e il cliente anche dal Registro FAI; quello scritto a mano non viene mai sovrascritto. "
                  "Ogni modifica finisce nel registro delle azioni."),
            ("p", "La scheda del P/N ha un indirizzo fisso, /produzione/pn/<P/N>/, che si può salvare o mandare. In alto la "
                  "striscia del percorso (KICK-OFF del P/N, Programmi CAM e CMM, FAI del P/N, OP del P/N) con lo stato di ogni "
                  "passo: ✓ fatto, numero arancione da fare, giallo in attesa, rosso da sistemare; il titolo apre il passo. "
                  "Sotto, le sezioni:"),
            ("def", [
                ("Panoramica", "«Da fare», una sola lista dalla più urgente (quote fuori nell'ultimo report, quote in deriva, "
                 "anomalie aperte, OP senza documenti, ognuna col suo pulsante); «Pezzi misurati per mese» (report CMM validi "
                 "degli ultimi 6 mesi, in rosso quelli con quote fuori); «Quote da tenere d'occhio» e gli OP."),
                ("OP", "tutti gli OP con CAR, stato, documenti e anomalie aperte; «Manca» e il numero delle anomalie portano "
                 "alla scheda dell'OP."),
                ("Report CMM", "i programmi CMM letti (con «Analisi quote») e gli ultimi 60 report, da spuntare per il "
                 "confronto; arrivando dalla mappa di «Quote CMM» solo i report di quella settimana («tutti» li rimostra)."),
                ("Qualità CMM", "a sinistra i programmi e le loro quote, dalla peggiore (icona rossa = fuori nell'ultimo "
                 "report, gialla = Cpk sotto 1,33 o in deriva, verde = capace, grigia = pochi pezzi per il Cpk) con il Cpk "
                 "accanto. Al centro la quota scelta: carta di controllo dei singoli valori sugli ultimi 30 pezzi validi "
                 "(fascia di tolleranza, LS e LI, media x̄, punti rossi = fuori, cerchiato l'ultimo pezzo), «Distribuzione», "
                 "Cpk, Cp, Media, σ, Fuori e Deriva, e una «Lettura» scritta dai numeri (dove lavora la media, la deriva, il "
                 "Cpk). «Tabella Cpk» elenca tutte le quote dal Cpk più basso; «Apri in Analisi quote» porta allo strumento completo."),
                ("Programmi", "i programmi CAM e CMM del KICK-OFF."),
                ("FAI", "la situazione per cliente (con la data «entro» cui ripeterlo), tutti i FAI del P/N con il loro OP e "
                 "il report CMM del primo articolo; «+ Nuovo FAI» apre la scheda FAI col P/N già scritto."),
            ]),
            ("p", "Il P/N nell'elenco degli OP e nella scheda dell'OP porta alla scheda del P/N."),
        ],
    },
    {
        "id": "percorso",
        "titolo": "Il percorso dell'OP",
        "blocchi": [
            ("p", "La scheda dell'OP è un percorso in cinque passi, nell'ordine in cui si lavora. Ogni passo dice "
                  "se è «Fatto», «Da fare», «In attesa» (tocca ad altri) o «Da gestire», e ha un solo pulsante che "
                  "porta all'azione già compilata."),
            ("def", [
                ("1 · KICK-OFF del P/N", "fatto se c'è un KICK-OFF dello stesso P/N; altrimenti «Nuovo KICK-OFF» con il P/N già scritto."),
                ("2 · Programmi CAM e CMM", "fatto quando tutte le righe CAM/CMM del KICK-OFF sono «Fatto»; in attesa se qualcuna è «Da fare»."),
                ("3 · Documenti di produzione", "fatto con almeno un documento registrato; «Aggiungi documento» apre il modulo."),
                ("4 · FAI del P/N", "conta il FAI più recente del P/N, anche se fatto su un altro OP: fatto se è a esito "
                 "positivo; in attesa se è eseguito e aspetta l'esito; «Da gestire» se l'articolo è da ripetere o, dopo un "
                 "FAI positivo, da verificare; senza FAI, «Nuovo FAI» con OP e P/N compilati. I FAI annullati non contano."),
                ("5 · Anomalie", "da gestire finché ci sono anomalie aperte sull'OP."),
            ]),
            ("p", "I passi stanno nella striscia in alto della scheda: ✓ fatto, numero arancione da fare, giallo in attesa, "
                  "rosso da gestire; il titolo apre l'azione. FAI, programmi e KICK-OFF compaiono solo a chi ha i permessi "
                  "del KICK-OFF."),
            ("p", "Nell'elenco, «Da sistemare» filtra gli OP con anomalie aperte, senza documenti o il cui P/N è senza FAI; nelle colonne "
                  "«Manca» porta alla sezione Documenti della scheda o alla sezione FAI del P/N."),
        ],
    },
    {
        "id": "scheda",
        "titolo": "La scheda dell'OP",
        "blocchi": [
            ("passi", [
                "In alto: capocommessa, CAR e stato; i numeri dell'OP (P/N, pezzi misurati, pezzi arrivati all'ultima fase "
                "senza quote fuori, pezzi con quote fuori, anomalie aperte, report CMM) e la striscia del percorso.",
                "Sezione «Pezzi»: la tabella «Pezzi e fasi» ha una riga per S/N e una colonna per fase di controllo (il "
                "programma CMM senza revisione, nell'ordine in cui compare la prima volta). Ogni cella è l'ultimo report "
                "di quel pezzo in quella fase: «OK», «al limite» (una quota oltre l'80% della tolleranza), «N fuori», «—» "
                "non misurato; ↻ vuol dire rimisurato. Un clic apre il report. Accanto al S/N le anomalie aperte. I report "
                "esclusi dall'analisi non contano. A destra «Cosa è successo» (report e documenti dal più recente) e gli "
                "altri OP dello stesso P/N.",
                "Sezione «Report CMM»: tutti i report dell'OP, da spuntare per il confronto.",
                "Sezione «Documenti»: premi «Aggiungi documento», scegli il tipo e indica titolo o numero, revisione, "
                "data e cartella o file di rete (\\\\server\\cartella). «Modifica» e «Elimina» su ogni riga.",
                "Sezione «FAI»: gli ultimi dieci FAI del P/N con l'OP su cui sono stati fatti; «+ Nuovo FAI del P/N» apre "
                "la scheda FAI con OP e P/N già compilati. Nella scheda FAI, «+ Nuovo OP» accanto al campo OP apre lo "
                "stesso pannello col P/N del FAI e mette l'OP creato nel campo.",
                "Sezione «Programmi»: i programmi CAM e CMM del KICK-OFF, che si cambiano dal KICK-OFF.",
            ]),
            ("p", "Aggiungere, cambiare ed eliminare i documenti richiede il permesso «Ordini di produzione - Documenti» "
                  "(di default solo admin, si assegna in Admin › ACL). Ogni modifica finisce nel registro delle azioni."),
        ],
    },
    {
        "id": "quote",
        "titolo": "Analisi quote dai report CMM",
        "blocchi": [
            ("p", "Il portale legge da solo i report CMM in PDF della cartella Collaudo (una cartella per P/N, dentro una "
                  "per OP) e ne tiene le misure: ogni ora i PDF nuovi o cambiati, senza toccare i file. Nella scheda del "
                  "P/N il riquadro «Report CMM» mostra «Quote da tenere d'occhio» (sugli ultimi 30 report di ogni "
                  "programma: fuori nell'ultimo report, poi Cpk sotto 1,33) e gli ultimi report; nella scheda dell'OP "
                  "ci sono i report di quell'OP."),
            ("p", "Si leggono sia i report di oggi sia quelli del formato vecchio (CALYPSO stampato con novaPDF, colonne "
                  "«Aktual», «pos Tol», «neg Tol», «<--|-->», fino al 2024, anche con la testata in italiano «Nome piano», "
                  "«No. di disegno»). I report vecchi già in elenco senza quote si rileggono da soli nei giri successivi: "
                  "finché non tocca a loro, la pagina del report dice «Report non ancora riletto con il lettore aggiornato». "
                  "Gli avvisi partono solo per i report degli ultimi 30 giorni, mai per quelli vecchi."),
            ("p", "«Analisi quote» (dalla scheda del P/N). In alto i filtri, che valgono per tutto quello che c'è sotto: "
                  "Programma (il «Part Program Name» senza revisione), Periodo (Tutto, 12 mesi, 90 giorni, 30 giorni, "
                  "«Dal… al…»), OP (uno o più, «Solo l'ultimo») ed «Evidenzia S/N», che segna un pezzo in tutte le viste. "
                  "Sotto, i numeri del programma: report, quote, misure fuori, quote andate fuori, quote con Cpk sotto "
                  "1,33 (un clic filtra l'elenco), ultimo report. Senza un periodo si vedono al massimo gli ultimi 800 "
                  "report."),
            ("p", "A sinistra l'elenco delle quote, raggruppate per titolo del report, con una mini linea degli ultimi 30 "
                  "valori e quante volte sono andate fuori (o il Cpk). Filtri: Tutte, Andate fuori, Cpk < 1,33, Vicine al "
                  "limite (ultima misura dentro ma oltre l'80% della tolleranza), Da verificare; «Cerca» per nome o "
                  "gruppo; «Ordina» come nel report, per volte fuori, Cpk peggiore, vicinanza al limite o nome. La "
                  "casella accanto a una quota la mette nel Confronto (fino a 6)."),
            ("def", [
                ("Quota", "statistiche (misure, fuori, media e scarto dal nominale, deviazione standard σ, Cp, Cpk con "
                 "Capace ≥ 1,33 / Al limite 1–1,33 / Non capace < 1, min÷max, ultima misura) e grafico con zona di "
                 "tolleranza, limiti, nominale e media; opzioni «% tolleranza», «±3σ», «Colori per OP» (i 3 OP più "
                 "recenti). Passando sul grafico si leggono S/N, OP, data e valore; clic evidenzia il S/N, doppio clic apre "
                 "il report, trascinare ingrandisce («Reimposta zoom»). Accanto la distribuzione dei valori, sotto la "
                 "tabella delle misure."),
                ("Mappa", "tutte le quote (con i filtri dell'elenco) per tutti i report: ogni casella è una misura, dal "
                 "grigio (centro della tolleranza) al blu (sotto) o al rosso (sopra) man mano che si avvicina al limite; "
                 "rosso pieno = fuori tolleranza. Clic su una casella: quella quota con quel S/N evidenziato."),
                ("Confronto", "le quote scelte sullo stesso grafico in % della loro tolleranza (0 = centro, ±100% = "
                 "limite), per vedere se si muovono insieme. «Le 4 più critiche» le sceglie da sé."),
                ("Pezzo", "tutte le quote di un S/N come barre in % della tolleranza, rosse se fuori; «Confronta con» "
                 "aggiunge un secondo S/N (rombo). Clic su una riga: l'andamento di quella quota."),
            ]),
            ("p", "Tolleranza usata: per le quote con nominale 0 e solo limite superiore (planarità, rotondità, "
                  "posizione, concentricità…) conta da 0 al limite, e il Cpk è (limite − media) / 3σ; per le altre conta "
                  "dal centro della zona di tolleranza. Una quota è il nome scritto nel report col suo nominale: se il "
                  "programma riusa lo stesso nome con un altro nominale sono due quote."),
            ("def", [
                ("Misure: Ultima per S/N / Tutte", "un S/N rimisurato (es. dopo una rilavorazione) conta una volta sola, con "
                 "l'ultima misura; «Tutte» le mostra tutte. Il riquadro «Rimisurati» dice quanti S/N sono stati misurati più volte."),
                ("Report", "spunta a mano i report da usare (o «Ultimi 10», «Ultimi 30», «Solo l'ultimo OP»); vale per tutte le viste."),
                ("Esclusi", "i report esclusi non contano; «Esclusi nascosti/mostrati» li fa rivedere (nel grafico il riquadro lo dice)."),
                ("In deriva", "retta sugli ultimi 20 pezzi: se si sposta di almeno il 20% della tolleranza, è oltre metà "
                 "tolleranza verso un limite e al ritmo attuale ci arriva entro 50 pezzi, la quota è «in deriva». Avviso giallo con "
                 "la stima dei pezzi, linea tratteggiata arancione sul grafico, filtro e riquadro «In deriva»."),
                ("Segnali", "regole di controllo statistico: punto oltre 3σ (cerchio), 9 punti di fila dallo stesso lato della media, 6 "
                 "di fila in salita o discesa (fascia gialla sotto l'asse). Sotto il grafico la tabella «Segnale / Dove / Cosa vuol dire»; "
                 "filtro «Con segnali», interruttore «Segnali»."),
                ("Eventi", "linee verticali sul grafico: il cambio di revisione del programma (dal report, tratteggiata grigia) e le note "
                 "scritte a mano (verde). «Note sulla quota»: scegli il S/N da cui vale, scrivi la nota (es. «cambiato inserto T12»), "
                 "«vale per tutte le quote» la mette su tutto il programma; la × la toglie (chi l'ha scritta)."),
                ("Anomalie", "una bandierina rossa sui pezzi che hanno una segnalazione in Gestione anomalie (stesso OP e S/N), "
                 "sbiadita se chiusa: passando sopra si leggono numero, stato e descrizione, clic apre Gestione anomalie su quell'OP."),
                ("Unisci un'altra quota a questa", "se la stessa caratteristica ha un altro nome (rinominata fra revisioni o misurata "
                 "in un altro programma del P/N) si unisce qui; ★ segna le quote con stesso nominale e tolleranze. «Unite qui» "
                 "elenca le unite, la × le separa. Serve il permesso «Gestire le quote CMM»."),
                ("PDF di capacità", "tabella Cp/Cpk e un grafico per quota con i filtri attivi: le quote spuntate per il Confronto, "
                 "altrimenti la quota aperta nella vista Quota, altrimenti quelle dell'elenco."),
            ]),
            ("p", "«Esporta CSV» scarica le misure con i filtri attivi (la quota scelta nella vista Quota, altrimenti le "
                  "quote dell'elenco). L'indirizzo della pagina conserva filtri e vista: si può copiare e mandare. "
                  "«Leggi i report» rilegge subito la cartella del P/N (in background: ricarica dopo qualche minuto)."),
            ("p", "«Quote CMM» (scheda della sezione): in alto P/N con report, P/N con fuori negli ultimi 30 giorni, quote con "
                  "Cpk sotto 1,33, quote in deriva e report letti oggi. La «Mappa qualità» ha una riga per P/N e una colonna per "
                  "settimana (ultime 12, «S» e numero della settimana): in ogni casella i report con quote fuori su quelli "
                  "misurati, verde senza fuori, giallo fino al 12%, rosa fino al 25%, rosso oltre; «·» nessun report. Clic su una "
                  "casella: i report di quel P/N in quella settimana; clic sul P/N: la sua Qualità CMM. Poi «Fuori ora», «Cpk < "
                  "1,33», «Deriva» e «Ultimo report»: questi tre li calcola il giro orario dei report (dopo un report nuovo o escluso), "
                  "finché non tocca a un P/N la riga dice «in calcolo». «Da guardare» mostra solo i P/N con fuori recenti o quote "
                  "in deriva. Sotto, "
                  "«Quote da guardare» di tutti questi P/N: fuori nell'ultimo report, poi in deriva, poi Cpk sotto 1,33."),
            ("p", "Escludere un report (prova, rilavorazione, doppione): nella pagina del report «Escludi dall'analisi», con motivo "
                  "e nota. Resta scritto chi e quando; «Riammetti» lo rimette. Il PDF non si tocca. Serve il permesso «Gestire le "
                  "quote CMM» (di default solo admin)."),
            ("p", "Avvisi: in Impostazioni › «Avvisi delle quote CMM» si sceglie chi li riceve (campanella del portale) e se "
                  "avvisare per i report nuovi con quote fuori e per le quote che vanno in deriva (al massimo un avviso al mese per "
                  "quota). Il FAI mostra il «Report CMM del primo articolo» del suo OP con il Cpk sui pezzi dopo."),
            ("p", "Il report (clic su un S/N) è un protocollo come quello della CMM. In alto il timbro «Esito»: NOK con "
                  "quote fuori, DA VERIFICARE se il calcolo e l'eccedenza stampata non coincidono, OK, ESCLUSO se tolto "
                  "dall'analisi; accanto P/N, S/N, OP, programma, data e quote (fuori, al limite, totale)."),
            ("p", "Sotto, il «Protocollo» in tre parti. A sinistra «Quote» per gruppo del report, con l'icona di ognuna (✓ "
                  "dentro, ! al limite oltre l'80% della tolleranza, ✕ fuori, ? da verificare): un clic porta alla quota. Al "
                  "centro la tabella nell'ordine del report: Nominale, Toll. sup, Toll. inf, Misurato, Deviazione (misurato − "
                  "nominale), «Grafico», «Fuori di» (di quanto supera il limite) e «Usata» (quanto della metà tolleranza è "
                  "consumato: 100% = al limite). Il grafico mostra la zona di tolleranza fra i due limiti, la fascia fino "
                  "all'80%, il nominale tratteggiato e la barra dal centro della tolleranza alla misura: verde dentro, gialla "
                  "al limite, rossa fuori; per forma e posizione parte da zero. Accanto alla quota «deriva» se va verso un limite."),
            ("p", "A destra il dettaglio della quota scelta (all'apertura la prima fuori): valori, «Pezzo prima», l'andamento "
                  "sugli ultimi 30 pezzi dello stesso programma con questo pezzo cerchiato, Cpk, Deriva e Fuori, «Analisi "
                  "quote» e «Apri anomalia». Si sceglie con un clic sulla riga o con le frecce ↑ ↓. I filtri «Tutte», "
                  "«Fuori», «Al limite» e «Cambiate dal pezzo prima» (oltre il 20% della tolleranza) restringono le righe; "
                  "«‹ S/N» e «S/N ›» passano al pezzo prima o dopo con lo stesso filtro; «Compatta» stringe le righe e il "
                  "browser lo ricorda. In alto «Confronta», «PDF originale» e «Apri segnalazione anomalia», che apre Gestione "
                  "anomalie sull'OP con il pannello «📄 Dal report CMM (PDF)» già pronto."),
            ("p", "Nelle pagine di dettaglio (report, pezzo, P/N, OP, confronto, Analisi quote) non ci sono le schede del "
                  "modulo: in alto il percorso «Ordini di produzione › P/N › OP» con i link e il pulsante «? Guida»."),
        ],
    },
    {
        "id": "statistica",
        "titolo": "Statistica di processo (Cpk, Ppk, rischio, segnali)",
        "blocchi": [
            ("p", "Le stesse formule valgono in tutte le pagine (report, scheda P/N, Analisi quote, Quote CMM, catalogo), sugli "
                  "ultimi 30 pezzi validi di ogni programma (Analisi quote: sui pezzi dei filtri scelti)."),
            ("def", [
                ("Cpk e Ppk", "Cpk = capacità della macchina, con la σ di breve periodo (differenze fra pezzi consecutivi, "
                 "«Sigma breve»); Ppk = quello che il processo ha fatto nel tempo, con la σ di tutti i pezzi. Se il Ppk è molto "
                 "più basso del Cpk la macchina è capace ma il processo si sposta (utensile, lotti, temperatura). Classifiche, "
                 "conteggi «non capaci» e «da guardare» usano il peggiore dei due."),
                ("Verdetto", "capace (almeno 1,33), al limite (da 1 a 1,33), non capace (sotto 1): si guarda il limite basso "
                 "dell'intervallo di confidenza al 95%, scritto accanto (es. «0,65–1,18»). Sotto 25 pezzi «pochi dati»."),
                ("Forma e posizione", "planarità, rotondità, posizione, concentricità (nominale 0, solo limite superiore) non "
                 "hanno una distribuzione normale: indice col metodo dei percentili (ISO 22514-2), segnato «percentili»."),
                ("Rischio", "probabilità che il prossimo pezzo esca, dal livello attuale della quota (media mobile EWMA, più la "
                 "deriva) e dalla sua dispersione. Rosso dal 10%, giallo dall'1%."),
                ("Limiti di controllo", "LCS e LCI = media ± 3σ di breve periodo: dove il processo resta se nulla cambia; sono "
                 "diversi dai limiti di tolleranza LS e LI del disegno. In Analisi quote l'interruttore «Limiti di controllo»."),
                ("Segnali", "regole di Nelson: oltre 3σ; 9 punti dallo stesso lato; 6 in salita o discesa; 14 a zig-zag; 2 su 3 "
                 "oltre 2σ; 4 su 5 oltre 1σ; 15 vicini alla media; 8 lontani dalla media; e «Spostamento (EWMA)» per gli "
                 "spostamenti piccoli. Ognuno dice cosa vuol dire."),
                ("Il processo è cambiato", "il punto dove la media è cambiata di almeno 1σ (linea arancione tratteggiata sulla "
                 "carta), con la media prima e dopo e il pezzo da cui parte."),
                ("Deriva", "retta sugli ultimi 20 pezzi; ora con la forchetta al 95% dei pezzi al limite (es. «12 – 59 pezzi»)."),
                ("Si muove insieme a", "quote dello stesso programma che salgono e scendono insieme (correlazione almeno 0,7 su "
                 "almeno 15 pezzi in comune): probabilmente una causa sola."),
                ("Gli OP sono diversi?", "test di Kruskal-Wallis fra gli OP con almeno 5 pezzi: «Sì» se p < 0,05, con l'indice di "
                 "ogni OP dal peggiore."),
                ("Quanto sbaglia la misura", "dalle rimisure dello stesso pezzo entro 2 giorni, quando la prima misura non aveva "
                 "quote fuori: quanta tolleranza consuma la sola misura (6σ / tolleranza). Oltre il 30% il problema è il "
                 "metodo di misura, non il pezzo. Servono almeno 5 coppie."),
            ]),
            ("p", "«Quote CMM»: «Salute» del P/N da 0 a 100 (si parte da 100 e si toglie fino a 40 per il rischio, 10 per ogni quota "
                  "fuori nell'ultimo report fino a 20, 5 per ogni quota non capace fino a 25, 2 per ogni quota al limite fino a 10, "
                  "5 per ogni quota in deriva fino a 15; verde da 80, giallo da 50); la tabella parte dalla salute più bassa. "
                  "«Anomalie da aprire»: report degli ultimi 30 giorni con quote fuori, non esclusi, senza una segnalazione aperta "
                  "per lo stesso S/N, con «Apri anomalia» già compilata; i report vecchi riletti non compaiono. Lo stesso link "
                  "arriva nell'avviso «Anomalia da aprire». «Stessa caratteristica su P/N diversi»: scrivi «Ø40 H7» o "
                  "«planarità» e confronta Cpk, Ppk e rischio della stessa quota su tutti i P/N."),
        ],
    },
    {
        "id": "pezzo",
        "titolo": "Pagina del pezzo (S/N)",
        "blocchi": [
            ("p", "Tutto quello che è successo a un pezzo. Si apre con un clic sul S/N nel titolo del report, da «Pagina del "
                  "pezzo» in «Altri report dello stesso S/N» e dal S/N nella tabella «Pezzi e fasi» della scheda dell'OP. Lo "
                  "stesso pezzo scritto in modi diversi (SN-7, SN7, sn 7) è riconosciuto come uno solo."),
            ("p", "In alto il timbro «Stato pezzo»: NOK se l'ultimo report di almeno una fase ha quote fuori (una rimisura "
                  "in tolleranza sostituisce la misura fuori, e la riga sotto dice quali fasi sono NOK), altrimenti OK; poi "
                  "P/N, OP, fasi misurate e report, ultimo report, quote fuori almeno una volta, anomalie e se è il primo "
                  "articolo del FAI."),
            ("p", "Il «Multi-protocollo» è una matrice: una riga per quota (per gruppo del report), una colonna per report dal "
                  "più vecchio (al massimo gli ultimi 12; «R» = rimisura della stessa fase) e «Δ ultimo − primo». Ogni "
                  "casella è colorata dalla tolleranza usata: fino al 50%, 50-80%, oltre l'80% (al limite), fuori; «% "
                  "tolleranza usata», «Deviazione» e «Valore misurato» cambiano il numero scritto (il browser ricorda la "
                  "scelta). Clic su una casella: il report a quella quota. Filtri «Fuori almeno una volta» e «Cambiate fra i "
                  "report» (oltre il 20% della tolleranza). A sinistra «Report del pezzo» (tutti, con rimisure ed esclusi), "
                  "«Anomalie» che citano il S/N e «Stesso OP», gli altri pezzi dell'OP con il loro esito."),
            ("p", "«Confronta le fasi» apre il Confronto report sugli ultimi 6 report del pezzo. «Scheda pezzo (PDF)» "
                  "scarica la scheda con l'elenco dei report e le quote degli ultimi 6, da allegare o mandare al cliente."),
        ],
    },
    {
        "id": "confronto",
        "titolo": "Confronto report",
        "blocchi": [
            ("p", "Affianca da 2 a 6 report, quota per quota. Negli elenchi dei report (scheda del P/N, scheda dell'OP, «Altri "
                  "report dello stesso S/N») spunta le righe: compare la barra «N report scelti» con «Confronta». Dal report "
                  "ci sono anche «Confronta» (pezzo prima e dopo) e «Confronta le fasi» (stesso S/N in tutti i programmi)."),
            ("p", "Ogni colonna è un report, con il suo colore; le quote si allineano per nome e nominale e quelle unite in "
                  "Analisi quote stanno sulla stessa riga anche fra programmi diversi. «Δ ultimo − primo» è la differenza fra "
                  "l'ultimo e il primo report che misurano la quota, anche in % della tolleranza; la barra mostra dove cade "
                  "ogni report. Prima le quote fuori, poi quelle che cambiano più del 20% della tolleranza."),
            ("p", "«Confronti pronti»: «Stesso S/N, tutte le fasi», «Primo articolo e ultimi pezzi» (il primo report dell'OP "
                  "con gli ultimi tre dello stesso programma), «Pezzo prima e dopo». «Che cambiano o fuori» nasconde il resto; "
                  "«Esporta CSV» scarica la tabella per Excel."),
        ],
    },
    {
        "id": "impostazioni",
        "titolo": "Impostazioni",
        "blocchi": [
            ("p", "Scheda «Impostazioni» (permesso «Ordini di produzione - Impostazioni»): i tipi di documento, con nome, "
                  "descrizione e ordine. Un tipo spento non si propone più, ma i documenti già registrati lo tengono."),
            ("p", "«Avvisi delle quote CMM»: report nuovi con quote fuori tolleranza, quote in deriva, e chi riceve gli avvisi. "
                  "Nessuno scelto = nessun avviso."),
        ],
    },
]
