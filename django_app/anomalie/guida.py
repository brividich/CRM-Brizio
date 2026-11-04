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
                "segnalazione al cliente, note. Il CAR è in copia. Con il sistema «Ruoli e permessi» acceso chi ha "
                "aperto l'anomalia non ne decide note, segnalazione al cliente, RDC e chiusura: la decisione la "
                "prende un'altra persona (chi rileva non decide, EN 9100 §8.7).",
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
                ("Capo del team", "con «modificare» sul team (ruolo Caporeparto) vede e decide sugli OP del suo team: "
                 "quelli dove lui o un membro del team è capocommessa o CAR e quelli con anomalie aperte dal team."),
                ("Chi gestisce tutti gli OP", "decide su qualunque OP (in «Ruoli e permessi»: anomalie, modificare = "
                 "«Tutti»; di serie solo il ruolo Qualità)."),
                ("Amministratori del modulo", "configurano liste, promemoria, accessi e vedono i log."),
            ]),
            ("p", "Con il sistema «Ruoli e permessi» acceso ognuno vede solo gli OP che lo riguardano: quelli di cui è "
                  "capocommessa o CAR, quelli dove ha aperto un'anomalia e quelli che l'ambito di «vedere» gli concede "
                  "(team o tutti). Ingegneria e Controllo qualità aprono segnalazioni su qualsiasi OP ma modificano "
                  "solo i propri. Chi può solo consultare trova i campi della decisione disattivati, con l'avviso "
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
                "«Continua». L'OP si crea solo quando salvi il primo blocco di anomalie (in alto c'è «Nuovo · si crea "
                "al primo salvataggio»); quello che scrivi prima si salva comunque in bozza. Se l'OP esiste già la "
                "pagina lo dice: sceglilo dall'elenco.",
                "Scrivi la «Fase del controllo», per esempio accettazione materiale, lavorazione o collaudo finale. "
                "Vale per tutti i blocchi e si può cambiare durante il controllo con «Cambia».",
                "Sotto «Mail al capocommessa: una sola, a fine controllo» vedi a chi andrà la mail: «A» il capocommessa "
                "(il CAR per i collaudi di benestare), «In copia» l'altro.",
                "Per mettere in copia un altro capocommessa premi «+ Aggiungi altro capocommessa» e sceglilo dall'elenco; "
                "per qualunque altro collega «+ Aggiungi persona» e cercalo per nome, cognome o email. La × lo toglie.",
                "Nelle righe «Riepilogo» e «Se RDC» vedi anche chi riceve il riepilogo senza link, dalle liste di "
                "Configurazione → Notifiche («Riepilogo modifiche» sempre, «RDC / segnalazione cliente» solo se "
                "un'anomalia è da aprire RDC o da segnalare al cliente). Lo stesso riquadro torna nel «Riepilogo del "
                "controllo», dove puoi ancora aggiungere o togliere persone prima di «Conferma e termina».",
                "Premi «Inizia controllo».",
            ]),
            ("p", "Si possono aggiungere solo persone dell'anagrafica con un'email di notifica (al massimo 10): ricevono la "
                  "stessa mail con il link di decisione, quindi non si accettano indirizzi esterni. I destinatari si "
                  "cambiano anche durante il controllo, dalla barra in alto, e valgono per le mail successive."),
            ("p", "Se sull'OP c'è già un controllo non terminato (tuo o di un collega), compare l'elenco dei controlli "
                  "aperti con fase, ora e blocchi salvati: con «Riprendi» continui il tuo, con «Prendi in carico» "
                  "prosegui quello del collega (che riceve un avviso). Per un controllo nuovo scrivi comunque la fase. "
                  "I controlli rimasti vuoti (nessun blocco salvato e nessuna bozza) si chiudono da soli dopo 24 ore."),
            ("def", [
                ("Quando parte la mail", "una sola volta, quando premi «Termina controllo»."),
                ("Promemoria (15 minuti)", "se 15 minuti dopo l'ultimo blocco salvato la mail non è ancora partita, "
                 "ricevi una notifica nel portale e una mail con il riepilogo salvato e il collegamento per riprendere il "
                 "controllo e inviarla. Un nuovo salvataggio fa ripartire il conteggio."),
                ("Invio automatico (1 ora)", "se non termini il controllo, 1 ora dopo l'ultimo blocco salvato la mail al "
                 "capocommessa parte da sola: nessuna anomalia resta senza comunicazione."),
            ]),
            ("p", "I due tempi sono quelli predefiniti: chi gestisce il modulo li cambia in Configurazione → Notifiche → "
                  "«Orari e soglie» («Controllo OP: promemoria dopo minuti» e «Controllo OP: invio automatico dopo minuti»)."),
            ("p", "Salvataggio automatico: mentre scrivi un blocco, seriali, stato superficie e descrizioni si salvano da "
                  "soli pochi secondi dopo ogni modifica (sotto il titolo del blocco compare «salvato in automatico alle …»). "
                  "Se chiudi la pagina o si spegne il PC, rientrando nell'OP con «Riprendi» ritrovi il blocco com'era. "
                  "Vale anche per un OP nuovo non ancora creato e per i blocchi copiati con «Clona» ancora da caricare. "
                  "Gli allegati non si salvano in automatico: dopo il ripristino vanno ricaricati."),
            ("p", "Bozza dimenticata: se un blocco resta scritto e non salvato per 15 minuti (lo stesso tempo del "
                  "promemoria) e non ci sono anomalie salvate da inviare, ricevi una notifica nel portale e una mail con "
                  "quello che avevi scritto (seriali, descrizioni, blocchi copiati ancora da caricare) e il link che "
                  "riapre il controllo dove eri rimasto, anche su un OP nuovo. Un promemoria per ogni pausa: se riprendi "
                  "a scrivere e ti fermi di nuovo, arriva di nuovo. La bozza non parte mai da sola: va salvata."),
            ("p", "Controlli del gruppo qualità: chi ha il ruolo «Controllo qualità» o «Qualità» vede, in cima ad "
                  "«Apertura segnalazione», il riquadro «Controlli in sospeso del gruppo qualità»: i controlli aperti "
                  "suoi e dei colleghi del gruppo con anomalie scritte da salvare, blocchi copiati da caricare o "
                  "anomalie non ancora comunicate (ultimi 14 giorni). Una segnalazione lunga iniziata a fine turno la "
                  "prosegue il collega del turno dopo o del giorno successivo."),
            ("passi", [
                "Nel riquadro premi «Apri» accanto al controllo del collega (oppure, entrando nell'OP, «Prendi in carico» "
                "in «Controlli ancora aperti su questo OP»).",
                "Compare «Controllo in carico a …» con fase, blocchi salvati e anomalie da salvare: premi «Prendi in "
                "carico e prosegui».",
                "Da qui il controllo è tuo: ritrovi il blocco in scrittura, salvi, ricevi i promemoria e premi «Termina "
                "controllo». Il collega riceve un avviso nel portale e il passaggio resta registrato (nel riquadro: "
                "«iniziato da …»).",
            ]),
            ("p", "Finché non lo prendi in carico il controllo del collega si guarda soltanto. Dopo il passaggio chi lo "
                  "aveva non può più modificarlo (gli compare «Il controllo è in carico a …»): così due persone non "
                  "scrivono sulla stessa bozza. Chi non ha questi ruoli vede solo i propri controlli."),
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
                "Scrivi «Dove sono i pezzi?» (es. area pezzi non conformi, reparto, carrello del collaudo): vale per "
                "tutti i pezzi del blocco e il capocommessa lo trova nella mail, nella pagina della mail e in Gestione "
                "anomalie.",
                "Descrivi l'anomalia: cosa hai rilevato, dove si trova sul pezzo, misura rilevata e tolleranza. Sopra la "
                "descrizione i pulsanti «Simboli» (Ø ± ° ⊥ ∥ ◎ ⌖ …) scrivono il simbolo dove si trova il cursore, anche "
                "nei campi delle misure; il controllo ortografico è quello del browser, in italiano.",
                "Se serve, in «Che cosa hai trovato?» scegli il caso (facoltativo): si aprono solo i campi di quel caso. "
                "«Misura fuori tolleranza»: una riga per misura con caratteristica, tolleranza (min/max, ± sul nominale "
                "o max per le tolleranze geometriche), rilevato e dove; il portale dice subito «Fuori tolleranza −0.015» "
                "e scrive la frase uniforme. «Difetto sul pezzo»: che difetto (bava, testimone di fusione, graffio…), "
                "dove e dimensioni. «Marcatura / documenti»: cosa c'è sul pezzo, cosa era atteso e i documenti coinvolti. "
                "Toccando di nuovo il caso scelto lo togli.",
                "Dal report ZEISS: nel riquadro «Misura fuori tolleranza» cattura le righe del protocollo (Win+Maiusc+S), "
                "clicca nel riquadro «Dal report ZEISS» e premi Ctrl+V (o «scegli l'immagine»). Il portale legge le righe e "
                "le propone con l'esito: quelle fuori tolleranza sono già spuntate, «da verificare» segnala un valore letto "
                "male. «Aggiungi N misure» le mette fra le misure, dove restano modificabili. L'immagine non viene allegata. "
                "Per una lettura migliore ingrandisci il PDF (almeno 125%) prima di catturare.",
                "«+ Riferimento» aggiunge disegno/revisione, sezione/vista e fase del ciclo/F.OP. Con un caso scelto "
                "compare anche il «Tipo di difetto» proposto dal portale (cambialo se non è giusto).",
                "«↓ Copia nella descrizione» porta le frasi delle misure nel testo; se lasci vuota la descrizione, al "
                "salvataggio si usano quelle frasi.",
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
                "Ogni seriale del blocco deve avere almeno un'anomalia. Se togli «Presente su tutti…» e qualche seriale "
                "non è scelto in nessuna anomalia, compare l'avviso giallo «S/N senza nessuna anomalia» e al salvataggio "
                "ti viene chiesto cosa fare: «Annulla, correggo» per sceglierli in un'anomalia, «Togli dal blocco e "
                "salva» se sono pezzi buoni, oppure «Salva comunque». Se salvi comunque, il blocco salvato e il "
                "riepilogo lo ricordano.",
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
                "Ordini: i filtri «Con aperte» (quello di partenza: gli OP con anomalie ancora aperte), «In carico a me» "
                "(OP con anomalie aperte di cui sei capocommessa o CAR; per i «Referenti RDC / segnalazione cliente» di "
                "Configurazione anche gli OP con anomalie aperte da aprire RDC o da segnalare al cliente, che possono "
                "anche modificare) e «Tutti» (anche gli OP con sole anomalie "
                "chiuse), con i conteggi; la ricerca trova OP, P/N, capocommessa e CAR. Il numero arancione su un OP "
                "indica le anomalie aperte ancora da decidere.",
                "Anomalie: raggruppate per blocco di seriali, con fase, operatore e data. «Da decidere» mostra solo quelle "
                "senza decisione; le chiuse sono raccolte in fondo in «Chiuse».",
                "«Clona» (sulla riga dell'OP, al passaggio del mouse) copia anomalie su un nuovo OP: spunta nella colonna "
                "Anomalie quelle da copiare (anche le chiuse; la casella sul blocco le prende tutte, «Tutte», «Aperte» e "
                "«Nessuna» fanno prima) e premi «Continua». Si apre «Nuova segnalazione» con il nuovo OP già compilato "
                "(P/N, capocommessa, CAR): scrivi il numero e premi «Continua», oppure scegli l'OP se esiste già; il nuovo "
                "OP si crea solo al primo «Salva blocco». Confermata la fase "
                "(proposta quella dell'OP di origine), i blocchi copiati si caricano uno alla volta con seriali, stato "
                "superficie e testi: cambia quello che serve e «Salva blocco» passa al successivo; «Salta questo blocco» "
                "lo scarta, «Carica ora» nell'elenco «Da copiare ancora» ne anticipa uno. Gli allegati dell'anomalia di "
                "origine si copiano solo spuntando «Copia anche … allegati». Con i testi si copiano anche misure, difetto, "
                "documenti e riferimento scritti dal controllore; «Dove sono i pezzi?» no (i pezzi del nuovo OP sono altri).",
                "Dettaglio: in alto OP, fase e se è un «Collaudo di benestare»; le frecce (o Alt+↑ / Alt+↓) "
                "passano all'anomalia precedente o successiva.",
                "Sotto il titolo, la fascia «Pezzi interessati» mostra i seriali dell'anomalia uno per chip (un "
                "intervallo appare come «LCN00060 → LCN00065») e il numero di pezzi. Se l'anomalia riguarda solo una "
                "parte del controllo, gli altri seriali compaiono barrati e sbiaditi, con «su N del controllo».",
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
                "In cima alla «Decisione del capocommessa» il percorso dell'anomalia mostra i passi con la loro data: "
                "Segnalata, Decisa (con la decisione presa), Risposta del cliente se è stata segnalata, Azione "
                "effettuata con «Azione di recupero», Chiusa; il passo arancione è quello in corso.",
                "Nella «Decisione del capocommessa» scegli i flag: «Aprire RDC», «Segnalare al cliente», «Segnala a "
                "terzista», «Segnala a CAR», «Pezzi precedenti al benestare». Spuntando «Segnalare al cliente» si spunta "
                "anche «Aprire RDC» (puoi toglierla); con «Aprire RDC» la segnalazione al cliente resta facoltativa.",
                "Con «Segnala a CAR» scegli in «A quale CAR?» uno o più capi reparto (di serie il CAR dell'OP; le altre "
                "scelte vengono dai capi reparto di Configurazione). Al salvataggio ognuno dei CAR appena scelti riceve "
                "una mail con l'anomalia, la decisione e il link, più una notifica nel portale; chi l'ha già ricevuta non "
                "la riceve di nuovo.",
                "Se servono, carica documenti o foto in «Allegati della decisione» (trascina o «sfoglia»): restano "
                "separati dagli allegati della segnalazione. Il riquadro «Dal controllore» mostra «Dove sono i pezzi?», "
                "le misure e i riferimenti scritti dal controllore (in sola lettura).",
                "Scegli l'«Avanzamento». Con «Aprire RDC» indica anche il «Numero RDC».",
                "Scrivi la «Risposta / note per il reparto»: decisione, istruzioni di rilavorazione, riferimenti.",
                "Premi «Salva» (Ctrl+S) oppure «Salva e prossima» per passare subito alla successiva.",
            ]),
            ("ul", [
                "L'anomalia si chiude da sola al salvataggio quando apri un RDC o scegli «Accetto lo stato» o «Apertura "
                "ORE/RIPI»: la pagina lo avvisa prima di salvare.",
                "Se scrivi qualcosa nelle note, l'avanzamento non può restare «In attesa»: scegline un altro, altrimenti "
                "il salvataggio si ferma con l'avviso (anche dal link della mail).",
                "Spuntando «Segnalare al cliente» l'avanzamento passa a «In attesa risposta cliente»: l'anomalia resta "
                "aperta e puoi scrivere la nota. Quando il cliente risponde scegli lo stato definitivo; togliendo la "
                "spunta torna lo stato di prima. Vale anche nella pagina del link della mail.",
                "Un'anomalia chiusa si riapre con «Riapri anomalia» nel riquadro verde in alto: il pulsante c'è per il "
                "capocommessa, il CAR, il controllore che l'ha segnalata e chi può modificare l'OP. Torna aperta e "
                "«In attesa»; la riapertura resta nella «Cronologia azioni».",
                "«Applica la stessa decisione anche a» copia la decisione (avanzamento, RDC, cliente, note) su altre "
                "anomalie aperte: «Solo questa» (di serie), «Stesso blocco di seriali», «Tutte le aperte dell'OP» o "
                "«Scelte a mano» (spunte raggruppate per S/N, con «Tutte» e «Nessuna»). Le anomalie già decise restano "
                "fuori, a meno di spuntare «Includi anche le … già decise». Al salvataggio un riepilogo mostra ogni "
                "anomalia con lo stato attuale e quello nuovo e quali si chiuderanno: «Conferma e salva» le salva tutte. "
                "Quelle in «Azione di recupero» senza azione effettuata ricevono la decisione ma restano aperte.",
                "Se cambi anomalia o OP senza salvare, la pagina chiede se salvare, scartare o restare.",
                "Puoi aggiungere allegati anche qui (trascina, sfoglia o Ctrl+V) e correggere il testo con «Modifica testo».",
                "«Cronologia azioni», in fondo al dettaglio, mostra chi ha fatto cosa sull'OP, dal portale e dalla mail.",
            ]),
            ("p", "Dopo il salvataggio parte da sola la mail di riepilogo al segnalante, al capocommessa, al CAR e alla "
                  "lista configurata, con tutte le decisioni prese sull'OP; le anomalie con RDC o da segnalare al cliente "
                  "sono evidenziate in cima. Parte quando sull'OP non salvi niente per 5 minuti (ogni salvataggio fa "
                  "ripartire l'attesa), così chi decide una alla volta manda una mail sola. In cima al dettaglio la "
                  "barra «N decisioni in attesa di invio · il riepilogo parte fra … min» lo ricorda: «Invia ora» lo "
                  "manda subito. Dal link della mail invece le decisioni partono alla conferma."),
        ],
    },
    {
        "id": "tempi",
        "titolo": "Tempi ed esiti: risposta del cliente e azione effettuata",
        "blocchi": [
            ("p", "Nel dettaglio dell'anomalia, sotto la decisione, il riquadro «Tempi ed esiti» mostra da quanto "
                  "tempo è aperta e quanto hanno richiesto le fasi, in ore lavorate: contano solo le ore dentro "
                  "l'orario di lavoro (di serie 08:00–18:00) dei giorni lavorativi; sabati, domeniche, festivi "
                  "nazionali, notti e ore fuori orario non contano. Da un giorno in su si vedono anche i giorni "
                  "lavorativi (1 giorno = 10 ore con l'orario di serie), per esempio «24 h · 2,4 gg». Un tempo «in "
                  "corso» è ancora aperto; in rosso se ha superato l'obiettivo."),
            ("def", [
                ("Risposta del capocommessa", "dalla mail del controllo (o dalla creazione, se l'anomalia è nata fuori "
                 "da un controllo) alla prima decisione."),
                ("Attesa del cliente", "da quando l'anomalia è «In attesa risposta cliente» a quando registri la "
                 "risposta o cambi lo stato."),
                ("Esecuzione dell'azione", "dalla decisione «Azione di recupero» all'azione effettuata."),
                ("Risoluzione", "dalla creazione alla chiusura (dopo una riapertura conta l'ultima chiusura)."),
            ]),
            ("passi", [
                "Risposta del cliente: quando l'anomalia è segnalata al cliente compare «Risposta del cliente». Scrivi "
                "cosa ha risposto, allega la mail (.msg o .eml, anche trascinandola da Outlook), foto o PDF e premi "
                "«Registra risposta». Poi scegli lo stato definitivo nella decisione.",
                "Azione effettuata: con la decisione «Azione di recupero» il riquadro è già aperto; per le altre "
                "anomalie aperte usa «+ Registra un'azione effettuata». Scegli l'azione (Rilavorato, Riparato, "
                "Scartato, Reso al fornitore, Accettato in deroga), scrivi le note, allega foto o documenti.",
                "Lascia «Chiudi l'anomalia» spuntato per chiuderla con l'azione. Dopo una rilavorazione o riparazione "
                "per chiudere serve anche «Pezzo riverificato conforme».",
                "Premi «Registra e chiudi» (o «Registra azione» se non la chiudi).",
            ]),
            ("ul", [
                "Se la prima decisione è stata «Azione di recupero», l'anomalia non si chiude dalla decisione (né dal "
                "link della mail) finché non registri l'azione effettuata; aprire un RDC resta possibile.",
                "Registrano risposta e azione il capocommessa, il CAR, il controllore che ha segnalato e chi può "
                "modificare l'OP.",
                "Gli allegati finiscono anche tra gli allegati dell'anomalia; mail e testi si scaricano, non si aprono "
                "nel browser.",
                "Risposte e azioni compaiono nella «Cronologia azioni».",
            ]),
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
                "e scrivi la risposta. «Segnalare a cliente?» spunta anche «Aprire RDC?» (si può togliere). «Chiudere? "
                "(automatico)» si calcola da solo. Terzista, CAR, dove sono i pezzi e allegati della decisione si "
                "indicano in Gestione anomalie.",
                "Per dare la stessa decisione ad altre anomalie scegli in «Applica la stessa decisione anche a» lo stesso "
                "blocco, tutte le aperte della pagina o quelle scelte a mano, poi «Salva»: un riepilogo le mostra tutte "
                "prima di confermare; avanzamento, RDC, cliente e note vengono copiati, come in Gestione anomalie.",
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
                ("Riepilogo dopo una decisione", "al segnalante, al capocommessa, al CAR e alla lista configurata, dopo 5 "
                 "minuti senza salvataggi sull'OP (configurabile) oppure subito con «Invia ora». RDC e segnalazioni al "
                 "cliente vanno anche al destinatario dedicato."),
                ("Decisioni all'operatore", "chi ha segnalato riceve una mail con la decisione e una notifica nel portale "
                 "che apre l'OP."),
                ("Promemoria", "a capocommessa e CAR, nella dashboard, per gli OP con anomalie «In attesa»; si chiudono da "
                 "soli quando l'OP è stato gestito."),
                ("Resoconto giornaliero", "nei giorni lavorativi, se attivato dagli amministratori."),
            ]),
            ("p", "La mail del controllo e il riepilogo hanno il pulsante «Apri nel portale» («Apri l'OP nel portale» "
                  "nel riepilogo): apre l'OP direttamente in Gestione anomalie, senza la pagina pubblica del link. Dai PC "
                  "aziendali entri in automatico con l'utente Windows; da telefono o fuori rete si apre il login e, dopo "
                  "l'accesso, arrivi comunque all'OP. Il pulsante non contiene credenziali: inoltrare la mail non dà "
                  "accesso a nessuno."),
            ("p", "Le mail inviate dal modulo sono registrate e si possono rispedire dalla configurazione (Log attività). "
                  "Compaiono anche in Automazioni → «Mail inviate» (tipo «Anomalie · …», richiesta «OP #…»), insieme alle "
                  "altre mail del portale."),
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
                "«Segna come Part 145» (in alto, per chi può modificare la NC aperta) indica che la NC riguarda un "
                "componente lavorato per l'organizzazione di manutenzione (MT CN 70 §6.13): la NC compare nel Dossier "
                "PART 145 tra le situazioni da sistemare, da comunicare all'organizzazione di manutenzione. Un secondo "
                "clic la toglie; la scelta resta nello storico della NC.",
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
                "Leggi i KPI in alto e le tabelle per avanzamento, per mese, per difetto, origine e decisione, e i top OP. "
                "Numeri, tabelle e ricerca contano solo le anomalie degli OP che vedi nell'elenco: con visibilità "
                "«assegnati» quelli in cui sei capocommessa o CAR, con «proprie anomalie» quelli su cui ne hai aperta una.",
                "In «Ricerca dettaglio» scorri le anomalie (25 per pagina) e scarica tutto con «Esporta CSV»: l'export "
                "rispetta i filtri ed è registrato.",
                "«Tempi di risposta e risoluzione»: mediana e media dei tempi conclusi, quanti sono ancora in corso, "
                "la percentuale entro l'obiettivo e le anomalie aperte oltre l'obiettivo, più le mediane per "
                "capocommessa. Tutto in ore lavorate (con i giorni lavorativi accanto) e con gli stessi filtri "
                "della pagina.",
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
                 "destinatari), composizione di capicommessa e CAR dai ruoli operativi dell'Anagrafica (solo assegnazioni in corso e "
                 "dipendenti attivi: chi ha cambiato ruolo o ha lasciato l'azienda non compare)."),
                ("Notifiche", "tutte le mail del modulo in un posto: quando partono, chi le riceve, se sono attive "
                 "e l'ultimo invio. Qui si cambiano le liste di destinatari fissi (riepilogo modifiche, RDC / "
                 "segnalazione cliente, supervisori), l'indirizzo della mail «nuova anomalia fuori da un controllo», "
                 "gli interruttori e gli orari. È la stessa vista di Automazioni → Notifiche di sistema: quello che "
                 "cambi in una pagina lo trovi già cambiato nell'altra. In «Orari e soglie» ci sono anche «Riepilogo "
                 "decisioni: invio dopo minuti di pausa» (di serie 5) e gli "
                 "obiettivi dei tempi: «Tempi: obiettivo prima decisione» (di serie 2 giorni lavorativi) e «Tempi: "
                 "obiettivo chiusura» (di serie 10), più l'orario di lavoro con cui si contano le ore: «Tempi: "
                 "orario di lavoro, dalle ore» (di serie 8) e «alle ore» (di serie 18)."),
                ("Campi del blocco del controllore", "in cima alla scheda Configurazione: per ogni parte nuova di "
                 "«Apertura segnalazione» («Dove sono i pezzi?», simboli, «Che cosa hai trovato?» e i tre casi, riquadro "
                 "«Dal report ZEISS», riferimento, tipo di difetto, «Copia nella descrizione») scegli «Visibile: Sempre», "
                 "«Mai» o «Solo se…». In cima, «Chi fa cosa: gruppi di controllori» (di serie «Controllo CMM» e «Controllo "
                 "visivo», se ne aggiungono altri) mette ogni controllore nel suo gruppo. Con «Solo se…» compili una o più "
                 "condizioni: gruppi di controllori, persone, ruoli operativi, parole "
                 "contenute nella fase del controllo (es. CMM), tipo di difetto dell'anomalia (scelto o proposto). Devono "
                 "valere tutte quelle compilate; dentro ognuna basta una voce. A destra l'«Anteprima dal vivo» mostra la scheda "
                 "come la vedrebbe un controllore («Vedi come»: persona, fase del controllo, tipo di difetto) mentre cambi "
                 "le regole, anche prima di salvarle; passando su una regola si evidenzia la sua parte e sotto c'è "
                 "l'elenco delle parti nascoste. «Salva campi» vale subito: il controllore "
                 "ricarica la pagina. Nascondere una parte non cancella i dati già inseriti."),
                ("Qualità", "catalogo dei tipi difetto e chi può chiudere le non conformità."),
                ("Permessi", "ruoli operativi (sola lettura, dall'Anagrafica) e regole di accesso per ruolo e per "
                 "singolo utente."),
                ("Record", "le ultime anomalie registrate, con ricerca."),
                ("Log attività", "audit del modulo e registro delle mail inviate, con «Reinvia»."),
            ]),
            ("nota", "Le automazioni di promemoria (difetto ricorrente, RDC senza numero, digest settimanale, OP completato) "
                     "sono spente di default: si accendono dalla scheda Notifiche."),
        ],
    },
    {
        "id": "faq",
        "titolo": "Domande frequenti",
        "blocchi": [
            ("def", [
                ("Non trovo l'OP.", "Cercalo per P/N o capocommessa. Se non esiste, crealo con «+ Nuovo OP» in Apertura "
                 "Segnalazione: compare negli elenchi dopo che hai salvato il primo blocco."),
                ("Ho salvato un blocco con un errore.", "«Modifica o aggiungi anomalie» lo riapre finché il capocommessa non "
                 "ha deciso."),
                ("Il capocommessa non ha ricevuto la mail.", "Controlla nel riepilogo del controllo a chi è andata; gli "
                 "amministratori la vedono e la possono reinviare da Configurazione → Log attività."),
                ("Vedo i campi della decisione grigi.", "Non sei capocommessa o CAR dell'OP e l'ambito di «modificare» "
                 "del tuo ruolo non lo copre: chiedilo a un amministratore."),
                ("Non vedo un OP.", "Vedi solo gli OP che ti riguardano (capocommessa, CAR, anomalie aperte da te o dal "
                 "tuo team). Controlla anche il filtro: «Con aperte» nasconde gli OP con sole anomalie chiuse, «Tutti» "
                 "li mostra."),
                ("Il link della mail dice che è scaduto o già usato.", "Apri l'OP dal portale in Gestione anomalie."),
                ("Non riesco a chiudere un'anomalia in «Azione di recupero».", "Va registrata prima l'azione "
                 "effettuata in «Tempi ed esiti»: con «Chiudi l'anomalia» la chiude direttamente."),
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
        if request.method == "GET" and (formato in ("1", "pdf") or formato in _guide_ruoli()):
            return guida_response(request, formato)
        return view_func(request, *args, **kwargs)

    return _wrapped


def _guide_ruoli() -> dict:
    from anomalie.guida_ruoli import GUIDE_RUOLI

    return GUIDE_RUOLI


def guida_response(request, formato: str) -> HttpResponse:
    """Guida completa (``?guida=1`` / ``?guida=pdf``) o guida rapida per ruolo
    (``?guida=controllore`` / ``?guida=pdf&per=controllore``, vedi ``guida_ruoli``)."""
    ruoli = _guide_ruoli()
    per = formato if formato in ruoli else str(request.GET.get("per") or "").strip().lower()
    guida_ruolo = ruoli.get(per)
    titolo = guida_ruolo["titolo"] if guida_ruolo else DOC_TITOLO
    sezioni = guida_ruolo["sezioni"] if guida_ruolo else SEZIONI
    if formato == "pdf":
        from core.guida_pdf import render_guida_pdf

        autore = (request.user.get_full_name() or request.user.get_username() or "").strip()
        pdf = render_guida_pdf(
            titolo=titolo,
            sottotitolo=guida_ruolo["sottotitolo"] if guida_ruolo else DOC_SOTTOTITOLO,
            sezioni=sezioni,
            generato_da=autore,
            generato_il=timezone.localdate().strftime("%d-%m-%Y"),
        )
        nome = guida_ruolo["file"] if guida_ruolo else "Guida_Gestione_Anomalie.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{nome}"'
        return response
    return render(
        request,
        "anomalie/pages/guida.html",
        {
            "page_title": titolo if guida_ruolo else f"Guida · {titolo}",
            "doc_titolo": titolo,
            "sezioni": sezioni,
            "torna_url": request.path,
            "guida_per": per if guida_ruolo else "",
            "guide_ruoli": [{"chiave": k, "etichetta": g["etichetta"]} for k, g in ruoli.items()],
        },
    )
