"""Guide rapide per ruolo del modulo Gestione anomalie: controllore e capocommessa/CAR.

Brevi e dirette (un compito = pochi passi numerati, con l'immagine della pagina),
da consegnare a chi usa il modulo. La guida completa resta ``anomalie/guida.py``.

Stessa forma delle sezioni di ``guida.py`` piu' il blocco ``("img", (percorso
static, didascalia))``: le immagini sono in ``anomalie/static/anomalie/guida/`` e
mostrano dati di esempio. Si aprono con ``?guida=<chiave>`` (pagina) e
``?guida=pdf&per=<chiave>`` (PDF) da qualunque pagina del modulo.
"""
from __future__ import annotations

_IMG = "anomalie/guida/"

SEZIONI_CONTROLLORE: list[dict] = [
    {
        "id": "c-apri",
        "titolo": "Aprire il controllo",
        "blocchi": [
            ("passi", [
                "Menu Anomalie › «Apertura Segnalazione».",
                "Cerca l'OP (numero, P/N, capocommessa o CAR) e cliccalo.",
                "OP che non c'è ancora: «+ Nuovo OP», compila P/N, anno e numero, capocommessa e CAR, poi «Continua». "
                "L'OP si crea solo quando salvi il primo blocco: se esci prima non resta niente.",
            ]),
            ("img", (_IMG + "c1_scegli_op.jpg", "Scelta dell'OP e inserimento di un nuovo OP")),
            ("passi", [
                "Scrivi la «Fase del controllo» (es. collaudo finale) e controlla a chi andrà la mail: «A» il "
                "capocommessa, «In copia» il CAR. «+ Aggiungi persona» mette in copia un collega.",
                "Premi «Inizia controllo».",
            ]),
            ("img", (_IMG + "c2_avvio.jpg", "Fase del controllo e destinatari della mail")),
            ("ul", [
                "Sull'OP c'è già un controllo non terminato? «Riprendi» continua il tuo, «Prendi in carico» prosegue "
                "quello di un collega. I controlli rimasti vuoti si chiudono da soli dopo 24 ore.",
            ]),
        ],
    },
    {
        "id": "c-blocco",
        "titolo": "Registrare le anomalie",
        "blocchi": [
            ("p", "Un blocco = i seriali con le stesse anomalie e lo stesso stato superficie."),
            ("passi", [
                "«Seriali»: scrivi un seriale o un intervallo (LCN00001-LCN00004) e premi Invio.",
                "Scegli lo «Stato superficie del blocco».",
                "Scrivi «Dove sono i pezzi?» (es. area pezzi non conformi): il capocommessa lo trova nella mail.",
                "Descrivi l'anomalia: cosa, dove, misura rilevata e tolleranza. I pulsanti «Simboli» (Ø ± ° ⊥ …) "
                "scrivono il simbolo dove si trova il cursore.",
                "Se serve, in «Che cosa hai trovato?» scegli il caso: «Misura fuori tolleranza», «Difetto sul pezzo» "
                "o «Marcatura / documenti». Si aprono solo i campi di quel caso; con le misure il portale dice subito "
                "se sono fuori tolleranza.",
                "Misure da un report ZEISS: cattura le righe del protocollo (Win+Maiusc+S, PDF ingrandito almeno al "
                "125%), clicca nel riquadro «Dal report ZEISS» e premi Ctrl+V. Controlla le righe proposte e premi "
                "«Aggiungi N misure»; «Testo letto dall'immagine» mostra cosa ha letto il portale.",
                "Foto: trascinale nel riquadro o incolla uno screenshot con Ctrl+V.",
                "Solo alcuni pezzi? Togli «Presente su tutti i … seriali del blocco» e tocca i seriali interessati.",
                "Altra anomalia sugli stessi pezzi: «+ Nuova anomalia su questi seriali».",
                "Premi «Salva blocco» e passa al blocco successivo.",
            ]),
            ("img", (_IMG + "c3_blocco.jpg", "Un blocco pronto da salvare, con «Dove sono i pezzi?» e una misura fuori tolleranza")),
            ("ul", [
                "Non vedi alcuni di questi campi? Chi gestisce il modulo sceglie in Configurazione quali compaiono e "
                "per chi (per esempio solo a chi fa il controllo CMM).",
                "Errore in un blocco salvato? «Modifica o aggiungi anomalie», finché il capocommessa non ha deciso.",
                "Mentre scrivi la pagina salva da sola, anche su un OP nuovo: se si chiude, rientra nell'OP e premi "
                "«Riprendi» (gli allegati vanno ricaricati).",
                "Blocco scritto e non salvato da 15 minuti: ti arriva una mail con quello che hai scritto e il link per "
                "riprendere. Riprendi e premi «Salva blocco».",
            ]),
        ],
    },
    {
        "id": "c-termina",
        "titolo": "Terminare e inviare",
        "blocchi": [
            ("passi", [
                "Premi «Termina controllo…».",
                "Controlla il «Riepilogo del controllo»: blocchi, anomalie, allegati e destinatari.",
                "Premi «Conferma e termina»: parte un'unica mail al capocommessa con il link per decidere.",
            ]),
            ("img", (_IMG + "c4_salvato.jpg", "Blocco salvato e «Termina controllo…»")),
            ("nota", "Se dimentichi di terminare: dopo 15 minuti dall'ultimo salvataggio ricevi un promemoria, dopo "
                     "un'ora la mail parte da sola."),
            ("p", "Quando il capocommessa decide ricevi una mail e una notifica nel portale con la decisione."),
        ],
    },
    {
        "id": "c-clona",
        "titolo": "Stesse anomalie su un altro OP («Clona»)",
        "blocchi": [
            ("passi", [
                "Gestione anomalie: passa con il mouse sull'OP di partenza e premi «Clona».",
                "Spunta le anomalie da copiare («Tutte», «Aperte», «Nessuna» fanno prima) e premi «Continua».",
                "Il nuovo OP arriva già compilato (P/N, capocommessa, CAR): scrivi il numero e «Continua».",
                "Conferma la fase e «Inizia controllo»: i blocchi copiati si caricano uno alla volta. Correggi seriali "
                "o testi e «Salva blocco»; «Salta questo blocco» lo scarta.",
            ]),
            ("p", "Si copiano anche misure e riferimenti; «Dove sono i pezzi?» no, perché i pezzi del nuovo OP sono altri."),
            ("img", (_IMG + "c5_clona.jpg", "Scelta delle anomalie da copiare")),
        ],
    },
    {
        "id": "c-correggi",
        "titolo": "Anomalia sbagliata: «Elimina» o «Taglia»",
        "blocchi": [
            ("passi", [
                "Nel controllo: «Modifica o aggiungi anomalie» sul blocco e apri l'anomalia. In Gestione anomalie: apri "
                "l'anomalia, card «Segnalazione».",
                "«Elimina» la toglie (chiede conferma). «✂ Taglia» la sposta: scrivi l'OP (lo stesso o un altro) e il S/N "
                "di destinazione, poi «Sposta qui».",
            ]),
            ("p", "Valgono solo per le anomalie che hai inserito tu e si può solo finché nessuno ci ha lavorato: niente decisione del capocommessa, niente presa in carico dal link della mail, niente risposte del cliente o azioni registrate. Su un altro OP l'anomalia esce dal "
                  "tuo controllo e il capocommessa di quell'OP la riceve nel riepilogo delle modifiche."),
        ],
    },
    {
        "id": "c-azione",
        "titolo": "Registrare l'azione effettuata",
        "blocchi": [
            ("p", "Quando il pezzo è stato rilavorato, riparato o scartato lo registri sull'anomalia: serve a chiuderla "
                  "e a calcolare i tempi."),
            ("passi", [
                "Gestione anomalie › apri l'anomalia › riquadro «Tempi ed esiti».",
                "Scegli l'«Azione effettuata» e scrivi cosa è stato fatto.",
                "Allega foto o documenti (trascina, sfoglia o Ctrl+V).",
                "Rilavorato o riparato: spunta «Pezzo riverificato conforme».",
                "Premi «Registra e chiudi».",
            ]),
            ("img", (_IMG + "e1_azione.jpg", "Azione effettuata con riverifica e chiusura")),
        ],
    },
    {
        "id": "c-riapri",
        "titolo": "Riaprire un'anomalia chiusa",
        "blocchi": [
            ("p", "Hai segnalato tu l'anomalia? In Gestione anomalie aprila e premi «Riapri anomalia» nel riquadro "
                  "verde: torna aperta e «In attesa», e il capocommessa la ritrova da decidere."),
        ],
    },
]

