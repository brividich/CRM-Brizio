"""Guida in-app del modulo Fornitori (pulsante «? Guida», ``/fornitori/guida/``).

Etichette e soglie prese dal codice: ``fornitori/requisiti.py`` (requisiti, 30 giorni
di preavviso), ``fornitori/tasks.py`` (avviso ogni 10 minuti a RSPP/ASPP, solo notifica).
"""
from __future__ import annotations

TITOLO = "Fornitori"
SOTTOTITOLO = ("Anagrafica fornitori, documenti con scadenza, requisiti di sicurezza per chi lavora in sede "
               "e accessi esterni dal GuestPortal.")

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
                ("Scheda fornitore", "dati, ordini, documenti, valutazioni, asset e il riquadro «Requisiti per "
                                     "lavorare in sede»."),
                ("Accessi esterni", "chi è entrato dal GuestPortal adesso e nei giorni scorsi, con la ditta "
                                    "collegata alla scheda fornitore."),
            ]),
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
            ("nota", "L'avviso non blocca l'ingresso: decide chi è in portineria con l'RSPP."),
        ],
    },
    {
        "id": "permessi",
        "titolo": "Chi vede cosa",
        "blocchi": [
            ("def", [
                ("Fornitori e scheda", "chi ha il modulo Fornitori."),
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
                ("Documento rinnovato ma ancora «scaduto»", "manca la scadenza sul nuovo documento o il tipo è "
                                                             "diverso: correggi caricandolo di nuovo con tipo e scadenza."),
                ("Nessuno riceve la notifica", "nell'organigramma nessuno ricopre oggi RSPP/ASPP, oppure la persona "
                                               "non ha un utente del portale."),
            ]),
        ],
    },
]
