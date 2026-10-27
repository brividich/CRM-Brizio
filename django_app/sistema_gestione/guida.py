"""Guida d'uso degli audit interni (MT CN 12) e del Registro OFI/NC (MOD.174).

Un solo contenuto per tre uscite: la pagina guida degli audit, la pagina guida del
Registro OFI (solo i capitoli del registro e della CAR) e il PDF di ciascuna (`?pdf=1`).
Testo semplice, niente HTML: il template lo mostra con l'autoescape e il PDF lo passa
da `escape()`.

Blocchi di una sezione: ("p", testo), ("ul", [voci]), ("nota", testo),
("def", [(termine, spiegazione)]). Le etichette citate sono quelle visibili nelle
pagine: se ne cambia una, va aggiornata anche qui. `PAGE_HELP` collega ogni rotta al
capitolo che la spiega (pulsante «Guida di questa pagina»).
"""
from __future__ import annotations


from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

# --- Parte generale -------------------------------------------------------------

_GENERALE = [
    {
        "id": "panoramica",
        "titolo": "A cosa serve e come è organizzato",
        "blocchi": [
            ("p", "La sezione Audit interni porta nel portale la procedura MT CN 12 «Audit Interni»: ogni processo del "
                  "Sistema di Gestione Integrato va verificato almeno una volta all'anno, per controllare conformità "
                  "legislativa, conformità alle norme (EN 9100, ISO 9001, ISO 45001, ISO 14001, ISO/IEC 27001, UNI/PdR 125) "
                  "e attuazione del sistema."),
            ("p", "Il percorso segue le cinque fasi della procedura, ognuna con la sua pagina:"),
            ("def", [
                ("1. Programmazione", "il programma annuale MOD.034 «Programmazione Verifiche Ispettive», redatto da MSM e "
                 "approvato dalla Direzione, aiutato da Priorità e proposte, Cicli triennali e Calendario."),
                ("2. Individuazione dell'auditor", "l'elenco Auditor con i requisiti del §6 della MT CN 12 e l'indipendenza "
                 "dal processo verificato."),
                ("3. Pianificazione", "il piano MOD.035A di ciascun audit: processi, norme e punti norma, team, persone, "
                 "agenda, approvazione Lead Auditor e Direzione, comunicazione agli auditati."),
                ("4. Esecuzione", "la checklist con una scheda «Compila verifica» per ogni domanda, evidenze e allegati, "
                 "utilizzabile anche da tablet."),
                ("5. Documentazione dei risultati", "il rapporto MOD.035B con firma dell'auditor, convalida del "
                 "responsabile dell'ente verificato e valutazione RDD."),
            ]),
            ("p", "Ogni OFI o NC rilevata diventa una voce del Registro OFI/NC MOD.174. Per le NC si apre la richiesta di "
                  "azione correttiva (CAR) secondo la MT CN 11 «Azioni Correttive», fino alla verifica di efficacia."),
            ("nota", "Ogni pagina ha in alto il collegamento «Guida di questa pagina», che apre direttamente il capitolo "
                     "che la spiega. La guida si scarica anche in PDF con «Scarica PDF»."),
        ],
    },
    {
        "id": "ruoli",
        "titolo": "Chi fa cosa",
        "blocchi": [
            ("p", "I ruoli della procedura e quello che fanno nel portale:"),
            ("def", [
                ("MSM (Qualità)", "redige e aggiorna il programma MOD.034, cura catalogo processi e auditor, pianifica gli "
                 "audit e ne conserva piani e rapporti."),
                ("Direzione / CEO", "approva il programma e il piano di audit, approva gli auditor esterni («Approva CEO»)."),
                ("RDD", "convalida il programma, approva le eventuali deroghe all'indipendenza, valuta il rapporto e chiude l'audit."),
                ("Lead Auditor e team", "approvano il piano come Lead Auditor, eseguono le verifiche, compilano e firmano il rapporto."),
                ("Responsabile dell'ente verificato", "conferma la data, fornisce le evidenze e convalida il rapporto."),
                ("Auditato / responsabile dell'azione", "vede i propri rilievi in «I miei rilievi» e compila la propria CAR."),
                ("RSGQ / Direzione sulla CAR", "approva analisi e azione, concede proroghe motivate e verifica l'efficacia."),
            ]),
            ("p", "I permessi si assegnano da Admin › ACL. Con la configurazione predefinita:"),
            ("def", [
                ("Audit: consulta", "vedere programmi, audit, catalogo, cruscotto ed evidenze. Predefinito: admin e qualità."),
                ("Audit: modifica", "creare programmi, processi, auditor e piani, comunicare e annullare. Predefinito: admin."),
                ("Audit: esegui", "approvare come Lead, avviare l'audit, compilare la checklist e il rapporto. Predefinito: admin."),
                ("Audit: approva", "approvazioni della Direzione, convalide, valutazione RDD, impostazioni. Predefinito: admin."),
                ("Audit: i miei rilievi", "vedere solo i propri rilievi e la propria CAR. Predefinito: tutti i ruoli."),
            ]),
            ("p", "Le regole di separazione sono controllate dal portale: la Direzione che approva il piano non può essere "
                  "il Lead Auditor, l'RDD che valuta il rapporto non può essere un auditor dell'audit, chi verifica "
                  "l'efficacia non può essere il responsabile dell'azione."),
        ],
    },
    {
        "id": "glossario",
        "titolo": "Parole e sigle",
        "blocchi": [
            ("def", [
                ("RAIS / RAI / STR", "numerazione degli audit per tipo: audit di sistema, audit mandatorio cliente, audit straordinario."),
                ("PR / RP / ST", "celle della griglia MOD.034: programmato, riprogrammato, straordinario."),
                ("Conforme", "requisito soddisfatto, con l'evidenza verificata."),
                ("Punto di forza", "pratica che va oltre il requisito, da citare nel rapporto."),
                ("Osservazione", "mancanza leggera che non comporta seri rischi (MT CN 12 §5.6): non richiede per forza una CAR."),
                ("OFI", "opportunità di miglioramento: osservazione, suggerimento o raccomandazione."),
                ("NC maggiore / minore", "non conformità con ripercussioni su prodotto, ambiente, sicurezza o politica aziendale; "
                 "richiede trattamento e, di norma, una CAR. Va classificata e documentata con un'evidenza allegata."),
                ("N/A", "requisito non applicabile, sempre con il motivo."),
                ("CAR", "Corrective Action Request (MOD.036): richiesta di azione correttiva della MT CN 11."),
                ("MOD.034 / MOD.035A / MOD.035B / MOD.174", "programma annuale, piano di audit, rapporto di audit interno, "
                 "registro OFI/NC."),
            ]),
        ],
    },
]

# --- Pagine degli audit ---------------------------------------------------------

