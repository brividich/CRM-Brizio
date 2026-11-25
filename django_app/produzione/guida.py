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
            ("p", "La scheda «P/N» elenca i P/N degli OP: il P/N è l'articolo principale e ha più OP. Per ogni P/N: quanti OP, "
                  "l'ultimo OP con il suo stato, il capocommessa, quanti FAI, la «Situazione FAI» e le anomalie aperte di tutti "
                  "i suoi OP. La ricerca trova il P/N anche da un suo OP, capocommessa o CAR, e conta comunque tutti i suoi OP."),
            ("p", "«Da sistemare» filtra i P/N «Con anomalie aperte», quelli «Senza FAI» e quelli con «FAI da ripetere o "
                  "verificare»."),
            ("p", "La scheda del P/N è un percorso in quattro passi:"),
            ("def", [
                ("1 · KICK-OFF del P/N", "come nella scheda dell'OP."),
                ("2 · Programmi CAM e CMM", "come nella scheda dell'OP."),
                ("3 · FAI del P/N", "la situazione per cliente (con la data «entro» cui ripeterlo) e tutti i FAI del P/N con il "
                 "loro OP; «+ Nuovo FAI per questo P/N» apre la scheda FAI col P/N già scritto."),
                ("4 · OP del P/N", "tutti gli OP con CAR, stato, documenti e anomalie aperte; «Manca» e il numero delle "
                 "anomalie portano al passo della scheda dell'OP."),
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
            ("p", "In cima, «Prossimo passo» mostra il primo passo da fare (o da gestire) con il suo pulsante; se restano "
                  "solo attese mostra la prima attesa; quando è tutto a posto compare «Percorso completo». FAI, programmi e "
                  "KICK-OFF compaiono solo a chi ha i permessi del KICK-OFF."),
            ("p", "Nell'elenco, «Da sistemare» filtra gli OP con anomalie aperte, senza documenti o il cui P/N è senza FAI; nelle colonne "
                  "«Manca» e il numero delle anomalie aperte portano dritti al passo della scheda."),
        ],
    },
    {
        "id": "scheda",
        "titolo": "La scheda dell'OP",
        "blocchi": [
            ("passi", [
                "In alto: P/N, capocommessa, CAR e stato dell'OP, poi «Prossimo passo» e i cinque passi.",
                "«Documenti registrati»: premi «Aggiungi documento», scegli il tipo e indica titolo o numero, revisione, "
                "data e cartella o file di rete (\\\\server\\cartella). «Modifica» e «Elimina» su ogni riga.",
                "«FAI del P/N»: gli ultimi dieci FAI del P/N con l'OP su cui sono stati fatti; «Scheda del P/N» per tutti, "
                "«+ Nuovo FAI del P/N» apre la scheda FAI con OP e P/N già compilati. Nella scheda FAI, "
                "«+ Nuovo OP» accanto al campo OP apre lo stesso pannello col P/N del FAI e mette l'OP creato nel campo.",
                "«Programmi CAM e CMM» e «KICK-OFF del P/N»: si aprono e si cambiano dal KICK-OFF.",
                "«Altri OP dello stesso P/N»: per passare a un OP precedente o successivo.",
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
            ("p", "«Esporta CSV» scarica le misure con i filtri attivi (la quota scelta nella vista Quota, altrimenti le "
                  "quote dell'elenco). L'indirizzo della pagina conserva filtri e vista: si può copiare e mandare. "
                  "«Leggi i report» rilegge subito la cartella del P/N (in background: ricarica dopo qualche minuto)."),
            ("p", "Dal report (clic su un S/N): le quote fuori tolleranza, «Andamento» per ciascuna, «Apri il PDF» e "
                  "«Apri segnalazione anomalia», che apre Gestione anomalie sull'OP con il pannello «📄 Dal report CMM "
                  "(PDF)» già pronto."),
        ],
    },
    {
        "id": "impostazioni",
        "titolo": "Impostazioni",
        "blocchi": [
            ("p", "Scheda «Impostazioni» (permesso «Ordini di produzione - Impostazioni»): i tipi di documento, con nome, "
                  "descrizione e ordine. Un tipo spento non si propone più, ma i documenti già registrati lo tengono."),
        ],
    },
]
