# Ruoli, mansioni e competenze: approfondimenti

Versione 1.1 · 22/11/2026 · dopo le indicazioni del proprietario su dieci punti rimasti aperti. La 1.1 aggiunge la
bozza della Qualità, nel capitolo sul catalogo.

> Fonti: i documenti in vigore del sistema di gestione, letti in sola lettura dalla cartella di rete (256 documenti,
> 2.888 pagine), e il codice del portale. Dalla skill matrix firmata e dal registro timbri sono riportati **solo
> conteggi**: nessun nominativo. Il portale è un gestionale interno **non collegato all'ERP**: non conosce chi ha
> lavorato su quale ordine, e non può impedire una firma su un documento di produzione.

## In breve

1. **Coperture reali.** Su 79 mansioni della skill matrix firmata, nessuna è scoperta e **2 hanno una sola persona
   autonoma**. In 9 c'è un solo formatore, in 1 nessuno.
2. **Firma e timbri.** Il registro timbri è già nel portale, e si sospende da solo quando decade un'abilitazione di
   processo. Manca il legame con la skill matrix, che la procedura chiede.
3. **Mancato esercizio.** Lo dichiara il capo reparto nella conferma semestrale: nessun dato di produzione.
4. **Personale non operativo.** Si tratta con lo stesso catalogo, senza livelli: requisiti posseduti sì o no.
5. **Clienti.** Tutti i piani di qualità rimandano alla procedura Risorse Umane. Chiedono in più scadenze proprie:
   12 mesi, 2 anni, 3 anni, 5 anni.
6. **Carico di valutazione.** Valutare ogni competenza moltiplica il lavoro per 2,6. Con le competenze generiche a
   «sì o no» il carico resta quello di oggi.
7. **Non conformità.** Il legame non può essere automatico né nominativo: si propone di passare dalla mansione e dal
   capo reparto.
8. **Bozza della Qualità.** 253 mansioni e 208 competenze, con la ricetta «sì o no». Compilati 5 fogli su 27: manca
   tutta la produzione. Il 95% dei livelli firmati si carica da solo nella nuova struttura.

---

## 1. Firma e timbri

**Che cosa c'è.** Il MOD.130 non è un modulo di carta: è la schermata di un'applicazione con, per ogni persona,
matricola, reparto, qualifica, firma depositata e timbri con stato e date. Il portale ha già lo stesso registro
(`timbri/models.py:84`): consegna, ritiro, sospensione con data e motivo, collegamento alla persona (`:32`) e,
facoltativo, a un'abilitazione di processo qualificato (`:120`). Quando quell'abilitazione decade, il timbro viene
sospeso da solo e la Qualità è avvisata (`anagrafica/services/mpq_timbri.py:1-12`).

**Che cosa manca.** La procedura chiede due condizioni insieme: timbro valido **e** autorizzazione nella skill matrix
(MT CN 06 §10.2). Il registro oggi conosce solo la prima, più i processi qualificati.

**Il limite.** Senza collegamento all'ERP il portale non può fermare una firma su un ordine di lavoro. Può fare tre
cose: tenere il registro, segnalare, e dire a reparto e Qualità chi può firmare che cosa.

**Proposta.**

| Che cosa | Come |
| --- | --- |
| «Può firmare» | Timbro attivo nel registro **e** mansione effettiva a livello L o superiore |
| Dove si vede | Scheda della persona, matrice, elenco stampabile per reparto |
| Quando una mansione non è più valida | Segnalazione «timbro da verificare» a capo reparto e Qualità; la sospensione resta un atto della Qualità |
| Processi qualificati e controlli non distruttivi | Resta la sospensione automatica che c'è già |

Stima: da S a M, perché si riusa il registro esistente.

## 2. Mancato esercizio: lo dichiara il capo reparto

Decisione del proprietario: non si usano dati di produzione. Nella conferma semestrale, per ogni persona e mansione,
il capo reparto sceglie una di tre risposte.

| Risposta | Effetto |
| --- | --- |
| Confermo | La mansione resta valida per altri sei mesi |
| Non la svolge da più di 12 mesi | La mansione passa a «da confermare»; sui controlli non distruttivi è sospesa, come impone MT CN 65 |
| Livello da rivedere | Si apre una sessione formativa di revisione |