_PAGINE_AUDIT = [
    {
        "id": "pagina-indice",
        "titolo": "Pagina «Audit interni»",
        "blocchi": [
            ("p", "È il punto di partenza. In alto i pulsanti verso le altre pagine: Priorita e proposte, Catalogo processi, "
                  "Auditor, Cicli triennali, Calendario, Cruscotto, I miei rilievi, Registro OFI (filtrato sui rilievi "
                  "degli audit), Guida e, secondo i permessi, Impostazioni, Nuovo programma e Nuovo audit. In cima c'è anche «Indicatori di processo - MT CN 13»."),
            ("ul", [
                "«Anno di riferimento» con «Mostra» cambia l'anno di tessere e tabelle.",
                "Le tessere riportano Audit programmati, Audit chiusi e Auditor attivi dell'anno.",
                "«Processi da verificare» elenca i processi mai auditati o oltre la frequenza raccomandata dal rischio, "
                "con il collegamento alle priorità.",
                "«Programmi annuali» elenca le revisioni del MOD.034 con stato e numero di righe; «Apri» porta al programma.",
                "«Audit» elenca gli audit con numero, data, tipo, processi, Lead Auditor e stato; il numero apre la scheda.",
            ]),
        ],
    },
    {
        "id": "pagina-catalogo",
        "titolo": "Pagina «Catalogo processi» e scheda processo",
        "blocchi": [
            ("p", "Una scheda per ogni processo del SGI, riusata da programma, piano e agenda senza riscriverla."),
            ("ul", [
                "«Cerca» trova codice, nome o ente; «Mostra» sceglie Attivi, Archiviati o Tutti; «Filtra» applica.",
                "La tabella riporta responsabile, ultimo audit chiuso e prossima verifica, calcolata dall'ultimo audit chiuso "
                "e dalla frequenza; «Da pianificare» segnala i processi senza storico o in scadenza.",
                "«Nuovo processo» crea una scheda: codice univoco, responsabile, scopo, ingressi, risultati, rischi, "
                "indicatori, procedure, punti norma per ciascuna norma, frequenza audit e «Motivo della revisione».",
            ]),
            ("p", "Nella scheda processo la testata riporta revisione, responsabile, ruolo owner, criticità, frequenza "
                  "audit ed enti; sotto, i contatori di mansioni collegate, domande attive, audit, OFI / NC aperte (rosso se "
                  "c'è una NC, cliccabile) e revisioni. Il resto è diviso in schede:"),
            ("ul", [
                "«Scheda»: scopo, ingressi, risultati attesi, rischi, indicatori, procedure, punti norma per ciascuna "
                "norma («non applicabile» se vuoti) e fonte documentale. «Revisiona scheda» crea una nuova revisione "
                "con autore e motivo.",
                "«Chi lo esegue» legge la Struttura organizzativa: chi ricopre oggi il ruolo owner, le mansioni "
                "lavorative collegate al processo con quanti operativi e quanti in lista («nessuno» in rosso se nessuno "
                "è operativo) e i nomi delle persone operative.",
                "«Checklist»: «Nuova domanda» aggiunge una domanda con norma, punti, criterio e suggerimento; "
                "«Proponi domande dalla scheda» le genera dai punti norma e le lascia in «bozza» finché non le apri con "
                "«Verifica»; quelle «attive» si cambiano con «Revisiona». Solo le domande attive vengono copiate nei nuovi piani.",
                "«Audit» elenca le verifiche del processo con data, lead auditor e stato.",
                "«OFI / NC» elenca le voci del Registro OFI collegate al processo, aperte prima: numero, tipo, fase, "
                "descrizione, responsabile («da indicare» se manca) e scadenza (in rosso se passata). «Nuova OFI / NC su "
                "questo processo» apre l'inserimento con processo, responsabile e norme già proposti; «Apri nel registro "
                "MOD.174» mostra le stesse voci nel registro.",
                "«Revisioni» conserva le versioni precedenti della scheda: aprendo una revisione si vedono i dati salvati.",
            ]),
            ("nota", "Un audit conserva la copia della scheda processo usata nel piano: le revisioni successive del catalogo "
                     "non cambiano gli audit già pianificati."),
        ],
    },
    {
        "id": "pagina-auditor",
        "titolo": "Pagina «Auditor»",
        "blocchi": [
            ("p", "L'elenco del personale che può condurre gli audit, con la qualifica secondo la MT CN 12 §6."),
            ("ul", [
                "Requisiti minimi della procedura: diploma di scuola media superiore, conoscenza delle norme e delle tecniche "
                "di audit, conoscenza del settore, almeno 4 audit interni svolti e almeno due anni di esperienza sui sistemi "
                "di gestione.",
                "La colonna «Audit svolti» è contata dal portale; «Qualifica» indica Qualificato oppure Non completo.",
                "«Nuovo auditor» e «Modifica» registrano requisiti, data di verifica, scadenza della qualifica e «Norme per cui "
                "è abilitato» (nessuna selezione = tutte le norme).",
                "Un auditor esterno (consulente) conduce audit solo dopo «Approva CEO», come prevede il §5.3 della procedura.",
            ]),
            ("p", "Il portale controlla l'indipendenza: chi è responsabile del processo o vi lavora non può verificarlo. "
                  "Se in Impostazioni la deroga è ammessa, va motivata nel piano e approvata dall'RDD."),
        ],
    },
    {
        "id": "pagina-priorita",
        "titolo": "Pagina «Priorità e proposte di audit»",
        "blocchi": [
            ("p", "Aiuta MSM a decidere la frequenza come chiede il §5.2 della MT CN 12: criticità, NC e OFI degli ultimi "
                  "24 mesi, rilievi degli enti esterni, requisiti cliente, esiti delle verifiche di efficacia e revisioni della scheda processo."),
            ("ul", [
                "Ogni processo riceve un punteggio fino a 100 (regola «priorita-v3») con le motivazioni in chiaro.",
                "I rilievi degli audit esterni degli ultimi 24 mesi pesano sul processo indicato nel rilievo (15 punti per "
                "NC, 5 per osservazione o OFI, al massimo 30): il campo «Processo / area» del rilievo deve riportare il "
                "codice o il nome del catalogo, che il modulo propone mentre scrivi.",
                "«Frequenza e ultimo audit» mostra la frequenza raccomandata (mai oltre 12 mesi), «Mai auditato» o "
                "«oltre la frequenza».",
                "Spunta i processi, scegli il «Programma in bozza» e premi «Aggiungi le proposte selezionate»: le righe "
                "già presenti restano invariate e le proposte fuori dall'anno del programma vengono saltate.",
            ]),
            ("nota", "Le proposte non approvano nulla: il programma resta in bozza finché non viene proposto e approvato."),
        ],
    },
    {
        "id": "pagina-programma",
        "titolo": "Programma annuale MOD.034",
        "blocchi": [
            ("p", "Si crea con «Nuovo programma» dalla pagina Audit interni e si apre dall'elenco «Programmi annuali»."),
            ("ul", [
                "«Copertura annuale - MT CN 12» in alto avvisa se un processo attivo non ha alcun mese pianificato "
                "(DA COMPLETARE) e se l'audit dell'anno è già chiuso.",
                "«Salva testata» registra i dati generali; «Aggiungi riga» inserisce un'area con enti e punti norma per "
                "9100, 45001, 14001, 27001, PdR 125 e altre normative.",
                "Nella «Griglia annuale» ogni mese si imposta a PR, RP o ST e si conferma con ✓. Da una cella senza audit "
                "«Pianifica» apre il nuovo audit già collegato; se l'audit esiste, compare il suo numero.",
                "Ricordarsi degli audit negli ambienti di lavoro (collaudo, reparti produttivi, magazzini) per illuminazione, "
                "temperatura, umidità, manutenzione e ordine, richiesti dal §5.4 della procedura.",
            ]),
            ("def", [
                ("Proponi", "invia il programma alla Direzione."),
                ("Approva Direzione / Respingi", "la Direzione approva, oppure lo riporta in bozza con un motivo obbligatorio. "
                 "Chi propone non può approvare."),
                ("Convalida RDD", "completa l'approvazione: il programma diventa Approvato."),
                ("Nuova revisione", "per date non rispettabili o audit aggiuntivi (§5.2): richiede il motivo e crea una nuova "
                 "revisione da riapprovare; la precedente resta archiviata."),
                ("PDF MOD.034 / Carica PDF firmato", "stampa nel formato del modulo e archivia la copia firmata a mano."),
            ]),
            ("p", "Dopo l'approvazione il programma va distribuito ai responsabili di processo, che così conoscono in anticipo "
                  "le date previste."),
        ],
    },
    {
        "id": "pagina-cicli",
        "titolo": "Pagine «Cicli di audit» e dettaglio ciclo",
        "blocchi": [
            ("p", "Un ciclo raggruppa i programmi del triennio di certificazione."),
            ("ul", [
                "«Nuovo ciclo» con nome, anni e note; «Crea il ciclo» lo registra.",
                "Il dettaglio mostra «Processi senza audit nel ciclo», «Clausole mai programmate» e il programma di ogni anno.",
                "«Copertura processo per processo» indica per ogni anno Eseguito o Programmato e le clausole del catalogo "
                "mai programmate: è l'evidenza da mostrare all'ente di certificazione.",
            ]),
        ],
    },
    {
        "id": "pagina-calendario",
        "titolo": "Pagina «Calendario audit»",
        "blocchi": [
            ("ul", [
                "Mostra un mese alla volta gli audit nelle loro date; i pulsanti con il nome del mese e «Oggi» spostano il calendario.",
                "Un clic sull'audit apre la scheda.",
                "«Da pianificare nel mese» elenca le celle del programma ancora senza audit, con «Pianifica».",
            ]),
        ],
    },
    {
        "id": "pagina-piano",
        "titolo": "Nuovo audit e modifica del piano MOD.035A",
        "blocchi": [
            ("p", "«Nuovo audit» (o «Pianifica» da una cella del programma) apre il piano in quattro passaggi. Il salvataggio "
                  "crea una bozza: prima delle firme il portale mostra esattamente cosa manca."),
            ("def", [
                ("1. Campo di audit", "programma e righe, tipo (sistema, mandatorio cliente, straordinario), processi scelti "
                 "dal catalogo e norme. «Adotta le revisioni attuali del catalogo» aggiorna le schede copiate nel piano. "
                 "«Perimetro Part 145» (Sì — audit di sistema / Sì — audit di prodotto) porta l'audit e i suoi rilievi "
                 "nel Dossier PART 145: l'anno ne chiede almeno uno di sistema e uno di prodotto (MT CN 70)."),
                ("2. Criteri e limiti", "punti norma, procedure e criteri (vuoti = quelli delle schede processo) ed esclusioni."),
                ("3. Team e indipendenza", "Lead Auditor e team. Se il sistema segnala un conflitto di imparzialità serve un "
                 "auditor indipendente oppure la motivazione della deroga, da far approvare all'RDD."),
                ("4. Date e metodo", "date, durata, sede e metodi: intervista, esame documenti, osservazione diretta, "
                 "verifica delle evidenze."),
            ]),
            ("p", "Il piano non limita la verifica: se durante l'audit servono altre persone o più tempo, si aggiungono "
                  "(§5.4 della procedura)."),
        ],
    },
    {
        "id": "pagina-audit",
        "titolo": "Scheda dell'audit",
        "blocchi": [
            ("p", "Raccoglie tutto l'audit. In alto: stato, tipo e data, i PDF MOD.035A e MOD.035B (anteprima con filigrana "
                  "«BOZZA - NON EMESSO» finché l'audit non è chiuso) e «Modifica piano» mentre è Pianificato."),
            ("ul", [
                "«Il prossimo passo» guida l'audit con i link 1. Piano, 2. Persone, 3. Agenda, 4. Verifiche, 5. Rapporto e "
                "firme e l'elenco puntuale di ciò che manca prima di approvare o firmare.",
                "«Processi inclusi e revisioni utilizzate» mostra le schede processo conservate nel piano.",
                "Le tessere contano Conformi, OFI, NC (maggiori e minori), Osservazioni, Punti di forza e N/A; «Rilievi in Excel» "
                "scarica i rilievi dell'audit.",
                "«4 · Persone coinvolte»: «Aggiungi persona» con funzione, email e ruolo; «Correggi» finché il piano è Pianificato. "
                "La colonna Conferma riporta la risposta all'invito Outlook. Sotto, «Proposte dalla struttura "
                "organizzativa» elenca chi ricopre il ruolo owner dei processi dell'audit (come Responsabile del "
                "processo) e chi è operativo sulle loro mansioni (come Auditato), con l'email di notifica: «Aggiungi» lo "
                "mette nel piano. Chi è già nel piano (stessa email o nome) non viene riproposto.",
                "«5 · Programma orario»: «Aggiungi voce» con data/ora, processo, attività e auditor.",
                "«6 · Approvazione piano»: prima «Approva come Lead Auditor», poi «Approva Direzione»; se c'è una deroga, "
                "«Approva la deroga (RDD)».",
            ]),
            ("p", "Comunicazione agli auditati e avvio:"),
            ("ul", [
                "«Comunica» invia il piano: con l'invito Outlook le conferme degli auditati si leggono con «Aggiorna conferme "
                "da Outlook», altrimenti parte un'email con l'allegato del calendario.",
                "Il portale richiede almeno 5 giorni lavorativi di preavviso (la MT CN 12 chiede almeno una settimana); "
                "un preavviso più breve richiede una motivazione che resta nella scheda come «Deroga preavviso».",
                "«Avvia audit» porta l'audit In corso e apre la compilazione della checklist.",
                "«Annulla l'audit» (con motivo) riporta la verifica da pianificare nel programma e cancella l'invito Outlook.",
            ]),
            ("p", "«Checklist e verifiche di processo»: il menu «Mostra» filtra Tutte le verifiche, Solo da completare o Solo "
                  "rilievi. Ogni domanda ha «Compila verifica» (o «Apri evidenze» in sola lettura). Con l'audit In corso, "
                  "«Domanda aggiuntiva» e «Aggiungi alla checklist» ampliano la lista di controllo, come ammette il §5.5."),
            ("nota", "Gli audit sul processo CND-PT sono presenziati dagli auditor del cliente e dal relativo RL3 (o dall'RL3 "
                     "di Costruzioni Novicrom): indicarli fra le persone coinvolte. Le NC si gestiscono comunque con la MT CN 11."),
        ],
    },
    {
        "id": "pagina-preparazione",
        "titolo": "Preparazione dell'audit",
        "blocchi": [
            ("p", "Dalla scheda audit, «Preparazione: precedenti audit, CAR cliente e documenti» registra ciò che il §5.5 della "
                  "MT CN 12 chiede prima della data di esecuzione."),
            ("def", [
                ("Audit precedenti", "riferimenti ed esame dei risultati precedenti nella stessa area, oppure assenza motivata."),
                ("CAR cliente", "CAR emesse dal cliente e loro stato, oppure assenza motivata."),
                ("Documenti e registrazioni", "cosa campionare, con revisioni e disponibilità."),
                ("Obiettivi e carenze", "obiettivi della verifica e carenze da approfondire."),
            ]),
            ("p", "La bozza AI facoltativa propone i testi da audit precedenti, CAR ed efficacia e KPI sotto target: si copia "
                  "nei campi vuoti e va sempre verificata. Il portale ricorda che il testo è partito da una bozza AI."),
        ],
    },
    {
        "id": "pagina-verifica",
        "titolo": "Compila verifica (esecuzione, anche da tablet)",
        "blocchi": [
            ("p", "Una domanda per pagina, con criterio e suggerimento. «← Precedente», «Successiva →» e «Prossima da "
                  "completare» spostano fra le verifiche; in alto «Verifica N di M»."),
            ("ul", [
                "Scegli l'esito con i pulsanti: Conforme, Punto di forza, Osservazione, OFI, NC, N/A.",
                "Registra l'evidenza oggettiva (interviste, documenti, osservazione delle attività), il campione, il documento "
                "con revisione e la data.",
                "Per N/A indica il motivo; per NC e OFI completa requisito atteso, scostamento, clausola, responsabile "
                "dell'azione e scadenza. Una NC va classificata maggiore o minore e richiede un'evidenza allegata.",
                "«Scatta foto» usa la fotocamera del tablet; «Scegli file (PDF, PNG, JPEG)» carica un documento. Gli allegati "
                "sono conservati in area privata con impronta SHA-256.",
                "La bozza si salva da sola e resta sul dispositivo finché il server non la conferma: se cade la rete, il "
                "salvataggio riprova quando torna. «Registra esito» conferma la verifica.",
            ]),
            ("p", "Registrando OFI o NC il portale crea una sola voce nel Registro OFI MOD.174 con fonte «Audit interno», norme, "
                  "clausola, responsabile e scadenza. Una NC maggiore entra con priorità Alta."),
        ],
    },
    {
        "id": "pagina-rapporto",
        "titolo": "Rapporto MOD.035B, firme e chiusura",
        "blocchi": [
            ("p", "Sezione «D–E · Rapporto e valutazioni» della scheda audit."),
            ("ul", [
                "«Precompila / aggiorna riepilogo» raccoglie i fatti registrati; giudizio conclusivo e punti di forza restano "
                "la valutazione dell'auditor. «Salva rapporto» registra.",
                "Per firmare servono checklist valutata, evidenze (anche per le conformità), motivazioni N/A, rilievi collegati "
                "e giudizio conclusivo: l'elenco «punti da completare prima della firma» li indica uno per uno.",
                "«Firma rapporto come auditor» blocca il rapporto. Prima della convalida l'auditor può usare «Riapri il rapporto».",
                "«Convalida responsabile ente»: la convalida del responsabile dell'ente verificato prevista dal §5.5 (anche "
                "il responsabile di processo con permesso di consultazione).",
                "«Valuta RDD e chiudi»: valutazione e CAR autorizzate. Con l'impostazione predefinita l'audit si chiude solo se "
                "ogni NC ha il piano d'azione approvato nella CAR.",
            ]),
            ("p", "Alla chiusura il MOD.035B viene emesso una sola volta e archiviato con impronta SHA-256 in «Versioni del "
                  "rapporto»: i download successivi consegnano quel file. «Apri una revisione formale» archivia il rapporto "
                  "e le firme e richiede nuove firme, con motivo."),
            ("p", "«Copie firmate a mano»: «Carica» archivia il PDF firmato del piano (dopo l'approvazione) e del rapporto "
                  "(dopo la chiusura). Il rapporto va distribuito al responsabile della funzione verificata e a MSM."),
        ],
    },
    {
        "id": "pagina-isms",
        "titolo": "Audit ISMS ISO/IEC 27001 (MOD.171 e MOD.168)",
        "blocchi": [
            ("p", "Per l'audit interno del sistema di gestione della sicurezza delle informazioni (MT CN 276) scegli nel "
                  "piano «Modulistica: Audit ISMS ISO/IEC 27001 (MOD.171 / MOD.168)». La norma ISO/IEC 27001 viene spuntata "
                  "da sola. Team, persone, programma orario, approvazioni, comunicazione, firme e chiusura sono gli stessi "
                  "degli altri audit interni; cambiano i moduli e quello che si compila."),
            ("ul", [
                "«Rapporto ISMS» (dalla scheda audit) apre la pagina di compilazione. In «MOD.171 · Elenco siti oggetto di "
                "audit» si indicano ID, campo d'applicazione, attività da remoto (S/N) e funzioni o processi: modificabile "
                "finché il piano è pianificato. L'agenda del piano diventa il «Piano di audit» del MOD.171.",
                "«MOD.168 · Attività, siti, modifiche e valutazioni»: date e durata in remoto (con la percentuale) o in "
                "campo, sito, campo d'applicazione, addetti e turni, le tre «Modifiche significative» (no / sì con "
                "specifica, più «Altro») e le tre valutazioni del team (azioni sulle NC minori precedenti, trattamento dei "
                "rilievi degli ultimi due audit, analisi dei commenti del precedente audit).",
                "«Efficacia del sistema di gestione»: 15 righe dei requisiti ISO/IEC 27001 del MOD.168 (4.3 … 10.1, obblighi "
                "di conformità, famiglie di controlli), ognuna con evidenze e rilievo.",
                "«Controlli ISO/IEC 27002:2022 · applicazione 0-4»: i 93 controlli per tema, con il livello della SoA "
                "approvata in vigore già inserito. Scala del MOD.165: 4 = pienamente applicato, 0 = non applicato o "
                "escluso. Se cambi il livello devi motivarlo nel commento; la riga mostra «Diverso dalla SoA». "
                "«Salva» registra la singola riga senza ricaricare la pagina.",
            ]),
            ("def", [
                ("NC", "Non conformità, maggiore o minore: crea una voce NC nel Registro OFI (MOD.174) con ISO 27001 e il "
                       "riferimento al requisito o al controllo. Prima della chiusura serve la CAR con piano azioni approvato."),
                ("AP", "Area di miglioramento: crea una voce OFI nel Registro OFI."),
                ("COM", "Commento: resta nel rapporto, non crea voci nel registro."),
            ]),
            ("p", "Un rilievo già registrato nel MOD.174 non cambia tipo dal rapporto: si prosegue nel registro. Se le azioni "
                  "sulle NC minori del precedente audit sono «non efficaci» il portale chiede di rilasciare una NC maggiore."),
            ("p", "Per firmare il rapporto servono: date dell'attività, risposte alle modifiche (con specifica se «sì»), le "
                  "tre valutazioni, evidenze su ogni requisito, il livello di tutti i 93 controlli e il giudizio conclusivo. "
                  "L'«Elenco azioni correttive» si compone dalle NC con azione, responsabile e scadenza presi dalla CAR o "
                  "dalla voce del registro. Alla chiusura il MOD.168 viene emesso e archiviato con impronta SHA-256."),
            ("p", "Dopo la chiusura, se dei livelli sono diversi dalla SoA, chi ha il permesso di modifica della SoA vede "
                  "«Apri una revisione della SoA con questi livelli»: nasce una revisione in bozza con i nuovi livelli e la "
                  "motivazione nella giustificazione, da verificare, proporre e far approvare dalla Direzione."),
        ],
    },
    {
        "id": "pagina-checklist-norme",
        "titolo": "Pagina «Checklist di audit per norma»",
        "blocchi": [
            ("p", "Da «Audit interni» › «Checklist per norma». Ogni norma ha le sue revisioni di checklist: quella "
                  "«Attiva» viene caricata all'avvio degli audit che hanno la norma spuntata nel piano (EN 9100, ISO 45001, "
                  "UNI/PdR 125). Più norme spuntate = più checklist nello stesso audit, ognuna con le sue sezioni."),
            ("ul", [
                "EN 9100: la checklist è il Folder B del MOD.035B, importata dagli amministratori.",
                "ISO 45001 e UNI/PdR 125: non c'è un modulo aziendale. «Crea la bozza di base» propone sezioni per punto "
                "norma o area, domande guida scritte per il portale e i riferimenti alle procedure MT CN. La bozza nasce "
                "«Non attiva»: va verificata da RSGI, adattata ai processi e poi attivata.",
                "Aprendo una revisione non attiva e mai usata si modificano sezioni (codice, titolo, criteri, ordine) e "
                "domande (punti norma, domanda guida, ordine, attiva), si aggiungono o rimuovono.",
                "«Attiva questa revisione» la mette in uso e spegne la precedente della stessa norma. «Disattiva» lascia la "
                "norma senza domande negli audit avviati da quel momento.",
                "Una revisione attiva o già usata in un audit non si modifica: «Apri una nuova revisione» ne crea una copia "
                "non attiva, con il motivo. Gli audit già avviati conservano le domande che hanno usato.",
            ]),
        ],
    },
    {
        "id": "pagina-efficacia",
        "titolo": "Verifica efficacia di un rilievo",
        "blocchi": [
            ("p", "Sotto ogni rilievo collegato al MOD.174, «Verifica efficacia» registra risultato (Efficace, Non efficace, "
                  "Da riverificare), metodo, evidenza, data ed eventuale prossima verifica."),
            ("ul", [
                "La verifica la fa una persona diversa dal responsabile dell'azione.",
                "«Storico verifiche di efficacia» conserva tutte le registrazioni.",
                "La chiusura della voce nel Registro OFI non equivale a efficacia verificata: per le NC con CAR l'efficacia si "
                "conferma nella CAR.",
            ]),
        ],
    },
    {
        "id": "pagina-car",
        "titolo": "Azione correttiva (CAR) MT CN 11",
        "blocchi": [
            ("p", "Si apre dalla scheda della voce MOD.174 («Azione correttiva MT CN 11…») o da «I miei rilievi». Riproduce "
                  "i campi del MOD.036 in quattro passaggi."),
            ("def", [
                ("1. Richiesta e responsabilità", "data della richiesta, responsabile, «CAR richiesta da cliente/ente» con il "
                 "riferimento all'approvazione esterna."),
                ("2. Analisi delle cause", "Root Cause Analysis con 5 perché, Ishikawa (6M) o documento esterno, e la causa radice."),
                ("3. Contenimento e azione correttiva", "azione di contenimento, azione correttiva con le modifiche alla "
                 "documentazione del sistema, data di valutazione."),
                ("4. Prove di attuazione ed efficacia", "evidenza di attuazione e metodo, campione e risultato della verifica."),
            ]),
            ("ul", [
                "«Scadenze e responsabilità» applica i tempi della MT CN 11: analisi entro 1 mese e chiusura entro 3 mesi dalla "
                "richiesta, con SCADUTA in evidenza.",
                "«Approva analisi e azione» (RSGQ/Direzione) richiede analisi, contenimento, azione e data. Se poi si cambia "
                "l'analisi, l'approvazione decade.",
                "«Approva proroga» sposta la scadenza con un motivo; la scadenza del MOD.174 si aggiorna e il sollecito riparte.",
                "«Conferma efficacia e chiudi CAR»: la verifica indipendente chiude la CAR e la voce del registro. Il "
                "responsabile dell'azione non può farla.",
                "Ogni giorno partono i solleciti al responsabile; oltre i giorni impostati (predefinito 15) c'è l'escalation a RSGI.",
            ]),
            ("nota", "Quando la CAR nasce da un cliente o dall'ente di certificazione, l'approvazione spetta a loro: indicarne "
                     "il riferimento. La loro verifica va preceduta da quella interna del RSGQ."),
        ],
    },
    {
        "id": "pagina-miei-rilievi",
        "titolo": "Pagina «I miei rilievi»",
        "blocchi": [
            ("ul", [
                "Mostra solo i rilievi degli audit in cui sei auditato, responsabile del processo o dell'azione, dopo la firma "
                "del rapporto da parte dell'auditor.",
                "Per ogni rilievo: audit, clausola, tipo, descrizione, scadenza e il numero MOD.174 con lo stato della CAR.",
                "«Gestisci l'azione correttiva» apre la tua CAR per compilare cause, contenimento, azione ed evidenze.",
                "«Rilievi degli enti esterni assegnati a te» elenca le voci MOD.174 nate da audit esterni di cui sei "
                "responsabile, con scadenza e fase.",
            ]),
        ],
    },
    {
        "id": "pagina-cruscotto",
        "titolo": "Pagina «Cruscotto audit interni»",
        "blocchi": [
            ("ul", [
                "Le tessere riportano Verifiche programmate, Eseguite, In ritardo (il parametro di controllo della MT CN 12: "
                "verifiche effettuate / programmate), NC maggiori e minori, OFI e osservazioni, giorni medi di chiusura CAR "
                "ed efficacia verificata.",
                "L'avanzamento si calcola solo sul MOD.034 approvato dell'anno.",
                "Tabelle: verifiche in ritardo, rilievi per processo, rilievi nel tempo, clausole con più rilievi, processi con "
                "rilievi ricorrenti (in almeno due audit negli ultimi 24 mesi).",
                "«Copertura delle clausole per norma» confronta le clausole richieste dal catalogo con quelle verificate "
                "negli audit chiusi; «clausole non verificate» le elenca.",
                "«Rilievi in Excel» scarica i rilievi dell'anno.",
                "«Audit esterni del …» conta i rilievi degli enti per classificazione, le NC degli enti ancora aperte e, "
                "per ogni audit esterno dell'anno, se il piano azioni è stato inviato.",
            ]),
        ],
    },
    {
        "id": "pagina-kpi",
        "titolo": "Indicatori di processo - MT CN 13",
        "blocchi": [
            ("p", "Registra le rilevazioni degli indicatori di processo in tre passaggi: indicatore e periodo, dati e calcolo, "
                  "confronto e decisioni. «Registra» le conserva; le rettifiche si fanno con una nuova rilevazione motivata."),
            ("p", "Gli indicatori sotto target compaiono nella preparazione degli audit. Nessuna CAR viene emessa automaticamente."),
        ],
    },
    {
        "id": "pagina-impostazioni",
        "titolo": "Impostazioni degli audit interni",
        "blocchi": [
            ("p", "Riservate a RSGI/Direzione (permesso di approvazione). Ogni modifica viene registrata nel log."),
            ("def", [
                ("Chiusura dell'audit solo con il piano azioni approvato per ogni NC", "attiva per impostazione predefinita."),
                ("Ammetti la deroga motivata all'indipendenza dell'auditor", "spenta per impostazione predefinita; se attiva, "
                 "la deroga va approvata dall'RDD."),
                ("Giorni di ritardo di una CAR prima dell'escalation a RSGI", "predefinito 15."),
                ("Email RSGI per escalation", "indirizzi separati da virgola."),
                ("Allegati del MOD.035B", "«Rilievi e azioni», preparazione MT CN 12 e indice delle evidenze con impronta SHA-256."),
            ]),
        ],
    },
    {
        "id": "pagina-esterni",
        "titolo": "Pagina «Certificazioni e audit esterni»",
        "blocchi": [
            ("p", "Dalla pagina degli audit, pulsante «Audit esterni e certificazioni». Raccoglie i certificati del sistema di "
                  "gestione e gli audit di enti di certificazione, clienti e autorità."),
            ("ul", [
                "Tessere: certificati in vigore, scaduti o in scadenza entro 90 giorni, sorveglianze entro 30 giorni, piani "
                "azioni da inviare all'ente entro 7 giorni.",
                "«Nuova certificazione»: norma (EN 9100, ISO 9001, 45001, 14001, 27001, PdR 125, Part 145 o «Altro» con "
                "descrizione), ente, numero, emissione, scadenza, prossimo audit di sorveglianza, campo di applicazione. "
                "Togli «Certificato in vigore» quando non vale più.",
                "Nella tabella «Registra audit» apre un nuovo audit di sorveglianza già legato al certificato.",
                "«Nuovo audit esterno»: tipo (certificazione iniziale, sorveglianza, rinnovo, cliente, autorità, speciale), "
                "ente, date, norme verificate (almeno una), auditor dell'ente, ambito, stato, esito e data entro cui inviare "
                "il piano azioni all'ente.",
            ]),
            ("p", "Nella scheda dell'audit:"),
            ("ul", [
                "«Carica il rapporto»: il PDF dell'ente, cifrato, con impronta SHA-256; download registrato.",
                "«Registra un rilievo»: classificazione (NC maggiore, NC minore, osservazione, OFI), testo dell'ente, "
                "requisito, processo, responsabile e scadenza. Il rilievo diventa una voce del Registro OFI con fonte l'ente "
                "e le norme dell'audit; una NC maggiore ha priorità alta. Azioni, CAR ed efficacia si gestiscono dalla voce.",
                "«Preparazione all'audit» (solo per gli audit pianificati) controlla cosa l'auditor dell'ente guarderà "
                "per primo: certificato valido, clausole delle norme dell'audit verificate dagli audit interni chiusi nei "
                "12 mesi precedenti, programma interno dell'anno approvato e senza ritardi, NC interne degli ultimi 24 mesi "
                "con azione chiusa ed efficacia verificata, voci MOD.174 aperte oltre la data richiesta sulle stesse norme, "
                "rilievi ancora aperti dell'audit precedente dello stesso certificato (o dello stesso ente), auditor interni "
                "con qualifica valida. Ogni controllo è «In ordine», «Da sistemare» o «Critico» e apre l'elenco delle voci "
                "da sistemare; «Scarica il pacchetto (xlsx)» li esporta.",
                "«Piano azioni per l'ente»: «Scarica il piano azioni (xlsx)» compone il piano dai testi delle voci MOD.174 "
                "(classificazione, requisito, rilievo, PLAN, DO, CHECK, responsabile, data, stato). Dopo l'invio registra "
                "la data con «Registra l'invio»: il promemoria del lunedì si ferma.",
                "«Chiudi l'audit» compare quando ci sono esito e rapporto, nessuna NC è ancora aperta e l'invio del piano "
                "azioni è registrato (se l'ente lo aspetta); dopo la chiusura non si aggiungono rilievi.",
                "Ogni lunedì RSGI riceve il riepilogo di certificati in scadenza, sorveglianze vicine e piani azioni da "
                "inviare non ancora registrati come inviati (job «sistema_gestione_scadenze_esterni»).",
            ]),
        ],
    },
]

