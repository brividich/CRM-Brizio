"""Guida d'uso del modulo Gestione anomalie.

Un solo contenuto per tre uscite:

* la pagina della guida, aperta con ``?guida=1`` da qualunque pagina del modulo
  (stessi permessi della pagina da cui si parte, nessuna rotta ACL nuova);
* il PDF scaricabile (``?guida=pdf``);
* il riquadro «Come funziona questa pagina» della pagina raggiunta dal link della
  mail, che e' pubblica e quindi non puo' rimandare a una pagina col login.

Ogni pagina ha il suo pulsante «?» che apre la guida sul paragrafo giusto
(:data:`PAGINE`).

Testo semplice, niente HTML: il template lo mostra con l'autoescape e il PDF lo
passa da ``escape()``. Blocchi di una sezione: ``("p", testo)`` paragrafo,
``("passi", [voci])`` passi numerati, ``("ul", [voci])`` elenco, ``("nota",
testo)`` riquadro di attenzione, ``("def", [(termine, spiegazione)])``
definizioni. Le etichette citate sono quelle visibili nelle pagine: se ne cambia
una, va aggiornata anche qui.
"""
from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

DOC_TITOLO = "Gestione anomalie"
DOC_SOTTOTITOLO = "Guida d'uso del modulo nel portale NOVICROM HUB"

