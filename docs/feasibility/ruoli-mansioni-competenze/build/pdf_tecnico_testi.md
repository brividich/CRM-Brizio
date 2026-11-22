<!-- Testi propri del PDF tecnico: tutto il resto è preso da 01_asis.md, 02_tobe_flusso_algoritmo.md e 03_ux.md.
     I rimandi {§01:9.2} vengono tradotti da costruisci_pdf.py nel numero di sezione del PDF. -->

<!-- blocco: sommario -->

**Che cosa chiede la Qualità.** Due atti formali che oggi non esistono: la **Sessione Formativa (SF)**, unico atto
che cambia le competenze di una persona, e la **Richiesta di Aggiornamento Mansione (RAM)**, unico atto che assegna
una mansione. In più: le mansioni potenziali segnalate e mai assegnate in automatico, la scheda MOD.053 generata dai
dati. Dei 34 requisiti ricavati dai due documenti, oggi 2 sono coperti, 21 lo sono in parte, 11 mancano ({§01:4}).

**Che cosa c'è già.** Il modello dati è in gran parte pronto e il motore dei requisiti di sicurezza è già unico,
spiegabile e ricalcolato ogni notte ({§01:3}). Manca il flusso: mansione e livello oggi si scrivono direttamente,
senza richiesta, senza evidenza e senza firma.

**Il riferimento è il sistema di gestione, non i dati del portale.** Ciò che oggi è caricato nel portale per skill
matrix e mansionario è un insieme di caricamenti di prova: i conteggi del capitolo 3 descrivono quell'ambiente e non
vanno usati come punto di partenza ({§01:8}). Il sistema di gestione in vigore ha invece ciò che serve ({§04:0}): la
skill matrix firmata (circa 690 livelli, circa 100 persone, 79 mansioni), la tabella delle competenze per ruolo e
mansione (MOD.053 Rev.4), la definizione dei livelli e le regole di approvazione (MT CN 06 Rev.21). Il confronto ha
corretto tre punti della proposta: a livello L si firma; ogni emissione della skill matrix è approvata da RDD; per i
controlli non distruttivi la sospensione è obbligatoria.

**Che cosa si propone** ({§02:1}).

1. Due atti, due effetti: la SF cambia ciò che la persona sa fare, la RAM ciò che è autorizzata a fare.
2. Il livello è un giudizio, la validità è un calcolo: il livello lo dà il responsabile in una SF e non cambia mai da
   solo; il portale calcola ogni giorno se è ancora valido e **lo segnala, senza bloccare** (modello ibrido, variante
   «segnalazione»: decisione del proprietario; la variante «blocco» resta attivabile con un parametro, {§02:3.3}).
3. Un solo motore, che per ogni persona dice che cosa è richiesto e perché, che cosa possiede, che cosa manca, che
   cosa potrebbe fare in più ({§02:5}).
4. Assegnazione in due passaggi, avviata e poi effettiva: concilia i due documenti della Qualità ({§02:3.4}).
5. Si costruisce sull'esistente: si aggiungono due oggetti di flusso e un calcolo, senza riscrivere.

**Interfaccia.** Prototipo navigabile con dati inventati: 16 pagine costruite, menu dell'Anagrafica riordinato in sei
pilastri, 51 controlli automatici superati ({§03:4}, {§03:10}).

**Tempi.** Quattordici blocchi (B0-B13). Percorso minimo B0-B3: da 7 a 11 settimane di sviluppo; con la RAM da 10 a
15; tutto tranne la rinomina facoltativa: da 18 a 31 settimane ({§02:7.6}). Il calendario reale dipende dal
popolamento del catalogo delle competenze.

**Rischi principali** ({§02:8}). Il catalogo non viene completato; troppa burocrazia per i responsabili; in modalità
segnalazione, una segnalazione ignorata lascia operare chi non ha il requisito, perciò ogni segnalazione ha una presa
in carico con termine.

**Decisioni richieste** ({§T:decisioni}). Le 18 risposte della Qualità; la data di demarcazione e il destino dello
storico; il reparto pilota; chi firma e chi sostituisce; la revisione di MT CN 06 se la nuova richiesta viene adottata.

**Giudizio.** Fattibilità tecnica **alta**. Fattibilità organizzativa **condizionata** al lavoro di contenuto della
Qualità e dei responsabili.

<!-- blocco: natura -->

