"""Guida d'uso della sezione Ordini di produzione (pulsante «? Guida» e PDF).

Le etichette sono quelle dei template ``produzione/elenco.html`` e ``produzione/scheda.html``;
se cambiano, va aggiornata anche ``core/guide_moduli/contenuti/produzione.py``.
"""
from __future__ import annotations

TITOLO = "Ordini di produzione"
SOTTOTITOLO = "Ogni OP con i suoi documenti di produzione: FAI, programmi CAM e CMM, documenti registrati e anomalie."

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
                ("FAI", "dal Registro FAI: prima quelli che citano l'OP, poi gli altri FAI dello stesso P/N."),
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
        "id": "scheda",
        "titolo": "La scheda dell'OP",
        "blocchi": [
            ("passi", [
                "In alto: P/N, capocommessa, CAR e stato dell'OP, con il link alle anomalie.",
                "«Documenti registrati»: premi «Aggiungi documento», scegli il tipo e indica titolo o numero, revisione, "
                "data e cartella o file di rete (\\\\server\\cartella). «Modifica» e «Elimina» su ogni riga.",
                "«FAI»: «Nuovo FAI per questo OP» apre la scheda FAI con OP e P/N già compilati. Nella scheda FAI, "
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
