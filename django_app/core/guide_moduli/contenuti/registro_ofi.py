GUIDA = {
    "slug": "registro_ofi",
    "titolo": "Registro OFI / NC",
    "area": "Qualità e sistema di gestione",
    "sintesi": "Opportunità di miglioramento e non conformità (MOD.174): dashboard, registro, le mie voci, PDCA fino alla chiusura.",
    "parole": "ofi nc non conformita opportunita miglioramento mod174 pdca registro rilievi car azione correttiva",
    "url": "registro_ofi:home",
    "prefissi": ("/ofi-registro/",),
    "dettaglio": [
        ("Guida Registro OFI", "registro_ofi:guida"),
    ],
    "uso": [
        {
            "id": "cosa",
            "titolo": "Cosa c'è nel modulo",
            "blocchi": [
                ("p", "«Registro OFI» nel menu Qualità. Il menu interno ha Dashboard, Registro MOD.174, Le mie voci, "
                      "+ Nuovo inserimento (a chi può inserire) e Guida."),
                ("def", [
                    ("Dashboard", "«Il mio lavoro» con le tue voci aperte; a chi consulta il registro anche scadute, in "
                     "scadenza entro 30 giorni, senza responsabile, origine delle voci, voci per processo del catalogo, "
                     "andamento e attività recente."),
                    ("Registro MOD.174", "tutte le voci con le colonne del modulo Excel, filtri ed «Esporta Excel»."),
                    ("Le mie voci", "le voci di cui sei responsabile, aperte e chiuse."),
                    ("Scheda della voce", "collegamenti (da dove nasce, processo del catalogo, CAR), avanzamento PDCA, "
                     "evidenze e cronologia."),
                ]),
            ],
        },
        {
            "id": "collegamenti",
            "titolo": "Come si collega al resto del portale",
            "blocchi": [
                ("ul", [
                    "Audit interni: ogni OFI o NC registrata in «Compila verifica» crea la voce; la scheda della voce porta "
                    "al rilievo dell'audit.",
                    "Audit degli enti: ogni rilievo dell'audit esterno è una voce con fonte l'ente.",
                    "Specifiche: le righe MOD.133 con impatto creano la voce.",
                    "Catalogo processi: la voce si lega al processo quando il «Processo/area» lo indica (codice, nome o "
                    "«codice - nome») o scegliendo «Processo del catalogo». La scheda del processo ha la scheda «OFI / NC» "
                    "con le sue voci e «Nuova OFI / NC su questo processo»; le voci dei rilievi degli enti alzano la "
                    "priorità degli audit del processo.",
                    "Azione correttiva MT CN 11: dalla scheda della voce; con una CAR aperta la voce si chiude chiudendo la CAR.",
                ]),
            ],
        },
        {
            "id": "lavoro",
            "titolo": "Seguire una voce di cui sei responsabile",
            "blocchi": [
                ("passi", [
                    "Apri «Le mie voci» (o «Il mio lavoro» nella dashboard) e clicca il numero della voce.",
                    "In «Stato PDCA» scrivi cosa è stato fatto nella fase in corso e premi «Passa a …» (in Act «Chiudi la voce»).",
                    "In «Evidenze» carica i documenti con «Carica».",
                    "Se la verifica non è superata usa «La verifica non è superata: riapri in PLAN» e scrivi il motivo.",
                ]),
                ("nota", "Le voci scadute ricevono un sollecito email: la scadenza è la «DATA REQUIRED»."),
            ],
        },
    ],
    "admin": [
        {
            "id": "permessi",
            "titolo": "Permessi",
            "blocchi": [
                ("ul", [
                    "«Registro OFI - Consulta registro e dashboard»: registro, dashboard completa ed export. Alla prima "
                    "installazione è stato dato a chi aveva «Specifiche - Visualizza», che prima apriva il registro.",
                    "«Registro OFI - Le mie voci»: a tutti i ruoli; apre solo le voci di cui si è responsabili.",
                    "«Registro OFI - Inserisci/Modifica» (modulo Specifiche): crea e modifica le voci.",
                    "Il responsabile di una voce la vede, la fa avanzare, la riapre e carica evidenze anche senza gli altri permessi.",
                    "Permessi di pagina: Amministrazione → Accessi, modulo Registro OFI / NC.",
                    "I solleciti vanno al responsabile e agli indirizzi di GESTIONE_SPECIFICHE «OFI_REMINDER_EMAILS».",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una voce non compare nella scheda del processo",
            "fare": [
                "Il «Processo/area» della voce non indica un solo processo del catalogo: apri la voce, «Modifica» e "
                "scegli «Processo del catalogo».",
                "Nel registro il filtro «Senza processo del catalogo» elenca le voci da collegare.",
            ],
        },
        {
            "sintomo": "Un responsabile riceve «Accesso negato» sulla voce",
            "fare": [
                "Controlla che sia indicato come «Responsabile (utente)» della voce.",
                "Controlla che il suo ruolo abbia «Registro OFI - Le mie voci».",
            ],
        },
        {
            "sintomo": "Il pulsante «Passa a …» non compare o la voce non si chiude",
            "fare": [
                "Il pulsante compare a chi gestisce il registro e al responsabile della voce.",
                "Per chiudere una fase va scritto cosa è stato fatto in quella fase.",
                "Se c'è una CAR aperta la voce si chiude chiudendo la CAR, dopo la verifica di efficacia.",
            ],
        },
    ],
}
