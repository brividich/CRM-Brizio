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
                    "Contatori in alto: dipendenti presenti, esterni in azienda e, per incarico di sicurezza, quanti sono in azienda.",
                    "Tabella «Esterni in azienda»: visitatori, ditte e docenti registrati al GuestPortal e non ancora usciti "
                    "(nome, azienda, tipo, referente, entrata, badge). Anche nel PDF.",
                    "Ricerca per nome, matricola o reparto; filtri per reparto e incarico.",
                    "«PDF»: la lista nel formato del vecchio CN-PRESENZE, senza ora di entrata.",
                    "Pallino verde «In azienda» accanto al nome in Anagrafica (elenco dipendenti e scheda) "
                    "e fra i dipendenti trovati con la ricerca in alto (Ctrl+K).",
                ]),
            ],
        },
        {
            "id": "andamento",
            "titolo": "Andamento per reparto",
            "blocchi": [
                ("p", "Scheda «Andamento per reparto»: persone in azienda a ogni ora di oggi (5-22) per reparto "
                      "dell'anagrafica, con colonna «Adesso» uguale alla lista. Solo numeri, nessun nome; dati "
                      "aggiornati al massimo ogni 5 minuti. Gli esterni non sono contati."),
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
                    "Dopo la chiusura si apre il «Verbale»: tempi al 50/90/100 %, chi ha contato, non contati, "
                    "osservazioni da scrivere; «PDF verbale» con spazi firma. Le esercitazioni si possono eliminare "
                    "(chi le ha avviate o l'amministratore), le emergenze no.",
                ]),
                ("nota", "L'appello comprende i dipendenti che hanno timbrato e gli esterni registrati al GuestPortal "
                         "(etichetta «Esterno · azienda»). Chi entra senza registrarsi al GuestPortal non c'è."),
            ],
        },
        {
            "id": "uscite",
            "titolo": "Uscite non timbrate",
            "blocchi": [
                ("p", "Si controllano tutte le timbrature del giorno, non solo l'ultima. Segnala: uscita mancante (l'ultima è un'entrata), verso sbagliato (es. E 12:55 · E 18:02: l'uscita delle 18:02 timbrata come entrata; E · U 12:03 · U 13:01 · U 17:08: il rientro delle 13:01 timbrato come uscita), due entrate o due uscite di fila. I turni a cavallo della mezzanotte (entrata la sera, uscita il mattino dopo entro 16 ore) non sono segnalati. La colonna «Problema» spiega cosa non torna e mostra le timbrature del giorno."),
                ("p", "Il capo vede la sua squadra e ogni mattina alle 7:30 (lunedì-sabato) riceve notifica e mail "
                      "con le uscite mancanti nuove degli ultimi 3 giorni e le timbrature del giorno. Verso sbagliato "
                      "e due entrate o uscite di fila restano solo nella pagina: nessuna notifica né mail."),
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
            "sintomo": "«Il GuestPortal non risponde» o «GuestPortal non collegato» sopra la lista",
            "perche": "il database del GuestPortal non è raggiungibile o le chiavi GUESTPORTAL_DB_* mancano nel .env.",
            "fare": ["Nell'emergenza conta gli esterni dal registro della portineria.",
                     "Poi controlla le chiavi GUESTPORTAL_DB_* nel .env e la rete verso il MySQL del GuestPortal."],
        },
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
