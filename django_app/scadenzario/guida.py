"""Guida completa dello Scadenzario (pulsante «? Guida» e PDF).

Testo semplice, stessi blocchi di ``core/guida_pdf.py``. Etichette, orari e soglie
sono quelli del codice (``scadenzario/avvisi.py``, ``controlli.py``, ``forms.py``,
``dashboard/scadenze_providers.py``, ``scadenzario/fonti_moduli.py``): se cambiano,
va aggiornata anche questa guida e ``core/guide_moduli/contenuti/scadenzario.py``.
"""
from __future__ import annotations

TITOLO = "Scadenzario"
SOTTOTITOLO = "Tutte le scadenze del portale in un posto solo: come leggerle, gestirle, rinnovarle e decidere chi le vede."

_IMG = "scadenzario/guida/"

SEZIONI: list[dict] = [
    {
        "id": "cosa",
        "titolo": "A cosa serve",
        "blocchi": [
            ("p", "Lo Scadenzario (menu in alto, indirizzo /scadenze) risponde a una domanda: cosa scade, quando e chi se ne occupa. "
                  "Ha tre parti."),
            ("def", [
                ("Calendario", "le scadenze di tutti i moduli insieme, in sola lettura: il dato resta nel modulo di origine e si corregge lì."),
                ("Scadenze generiche", "le attività che non stanno in un altro modulo (certificati, contratti, verifiche). "
                                       "Nascono qui, si rinnovano qui e mandano gli avvisi per mail. Sostituiscono il vecchio scadenzario sul NAS."),
                ("Gestione", "per chi amministra: cosa compare e chi lo vede, fino alla singola voce."),
            ]),
            ("img", (_IMG + "calendario.jpg", "Il calendario del mese: a destra il pannello del giorno e le scadute")),
            ("nota", "Esempi e nomi nelle immagini sono inventati."),
        ],
    },
    {
        "id": "subito",
        "titolo": "Le cose da fare più spesso",
        "blocchi": [
            ("def", [
                ("Vedere cosa tocca a me", "«👤 Solo le mie»: le scadenze col tuo nome, di cui sei responsabile o che hai preso in carico."),
                ("Vedere cosa è già scaduto", "clic sul contatore «Scadute», oppure il riquadro «⚠ Scadute» accanto al calendario."),
                ("Aprire il dettaglio", "clic sulla scadenza: porta alla pagina dove si gestisce."),
                ("Dire ai colleghi che ci penso io", "«👤 Me ne occupo io» sotto la scadenza."),
                ("Registrare un rinnovo", "«✓ Rinnovato oggi» (solo scadenze generiche con validità in mesi)."),
                ("Aggiungere un'attività da ricordare", "Scadenze generiche → «+ Nuova attività»."),
                ("Riceverle senza aprire il portale", "Impostazioni notifiche: riepilogo per mail ogni mattina feriale, oppure calendario in Outlook."),
            ]),
        ],
    },
    {
        "id": "viste",
        "titolo": "Calendario, Anno, Agenda, Elenco, Andamento",
        "blocchi": [
            ("p", "In alto i contatori: Scadute, Entro 30 giorni, 31–60, 61–90 e Totale. Contano le scadute e i prossimi 90 giorni. "
                  "Sotto si sceglie la vista."),
            ("def", [
                ("Calendario", "il mese, con lunedì come primo giorno. Ogni giorno mostra le scadenze che ci stanno, colorate per fonte, e «+N altre». "
                               "Il numero in alto a destra è rosso se c'è una scaduta, arancio se scade entro 30 giorni. Clic su un giorno: l'elenco completo nel pannello a destra (sotto, da telefono). "
                               "‹ › o le frecce ← → cambiano mese. Mostra anche le scadenze oltre i 90 giorni."),
                ("Anno", "i 12 mesi affiancati: più scuro è il giorno, più scadenze ha; il bordo rosso segnala le scadute. Serve a programmare audit, rinnovi e ferie."),
                ("Agenda", "le settimane in fila: prima le Scadute, poi «Questa settimana», «La prossima settimana» e le seguenti."),
                ("Elenco", "la tabella, 50 righe per pagina."),
                ("Andamento", "solo per chi gestisce lo scadenzario: scadute ed entro 30 giorni nel tempo, da una fotografia presa ogni mattina. Serve al riesame della direzione."),
            ]),
            ("ul", [
                "«⛶ Schermo intero»: lo scadenzario copre la finestra; si esce con Esc. Lì puoi attivare «⟳ Aggiorna» ogni 5, 10 o 15 minuti per un monitor d'ufficio.",
                "«🖨 Stampa»: stampa o salva in PDF quello che vedi, con i filtri attivi in testa.",
                "Festivi in rosso. Una scadenza che cade in un giorno non lavorativo mostra «⚠ domenica», «⚠ Natale» e simili.",
            ]),
        ],
    },
    {
        "id": "filtri",
        "titolo": "Filtri e viste salvate",
        "blocchi": [
            ("p", "I filtri valgono in tutte le viste e si possono combinare."),
            ("ul", [
                "Contatori: un clic aggiunge la fascia al filtro, un secondo clic la toglie. «Totale» le toglie tutte.",
                "Etichette colorate delle fonti o tendina «Fonti»: scegline una o più.",
                "Tendina «Reparti»: spunta e premi «Applica».",
                "«Cerca»: trova persona, asset, attività o reparto (Invio).",
                "«✕ Togli tutti i filtri» riparte da zero.",
            ]),
            ("p", "Ogni contatore tiene conto degli altri filtri ma non del proprio: così vedi quante scadenze aggiungeresti."),
            ("passi", [
                "Imposta filtri e vista che usi di solito.",
                "Apri «★ Viste», scrivi un nome (es. «Antincendio scadute») e premi «Salva i filtri attuali».",
                "Spunta «apri questa vista entrando», oppure usa ☆ accanto alla vista, se vuoi trovarla ogni volta che apri lo scadenzario.",
            ]),
        ],
    },
    {
        "id": "scadenza",
        "titolo": "Cosa puoi fare su una scadenza",
        "blocchi": [
            ("def", [
                ("Clic sulla scadenza", "apre la pagina dove si gestisce, nel modulo di origine."),
                ("👤 Me ne occupo io", "tutti vedono il tuo nome accanto alla scadenza; con «＋ nota» aggiungi una riga (es. «chiamata la ditta»)."),
                ("👤 Subentro io", "prendi il posto di chi l'aveva."),
                ("✕ Lascia", "la liberi. Chi gestisce lo scadenzario può liberare anche quelle degli altri."),
                ("→ Assegna", "per chi ha la scadenza o gestisce lo scadenzario: scrivi il nome, sceglilo dall'elenco e conferma. La persona riceve una notifica, e anche chi l'aveva prima."),
                ("✓ Rinnovato oggi", "solo scadenze generiche, per chi gestisce la categoria: registra il rinnovo e calcola la prossima scadenza."),
            ]),
            ("nota", "Se la scadenza cambia data, la presa in carico decade da sola. Il nome si vede nello Scadenzario e nel riquadro delle schede dei moduli."),
        ],
    },
    {
        "id": "fonti",
        "titolo": "Da dove arrivano le scadenze",
        "blocchi": [
            ("p", "Ogni fonte è un modulo del portale. Vedi quelle dei moduli che puoi aprire, più ciò che il pannello Gestione ti concede."),
            ("def", [
                ("Personale (HR)", "qualifiche, visite mediche, corsi obbligatori, contratti a termine, periodi di prova."),
                ("Asset", "scadenze amministrative (revisioni, certificati), licenze software, contratti di assistenza."),
                ("Verifiche impianti", "la prossima verifica di ogni tipo attivo (estintori, luci di emergenza, quadri…)."),
                ("DPI", "DPI consegnati e non ancora sostituiti, alla data di fine vita utile."),
                ("RENTRI", "FIR mancanti e depositi temporanei vicini al limite."),
                ("Azioni CAPA", "azioni aperte con una scadenza; chi non gestisce le CAPA vede le proprie."),
                ("Sistema di gestione", "sorveglianza e scadenza dei certificati, audit interni ed esterni, risposta all'ente, analisi e chiusura delle CAR, verifica di efficacia, qualifica degli auditor, azioni della SoA, scenari di rischio OT."),
                ("Qualifiche di processo", "scadenza e revisione dei processi MOD.128, requisiti, certificazioni individuali, revisione delle abilitazioni macchina."),
                ("Formazione (enti e verifiche)", "documenti di enti e docenti, verifica assenza NC a 6 mesi."),
                ("SOC / NIS2", "azioni correttive degli incidenti, accettazioni del rischio, termini di legge NIS2 e GDPR con l'ora nel titolo."),
                ("GDPR", "verifica periodica degli amministratori di sistema."),
                ("Presa visione procedure", "prese visione aperte con scadenza (ognuno vede le proprie, chi gestisce le campagne tutte) e campagne pubblicate."),
                ("Fornitori (documenti di sicurezza)", "documenti con scadenza dei fornitori."),
                ("Registro OFI", "voci aperte con data di chiusura richiesta, senza CAR (quelle con CAR sono nel Sistema di gestione)."),
                ("Anomalie e NC", "azioni sulle non conformità e verifiche di efficacia previste; chi non apre le NC vede solo le proprie azioni."),
                ("KICK-OFF e attività", "solo le tue: attività e azioni degli incontri assegnate a te."),
                ("Suggestion Corner", "esecuzioni e controlli da fare sulle segnalazioni che puoi vedere."),
                ("Attrezzature", "attività aperte sulle attrezzature."),
                ("Ingressi e cambi mansione", "voci dell'inserimento, adempimenti del cambio mansione e deroghe operative alle visite."),
                ("Manutenzione programmata", "manutenzioni ordinarie e tarature. Sono molte voci: è spenta finché chi gestisce il pannello non la accende."),
                ("Scadenze generiche", "le attività inserite qui, divise per categoria."),
            ]),
        ],
    },
    {
        "id": "collegamenti",
        "titolo": "Come è collegato agli altri moduli",
        "blocchi": [
            ("def", [
                ("Dal modulo allo Scadenzario", "automatico: le scadenze si leggono dal modulo a ogni apertura. Chiudi o rinnovi nel modulo e la voce si aggiorna, non c'è nulla da copiare."),
                ("Dallo Scadenzario al modulo", "con il clic: porta alla scheda o, per alcune fonti (qualifiche della persona, depositi RENTRI, certificazioni individuali, abilitazioni macchina, accettazioni del rischio, GDPR), alla pagina generale del modulo."),
                ("Modifiche dallo Scadenzario", "solo sulle scadenze generiche. Le altre si cambiano nel loro modulo: lì ci sono controlli, allegati e registro propri."),
                ("Scheda del modulo → Scadenzario", "nelle schede di dipendente, asset, fornitore, certificazione, audit, incidente, verifica impianto e corso compare il riquadro «📅 Scadenze di questa scheda»: scadenze, chi se ne occupa, «Me ne occupo io» e link allo Scadenzario. Compare solo se c'è qualcosa che puoi vedere."),
                ("Attività collegata", "un'attività generica collegata a qualcosa si apre da entrambe le parti (vedi «Collegare un'attività alle cose già presenti»)."),
            ]),
            ("nota", "Se vedi una voce grazie a una regola del pannello ma non hai il permesso del modulo, il clic può darti accesso negato: chiedi a chi gestisce il modulo o al referente."),
        ],
    },
    {
        "id": "nuova",
        "titolo": "Scadenze generiche: inserire un'attività",
        "blocchi": [
            ("passi", [
                "Scadenzario → «🗂 Scadenze generiche» → «+ Nuova attività». Il pulsante c'è se gestisci almeno una categoria.",
                "Scegli la categoria e scrivi l'attività.",
                "Inserisci la «Scadenza», oppure «Ultimo controllo» e «Validità (mesi)»: la data si calcola da sola e la vedi subito.",
                "In «A chi arrivano gli avvisi» scrivi le email separate da virgola, oppure premi «Usa quelli della categoria».",
                "Scegli il «Responsabile»: vede l'attività anche senza altri permessi e la trova con «Solo le mie».",
                "«Salva».",
            ]),
            ("img", (_IMG + "nuova.jpg", "Il modulo: la scadenza calcolata compare accanto ai campi")),
            ("p", "«Altri dettagli» contiene preavviso, ripetizione, descrizione, ubicazione, asset e fornitore collegati. Se non servono, lasciali vuoti: valgono quelli della categoria."),
            ("nota", "Metti sempre la validità in mesi se l'attività si ripete: senza, «✓ Rinnovato oggi» non compare perché non si saprebbe la prossima scadenza."),
        ],
    },
    {
        "id": "rinnovo",
        "titolo": "Scadenze generiche: registrare un rinnovo",
        "blocchi": [
            ("p", "Rinnovare è di chi gestisce la categoria («Vedere e gestire»): il solo responsabile vede l'attività ma non la rinnova, se non ha anche una regola di gestione."),
            ("def", [
                ("Caso semplice", "«✓ Rinnovato oggi» nel calendario, nell'elenco o nella scheda. Conferma e la prossima scadenza si calcola dalla validità."),
                ("Con altra data, note o allegato", "apri la scheda → «Rinnovo con altra data, note o allegato» («Registra controllo / rinnovo» se manca la validità). "
                                                    "Compila «Eseguito il», che non può essere futura; «Nuova scadenza», vuota = controllo + validità; «Note»; «Allegato», fino a 20 MB. Poi «Registra»."),
            ]),
            ("nota", "Senza validità e senza «Nuova scadenza», il controllo si registra ma la scadenza resta quella di prima: l'attività continua a risultare scaduta."),
            ("p", "La scheda conserva lo «Storico dei rinnovi» (chi, quando, scadenza precedente e nuova, allegato) e gli «Ultimi avvisi inviati»."),
        ],
    },
    {
        "id": "collega",
        "titolo": "Scadenze generiche: collegare un'attività alle cose già presenti",
        "blocchi": [
            ("p", "Un'attività può rimandare a una certificazione, una verifica impianto, un asset, un fornitore, un tipo di qualifica o un corso. Non succede mai da solo: conferma sempre una persona."),
            ("def", [
                ("Collega", "ogni scheda rimanda all'altra e ognuna tiene la sua data."),
                ("Unisci", "solo per certificazioni e verifiche impianto, che hanno una data loro. Nel calendario resta una voce sola, quella del modulo; l'attività prende la data da lì, conserva storico e destinatari e continua a mandare gli avvisi."),
                ("Separa", "annulla l'unione: l'attività torna una voce a sé e resta collegata."),
                ("Scollega", "toglie il legame."),
            ]),
            ("passi", [
                "Scadenzario → «Collega»: le attività con un possibile collegamento, trovato confrontando i testi. Può sbagliare: leggi prima di confermare.",
                "Premi «Collega» o «Unisci» accanto alla proposta giusta; ignora le altre.",
                "Se la proposta non c'è, apri la scheda dell'attività: in «Collegamenti» scegli il tipo, cerca e conferma.",
            ]),
            ("p", "Se l'attività è un certificato non ancora presente nel Sistema di gestione: nella scheda usa «Crea la certificazione da questa attività». Il modulo si apre già compilato; salvando, l'attività resta unita alla nuova certificazione. Serve il permesso di modifica degli audit."),
            ("nota", "Un'attività unita non si rinnova nello Scadenzario: si aggiorna la data nel modulo e l'attività la segue il mattino dopo, o quando apri la sua scheda."),
        ],
    },
    {
        "id": "massa",
        "titolo": "Scadenze generiche: più attività insieme",
        "blocchi": [
            ("passi", [
                "Trova le righe con i filtri. «Mancano» trova quelle «Senza responsabile» o «Senza destinatari».",
                "Spunta le righe (la casella in testa le prende tutte).",
                "Nella barra in basso scegli «Cosa fare» e premi «Applica».",
            ]),
            ("img", (_IMG + "elenco.jpg", "Elenco con righe spuntate e barra delle azioni in basso")),
            ("def", [
                ("Assegna il responsabile", "«Nessuno» lo toglie."),
                ("Aggiungi destinatari degli avvisi", "somma gli indirizzi a quelli già presenti."),
                ("Sostituisci i destinatari degli avvisi", "cancella i presenti e mette i nuovi."),
                ("Usa i destinatari della categoria", "copia quelli della categoria di ogni attività."),
                ("Sospendi / Riattiva", "una sospesa non manda avvisi e non compare nel calendario. Per rivederla nell'elenco spunta «anche le sospese»."),
            ]),
            ("p", "Vale solo per le categorie che gestisci. «Excel» scarica l'elenco."),
        ],
    },
    {
        "id": "avvisi",
        "titolo": "Avvisi per mail",
        "blocchi": [
            ("def", [
                ("Avviso singolo", "ogni giorno alle 7:15, ai destinatari dell'attività, quando entra nel preavviso. Si ripete finché non registri il rinnovo."),
                ("Responsabile", "riceve una notifica nel portale quando diventa responsabile e poi a scaletta (preavviso, 14, 7 e 1 giorno prima, il giorno stesso, poi ogni 7 giorni), anche senza destinatari mail."),
                ("Riepilogo mensile", "il 1° del mese alle 8, alle email della categoria: tutte le attività scadute o in scadenza nei 60 giorni successivi."),
                ("Preavviso", "30 giorni, salvo diversa impostazione. Conta prima l'attività, poi la categoria, poi il valore generale."),
                ("Ripeti l'avviso ogni", "7 giorni, con lo stesso ordine."),
                ("Avvisa anche dopo la scadenza", "sulla categoria: le scadute continuano a mandare l'avviso. Se è spenta, dopo la scadenza restano solo nel riepilogo."),
            ]),
            ("nota", "Attività senza destinatari propri: nessun avviso singolo, solo il riepilogo mensile della categoria. È normale, ma per le attività importanti conviene aggiungere destinatari."),
            ("p", "La pagina «Avvisi» mostra in alto cosa partirà al prossimo invio, senza spedire nulla: le mail in partenza, le attività nel preavviso senza destinatari, quelle già avvisate che ripartiranno più avanti. "
                  "Sotto, «Già inviati» è il registro delle ultime 300 mail con l'esito; quelle importate sono segnate «vecchio scadenzario»."),
            ("img", (_IMG + "avvisi.jpg", "Anteprima del prossimo invio")),
        ],
    },
    {
        "id": "promemoria",
        "titolo": "Le scadenze fuori dal portale",
        "blocchi": [
            ("def", [
                ("Riepilogo personale per mail", "Impostazioni notifiche → «Riepilogo scadenze via mail»: alle 7:30 dei giorni feriali, le scadenze che puoi vedere. Se non c'è niente, la mail non parte."),
                ("Outlook sempre aggiornato", "Impostazioni notifiche → «Le mie scadenze nel calendario Outlook»: un calendario allineato ogni mattina alle 6:30."),
                ("⬇ Outlook (.ics)", "un file con le righe filtrate: ogni scadenza diventa un evento con promemoria il giorno prima alle 9. È una copia, non si aggiorna."),
                ("⬇ CSV", "le righe filtrate, scadute e prossimi 90 giorni."),
            ]),
        ],
    },
    {
        "id": "mail",
        "titolo": "Quali promemoria arrivano e a chi",
        "blocchi": [
            ("p", "Oltre agli avvisi delle scadenze generiche, ogni modulo ha i suoi promemoria. Chi vuole un solo riepilogo personale attiva quello in Impostazioni notifiche."),
            ("def", [
                ("Campanella del portale", "visite e formazione alla persona interessata: 30, 14, 7 e 1 giorno prima, il giorno stesso, poi il giorno dopo e ogni 7 giorni. Scadenza assegnata a te, attività generiche di cui sei responsabile."),
                ("Home", "«Le mie scadenze» in «Cose da gestire»: scadute ed entro 7 giorni, senza quelle sanitarie."),
                ("Mail personale", "riepilogo facoltativo alle 7:30 dei giorni feriali."),
                ("Mail ai referenti", "HR per visite, contratti e formazione; gestori DPI; referenti asset per le manutenzioni; RSGI per certificati e CAR; Qualità per Part 145; responsabili RENTRI; assegnatari per le prese visione."),
            ]),
        ],
    },
    {
        "id": "categorie",
        "titolo": "Per chi gestisce: categorie e chi le vede",
        "blocchi": [
            ("p", "Da fare per prima cosa. Senza regole le scadenze generiche le vedono solo chi gestisce il pannello e il responsabile dell'attività."),
            ("passi", [
                "Scadenzario → «Categorie»: la tabella mostra attività, chi vede ogni categoria, destinatari del riepilogo e impostazioni degli avvisi.",
                "«Apri» sulla categoria.",
                "In «Chi la vede e chi la gestisce» scegli dal menu «Aggiungi» un ruolo aziendale, un ruolo del portale o una persona.",
                "In «Può» scegli «Solo vedere» o «Vedere e gestire», poi «Aggiungi». «Togli» rimuove.",
                "In «Avvisi e dati della categoria» controlla le email del riepilogo e «Salva».",
            ]),
            ("img", (_IMG + "categoria.jpg", "Scheda della categoria: chi la vede e impostazioni degli avvisi")),
            ("p", "Meglio un ruolo aziendale che le persone: quando cambia chi ricopre il ruolo, il permesso segue da solo. «+ Nuova categoria» è di chi gestisce il pannello."),
        ],
    },
    {
        "id": "gestione",
        "titolo": "Per chi gestisce: pannello Gestione",
        "blocchi": [
            ("p", "«Da sistemare» elenca solo ciò che manca, con il link per farlo."),
            ("def", [
                ("Categorie senza destinatari del riepilogo", "le loro attività senza email propria non avvisano nessuno."),
                ("Attività scadute", "da rinnovare, o da sospendere se non servono più."),
                ("Categorie senza nessuno assegnato", "le vedono solo il pannello e il responsabile."),
                ("Attività senza responsabile", "nessuno le trova con «Solo le mie»."),
                ("Attività nel preavviso senza destinatari", "compaiono solo nel riepilogo mensile."),
            ]),
            ("img", (_IMG + "gestione.jpg", "Pannello Gestione: albero delle voci e dettaglio")),
            ("p", "A sinistra l'albero: fonte → tipo → singolo elemento. Si aggiorna da solo; un elemento compare quando ha una scadenza scaduta o nei prossimi 90 giorni. "
                  "Il numero accanto è quante scadenze ci sono oggi. Clic su una voce: la frase in alto dice chi la vede oggi."),
            ("def", [
                ("Regole", "aggiungono persone o ruoli alla voce e a tutto ciò che sta sotto."),
                ("Compare nello scadenzario", "«No» la toglie a tutti, con ciò che sta sotto; un elemento sotto può riaccendersi con «Sì»."),
                ("Chi la vede", "«Chi ha il permesso del modulo, più le regole» è il predefinito. «Solo chi è nelle regole» la limita alle regole e agli amministratori."),
                ("Vedere e gestire", "ha effetto solo sulle scadenze generiche."),
                ("Chi gestisce questo pannello", "gli amministratori sempre; qui si aggiungono altri ruoli o persone."),
            ]),
            ("nota", "Le visite mediche sono dati sanitari: una regola le mostra anche a chi non apre il modulo. Concedile solo a medico competente, RSPP e HR. Ogni modifica resta nel registro attività."),
        ],
    },
    {
        "id": "problemi",
        "titolo": "Se qualcosa non torna",
        "blocchi": [
            ("def", [
                ("Non vedo una scadenza", "non hai il permesso del modulo e nessuna regola, oppure è spenta, è oltre i 90 giorni (cerca nel Calendario) o è esclusa da un filtro: prova «✕ Togli tutti i filtri»."),
                ("Non c'è «✓ Rinnovato oggi»", "l'attività non ha la validità in mesi, oppure non gestisci la categoria. Nel calendario il pulsante compare solo nelle generiche."),
                ("Il rinnovo non cambia la scadenza", "manca la validità e non hai scritto «Nuova scadenza»: registra di nuovo indicandola."),
                ("Non arriva l'avviso", "apri «Avvisi»: l'attività può essere senza destinatari, già avvisata, fuori preavviso o sospesa."),
                ("Clic su una voce e accesso negato", "la vedi per una regola del pannello, ma non hai il permesso del modulo."),
                ("Una scadenza è sbagliata", "correggila nel modulo di origine: lo Scadenzario la legge da lì."),
                ("Un'attività non è più nel calendario", "può essere sospesa o unita a un modulo: nell'elenco compare «unita al modulo» e nel calendario trovi la voce del modulo."),
            ]),
        ],
    },
]