# --- Registro OFI ---------------------------------------------------------------

_PAGINE_OFI = [
    {
        "id": "ofi-registro",
        "titolo": "Il Registro OFI/NC (MOD.174)",
        "blocchi": [
            ("p", "Il registro unico delle opportunità di miglioramento e delle non conformità del SGI, fedele al MOD.174 - "
                  "SGI Registro OFI_NC Rev.0, con il ciclo PLAN-DO-CHECK-ACT. È un modulo a sé, «Registro OFI» nel menu "
                  "Qualità, con il suo menu interno: Dashboard, Registro MOD.174, Le mie voci, + Nuovo inserimento, Guida."),
            ("p", "Le voci arrivano da più parti:"),
            ("ul", [
                "dagli audit interni: ogni OFI o NC registrata in «Compila verifica» (fonte «Audit interno»);",
                "dagli audit degli enti: ogni rilievo registrato nella scheda dell'audit esterno (fonte l'ente);",
                "dalle specifiche cliente: le righe MOD.133 con impatto;",
                "dalla scheda di un processo del catalogo, scheda «OFI / NC», «Nuova OFI / NC su questo processo»;",
                "da altre segnalazioni, con «Nuovo inserimento» (fonte per esempio cliente, INTERNO);",
                "dall'import del MOD.174 Excel già compilato.",
            ]),
            ("p", "Ogni voce è legata a un processo del catalogo quando il «Processo/area» lo indica senza dubbi (codice, nome "
                  "o «codice - nome»), oppure scegliendolo in «Processo del catalogo». Le voci dei rilievi degli audit interni "
                  "prendono il processo della domanda di checklist, o l'unico processo dell'audit. Le voci collegate compaiono "
                  "nella scheda del processo e pesano sulla priorità dei suoi audit."),
            ("p", "Permessi: «Registro OFI - Consulta registro e dashboard» apre registro, dashboard completa ed export; «Registro "
                  "OFI - Le mie voci», dato a tutti, apre solo le voci di cui si è responsabili; «Registro OFI - "
                  "Inserisci/Modifica» crea e modifica le voci. Chi apriva il registro con il permesso delle specifiche lo apre "
                  "ancora: il permesso nuovo è stato concesso agli stessi ruoli, utenti e gruppi."),
            ("def", [
                ("Fonte", "chi ha rilevato la voce (nel modulo Excel è la colonna intestata «27001»: DEKRA, INTERNO…)."),
                ("Norme", "9100, 45001, 14001, 27001 e PdR 125, più il REF NORMA con il paragrafo (es. 27002-7.2)."),
                ("PLAN / DO / CHECK / ACT", "cosa si pianifica, cosa si è fatto, come si è verificato, come si consolida."),
                ("DATA REQUIRED / DATA CLOSED", "scadenza richiesta e data di chiusura."),
                ("P D C A e TOT", "le X cumulative del modulo: una voce in Check ha la X in P, D e C; TOT è la lettera della fase."),
            ]),
            ("p", "Il contatore A/P confronta le voci arrivate almeno ad Act con il totale: l'obiettivo del modulo è almeno il 90%."),
        ],
    },
    {
        "id": "ofi-lista",
        "titolo": "Pagina «Registro MOD.174»",
        "blocchi": [
            ("ul", [
                "Le tessere in alto mostrano il numero di voci e la percentuale di completamento (A/P).",
                "Filtri: OFI/NC, modulo d'origine (senza filtro è il registro unico), origine (Audit interni, Audit degli "
                "enti, Specifiche / MOD.133, Inserite a mano), processo del catalogo (anche «Senza processo del catalogo»), "
                "fase, priorità, «Solo scaduti», «Solo aperte» e «Le mie voci» (quelle di cui sei responsabile, con il "
                "numero di quelle ancora aperte). La casella «Cerca» trova numero, processo, descrizione, PLAN, REF, norma, "
                "fonte e owner; «Cerca» applica.",
                "Dalla dashboard arrivano anche i filtri «In scadenza entro 30 giorni» e «Senza responsabile»: compaiono come "
                "etichette con ✕ per toglierli.",
                "«Dashboard» torna alla pagina iniziale del modulo.",
                "Nella colonna PROCESSO il nome è un collegamento quando la voce è legata a un processo del catalogo: apre "
                "la scheda del processo.",
                "Sopra la tabella i contatori P, D, C, A, la percentuale A/P (verde se almeno 90%) e le voci scadute.",
                "La colonna «STATO PDCA» mostra le quattro tappe con i colori del modulo: P azzurro, D rosso, C giallo, A verde; "
                "la tappa in corso è cerchiata in arancio.",
                "Il numero apre la scheda della voce; «Modifica» compare a chi può inserire voci.",
                "«Esporta Excel» scarica le voci filtrate con le colonne del MOD.174 e i contatori in testa. L'esportazione "
                "viene registrata nel log.",
            ]),
        ],
    },
    {
        "id": "ofi-inserimento",
        "titolo": "Nuovo inserimento e modifica di una voce",
        "blocchi": [
            ("p", "«Nuovo inserimento» (permesso «Registro OFI - Inserisci/Modifica»). Il numero viene assegnato dal portale."),
            ("ul", [
                "Il primo campo è la scelta OFI o NC. Seguono REF, DATA, fonte, modulo di competenza, norme e REF NORMA, "
                "«Processo del catalogo», «PROCESSO (testo del MOD.174)» e OPPORTUNITY.",
                "Scegliendo il «Processo del catalogo» il testo PROCESSO si compila da solo e, se il «Responsabile (utente)» "
                "è vuoto, diventa il responsabile del processo.",
                "Da «Nuova OFI / NC su questo processo» nella scheda del processo il modulo arriva con processo, responsabile, "
                "fonte INTERNO e norme del processo già proposti; «Annulla» riporta alla scheda del processo.",
                "Dopo il salvataggio si apre la scheda della voce.",
                "Il ciclo PDCA si compila man mano: fase, PLAN, Allegato/Link, DO, CHECK e ACT.",
                "In «Allegato / Link» vanno solo indirizzi http(s):// o percorsi di rete \\\\server\\cartella.",
                "Gestione: «Responsabile (utente)», DATA REQUIRED, DATA CLOSED, proprietario, OWNER, priorità e «Reminder "
                "scadenza attivo». Il responsabile è un utente del portale: riceve i solleciti, trova la voce in «Le mie voci» "
                "e può farla avanzare nel PDCA anche senza il permesso di inserimento. Proprietario e OWNER restano testo "
                "libero come nel MOD.174.",
            ]),
            ("p", "Regole controllate al salvataggio:"),
            ("ul", [
                "Una voce «Chiuso» richiede la DATA CLOSED e, viceversa, con la DATA CLOSED la fase deve essere «Chiuso».",
                "La chiusura non può precedere l'apertura.",
                "Prima di chiudere va scritto nel CHECK come è stata verificata l'efficacia (MT CN 11 §5.4).",
                "Se la voce ha una CAR, scadenza, fase e chiusura si gestiscono solo dalla CAR (proroga e verifica indipendente).",
                "Con una CAR ancora aperta la voce non si può mettere in «Chiuso».",
            ]),
            ("p", "Ogni salvataggio scrive nella cronologia della voce i cambi di fase, scadenza e responsabile."),
        ],
    },
    {
        "id": "ofi-scheda",
        "titolo": "Scheda della voce",
        "blocchi": [
            ("ul", [
                "In alto tipo, numero, modulo d'origine e fase.",
                "«Collegamenti»: «Da dove nasce» porta al rilievo dell'audit interno, all'audit dell'ente o alla specifica "
                "(MOD.133) da cui viene la voce («Inserita a mano» se non viene da altri moduli); «Processo del catalogo» "
                "apre la scheda del processo, oppure «Scegli il processo» se non è collegata; «Azione correttiva MT CN 11» "
                "apre la CAR (aperta, chiusa o da aprire): per le NC va aperta di norma, per le OFI è facoltativa.",
                "La scheda si apre a chi consulta il registro e al responsabile della voce; gli altri ricevono «accesso negato».",
                "«Stato PDCA» mostra le tappe completate, quella in corso e quelle da fare.",
                "Sotto lo stato, chi gestisce il registro e il responsabile della voce scrivono cosa è stato fatto nella fase "
                "corrente e premono «Passa a …» (in Act il pulsante è «Chiudi la voce»). Senza testo la fase non si chiude. "
                "Se c'è una CAR aperta, al posto del pulsante compare il collegamento alla CAR: la voce si chiude con la CAR.",
                "«La verifica non è superata: riapri in PLAN» (in Check, Act o a voce chiusa) riporta la voce in PLAN; il "
                "motivo è obbligatorio e resta in cronologia.",
                "«Evidenze»: file PDF, immagini, Word o Excel caricati con «Carica». Sono cifrati, si scaricano solo dalla "
                "scheda e ogni caricamento e download è registrato.",
                "«Cronologia»: chi ha creato la voce, cambiato fase, scadenza o responsabile, caricato evidenze, riaperto la "
                "voce, e i solleciti inviati. Le voci esistenti prima di questa funzione hanno la cronologia dalle modifiche "
                "successive.",
                "Seguono Identificazione (fonte, norme, processo, opportunità), Ciclo PDCA e Gestione e scadenza; le date "
                "scadute sono in rosso.",
                "«Azioni collegate» riporta le azioni MOD.133 sui documenti CN.",
            ]),
        ],
    },
    {
        "id": "ofi-solleciti",
        "titolo": "Scadenze e solleciti",
        "blocchi": [
            ("ul", [
                "Le voci aperte con «Reminder scadenza attivo» e DATA REQUIRED passata ricevono un sollecito email al "
                "responsabile della voce e agli indirizzi configurati (automazione «gs_ofi_reminder»). Il sollecito resta "
                "nella cronologia.",
                "Il sollecito parte una volta per scadenza: se la DATA REQUIRED cambia, per esempio con una proroga della CAR, "
                "riparte per la nuova data.",
                "Le CAR hanno in più i solleciti giornalieri al responsabile e l'escalation a RSGI.",
            ]),
        ],
    },
    {
        "id": "ofi-cruscotto",
        "titolo": "Dashboard del modulo",
        "blocchi": [
            ("p", "È la pagina iniziale del Registro OFI (voce «Dashboard» del menu interno; il vecchio indirizzo del "
                  "cruscotto porta qui). Il filtro modulo restringe tutti i numeri a un modulo d'origine."),
            ("ul", [
                "«Il mio lavoro», per tutti: le voci aperte di cui sei responsabile, con fase, processo e scadenza (in rosso se "
                "scaduta) e i contatori «scadute» ed «entro 30 giorni»; «Tutte le mie voci →» apre «Le mie voci».",
                "Il resto è di chi consulta il registro. Tessere: voci aperte, di cui non conformità, scadute, in scadenza "
                "entro 30 giorni, aperte senza responsabile, chiuse negli ultimi 12 mesi, tempo medio di chiusura (giorni "
                "dall'apertura alla chiusura, voci chiuse negli ultimi 12 mesi) e percentuale di quelle chiuse entro la DATA "
                "REQUIRED (verde da 90%). Le prime cinque aprono il registro già filtrato.",
                "«Scadute», «In scadenza entro 30 giorni» e «Senza responsabile»: le prime 8 voci di ciascun elenco, con "
                "«Tutte le … →» quando sono di più.",
                "«Da dove arrivano le voci»: aperte e totali per origine (Audit interni, Audit degli enti, Specifiche / "
                "MOD.133, Inserite a mano); ogni riquadro apre il registro filtrato.",
                "«Voci aperte per processo del catalogo»: aperte, NC e scadute per processo, con il collegamento alla scheda "
                "del processo e «Voci →» al registro filtrato; in alto il numero di voci aperte senza processo del catalogo.",
                "Andamento: voci aperte e chiuse in ciascuno degli ultimi 12 mesi.",
                "Aperte per fase PDCA, per anzianità (fino a 30 giorni, 31-90, 91-180, oltre 180), per fonte e per norma.",
                "Rilievi ricorrenti: processi con 3 o più voci aperte negli ultimi 12 mesi, da guardare per una causa comune.",
                "«Attività recente»: gli ultimi 12 eventi delle cronologie (creazioni, cambi di fase, evidenze, solleciti).",
            ]),
        ],
    },
    {
        "id": "ofi-mie",
        "titolo": "Le mie voci",
        "blocchi": [
            ("p", "Le voci di cui sei «Responsabile (utente)», anche senza il permesso di consultare tutto il registro."),
            ("ul", [
                "«Aperte»: voce, PDCA (tappe fatte in verde, quella in corso in arancio), processo, descrizione, da dove nasce "
                "e scadenza (in rosso se passata). Le scadenze più vicine sono in alto, le voci senza scadenza in fondo.",
                "«Chiuse»: le voci già chiuse, dalla più recente.",
                "Il numero apre la scheda: lì scrivi cosa hai fatto nella fase in corso, passi alla successiva e carichi le "
                "evidenze.",
            ]),
        ],
    },
    {
        "id": "ofi-import",
        "titolo": "Import del MOD.174 storico (amministratori)",
        "blocchi": [
            ("p", "Il comando «import_mod174» carica nel registro un MOD.174 Excel già compilato, senza duplicare: le voci si "
                  "riconoscono dal REF."),
            ("ul", [
                "Senza «--apply» è una prova che conta soltanto le voci da creare e aggiornare.",
                "La fase si ricava dalle X di P, D, C e A; con la DATA CLOSED la voce è chiusa.",
                "La colonna «27001» diventa la fonte (DEKRA, INTERNO); le norme si ricavano anche dal REF NORMA "
                "(27001-9.2, 27002-7.2 = ISO 27001).",
            ]),
        ],
    },
]