SEZIONI: list[dict] = [
    {
        "id": "in-breve",
        "titolo": "Il modulo in breve",
        "blocchi": [
            ("p", "Il modulo registra le anomalie trovate sui pezzi durante i controlli di produzione e porta "
                  "ogni anomalia fino a una decisione del capocommessa."),
            ("passi", [
                "L'operatore apre un controllo sull'OP, indica la fase e registra le anomalie a blocchi di seriali, "
                "con foto e documenti.",
                "Il capocommessa riceve una mail con il link e decide anomalia per anomalia: avanzamento, RDC, "
                "segnalazione al cliente, note. Il CAR è in copia.",
                "L'operatore che ha segnalato riceve una mail con la decisione e una notifica nel portale.",
                "Le anomalie chiuse restano consultabili; statistiche, estrazioni e non conformità raccolgono lo storico.",
            ]),
            ("def", [
                ("OP", "l'ordine di produzione, con P/N, capocommessa e CAR."),
                ("Controllo", "una sessione di verifica su un OP in una fase (per esempio «collaudo finale»)."),
                ("Blocco", "un gruppo di seriali con le stesse anomalie e lo stesso stato superficie."),
                ("Anomalia", "un difetto descritto su quei seriali, con i suoi allegati e la sua decisione."),
                ("CAR", "il caporeparto responsabile dell'OP."),
                ("RDC", "la richiesta di concessione/deroga da aprire quando il pezzo non è conforme."),
            ]),
        ],
    },
    {
        "id": "chi-fa-cosa",
        "titolo": "Chi fa cosa",
        "blocchi": [
            ("def", [
                ("Operatore / collaudatore", "apre i controlli e segnala le anomalie («Apertura Segnalazione»)."),
                ("Capocommessa dell'OP", "decide sulle anomalie dei propri OP, dal portale o dal link della mail."),
                ("CAR dell'OP", "riceve le mail in copia e, se abilitato, decide sugli OP di cui è incaricato. "
                 "Per i collaudi di benestare è il destinatario principale."),
                ("Chi gestisce tutti gli OP", "decide su qualunque OP (permesso di modifica globale)."),
                ("Amministratori del modulo", "configurano liste, promemoria, accessi e vedono i log."),
            ]),
            ("p", "Chi può solo consultare vede tutto ma trova i campi della decisione disattivati, con l'avviso "
                  "«Sola lettura». I pulsanti del menu compaiono solo a chi ha il permesso corrispondente."),
        ],
    },
    {
        "id": "menu",
        "titolo": "Il menu Anomalie",
        "blocchi": [
            ("def", [
                ("Apertura Segnalazione", "apre un nuovo controllo su un OP e registra le anomalie."),
                ("Segnalazioni Aperte", "apre Gestione anomalie sugli OP con anomalie aperte."),
                ("Segnalazioni in Carico", "apre Gestione anomalie sugli OP di cui sei capocommessa o CAR."),
                ("Non Conformità", "le schede di non conformità per OP."),
                ("Configurazione liste", "in basso a destra, solo per gli amministratori."),
            ]),
        ],
    },
    {
        "id": "controllo",
        "titolo": "Segnalare: aprire un controllo",
        "blocchi": [
            ("passi", [
                "Dal menu premi «Apertura Segnalazione».",
                "Cerca l'OP per titolo, P/N, capocommessa o CAR e cliccalo. Se l'OP non esiste ancora, «+ Nuovo OP»: "
                "compila P/N, poi anno e numero, infine capocommessa e CAR (i campi si sbloccano in ordine) e premi "
                "«Crea OP e continua».",
                "Scrivi la «Fase del controllo», per esempio accettazione materiale, lavorazione o collaudo finale. "
                "Vale per tutti i blocchi e si può cambiare durante il controllo con «Cambia».",
                "Scegli come avvisare il capocommessa: «A ogni blocco salvato» oppure «Una sola mail a fine controllo».",
                "Premi «Inizia controllo».",
            ]),
            ("p", "Se sull'OP hai già un controllo lasciato aperto, compare «Hai un controllo ancora aperto su questo OP»: "
                  "con «Riprendi» continui da dove eri rimasto."),
            ("def", [
                ("A ogni blocco salvato", "la mail parte qualche minuto dopo l'ultimo salvataggio; più blocchi salvati "
                 "di seguito arrivano in un'unica mail."),
                ("Una sola mail a fine controllo", "la mail parte con «Termina controllo», oppure da sola dopo 4 ore senza "
                 "salvataggi."),
            ]),
        ],
    },
    {
        "id": "blocchi",
        "titolo": "Segnalare: blocchi di seriali e anomalie",
        "blocchi": [
            ("passi", [
                "In «Seriali» scrivi un seriale, un range (LCN00005-LCN00010) o più seriali separati da virgola e premi "
                "Invio. Sotto compare il totale dei pezzi.",
                "Se richiesto, scegli lo «Stato superficie del blocco»: vale per tutti i pezzi del blocco.",
                "Descrivi l'anomalia: cosa hai rilevato, dove si trova sul pezzo, misura rilevata e tolleranza.",
                "Con più pezzi nel blocco, sotto la descrizione c'è la casella «Presente su tutti i N seriali del blocco», "
                "già spuntata. Se l'anomalia è solo su alcuni pezzi toglila e tocca i seriali interessati: un range "
                "compare pezzo per pezzo. Per sceglierne più di fila tieni premuto su un seriale e trascina sugli altri "
                "(se il primo era spento li accende, se era acceso li spegne). Ci sono anche «Seleziona tutti» e «Nessuno».",
                "Aggiungi foto e documenti: trascinali nel riquadro, sfogliali, oppure clicca nel riquadro e premi Ctrl+V "
                "per incollare uno screenshot o una foto copiata.",
                "Altre anomalie sugli stessi seriali: «+ Nuova anomalia su questi seriali». Le precedenti si comprimono.",
                "Premi «Salva blocco»: il blocco si congela e se ne apre uno nuovo.",
            ]),
            ("ul", [
                "Pezzi in stati superficie diversi vanno in blocchi separati. Anomalie diverse su pezzi diversi invece "
                "stanno nello stesso blocco: per ognuna scegli i seriali togliendo «Presente su tutti i seriali del "
                "blocco». Nel blocco salvato, nel riepilogo, nella mail e nella gestione compare «Solo …» con i seriali "
                "scelti.",
                "Gli avvisi gialli sui seriali (formato, prefisso diverso) non bloccano il salvataggio: servono a evitare "
                "errori di battitura.",
                "Se un seriale ha già un'anomalia aperta sull'OP, accanto al campo compaiono descrizione, stato e chi l'ha "
                "inserita: controlla che non sia un doppione.",
                "Lo stesso seriale in due blocchi è ammesso (altra fase o altro stato superficie) ma va confermato con "
                "«Sì, è voluto: salva». Per aggiungere anomalie a pezzi già registrati usa invece «Modifica o aggiungi "
                "anomalie» sul blocco esistente.",
                "«Suggerimento AI sul triage» propone stato superficie, avanzamento e una bozza di descrizione: non salva "
                "nulla, decidi tu cosa usare.",
                "Un blocco salvato si riapre con «Modifica o aggiungi anomalie» finché il capocommessa non ha deciso. Dopo "
                "la decisione seriali e anomalie già gestite restano bloccati, ma si possono aggiungere nuove anomalie.",
            ]),
        ],
    },
    {
        "id": "fine-controllo",
        "titolo": "Segnalare: terminare il controllo",
        "blocchi": [
            ("passi", [
                "Premi «Termina controllo…». Se il blocco in corso non è salvato, scegli «Salva e vai al riepilogo» o "
                "«Scarta il blocco».",
                "Controlla il «Riepilogo del controllo»: blocchi, pezzi, anomalie, allegati e a chi andrà la mail.",
                "Premi «Conferma e termina».",
            ]),
            ("p", "La pagina finale «Controllo terminato» dice se la mail con il link di decisione è partita e a chi. "
                  "Da qui puoi stampare il riepilogo, controllare un altro OP o aprire un nuovo controllo sullo stesso OP."),
            ("nota", "Se capocommessa e CAR dell'OP non hanno un indirizzo email, il riepilogo lo segnala in rosso: la mail "
                     "non può partire, avvisa l'ufficio. Se l'invio non riesce, il sistema riprova da solo."),
        ],
    },
    {
        "id": "gestione",
        "titolo": "Gestione anomalie: trovare l'OP e l'anomalia",
        "blocchi": [
            ("p", "La pagina ha tre colonne: ordini di produzione, anomalie dell'OP scelto, dettaglio dell'anomalia. "
                  "Da telefono le tre colonne diventano le schede Ordini, Anomalie e Dettaglio in basso."),
            ("ul", [
                "Ordini: i filtri «Tutti», «Con aperte» e «In carico a me» con i conteggi; la ricerca trova OP, P/N, "
                "capocommessa e CAR. Il numero arancione su un OP indica le anomalie da decidere.",
                "Anomalie: raggruppate per blocco di seriali, con fase, operatore e data. «Da decidere» mostra solo quelle "
                "senza decisione; le chiuse sono raccolte in fondo in «Chiuse».",
                "Dettaglio: in alto OP, seriali, fase e se è un «Collaudo di benestare»; le frecce (o Alt+↑ / Alt+↓) "
                "passano all'anomalia precedente o successiva.",
                "«Nuova segnalazione» apre un controllo sull'OP. Il menu ⋯ contiene «Report OP», «Report OP in PDF», "
                "«Duplica anomalia come nuovo record» e, per gli amministratori, «Configurazione modulo».",
            ]),
        ],
    },
    {
        "id": "decisione",
        "titolo": "Decidere su un'anomalia (capocommessa)",
        "blocchi": [
            ("passi", [
                "Apri l'OP e scegli l'anomalia (filtro «Da decidere» per vedere solo quelle aperte).",
                "Leggi la «Segnalazione» e guarda gli allegati: un clic su una foto la ingrandisce.",
                "Nella «Decisione del capocommessa» scegli i flag: «Aprire RDC», «Segnalare al cliente», «Pezzi precedenti "
                "al benestare».",
                "Scegli l'«Avanzamento». Con «Aprire RDC» indica anche il «Numero RDC».",
                "Scrivi la «Risposta / note per il reparto»: decisione, istruzioni di rilavorazione, riferimenti.",
                "Premi «Salva» (Ctrl+S) oppure «Salva e prossima» per passare subito alla successiva.",
            ]),
            ("ul", [
                "L'anomalia si chiude da sola al salvataggio quando apri un RDC o scegli «Accetto lo stato» o «Apertura "
                "ORE/RIPI»: la pagina lo avvisa prima di salvare.",
                "Con «Segnalare al cliente» l'avanzamento resta quello attuale.",
                "«Applica la stessa decisione anche alle altre anomalie aperte di questi seriali» copia la decisione sulle "
                "altre anomalie aperte del blocco.",
                "Se cambi anomalia o OP senza salvare, la pagina chiede se salvare, scartare o restare.",
                "Puoi aggiungere allegati anche qui (trascina, sfoglia o Ctrl+V) e correggere il testo con «Modifica testo».",
                "«Cronologia azioni», in fondo al dettaglio, mostra chi ha fatto cosa sull'OP, dal portale e dalla mail.",
            ]),
            ("p", "Al salvataggio parte in automatico, qualche minuto dopo, la mail di riepilogo al segnalante, al "
                  "capocommessa, al CAR e alla lista configurata; le anomalie con RDC o da segnalare al cliente sono "
                  "evidenziate in cima. Non serve nessun pulsante di invio."),
        ],
    },
    {
        "id": "mail",
        "titolo": "Decidere dal link della mail",
        "blocchi": [
            ("p", "Il link della mail apre una pagina che non chiede il login: il link stesso è l'autorizzazione, "
                  "quindi non va inoltrato."),
            ("passi", [
                "Apri il link: in cima le anomalie della mail («Da decidere»), sotto le altre ancora aperte sull'OP.",
                "Espandi un'anomalia per vedere descrizione, foto e allegati. «Espandi tutte» le apre tutte.",
                "Nella «Decisione su questa anomalia» scegli «Aprire RDC?», «Segnalare a cliente?», il «Nuovo avanzamento» "
                "e scrivi la risposta. «Chiudere? (automatico)» si calcola da solo.",
                "Per decidere tutto un blocco insieme compila il riquadro del blocco e premi «Applica a tutte».",
                "Premi «Conferma e invia aggiornamenti», controlla il riepilogo e conferma con «Conferma e invia».",
            ]),
            ("ul", [
                "Cambiano solo le anomalie che hai toccato: le altre restano com'erano.",
                "Dopo la conferma il link non si può più usare per un'altra decisione; il link scade dopo il tempo "
                "configurato.",
                "Foto e PDF si aprono nel browser; gli altri file si scaricano.",
            ]),
        ],
    },
    {
        "id": "avvisi",
        "titolo": "Mail, notifiche e promemoria automatici",
        "blocchi": [
            ("def", [
                ("Mail del controllo", "al capocommessa con il link di decisione, il CAR in copia (per i collaudi di "
                 "benestare il contrario)."),
                ("Riepilogo dopo una decisione", "al segnalante, al capocommessa, al CAR e alla lista configurata, qualche "
                 "minuto dopo l'ultimo salvataggio. RDC e segnalazioni al cliente vanno anche al destinatario dedicato."),
                ("Decisioni all'operatore", "chi ha segnalato riceve una mail con la decisione e una notifica nel portale "
                 "che apre l'OP."),
                ("Promemoria", "a capocommessa e CAR, nella dashboard, per gli OP con anomalie «In attesa»; si chiudono da "
                 "soli quando l'OP è stato gestito."),
                ("Resoconto giornaliero", "nei giorni lavorativi, se attivato dagli amministratori."),
            ]),
            ("p", "Le mail inviate dal modulo sono registrate e si possono rispedire dalla configurazione (Log attività)."),
        ],
    },
    {
        "id": "non-conformita",
        "titolo": "Non conformità per OP",
        "blocchi": [
            ("p", "Ogni OP con anomalie ha una scheda di non conformità (protocollo NC-anno-numero) secondo ISO 9001 "
                  "§10.2. Tutte le sezioni sono facoltative: lo stato si calcola da ciò che è compilato."),
            ("ul", [
                "L'elenco filtra per stato (Aperte, Contenimento, Analisi cause, Azioni in corso, In verifica, Chiusa, "
                "Tutte), cerca per OP, P/N o protocollo e ha «Solo le mie» e «Con azioni scadute».",
                "Nella scheda: «Azioni di contenimento», analisi delle cause (5 perché, Ishikawa o documento esterno) con "
                "«Causa radice», azioni correttive con responsabile e scadenza, verifica di efficacia, allegati e storico. "
                "Ogni sezione ha il suo pulsante di salvataggio.",
                "«Proponi analisi e azioni» chiede all'AI una proposta: non salva nulla.",
                "«Chiudi NC» e «Riapri NC» sono riservati a chi è indicato nella configurazione (scheda Qualità).",
                "«PDF» scarica la scheda; «Anomalie dell'OP» riporta alla gestione.",
            ]),
        ],
    },
    {
        "id": "statistiche",
        "titolo": "Statistiche ed estrazioni",
        "blocchi": [
            ("passi", [
                "Imposta i filtri: periodo di creazione, avanzamento, nominativo OP, stato, RDC, segnalazione cliente e "
                "ricerca libera (seriale, descrizione, OP, RDC).",
                "Premi «Aggiorna»; «Azzera filtri» li toglie.",
                "Leggi i KPI in alto e le tabelle per avanzamento, per mese, per difetto, origine e decisione, e i top OP.",
                "In «Ricerca dettaglio» scorri le anomalie (25 per pagina) e scarica tutto con «Esporta CSV»: l'export "
                "rispetta i filtri ed è registrato.",
            ]),
        ],
    },
    {
        "id": "configurazione",
        "titolo": "Configurazione (amministratori)",
        "blocchi": [
            ("def", [
                ("Riepilogo", "la distribuzione delle anomalie per avanzamento."),
                ("Configurazione", "logo del menu, modello del Report OP, liste (avanzamenti, stati superficie, causali, "
                 "destinatari), composizione di capicommessa e CAR dai ruoli operativi dell'Anagrafica, promemoria e "
                 "automazioni."),
                ("Qualità", "catalogo dei tipi difetto e chi può chiudere le non conformità."),
                ("Permessi", "ruoli operativi (sola lettura, dall'Anagrafica) e regole di accesso per ruolo e per "
                 "singolo utente."),
                ("Record", "le ultime anomalie registrate, con ricerca."),
                ("Log attività", "audit del modulo e registro delle mail inviate, con «Reinvia»."),
            ]),
            ("nota", "Le automazioni di promemoria (difetto ricorrente, RDC senza numero, digest settimanale, OP completato) "
                     "sono spente di default: si accendono dalla scheda Configurazione."),
        ],
    },
    {
        "id": "faq",
        "titolo": "Domande frequenti",
        "blocchi": [
            ("def", [
                ("Non trovo l'OP.", "Cercalo per P/N o capocommessa. Se non esiste, crealo con «+ Nuovo OP» in Apertura "
                 "Segnalazione."),
                ("Ho salvato un blocco con un errore.", "«Modifica o aggiungi anomalie» lo riapre finché il capocommessa non "
                 "ha deciso."),
                ("Il capocommessa non ha ricevuto la mail.", "Controlla nel riepilogo del controllo a chi è andata; gli "
                 "amministratori la vedono e la possono reinviare da Configurazione → Log attività."),
                ("Vedo i campi della decisione grigi.", "Non sei capocommessa o CAR dell'OP e non hai il permesso di "
                 "modifica globale: chiedilo a un amministratore."),
                ("Il link della mail dice che è scaduto o già usato.", "Apri l'OP dal portale in Gestione anomalie."),
            ]),
        ],
    },
]