La conferma del capo reparto esiste già nel portale (`anagrafica/services/skillmatrix_refresh.py`): si aggiunge la
seconda risposta. Stima: S. Il rischio «manca la fonte dell'ultimo esercizio» è chiuso.

## 3. Personale non operativo

**Regole in vigore.** Per chi non sta in skill matrix la procedura usa strumenti diversi (MT CN 06 §8.1, §9.6):

| Strumento | A che cosa serve |
| --- | --- |
| Organigramma approvato dalla Direzione (IDOR CN 01 Allegato C) | È la nomina nel ruolo |
| Requisiti minimi per funzione (MT CN 06, Annex 1) | Titolo di studio, provenienza, conoscenze, patenti, abilitazioni |
| Scheda profilo professionale (MOD.039) | Requisiti necessari a confronto con quelli posseduti |
| Nomina incarichi (MOD.188) | Incarichi che non rientrano negli altri strumenti |
| Tutor o responsabile di funzione | Segue la formazione e ne valuta l'efficacia |

La tabella dei moduli MOD.053 e MOD.039 copre già questi ruoli: su 58 ruoli, 38 non sono operativi.

**Proposta.** Stesso catalogo e stesso calcolo, con tre differenze:

| | Operativi | Non operativi |
| --- | --- | --- |
| Scala | Livelli I, L, U, O | Requisito posseduto sì o no, con la prova |
| Atto che assegna | Richiesta di mansione approvata | Organigramma approvato dalla Direzione |
| Chi valuta | Capo reparto | Responsabile di funzione o tutor |

Il portale distingue già ruoli diretti e indiretti (`anagrafica/models.py:409-426`) e registra il titolo di studio
(`:1225`). Da chiedere alla Qualità: se anche per gli indiretti servono livelli. Ipotesi: no.

## 4. Requisiti dei clienti e dei processi

I piani di qualità di Leonardo, MBDA, Rheinmetall, Piaggio e Avio rimandano tutti a MT CN 06 e al MOD.128: **nessun
cliente chiede un modello diverso**. Chiedono però scadenze e prove proprie.

| Fonte | Che cosa chiede | Cadenza |
| --- | --- | --- |
| Avio, parti critiche (PdQ CN_01.23 §8.1) | Formazione su parte critica e sicurezza; esami periodici della vista per il collaudo | Periodica |
| Foratura critica P11TF12 (MT CN 69 §7) | Corso di consapevolezza; elenco del personale abilitato | 12 mesi |
| Part 145 (MO-ID-009.24 §2) | Formazione sulla sicurezza iniziale e ricorrente, con verifica; cartella personale consegnata al cliente, che rilascia la dichiarazione di competenza | 2 anni |
| Controlli non distruttivi (MT CN 65 §3) | Approvazione; verifica annuale; esame della vista da vicino; sospensione dopo 12 mesi senza operare | 5 anni · 1 anno · 1 anno |
| Verifica di pulizia (MOD.128) | Attestato di qualificazione | 3 anni |
| Manifattura digitale Leonardo (DMFGSDP §9) | Formazione minima; elenco degli operatori con licenza | Non indicata |

**Che cosa comporta.** Sono tutti requisiti formali con scadenza, già previsti. Servono due aggiunte: la prova
**rilasciata dal cliente** come tipo di requisito, e una vista **per cliente**: chi è abilitato per quel cliente o
processo.

**Due rilievi.**

- Le procedure citano già il portale come luogo di registrazione: MT CN 69 dice che il personale abilitato è
  «registrato su gestionale interno», il piano Piaggio parla del «gestionale risorse umane».
- Il MOD.128 elenca quattro persone qualificate per la verifica di pulizia; la skill matrix, sulla colonna
  «Cleanliness Check», una sola persona autonoma. Da verificare con la Qualità.

## 5. Carico di valutazione: pregi, difetti, soluzioni

**I numeri.** La skill matrix firmata conta 691 livelli; in media ogni persona ha 6,6 mansioni, al massimo 19. Sui
nove ruoli operativi abbinabili al MOD.053 (452 livelli) il confronto è questo:

| Modo di valutare | Valutazioni | Rispetto a oggi |
| --- | --- | --- |
| Oggi: una lettera per mansione | 452 | 1 |
| Un livello per competenza, valutata una volta per persona | 1.184 | × 2,6 |
| Un livello per competenza e per macchina | 3.476 | × 7,7 |