_FAQ = {
    "id": "faq",
    "titolo": "Domande frequenti",
    "blocchi": [
        ("def", [
            ("Non vedo i pulsanti per modificare.", "Manca il permesso: chiedilo a un amministratore da Admin › ACL."),
            ("Non riesco ad approvare il piano come Direzione.", "La Direzione deve essere una persona diversa dal Lead Auditor."),
            ("Il portale non accetta la data dell'audit.", "Serve un preavviso di almeno 5 giorni lavorativi dalla comunicazione, "
             "oppure una motivazione per la deroga."),
            ("Non riesco a chiudere l'audit.", "Leggi «Prima della chiusura»: di solito manca il piano azioni approvato di una NC."),
            ("Non riesco a chiudere la CAR.", "Serve l'approvazione dell'analisi, tutte le evidenze compilate e una persona diversa "
             "dal responsabile dell'azione."),
            ("Una OFI va trattata con la CAR?", "Non obbligatoriamente: un'osservazione o un'OFI può essere risolta dal "
             "responsabile di processo nel PDCA della voce (MT CN 12 §5.6)."),
            ("Dove trovo il rapporto definitivo?", "In «Versioni del rapporto», versione «Emissione» con impronta SHA-256."),
        ]),
    ],
}

GUIDA_AUDIT = {
    "titolo": "Audit interni e Registro OFI",
    "codice": "MT CN 12 · MT CN 11 · MOD.174",
    "sottotitolo": "Come si programmano, pianificano, eseguono e documentano gli audit interni e come si trattano i rilievi.",
    "sezioni": _GENERALE + _PAGINE_AUDIT + _PAGINE_OFI + [_FAQ],
    "url_name": "sistema_gestione:audit_guida",
    "indietro": ("sistema_gestione:audit_index", "Audit interni"),
}