> **Natura del documento.** Sola analisi: nessun codice, modello, migrazione o dato del portale è stato modificato.
> Ogni proposta che tocca contenuti, relazioni o regole HR resta una **proposta**: la decisione è del proprietario
> del progetto e della Qualità.
>
> **Fonti.** Questo PDF è composto dai tre documenti di analisi (`01_asis.md`, `02_tobe_flusso_algoritmo.md`,
> `03_ux.md`) con lo script `build/costruisci_pdf.py`. Codice di riferimento: ramo `main`, commit `784cbf3ae`
> (21/11/2026); i percorsi sono relativi a `django_app/anagrafica/` salvo diversa indicazione, nella forma
> `file.py:riga`. Dati reali: soli conteggi, letti dalla produzione in sola lettura il 21/11/2026, senza nominativi.
> Esempi e schermate: dati **inventati** (32 persone, 14 mansioni, 30 competenze, data di riferimento 15/03/2027).
>
> **Etichette.** <span class="chip deciso">deciso Tn / G2</span> indica una decisione del proprietario;
> <span class="chip ipotesi">ipotesi Dn</span> indica l'ipotesi adottata in attesa della risposta della Qualità alla
> domanda n del questionario (appendice).

<!-- blocco: galleria -->

Le immagini sono catture del prototipo (`prototipo/prototipo_rmc.html`), prese dallo script
`build/verifica_prototipo.py` con dati inventati. Ogni didascalia riporta la rotta: basta aggiungerla all'indirizzo
del prototipo per aprire la stessa pagina. Tutte le 26 catture sono in `prototipo/png/`.

<!-- blocco: decisioni -->

Le decisioni sono elencate dalla più pesante sul disegno alla più leggera. Dove esiste, è indicata l'ipotesi con cui
l'analisi ha proceduto: se la risposta è diversa, cambia ciò che è scritto nell'ultima colonna.

| # | Decisione | Chi decide | Ipotesi o decisione attuale | Se la risposta è diversa |
| --- | --- | --- | --- | --- |
| 1 | Vocabolario dei livelli e soglia di firma (domanda 1) | Qualità | Valgono le definizioni di MT CN 06: a L si firma. Nel portale la soglia è U | Va allineata la procedura o il portale ({§04:3}) |
| 2 | Il livello può scendere, e con quale atto (domanda 5) | Qualità | Non scende da solo: scende la validità; il livello cambia solo con una SF di revisione | Con la discesa automatica si passa al modello C ({§02:4}) |
| 3 | Segnalare o bloccare | Proprietario, sentita la Direzione | **Deciso: segnalazione.** Il blocco resta attivabile, anche per le sole competenze dei processi qualificati | Nessuna modifica ai dati: è un parametro ({§02:3.3}) |
| 4 | **Data di demarcazione e storico** | Qualità e proprietario | I livelli della skill matrix firmata entrano con una SF di impianto in modalità «pregresso» (ipotesi: gennaio 2027); i dati oggi nel portale sono di prova e non si usano | Vedi sotto: è il dubbio aperto |
| 5 | Chi è in formazione compare in skill matrix (domanda 12) | Qualità | Sì, come mansione «avviata», distinta da «effettiva» | Basta un filtro: il modello non cambia |
| 6 | Chi firma e chi sostituisce RDD e MSO (domanda 14) | Qualità e Direzione | RDD approva, e firma ogni emissione della skill matrix; MSO firma l'esito dell'aggiornamento mansione, ruolo nuovo rispetto a MT CN 06; sostituti e deleghe a termine | Cambia il blocco B7; va chiuso prima di attivare la RAM |
| 7 | Regola del livello sulla mansione (domanda 4) | Qualità | **Deciso dal proprietario:** il più basso fra le competenze bloccanti | Con la media attuale chi è in regola può risultare «in addestramento» ({§02:3.4}) |
| 8 | Reparto pilota per la tappa 0 | Direzione e Qualità | Da scegliere; criterio proposto: mansioni con più persone e processi qualificati | Senza pilota il catalogo non parte |
| 9 | Gli 11 parametri del calcolo | Qualità | Valori proposti in {§02:4.5} | Sono configurazione |
| 10 | Rinomina dei modelli nel codice (B12) | Proprietario | Non ora | Nessun effetto per gli utenti |
| 11 | Revisione di MT CN 06 e dei moduli MOD.053, MOD.040, MOD.187 | Qualità e Direzione | Necessaria se la nuova richiesta viene adottata | {§04:4} |
| 12 | Segnalare o bloccare sui controlli non distruttivi | Qualità | Blocco: lo impone MT CN 65 | {§04:5} |
| 13 | Riordino del menu e stile | Proprietario | Prototipo approvato il 21/11/2026; raccomandato lo stile rinfrescato, da provare sulle pagine dense e sul tema scuro | {§03:10} |