Due osservazioni decisive. Il 61% delle valutazioni in più viene dalle **competenze generiche** (disegno tecnico,
FOD, procedure interne): quelle specifiche, valutate una volta, sono 458, quante le lettere di oggi. E solo il 28% dei
livelli è I o L: il resto è già autonomo.

**Le soluzioni.**

| | Come funziona | Pregi | Difetti |
| --- | --- | --- | --- |
| A | Un livello per ogni competenza | Massimo dettaglio; ciò che si dimostra su una macchina vale sulle altre | Lavoro × 2,6 |
| B | Generiche a «sì o no», livelli solo sulle specifiche | Carico pari a oggi; resta il riuso fra macchine | Le generiche non hanno gradi |
| C | Il livello resta sulla mansione; le competenze sono una lista di spunte che lo giustifica | Nessuna modifica alla procedura; carico minimo | Niente riuso fra macchine; mansioni potenziali meno precise |
| D | All'avvio chi è U o O si considera coperto; il dettaglio solo per I, L e nuovi ingressi | Avvio leggero: riguarda il 28% dei livelli | Il dettaglio si completa nel tempo |

**Raccomandazione: B a regime, D all'avvio.** La soluzione C è il ripiego se la Qualità preferisce non toccare la
struttura della skill matrix.

**Per renderlo più fruibile**, qualunque sia la scelta: una griglia per reparto, persone per competenze, in una
schermata; conferma semestrale «tutto confermato, salvo…»; valori precompilati dalla skill matrix firmata.

## 6. Copertura per turno

La skill matrix riporta il turno di ogni persona: circa 37 a giornata, 30 al primo turno, 33 al secondo.

| | Mansioni |
| --- | --- |
| Con persone a turno | 75 |
| Con persone autonome in entrambi i turni | 65 |
| Con persone autonome in un solo turno | 9 |
| Senza persone autonome nei due turni, coperte da chi fa giornata | 1 |

I valori per turno sono approssimati: dalla lettura sono rimaste fuori due persone.

**Nel portale.** L'anagrafica non registra il turno della persona. Il turno esiste nella pianificazione delle macchine
(`gestione_carichi_macchina/models.py:431-483`) e come classificazione «un turno o due» della mansione
(`anagrafica/models_skillmatrix.py:316-321`).

**Proposta.** Il turno abituale diventa un dato dell'anagrafica HR, con lo storico. La matrice ha il filtro per turno
e il cruscotto mostra le mansioni scoperte in un turno. Stima: da S a M. Da decidere: chi aggiorna il turno quando
cambia.

## 7. Mansioni con meno di due persone autonome

Dato reale, dai totali della skill matrix firmata del 30/04/2026.

| | Mansioni | Quali |
| --- | --- | --- |
| Nessuna persona autonoma | 0 | — |
| **Una sola persona autonoma** | **2** | Cleanliness Check, Manutenzione |
| Due o più | 77 | — |
| Un solo formatore (livello O) | 9 | AGV3, Affilatura, Mascheratura, Sala taglio, TNZ, STZ, Controllo configurazione finale, Cleanliness Check, Manutenzione |
| Nessun formatore | 1 | Magazzino 02 |

La regola delle due persone autonome (MT CN 06 §8.2.2) è rispettata su 77 mansioni. Il livello O è il 46% dei livelli.

## 8. Non conformità e competenze

**Perché non è un automatismo.**

- Il cartellino di non conformità riporta reparto, macchina e fase, non chi ha lavorato (MT CN 16). Il portale non lo
  sa: non è collegato all'ERP.
- La procedura sulla sicurezza del prodotto vieta di usare le segnalazioni per attribuire colpe (MT CN 21, «just
  culture»). Un legame nominativo farebbe calare le segnalazioni.
- «Manodopera» non vuol dire «competenza»: può essere un'istruzione poco chiara, un metodo, il carico di lavoro.

**Che cosa c'è già.** La procedura fa aggiornare la skill matrix dopo le non conformità riconducibili alla competenza
(MT CN 06 §8.4), e il registro corsi chiede la «verifica di assenza di non conformità nei 6 mesi». Nel portale il
modulo Anomalie ha l'analisi delle cause con la voce «Manodopera» (`anomalie/nc_views.py:39-40`), la causa radice in
testo libero (`anomalie/quality_models.py:85`) e la segnalazione al capo reparto (`:187`).

