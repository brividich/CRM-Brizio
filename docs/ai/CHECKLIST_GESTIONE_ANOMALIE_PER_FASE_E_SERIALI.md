# Piano di avanzamento — evoluzione Gestione anomalie

**Stato:** proposta dettagliata, da rivedere con il reparto Controllo prima dello sviluppo  
**Area:** `django_app/anomalie`  
**Data:** 5 ottobre 2026

## 1. Obiettivo

Rendere possibile gestire una singola anomalia riferita a un OP anche quando il controllo avviene in più fasi e coinvolge più seriali, mantenendo ogni descrizione, allegato e risposta del capocommessa associati ai seriali corretti. Negli elenchi deve inoltre essere immediatamente riconoscibile il collaudo di benestare.

## 2. Comprensione della richiesta

- In apertura della segnalazione deve comparire un pulsante arancione **+ NUOVA SEGNALAZIONE**.
- La fase di controllo/lavorazione deve essere indicata per ogni segnalazione. Lo stesso OP può essere controllato in fasi diverse.
- Le segnalazioni relative allo stesso OP devono potersi ricondurre alla stessa anomalia, così che i controlli in fasi differenti non diventino casi scollegati.
- Una anomalia può comprendere più seriali o gruppi di seriali, aggiungibili con **+ Nuovo seriale**.
- La descrizione dell’anomalia è composta da più voci. Ogni voce specifica uno o più seriali, una descrizione e uno o più allegati.
- Il capocommessa deve rispondere a ogni voce di descrizione, sia nella vista **Anomalie in carico** sia dal flusso e-mail.
- Gli elenchi distinguono visivamente i collaudi di benestare dalle altre segnalazioni.

## 3. Scelte progettuali proposte

Queste sono le scelte su cui baserei l’implementazione; sono evidenziate come proposta perché determinano il significato dei dati e del flusso.

### 3.1 Un’anomalia comune, più segnalazioni per fase

**Proposta:** mantenere un record principale dell’anomalia/NC per l’OP e registrare le singole segnalazioni di controllo come elementi collegati, ciascuno con la propria fase e i propri seriali. Così l’OP resta il riferimento comune, mentre fase e rilievi restano distinguibili.

Il modello attuale contiene già `AnomaliaNC` per raccogliere anomalie riferite a un OP e `AnomaliaSchedaQualita` collegata alla riga legacy. La soluzione dovrà integrarsi con questo impianto e con le automazioni legacy, senza presumere che sia necessario sostituirlo.

**Da confermare:** quando si apre una segnalazione per un OP già presente, l’utente deve poter scegliere tra collegarla all’anomalia aperta e aprire un caso nuovo? La proposta predefinita è collegarla all’anomalia aperta dell’OP, lasciando esplicita la possibilità di creare un nuovo caso quando si tratta di un problema distinto.

### 3.2 Fase registrata su ogni segnalazione

**Proposta:** rendere la fase obbligatoria sulla singola segnalazione, anche se l’OP ha già una o più fasi registrate. La fase non identifica da sola l’anomalia e non deve fondere automaticamente rilievi di fasi diverse.

**Da chiarire:** usare un elenco di fasi configurabile/controllato oppure testo libero? La proposta è riutilizzare il campo e le opzioni già presenti, dopo averne verificato il formato e l’origine.

### 3.3 Seriali e gruppi di seriali

**Proposta:** aggiungere seriali progressivamente tramite **+ Nuovo seriale**, conservando i seriali già inseriti. Un seriale potrà essere selezionato dall’elenco dell’OP oppure digitato manualmente. La pagina indicherà chiaramente quali seriali provengono dall’elenco e quali sono stati inseriti a mano, evitando duplicati evidenti.

Le descrizioni potranno riferirsi a un singolo seriale o a più seriali selezionati (multibox). La selezione non cancellerà né sovrascriverà i seriali già associati ad altre descrizioni.