**Il dubbio aperto: linea di demarcazione e «ripescaggio» dal vecchio catalogo.** L'orientamento del proprietario è
tracciare una linea alla data di introduzione (ipotesi: gennaio 2027): da lì in avanti le competenze cambiano solo
con una SF. Resta da decidere con la Qualità che cosa fare dei **corsi svolti prima**. Il catalogo attuale conta 774
corsi, di cui 595 con una sola edizione, nessuna verifica di apprendimento registrata e nessuna valutazione di
efficacia ({§01:11}).

| Opzione | Che cosa comporta | Valutazione dell'analisi |
| --- | --- | --- |
| A. Linea netta | Solo i corsi creati dopo la data alimentano competenze; lo storico resta consultabile ma non produce evidenze | La più semplice e la più difendibile; perde le evidenze di corsi recenti e ancora validi |
| B. Ripescaggio selettivo | La Qualità marca come «formativi» alcuni corsi del vecchio catalogo; le loro edizioni concluse diventano evidenze di tipo C, con la data originale | **Proposta.** Richiede un lavoro di scelta della Qualità, limitato ai corsi con una validità ancora in corso |
| C. Ripescaggio totale | Tutti i corsi storici diventano evidenze | Sconsigliata: il catalogo è un archivio importato, con il «corso» usato come singolo evento |

In tutti e tre i casi i livelli attuali entrano con la SF di impianto: il ripescaggio riguarda le **evidenze**, non i
livelli. La scelta non cambia il modello dati.

<!-- blocco: domande_nota -->

Le stesse domande, riformulate per la Qualità in 18 punti con le risposte possibili e l'ipotesi adottata, sono nel
questionario riportato in appendice ({§T:questionario}). Le sigle Q1-Q17 sono quelle usate nei capitoli 2 e 3.

<!-- blocco: glossario -->

| Termine | Significato in questo documento |
| --- | --- |
| **Ruolo** | La posizione organizzativa della persona (per esempio «Operatore macchina utensile»). Dal ruolo derivano le mansioni proposte |
| **Mansione lavorativa** | Ciò che la persona è formalmente autorizzata a fare: una macchina o un processo. È la colonna della skill matrix |
| **Mansione di rischio** | La mansione ai fini della sicurezza (DVR): determina formazione obbligatoria, visite, DPI. Distinta dalla mansione lavorativa |
| **Competenza** | Ciò che la persona sa fare, valutabile con un livello. La stessa competenza può servire a più mansioni |
| **Livello I / L / U / O** | I in formazione, L intermedio, U autonomo, O esperto o formatore. Il significato operativo è una proposta da validare |
| **Livello valutato** | Il livello attribuito da una persona, in una SF. Non cambia mai da solo |
| **Stato di validità** | Calcolato dal portale: valida, da confermare, in deroga, sospesa, assente |
| **Livello efficace** | Il livello che conta nel calcolo: in modalità segnalazione coincide con quello valutato; in modalità blocco vale «I» se la competenza è sospesa |
| **Profilo della mansione** | L'elenco delle competenze richieste da una mansione, ciascuna con livello atteso e criticità. Ha versioni |
| **Criticità B / I / U** | Bloccante, importante, utile: quanto pesa la mancanza di una competenza sulla mansione |
| **SF, Sessione Formativa** | L'atto, numerato `SF-AAAA-NNNN`, che registra formazione ed evidenze e attribuisce i livelli. È l'unico che cambia le competenze |
| **RAM, Richiesta di Aggiornamento Mansione** | L'atto, numerato `RAM-AAAA-NNNN`, che assegna una mansione. È l'unico che lo fa |
| **P / A / C** | Modalità dell'evidenza: esperienza pregressa, affiancamento, corso. Non sono livelli |
| **Mansione avviata / effettiva** | Avviata: assegnata, la persona è in formazione e non firma. Effettiva: requisiti raggiunti ed esito positivo |
| **Conforme, con riserva, sotto supervisione, non conforme** | Stato della persona rispetto a una mansione, calcolato dal confronto fra profilo e competenze possedute |
| **Mansione potenziale** | Mansione non assegnata i cui requisiti la persona soddisfa in tutto o in buona parte. Segnalata, mai assegnata in automatico |
| **Mancanza (gap)** | Requisito del profilo non raggiunto o non più valido |
| **Deroga** | Autorizzazione a termine su un requisito, con motivo e approvazione |
| **Presa in carico** | La risposta del responsabile a una segnalazione, entro un termine: che cosa intende fare |
| **SF di impianto, linea di demarcazione** | La sessione che porta nel nuovo modello i livelli esistenti come «pregresso», alla data di avvio |
| **MOD.053** | Scheda di formazione personale: nella proposta è un documento generato dai dati, non compilato a mano |
| **MOD.040** | Registro dell'affiancamento, allegato alla SF |
| **MOD.187 (SKM)** | La skill matrix: nella proposta è la fotografia corrente dei livelli |
| **MOD.128** | Mansionario dei processi qualificati |
| **RDD, MSM, MSO, MSA, CAR** | Responsabile della Direzione; Management System Manager, Officer e Assistant (la funzione Qualità); Capo Area o Capo Reparto. Definizioni di MT CN 06 Rev.21 |
| **Motore** | La parte del portale che calcola requisiti, mancanze e stati a partire dai dati |
| **Proiezione** | Tabella calcolata dal motore e riscritta a ogni ricalcolo, usata dalle pagine di elenco (per esempio `TrainingDeadline`) |

