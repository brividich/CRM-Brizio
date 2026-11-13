GUIDA = {
    "slug": "notizie",
    "titolo": "Notizie e comunicazioni",
    "area": "Per tutti",
    "sintesi": "Le comunicazioni aziendali: si leggono qui e, quando è richiesto, si conferma di averle lette.",
    "parole": "notizia notizie comunicazione comunicazioni avviso circolare conferma lettura",
    "url": "notizie_lista",
    "prefissi": ("/notizie/",),
    "uso": [
        {
            "id": "leggere",
            "titolo": "Leggere le comunicazioni",
            "blocchi": [
                ("passi", [
                    "Apri Notizie: vedi «Notizie e comunicazioni». Le schede in alto filtrano: «Da leggere», «Da confermare», «Da riconfermare» (notizie aggiornate dopo la tua conferma), «Confermate», «Obbligatorie»; il numero accanto dice quante sono. «Cerca nel titolo o nel testo» trova una notizia per parola.",
                    "Clicca una notizia per leggerla. Sotto il testo ci sono gli allegati.",
                    "PDF e immagini si aprono nell'anteprima a destra della notizia: «Anteprima» su un allegato lo mostra lì, «Schermo intero» lo apre in una nuova scheda, «Scarica» lo salva. Gli altri file (Word, Excel, ZIP…) si scaricano. Sul telefono il PDF si apre con «Apri il PDF».",
                    "Clicca «Confermo di aver letto e compreso» nella barra in fondo alla notizia.",
                ]),
                ("p", "Se hai comunicazioni obbligatorie da confermare il portale ti porta a «Comunicazioni obbligatorie da confermare»: clicca «Leggi e conferma» su ognuna."),
            ],
        },
    ],
    "admin": [
        {
            "id": "pubblicare",
            "titolo": "Pubblicare una notizia",
            "blocchi": [
                ("passi", [
                    "Apri «Dashboard Notizie» (pagina «Gestione notizie») e clicca «+ Nuova notizia».",
                    "Scrivi titolo e testo; una riga vuota separa i paragrafi. «Anteprima» mostra la notizia come la leggeranno.",
                    "In «Allegati» trascina i file nel riquadro o cliccalo per sceglierli, anche più file insieme. «+ Aggiungi un link esterno» aggiunge un indirizzo web.",
                    "In «Destinatari» clicca i ruoli che la devono vedere. Se non scegli nessun ruolo la vedono tutti.",
                    "Accendi «Obbligatoria» se chi la riceve deve confermarla prima di continuare a usare il portale.",
                    "Clicca «Salva bozza» per finirla dopo, oppure «Salva e pubblica».",
                ]),
                ("p", "Su una notizia già pubblicata «Salva e pubblica» crea una nuova versione e chiede di nuovo la conferma a tutti; «Salva bozza» la toglie dalla pubblicazione finché non la ripubblichi. Negli allegati già caricati puoi cambiare il nome o cliccare «Rimuovi»."),
                ("p", "In «Gestione notizie» le schede Bozze / Pubblicate / Archiviate filtrano l'elenco; per ogni notizia pubblicata la barra dice quanti hanno confermato su quanti la ricevono."),
            ],
        },
        {
            "id": "report",
            "titolo": "Chi ha letto",
            "blocchi": [
                ("p", "«Report Letture» mostra per ogni notizia chi l'ha letta e confermata; «Esporta CSV» scarica l'elenco."),
            ],
        },
        {
            "id": "permessi",
            "titolo": "Chi può pubblicare",
            "blocchi": [
                ("p", "«Gestione notizie» → «Permessi» (pannello laterale) oppure Notizie → «Impostazioni»: «Salva permessi» decide chi entra nella "
                      "dashboard di gestione. Con il sistema «Ruoli e permessi» acceso conta il permesso «gestire» su Notizie "
                      "(ruoli Gestione personale, Amministrazione e RSPP)."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": 'La conformità in Impostazioni è più bassa di prima',
            "fare": [
                "Ora conta le conferme della versione corrente sui destinatari delle notizie obbligatorie pubblicate (chi non l'ha mai aperta conta come non conforme), come il riepilogo per notizia.",
            ],
        },
        {
            "sintomo": "Una persona non vede la notizia",
            "fare": [
                "Apri la notizia in modifica e controlla «Destinatari»: la persona deve avere uno dei ruoli scelti.",
                "Controlla che la notizia sia pubblicata e non archiviata.",
            ],
        },
        {
            "sintomo": "Il PDF non si vede nell'anteprima",
            "fare": [
                "Clicca «Schermo intero» o «Scarica»: alcuni browser (e i telefoni) non mostrano i PDF dentro la pagina.",
                "L'anteprima vale solo per PDF e immagini (PNG, JPG, GIF, WEBP); gli altri file si scaricano.",
            ],
        },
        {
            "sintomo": "Un allegato non si scarica",
            "fare": [
                "Gli allegati si scaricano solo dal portale e solo da chi vede la notizia.",
                "Se l'errore è «file non trovato», controlla nel .env il percorso PRIVATE_ATTACHMENTS_ROOT e che la cartella esista sul server.",
            ],
        },
    ],
}