**Proposta, in tre passi.**

1. **Si collega la mansione, non la persona.** Chi chiude l'analisi, se la causa riguarda la competenza, indica
   mansione e competenza interessate. Nasce un fabbisogno formativo per il reparto.
2. **Decide il capo reparto**: nessuna azione, motivata; un richiamo per il reparto o per alcune persone; la
   revisione della ricetta, se era quella a essere carente. La persona entra solo qui.
3. **La verifica a sei mesi si prepara da sola.** Dopo una sessione formativa il portale conta le non conformità con
   causa «competenza» su quella mansione e propone l'esito alla Qualità, che firma. È una misura del reparto.

**Da studiare con la Qualità.** Chi classifica la causa; se serve una voce «competenza» distinta dentro
«Manodopera»; se vale anche per le segnalazioni del cliente.

## 9. Catalogo completo

La tabella del MOD.053 Rev.4 contiene 58 ruoli, 118 mansioni, 414 competenze di mansione e 319 generiche. Incrociata
con le 79 colonne della skill matrix:

| Esito | Colonne |
| --- | --- |
| Coincidono per nome | 49 |
| Coincidono nella sostanza, con nome o livello diverso | 29 |
| Solo nella skill matrix | 1: Lavaggio condotti |
| Solo nel MOD.053 | 4: DM16, DM17, Smontaggio trasmissioni, Ritocchi verniciatura e trattamenti |

Delle 29, 18 sono controlli di qualità: nella skill matrix sono colonne, nel MOD.053 sono attività di un'unica
mansione. Ci sono poi differenze di scrittura, come «DMC» e «DMG» per la stessa macchina.

### La bozza della Qualità

Ricevuta il 22/11/2026: un elenco di mansioni (versione 9) e una matrice delle competenze per reparto, ancora in
scrittura. È la struttura a cui tendere, e sostituisce la tabella del MOD.053 più che completarla: solo 18 competenze
su 208 hanno lo stesso nome.

| Voce | Bozza | Documenti in vigore |
| --- | --- | --- |
| Mansioni | 253, in 39 reparti e 9 processi | 79 colonne nella skill matrix, 118 nel MOD.053 |
| Mansioni fuori dal processo «Produzione» | 115 | Nessuna nella skill matrix |
| Competenze distinte | 208 | 366 di mansione e 111 generiche nel MOD.053 |
| Mansioni con abilitazione a scadenza | 8 | Non distinte |
| Ricetta (competenze richieste) | «Sì o no», livello richiesto unico: U | Non prevista |

**Che cosa risolve.**

- **Una competenza vale su più macchine.** La mansione dell'operatore è la singola macchina (44 mansioni); le
  competenze sono per famiglia: 20 «piazzature» coprono le 44 macchine. È la risposta di fatto alla domanda 1.
- **Non serve un livello richiesto per ogni competenza.** La matrice dice «sì» o «no», con U come livello richiesto
  per tutte. Cadono le 114 celle «livello richiesto» del catalogo ricavato dal MOD.053.
- **Il personale non operativo c'è già.** Uffici e direzione sono trattati con la stessa struttura; 73 mansioni hanno
  la ricetta compilata, in media 9 competenze ciascuna.
- **Chi approva in ogni reparto.** «Responsabilità del reparto» è una mansione, una per reparto (39): il portale può
  ricavare da lì chi valuta e chi approva.
- **Dove fermare invece di segnalare.** Le 8 mansioni marcate «abilitazione» hanno validità e scadenza: sono il
  perimetro candidato. Oggi la procedura lo impone solo per i liquidi penetranti.
- **Tre tipi di competenza:** trasversale, tecnica, abilitazione.

**Che cosa manca.**

| Punto | Misura |
| --- | --- |
| Fogli della matrice ancora vuoti | 22 su 27: tutta la produzione, 177 mansioni, 3.054 celle |
| Tipo e origine della competenza | Indicati su 45 competenze su 208 |
| Competenze con il controllo numerico «da definire» | 2, in 5 fogli |
| Mansioni diverse fra elenco e matrice | 5: tre solo nell'elenco, due solo nella matrice |
| Foglio dei punti aperti, citato in legenda | Assente; un solo «?» nella matrice |
| Colonne «diretto/indiretto» e «valenza», citate nelle regole | Assenti nella versione 9 |
| Peso della competenza (bloccante, importante, utile) | Non previsto |

