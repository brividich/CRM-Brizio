"""Centro guide: Presenti in azienda (timbrature Solari)."""

GUIDA = {
    "slug": "presenti",
    "titolo": "Presenti in azienda",
    "area": "Persone e HR",
    "sintesi": "Chi è in azienda adesso dalle timbrature, appello di evacuazione condiviso, uscite non timbrate.",
    "parole": "presenti presenze timbrature solari badge evacuazione appello punto di raccolta emergenza uscita "
              "dimenticata cn-presenze preposto antincendio primo soccorso",
    "url": "presenti:home",
    "prefissi": ("/presenti/",),
    "dettaglio": [
        ("Guida Presenti in azienda", "presenti:guida"),
    ],
    "uso": [
        {
            "id": "lista",
            "titolo": "La lista dei presenti",
            "blocchi": [
                ("p", "«Presenti in azienda» nel menu Persone. Una persona è presente quando la sua ultima timbratura "
                      "di oggi è un'entrata. La tabella si aggiorna da sola ogni 30 secondi; le timbrature si leggono al "
                      "massimo una volta al minuto."),
                ("ul", [
                    "Contatori in alto: presenti e, per incarico di sicurezza, quanti sono in azienda.",
                    "Ricerca per nome, matricola o reparto; filtri per reparto e incarico.",
                    "«PDF»: la lista nel formato del vecchio CN-PRESENZE, senza ora di entrata.",
                    "Pallino verde «In azienda» accanto al nome in Anagrafica (elenco dipendenti e scheda) "
                    "e fra i dipendenti trovati con la ricerca in alto (Ctrl+K).",
                ]),
            ],
        },
        {
            "id": "appello",
            "titolo": "Appello di evacuazione",
            "blocchi": [
                ("passi", [
                    "«Appello di evacuazione» → «Avvia appello adesso» (segna «È un'esercitazione» per le prove).",
                    "Al punto di raccolta tocca ogni persona trovata: diventa verde con ora e nome di chi l'ha contata.",
                    "Più persone contano insieme: le spunte degli altri arrivano entro 3 secondi; «Da trovare» resta in cima.",
                    "«Chiudi appello» a fine conta; «Stampa» dà il PDF con la colonna «CONTATO».",
                ]),
                ("nota", "L'appello comprende solo chi timbra: visitatori e fornitori vanno contati dal registro accessi."),
            ],
        },
        {
            "id": "uscite",
            "titolo": "Uscite non timbrate",
            "blocchi": [
                ("p", "Le giornate chiuse con un'entrata e senza uscita. Il capo vede la sua squadra e ogni mattina alle "
                      "7:30 (lunedì-sabato) riceve notifica e mail con le giornate nuove degli ultimi 3 giorni."),
            ],
        },
    ],
    "admin": [
        {
            "id": "config",
            "titolo": "Configurazione",
            "blocchi": [
                ("def", [
                    ("Collegamento Solari", "chiavi SOLARI_DB_* nel .env del server (login con sola lettura); con ODBC Driver 18 "
                     "anche SOLARI_DB_ENCRYPT=1 e SOLARI_DB_TRUST_CERT=1; riavvio del portale."),
                    ("Permessi", "lista, appello e uscite della squadra a tutti i ruoli; «Uscite non timbrate (tutti)» e "
                     "«Impostazioni» solo admin (Accessi › permessi del modulo Presenti in azienda)."),
                    ("PDF su SharePoint", "Presenti › Impostazioni: ogni 30 minuti, raccolta e nome file configurabili; "
                     "usa le credenziali Graph del portale."),
                    ("Avvisi uscite", "Presenti › Impostazioni, casella dell'avviso mattutino al capo."),
                    ("Incarichi di sicurezza", "dall'organigramma ISO 45001 in Anagrafica; import una tantum dal vecchio "
                     "config.ini con «manage.py importa_incarichi_presenze --ini <file>» (poi --apply)."),
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "«Database timbrature Solari non configurato»",
            "perche": "mancano le chiavi SOLARI_DB_* nel file .env del server.",
            "fare": ["Compila le chiavi SOLARI_DB_* nel .env (login con sola lettura).", "Riavvia il portale."],
        },
        {
            "sintomo": "«Il database delle timbrature non risponde»",
            "perche": "il server Solari non è raggiungibile o il login è stato cambiato.",
            "fare": ["Aspetta un minuto: la pagina riprova da sola.",
                     "Se dura, controlla la rete verso l'istanza Solari e utente/password nel .env."],
        },
        {
            "sintomo": "Una persona presente non ha il link alla scheda",
            "perche": "il codice fiscale in Solari e in Anagrafica non coincide.",
            "fare": ["Correggi il codice fiscale nella scheda dipendente (dati civili) o in Solari."],
        },
        {
            "sintomo": "Un incarico di sicurezza non compare",
            "fare": ["In Anagrafica controlla che il ruolo sia nell'ambito «Sicurezza ISO 45001».",
                     "Controlla che l'assegnazione non abbia una data di fine passata."],
        },
        {
            "sintomo": "Il PDF su SharePoint non si aggiorna",
            "fare": ["Apri Presenti › Impostazioni e leggi «Ultima pubblicazione».",
                     "Verifica raccolta e nome file; l'app Graph del portale deve poter scrivere sul sito."],
        },
    ],
}
