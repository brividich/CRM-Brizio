GUIDA = {
    "slug": "scadenzario",
    "titolo": "Scadenzario",
    "area": "Per tutti",
    "sintesi": "Le scadenze di tutti i moduli in una pagina, le scadenze generiche con avvisi per mail e il pannello che decide cosa compare e chi lo vede.",
    "parole": "scadenzario scadenze scadenza generiche categoria categorie rinnovo avviso avvisi preavviso riepilogo mensile gestione pannello regole ruolo aziendale persona visibilità certificati contratti",
    "url": "scadenze_globali",
    "prefissi": ("/scadenze",),
    "dettaglio": [("Guida completa dello Scadenzario", "scadenzario:guida")],
    "uso": [
        {
            "id": "pagina",
            "titolo": "Lo Scadenzario",
            "blocchi": [
                ("p", "Menu in alto «Scadenzario» (indirizzo /scadenze): le scadute e le scadenze dei prossimi 90 giorni di "
                      "personale, asset, verifiche impianti, DPI, RENTRI, azioni CAPA e scadenze generiche, le più urgenti in cima. "
                      "Si apre sul calendario del mese (clic su un giorno per il dettaglio, «⛶ Schermo intero» per riempire la finestra), con le viste Agenda ed Elenco e filtri a scelta multipla; "
                      "contatori, filtri, CSV e file per Outlook come descritto nella guida della Home («Lo Scadenzario globale»)."),
                ("def", [
                    ("Sistema di gestione", "sorveglianza e scadenza dei certificati (attivi), audit esterni pianificati e risposta all'ente, audit interni pianificati o con piano approvato, analisi (1 mese) e chiusura (3 mesi o proroga) delle CAR aperte, prossima verifica di efficacia, qualifica degli auditor attivi, azioni della SoA e scenari di rischio OT della revisione in vigore."),
                    ("Qualifiche di processo", "scadenza e revisione dei processi MOD.128 attivi, requisiti con scadenza, certificazioni individuali attive, revisione delle abilitazioni macchina della skill matrix."),
                    ("Formazione (enti e verifiche)", "documenti di enti e docenti con scadenza (accreditamento, contratto, assicurazione…), «verifica assenza NC a 6 mesi» delle edizioni approvate senza esito."),
                    ("SOC / NIS2", "azioni correttive degli incidenti non fatte, accettazioni del rischio non revocate, termini di legge NIS2 e GDPR non ancora rispettati."),
                    ("GDPR", "verifica periodica dell'operato degli amministratori di sistema non revocati."),
                    ("Registro OFI", "voci aperte con data di chiusura richiesta e senza CAR."),
                    ("Anomalie e NC", "azioni sulle non conformità e verifiche di efficacia previste."),
                    ("KICK-OFF e attività", "solo le tue: attività e azioni degli incontri assegnate a te."),
                    ("Suggestion Corner", "esecuzioni e controlli da fare."),
                    ("Attrezzature", "attività aperte sulle attrezzature."),
                    ("Ingressi e cambi mansione", "voci dell'inserimento, adempimenti del cambio mansione e deroghe operative."),
                    ("Manutenzione programmata", "manutenzioni ordinarie e tarature: spenta finché il pannello non la accende."),
                    ("Presa visione procedure", "prese visione aperte con scadenza (ognuno vede le proprie, chi gestisce le campagne tutte) e campagne pubblicate."),
                ]),
                ("p", "Ogni voce compare a chi può aprire la pagina dove si gestisce (la tua CAR e la tua presa visione le vedi sempre). "
                      "Il nome nella colonna Soggetto porta a quella pagina."),
                ("p", "Nelle schede di dipendente, asset, fornitore, certificazione, audit, incidente, verifica impianto e corso il riquadro «📅 Scadenze di questa scheda» mostra le scadenze, chi se ne occupa e «Me ne occupo io»."),
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
                    "«Destinatari dell'avviso»: le email che ricevono il promemoria della singola attività. «Usa quelli della categoria» li copia. Vuoto: nessun avviso singolo, l'attività resta nel riepilogo mensile della categoria.",
                    "Quando l'attività è fatta usa «✓ Rinnovato oggi» nell'elenco o nella scheda: compare se l'attività ha la validità in mesi, da cui si calcola la prossima scadenza.",
                    "Per un'altra data, le note o un allegato (verbale, certificato) apri nella scheda «Rinnovo con altra data, note o allegato».",
                ]),
                ("p", "«Collega» propone i legami con certificazioni, verifiche impianto, asset, fornitori, qualifiche e corsi: conferma sempre una persona. «Unisci» lascia una voce sola, quella del modulo, che dà anche la data; l'attività tiene storico e destinatari e si può separare."),
                ("p", "Più attività insieme: nell'elenco spunta le righe e, nella barra che compare in basso, assegna il responsabile, aggiungi o sostituisci i destinatari, usa quelli della categoria, sospendi o riattiva. "
                      "Il filtro «Mancano» trova le attività senza responsabile o senza destinatari; i riquadri in alto filtrano scadute ed entro 30 giorni."),
                ("def", [
                    ("Preavviso", "quanti giorni prima della scadenza parte il primo avviso; vuoto = quello della categoria, poi quello generale (30)."),
                    ("Ripeti l'avviso ogni", "ogni quanti giorni l'avviso si ripete finché non registri il rinnovo; vuoto = categoria, poi generale (7)."),
                    ("Avvisa anche dopo la scadenza", "sulla categoria: le attività scadute e non rinnovate continuano a mandare l'avviso."),
                    ("Responsabile", "riceve una notifica nel portale quando viene assegnato e poi a scaletta, anche senza destinatari mail."),
                    ("Riepilogo mensile", "il 1° del mese alle 8 le email della categoria ricevono l'elenco delle attività scadute o in scadenza nei 60 giorni successivi."),
                    ("Avvisi", "in alto cosa partirà al prossimo invio (anteprima, non spedisce nulla), con le attività nel preavviso senza destinatari e quelle già avvisate; sotto il registro di ogni mail, riuscita o no. Quelle del vecchio scadenzario sono segnate «vecchio scadenzario»."),
                ]),
            ],
        },
    ],
    "admin": [
        {
            "id": "gestione",
            "titolo": "Pannello «Gestione»: cosa compare e chi lo vede",
            "blocchi": [
                ("p", "Per dare una categoria a un ruolo fai prima da «Categorie»: la tabella mostra chi vede ogni categoria; aprila e usa «Aggiungi» (un solo menu con ruoli aziendali, ruoli del portale e persone) scegliendo «Solo vedere» o «Vedere e gestire»."),
                ("p", "Scadenzario → «Gestione». Appena entri, «Da sistemare» elenca cosa manca alle scadenze generiche, con il link per farlo. A sinistra, con la ricerca e il filtro «Solo le voci già impostate», l'albero delle voci: fonte (Personale, Asset, Scadenze generiche…) → "
                      "tipo (Qualifica, Visita medica, Formazione, categoria…) → singolo elemento (il tipo di qualifica, il corso, "
                      "la verifica, la singola attività). L'albero si aggiorna da solo: un tipo di qualifica o una categoria nuovi "
                      "compaiono appena hanno una scadenza. Il numero accanto è quante scadenze ci sono oggi."),
                ("def", [
                    ("Frase in alto", "dice in parole semplici chi vede la voce oggi, contando anche le impostazioni delle voci superiori."),
                    ("Compare nello scadenzario", "in «Spegnere la voce o limitarla alle sole regole». «No» toglie la voce e tutto ciò che sta sotto, a tutti; un elemento sotto può riaccendersi con «Sì». Vuoto = come la voce superiore."),
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
                    "Import: python manage.py importa_scadenzario --apply --con-avvisi. Si può rilanciare: non duplica e lascia come sono le voci già importate, così non perdi le modifiche fatte nel portale. Solo --aggiorna le riscrive con i dati del vecchio scadenzario.",
                    "Ferma le mail del vecchio scadenzario sul NAS lo stesso giorno, altrimenti arrivano doppie.",
                ]),
                ("p", "Santo patrono nel calendario: SiteConfig scadenzario_patrono = «MM-GG Nome» (es. «06-29 San Pietro»). "
                      "Andamento: task «scadenzario_foto_giornaliera» ogni giorno alle 6:45; dopo il deploy python manage.py scadenzario_foto per il primo punto."),
                ("p", "Anteprima da riga di comando: python manage.py scadenzario_avvisi (facoltativo --giorno AAAA-MM-GG). Non invia nulla."),
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
            "perche": "L'avviso mail va solo ai destinatari; il responsabile riceve la notifica nel portale. Nessun destinatario sull'attività (in quel caso resta solo il riepilogo mensile della categoria), attività o categoria sospesa, fuori preavviso, oppure scaduta in una categoria che non avvisa dopo la scadenza.",
            "fare": ["Apri «Avvisi»: l'anteprima mostra se partirà al prossimo invio.", "Controlla la scheda dell'attività.", "Controlla che il task «scadenzario_avvisi_attivita» sia attivo nella Centrale di comando."],
        },
    ],
}
