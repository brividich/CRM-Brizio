# Prompt per Claude Code — Analisi e Remediation Gestionale (Anagrafica / DPI / Asset / Mod.133)

## Contesto

Sei all'interno del repository del gestionale aziendale (moduli Anagrafica, DPI, Asset, Gestione Specifiche). Di seguito trovi un elenco di bug, criticità e richieste di modifica raccolte dagli utenti/dal team. Il tuo compito NON è modificare subito il codice, ma:

1. Analizzare il codice esistente per ogni punto (file, componenti, modelli dati, query, UI coinvolte).
2. Individuare la causa (per i bug) o il punto di intervento (per le nuove feature).
3. Proporre una remediation concreta, con eventuali alternative, impatti su DB/schema/API, e stima di complessità (S/M/L).
4. Solo dopo mia conferma esplicita su ciascun punto, procedere con l'implementazione.

Per i punti che lo richiedono esplicitamente (segnalati sotto), effettua anche una ricerca comparativa sul web su standard/prassi di settore prima di proporre la soluzione.

Al termine dell'analisi, produci un documento riepilogativo (`remediation-plan.md`) con: elenco dei punti, causa/analisi, proposta, complessità stimata, priorità suggerita, dipendenze tra punti (es. punti che vanno fatti in un certo ordine perché toccano lo stesso modello dati).

---

## 1. ANAGRAFICA

**1.1 Bug filtro visite mediche in "Nuova sessione"**
Nel flusso "+ Nuova sessione", cambiando la tipologia di visita, la lista/ricerca sottostante non si riaggiorna. Inoltre i filtri della lista non funzionano affatto. Analizza il componente di selezione tipologia e la lista collegata: probabile problema di stato non reattivo (mancato re-fetch/re-render al cambio filtro) o di query dei filtri non applicata lato backend/frontend.

**1.2 Nome dipendente al posto dell'ID nelle tabelle**
In tutte le tabelle del gestionale dove oggi compare l'ID dipendente, sostituire con nome e cognome (join/lookup anagrafica). Mappare tutte le tabelle coinvolte, non solo quelle più visibili.

**1.3 Ex dipendenti nello scadenziario**
Gli ex dipendenti (cessati) non devono comparire nello scadenziario. Verificare la query dello scadenziario: probabilmente manca il filtro sullo stato/flag "attivo" del dipendente.

**1.4 Anagrafica/dipendenti/nuovo — ristrutturazione campi**
- Aggiungere campo "area aziendale" accanto a "reparto".
- Separare il concetto di mansione: introdurre "mansione lavorativa" e "mansione di rischio", con la mansione di rischio collegata/derivata dalla mansione lavorativa.
- Aggiungere campo "ruolo".
- Rimuovere dalla lista (solo a livello di visualizzazione/selezione, non necessariamente dal DB) le voci "ruoli operativi" e "ruoli operativi di sicurezza".
Valuta impatto sul modello dati (nuove tabelle/relazioni mansione-lavorativa ↔ mansione-di-rischio) e su eventuali dipendenze già esistenti (es. DPI, skill matrix — vedi punti 1.9, 1.12, 2.1).

**1.5 Visite mediche inserite da profilo utente**
Se una visita medica viene inserita direttamente dal profilo del dipendente (fuori dal flusso "sessione"), deve comunque alimentare lo scadenziario. Verificare se esiste un doppio percorso di inserimento con logiche disallineate.

**1.6 Formazione — colonna data sessione/corso in tabella**
Nella tabella formazione, aggiungere/mostrare la data della sessione/corso.

**1.7 Codice corso automatico e incrementale**
Il codice corso deve essere generato automaticamente, incrementale, nel formato `<codice corso>-<N>`. Progetta la logica di generazione (gestione concorrenza, univocità, riuso in caso di eliminazioni).

**1.8 Processi qualificati — selezione multiutente**
Il campo "processi qualificati" deve permettere la scelta di più utenti contemporaneamente (attualmente presumibilmente single-select).

**1.9 Collegamento mansione di rischio ↔ dipendente/mansione lavorativa (a cascata)**
Prevedere che una mansione di rischio possa essere collegata:
- direttamente a un singolo dipendente, oppure
- a una o più mansioni lavorative, in modo che tutti i dipendenti associati a quella mansione lavorativa ereditino automaticamente la mansione di rischio (collegamento "a cascata").
Questo è strutturalmente collegato al punto 1.4: valutare insieme il modello dati.