I nomi usati nel codice non coincidono con quelli della Qualità: la tabella di corrispondenza è in {§01:2.1}.

<!-- blocco: en9100 -->

Sintesi **non testuale** dei punti della norma, per collegarli alla proposta. È stata verificata sul testo presente
nella cartella del sistema di gestione, che è la bozza prEN 9100:2016: la Qualità può confermarla sull'edizione in
vigore. MT CN 06 Rev.21 riprende gli otto contenuti del punto 7.3 uno per uno.

| Punto | Che cosa chiede, in sintesi | Come risponde la proposta | Dove |
| --- | --- | --- | --- |
| **7.1.2 Persone** | Determinare e rendere disponibili le persone necessarie al sistema di gestione e ai processi | Copertura per mansione e per reparto; avviso quando una mansione resta con meno di due persone operative; mansioni potenziali e simulatore per sapere chi può coprire che cosa | {§02:3.4}, {§02:5} |
| **7.2 Competenza** — determinare la competenza necessaria | Stabilire che cosa deve saper fare chi svolge un lavoro che incide sulla qualità | Profilo della mansione: competenze, livello atteso, criticità; versioni approvate, con anteprima d'impatto | {§02:6.1}, {§02:3.5} |
| **7.2** — persone competenti per istruzione, formazione o esperienza | Dimostrare su che base la persona è competente | Evidenze P (esperienza), A (affiancamento), C (corso) registrate nella SF | {§02:3.2}, {§02:6.3} |
| **7.2** — azioni per acquisire la competenza e valutarne l'efficacia | Colmare le mancanze e verificare che l'azione abbia funzionato | Mancanze → fabbisogni → SF; il livello attribuito a fine sessione è la verifica; conferma periodica | {§02:6.5}, {§02:6.4} |
| **7.2** — informazioni documentate come evidenza | Conservare le prove | SF immodificabili dopo la chiusura; storico; MOD.053 generato dai dati | {§02:6.3} |
| **7.2** — riesame periodico della competenza necessaria (indicazione della EN 9100) | Rivedere nel tempo ciò che è richiesto | Conferma periodica a 6 mesi; revisione del profilo con transitorio | {§02:4.5} |
| **7.3 Consapevolezza** | Le persone conoscono politica, obiettivi, il proprio contributo e le conseguenze del mancato rispetto dei requisiti; per la EN 9100 anche il contributo alla conformità e alla sicurezza del prodotto e il comportamento etico | **Coperto in parte.** La persona vede che cosa può fare, che cosa le manca e che cosa scade («La mia scheda») e riceve gli avvisi. I contenuti di consapevolezza restano corsi del catalogo, tracciabili come requisiti formali di una competenza | {§03:4} |

<!-- blocco: codice -->

File citati nel documento, con le righe richiamate. I percorsi sono relativi a `django_app/anagrafica/` salvo diversa
indicazione; il commit di riferimento è `784cbf3ae`.
