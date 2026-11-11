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
            ]),
            ("p", "Sotto ogni copertina di scaffale c'è la prossima sorveglianza della certificazione collegata: pallino giallo se mancano meno di 30 giorni."),
        ],
    },
    {
        "id": "ricerca",
        "titolo": "Cercare in tutte le procedure",
        "blocchi": [
            ("passi", [
                "Scrivi nella ricerca in alto (il tasto «/» ci porta il cursore) un codice, un titolo o una frase.",
                "In «Ricerca» scegli dove cercare: «Codice, titolo e testo», «Solo codice e titolo» o «Solo testo dei documenti».",
                "Spunta uno o più scaffali per restringere i risultati.",
                "Ogni risultato mostra il paragrafo e la pagina: clicca «§ … · pag. N ↗» per aprire il PDF a quella pagina.",
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
                "«Apri il PDF ↗» apre la revisione in vigore nel browser.",
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
                "Ogni ora il portale guarda solo nomi, dimensioni e date dei file della cartella SGI: se qualcosa è cambiato sincronizza subito.",
                "Di notte (03:00) fa la lettura completa: testo dei PDF nuovi, collegamenti, indice.",
                "In alto a destra «Controllata alle …» dice l'ora dell'ultimo controllo.",
                "Le due sincronizzazioni sono attive solo con l'interruttore della sincronizzazione automatica acceso in «Impostazioni».",
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
