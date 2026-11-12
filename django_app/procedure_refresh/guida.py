"""Guida d'uso di CN-SGI (libreria delle procedure).

Si apre con ``?guida=1`` da qualunque pagina della libreria (stessi permessi della
pagina da cui si parte, nessuna rotta nuova) e si scarica in PDF con ``?guida=pdf``.
Il pulsante «? Guida» di ogni pagina porta al paragrafo giusto.

Testo semplice, niente HTML. Blocchi: ``("p", testo)``, ``("passi", [voci])``,
``("ul", [voci])``, ``("nota", testo)``, ``("def", [(termine, spiegazione)])``.
Le etichette sono quelle visibili nelle pagine: se ne cambia una, va cambiata anche qui.
"""
from __future__ import annotations

from functools import wraps

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

DOC_TITOLO = "CN-SGI"
DOC_SOTTOTITOLO = "Guida d'uso della libreria delle procedure nel portale NOVICROM HUB"

SEZIONI: list[dict] = [
    {
        "id": "in-breve",
        "titolo": "CN-SGI in breve",
        "blocchi": [
            ("p", "CN-SGI raccoglie le procedure del sistema di gestione integrato che stanno nella cartella di rete "
                  "«sistema gestione integrato»: manuali, MT, MTSI, istruzioni, modelli MOD e piani qualità dei clienti. "
                  "Si apre dal menu «CN-SGI» oppure da Sapere."),
            ("ul", [
                "Ogni scaffale è una certificazione (9100, 27001, 45001, 125, PART 145, Piani Qualità): le sezioni sono le sue sottocartelle.",
                "Si vede sempre e solo la revisione in vigore. L'archivio SUPERATO non è mostrato a nessuno.",
                "Il portale legge la cartella e non la modifica mai: per cambiare un documento la qualità emette una nuova revisione.",
            ]),
            ("def", [
                ("Revisione in vigore", "il file presente oggi nella cartella SGI per quel codice."),
                ("Nuova revisione", "un documento nuovo o con revisione più alta comparso negli ultimi 30 giorni: ha la fascia «NUOVA REV.»."),
                ("Da leggere", "un documento per cui ti è stata chiesta la presa visione: ha la fascia «DA LEGGERE»."),
            ]),
        ],
    },
    {
        "id": "scaffali",
        "titolo": "Scaffali e sezioni",
        "blocchi": [
            ("passi", [
                "In «Libreria» clicca la copertina di uno scaffale.",
                "A sinistra scegli una sezione (per esempio «MT» o «Modelli»), oppure «Tutte».",
                "Scrivi nel campo «Filtra in questo scaffale» per restringere l'elenco a codice o titolo.",
                "Scegli «Copertine» per i fogli con il cartiglio o «Elenco» per una tabella compatta: la scelta resta per le volte successive.",
                "Restringi con il tipo (Manuali, MT, MTSI, MOD, Piani qualità), con «Cambiati negli ultimi 30 giorni / 90 giorni / ultimo anno» e ordina «Per codice», «Più recenti» o «Più consultati». «Togli i filtri» riparte da capo.",
                "«Etichette QR» prepara le etichette di tutto lo scaffale, o della sezione scelta, pronte da stampare.",
            ]),
            ("p", "Sotto ogni copertina di scaffale c'è la prossima sorveglianza della certificazione collegata: pallino giallo se mancano meno di 30 giorni."),
        ],
    },
    {
        "id": "ricerca",
        "titolo": "Cercare in tutte le procedure",
        "blocchi": [
            ("passi", [
                "Scrivi nella ricerca in alto (il tasto «/» ci porta il cursore) un codice, un titolo o una frase: sotto compaiono subito i documenti che corrispondono, e con le frecce li scegli. Col campo vuoto vedi le tue ricerche recenti.",
                "«Cerca … anche nel testo dei documenti →» apre «Ricerca»: lì i risultati si aggiornano mentre scrivi.",
                "In «Ricerca» scegli dove cercare: «Codice, titolo e testo», «Solo codice e titolo» o «Solo testo dei documenti».",
                "Spunta uno o più scaffali per restringere i risultati.",
                "Ogni risultato mostra il paragrafo e la pagina: clicca «§ … · pag. N ↗» per aprire il PDF a quella pagina.",
            ]),
            ("ul", [
                "Le parole valgono in qualunque ordine e anche lontane fra loro; «di», «della», «per» e simili non contano.",
                "Ogni parola si cerca per radice: «procedura» trova anche «procedure», «conformita» trova «conformità».",
                "I codici valgono con o senza zeri e separatori: «MT 6» trova MT CN 06, «mod93» trova MOD.093.",
                "Una parola scritta male si corregge con la più simile che c'è nei documenti: la pagina scrive «Cercato anche …».",
                "Se nessun documento ha tutte le parole, la pagina mostra quelli a cui ne manca una e lo dice.",
            ]),
            ("nota", "La ricerca non bada a maiuscole e accenti. I PDF scansionati senza testo si trovano solo per codice e titolo."),
            ("p", "Le procedure si trovano anche dalla ricerca in alto nel portale («Cerca o vai a…», Ctrl+K), gruppo «CN-SGI · Procedure». "
                  "Quando l'assistente AI cita una procedura, l'etichetta della fonte apre la sua scheda nella libreria."),
        ],
    },
    {
        "id": "scheda",
        "titolo": "La scheda del documento",
        "blocchi": [
            ("p", "Un clic su un documento apre la scheda in un pannello a destra, senza lasciare la pagina."),
            ("ul", [
                "«Leggi qui» apre il PDF dentro il pannello (scheda «Anteprima»); i titoli dell'indice e i risultati della ricerca lo aprono alla pagina giusta. «Apri il PDF ↗» lo apre in una nuova scheda del browser.",
                "La stella ☆ in alto a destra mette il documento tra «I miei documenti», la prima fila della libreria. Sulle copertine «✓ letta» vuol dire che hai confermato la lettura di questa revisione.",
                "«Cosa cambia» confronta la revisione in vigore con la precedente, paragrafo per paragrafo: «Nuovo», «Tolto», «Cambiato» con le frasi tolte (barrate) e aggiunte. C'è solo se il testo della revisione precedente era stato letto dal portale.",
                "«QR» apre l'etichetta con il QR del documento da stampare e affiggere in reparto: inquadrata col telefono apre la scheda.",
                "In «Panoramica», «Chiedi all'assistente su questo documento» apre l'assistente AI con la domanda già riferita al documento.",
                "In «Collegamenti» la mappa mostra a sinistra i documenti che lo citano e a destra quelli che cita.",
                "«Panoramica»: scaffale, revisione, pagine, processi e l'indice dei paragrafi con la pagina.",
                "«Collegamenti»: i documenti che cita e quelli che lo citano, ricavati dal testo.",
                "«Revisioni»: lo storico; si apre solo quella in vigore.",
                "«Presa visione»: se ti è stata chiesta, «Apri la lettura e conferma».",
                "«Segnala»: proponi una modifica; arriva a chi gestisce CN-SGI.",
            ]),
        ],
    },
    {
        "id": "letture",
        "titolo": "Le mie letture",
        "blocchi": [
            ("p", "«Le mie letture» elenca i documenti per cui ti è stata chiesta la presa visione, con la scadenza. "
                  "Il numero accanto alla voce dice quanti ne restano. In «Libreria» gli stessi documenti sono nella fila «Da leggere per te»."),
            ("p", "Nella stessa pagina, «Le mie segnalazioni» mostra le modifiche che hai proposto e il loro stato (aperta, presa in carico, recepita nella revisione, respinta) con la risposta. "
                  "Quando lo stato cambia ricevi una notifica nel portale."),
        ],
    },
    {
        "id": "visibilita",
        "titolo": "Chi vede cosa (per chi gestisce)",
        "blocchi": [
            ("passi", [
                "Apri «Chi vede cosa».",
                "Scegli lo scaffale e, se serve, una sezione o un singolo documento.",
                "In «Chi vede» scegli «Solo i ruoli scelti» e spunta i ruoli, oppure «Solo chi gestisce CN-SGI».",
                "Clicca «Salva la regola». Nella tabella «Regole attive» vedi quanti documenti tocca ogni regola; «Togli» la cancella.",
            ]),
            ("ul", [
                "Vince la regola più precisa: documento, poi sezione, poi scaffale. Senza regole il documento è di tutti.",
                "Chi gestisce CN-SGI, gli amministratori e i ruoli «vede tutto» vedono sempre tutto.",
                "Un documento riservato non compare in Bacheca, l'assistente AI non lo cita e la sua scheda non si apre a chi non ha il ruolo.",
                "I documenti segnati come sensibili (esclusi dall'AI) li vede solo chi gestisce CN-SGI.",
            ]),
        ],
    },
    {
        "id": "gestione-scaffali",
        "titolo": "Scaffali (per chi gestisce)",
        "blocchi": [
            ("p", "In «Scaffali» cambi nome, sigla, norma, colore e ordine delle copertine, colleghi la certificazione "
                  "(scadenza e sorveglianza sulla copertina) e nascondi uno scaffale togliendo «Mostrato»."),
            ("p", "«Icona» mette un pittogramma sulla copertina (aereo, scudo, ambiente…); «Logo» carica un'immagine JPG, PNG o WebP, "
                  "per esempio il logo dell'ente di certificazione, che compare in alto a destra della copertina e nella testata dello scaffale. "
                  "Il logo viene ridotto e ricodificato; «Togli» lo rimuove. Clicca «Salva gli scaffali»."),
            ("p", "«Allinea scaffali e sezioni» crea gli scaffali delle cartelle nuove e riallinea le sezioni dai percorsi già registrati, senza leggere la cartella."),
        ],
    },
    {
        "id": "collegamenti",
        "titolo": "Collegamenti ai moduli (per chi gestisce)",
        "blocchi": [
            ("passi", [
                "Apri «Collegamenti ai moduli».",
                "In «Proposte da confermare» spunta i collegamenti giusti (trovati dalle parole del codice e del titolo) e clicca «Conferma le spuntate».",
                "Per aggiungerne uno a mano scegli documento e modulo, spunta «Si compila nell'HUB» se il modello cartaceo è stato digitalizzato da quel modulo, e clicca «Collega».",
                "«Togli» cancella un collegamento.",
            ]),
            ("ul", [
                "Sulle pagine del modulo la procedura compare in alto a destra, sotto «Procedure», come etichetta «SGI · codice Rev.» (al massimo tre, poi «+N»).",
                "Nella scheda del documento, scheda «Collegamenti», c'è l'elenco «Moduli dell'HUB che lo applicano».",
                "Con «Si compila nell'HUB» la scheda del modello mostra il pulsante «Compila nell'HUB · nome del modulo».",
                "Le etichette sulle pagine dei moduli mostrano solo i documenti aperti a tutti.",
                "Nella panoramica di un KICK-OFF il riquadro «Piano qualità e procedure» mostra il piano qualità del cliente della commessa (cartella del cliente nello scaffale Piani Qualità) e le procedure collegate al KICK-OFF.",
            ]),
        ],
    },
    {
        "id": "segnalazioni-riletture",
        "titolo": "Segnalazioni e riletture (per chi gestisce)",
        "blocchi": [
            ("ul", [
                "Ogni nuova segnalazione arriva come notifica nel portale a chi gestisce CN-SGI (i destinatari del riepilogo settimanale in «Impostazioni» e chi ha già gestito segnalazioni). Il numero accanto a «Segnalazioni» dice quante sono aperte o prese in carico.",
                "In «Segnalazioni» porti ogni proposta a «Presa in carico», «Recepita» (indicando la revisione) o «Respinta», con una risposta: chi l'ha scritta riceve una notifica.",
                "Le segnalazioni recepite compaiono nella scheda del documento, in «Cosa cambia» della revisione che le ha accolte.",
                "Quando esce una nuova revisione, in «Cosa cambia» c'è «Chiedi la rilettura»: crea e pubblica la richiesta di presa visione della revisione in vigore per chi aveva quella delle revisioni precedenti, con la scadenza scelta (14 giorni di partenza), e avvisa le persone.",
            ]),
        ],
    },
    {
        "id": "modifiche",
        "titolo": "Modifiche ai documenti",
        "blocchi": [
            ("p", "«Modifiche» segue una nuova revisione (o un documento nuovo) dalla richiesta all'emissione: "
                  "redazione → verifica → approvazione → emissione. Il testo si scrive in Word come sempre; nell'HUB restano bozze, firme e registro. "
                  "La voce compare a chi gestisce CN-SGI e a chi ha una modifica in mano, con il numero di quelle che aspettano te. "
                  "Le stesse modifiche sono in «Le mie letture», riquadro «Documenti da lavorare»."),
            ("passi", [
                "Chi redige apre la modifica, carica la bozza (Word .docx, Excel .xlsx o PDF, fino a 25 MB) con due righe su cosa cambia e clicca «Invia in verifica». Si possono caricare più bozze: vale l'ultima.",
                "Chi verifica scarica la bozza e guarda «Cosa cambia»: i paragrafi cambiati rispetto alla revisione in vigore, dal testo dei due file. Poi «Verificata, passa in approvazione» oppure «Rimanda a chi redige» con una nota (obbligatoria).",
                "Chi approva spunta «Approvo la bozza …» e clicca «Approva»: nome, ruolo, data, ora e impronta della bozza restano nel registro. Anche chi approva può rimandare a chi redige.",
                "Chi gestisce salva il PDF nella cartella SGI e sposta la revisione precedente in SUPERATO. Al controllo orario l'HUB riconosce la nuova revisione e porta la modifica a «Emessa». Se la revisione è già arrivata, «Segna come emessa» la chiude subito.",
            ]),
            ("ul", [
                "A ogni passaggio chi deve agire riceve una notifica nel portale. Una modifica ferma da 5 giorni o più riceve un sollecito ogni mattina, al massimo uno ogni 5 giorni.",
                "All'emissione le segnalazioni collegate diventano «Recepita» nella nuova revisione (chi le ha scritte riceve l'avviso). Se l'opzione è spuntata, parte anche la rilettura per chi aveva letto le revisioni precedenti.",
                "Il registro si può solo aggiungere: nessuna pagina modifica o cancella un passaggio. La modifica, le bozze e il registro li vedono solo chi ha un ruolo nella modifica e chi gestisce CN-SGI.",
                "Nella scheda del documento, «Nuova revisione in preparazione» avvisa chi legge che è in arrivo una revisione.",
            ]),
        ],
    },
    {
        "id": "modifiche-firme",
        "titolo": "Aprire una modifica e chi firma cosa (per chi gestisce)",
        "blocchi": [
            ("ul", [
                "Una modifica si apre da «Modifiche» → «Nuova modifica», dalla scheda del documento («Per chi gestisce» → «Avvia una modifica»), da una segnalazione («Avvia una modifica del documento») o da «Da rivedere». «Documento nuovo» propone i prossimi codici liberi.",
                "Servono cosa si modifica, perché e chi redige. Origine e riferimento (NC, audit, RFC MOD.172, riesame, norma) restano come evidenza. Le segnalazioni spuntate passano a «Presa in carico».",
                "«Chi firma cosa» fissa, per tipo di documento (Manuali, MT, MTSI, MOD, Piani qualità, Altri), chi redige, verifica e approva di solito: sono le persone proposte all'apertura. «Altri» vale anche per i campi lasciati vuoti negli altri tipi.",
                "Nella modifica, «Chi firma» cambia le persone; chi entra nel passaggio in corso riceve l'avviso. Se chi redige verifica o approva anche, la pagina lo segnala: per la norma la verifica dovrebbe farla un'altra persona.",
                "«Annulla la modifica» chiede il motivo e resta nel registro.",
            ]),
        ],
    },
    {
        "id": "da-rivedere",
        "titolo": "Da rivedere (per chi gestisce)",
        "blocchi": [
            ("ul", [
                "«Non revisionati da più di 3 anni»: i documenti con la revisione in vigore più vecchia di tre anni, dal più vecchio.",
                "«Citati ma non presenti»: i codici scritti nel testo dei documenti in vigore che nella cartella SGI non esistono (documento mancante o refuso), con i documenti che li citano.",
            ]),
        ],
    },
    {
        "id": "audit",
        "titolo": "Pacchetto audit",
        "blocchi": [
            ("passi", [
                "Apri uno scaffale e clicca «Pacchetto audit» in alto a destra.",
                "Leggi l'elenco: sezione, codice, titolo, revisione e data, processi, prese visione confermate su quelle chieste.",
                "Clicca «Scarica Excel» per avere le stesse colonne in un file.",
            ]),
            ("p", "In testa ci sono il numero di documenti in vigore, quanti sono stati revisionati negli ultimi 12 mesi e, se lo scaffale ha la certificazione collegata, scadenza, prossima sorveglianza ed ente. "
                  "Il pacchetto lo vedono chi gestisce CN-SGI e i ruoli «vede tutto»."),
        ],
    },
    {
        "id": "aggiornamento",
        "titolo": "Come resta aggiornata",
        "blocchi": [
            ("ul", [
                "Ogni 15 minuti il portale guarda solo nomi, dimensioni e date dei file della cartella SGI: se qualcosa è cambiato importa documenti nuovi, revisioni nuove (anche dei documenti in presa visione) e file spostati o rinominati.",
                "Entrano anche i file con nomi liberi (piani qualità, manuali, documenti senza codice SGI). Restano fuori solo i file con lo stesso codice in più punti della cartella e quelli con una revisione nel nome non più recente di quella in libreria.",
                "Di notte (03:00) fa la lettura completa: testo dei PDF nuovi, collegamenti, indice.",
                "In alto a destra «Controllata alle …» dice l'ora dell'ultimo controllo; il pallino diventa giallo se il controllo non gira da più di 45 minuti.",
                "In «Impostazioni», riquadro «Sincronizzazione con la cartella SGI», chi gestisce vede cosa va e cosa no (interruttore acceso, cartella raggiungibile, controllo programmato, qcluster in funzione, ultimo controllo) e l'elenco «File non sincronizzati» con il motivo.",
            ]),
            ("p", "«Richieste di presa visione» (prima «Refresh procedure») resta l'azione per chiedere la lettura di uno o più documenti a persone o reparti, con promemoria e report."),
        ],
    },
]

_PER_ID = {s["id"]: s for s in SEZIONI}


def con_guida(view_func):
    """La view risponde con la guida a ``?guida=1`` (pagina) o ``?guida=pdf``."""

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
        response["Content-Disposition"] = 'attachment; filename="Guida_CN-SGI.pdf"'
        return response
    return render(request, "procedure_refresh/libreria/guida.html", {
        "doc_titolo": DOC_TITOLO,
        "sezioni": SEZIONI,
        "torna_url": request.path,
    })