Sul peso si propone di seguire la bozza: ogni «sì» è richiesto, senza gradi. Il modello si semplifica e la domanda 8
si chiude.

**Caricare la skill matrix firmata nella nuova struttura.**

| Colonne della skill matrix | Colonne | Livelli firmati |
| --- | --- | --- |
| Stesso nome nella bozza, o rinominate una a una | 73 (68 e 5) | 657: si caricano da soli |
| Divise in più mansioni | 6, che diventano 17 | 34: li ripartisce il capo reparto |

Restano 163 mansioni senza livelli firmati: le 39 responsabilità di reparto e quelle degli uffici. Si assegnano
all'avvio, con una richiesta di mansione o con un caricamento iniziale approvato da RDD. L'abbinamento delle 11
colonne cambiate è una proposta dell'analisi; due voci («Sala taglio», «Magazzino 02») sono le più incerte.

Il file `Catalogo_competenze_completo.xlsx` contiene ora anche la bozza: i fogli «Mansioni bozza», «Competenze bozza»
e «Stato bozza», e nel foglio «Incrocio» dove finisce ogni colonna della skill matrix. Il catalogo del reparto pilota
(`Catalogo_pilota_CN5G.xlsx`) è superato: i fogli veri sono quelli dei reparti CN5GS e CN5GL, 12 mansioni e 192 celle.

## 10. Indicatori per il riesame

Oggi la procedura sugli indicatori ha una sola misura sulla formazione: le ore sulla sicurezza (MT CN 13). Il riesame
della Direzione ha già una voce «piano di formazione del personale» (MOD.062).

| Indicatore | Oggi | Cadenza | Responsabile |
| --- | --- | --- | --- |
| Mansioni con una sola persona autonoma | 2 su 79 | Semestrale | RDD |
| Mansioni con un solo formatore | 9 su 79 | Semestrale | Capi reparto |
| Mansioni senza autonomi in un turno | circa 10 su 75 | Semestrale | OPM |
| Requisiti scaduti o in scadenza a 90 giorni | Da misurare | Mensile | MSM |
| Conferme semestrali completate nei termini | Da misurare | Semestrale | MSM |
| Segnalazioni prese in carico entro il termine | Da misurare | Trimestrale | RDD |
| Mansioni avviate da più di sei mesi | Da misurare | Trimestrale | Capi reparto |
| Sessioni formative con verifica a sei mesi positiva | Da misurare | Semestrale | MSM |
| Ore di formazione per persona, anche per genere | Da misurare | Annuale | HRM |

I primi tre hanno già un valore di partenza, ricavato dalla skill matrix firmata.

---

## Che cosa cambia nella proposta

| Prima | Ora |
| --- | --- |
| Ultimo esercizio da collegare alla produzione | Lo dichiara il capo reparto nella conferma semestrale |
| «Può firmare» calcolato dal solo livello | Livello **e** timbro attivo nel registro |
| Solo personale operativo | Anche non operativo, con requisiti «sì o no» |
| Un livello per ogni competenza | Generiche «sì o no», livelli sulle specifiche; all'avvio dettaglio solo per I e L |
| Non conformità: avviso al capo reparto | Collegamento alla mansione, decisione del capo reparto, verifica a sei mesi proposta dal portale |
| Turno non considerato | Turno abituale in anagrafica HR e copertura per turno |
| Requisiti formali generici | Anche prove rilasciate dal cliente e vista per cliente |
| Catalogo caricato dal MOD.053 | Catalogo caricato dalla bozza della Qualità, quando è completa |
| Livello richiesto e peso per ogni competenza | Ricetta «sì o no», livello richiesto unico U, nessun peso |
| Chi approva deciso con permessi a mano | Ricavato dalla mansione «Responsabilità del reparto» |

## Limiti

- I manuali Part 145 del cliente (469 pagine) sono stati letti solo nelle parti sui subfornitori.
- I conteggi per turno sono approssimati; quelli per mansione vengono dai totali stampati sulla skill matrix.
- Il carico di valutazione è stimato su 452 livelli dei 691, quelli dei ruoli abbinabili per nome al MOD.053.
- Il registro timbri della cartella di rete è alla revisione 1, quello del portale dichiara la revisione 2.
- La bozza della Qualità è in scrittura: i conteggi valgono per i file ricevuti il 22/11/2026.