**Da chiarire:** “gruppo” significa soltanto più seriali aggiunti alla medesima segnalazione, oppure i seriali devono poter essere etichettati in gruppi nominati? La proposta iniziale è un elenco di seriali; gruppi con nome si aggiungono solo se il reparto ne ha un caso d’uso concreto.

### 3.4 Descrizioni come righe indipendenti

**Proposta:** ogni pressione di **+ Nuova descrizione** crea una riga/card autonoma con:

1. seriale o seriali a cui si riferisce;
2. testo della descrizione;
3. caricamento di allegati;
4. risposta del capocommessa e relativo stato (in attesa/risposta ricevuta).

L’anomalia resta una sola: sono le sue voci di descrizione a essere molteplici. L’interfaccia iniziale sarà una sequenza di schede compatte, numerate e leggibili, con rimozione/modifica prima del salvataggio secondo i permessi esistenti. Se le informazioni diventano dense, la vista di dettaglio potrà mostrarle in tabella; il form di inserimento manterrà controlli comodi anche su schermi stretti.

**Allegati:** ogni allegato sarà associato alla propria descrizione, non soltanto all’anomalia generale, per evitare ambiguità in vista ed e-mail.

### 3.5 Benestare visibile negli elenchi

**Proposta:** usare il dato già presente che identifica lo stato/tipo di benestare, se la verifica del codice conferma che rappresenta proprio il “collaudo di benestare” richiesto. Mostrare un badge evidente **Collaudo di benestare** o **Altro controllo** negli elenchi interessati e nel riepilogo.

Non creare un secondo flag indipendente se il significato è già coperto dai dati esistenti: si evitano valori discordanti.

### 3.6 Risposta del capocommessa per descrizione

**Proposta:** in **Anomalie in carico** mostrare ogni descrizione come unità a cui rispondere, con seriali e allegati correlati. Lo stato e il testo della risposta saranno per singola descrizione; il riepilogo dell’anomalia indicherà quante voci sono in attesa e quante hanno ricevuto risposta.

L’e-mail riepilogherà le descrizioni in blocchi numerati con i rispettivi seriali e allegati/link disponibili, e offrirà un campo di risposta distinto per ogni blocco nel flusso di azione via e-mail già esistente, se tecnicamente compatibile. La risposta dovrà tornare associata alla voce corretta e restare consultabile nel portale.

**Da verificare:** il flusso e-mail attuale permette già risposte strutturate per più anomalie; il piano prevede di estenderlo con identificativi stabili per singola descrizione e di preservare audit, token e autorizzazioni già in uso.

## 4. Piano di lavoro con checklist

### Fase A — Ricognizione tecnica e regole di dominio

- [x] Tracciare il flusso reale di apertura, salvataggio, visualizzazione e mail.
- [x] Individuare i campi esistenti per fase, seriale, benestare e collegamento all’NC per OP.
- [x] Verificare la sorgente dei seriali disponibili sull’OP e l’inserimento manuale: il form propone i seriali dell’OP e accetta seriali digitati.
- [x] Mappare i vincoli legacy interessati: la riga SQL resta la chiave canonica; fase e descrizioni vivono nei modelli Django collegati per id. Il salvataggio mantiene il percorso esistente di audit, coda mail e trigger.
- [x] Definire le scelte implementative di questa iterazione nel §7; la conferma d’uso e dei valori di fase resta parte dell’UAT con il reparto.

### Fase B — Modello dati e compatibilità

- [x] Definire la relazione tra caso/NC, segnalazioni per fase e voci di descrizione.
- [x] Definire una voce descrizione con seriali associati, testo, allegati e risposta del capocommessa.
- [x] Preparare migrazioni Django compatibili con lo storico; non eliminare né riscrivere i dati legacy.
- [x] Stabilire compatibilità storico: le righe legacy continuano a mostrare seriale e descrizione; al primo salvataggio viene creata una descrizione associata, senza inventare la fase.
- [x] Verificare staticamente permessi di lettura/scrittura per OP e registrazione audit sui canali portale/e-mail; copertura UAT resta aperta.