**1.10 Anagrafica/ratei — filtri con operatori**
Nella tabella ratei, aggiungere filtri con operatori di confronto (`<`, `>`, `=`), non solo filtri di uguaglianza/testo.

**1.11 Anagrafica/dipendenti/assenze — KPI annuali**
Nella sezione "assenze" del dipendente, aggiungere KPI annuali con conteggio per tipologia di richiesta assenza (es. ferie, malattia, permesso, ecc.).

**1.12 Skill matrix — regola di avanzamento I → L e contatore abilitati**
- Livelli: I = formazione, L = intermedio. Per passare da I a L il dipendente deve aver concluso un corso specifico: serve un meccanismo di blocco/validazione che impedisca l'avanzamento manuale senza il corso completato. Proponi come implementarlo (es. stato derivato/calcolato vs. campo editabile con validazione, log delle eccezioni se un responsabile forza il passaggio).
- Aggiungere un contatore sopra ogni "macchina" (colonna/competenza) nella skill matrix con il numero di dipendenti abilitati su quella macchina.

**1.13 Sezione "verifica copertura minima" (ISO 9100)**
Prevedere una nuova sezione che verifichi la copertura minima di personale qualificato richiesta dalla certificazione ISO 9100 (es. minimo N persone abilitate per ruolo/macchina/processo critico). Definire da dove derivano le soglie minime (configurabili per certificazione).

**1.14 Mod.128 — requisiti multipli per qualifica**
Per ogni qualifica, prevedere più requisiti (es. audit, corsi, altro), non un requisito singolo. Prima di proporre lo schema, fai una ricerca comparativa sul web su come vengono tipicamente gestiti i requisiti di qualifica multipli in ambito aeronautico/MRO (Part 145) e qualità (ISO 9100), per allinearti alle prassi di settore.

**1.15 Matricola — rimozione zeri superflui**
Rimuovere gli zeri superflui (padding) nella visualizzazione/formattazione della matricola dipendente.

---

## 2. DPI

**2.1 Disponibilità DPI filtrata per mansione di rischio**
In fase di richiesta DPI, mostrare come disponibili solo i DPI associati alla mansione di rischio del dipendente richiedente (collegato ai punti 1.4 e 1.9: dipende da come viene modellata la mansione di rischio).

---

## 3. ASSET

**3.1 Tag PART145 — stile**
Il tag "PART145" deve avere sfondo blu e testo bianco.

**3.2 Data acquisto + data fabbricazione**
Verificare quali campi data esistono già sull'asset e quali mancano; aggiungere "data acquisto" e "data fabbricazione" se non presenti.

**3.3 N. Interno progressivo**
Il numero interno asset deve essere progressivo. Proponi la logica (partire dall'ultimo numero assegnato e incrementare), gestendo eventuali edge case (eliminazioni, importazioni massive, concorrenza).

**3.4 Rinominare "storico interventi" in "interventi straordinari"**
Rinominare l'etichetta/sezione, verificando se il cambio di nome implica anche una modifica di significato/filtro dei dati mostrati o è puramente testuale.

---

## 4. GESTIONE SPECIFICHE — MOD.133

**4.1 Più documenti impattanti sulla stessa riga**
Attualmente probabilmente un solo documento impattante per riga: consentire di associarne più di uno sulla stessa riga.

**4.2 Registro OFI centralizzato**
Prevedere un registro OFI (Opportunity For Improvement) unico, dove confluiscono anche le OFI generate da altri moduli. Ogni task del registro deve avere: un "proprietario", un "owner di processo", una priorità, e un reminder collegato alla scadenza. Proponi schema dati e UI, e come agganciare le OFI provenienti da altri moduli (evento comune, tabella centralizzata con riferimento al modulo di origine).

---

## Note trasversali per l'analisi

- Diversi punti (1.4, 1.9, 2.1) sono collegati tra loro tramite il nuovo concetto di "mansione di rischio": trattali come un'unica epica di modello dati, non come fix indipendenti.
- Per ogni bug (1.1, 1.3, 1.5), distingui chiaramente tra causa root e fix minimo vs. eventuale refactor più ampio necessario.
- Segnala se qualche richiesta impatta permessi/ruoli utente o audit trail (rilevante soprattutto per Mod.128, Mod.133, ISO 9100).