SEZIONI_CAPOCOMMESSA: list[dict] = [
    {
        "id": "k-trova",
        "titolo": "Trovare le anomalie da decidere",
        "blocchi": [
            ("ul", [
                "Dalla mail del controllo: «Apri nel portale» apre l'OP in Gestione anomalie (dai PC aziendali senza "
                "login).",
                "Dal portale: Menu Anomalie › «Segnalazioni in Carico», oppure Gestione anomalie con il filtro «In "
                "carico a me» (gli OP di cui sei capocommessa o CAR; se sei fra i «Referenti RDC / segnalazione "
                "cliente» di Configurazione, anche gli OP con anomalie da aprire RDC o da segnalare al cliente, che "
                "puoi modificare).",
            ]),
            ("passi", [
                "Clicca l'OP nella colonna di sinistra: il numero arancione indica le anomalie ancora da decidere.",
                "Nella colonna centrale «Da decidere» mostra solo quelle aperte: clicca l'anomalia.",
            ]),
            ("img", (_IMG + "k1_gestione.jpg", "Gestione anomalie: OP, anomalie e dettaglio")),
        ],
    },
    {
        "id": "k-decidi",
        "titolo": "Decidere",
        "blocchi": [
            ("passi", [
                "Leggi la «Segnalazione» e guarda le foto (un clic le ingrandisce). Il riquadro «Dal controllore» "
                "mostra dove sono i pezzi e le misure.",
                "Spunta se serve «Aprire RDC» (con il «Numero RDC»), «Segnalare al cliente» (spunta anche «Aprire "
                "RDC», che puoi togliere), «Segnala a terzista», «Pezzi precedenti al benestare».",
                "«Segnala a CAR»: in «A quale CAR?» spunta i capi reparto da avvisare (nessuno è scelto di serie). Al "
                "salvataggio solo loro ricevono la mail; il CAR dell'OP riceve comunque il riepilogo delle modifiche.",
                "Documenti o foto della decisione: «Allegati della decisione» (si caricano anche ad anomalia chiusa).",
                "Scegli l'«Avanzamento».",
                "Scrivi la «Risposta / note per il reparto».",
                "«Salva» (Ctrl+S) oppure «Salva e prossima».",
            ]),
            ("img", (_IMG + "k2_decisione.jpg", "Decisione del capocommessa: flag, «A quale CAR?», «Dal controllore» e allegati")),
            ("ul", [
                "Con una nota l'avanzamento non può restare «In attesa».",
                "L'anomalia si chiude da sola con «Accetto lo stato», «Apertura ORE/RIPI» o aprendo un RDC.",
                "Stessa decisione su più anomalie: in «Applica la stessa decisione anche a» scegli stesso blocco, tutte "
                "le aperte dell'OP o «Scelte a mano»; prima di salvare un riepilogo le mostra tutte. Le già decise "
                "restano fuori, salvo spuntarle.",
                "Le decisioni partono in un'unica mail quando sull'OP non salvi niente per 5 minuti; la barra in cima al "
                "dettaglio dice quante sono in attesa e «Invia ora» le manda subito.",
            ]),
        ],
    },
    {
        "id": "k-cliente",
        "titolo": "Segnalare al cliente",
        "blocchi": [
            ("passi", [
                "Spunta «Segnalare al cliente»: l'avanzamento passa a «In attesa risposta cliente».",
                "Scrivi nella nota cosa hai chiesto al cliente e salva: l'anomalia resta aperta.",
                "Quando hai avvisato il cliente spunta «Segnalato al cliente» (per il terzista «Segnalato al "
                "terzista»): si registra subito con data e nome e non manda nessuna mail; compare nel riepilogo "
                "successivo. Puoi allegare la comunicazione in «Allegati della decisione».",
                "Quando il cliente risponde, torna sull'anomalia in Gestione e scegli lo stato definitivo.",
            ]),
            ("img", (_IMG + "k3_cliente.jpg", "«Segnalare al cliente», «Segnalato al cliente» e stato «In attesa risposta cliente»")),
        ],
    },
    {
        "id": "k-esiti",
        "titolo": "Risposta del cliente e azione effettuata",
        "blocchi": [
            ("passi", [
                "Il cliente ha risposto: nel riquadro «Tempi ed esiti» scrivi la risposta, allega la mail (.msg o .eml) "
                "e premi «Registra risposta», poi scegli lo stato definitivo.",
                "Con «Azione di recupero» l'anomalia si chiude solo registrando l'azione effettuata (la registri tu, il "
                "CAR o il controllore): rilavorato o riparato chiede «Pezzo riverificato conforme».",
            ]),
            ("img", (_IMG + "e2_cliente.jpg", "Tempi in ore lavorate e risposta del cliente con la mail allegata")),
            ("p", "I tempi sono in ore lavorate (08:00–18:00 dei giorni lavorativi); in rosso quelli oltre l'obiettivo. In Statistiche trovi i tempi di "
                  "risposta e risoluzione per capocommessa."),
        ],
    },
    {
        "id": "k-mail",
        "titolo": "Decidere dal link della mail",
        "blocchi": [
            ("passi", [
                "Apri il link della mail (non chiede il login: non inoltrarlo).",
                "Espandi un'anomalia, scegli «Aprire RDC?», «Segnalare a cliente?», il «Nuovo avanzamento» e scrivi la "
                "risposta, poi «Salva».",
                "«Conferma e invia aggiornamenti», controlla il riepilogo e «Conferma e invia».",
            ]),
            ("p", "Il link vale una volta sola: per cambiare una decisione già inviata usa il portale."),
        ],
    },
    {
        "id": "k-riapri",
        "titolo": "Riaprire, report e controllo",
        "blocchi": [
            ("ul", [
                "Anomalia chiusa per errore: «Riapri anomalia» nel riquadro verde la riporta aperta e «In attesa».",
                "Menu «…» in alto a destra: «Report OP» e «Report OP in PDF».",
                "«Cronologia azioni», in fondo al dettaglio: chi ha fatto cosa sull'OP, dal portale e dalla mail.",
            ]),
            ("img", (_IMG + "k4_riapri.jpg", "Anomalia chiusa con «Riapri anomalia»")),
            ("nota", "Vedi e decidi gli OP di cui sei capocommessa o CAR (il caporeparto anche quelli del suo team). "
                     "Campi grigi con «Sola lettura»: l'OP non è tuo, chiedi a chi ne è incaricato."),
        ],
    },
]

GUIDE_RUOLI: dict[str, dict] = {
    "controllore": {
        "titolo": "Anomalie · Guida del controllore",
        "sottotitolo": "Registrare le anomalie di un controllo e inviarle al capocommessa",
        "file": "Guida_Anomalie_Controllore.pdf",
        "etichetta": "Guida del controllore",
        "sezioni": SEZIONI_CONTROLLORE,
    },
    "capocommessa": {
        "titolo": "Anomalie · Guida del capocommessa e del CAR",
        "sottotitolo": "Decidere sulle anomalie dei propri OP, dal portale o dalla mail",
        "file": "Guida_Anomalie_Capocommessa_CAR.pdf",
        "etichetta": "Guida del capocommessa / CAR",
        "sezioni": SEZIONI_CAPOCOMMESSA,
    },
}