### Fase C — Form di inserimento

- [x] Rendere ben visibile il pulsante arancione **+ NUOVA SEGNALAZIONE**.
- [x] Rendere la fase chiara e obbligatoria per la nuova segnalazione.
- [x] Implementare **+ Nuovo seriale** e la selezione multipla dei seriali per ogni descrizione.
- [x] Consentire l’inserimento manuale del seriale.
- [x] Implementare **+ Nuova descrizione** con selezione seriali, testo e allegati per voce.
- [x] Rendere chiara la gerarchia OP → segnalazione per fase → descrizioni numerate.
- [x] Curare selezione seriali per ogni descrizione, stati vuoti degli allegati, errori di validazione e adattamento dei controlli alla larghezza disponibile; compilazione Babel JSX completata.

### Fase D — Elenchi e dettaglio

- [x] Evidenziare collaudo di benestare e altro controllo negli elenchi OP.
- [x] Mostrare la fase nel dettaglio della segnalazione e mantenere il collegamento all’NC dell’OP.
- [x] Mostrare ogni descrizione con seriali, allegati e risposte nel dettaglio.
- [x] Mostrare ogni descrizione nel dettaglio di Gestione anomalie e raccogliere lì una risposta distinta per voce.
- [x] Raccogliere una risposta distinta per descrizione anche nella pagina protetta raggiunta dall’e-mail.

### Fase E — Mail e risposta

- [x] Adattare il contenuto e-mail e la pagina collegata per mostrare le voci con seriali e allegati pertinenti.
- [x] Fornire un canale di risposta distinto per ciascuna descrizione.
- [x] Persistire ciascuna risposta sulla voce corretta, con autore e data/ora, e mostrarla sia nel dettaglio del portale sia nella pagina protetta e-mail.
- [x] Mantenere le protezioni, la scadenza/monouso dei token e il log delle azioni del flusso attuale (verifica statica del codice; resta UAT).
- [x] Verificare la generazione dei corpi e-mail HTML e testo semplice con fase, seriali, descrizioni e allegati; la leggibilità nei client reali resta UAT.

### Fase F — Verifica e rilascio

- [ ] UAT browser: inserimento con un seriale, più seriali selezionati e seriali digitati manualmente.
- [ ] UAT browser: più descrizioni, allegati distinti e risposte indipendenti (test e-mail automatizzato copre associazione risposta e rendering).
- [ ] UAT con dati di reparto: stesso OP in più fasi e collegamento alla NC dell’OP.
- [ ] UAT con ordini reali di collaudo di benestare e altri controlli.
- [ ] UAT su segnalazioni storiche e verifica dei flussi automatici nell’ambiente integrato.
- [x] Eseguire i test mirati mail-action/qualità (45 passati) e `manage.py check` Django.
- [x] Aggiornare README e changelog per il comportamento visibile.
- [x] Preparare nota rilascio/migrazione: applicare 0013 e 0014; eseguire backup DB e storage allegati prima della migrazione. Le nuove tabelle sono additive; rollback di schema richiede conservare un backup se i nuovi dati sono già stati inseriti.

## 5. Esclusione temporanea della Scheda qualità

- [x] Nascondere temporaneamente l’accesso e la presentazione della **Scheda qualità** nell’interfaccia di Gestione anomalie.
- [x] Escludere la Scheda qualità dai nuovi passaggi di inserimento descritti in questo piano.
- [x] Lasciare invariati modello, dati storici e logica backend: la richiesta riguarda il nascondimento temporaneo, non la cancellazione o la disattivazione dei dati.
- [ ] Valutare la riattivazione in una fase futura, fuori dal rilascio corrente.

## 6. Perimetro e cautele

