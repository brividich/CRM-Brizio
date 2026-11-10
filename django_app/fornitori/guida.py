"""Guida in-app del modulo Fornitori (pulsante «? Guida», ``/fornitori/guida/``).

Etichette e soglie prese dal codice: ``fornitori/requisiti.py`` (requisiti, 30 giorni
di preavviso, ditte attese entro 30 giorni), ``fornitori/tasks.py`` (avviso ogni 10 minuti e
ogni mattina feriale a RSPP/ASPP, solo notifica), ``fornitori/ingressi.py`` (da collegare, 30 giorni).
"""
from __future__ import annotations

TITOLO = "Fornitori"
SOTTOTITOLO = ("Anagrafica fornitori, documenti con scadenza, requisiti di sicurezza per chi lavora in sede, "
               "accessi esterni dal GuestPortal e tutto ciò che gli altri moduli sanno della ditta.")

SEZIONI = [
    {
        "id": "cosa",
        "titolo": "A cosa serve",
        "blocchi": [
            ("p", "Raccoglie i fornitori con contatti, ordini, valutazioni, asset in carico e documenti. Per le ditte "
                  "che lavorano nei nostri locali controlla i documenti di sicurezza e li confronta con chi entra "
                  "dal GuestPortal."),
            ("def", [
                ("Elenco fornitori", "ricerca per nome, P.IVA o città; nella colonna «Stato» anche lo stato dei "
                                     "documenti di sicurezza."),
                ("Scheda fornitore", "dati, ordini, documenti, valutazioni, asset, il riquadro «Requisiti per "
                                     "lavorare in sede» e le schede «Manutenzione», «Copie MFC», «Scadenze», "
                                     "«Tecnici» e «Riepilogo annuale»."),
                ("+ Crea fornitore", "in «Accessi esterni», accanto a un'azienda che non è tra i fornitori: crea il "
                                     "fornitore con il nome scritto nel GuestPortal e ci registra la persona tra i "
                                     "tecnici. Gli altri dati si completano dopo con «Modifica»; il tecnico non "
                                     "riceve nessun accesso al portale."),
                ("Accessi esterni", "chi è entrato dal GuestPortal adesso e nei giorni scorsi, con la ditta "
                                    "collegata alla scheda fornitore."),
            ]),
        ],
    },
    {
        "id": "scheda-collegamenti",
        "titolo": "Manutenzione, copie, scadenze, tecnici e riepilogo della ditta",
        "blocchi": [
            ("p", "«Riepilogo annuale» mette insieme un anno con la ditta: OdL chiusi e costo, ordinarie eseguite e in "
                  "ritardo, ticket delegati, verifiche, ingressi e ore in azienda, ordini, fatture copie e medie delle "
                  "valutazioni. Scegli l'anno dal menu (gli ultimi 5). Si guarda solo nel portale, non si esporta, e non "
                  "dà giudizi: la valutazione resta nella scheda «Valutazioni»."),
            ("p", "Nella scheda del fornitore queste schede raccolgono ciò che esiste già negli altri moduli. Sono "
                  "tutte facoltative: non c'è niente da compilare e una scheda vuota lo dice senza errori."),
            ("def", [
                ("Manutenzione", "ordini di lavoro aperti e chiusi, ticket delegati alla ditta, contratti di "
                                 "assistenza, verifiche impianti, ricambi e rinnovi di licenze. «OdL chiusi 12 mesi» "
                                 "e «Costo OdL 12 mesi» sono gli stessi numeri di «Scheda manutenzione completa»; "
                                 "la nota sotto dice su quanti OdL il costo è compilato."),
                ("Copie MFC", "macchine e fatture delle copie, con l'esito della Riconciliazione degli ultimi 8 "
                              "trimestri fatturati e i trimestri con letture ma senza fattura della ditta. Gli "
                              "importi in euro non ci sono: il modulo Contatori non li registra."),
                ("Scadenze", "documenti, contratti, verifiche periodiche e attività dello Scadenzario della ditta, "
                             "in ordine di data. «In scadenza» = entro 30 giorni."),
                ("Manutenzione", "tra le altre cose, anche le manutenzioni ordinarie aperte affidate alla ditta, con gli "
                                 "ingressi collegati a ciascuna."),
                ("Tecnici", "il registro dei tecnici della ditta con qualifica, contatti e attestati. Chi ha il permesso "
                            "di «Accessi esterni» vede anche ingressi, ore in azienda, ultimo ingresso, chi è dentro "
                            "ora e gli ingressi degli ultimi 90 giorni."),
            ]),
            ("p", "La scheda «Copie MFC» compare da sola se il fornitore ha lo stesso nome di quello usato in Contatori "
                  "(BASE SPA, Copylab). Altrimenti, nel riquadro «Multifunzioni» a destra, apri «Fattura le copie delle "
                  "multifunzioni?», scegli il fornitore e premi «Collega»; «Togli» annulla il collegamento."),
            ("p", "Un tecnico si registra da solo quando entra dal GuestPortal per una ditta riconosciuta (controllo ogni "
                  "10 minuti) o quando un suo ingresso viene collegato a un intervento. Puoi aggiungerlo con «+ Nuovo "
                  "tecnico» o con «Registra» / «Registra tutti» in «Entrati ma non ancora registrati». Da «Modifica» "
                  "compili qualifica, contatti e «Attestati validi fino al» (facoltativi): la data compare in «Scadenze» "
                  "e nello Scadenzario."),
            ("nota", "Il registro resta nell'HUB anche dopo la pulizia GDPR del GuestPortal: chi non lavora più per la ditta "
                     "si disattiva da «Modifica», oppure si cancella con «Elimina dal registro». Ingressi e ore invece si "
                     "leggono dal GuestPortal a ogni apertura, senza copie. Se non risponde la scheda lo dice e il resto "
                     "della pagina funziona."),
        ],
    },
    {
        "id": "chiosco",
        "titolo": "Chiosco della reception",
        "blocchi": [
            ("p", "Il pulsante «Chiosco» in Accessi esterni apre /chiosco/: il visitatore registra ingresso e uscita senza login, "
                  "e le visite compaiono qui come sempre. Si apre solo dalle postazioni abilitate dall'amministratore. "
                  "Una domanda alla volta: nome e cognome; se qualcuno con quel nome è già venuto compare solo la sua azienda da confermare "
                  "(più righe se ci sono omonimi) e referente e motivo dell'ultima volta sono già scelti; poi l'informativa da spuntare. "
                  "«Esco» mostra i numeri dei cartellini in uso: basta toccare il proprio. Il referente si cerca scrivendo il nome. Il pannello per gestire presenti, storico, pre-registrazioni e "
                  "cartellini è «Reception», nel menu di Fornitori."),
            ("p", "Ogni dipendente può annunciare un ospite da «Annuncia una visita» nella barra in alto: l'ospite riceve codice e QR. "
                  "Gli esterni possono chiedere un appuntamento dal modulo pubblico /richiesta-visita/: dopo la conferma dell'email la richiesta "
                  "arriva alla persona indicata («Richieste per te») e in Reception → «Richieste», dove si accetta o si rifiuta."),
        ],
    },
    {
        "id": "requisiti",
        "titolo": "Requisiti per lavorare in sede",
        "blocchi": [
            ("p", "Nella scheda del fornitore spunta «Lavora nei nostri locali» (Modifica) per le ditte che fanno "
                  "appalti, manutenzioni o servizi in azienda. Per loro servono i documenti dell'art. 26 del "
                  "D.Lgs. 81/2008."),
            ("def", [
                ("Visura camerale", "obbligatoria."),
                ("Idoneità tecnico-professionale", "obbligatoria (autocertificazione)."),
                ("DURC", "obbligatorio; vale 120 giorni."),
                ("DUVRI", "obbligatorio; di solito vale fino alla fine del contratto."),
                ("Polizza RCT/RCO", "consigliata: se manca non rende la ditta «non in regola»."),
            ]),
            ("passi", [
                "Apri la scheda «Documenti» del fornitore e premi «+ Carica documento».",
                "Scegli il tipo (es. «DURC»), indica la scadenza e carica il file.",
                "Quando rinnovi un documento caricane uno nuovo dello stesso tipo: vale quello con la scadenza più "
                "lontana, il vecchio può restare come storico.",
            ]),
            ("def", [
                ("Documenti in regola", "tutti gli obbligatori caricati e validi."),
                ("Documenti in scadenza", "un obbligatorio scade entro 30 giorni."),
                ("Documenti non in regola", "un obbligatorio manca o è scaduto."),
            ]),
            ("nota", "Un documento senza scadenza vale finché non ne carichi uno nuovo. Le scadenze compaiono anche "
                     "nello Scadenzario, alla voce «Fornitori (documenti di sicurezza)»."),
        ],
    },
    {
        "id": "ingressi",
        "titolo": "Ingressi delle ditte non in regola",
        "blocchi": [
            ("p", "Quando una persona entra dal GuestPortal, la sua azienda viene collegata alla scheda fornitore "
                  "(abbinamento ditta in «Ditte GuestPortal», altrimenti stessa ragione sociale). Se la ditta lavora "
                  "in sede e i documenti non sono in regola:"),
            ("ul", [
                "in «Accessi esterni» e nella lista «Presenti in azienda» accanto alla ditta compare l'avviso "
                "rosso con cosa manca (es. «DURC scaduto il …»);",
                "ogni 10 minuti il portale manda una notifica (mai una mail) a chi ricopre oggi i ruoli RSPP o ASPP "
                "nell'organigramma, una sola volta per ingresso, con il link alla scheda del fornitore.",
            ]),
            ("p", "Prima che la ditta entri: se ha una manutenzione aperta entro 30 giorni (anche in ritardo), un OdL o "
                  "un ticket delegato aperti e a quella data i documenti non saranno in regola, ogni mattina dal lunedì "
                  "al venerdì RSPP e ASPP ricevono una notifica. Per la stessa ditta si ripete solo se i problemi cambiano "
                  "o dopo 14 giorni. Lo stesso elenco è in «Ditte attese con i documenti non in regola», nella pagina "
                  "iniziale di Fornitori."),
            ("nota", "Gli avvisi non bloccano l'ingresso: decide chi è in portineria con l'RSPP."),
        ],
    },
    {
        "id": "permessi",
        "titolo": "Chi vede cosa",
        "blocchi": [
            ("def", [
                ("Fornitori e scheda", "chi ha il modulo Fornitori."),
                ("Manutenzione, Copie MFC", "chi apre anche le manutenzioni delle ditte in Asset, o le fatture in "
                                            "Contatori; i ticket sono quelli che la persona può gestire."),
                ("Collegare un ingresso a manutenzione o scadenza", "manutenzione ordinaria: chi la può registrare; "
                                                                    "scadenza dell'asset: chi apre la modifica della scadenza; "
                                                                    "attività dello Scadenzario: chi gestisce la categoria."),
                ("Tecnici", "il registro con la scheda del fornitore; ingressi e ore con il permesso di «Accessi "
                            "esterni»; aggiungere, modificare ed eliminare con il permesso di modifica del fornitore."),
                ("Accessi esterni", "chi ha il permesso del portale esterno (in produzione amministratori)."),
                ("Notifica ingressi non in regola", "chi ricopre i ruoli indicati nella chiave "
                                                     "«fornitori_requisiti_ruoli» (predefinito «RSPP,ASPP»)."),
            ]),
        ],
    },
    {
        "id": "problemi",
        "titolo": "Problemi frequenti",
        "blocchi": [
            ("def", [
                ("La ditta entrata non risulta collegata", "il nome nel GuestPortal è diverso dalla ragione sociale: "
                                                           "abbinala in «Ditte GuestPortal»."),
                ("Un tecnico entrato non è nel registro", "la ditta ha un altro nome nel GuestPortal: abbinala in «Ditte "
                                                          "GuestPortal». Il controllo gira ogni 10 minuti e vede chi è "
                                                          "dentro in quel momento: chi è già uscito si registra da «Entrati "
                                                          "ma non ancora registrati»."),
                ("Non vedo «Copie MFC»", "il nome non coincide con quello di Contatori: collega il fornitore dal "
                                         "riquadro «Multifunzioni» della scheda. Serve anche il permesso delle "
                                         "fatture di Contatori."),
                ("Documento rinnovato ma ancora «scaduto»", "manca la scadenza sul nuovo documento o il tipo è "
                                                             "diverso: correggi caricandolo di nuovo con tipo e scadenza."),
                ("Nessuno riceve la notifica", "nell'organigramma nessuno ricopre oggi RSPP/ASPP, oppure la persona "
                                               "non ha un utente del portale."),
            ]),
        ],
    },
]
