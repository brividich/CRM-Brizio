GUIDA = {
    "slug": "checklist_operativa",
    "titolo": "Checklist operativa",
    "area": "Produzione e operations",
    "sintesi": "La checklist di chiusura aziendale (ferie, Natale): ognuno conferma i compiti che gli sono assegnati.",
    "parole": "checklist chiusura ferie natale compiti conferma mansioni vice",
    "url": "checklist_operativa:gestione",
    "prefissi": ("/checklist-operativa/",),
    "uso": [
        {
            "id": "confermare",
            "titolo": "Confermare i tuoi compiti",
            "blocchi": [
                ("passi", [
                    "Apri Checklist operativa: vedi i compiti assegnati a te per la chiusura in corso.",
                    "Quando hai fatto un compito clicca «Confermo».",
                    "Se ti accorgi che manca un compito, scrivilo e clicca «Invia proposta»: lo valuta chi gestisce la checklist.",
                ]),
                ("p", "Se sei il vice di un responsabile, vedi anche i suoi compiti, segnati come «vice», e puoi confermarli tu se lui è assente."),
                ("nota", "Riceverai promemoria 7, 3, 1 giorno prima e il giorno stesso della scadenza finché ci sono compiti non confermati."),
            ],
        },
    ],
    "admin": [
        {
            "id": "mansioni",
            "titolo": "Preparare i compiti tipo (mansioni template)",
            "blocchi": [
                ("passi", [
                    "Apri «Configurazione» e clicca «+ Nuova mansione».",
                    "Scrivi il compito, scegli il reparto dal catalogo, il responsabile ed eventuali vice.",
                    "Salva. Il compito sarà copiato in ogni nuova chiusura.",
                ]),
            ],
        },
        {
            "id": "evento",
            "titolo": "Aprire una chiusura (evento)",
            "blocchi": [
                ("passi", [
                    "In «Configurazione» clicca «+ Nuovo evento», indica nome e date.",
                    "Clicca «Crea evento e genera checklist»: i compiti attivi vengono creati subito.",
                    "Per un compito in più usa «+ Aggiungi voce» nella scheda dell'evento.",
                    "A chiusura finita clicca «Chiudi evento»: diventa archivio. Si può riaprire con «Riapri evento».",
                ]),
                ("p", "«Proposte in attesa» raccoglie i compiti proposti dai dipendenti: «Conferma decisione» li accetta o li scarta."),
                ("p", "«Riepilogo» mostra lo storico delle chiusure con la percentuale completata e il PDF da archiviare."),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Permessi",
            "blocchi": [
                ("p", "La configurazione richiede il permesso «checklist_operativa.configurazione.manage» (Amministrazione → Accessi). "
                      "La pagina dei compiti è aperta a tutti quelli che hanno fatto l'accesso."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona non vede il suo compito",
            "fare": [
                "Apri l'evento in Configurazione e controlla responsabile e vice della voce.",
                "Se il compito tipo è stato aggiunto dopo la creazione dell'evento, aggiungilo con «+ Aggiungi voce».",
            ],
        },
        {
            "sintomo": "Non partono i promemoria",
            "fare": [
                "Controlla che l'evento sia aperto (non chiuso).",
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla il promemoria della checklist.",
                "Controlla in Anagrafica l'email di notifica del responsabile.",
            ],
        },
    ],
}
