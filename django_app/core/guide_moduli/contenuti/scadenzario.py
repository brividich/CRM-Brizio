GUIDA = {
    "slug": "scadenzario",
    "titolo": "Scadenzario",
    "area": "Per tutti",
    "sintesi": "Le scadenze di tutti i moduli in una pagina, le scadenze generiche con avvisi per mail e il pannello che decide cosa compare e chi lo vede.",
    "parole": "scadenzario scadenze scadenza generiche categoria categorie rinnovo avviso avvisi preavviso riepilogo mensile gestione pannello regole ruolo aziendale persona visibilità certificati contratti",
    "url": "scadenze_globali",
    "prefissi": ("/scadenze",),
    "uso": [
        {
            "id": "pagina",
            "titolo": "Lo Scadenzario",
            "blocchi": [
                ("p", "Menu in alto «Scadenzario» (indirizzo /scadenze): le scadute e le scadenze dei prossimi 90 giorni di "
                      "personale, asset, verifiche impianti, DPI, RENTRI, azioni CAPA e scadenze generiche, le più urgenti in cima. "
                      "Filtri, CSV e calendario come descritto nella guida della Home («Lo Scadenzario globale»)."),
                ("def", [
                    ("Sistema di gestione", "sorveglianza e scadenza dei certificati (attivi), audit esterni pianificati e risposta all'ente, audit interni pianificati o con piano approvato, analisi (1 mese) e chiusura (3 mesi o proroga) delle CAR aperte, prossima verifica di efficacia, qualifica degli auditor attivi, azioni della SoA e scenari di rischio OT della revisione in vigore."),
                    ("Qualifiche di processo", "scadenza e revisione dei processi MOD.128 attivi, requisiti con scadenza, certificazioni individuali attive, revisione delle abilitazioni macchina della skill matrix."),
                    ("Formazione (enti e verifiche)", "documenti di enti e docenti con scadenza (accreditamento, contratto, assicurazione…), «verifica assenza NC a 6 mesi» delle edizioni approvate senza esito."),
                    ("SOC / NIS2", "azioni correttive degli incidenti non fatte, accettazioni del rischio non revocate."),
                    ("GDPR", "verifica periodica dell'operato degli amministratori di sistema non revocati."),
                    ("Presa visione procedure", "prese visione aperte con scadenza (ognuno vede le proprie, chi gestisce le campagne tutte) e campagne pubblicate."),
                ]),
                ("p", "Ogni voce compare a chi può aprire la pagina dove si gestisce (la tua CAR e la tua presa visione le vedi sempre). "
                      "Il nome nella colonna Soggetto porta a quella pagina."),
                ("p", "Cosa vedi lo decidono i permessi del modulo di origine più le regole del pannello «Gestione»: "
                      "una regola può farti vedere scadenze di un modulo che non apri, oppure toglierne alcune a tutti."),
            ],
        },
        {
            "id": "generiche",
            "titolo": "Scadenze generiche",
            "blocchi": [
                ("p", "«Scadenze generiche» raccoglie le attività che non stanno in un altro modulo (certificati, contratti, "
                      "verifiche…), divise per categoria. Arrivano dal vecchio scadenzario sul NAS."),
                ("passi", [
                    "«+ Nuova attività»: scegli la categoria, scrivi l'attività e la scadenza, oppure ultimo controllo e validità in mesi (la scadenza si calcola).",
                    "«Destinatari dell'avviso»: le email che ricevono il promemoria della singola attività.",
                    "Quando l'attività è fatta apri la scheda e usa «Registra controllo / rinnovo»: data del controllo, allegato (verbale, certificato) e la nuova scadenza, calcolata dalla validità se la lasci vuota.",
                ]),
                ("def", [
                    ("Preavviso", "quanti giorni prima della scadenza parte il primo avviso; vuoto = quello della categoria, poi quello generale (30)."),
                    ("Ripeti l'avviso ogni", "ogni quanti giorni l'avviso si ripete finché non registri il rinnovo; vuoto = categoria, poi generale (7)."),
                    ("Avvisa anche dopo la scadenza", "sulla categoria: le attività scadute e non rinnovate continuano a mandare l'avviso."),
                    ("Riepilogo mensile", "il 1° del mese alle 8 le email della categoria ricevono l'elenco delle attività scadute o in scadenza nei 60 giorni successivi."),
                    ("Avvisi inviati", "registro di ogni mail, riuscita o no; quelli del vecchio scadenzario sono segnati «vecchio scadenzario»."),
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "gestione",
            "titolo": "Pannello «Gestione»: cosa compare e chi lo vede",
            "blocchi": [
                ("p", "Scadenzario → «⚙ Gestione». A sinistra l'albero delle voci: fonte (Personale, Asset, Scadenze generiche…) → "
                      "tipo (Qualifica, Visita medica, Formazione, categoria…) → singolo elemento (il tipo di qualifica, il corso, "
                      "la verifica, la singola attività). L'albero si aggiorna da solo: un tipo di qualifica o una categoria nuovi "
                      "compaiono appena hanno una scadenza. Il numero accanto è quante scadenze ci sono oggi."),
                ("def", [
                    ("Compare nello scadenzario", "«No» toglie la voce e tutto ciò che sta sotto, a tutti; un elemento sotto può riaccendersi con «Sì». Vuoto = come la voce superiore."),
                    ("Chi la vede", "«Chi ha il permesso del modulo, più le regole» (predefinito): le regole aggiungono persone. «Solo chi è nelle regole»: la vedono solo le regole e gli amministratori."),
                    ("Regole", "ruolo del portale, ruolo aziendale dell'organigramma (chi lo ricopre oggi) o persona aggiunta a mano. Valgono per la voce e per tutto ciò che sta sotto: le regole che arrivano dalle voci superiori sono elencate a parte."),
                    ("Vede e gestisce", "solo per le scadenze generiche: inserisce, modifica e rinnova le attività della categoria."),
                    ("Chi gestisce questo pannello", "gli amministratori sempre; qui si aggiungono altri ruoli o persone."),
                ]),
                ("nota", "Le visite mediche sono dati sanitari: una regola sulle visite le mostra anche a chi non apre il modulo, "
                         "quindi concedile solo a medico competente, RSPP e HR. Ogni modifica del pannello resta nel registro attività."),
            ],
        },
        {
            "id": "import",
            "titolo": "Import dal vecchio scadenzario",
            "blocchi": [
                ("passi", [
                    "Sul server dell'HUB: variabile d'ambiente SCADENZARIO_DB_PASSWORD con la password dell'utente MySQL in sola lettura.",
                    "Prova: python manage.py importa_scadenzario (conta categorie e attività, non scrive).",
                    "Import: python manage.py importa_scadenzario --apply --con-avvisi (rilanciabile: aggiorna, non duplica).",
                    "Ferma le mail del vecchio scadenzario sul NAS lo stesso giorno, altrimenti arrivano doppie.",
                ]),
                ("p", "Preavviso, ripetizione e finestra del riepilogo generali: SiteConfig scadenzario_preavviso_giorni (30), "
                      "scadenzario_ripeti_giorni (7), scadenzario_riepilogo_giorni (60). Task: «scadenzario_avvisi_attivita» "
                      "(ogni giorno alle 7:15) e «scadenzario_riepilogo_mensile» (il 1° alle 8)."),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Una persona non vede scadenze che dovrebbe vedere",
            "perche": "Non ha il permesso del modulo di origine e nessuna regola gliele concede, oppure la voce è spenta o «Solo chi è nelle regole».",
            "fare": [
                "In «Gestione» apri la voce: controlla «Compare» e «Chi la vede» anche sulle voci superiori.",
                "Aggiungi una regola per il suo ruolo del portale, il suo ruolo aziendale o la persona.",
            ],
        },
        {
            "sintomo": "Un elemento non compare nell'albero del pannello",
            "perche": "Gli elementi compaiono quando hanno una scadenza scaduta o nei prossimi 90 giorni.",
            "fare": ["Imposta la voce del tipo superiore: vale anche per gli elementi che compariranno."],
        },
        {
            "sintomo": "Non arrivano gli avvisi di un'attività",
            "perche": "Nessun destinatario sull'attività, attività o categoria sospesa, fuori preavviso, oppure scaduta in una categoria che non avvisa dopo la scadenza.",
            "fare": ["Controlla la scheda dell'attività e «Avvisi inviati».", "Controlla che il task «scadenzario_avvisi_attivita» sia attivo nella Centrale di comando."],
        },
    ],
}