# Pagina del modulo -> paragrafo della guida aperto dal pulsante «?».
PAGINE = {
    "anomalie_menu": "menu",
    "apertura_segnalazione": "controllo",
    "gestione_anomalie_page": "gestione",
    "anomalie_statistiche_page": "statistiche",
    "anomalie_configurazione_page": "configurazione",
    "anomalie_nc_lista": "non-conformita",
    "anomalie_nc_dettaglio": "non-conformita",
    "anomalie_mail_action": "mail",
}

_SEZIONI_PER_ID = {sezione["id"]: sezione for sezione in SEZIONI}


def sezione(sezione_id: str) -> dict | None:
    return _SEZIONI_PER_ID.get(sezione_id)


def con_guida(view_func):
    """La view risponde con la guida a ``?guida=1`` (pagina) o ``?guida=pdf``.

    Si mette sotto i decoratori di accesso della view: la guida ha quindi gli
    stessi permessi della pagina da cui la si apre e non serve nessuna rotta
    (ne' binding ACL) nuova.
    """
    from functools import wraps

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        formato = str(request.GET.get("guida") or "").strip().lower()
        if request.method == "GET" and formato in ("1", "pdf"):
            return guida_response(request, formato)
        return view_func(request, *args, **kwargs)

    return _wrapped


def guida_response(request, formato: str) -> HttpResponse:
    if formato == "pdf":
        from core.guida_pdf import render_guida_pdf

        autore = (request.user.get_full_name() or request.user.get_username() or "").strip()
        pdf = render_guida_pdf(
            titolo=DOC_TITOLO,
            sottotitolo=DOC_SOTTOTITOLO,
            sezioni=SEZIONI,
            generato_da=autore,
            generato_il=timezone.localdate().strftime("%d-%m-%Y"),
        )
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="Guida_Gestione_Anomalie.pdf"'
        return response
    return render(
        request,
        "anomalie/pages/guida.html",
        {
            "page_title": f"Guida · {DOC_TITOLO}",
            "doc_titolo": DOC_TITOLO,
            "sezioni": SEZIONI,
            "torna_url": request.path,
        },
    )
