GUIDA = {
    "slug": "schede_sicurezza",
    "titolo": "Schede di sicurezza (SDS)",
    "area": "Sicurezza sul lavoro",
    "sintesi": "Le schede dei prodotti chimici: chi le deve leggere, conferma di lettura e QR sul contenitore.",
    "parole": "sds scheda sicurezza chimico chimici prodotto pittogrammi qr presa visione",
    "url": "schede_sicurezza:prodotto_list",
    "prefissi": ("/schede-sicurezza/",),
    "uso": [
        {
            "id": "leggere",
            "titolo": "Leggere e confermare le tue schede",
            "blocchi": [
                ("passi", [
                    "Apri Schede di sicurezza e clicca «Le mie SDS» (il numero dice quante sono da leggere).",
                    "In «Presa visione richiesta» clicca «Apri, leggi e conferma» sulla prima scheda.",
                    "Leggi la scheda, poi clicca «Confermo di aver letto la scheda».",
                    "Ripeti per le altre. Quelle già confermate sono in «SDS correnti gia' confermate».",
                ]),
                ("p", "Le schede da leggere dipendono dalla tua mansione. Se cambi mansione o esce una nuova versione, ti arriva una notifica."),
            ],
        },
        {
            "id": "qr",
            "titolo": "Il QR sul contenitore",
            "blocchi": [
                ("p", "Inquadrando il QR attaccato al contenitore si apre una pagina breve con pittogrammi di pericolo, frasi H e P, "
                      "DPI obbligatori, primo soccorso e incompatibilità. Funziona anche senza fare l'accesso. "
                      "Sull'etichetta, accanto al QR, ci sono già nome del prodotto e pittogrammi di pericolo."),
            ],
        },
        {
            "id": "cercare",
            "titolo": "Cercare un prodotto",
            "blocchi": [
                ("ul", [
                    "L'elenco «Prodotti chimici» è diviso per reparto. Filtra per reparto, famiglia o stato della scheda e clicca «Filtra».",
                    "Clicca un pittogramma di pericolo in alto per vedere solo i prodotti con quel pericolo.",
                    "Barra verde = scheda aggiornata; ambra = scheda più vecchia di 36 mesi («Da rivedere»); rossa = scheda mancante.",
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "prodotto",
            "titolo": "Aggiungere un prodotto e la sua scheda",
            "blocchi": [
                ("passi", [
                    "Clicca «Nuovo prodotto» e compila nome, produttore e mansioni di rischio che lo usano.",
                    "Salva, poi nel dettaglio carica il PDF della scheda («Carica SDS»).",
                    "Il portale legge la scheda e compila da solo pittogrammi, frasi H/P, primo soccorso e DPI. Controlla e correggi se serve.",
                    "Nel dettaglio clicca «Stampa etichetta 10×5»: esce un'etichetta con logo, nome, pittogrammi di pericolo e QR. "
                    "Stampala al 100% (dimensioni effettive) su carta 100 × 50 mm e attaccala al contenitore.",
                ]),
                ("nota", "Una nuova versione della scheda chiede di nuovo la conferma di lettura a tutte le persone interessate."),
            ],
        },
        {
            "id": "report",
            "titolo": "Controllare chi ha letto",
            "blocchi": [
                ("p", "«Report compliance»: prodotti senza scheda, prodotti senza mansioni e per ogni mansione la percentuale di persone "
                      "che hanno confermato. «Assegna mansioni» e «Carica SDS» portano dove sistemare; «Export CSV» scarica tutto."),
            ],
        },
        {
            "id": "mail",
            "titolo": "Mail al cambio mansione",
            "blocchi": [
                ("p", "La mail al dipendente quando cambia mansione la manda la regola AU56 del modulo Automazioni: se non parte, "
                      "controlla che la regola sia attiva."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Un dipendente non vede schede da leggere",
            "perche": "le schede dovute si calcolano dalla mansione attuale in Anagrafica.",
            "fare": [
                "In Anagrafica controlla la mansione del dipendente.",
                "Nel dettaglio del prodotto controlla che quella mansione sia tra le mansioni di rischio.",
                "Controlla che l'account del dipendente sia collegato alla sua anagrafica.",
            ],
        },
        {
            "sintomo": "Pittogrammi o frasi H/P non letti dal PDF",
            "perche": "la lettura automatica funziona solo se il PDF ha il testo (non una scansione).",
            "fare": [
                "Correggi a mano nel dettaglio del prodotto con il selettore dei pittogrammi.",
                "Per rifare la lettura sul server: comando estrai_sds <numero scheda>.",
            ],
        },
    ],
}