- Il lavoro previsto è nel modulo `django_app/anomalie`. La Scheda qualità resta nascosta nell’interfaccia per questa fase; non si pianifica la rimozione di dati o backend.
- È probabile una modifica al modello dati e una migrazione: la decisione va presa dopo la ricognizione, non prima.
- Il modulo contiene un’interfaccia React, righe legacy SQL e flussi e-mail con token; occorre seguire i percorsi esistenti e mantenere la compatibilità.
- Nessun cambiamento a ACL globali, middleware, navigazione o configurazioni globali è previsto dal piano.
- Nessun dato storico va eliminato. La migrazione deve preservare contenuti, allegati e riferimenti disponibili.

## 7. Decisioni adottate per questa iterazione

1. **Collegamento:** segnalazione sullo stesso OP si collega di default all’NC aperta oppure l’utente sceglie sempre? Scelta implementata: collegamento automatico alla NC aperta dell’OP; dopo la chiusura, il servizio esistente apre una nuova NC per ricaduta.
2. **Fasi:** quali valori validi devono comparire? Scelta implementata: campo fase testuale obbligatorio (max 100 caratteri), così il reparto può usare le denominazioni correnti senza introdurre un secondo catalogo.
3. **Gruppi seriali:** è sufficiente aggiungere seriali all’elenco oppure servono gruppi nominati? Scelta implementata: elenco di seriali semplice, senza gruppi nominati; ogni descrizione ha selezione multipla a caselle e accetta seriali manuali.
4. **Benestare:** qual è la regola che identifica il collaudo di benestare nei dati correnti? Scelta verificata nel codice: `ordini_produzione.stato = Benestare`; gli altri stati sono mostrati come **Altro controllo**.
5. **Risposta e-mail:** il capocommessa deve rispondere direttamente ai campi distinti nella mail oppure la mail deve portare a una pagina protetta con una risposta per voce? Scelta implementata: pagina protetta da token e-mail, con un campo risposta per descrizione; il token conserva scadenza, revoca, monouso per azioni dispositive e audit.
6. **Allegati:** confermare se più allegati per singola descrizione sono ammessi. Scelta implementata: più allegati per descrizione, con validazione formato e limite 20 MB per file.

## 8. Criterio di completamento

La modifica è completa quando il reparto può aprire una segnalazione indicando fase e seriali, articolare l’anomalia in più descrizioni corredate da allegati, distinguere il collaudo di benestare negli elenchi e ricevere dal capocommessa una risposta consultabile per ogni descrizione, mantenendo collegamento all’OP e integrità dello storico.

## Avanzamento implementazione (5 ottobre 2026)

Completati pulsante di apertura, fase obbligatoria per le nuove segnalazioni, collegamento della fase alla NC dell’OP, gruppi aggiuntivi di seriali, selezione multipla a caselle dei seriali per ogni descrizione con inserimento manuale aggiuntivo e allegati distinti con limiti di formato/dimensione, distinzione del collaudo di benestare negli elenchi e risposte separate per descrizione sia nel dettaglio di Gestione anomalie sia nella pagina protetta raggiunta dall’e-mail. Ogni risposta registra autore e data/ora. La Scheda qualità è nascosta nell’interfaccia; modelli e storico restano disponibili.

**Migrazioni da applicare:** `0013_anomaliasegnalazionemeta.py` e `0014_anomaliadescrizione_anomaliadescrizioneallegato.py`. Per le segnalazioni storiche la fase non viene inventata: rimane vuota fino a eventuale compilazione esplicita. La ricognizione e i controlli statici sono stati eseguiti; i test mirati mail-action/qualità passano (45/45). Sono stati verificati anche i controlli token valido/non scaduto/non revocato/non usato e la registrazione delle azioni. Restano da fare UAT dei due canali di risposta, della scadenza/monouso effettivo, del rendering e-mail e della migrazione dati; le caselle di verifica/rilascio restano aperte fino a tale validazione.
