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
        "id": "impostazioni",
        "titolo": "Impostazioni",
        "blocchi": [
            ("p", "Scheda «Impostazioni» (permesso «Ordini di produzione - Impostazioni»): i tipi di documento, con nome, "
                  "descrizione e ordine. Un tipo spento non si propone più, ma i documenti già registrati lo tengono."),
        ],
    },
]