GUIDA_OFI = {
    "titolo": "Registro OFI / NC",
    "codice": "MOD.174 Rev.0 · MT CN 11",
    "sottotitolo": "Come si registrano, seguono nel PDCA e chiudono le opportunità di miglioramento e le non conformità.",
    "sezioni": _PAGINE_OFI + [s for s in _PAGINE_AUDIT if s["id"] == "pagina-car"] + [_FAQ],
    "url_name": "registro_ofi:guida",
    "indietro": ("registro_ofi:home", "Registro OFI"),
}

# Rotta -> (guida, capitolo). Le pagine del registro puntano alla guida del registro,
# così chi ha solo quel permesso non incontra un 403.
PAGE_HELP = {
    "sistema_gestione:audit_index": ("audit", "pagina-indice"),
    "sistema_gestione:processi_catalogo": ("audit", "pagina-catalogo"),
    "sistema_gestione:processo_dettaglio": ("audit", "pagina-catalogo"),
    "sistema_gestione:processo_nuovo": ("audit", "pagina-catalogo"),
    "sistema_gestione:processo_modifica": ("audit", "pagina-catalogo"),
    "sistema_gestione:checklist_processo_nuova": ("audit", "pagina-catalogo"),
    "sistema_gestione:checklist_processo_modifica": ("audit", "pagina-catalogo"),
    "sistema_gestione:auditor_elenco": ("audit", "pagina-auditor"),
    "sistema_gestione:auditor_nuovo": ("audit", "pagina-auditor"),
    "sistema_gestione:auditor_modifica": ("audit", "pagina-auditor"),
    "sistema_gestione:audit_priorita": ("audit", "pagina-priorita"),
    "sistema_gestione:programma_nuovo": ("audit", "pagina-programma"),
    "sistema_gestione:programma_dettaglio": ("audit", "pagina-programma"),
    "sistema_gestione:programma_riga_nuova": ("audit", "pagina-programma"),
    "sistema_gestione:programma_riga_modifica": ("audit", "pagina-programma"),
    "sistema_gestione:programma_cicli": ("audit", "pagina-cicli"),
    "sistema_gestione:programma_ciclo": ("audit", "pagina-cicli"),
    "sistema_gestione:audit_calendario": ("audit", "pagina-calendario"),
    "sistema_gestione:audit_nuovo": ("audit", "pagina-piano"),
    "sistema_gestione:audit_modifica": ("audit", "pagina-piano"),
    "sistema_gestione:audit_elemento_modifica": ("audit", "pagina-audit"),
    "sistema_gestione:audit_dettaglio": ("audit", "pagina-audit"),
    "sistema_gestione:audit_isms": ("audit", "pagina-isms"),
    "sistema_gestione:checklist_norme": ("audit", "pagina-checklist-norme"),
    "sistema_gestione:checklist_modello": ("audit", "pagina-checklist-norme"),
    "sistema_gestione:procedura_preparazione": ("audit", "pagina-preparazione"),
    "sistema_gestione:audit_esito_editor": ("audit", "pagina-verifica"),
    "sistema_gestione:audit_verifica_efficacia": ("audit", "pagina-efficacia"),
    "sistema_gestione:procedura_car": ("ofi", "pagina-car"),
    "sistema_gestione:audit_miei_rilievi": ("audit", "pagina-miei-rilievi"),
    "sistema_gestione:esterni_elenco": ("audit", "pagina-esterni"),
    "sistema_gestione:esterni_certificazione_nuova": ("audit", "pagina-esterni"),
    "sistema_gestione:esterni_certificazione": ("audit", "pagina-esterni"),
    "sistema_gestione:esterni_audit_nuovo": ("audit", "pagina-esterni"),
    "sistema_gestione:esterni_audit": ("audit", "pagina-esterni"),
    "sistema_gestione:esterni_audit_modifica": ("audit", "pagina-esterni"),
    "sistema_gestione:esterni_preparazione_export": ("audit", "pagina-esterni"),
    "sistema_gestione:esterni_piano_export": ("audit", "pagina-esterni"),
    "sistema_gestione:audit_cruscotto": ("audit", "pagina-cruscotto"),
    "sistema_gestione:procedura_kpi": ("audit", "pagina-kpi"),
    "sistema_gestione:audit_impostazioni": ("audit", "pagina-impostazioni"),
    "registro_ofi:home": ("ofi", "ofi-cruscotto"),
    "registro_ofi:mie": ("ofi", "ofi-mie"),
    "registro_ofi:lista": ("ofi", "ofi-lista"),
    "registro_ofi:nuovo": ("ofi", "ofi-inserimento"),
    "registro_ofi:modifica": ("ofi", "ofi-inserimento"),
    "registro_ofi:dettaglio": ("ofi", "ofi-scheda"),
    "registro_ofi:cruscotto": ("ofi", "ofi-cruscotto"),
}

