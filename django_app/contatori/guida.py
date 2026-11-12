"""Guida di Contatori IT (pagina «? Guida» della barra del modulo).

Testo semplice, niente HTML: il template lo mostra con l'autoescape. Blocchi di una
sezione: ("p", testo), ("ul", [voci]), ("nota", testo), ("def", [(termine, spiegazione)]).
Le etichette citate sono quelle visibili nelle pagine: se ne cambia una, va
aggiornata anche qui.
"""
from __future__ import annotations

SEZIONI: list[dict] = [
    {
        "id": "scopo",
        "titolo": "A cosa serve",
        "blocchi": [
            ("p", "La riconciliazione confronta, per ogni trimestre, le letture dei contatori stampate "
                  "nella fattura del fornitore con le letture interne delle stesse MFC. La lettura interna "
                  "è fatta qualche giorno dopo la chiusura del fornitore, quindi deve essere maggiore o "
                  "uguale: se è minore, il fornitore ha fatturato copie che la macchina non mostra."),
            ("def", [
                ("Scarto", "interno − fornitore. Negativo = da controllare."),
                ("OK esatto", "interno uguale al fornitore."),
                ("OK (stampe nel ritardo)", "interno maggiore: sono le copie fatte tra la chiusura del "
                                            "fornitore e la lettura interna."),
                ("Da controllare: fornitore > interno", "il fornitore dichiara più copie della macchina."),
                ("lettura interna mancante", "almeno una MFC del contratto non ha la lettura del trimestre."),
            ]),
        ],
    },
    {
        "id": "fattura",
        "titolo": "Caricare la fattura",
        "blocchi": [
            ("p", "Da Riconciliazione → «+ Nuova fattura» carica la fattura elettronica (XML, consigliato) "
                  "o la sua stampa PDF e premi «Leggi la fattura»: la pagina si compila da sola. Controlla "
                  "gli avvisi in giallo, poi «Salva fattura». Il file non viene conservato."),
            ("p", "Sono riconosciuti due tracciati:"),
            ("ul", [
                "BASE: blocchi «N. Contratto: …» con una riga per contatore A4/A3 B/N e colore. Il "
                "contatore si ricava dal prezzo per copia.",
                "Copylab: blocchi «Matricola:… Contratto:…» per ogni macchina, con le righe «COPIE "
                "EFFETTUATE B/N» e «COPIE EFFETTUATE COLORE». La fattura riporta solo i totali: viene "
                "salvata con «Letture in fattura» = «Solo totali B/N e colore».",
            ]),
            ("p", "Per Copylab il contratto della riga viene preso dall'anagrafica stampanti cercando la "
                  "matricola: se la macchina non ha il contratto in anagrafica compare un avviso con il "
                  "valore da impostare."),
            ("nota", "In una fattura «Solo totali» il totale B/N va nella colonna «B/N totale» e il totale "
                     "colore in «Colore totale»; le colonne A3 non si usano."),
        ],
    },
    {
        "id": "fatture-multiple",
        "titolo": "Caricare più fatture insieme (trimestri passati)",
        "blocchi": [
            ("ul", [
                "Fatture → «Importa più fatture» (o dalla Riconciliazione / da «+ Nuova fattura» → «Più fatture insieme»).",
                "Scegli tutti i file insieme (XML o PDF, fino a 30 file da 5 MB) e premi «Leggi le fatture».",
                "Nell'anteprima ogni fattura ha un esito: «pronta» (già selezionata), «da verificare» (ci sono "
                "avvisi: leggili, poi selezionala o aprila con «Apri per controllare e salvare»), «già caricata» "
                "(stesso numero nello stesso trimestre, anche ripetuto nell'import) o «non leggibile».",
                "Premi «Salva le fatture selezionate». Ogni fattura passa gli stessi controlli della pagina "
                "singola: se uno non torna (contratto non in anagrafica, chiusura fuori dal trimestre) non viene "
                "salvata e il messaggio dice il motivo.",
            ]),
            ("p", "Il trimestre di ogni fattura è quello della data di chiusura letture del fornitore. Si possono "
                  "caricare fatture di qualunque trimestre passato."),
            ("p", "Fatture → l'archivio elenca tutte le fatture per trimestre con l'esito della riconciliazione "
                  "e segna «fattura mancante» i trimestri con letture interne ma senza fattura."),
            ("nota", "I file non vengono conservati: l'anteprima resta disponibile finché non premi «Svuota "
                     "l'elenco» o carichi altri file."),
        ],
    },
    {
        "id": "pool",
        "titolo": "Più MFC sullo stesso contratto (pool)",
        "blocchi": [
            ("p", "Se più MFC hanno lo stesso valore nel campo «Contratto» dell'anagrafica stampanti, sono "
                  "fatturate in pool: la fattura riporta una lettura unica e la riconciliazione la confronta "
                  "con la somma delle letture interne delle macchine. Il contratto mostra il badge "
                  "«pool · N MFC» e sotto il valore interno la parte di ogni macchina."),
            ("p", "Se manca la lettura anche di una sola macchina del pool il confronto non viene fatto "
                  "(una somma parziale darebbe un falso allarme): l'esito è «lettura interna mancante» e "
                  "accanto alla macchina c'è «+ Lettura»."),
            ("nota", "Il contratto deve essere scritto identico su tutte le MFC del pool. Una MFC dismessa "
                     "(non attiva) conta solo nei trimestri in cui ha una lettura: dopo la sostituzione non "
                     "risulta più «lettura mancante»."),
        ],
    },
    {
        "id": "lettura",
        "titolo": "Leggere la pagina",
        "blocchi": [
            ("ul", [
                "Le schede in alto contano i contratti: «Allineati», «Da controllare» (con il numero di "
                "contatori in cui il fornitore supera l'interno) e «Letture interne mancanti».",
                "«Tutti» / «Da verificare» filtrano i contratti: «Da verificare» mostra solo quelli da "
                "controllare o incompleti.",
                "Ogni contratto ha la sua scheda: fattura, fornitore, data di chiusura e, per ogni MFC, la "
                "data della lettura interna e i giorni dopo la chiusura del fornitore. Una lettura fatta "
                "prima della chiusura viene segnalata: in quel caso uno scarto negativo è atteso.",
                "Nelle fatture «Solo totali» i contatori sono «BN totale» e «COL totale»: l'interno è A4 + A3.",
                "«Esporta .xlsx» scarica il confronto riga per riga.",
            ]),
        ],
    },
    {
        "id": "registro-letture",
        "titolo": "Registro letture, elenco MFC e scheda MFC",
        "blocchi": [
            ("p", "Letture → «Registro letture»: una riga per MFC e una colonna per trimestre (4, 8, 12 o 16). "
                  "Ogni cella mostra il totale letto, le copie rispetto al trimestre prima e la fonte. «+ manca» "
                  "(in giallo) è un trimestre chiuso senza lettura, dalla prima lettura della MFC in poi: un clic "
                  "apre l'inserimento già compilato. In rosso i contatori scesi rispetto alla lettura prima. "
                  "Nella colonna del trimestre «in corso», se la lettura del trimestre non c'è ancora, compare in "
                  "grigio corsivo l'ultima lettura mensile presa nel trimestre (es. «mensile 01/11») con le copie "
                  "rispetto al trimestre prima: è provvisoria, non conta come lettura e non si modifica da lì. "
                  "«+ Nuova lettura» (o «+ manca», «+») con stampante e trimestre scelti precompila i contatori "
                  "dalla lettura mensile SNMP: per un trimestre chiuso quella del primo giorno del trimestre dopo "
                  "(presa entro il giorno 7), per il trimestre in corso l'ultima presa, provvisoria. Cambiando "
                  "stampante o trimestre i valori si ricaricano; senza mensile si inseriscono a mano. "
                  "«Anche le MFC dismesse» mostra le macchine non più attive."),
            ("p", "Stampanti MFC: si cerca per reparto, matricola, contratto, IP, modello o asset e si filtra per "
                  "salute SNMP e per «Lettura»: trimestre in corso mancante o presente, oppure «Mensile mm/aaaa "
                  "mancante» (le MFC con IP senza la lettura mensile del mese, le stesse della voce «letture "
                  "mensili in attesa / saltate» della Centrale). Le MFC dismesse sono nascoste salvo «Anche le "
                  "dismesse». Ogni riga mostra anche il consumabile più basso."),
            ("p", "Letture → «Tutte le MFC di un trimestre»: una riga per MFC attiva con l'ultima lettura "
                  "precedente come riferimento. Compila solo le righe che hai e premi «Salva le letture "
                  "compilate»: le righe vuote si saltano, quelle valide si salvano e quelle con un errore "
                  "(data fuori trimestre, contatore più basso) restano in pagina evidenziate. Per un contatore "
                  "azzerato o una macchina sostituita spunta «Confermo: azzerato o sostituito». Utile per "
                  "caricare lo storico dei trimestri passati."),
            ("ul", [
                "Scheda MFC → letture trimestrali dalla più recente con la colonna «Copie»; un trimestre saltato "
                "compare come «Lettura mancante» con «Inserisci».",
                "Letture mensili con le copie del mese (gli ultimi 24 mesi; con il permesso di gestione "
                "«Tutte (N) in Gestisci letture» apre l'elenco completo della MFC).",
                "«Fatture del contratto»: esito della riconciliazione negli ultimi 6 trimestri fatturati e giorni "
                "tra la chiusura del fornitore e la lettura interna; se ce ne sono di più, «Tutte (N) →» apre "
                "l'archivio fatture. Nelle MFC in pool l'Info elenca le altre macchine dello stesso contratto.",
                "«Esporta storico»: Excel con letture trimestrali (copie, mancanze, cali), mensili e anagrafica.",
                "Scheda asset di una stampante (modulo Asset) → «Letture trimestrali (confronto con la fattura)»: "
                "le ultime 4 con le copie del trimestre e le letture mancanti.",
                "Monitor SNMP: «Cerca» per nome, IP, posizione o asset; la colonna «Risposte 24 h» dice quante "
                "interrogazioni hanno avuto risposta (verde 100%, giallo dal 95%, rosso sotto).",
                "Scheda di un dispositivo SNMP → «Storico interrogazioni»: tutte le interrogazioni dalla più "
                "recente, caricate man mano che si scorre; «Stato» mostra solo quelle Operative, in Attenzione o "
                "in Errore.",
            ]),
        ],
    },
    {
        "id": "gestisci-letture",
        "titolo": "Gestisci letture: correggere ed eliminare",
        "blocchi": [
            ("p", "Letture → «Gestisci letture» (serve «Contatori - Gestione»): tutte le letture in un elenco, "
                  "dalla più recente. In alto si sceglie «Trimestrali» (Q1–Q4, quelle della riconciliazione) "
                  "oppure «Mensili» (le letture automatiche SNMP del giorno 1)."),
            ("ul", [
                "Filtri: «MFC», «Anno» e «Solo letture con un calo». In rosso, con «calo A4 BN…», le letture "
                "con un contatore più basso della lettura prima della stessa MFC: di solito sono quelle sbagliate. "
                "Dalla Centrale, un clic su una riga di «Cali di lettura» apre questo elenco già filtrato sulla MFC.",
                "«Modifica» apre la correzione; dopo il salvataggio si torna all'elenco con gli stessi filtri. "
                "Se un valore resta più basso della lettura prima (o più alto della dopo) il portale chiede "
                "«Confermo i valori: il contatore è stato azzerato o la macchina sostituita».",
                "Per eliminare: spunta le righe (la casella in testata le seleziona tutte) e premi «Elimina "
                "selezionate»; il portale chiede conferma. L'operazione non si annulla e resta nel log.",
                "Una lettura mensile eliminata non si ricrea: solo quella del mese in corso viene riletta "
                "in automatico, se siamo entro il giorno 7.",
            ]),
        ],
    },
    {
        "id": "centrale",
        "titolo": "Barra del modulo e Centrale",
        "blocchi": [
            ("p", "La barra in alto raggruppa le pagine in Operatività (Centrale, Stampanti MFC, Letture, "
                  "Mensili, Consumabili, Fabbisogno, Monitor SNMP), Economico (Riconciliazione, Fatture, Analisi) e Configurazione "
                  "(Profili SNMP, Discovery, Impostazioni). Le procedure guidate «+ Apparato» (stampanti MFC e "
                  "dispositivi SNMP) e «+ Profilo SNMP» sono nel menu «+ Nuovo» (solo con il permesso di "
                  "gestione). «? Guida», a destra, apre questa pagina da qualunque punto del modulo."),
            ("p", "La Centrale sta in una schermata: in alto gli indicatori (letture del trimestre, copie, "
                  "riconciliazione del trimestre precedente, stato flotta SNMP, consumabili sotto soglia, "
                  "letture da confermare, fatture da riconciliare, licenze degli apparati); sotto, il flusso dei dati: a sinistra le "
                  "famiglie di apparati (Stampanti MFC, Videosorveglianza, Rete e sicurezza, Server e storage, UPS e ambiente, "
                  "Lettori), al centro il cerchio con gli apparati operativi sul totale, a destra i risultati (letture del trimestre, "
                  "consumabili, errori SNMP, letture da confermare, fatture). Il colore dice lo stato (verde in regola, giallo da "
                  "guardare, rosso in errore); un clic su un risultato apre la sua pagina, un clic su una famiglia filtra la mappa. "
                  "La mappa della flotta ha un riquadro per apparato, con sigla (MFC, NET, SRV, UPS, CAM, LET), nome e IP, in "
                  "cima chi è in errore: i filtri In errore / Attenzione / Non interrogati / Operativi usano gli stessi numeri di "
                  "«Stato flotta», la casella cerca per nome o IP, un clic apre il pannello laterale (Ctrl+clic la scheda). "
                  "Ancora sotto, tre colonne che scorrono ognuna per "
                  "conto suo: «Da fare», «Parco MFC» e «SNMP». Ogni indicatore e ogni voce aprono la pagina "
                  "dove si interviene, già filtrata (es. «MFC non raggiungibili» apre le Stampanti MFC in errore, "
                  "«letture mensili in attesa» quelle senza la lettura del mese); nel Parco MFC il dettaglio "
                  "A4/A3 compare passando il mouse sul totale. Gli elenchi brevi della colonna SNMP finiscono con "
                  "«e altri N →», che apre la lista completa nel Monitor. In fondo a «Da fare», il blocco «Asset "
                  "e SOC» (vedi la sezione dedicata)."),
            ("p", "Cali di lettura: «Da fare» conta a parte le letture trimestrali e le letture mensili con un "
                  "contatore più basso della lettura prima; l'elenco «Cali di lettura» mostra MFC, contatore e i "
                  "due valori, e il nome della MFC apre «Gestisci letture» filtrato su quella stampante. Se il "
                  "calo è vero (contatore azzerato dal tecnico, macchina sostituita) apri «Azzeramento o "
                  "sostituzione? Segna come spiegato», scrivi il motivo e premi «Segna come spiegato» (serve "
                  "«Contatori - Gestione»): il calo esce da «Da fare» e restano nel log chi, quando e perché. "
                  "Se poi i contatori di quella lettura vengono corretti, la spiegazione si annulla."),
            ("p", "Monitor SNMP: «Interroga tutti ora» (serve «Contatori - Gestione», come «Interroga ora» "
                  "nella scheda di un dispositivo) mette in coda un'interrogazione per ogni dispositivo attivo: "
                  "gli stati si aggiornano entro qualche minuto (il monitor lo fa comunque ogni 5 minuti). I "
                  "filtri Cerca, Categoria e Stato valgono anche per la tabella «Stampanti MFC»; una categoria "
                  "diversa da «Stampante / MFC extra» la svuota. «Stato» ha le stesse voci dei riquadri: "
                  "Operativi, In attenzione, In errore, Non interrogati da oltre 3 giorni. I riquadri Operativi / "
                  "Attenzione / Errori / Non interrogati sono gli stessi numeri di «Stato flotta» della Centrale "
                  "e un clic mostra quegli apparati; «Apparati» conta tutti quelli censiti. Sotto i filtri, il "
                  "filtro rapido «Videosorveglianza»."),
            ("p", "Scheda MFC: «Prova SNMP» (serve «Contatori - Gestione», come il pulsante «Test» nelle Stampanti "
                  "MFC) verifica subito che la stampante risponda e mostra i contatori letti senza salvarli; «Asset …» "
                  "apre la scheda dell'asset collegato. Dopo «Modifica MFC» si torna alla scheda della stampante."),
            ("p", "«Apri ticket» (scheda MFC e pannello laterale, a chi può aprire ticket IT) apre il form «Nuovo "
                  "ticket» già compilato: categoria «Stampante / Scanner», asset collegato se c'è, titolo con il "
                  "problema (l'ultimo avviso critico aperto, altrimenti «non risponde in rete» o i consumabili da "
                  "sostituire) e descrizione con matricola, modello, IP, stato SNMP e ultimo errore, avviso critico, "
                  "consumabili sotto il 15% e link alla scheda. Priorità «Alta» con un avviso critico o la stampante "
                  "non raggiungibile, altrimenti «Media». Il ticket nasce solo quando premi «Invia richiesta»: prima "
                  "controlli e correggi."),
            ("p", "«Scarica Excel» c'è in Consumabili, Fabbisogno, Registro letture, Gestisci letture, Stampanti "
                  "MFC, Monitor SNMP e Archivio fatture: scarica tutte le righe con i filtri della pagina (in "
                  "Gestisci letture anche quelle non ancora caricate scorrendo), con gli stessi permessi della "
                  "pagina."),
        ],
    },
    {
        "id": "mensili",
        "titolo": "Letture mensili automatiche",
        "blocchi": [
            ("p", "Il giorno 1 alle 00:00 il portale legge i contatori di ogni MFC attiva con IP, allineati "
                  "alla chiusura del fornitore. Le MFC spente o in sospensione vengono riprovate ogni 15 minuti "
                  "fino al giorno 7: la lettura arriva entro un quarto d'ora da quando la macchina si riaccende."),
            ("ul", [
                "Nella scheda MFC, «Letture mensili automatiche», il badge giallo (es. «+31 h» o «+3 gg») indica "
                "che la lettura è arrivata dopo la chiusura: i contatori includono le copie fatte nel frattempo.",
                "Dal giorno 2 al 7 la Centrale mostra «N letture mensili in attesa»; dal giorno 8 diventa "
                "«N letture mensili saltate» («1 lettura mensile saltata» se è una sola): la MFC non ha mai "
                "risposto, controlla che sia accesa e in rete.",
                "La prima lettura riuscita del mese non viene più sovrascritta.",
                "Mail di riepilogo: quando tutte le MFC sono lette parte una mail con contatori, copie del mese "
                "(«—» se manca la lettura del mese prima o un contatore è sceso), Excel allegato e link a queste "
                "letture. Il giorno 7 dalle 23:00, se manca ancora qualche MFC, parte con le mancanti e il motivo. "
                "Destinatari in Automazioni → «Pianificati» → «contatori letture mensili» → «Modifica»: "
                "senza destinatari non parte.",
            ]),
        ],
    },
    {
        "id": "letture-mensili",
        "titolo": "Letture mensili per mese",
        "blocchi": [
            ("p", "«Mensili» nella barra del modulo: una riga per MFC, una colonna per mese (gli ultimi 12 mesi, "
                  "oppure i 12 mesi dell'anno scelto in «Periodo»). Ogni cella mostra il totale letto e, sotto, le "
                  "copie rispetto al mese prima («copie n/d» se quella lettura manca, «calo …» se un contatore è "
                  "sceso)."),
            ("ul", [
                "«manca» (in giallo): MFC attiva con IP senza la lettura di quel mese, dal mese della sua prima "
                "lettura mensile; il mese in corso conta sempre, come «letture mensili in attesa» della Centrale.",
                "In fondo, «Copie del mese»: la somma delle copie delle MFC che hanno anche la lettura del mese "
                "prima, quante sono e quante mancano.",
                "«Excel» sotto un mese con letture scarica lo stesso file allegato alla mail delle letture "
                "mensili (letture, copie per contatore e MFC mancanti con il motivo).",
                "Con «Contatori - Gestione» un clic sul totale apre la correzione della lettura.",
            ]),
        ],
    },
    {
        "id": "consumabili",
        "titolo": "Consumabili della flotta",
        "blocchi": [
            ("p", "«Consumabili» mostra l'ultimo livello letto di toner, tamburi e fusore di ogni MFC attiva con "
                  "IP, le più critiche in cima. La lettura gira ogni mattina; «Leggi ora» (serve «Contatori - "
                  "Gestione») aggiorna subito una macchina."),
            ("def", [
                ("Da ordinare", "MFC con almeno un consumabile al 15% o meno, qualunque sia la data "
                                "dell'ultima lettura. Un clic mostra solo quelle."),
                ("Finiscono entro 30 giorni", "MFC con almeno un consumabile che, al ritmo di consumo stimato, si "
                                              "esaurisce entro 30 giorni. Un clic mostra solo quelle; se ce ne "
                                              "sono, la Centrale lo dice in «Da fare»."),
                ("Senza lettura recente", "MFC mai lette o con l'ultima lettura più vecchia di 7 giorni: la "
                                          "stampante non risponde da giorni. Un clic mostra solo quelle; nella "
                                          "colonna «Ultima lettura» la data è in giallo."),
                ("MFC controllate", "MFC attive con indirizzo IP."),
            ]),
            ("p", "La stima dei giorni residui usa solo le letture degli ultimi 60 giorni, dall'ultima "
                  "sostituzione: con una lettura vecchia il livello resta visibile ma la stima no."),
        ],
    },
    {
        "id": "fabbisogno",
        "titolo": "Fabbisogno dei consumabili",
        "blocchi": [
            ("p", "«Fabbisogno» (barra del modulo, o il pulsante in Consumabili): una riga per consumabile, con il "
                  "nome letto dalla stampante (es. il codice del toner), sotto i modelli di MFC che lo usano."),
            ("def", [
                ("MFC che lo usano", "MFC attive con IP che hanno quel consumabile nell'ultima lettura."),
                ("Durata media", "media dei giorni tra due sostituzioni consecutive sulla stessa MFC (i cambi "
                                 "rilevati quando il livello risale); «n/d» finché non ci sono almeno due cambi."),
                ("Pezzi all'anno", "MFC che lo usano × 365 / durata media."),
                ("Entro 30 giorni / Entro 60 giorni", "quanti di quei consumabili finiscono entro 30 o 60 giorni "
                                                      "secondo la stima della pagina Consumabili. Il numero dei 30 "
                                                      "giorni apre Consumabili filtrata."),
            ]),
            ("p", "Riquadro di Consumabili, voce della Centrale e questa pagina usano lo stesso calcolo: il "
                  "riquadro conta le MFC, questa pagina i singoli consumabili."),
        ],
    },
    {
        "id": "controlli",
        "titolo": "Controlli sulle letture SNMP",
        "blocchi": [
            ("p", "Una lettura SNMP viene scartata, e non salvata, quando i numeri non possono essere quelli "
                  "della macchina. Il motivo compare nella salute SNMP della MFC (scheda e Centrale) e nel "
                  "«Test» dell'elenco stampanti."),
            ("ul", [
                "Matricola diversa: all'IP risponde una stampante con un'altra matricola (IP cambiato o "
                "riassegnato). Correggi l'IP nella scheda MFC.",
                "Somma dei quattro contatori oltre le pagine totali dichiarate dalla stampante: il profilo "
                "SNMP conta due volte le stesse pagine. Verifica il profilo.",
                "Contatore più basso dell'ultima lettura salvata (trimestrale o mensile): o la lettura salvata "
                "è sbagliata, e va corretta, o la macchina è stata azzerata/sostituita. In quel caso inserisci "
                "la lettura a mano con «Confermo i valori» e segna il calo come spiegato dalla Centrale.",
                "Contatore negativo o oltre 2.147.483.647: l'OID del profilo non è un contatore di pagine. "
                "Verifica il profilo.",
            ]),
            ("p", "Il «Test» mostra comunque i valori letti e avvisa con «Non verrebbe salvata» se sono più "
                  "bassi dell'ultima lettura. «Leggi MFC ora» e la raccolta mensile applicano gli stessi controlli."),
            ("p", "«Leggi MFC ora» nei primi 7 giorni di gennaio, aprile, luglio e ottobre salva la lettura di "
                  "chiusura del trimestre appena finito; dal giorno 8 salva quella del trimestre in corso. Una "
                  "lettura manuale salvata mentre la lettura SNMP è in corso non viene sovrascritta."),
            ("p", "Letture da confermare: per un trimestre viene proposta solo la lettura mensile di chiusura, "
                  "cioè quella del mese successivo presa entro il giorno 7. Una lettura più bassa del trimestre "
                  "precedente o più alta del successivo non si conferma: va inserita a mano."),
            ("p", "Lettura a mano: la data deve stare nel trimestre o nei 45 giorni dopo la chiusura, e non "
                  "può essere nel futuro."),
            ("p", "Analisi: le copie di un trimestre sono la differenza tra due trimestri consecutivi. Se a una "
                  "MFC manca una lettura, le sue copie non vengono attribuite a nessuno dei due trimestri e il "
                  "trimestre è segnato «parziale N/M MFC». Il trimestre corrente è «in corso» e la Centrale non "
                  "lo confronta; la variazione percentuale compare solo tra due trimestri completi."),
            ("p", "MFC Kyocera (TASKalfa): ogni contatore è la somma di stampe e copie dello stesso colore e "
                  "formato. In un profilo SNMP una colonna può sommare più OID scrivendoli uniti da + "
                  "(solo modalità GET)."),
        ],
    },
    {
        "id": "stampanti-dati",
        "titolo": "Stampanti (MFC a contratto e Monitor SNMP): avvisi, cassetti e quando finisce il toner",
        "blocchi": [
            ("p", "Le MFC a contratto sono stampanti come le altre: nella scheda MFC e nella scheda di una "
                  "stampante del Monitor SNMP compare lo stesso pannello «La stampante adesso» con lo stesso "
                  "registro avvisi. Il portale legge dalla stampante (solo lettura, standard Printer-MIB): le MFC "
                  "ogni 15 minuti (una MFC spenta si riprova dopo 15 minuti), le altre a ogni interrogazione:"),
            ("def", [
                ("La stampante adesso", "stato («pronta», «in stampa», «in riscaldamento»), il testo del "
                                        "display, le pagine stampate al giorno e l'elenco «Da sistemare»: "
                                        "avvisi aperti, sportelli aperti, cassetti vuoti o in avviso."),
                ("Cassetti carta", "nome, formato della carta, capacità in fogli e livello; «Vuoto» in rosso."),
                ("Sportelli", "aperto (rosso) o chiuso."),
                ("Registro avvisi", "ogni avviso della stampante (carta inceppata, toner in esaurimento, "
                                    "sportello aperto, assistenza richiesta…) con «Dal», «Al» e «Durata»: si apre "
                                    "quando la stampante lo segnala e si chiude quando non lo segnala più. "
                                    "«Chi interviene» è quello indicato dalla stampante. In grigio gli eventi "
                                    "normali (accensione, pronta a stampare). Gli avvisi chiusi da oltre 400 "
                                    "giorni si cancellano."),
                ("Sostituzioni consumabili", "ogni cambio di toner, tamburo, fusore o altro consumabile: "
                                             "quando il livello risale di più di 5 punti fra due letture il "
                                             "portale registra «Rilevato il» (prima lettura con il consumabile "
                                             "nuovo), «Lettura precedente» (il cambio è avvenuto fra le due), "
                                             "«Livello» prima e dopo e «Durata del precedente» (giorni dal cambio "
                                             "precedente dello stesso consumabile). In alto quanti cambi per "
                                             "consumabile negli ultimi 12 mesi. Un cambio visto due volte nei 2 "
                                             "giorni attorno (le MFC lo vedono sia dalla lettura ogni 15 minuti sia "
                                             "da quella giornaliera dei consumabili) si registra una volta sola. Il "
                                             "registro parte dal giorno dell'aggiornamento: i cambi precedenti non "
                                             "ci sono."),
                ("Finisce verso il", "sotto ogni toner: la data in cui si esaurisce al ritmo di consumo "
                                     "dall'ultima sostituzione (letture degli ultimi 60 giorni). Servono almeno 3 "
                                     "giorni di letture e un calo di almeno 2 punti; il contenitore di scarto non "
                                     "si stima. In giallo se mancano 14 giorni o meno."),
            ]),
            ("p", "Un avviso critico o uno sportello aperto mette la stampante in «Errore», gli altri avvisi e "
                  "un cassetto vuoto in «Attenzione». Se una stampante non espone la tabella avvisi, il registro "
                  "usa gli errori che segnala (carta inceppata, sportello aperto, toner esaurito…). Sulle MFC "
                  "la lettura non cambia contatori di fatturazione e letture; la data di fine del toner delle MFC "
                  "resta quella della pagina «Consumabili»."),
            ("p", "Una stampante censita due volte, come MFC a contratto e come dispositivo del Monitor SNMP (stesso "
                  "IP o stesso asset), è una sola: compare e conta una volta, come MFC, e la scheda del dispositivo "
                  "porta alla scheda MFC. Sonde, firmware e storico delle interrogazioni restano raggiungibili dal "
                  "link «Dettagli tecnici SNMP» sotto il pannello della stampante. Non si cancella nulla."),
        ],
    },
    {
        "id": "tvcc",
        "titolo": "Videosorveglianza (NVR e telecamere TVT)",
        "blocchi": [
            ("p", "NVR e telecamere IP si aggiungono con «+ Nuovo» → «+ Apparato» "
                  "con tipo «TVCC - Videoregistratore (NVR)» o «TVCC - Telecamera IP», e si collegano "
                  "all'asset di videosorveglianza già censito. Il portale legge solo dati tecnici via SNMP: "
                  "nessuna immagine e nessun flusso video."),
            ("def", [
                ("Profilo «TVT NVR (videoregistratore)»", "velocità e stato delle due schede di rete (eth0, "
                                                          "eth1): una scheda non attiva mette l'NVR in "
                                                          "«Attenzione». Modello e firmware compaiono nella "
                                                          "scheda del dispositivo. L'NVR non espone via SNMP "
                                                          "MAC, dischi né risorse."),
                ("Profilo «TVT telecamera IP»", "solo controllo di raggiungibilità: «Operativo» se la "
                                                "telecamera risponde, «Errore» se non risponde. Le telecamere "
                                                "non espongono interfacce, MAC né risorse."),
                ("Attivare SNMP", "sulla telecamera va abilitato SNMP (v2c con community di sola lettura, "
                                  "oppure v3) dalla sua pagina web. La community di scrittura non serve: "
                                  "il portale legge e basta."),
            ]),
            ("p", "Nel Monitor SNMP il pulsante «Videosorveglianza» (o la categoria «Videosorveglianza (NVR e "
                  "telecamere)» nel filtro) mostra solo NVR e telecamere, con l'asset collegato."),
            ("p", "In «Configurazione» → «Impostazioni», riquadro «Videosorveglianza» (link «Impostazioni SNMP "
                  "e TVCC» nel Monitor SNMP) si impostano: «TVCC - Intervallo NVR (minuti)» (predefinito 5), «TVCC - "
                  "Intervallo telecamere (minuti)» (predefinito 30) e «TVCC - Storico rilevazioni (giorni)» "
                  "(predefinito 14). Ogni notte le rilevazioni TVCC più vecchie vengono cancellate."),
            ("p", "Nello stesso riquadro «Altri apparati - Storico rilevazioni (giorni)» vale per stampanti, switch, "
                  "server e gli altri apparati non TVCC: di serie è 0 = conserva tutto. Con un numero (minimo 60, "
                  "servono alle stime dei toner) ogni notte le rilevazioni più vecchie vengono cancellate; l'ultima "
                  "di ogni apparato resta sempre. Se lo storico è lungo la pulizia prosegue nelle notti successive."),
            ("p", "Contatori e consumabili di una stampante si salvano solo quando cambiano: nello «Storico contatori "
                  "e consumabili» le interrogazioni uguali alla successiva dello stesso giorno compaiono come "
                  "«Invariati: uguali alla lettura successiva»."),
            ("p", "Nella lista asset un pallino accanto al nome riassume lo stato SNMP dei dispositivi "
                  "collegati: verde «Operativo», giallo «Attenzione», rosso «Errore» (non risponde), grigio "
                  "«Mai interrogato»; con più dispositivi vince il peggiore. Passando il mouse si vede il "
                  "dettaglio. Il pallino si vede solo con accesso al Monitor SNMP."),
            ("p", "Nella scheda dell'asset, tab «Monitoraggio», compaiono stato, ultimo controllo, da quanti "
                  "giorni è acceso (non per le telecamere: il loro dato riguarda il servizio SNMP) e gli "
                  "ultimi valori letti, con lo stesso riquadro degli asset IT e gli stessi permessi del Monitor "
                  "SNMP. Il MAC letto è confrontato con quelli dei punti rete dell'asset: «= punto rete», "
                  "«diverso dal punto rete» oppure «non nei punti rete». Il monitoraggio non modifica mai i dati "
                  "dell'asset da solo."),
        ],
    },
    {
        "id": "licenze",
        "titolo": "Licenze e software degli apparati",
        "blocchi": [
            ("p", "Le licenze stanno nel modulo Asset («Licenze software»): la Centrale e le schede le leggono "
                  "dall'asset collegato all'MFC o al dispositivo SNMP, senza duplicarle."),
            ("ul", [
                "Indicatore «Licenze degli apparati»: licenze scadute e in scadenza (entro 30 giorni) degli asset "
                "collegati ad apparati attivi, più il numero di apparati senza asset. Apre l'elenco licenze filtrato.",
                "Nella scheda MFC e dispositivo, riquadro «Asset collegato»: nome, tipo, seriale e codice "
                "dell'asset, numero di licenze e di software rilevati dall'inventario del SOC, poi ogni licenza "
                "con scadenza, giorni mancanti (o trascorsi) e stato (valida, in scadenza, scaduta, disattiva). "
                "Pulsanti «Gestisci licenze» e «Apri scheda asset». Se negli ultimi 12 mesi sull'asset ci sono "
                "importi registrati (rinnovi licenze, interventi chiusi, adempimenti) compare il totale con il link "
                "«dettaglio» al riquadro «Costi registrati» della scheda asset.",
                "Apparato senza asset: se il portale trova un solo asset con la stessa matricola/seriale o lo stesso "
                "IP lo propone («Asset trovato per seriale», «per indirizzo IP», …) e chi gestisce il modulo lo collega "
                "con «Collega» (registrato nell'audit). Con «Scegli un altro», o se non c'è una proposta univoca, "
                "«Collega un asset esistente» apre la modifica dell'apparato. Se l'apparato non è nel registro, "
                "«Crea l'asset» (vedi «Asset e SOC»).",
                "Una MFC creata da «Modulo completo» viene collegata da sola all'asset con la stessa matricola o "
                "lo stesso IP, se ce n'è uno solo (come i dispositivi SNMP).",
            ]),
        ],
    },
    {
        "id": "asset-soc",
        "titolo": "Asset e SOC: un apparato, tre moduli",
        "blocchi": [
            ("p", "Ogni apparato di Contatori IT è anche un asset dell'inventario e, per il SOC, un host con un "
                  "firmware. Le tre viste restano allineate così:"),
            ("def", [
                ("Crea l'asset", "nella scheda di un apparato senza asset (permesso di gestione Contatori e di "
                                 "creazione asset): crea l'asset con nome, tipo, produttore, modello, matricola e "
                                 "posizione letti dall'apparato, un punto rete «Monitoraggio SNMP» con il suo IP, "
                                 "e lo collega. Chiede conferma ed è registrato nello storico dell'asset. Reparto, "
                                 "data d'acquisto e assegnazione si completano dalla scheda asset."),
                ("Apparato e inventario non dicono la stessa cosa", "riquadro nella scheda dell'apparato, sotto "
                                 "«Asset collegato»: numero di serie, produttore, modello, IP e posizione "
                                 "diversi tra apparato e asset, e lo stato di vita («Asset dismesso» con apparato "
                                 "ancora interrogato). Niente si sovrascrive da solo: «Allinea dalla scheda asset» "
                                 "porta alla tabella «Il monitoraggio ha dati diversi dall'anagrafica», dove "
                                 "«Applica» copia il valore (per l'IP aggiunge un punto rete)."),
                ("Sicurezza", "riquadro nella scheda dell'apparato. Per tutti: «SNMPv1/v2c senza cifratura» "
                              "(community in chiaro sulla rete) e «Community predefinita» (public, private…: "
                              "cambiala). Solo con accesso al SOC: il firmware nell'inventario del SOC, le CVE che "
                              "lo impattano (KEV = sfruttata attivamente) e l'alert aperto se l'apparato non "
                              "risponde. Il valore della community non viene mai mostrato."),
                ("Apparati di rete che cadono", "firewall, switch (Rete), server, storage, UPS e "
                                                "videoregistratori che non rispondono per 2 controlli di fila "
                                                "(circa 10 minuti) aprono un alert nel SOC, uno per apparato; "
                                                "l'alert si chiude da solo alla prima risposta. Stampanti, "
                                                "telecamere, lettori e sensori no. Il numero di controlli e "
                                                "l'interruttore sono nel SOC: «Impostazioni» → «Apparati di "
                                                "rete (Contatori IT)»."),
                ("Firmware sempre coerente", "disattivando, eliminando o cambiando IP a un dispositivo, il suo "
                                             "firmware nell'inventario del SOC diventa «non più rilevato»; "
                                             "collegandolo a un asset, firmware e CVE passano subito su "
                                             "quell'asset."),
                ("Centrale, blocco «Asset e SOC»", "apparati di rete non raggiungibili (alert SOC aperti), "
                                                   "apparati con firmware vulnerabile (solo con accesso al SOC), "
                                                   "apparati su asset dismessi e apparati senza asset (telecamere "
                                                   "escluse), con «Riconcilia» verso la riconciliazione IT del "
                                                   "modulo Asset."),
            ]),
            ("p", "Nel SOC, pagina «Vulnerabilità», «Host più esposti»: un host che è un apparato di Contatori IT "
                  "mostra il nome dell'apparato e apre la sua scheda."),
        ],
    },
    {
        "id": "firmware",
        "titolo": "Firmware dei dispositivi SNMP",
        "blocchi": [
            ("p", "A ogni interrogazione riuscita il portale legge la versione firmware: prima da una sonda di testo "
                  "il cui nome contiene «Firmware» (es. preset Kyocera, HPE iLO), altrimenti dal sysDescr "
                  "(«Version 15.2(4)E10», «Firmware 2.5.1»)."),
            ("ul", [
                "Nella scheda del dispositivo, riga «Firmware» in «Identità SNMP»: versione, fonte e data di lettura; "
                "con più versioni viste, l'elenco «N versioni viste» con le date di inizio e fine.",
                "Il firmware compare anche nel tab «Monitoraggio» della scheda asset collegata.",
                "Se il dispositivo ha produttore e modello, il firmware entra nell'inventario software del SOC "
                "come «<modello> firmware» (fonte «Firmware da monitoraggio SNMP»): il SOC lo confronta con le CVE "
                "come il software dei PC. Una versione nuova sostituisce la precedente.",
                "Le MFC del modulo (letture contatori) non leggono il sysDescr: per il firmware di una stampante "
                "aggiungila anche in Monitor SNMP.",
            ]),
        ],
    },
    {
        "id": "porte-switch",
        "titolo": "Chi è collegato alle porte degli switch",
        "blocchi": [
            ("p", "Ogni notte alle 05:30 il portale legge (solo lettura) la tabella MAC degli apparati di categoria «Rete» "
                  "attivi e raggiungibili: su quale porta e VLAN sta ogni MAC."),
            ("ul", [
                "Nella scheda dello switch, riquadro «Chi è collegato alle porte»: porta, VLAN, MAC e l'asset riconosciuto. "
                "Si mostrano solo le porte con al massimo 3 MAC: quelle con più MAC portano ad altri switch o access point.",
                "Nella scheda asset di un PC, la riga «Visto da» ha la voce «Rete» con switch e porta.",
                "Il MAC del PC arriva da Intune, da WatchGuard o dal punto rete dichiarato dell'asset: un MAC sconosciuto resta «non riconosciuto».",
                "Si legge dal Q-BRIDGE-MIB o, se l'apparato non lo espone, dal BRIDGE-MIB. Gli switch Cisco con tabella separata per VLAN "
                "(community@vlan) non sono coperti.",
                "Interruttore nel SOC: «Impostazioni» → «Apparati di rete» → «Leggi la tabella MAC degli switch».",
                "Se una lettura non arriva in fondo (lo switch smette di rispondere) l'esito dice «lettura parziale» e "
                "restano le porte della lettura precedente: niente viene cancellato. Gli switch che non entrano nel "
                "tempo della lettura (90 secondi) sono «rimandati al prossimo giro» e passano per primi la volta dopo.",
            ]),
        ],
    },
    {
        "id": "nuovo-apparato",
        "titolo": "Aggiungere un apparato (MFC o dispositivo SNMP)",
        "blocchi": [
            ("p", "Un solo percorso guidato per stampanti MFC e dispositivi SNMP: «+ Nuovo» → «+ Apparato» "
                  "(anche «+ Nuova MFC» in Stampanti MFC, «+ Apparato» nel Monitor SNMP e «Aggiungi» nei "
                  "risultati del Discovery, che precompilano i dati). Dalla scheda di un asset IT senza "
                  "monitoraggio, il pulsante «Monitora via SNMP» apre il wizard con l'asset già scelto e il "
                  "tipo proposto (stampante → MFC, server, firewall, TVCC). Quattro passi:"),
            ("def", [
                ("1 · Apparato", "«Asset collegato (registro HUB)»: se l'apparato è già nel registro sceglilo, "
                                 "i campi lasciati vuoti prendono nome, matricola, modello, reparto e IP "
                                 "dall'asset. «Tipo di apparato»: «Stampante MFC a contratto (contatori e "
                                 "fattura)» chiede anche contratto e fornitore e la matricola è obbligatoria; "
                                 "gli altri tipi (rete, UPS, TVCC…) vanno nel Monitor SNMP."),
                ("2 · Connessione", "indirizzo, porta, «Versione SNMP» e credenziali nella stessa pagina. "
                                    "Con v1/v2c: una credenziale del catalogo o una nuova community. Con SNMPv3 "
                                    "la community sparisce e compare il riquadro «Credenziali SNMPv3»."),
                ("3 · Verifica", "un solo pulsante «Verifica»: legge identità, riconosce il modello e legge "
                                 "i valori (per le MFC i quattro contatori). «Modello (profilo SNMP)» si può "
                                 "scegliere qui; vuoto = riconosciuto dalla verifica. Una MFC prosegue solo "
                                 "con i quattro contatori letti e numerici. Un profilo specifico (es. "
                                 "Fortinet, APC) imposta anche il tipo di apparato; un profilo generico "
                                 "lascia il tipo scelto al passo 1."),
                ("4 · Riepilogo", "controlla e «Conferma e crea». Se non hai scelto un asset e il registro "
                                  "ne ha uno con la stessa matricola o lo stesso IP, il portale lo propone: "
                                  "«Collega questo asset»."),
            ]),
            ("p", "Un dispositivo (non una MFC) si può salvare come bozza «non verificata» dal passo "
                  "«Connessione» in poi: viene verificato alla prima lettura SNMP riuscita."),
        ],
    },
    {
        "id": "snmpv3",
        "titolo": "SNMPv3 e verifica",
        "blocchi": [
            ("p", "Con «SNMPv3 (utente e chiavi)» al passo «Connessione» si compilano solo "
                  "«SNMPv3 - utente», «SNMPv3 - autenticazione» (SHA o MD5) con la sua chiave e «SNMPv3 - "
                  "cifratura» (AES o DES) con la sua chiave, oppure una credenziale v3 del catalogo. "
                  "La community non serve. Il portale supporta AES-128 e DES, SHA-1 e MD5: "
                  "AES-192/256 e SHA-224/256/384/512 non sono supportati."),
            ("p", "Se la verifica va in timeout con SNMPv3, il portale invia all'apparato una richiesta di "
                  "identificazione senza credenziali e mostra il codice giusto:"),
            ("def", [
                ("SNMP-009 · apparato raggiungibile, credenziali scartate", "la rete funziona: l'apparato "
                 "risponde a SNMPv3 (si vede il suo engine ID) ma ignora la lettura. Quasi sempre è la "
                 "cifratura: protocollo diverso (AES/DES, oppure AES-192/256 sull'apparato) o chiave di "
                 "cifratura errata. Ricontrolla l'utente sull'apparato e reinserisci tutte le chiavi."),
                ("SNMP-010 · nessuna risposta SNMPv3", "l'apparato non risponde nemmeno all'identificazione: "
                 "spento, IP errato, SNMPv3 non attivo, firewall o VLAN che bloccano UDP 161 dal server del "
                 "portale, oppure l'apparato accetta solo gestori autorizzati."),
                ("SNMP-004 · credenziali SNMPv3 rifiutate", "l'apparato risponde con un errore esplicito: "
                 "utente sconosciuto o chiave/protocollo di autenticazione errati."),
            ]),
        ],
    },
    {
        "id": "tabelle",
        "titolo": "Tabelle: anteprima, raggruppa e azioni su più righe",
        "blocchi": [
            ("p", "Un clic su una riga di Stampanti MFC, Monitor SNMP, Consumabili o «Parco MFC» della Centrale apre "
                  "il pannello laterale: stato SNMP, ultima lettura, consumabili con la percentuale, avvisi aperti, "
                  "asset collegato e «Apri la scheda MFC» (o «Apri la scheda del dispositivo»). Le frecce ← → passano "
                  "alla riga prima o dopo, Esc chiude. Ctrl+clic sul nome apre direttamente la scheda."),
            ("p", "«Raggruppa ▾» sopra le tabelle divide le righe per valore di una colonna (stato, contratto, fonte…)."),
            ("ul", [
                "Le caselle a sinistra selezionano le righe; quella in testata le seleziona tutte (solo le visibili), "
                "Maiusc+clic seleziona un intervallo. All'apertura nessuna riga è spuntata; i pulsanti compaiono quando "
                "c'è una selezione, accanto a «N selezionate».",
                "Consumabili: «Leggi ora le selezionate» mette in coda la lettura di quelle MFC (serve «Contatori - "
                "Gestione»); «Prepara richiesta ordine» scarica un CSV con modello, matricola, MFC, consumabile, livello %, "
                "giorni stimati e «Sotto soglia»: per ogni MFC i consumabili al 15% o meno, altrimenti il più basso.",
                "Stampanti MFC: la casella c'è solo sulle MFC senza asset; «Collega gli asset proposti» mostra prima gli "
                "abbinamenti (asset trovato per seriale o IP, «nessuna proposta», «già collegata») e collega solo con "
                "«Conferma i collegamenti», e solo se la proposta non è cambiata nel frattempo.",
                "Letture da confermare: spunta le letture e premi «Conferma le letture selezionate».",
                "Gestisci letture: le righe arrivano a pagine da 100 e si caricano scorrendo; «Elimina selezionate» "
                "chiede conferma.",
                "Discovery: sulle righe «IP diverso» «Correggi gli IP selezionati» scrive su ogni MFC l'IP trovato in rete, "
                "come «Correggi IP» di riga; entrambe restano nel log con l'IP di prima e quello nuovo.",
            ]),
        ],
    },
    {
        "id": "permessi",
        "titolo": "Chi può fare cosa",
        "blocchi": [
            ("def", [
                ("Consultare la riconciliazione", "permesso «Contatori - Consultazione»."),
                ("Caricare, modificare ed eliminare fatture e letture", "permesso «Contatori - Gestione»."),
                ("Impostazioni, profili, discovery, nuovi apparati", "permesso «Contatori - Gestione»."),
                ("Interrogare subito un dispositivo o tutti, «Prova SNMP» e «Test», segnare un calo come spiegato",
                 "permesso «Contatori - Gestione»."),
                ("«Scarica Excel»", "lo stesso permesso della pagina (Gestisci letture: «Contatori - Gestione»)."),
                ("«Apri ticket»", "permesso di aprire ticket IT nel modulo Ticket."),
                ("«Leggi ora le selezionate», «Collega gli asset proposti», «Correggi gli IP selezionati»",
                 "permesso «Contatori - Gestione»; «Prepara richiesta ordine» e il pannello di anteprima con la "
                 "consultazione."),
                ("Creare l'asset da un apparato", "permesso «Contatori - Gestione» e permesso di creazione nel "
                                                  "modulo Asset."),
                ("Vedere CVE, firmware nel SOC e alert", "accesso al Security Center (SOC)."),
            ]),
        ],
    },
]