_GUIDE = {"audit": GUIDA_AUDIT, "ofi": GUIDA_OFI}


def link_pagina(route_name: str) -> str:
    """URL del capitolo che spiega la rotta (stringa vuota se la rotta non ha un capitolo)."""
    voce = PAGE_HELP.get(route_name or "")
    if not voce:
        return ""
    guida, ancora = voce
    return f"{reverse(_GUIDE[guida]['url_name'])}#{ancora}"


def risposta_guida(request, guida: dict):
    if request.GET.get("pdf") == "1":
        pdf = render_guida_pdf(guida, generato_da=request.user.get_full_name() or request.user.get_username(),
                               generato_il=timezone.localtime().strftime("%d/%m/%Y %H:%M"))
        resp = HttpResponse(pdf, content_type="application/pdf")
        nome = guida["titolo"].replace(" / ", " ").replace(" ", "_")
        resp["Content-Disposition"] = f'attachment; filename="Guida_{nome}.pdf"'
        return resp
    indietro_url, indietro_label = guida["indietro"]
    return render(request, "sistema_gestione/pages/guida.html", {
        "guida": guida, "sezioni": guida["sezioni"], "pdf_url": f"{reverse(guida['url_name'])}?pdf=1",
        "indietro_url": reverse(indietro_url), "indietro_label": indietro_label,
    })


@login_required
def guida_audit(request):
    return risposta_guida(request, GUIDA_AUDIT)


def render_guida_pdf(guida: dict, *, generato_da: str = "", generato_il: str = "") -> bytes:
    from core.guida_pdf import render_guida_pdf as _pdf

    return _pdf(titolo=f"{guida['titolo']} · {guida['codice']}", sottotitolo=guida["sottotitolo"],
                sezioni=guida["sezioni"], generato_da=generato_da, generato_il=generato_il)
