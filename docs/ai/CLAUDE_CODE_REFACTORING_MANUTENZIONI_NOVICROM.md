# Refactoring Modulo Manutenzioni — Specifica Tecnica per Claude Code

## 0. Obiettivo del lavoro

Refactoring sostanziale del modulo manutenzioni del portale Novicrom.

L'obiettivo NON è aggiungere semplicemente nuove funzioni all'architettura esistente, ma semplificare il modello concettuale e operativo.

Il nuovo sistema deve ruotare intorno a quattro concetti principali:

1. **Piano di manutenzione**: il "contenitore" che descrive cosa deve essere fatto.
2. **Applicazione del piano**: specifica su quali asset/gruppi si applica, con quale periodicità e preavviso.
3. **Occorrenza manutentiva**: rappresenta una singola manutenzione dovuta su un singolo asset.
4. **Ordine di Lavoro (OdL)**: organizza una o più occorrenze in una attività operativa, anche massiva e distribuita su più giorni.

Il nuovo modello deve essere semplice da capire per:
- amministratore;
- responsabile manutenzione;
- manutentore interno;
- caporeparto.

La priorità è ridurre la complessità percepita lato UI senza perdere tracciabilità.

---

# 1. Principi architetturali

## 1.1 Concetti visibili all'utente

L'interfaccia deve usare principalmente questi termini:

- **Piano di manutenzione**
- **Asset / Gruppo asset**
- **Scadenza**
- **Ordine di lavoro**
- **Follow-up**
- **Rapporto / allegato**

Evitare nell'interfaccia utente termini tecnici come:
- MaintenanceRule
- Override
- Threshold
- AssetMaintenanceRuleState
- Meter
- Scope type

Questi concetti possono eventualmente esistere internamente, ma non devono costituire il linguaggio principale della UI.

---

# 2. Rimozione completa dei contatori

## 2.1 Requisito

Il sistema Novicrom NON è attualmente in grado di gestire in modo attendibile:

- ore macchina;
- chilometri;
- cicli;
- altri contatori di utilizzo.

Pertanto il refactoring deve eliminare dal flusso manutentivo qualsiasi logica basata su contatori.

## 2.2 Eliminare o rendere non utilizzato

Rimuovere dal nuovo flusso:

- `AssetMeter`
- threshold HOURS
- threshold KM
- threshold CYCLES
- `meter_value_at_close`
- `meter_is_stale`
- snapshot contatori
- logiche di consumo
- warning basati su contatore
- filtri / badge / UI relativi ai contatori

Se alcuni modelli sono referenziati altrove nel progetto, valutare con attenzione prima di eliminarli fisicamente tramite migration.

Se non sono eliminabili subito senza rischi, possono essere inizialmente deprecati, ma:
- non devono più essere usati dal nuovo motore manutenzioni;
- non devono più comparire nell'interfaccia;
- il codice nuovo non deve dipendere da essi.

Non mantenere questa complessità "nel caso serva in futuro".

Se un giorno verranno implementate letture automatiche Industria 4.0, quella parte sarà progettata separatamente.

---

# 3. Nuovo modello concettuale

Il modello logico desiderato è:

```text
MaintenancePlan
      |
      +---- Checklist / attività operative
      |
      +---- MaintenancePlanAssignment
                   |
                   +---- Asset
                   |
                   +---- AssetGroup
                           |
                           v
                  MaintenanceOccurrence
                           |
                           v
                       WorkOrder
                    (anche massivo)
                           |
                  +--------+--------+
                  |                 |
          WorkOrderExecutionDay   FollowUp
                  |
               Allegati
```

Questa struttura è indicativa.

Claude Code deve prima analizzare i modelli esistenti e poi scegliere il modo meno invasivo e più coerente per introdurre questi concetti.

Non è obbligatorio usare esattamente questi nomi di classe se il progetto ha già modelli compatibili.

---

# 4. Piano di manutenzione

## 4.1 Definizione

Il Piano di manutenzione rappresenta **COSA deve essere fatto**.

Esempi:

- Cambio olio
- Pulizia filtri
- Controllo impianto aspirazione
- Verifica estintori
- Taratura annuale
- Rinnovo assicurazione
- Revisione periodica
- Verifica documentale

## 4.2 Campi logici indicativi

Il piano dovrebbe contenere almeno:

```text
id
name / label
description
type
execution_mode
default_supplier (opzionale)
default_assignee (opzionale)
attachment_required
active
created_at
updated_at
```

Checklist e attività operative possono continuare ad essere modellate tramite le strutture già esistenti, se compatibili.

## 4.3 Tipologie

Prevedere almeno:

```text
ORDINARY
ADMINISTRATIVE
INSPECTION
SAFETY
CALIBRATION
```

È accettabile mantenere nomi tecnici diversi se già presenti.

L'importante è distinguere chiaramente almeno:

- manutenzione ordinaria;
- scadenza amministrativa.

---

# 5. Scadenze amministrative integrate nelle manutenzioni

## 5.1 Requisito

Le attuali "scadenze amministrative" non devono più vivere come sistema concettualmente separato.

Devono diventare un tipo di Piano di manutenzione.

Esempi:

- rinnovo assicurazione;
- certificazione;
- documento periodico;
- verifica amministrativa;
- scadenza contrattuale;
- revisione;
- autorizzazione.

## 5.2 Regole speciali

Per i piani di tipo `ADMINISTRATIVE`:

- l'allegato deve essere obbligatorio alla chiusura;
- la periodicità deve essere ancorata alla scadenza teorica;
- l'eventuale ritardo nell'esecuzione NON deve spostare il calendario futuro.

Esempio:

```text
scadenza teorica: 10/09/2026
eseguita:          20/09/2026
periodicità:       1 mese
prossima scadenza: 10/10/2026
```

---

# 6. Applicazione del piano

## 6.1 Definizione

La periodicità NON deve appartenere necessariamente al Piano stesso.

Lo stesso Piano può essere applicato a gruppi differenti con periodicità differenti.

Esempio:

```text
Piano: Cambio olio

Gruppo TORNI
- ogni 30 giorni
- preavviso 10 giorni

Gruppo FRESE
- ogni 90 giorni
- preavviso 20 giorni

Asset DMG-04
- ogni 45 giorni
- preavviso 15 giorni
```

Serve quindi un'entità equivalente a:

```text
MaintenancePlanAssignment
```

che descriva:

> "Questo piano si applica a questi asset con queste regole temporali."

## 6.2 Campi indicativi

```text
plan
target_type
asset nullable
asset_group nullable

recurrence_rule
warning_days

execution_mode override opzionale
supplier override opzionale
assigned_to override opzionale

first_due_date / start_date
active
```

Il dettaglio esatto dei campi va deciso dopo aver analizzato il progetto.

---

# 7. Asset singoli e gruppi di asset

## 7.1 Gruppi

Verificare se `AssetCategory` è sufficiente per rappresentare i gruppi operativi.

Se non lo è, introdurre un concetto più flessibile tipo:

```text
AssetGroup
AssetGroupMembership
```

Esempi di gruppi:

```text
DMG MORI
TORNI
FRESE
MACCHINE REPARTO 1
CENTRI 5 ASSI
ASPIRATORI
```

Un asset potrebbe dover appartenere a più gruppi logici.

## 7.2 Precedenza

Se esiste un'applicazione specifica del Piano sul singolo asset, questa deve avere precedenza rispetto al gruppo.

Regola:

```text
ASSET SPECIFICO > GRUPPO
```

Esempio:

```text
Cambio olio
- TORNI: ogni 90 giorni
- TORNIO03: ogni 60 giorni

Risultato:
- TORNIO01 = 90
- TORNIO02 = 90
- TORNIO03 = 60
```

La UI deve evidenziare:

```text
Periodicità personalizzata
Standard gruppo: 90 giorni
Questo asset: 60 giorni
```

---

# 8. Conflitti tra gruppi

Se un asset appartiene a più gruppi e lo stesso Piano arriva da più gruppi con configurazioni differenti, NON scegliere silenziosamente una regola.

Esempio:

```text
DM01 appartiene a:
- DMG MORI → Cambio olio ogni 90 giorni
- REPARTO 1 → Cambio olio ogni 60 giorni
```

Il sistema deve mostrare un conflitto.

Possibili stati:

```text
CONFLICT
```

o equivalente.

UI:

```text
Conflitto piano

Cambio olio è applicato a DM01 tramite più gruppi
con periodicità differenti.

DMG MORI: 90 giorni
REPARTO 1: 60 giorni

[Personalizza DM01]
```

La creazione di un assignment specifico per DM01 deve risolvere il conflitto.

---

# 9. Motore di periodicità solo temporale

## 9.1 Tipologie supportate

Il motore deve supportare almeno:

- ogni N giorni;
- ogni N settimane;
- ogni N mesi;
- ogni N anni;
- mensile in giorno fisso;
- annuale in data fissa;
- trimestrale;
- semestrale;
- primo lunedì del mese;
- secondo lunedì del mese;
- ultimo giorno specifico del mese se ragionevole;
- in generale ricorrenze calendario sufficientemente flessibili.

Non esporre cron expression all'utente.

## 9.2 Recurrence Rule

Internamente è possibile usare:
- struttura JSON;
- campi normalizzati;
- libreria `dateutil.rrule`;
- altra soluzione coerente con il progetto.

Esempio concettuale:

```json
{
  "frequency": "MONTHLY",
  "interval": 1,
  "weekday": "MONDAY",
  "week_of_month": 1
}
```

che significa:

```text
Primo lunedì di ogni mese
```

La UI deve essere leggibile da un utente non tecnico.

---

# 10. Due diversi ancoraggi della periodicità

Questo è un requisito fondamentale.

## 10.1 FROM_COMPLETION

Usato normalmente dalle manutenzioni ordinarie.

Esempio:

```text
scadenza:          10/09/2026
eseguita:          20/09/2026
periodicità:       1 mese
prossima scadenza: 20/10/2026
```

Formalmente:

```text
next_due = completion_date + recurrence
```

## 10.2 FIXED_CALENDAR

Usato dalle scadenze amministrative.

Esempio:

```text
scadenza:          10/09/2026
eseguita:          20/09/2026
periodicità:       1 mese
prossima scadenza: 10/10/2026
```

Formalmente:

```text
next_due = previous_due + recurrence
```

## 10.3 Default

Impostare preferibilmente:

```text
ORDINARY        -> FROM_COMPLETION
ADMINISTRATIVE  -> FIXED_CALENDAR
```

Il campo può essere modificabile solo da amministratore/responsabile se necessario.

---

# 11. Occorrenza manutentiva

## 11.1 Concetto centrale

Introdurre un modello equivalente a:

```text
MaintenanceOccurrence
```

L'Occurrence rappresenta:

> "Il Piano X deve essere eseguito sull'Asset Y entro la data Z."

Esempio:

```text
Piano:     Cambio olio
Asset:     DMG01
Due date:  20/10/2026
Stato:     DA PIANIFICARE
```

## 11.2 Perché è necessaria

L'Occurrence deve esistere indipendentemente dall'OdL.

Questo consente di:

- creare OdL massivi;
- togliere un asset dall'OdL senza perdere la manutenzione;
- ripianificare;
- dividere il lavoro su più giorni;
- vedere manutenzioni non ancora organizzate;
- evitare duplicazioni;
- mantenere la scadenza originaria;
- agganciare follow-up al singolo asset;
- mantenere storico e audit.

## 11.3 Campi indicativi

```text
plan
assignment
asset

due_date
warning_date

status

workorder nullable

completed_at nullable
completed_by nullable

source_due_date / previous_due_date opzionale
created_at
updated_at
```

Possibili stati:

```text
UPCOMING
DUE
OVERDUE
PLANNED
IN_PROGRESS
DONE
CANCELED
```

Non è obbligatorio memorizzare tutti gli stati se alcuni possono essere derivati.

Preferire stati derivati quando possibile, per evitare ridondanza.

---

# 12. Generazione delle occorrenze

## 12.1 Nuovo paradigma

Il task schedulato NON deve più generare direttamente sempre e soltanto un WorkOrder.

Nuovo flusso:

```text
Scheduler
   |
   v
MaintenanceOccurrence
   |
   v
Raggruppamento / pianificazione
   |
   v
WorkOrder massivo
```

## 12.2 Quando generare l'Occurrence

Quando una manutenzione entra nella finestra di preavviso.

Esempio:

```text
due_date = 20/10/2026
warning_days = 30
warning_date = 20/09/2026
```

Dal 20/09/2026 l'Occurrence deve essere visibile e pianificabile.

## 12.3 Idempotenza

La generazione deve essere idempotente.

Deve esistere un vincolo logico che impedisca di creare due occurrence per:

```text
plan / assignment / asset / due_date
```

o chiave equivalente.

Implementare constraint DB se ragionevole.

## 12.4 Dry run

Conservare o reintrodurre una modalità tipo:

```text
--dry-run
```

per verificare cosa verrebbe creato.

---

# 13. OdL massivi

## 13.1 Requisito

Quando più occurrence compatibili entrano nella finestra di preavviso, devono poter essere raccolte in un unico OdL.

Esempio:

```text
OdL #452
Cambio olio — Ottobre 2026

DMG01
DMG02
DMG03
DMG04
DMG05
```

L'OdL è quindi un contenitore operativo di una o più occurrence.

## 13.2 Raggruppamento

Il sistema può suggerire il raggruppamento per:

- stesso Piano;
- stessa famiglia/gruppo;
- stessa finestra temporale;
- stesso responsabile;
- stesso fornitore;
- stesso execution mode.

Non serve automatizzare tutto in modo aggressivo.

Meglio evitare modifiche silenziose a un OdL già organizzato.

---

# 14. Nuove occurrence dopo creazione OdL

Caso:

```text
OdL 501 esiste già con:
DM01
DM02
DM03
DM04
DM05
```

Il giorno successivo entra nella finestra:

```text
DM06
```

NON aggiungere necessariamente DM06 in automatico all'OdL già pianificato.

Preferire:

```text
1 nuova manutenzione compatibile disponibile
[Aggiungi all'OdL]
```

oppure lasciarla in:

```text
DA PIANIFICARE
```

Questo evita modifiche operative non visibili.

---

# 15. Rimozione di un asset dall'OdL

Requisito fondamentale.

Se l'utente deseleziona un asset da un OdL massivo:

```text
☑ DM01
☑ DM02
☐ DM03
☑ DM04
```

DM03 NON deve risultare:

- completato;
- cancellato;
- ignorato;
- rinviato automaticamente.

Deve semplicemente tornare / restare:

```text
Occurrence DM03 = DA PIANIFICARE
```

e continuare a comparire nelle manutenzioni da fare.

Successivamente sarà possibile:

```text
[Crea nuovo OdL]
```

usando una o più occurrence rimaste fuori.

---

# 16. Distribuzione dell'OdL su più giorni

## 16.1 Obiettivo

Un OdL massivo può essere eseguito in più giornate.

Esempio:

```text
OdL #452 — Cambio olio

20 ottobre
- DMG01
- DMG02
- DMG03

21 ottobre
- DMG04
- DMG05

22 ottobre
- DMG06
- DMG07
```

## 16.2 WorkOrderExecutionDay

Esiste già nel progetto un concetto equivalente a `WorkOrderExecutionDay`.

Valutare se estenderlo invece di creare un modello nuovo.

Dovrebbe poter contenere almeno:

```text
date
workorder
occurrences / assets
notes
attachment(s)
completed_by
completed_at
```

Un giorno di esecuzione deve poter avere uno o più rapportini allegati.

## 16.3 UI

Dentro l'OdL prevedere un'azione tipo:

```text
[Distribuisci su più giorni]
```

Possibile UX:

- selezione asset;
- scelta data;
- sposta;
- drag&drop opzionale;
- raggruppamento per giornata.

---

# 17. Allegati e rapportini

## 17.1 Manutenzione interna

Il rapporto può essere opzionale, salvo diversa configurazione del Piano.

## 17.2 Manutenzione esterna

Flusso desiderato:

```text
DA PROGRAMMARE
      |
      v
APPUNTAMENTO FISSATO
      |
      v
ESEGUITA
      |
      v
RAPPORTO CARICATO
      |
      v
CHIUSA
```

Il sistema deve distinguere "lavoro eseguito" da "pratica amministrativamente completa".

Caso reale:

```text
10 settembre -> intervento eseguito dal fornitore
15 settembre -> arriva il rapportino PDF
```

Tra il 10 e il 15 deve risultare:

```text
Eseguito — rapporto mancante
```

## 17.3 Scadenze amministrative

Per `ADMINISTRATIVE`:

```text
attachment_required = True
```

La chiusura deve essere bloccata senza allegato.

Messaggio UI chiaro:

```text
Per completare questa scadenza è obbligatorio allegare il documento aggiornato.
```

---

# 18. Stato degli OdL

Mantenere per quanto possibile il modello semplice:

```text
OPEN
DONE
CANCELED
```

Gli stati operativi possono continuare ad essere derivati:

```text
unassigned
assigned
in_progress
waiting
```

Aggiungere / mantenere per l'attesa:

```text
waiting_reason
waiting_started_at
expected_resume_date opzionale
```

Calcolare eventualmente:

```text
total_waiting_time
```

per KPI futuri.

---

# 19. Follow-up

## 19.1 Requisito

Se durante una manutenzione emerge un problema, NON creare necessariamente un nuovo ticket separato scollegato.

Creare un Follow-up dell'intervento / occurrence.

Esempio:

```text
OdL Cambio olio

DM01 -> OK
DM02 -> OK
DM03 -> perdita olio rilevata
DM04 -> OK
```

Creare:

```text
Follow-up
Asset: DM03
Origine: OdL #501
Occurrence: Cambio olio DM03
Motivo: perdita olio
```

## 19.2 Collegamenti

Il follow-up dovrebbe poter essere collegato a:

```text
workorder
occurrence
asset
checklist_step opzionale
```

Se il modello attuale usa `follow_up_of`, adattarlo senza perdere storico.

## 19.3 Checklist fuori range / KO

Una checklist con esito negativo o valore fuori range deve poter:

- mostrare chiaramente l'anomalia;
- permettere all'utente di creare un follow-up;
- eventualmente proporre automaticamente il follow-up.

Non creare automaticamente lavori non desiderati senza conferma, salvo regola già prevista dal sistema.

---

# 20. Chiusura manutenzione e avanzamento scadenza

## 20.1 Manutenzione ordinaria

Alla chiusura effettiva dell'Occurrence:

```text
next_due = completion_date + recurrence
```

Esempio:

```text
due 10/09
done 20/09
next 20/10
```

## 20.2 Amministrativa

Alla chiusura:

```text
next_due = theoretical_due + recurrence
```

Esempio:

```text
due 10/09
done 20/09
next 10/10
```

## 20.3 Occurrence massiva

Ogni asset deve avanzare la propria periodicità individualmente.

La chiusura di DM01 NON deve automaticamente chiudere DM02.

Un OdL massivo può quindi essere:

```text
PARZIALMENTE COMPLETATO
```

come stato operativo derivato.

---

# 21. Esecuzione parziale

Un OdL massivo deve poter avere:

```text
5 occurrence completate
2 occurrence ancora da fare
1 occurrence rimossa dall'OdL
```

L'OdL non deve perdere tracciabilità.

Esempio UI:

```text
OdL #452 — Cambio olio

Completate:      5
Da fare:         2
Rimosse:         1
Totale iniziale: 8
```

Le occurrence rimosse restano manutenzioni aperte ma non più assegnate a quell'OdL.

---

# 22. Dashboard manutentore

## 22.1 Obiettivo

Il manutentore deve vedere immediatamente cosa deve fare.

La dashboard NON deve essere dominata da KPI amministrativi.

## 22.2 Riepilogo superiore

Esempio:

```text
4 SCADUTE
7 DA FARE ENTRO 7 GIORNI
14 IN PROGRAMMA
3 APPUNTAMENTI ESTERNI
```

## 22.3 Lista operativa

Campi utili:

```text
Quando
Piano
Asset
Famiglia
Stato
OdL
Priorità
Assegnatario
```

Esempio:

```text
02/09 | Cambio olio       | 4 asset | Torni | SCADUTO
05/09 | Pulizia filtri    | 7 asset | DMG   | DA FARE
08/09 | Controllo aspiraz.| ASP-01  |       | DA FARE
```

## 22.4 Modi di raggruppamento

La stessa base dati deve poter essere vista:

### Per Piano

```text
Cambio olio       8
Pulizia filtri    4
Tarature          3
```

### Per Famiglia

```text
Torni             6
Centri DMG        7
Impianti          2
```

### Per Asset

```text
DMG01             3
DMG02             1
TORNIO01          2
```

Aggiungere filtri sensati.

---

# 23. Dashboard responsabile

Il responsabile vede un quadro generale.

## 23.1 KPI / conteggi

Almeno:

```text
SCADUTE
IN SCADENZA
NON PIANIFICATE
ODL APERTI
ODL IN CORSO
IN ATTESA
RAPPORTI MANCANTI
FOLLOW-UP APERTI
```

## 23.2 Sezione importante: manutenzioni senza OdL

Mostrare chiaramente le occurrence:

```text
Cambio olio — DMG07 — scaduta da 5 giorni
Cambio filtri — ASP03 — scade tra 2 giorni
```

che esistono ma non sono ancora inserite in un OdL.

Questa distinzione è fondamentale:

```text
manutenzione dovuta != manutenzione pianificata
```

---

# 24. Dashboard amministratore

L'amministratore deve avere:

- tutto ciò che vede il responsabile;
- configurazione Piani;
- configurazione Assignment;
- gestione gruppi asset;
- gestione fornitori;
- gestione template/checklist;
- gestione ricorrenze;
- gestione eventuali conflitti;
- gestione dati storici;
- audit;
- eventuale migrazione / import massivo.

---

# 25. Caporeparto

Il caporeparto dovrebbe vedere almeno:

- manutenzioni del proprio reparto;
- asset coinvolti;
- manutenzioni scadute;
- manutenzioni imminenti;
- OdL programmati;
- eventuali fermi previsti;
- eventuali follow-up aperti.

Valutare se possa:
- modificare pianificazione;
- completare checklist;
- solo consultare.

Se il progetto ha già ruoli/permission, integrarsi con quelli senza inventare un sistema parallelo.

---

# 26. Filtri utili

Prevedere filtri almeno per:

```text
Piano
Asset
Gruppo
Reparto
Tipo
Stato
Scaduto / in scadenza
Assegnatario
Fornitore
Interna / esterna
Con OdL / senza OdL
Rapporto mancante
Follow-up aperto
Periodo
```

---

# 27. Ordinamento

Nelle viste operative usare priorità:

```text
1. Scadute
2. In scadenza
3. Da pianificare
4. Programmate
5. Future
```

Evitare di mettere "missing" come concetto utente generico.

Se mancano dati indispensabili, mostrare un messaggio specifico.

---

# 28. Stati visuali consigliati

Esempi:

```text
SCADUTA
IN SCADENZA
DA PIANIFICARE
PIANIFICATA
IN CORSO
IN ATTESA
ESEGUITA
RAPPORTO MANCANTE
COMPLETATA
ANNULLATA
CONFLITTO
```

Non è obbligatorio salvare tutti questi valori nel DB.

Molti possono essere derivati.

---

# 29. Creazione di un Piano — UX

Preferire un wizard o form progressivo.

## Step 1 — Cosa

```text
Nome
Tipo
Descrizione
Checklist
Allegato obbligatorio
Interna/Esterna
```

## Step 2 — Dove

```text
Gruppo asset
oppure
Asset specifici
```

Possibilità di aggiungere più applicazioni.

## Step 3 — Quando

```text
Periodicità
Data iniziale
Preavviso
```

## Step 4 — Chi

```text
Assegnatario
Fornitore
Modalità esecuzione
```

## Step 5 — Anteprima

Esempio:

```text
Questo Piano interesserà 14 asset.

Prime scadenze:
8 entro ottobre
6 entro novembre

2 asset presentano conflitti.
```

---

# 30. Scheda Piano

Esempio:

```text
CAMBIO OLIO

Tipo: Manutenzione ordinaria
Checklist: 5 step
Modalità: Interna

APPLICAZIONI

TORNI
12 asset
Ogni 30 giorni
Preavviso 10 giorni

FRESE
8 asset
Ogni 90 giorni
Preavviso 20 giorni

DMG04
Personalizzato
Ogni 45 giorni
Preavviso 15 giorni
```

Sotto:

```text
Prossime scadenze
OdL aperti
Storico
Follow-up
```

---

# 31. Scheda Asset

Nella scheda asset mostrare:

```text
PIANI DI MANUTENZIONE

Cambio olio
Ogni 90 giorni
Ereditato da: TORNI
Prossima: 20/10/2026

Pulizia filtro
Ogni mese
Personalizzato

Verifica assicurazione
Ogni anno
Amministrativa
```

Azioni:

```text
[Personalizza]
[Disabilita per questo asset]
[Visualizza storico]
```

Non usare "override" nella UI.

---

# 32. Disabilitazione per singolo asset

Serve poter escludere un asset da un Piano ereditato dal gruppo.

UX:

```text
○ Usa impostazioni del gruppo
● Personalizza per questo asset
○ Escludi questo asset
```

Se viene escluso:
- non creare nuove occurrence;
- non cancellare lo storico;
- mantenere audit della scelta.

---

# 33. Storico

Lo storico deve poter essere visto:

- per Piano;
- per Asset;
- per gruppo;
- per OdL;
- per fornitore;
- per periodo.

Dati importanti:

```text
scadenza teorica
data esecuzione
ritardo
esecutore
OdL
esito
allegati
follow-up
note
```

---

# 34. Storico iniziale / migrazione dati

Mantenere la possibilità di impostare manualmente l'ultima manutenzione senza creare un OdL storico completo.

Esempio:

```text
Asset
Piano
Ultima esecuzione
Note
```

Prevedere anche import massivo Excel/CSV.

Esempio:

```text
Asset | Piano | Ultima esecuzione
DM01  | Cambio olio | 15/03/2026
DM02  | Cambio olio | 21/07/2026
```

Implementare:

```text
dry-run
anteprima
errori riga
conferma
```

---

# 35. Template / checklist

Il sistema attuale copia la checklist del template nell'OdL.

Questa impostazione va mantenuta o migliorata.

Una modifica futura al template NON deve alterare retroattivamente gli OdL già eseguiti.

Valutare versionamento automatico.

Esempio:

```text
Cambio olio
Rev. 1
Rev. 2 dal 01/01/2027
```

Lo storico deve permettere di sapere quale revisione è stata utilizzata.

Il versionamento può essere implementato ora se semplice, oppure predisposto senza bloccare il refactoring principale.

---

# 36. Checklist obbligatorie

Mantenere il comportamento utile già presente:

- step obbligatorio;
- valore;
- testo;
- sì/no;
- foto;
- range;
- motivazione di skip;
- audit.

Uno step obbligatorio non completato deve poter bloccare la chiusura.

Lo skip deve rimanere tracciato:

```text
chi
quando
perché
```

---

# 37. Anomalie durante checklist

Se uno step:

```text
KO
fuori range
problema rilevato
```

la UI deve proporre:

```text
[Crea follow-up]
```

Il follow-up deve essere già precompilato con:

```text
asset
piano
occurrence
OdL
step
descrizione anomalia
```

---

# 38. Manutenzione ordinaria vs esito problema

Non confondere:

```text
"manutenzione eseguita"
```

con:

```text
"eventuale problema risolto"
```

Esempio:

```text
Manutenzione annuale eseguita correttamente.
Durante il controllo viene trovata una perdita.
```

La manutenzione può essere considerata eseguita e quindi avanzare la periodicità.

La perdita diventa follow-up aperto.

Non usare l'esito `Risolto / Non risolto` come unico criterio per decidere se una manutenzione programmata è stata realmente eseguita.

---

# 39. Manutenzioni esterne

Campi / stati utili:

```text
supplier
appointment_date
appointment_notes
external_execution_date
report_received_at
report_attachment
```

Stato derivato:

```text
DA PROGRAMMARE
APPUNTAMENTO FISSATO
ESEGUITA
RAPPORTO MANCANTE
CHIUSA
```

Il rapporto può essere obbligatorio per Piano.

---

# 40. Fermo macchina

Se già presente, mantenere:

```text
downtime
```

Valutare per OdL massivo se il fermo debba essere registrato per singolo asset/occurrence e non solo a livello generale.

Preferire granularità per asset.

---

# 41. Costi

Se già presenti:

```text
labor_cost
materials_cost
total_cost
covered_by_contract
```

mantenere.

Per OdL massivi valutare:

- costo generale OdL;
- eventuale costo per singola occurrence/asset;
- ripartizione opzionale.

Non complicare il primo refactoring se non necessario.

---

# 42. Contratti e fornitori

Mantenere compatibilità con:

```text
AssistanceContract
Supplier
```

e la logica `covered_by_contract` se già funzionante.

L'integrazione deve essere adattata al nuovo Piano/Occurrence senza eliminare funzioni utili.

---

# 43. Migrazione dal modello attuale

Prima di modificare il DB, Claude Code deve analizzare:

```text
MaintenanceInterventionTemplate
MaintenanceChecklistStep
MaintenanceRule
MaintenanceRuleAssetOverride
AssetMaintenanceRuleState
AssetMeter
WorkOrder
WorkOrderChecklist
WorkOrderExecutionDay
WorkOrderAttachment
WorkOrderLog
PeriodicVerification
AssistanceContract
AssetMaintenanceBudget
```

e tutti i riferimenti.

## 43.1 Non fare migrazioni distruttive alla cieca

Procedura richiesta:

1. mappare modelli e FK;
2. mappare view/form/service/command/task/template che li usano;
3. identificare i dati esistenti;
4. predisporre schema nuovo;
5. migrare dati;
6. verificare;
7. solo dopo deprecare/rimuovere vecchi campi.

## 43.2 Legacy PeriodicVerification

Il sistema attuale ha `PeriodicVerification` legacy.

Le scadenze amministrative e verifiche periodiche devono confluire progressivamente nel nuovo motore.

Non mantenere due scheduler paralleli a lungo termine.

Predisporre migrazione sicura.

---

# 44. AssetMaintenanceRuleState

La funzione attuale di memoria dell'ultima esecuzione deve essere rivalutata.

Nel nuovo modello l'Occurrence e lo storico delle occurrence completate potrebbero diventare la fonte primaria.

Evitare doppie fonti di verità.

Idealmente:

```text
ultima esecuzione
prossima scadenza
```

devono poter essere ricavati da una fonte canonica.

Se `AssetMaintenanceRuleState` resta temporaneamente per compatibilità, documentare chiaramente quale modello è authoritative.

---

# 45. Fonte di verità

Requisito architetturale:

NON avere contemporaneamente:

```text
next_due sul piano
next_due sull'asset
next_due sulla WorkMachine
next_due nello state
next_due nell'occurrence
```

con logiche differenti.

Definire una fonte canonica.

Suggerimento:

```text
Occurrence = fonte della scadenza concreta
Assignment + ultimo completamento = fonte per calcolo futura occurrence
```

Cache/denormalizzazioni sono ammesse solo se chiaramente sincronizzate.

---

# 46. WorkMachine.next_maintenance_date

Se esiste ancora un campo tipo:

```text
next_maintenance_date
```

valutare se:
- eliminarlo;
- renderlo solo cache;
- mantenerlo per compatibilità temporanea.

Non deve diventare una seconda fonte di verità.

---

# 47. Scheduler

Rivedere:

```text
generate_scheduled_workorders
run_generate_scheduled_workorders
```

Il nuovo processo dovrebbe essere separato in modo concettuale.

Esempio:

```text
generate_maintenance_occurrences
group_occurrences_into_workorders
send_maintenance_reminders
```

Il grouping può essere automatico o assistito.

Priorità:
1. generazione occurrence;
2. reminder/dashboard;
3. creazione OdL.

---

# 48. Reminder

I reminder devono basarsi sulle occurrence.

Esempi:

```text
Scadute
In scadenza entro 7 giorni
In scadenza entro 30 giorni
Da pianificare
Rapporto esterno mancante
Follow-up aperti
```

Il responsabile deve poter ricevere riepiloghi.

Non è necessario implementare nuove email in questa prima fase se non richiesto dal codice esistente, ma il modello deve supportarle.

---

# 49. Idempotenza e concorrenza

Proteggere:

- generazione occurrence duplicate;
- doppia creazione OdL;
- doppia chiusura;
- doppio avanzamento scadenza.

Usare transazioni DB quando opportuno.

Possibili constraint:

```text
unique(plan/assignment/asset/due_date)
```

o equivalente.

---

# 50. Audit

Mantenere / ampliare `WorkOrderLog`.

Tracciare almeno:

- creazione occurrence;
- inserimento in OdL;
- rimozione da OdL;
- cambio data;
- cambio gruppo/giornata;
- inizio lavoro;
- completamento;
- skip checklist;
- upload rapporti;
- creazione follow-up;
- modifica configurazione;
- esclusione asset;
- personalizzazione periodicità.

---

# 51. Permessi

Riutilizzare il sistema ruoli esistente.

Indicativamente:

## Admin
tutto.

## Responsabile manutenzione
- configurazione Piani;
- pianificazione;
- OdL;
- assegnazioni;
- gruppi;
- storico;
- follow-up;
- fornitori;
- report.

## Manutentore interno
- vedere attività assegnate;
- iniziare;
- compilare checklist;
- caricare allegati;
- completare;
- creare follow-up;
- segnalare attesa.

## Caporeparto
- vedere asset/reparto;
- vedere scadute;
- vedere pianificate;
- vedere fermi;
- consultare storico;
- eventuali azioni da definire secondo permessi già presenti.

---

# 52. UI principale proposta

Possibili voci:

```text
Manutenzione
├── Da fare
├── Scadenze
├── Ordini di lavoro
├── Piani
├── Gruppi asset
├── Storico
├── Follow-up
├── Fornitori
└── Contratti
```

"Scadenze amministrative" non deve più essere una sezione concettualmente separata se migrate nel nuovo sistema.

---

# 53. Pagina "Da fare"

Questa dovrebbe essere la pagina quotidiana del manutentore.

Blocchi:

```text
SCADUTE
DA FARE QUESTA SETTIMANA
PROGRAMMATE
IN ATTESA
ESTERNE
```

Vista switch:

```text
[Piano] [Famiglia] [Asset]
```

---

# 54. Pagina "Scadenze"

Vista temporale completa.

Tab / filtri:

```text
Scadute
30 giorni
90 giorni
Tutte
Amministrative
Ordinarie
```

Possibile calendario, ma non deve sostituire la lista.

---

# 55. Pagina "Piani"

Elenco:

```text
Nome
Tipo
N. asset coperti
Periodicità applicate
Prossima scadenza
Scadute
Attivo
```

Azione:

```text
[Nuovo Piano]
```

---

# 56. Matrice copertura

Mantenere il concetto utile della matrice asset × piani.

Deve però riflettere il nuovo sistema.

Indicazioni visive:

```text
✓ ereditato
P personalizzato
X escluso
! conflitto
- non applicato
```

---

# 57. Anteprima impatto

Prima di salvare un Assignment:

```text
Questo cambiamento coinvolgerà 18 asset.

Nuove scadenze: 18
Occurrence esistenti non modificate: 7
Conflitti: 2
```

Non modificare retroattivamente occurrence già eseguite.

Per occurrence future già create, definire una policy chiara.

Suggerimento:
- chiedere se ricalcolare le future non ancora pianificate;
- non toccare quelle già completate;
- non modificare silenziosamente OdL già in corso.

---

# 58. Cambio periodicità

Caso:

```text
Cambio olio TORNI
da 90 giorni
a 60 giorni
```

Regole consigliate:

- storico invariato;
- occurrence DONE invariata;
- occurrence future DA PIANIFICARE: ricalcolabili;
- occurrence già in OdL: avviso e scelta esplicita;
- nuova periodicità usata dalle generazioni successive.

---

# 59. Eliminazione Piano

Non eliminare fisicamente un Piano con storico.

Usare:

```text
active = False
```

o soft delete.

Stesso principio per Assignment usati storicamente.

---

# 60. Asset fuori uso

Le manutenzioni a calendario devono continuare ad essere visibili anche se una macchina è temporaneamente ferma/non utilizzata, salvo esclusione esplicita del Piano.

Non sospendere automaticamente la manutenzione solo per stato operativo.

Se esistono asset definitivamente dismessi, definire un comportamento specifico per `DECOMMISSIONED` / equivalente.

---

# 61. Prima scadenza

Quando si applica un Piano senza storico:

deve essere obbligatorio o chiaramente gestito uno dei seguenti:

```text
prima scadenza
data ultima esecuzione
data di partenza
```

Evitare stato ambiguo "mai eseguita" senza possibilità operativa di risolverlo.

---

# 62. Import iniziale

Creare eventualmente wizard:

```text
Scarica template Excel
Carica file
Anteprima
Errori
Conferma
```

Campi:

```text
asset_tag
plan
last_execution_date
note
```

Se serve importare Assignment:

```text
plan
asset/group
recurrence
warning
```

---

# 63. Performance

Le dashboard potrebbero coinvolgere molte combinazioni Piano × Asset.

Evitare calcoli N+1.

Usare:
- `select_related`
- `prefetch_related`
- query aggregate
- indici DB

Indici probabili:

```text
Occurrence(status, due_date)
Occurrence(asset, due_date)
Occurrence(plan, due_date)
Assignment(plan, active)
WorkOrder(status, due_at)
```

Da adattare allo schema reale.

---

# 64. Test obbligatori

Aggiungere test almeno per:

## 64.1 Periodicità ordinaria

```text
due 10/09
done 20/09
monthly
=> next 20/10
```

## 64.2 Amministrativa

```text
due 10/09
done 20/09
monthly
=> next 10/10
```

## 64.3 Primo lunedì del mese

Verificare mesi con date differenti.

## 64.4 Trimestrale

Verificare passaggio anno.

## 64.5 Preavviso

```text
due 20/10
warning 30
=> occurrence visibile dal 20/09
```

## 64.6 Idempotenza

Eseguire scheduler due volte:

```text
=> una sola occurrence
```

## 64.7 OdL massivo

3 occurrence -> 1 OdL.

## 64.8 Rimozione asset

Occurrence rimossa da OdL:

```text
=> resta aperta
=> torna da pianificare
```

## 64.9 Completamento parziale

Chiudere 2 occurrence su 3:

```text
=> 2 DONE
=> 1 ancora aperta
```

## 64.10 Allegato amministrativo

Chiusura senza allegato:

```text
=> bloccata
```

## 64.11 Esterna

Eseguita senza rapportino:

```text
=> rapporto mancante
=> non completamente chiusa se obbligatorio
```

## 64.12 Follow-up

KO su DM03:

```text
=> follow-up collegato a DM03
=> non all'intero lotto genericamente
```

## 64.13 Assignment specifico

Gruppo 90 giorni + asset 60:

```text
=> asset specifico = 60
```

## 64.14 Conflitto gruppi

Due gruppi con config diverse:

```text
=> conflitto
=> nessuna scelta arbitraria
```

---

# 65. Compatibilità dati

Prima del refactoring creare:

- backup DB;
- migrazione reversibile se possibile;
- eventuale management command di verifica.

Aggiungere controlli:

```text
numero vecchie regole
numero asset coinvolti
numero state
numero OdL periodici
numero verifiche legacy
```

Dopo migrazione confrontare quantità e campioni.

---

# 66. Strategia di implementazione consigliata

NON tentare un "big bang" senza verifiche.

## Fase A — Audit

Analizzare:
- modelli;
- services;
- scheduler;
- view;
- form;
- template;
- JS;
- permissions;
- URL;
- test;
- migrations;
- dati legacy.

Produrre una breve mappa tecnica interna.

## Fase B — Nuovo dominio

Implementare:
- Piano;
- Assignment;
- gruppi;
- Occurrence;
- recurrence engine.

Senza ancora eliminare il vecchio sistema.

## Fase C — Generazione

Implementare:
- scheduler occurrence;
- idempotenza;
- preavviso;
- next due.

## Fase D — OdL massivo

Collegare:
- occurrence;
- WorkOrder;
- execution days;
- completamento parziale;
- rimozione.

## Fase E — UI

Rifare:
- dashboard manutentore;
- dashboard responsabile;
- Piani;
- scadenze;
- OdL.

## Fase F — Amministrative

Migrare:
- scadenze amministrative;
- verifiche legacy compatibili.

## Fase G — Deprecazione

Rimuovere/deprecare:
- contatori;
- vecchio scheduler;
- vecchie regole ridondanti;
- vecchie viste non più necessarie.

---

# 67. Vincoli di implementazione

Claude Code deve:

1. studiare il codice esistente prima di modificare;
2. riutilizzare strutture funzionanti quando coerenti;
3. evitare duplicazioni;
4. non creare un secondo modulo parallelo;
5. mantenere stile UI esistente del portale;
6. mantenere permessi esistenti;
7. mantenere audit;
8. usare migrations Django corrette;
9. aggiungere test;
10. non rompere storico e allegati;
11. evitare modifiche silenziose a dati già completati;
12. evitare fonti multiple di verità.

---

# 68. Cosa NON fare

Non fare:

```text
un WorkOrder per ogni asset sempre
```

Non fare:

```text
la scadenza esiste solo dentro WorkOrder
```

Non fare:

```text
rimuovo asset da OdL = manutenzione annullata
```

Non fare:

```text
stessa periodicità obbligatoria per tutti gli asset del Piano
```

Non fare:

```text
regole HOURS/KM/CYCLES ancora visibili
```

Non fare:

```text
scadenze amministrative in un sistema totalmente separato
```

Non fare:

```text
modifica template retroattiva sugli OdL già eseguiti
```

Non fare:

```text
auto-risoluzione arbitraria di conflitti tra gruppi
```

Non fare:

```text
next_due duplicato in vari modelli senza fonte canonica
```

Non fare:

```text
aggiunta silenziosa di nuovi asset a un OdL già organizzato
```

---

# 69. Esempio completo

## Configurazione

```text
Piano:
CAMBIO OLIO

Tipo:
ORDINARY

Checklist:
- Scaricare olio
- Verificare residui
- Sostituire filtro
- Caricare olio nuovo
- Controllo perdite
```

Applicazioni:

```text
TORNI
ogni 30 giorni
preavviso 10 giorni

FRESE
ogni 90 giorni
preavviso 20 giorni

DMG04
ogni 45 giorni
preavviso 15 giorni
```

## Generazione

Al 20 settembre entrano nel preavviso:

```text
DMG01 due 10/10
DMG02 due 10/10
DMG03 due 11/10
DMG04 due 12/10
```

Creare occurrence:

```text
OCC-1 DMG01
OCC-2 DMG02
OCC-3 DMG03
OCC-4 DMG04
```

## Pianificazione

Responsabile seleziona tutte:

```text
[Crea OdL]
```

Risultato:

```text
OdL #501
Cambio olio
4 occurrence
```

## Distribuzione

```text
10 ottobre
DMG01
DMG02

11 ottobre
DMG03
DMG04
```

## Modifica

DMG03 non può essere fermata.

Viene rimossa dall'OdL.

Risultato:

```text
OCC-3 torna DA PIANIFICARE
```

Non è persa.

## Esecuzione

10 ottobre:

```text
DMG01 DONE
DMG02 DONE
```

Su DMG02 viene trovata perdita.

Creare:

```text
Follow-up
DMG02
Perdita olio
Origine OdL #501
Origine OCC-2
```

La manutenzione ordinaria è comunque stata eseguita.

Nuova scadenza DMG02:

```text
10 novembre
```

## DMG03

Resta:

```text
SCADUTA / DA PIANIFICARE
```

Finché non viene inserita in un altro OdL.

---

# 70. Esempio amministrativo

Piano:

```text
RINNOVO ASSICURAZIONE
Tipo: ADMINISTRATIVE
Periodicità: annuale
Scadenza: 31/12
Preavviso: 30 giorni
Allegato: obbligatorio
```

Occurrence 2026:

```text
Asset/oggetto: DMG01
Due: 31/12/2026
```

Completata:

```text
05/01/2027
```

Il sistema richiede:

```text
nuova polizza.pdf
```

Nuova scadenza:

```text
31/12/2027
```

NON:

```text
05/01/2028
```

---

# 71. Obiettivo UX finale

Un manutentore deve poter aprire la pagina e capire in pochi secondi:

```text
Cosa devo fare?
Su quali macchine?
Entro quando?
Quali sono già scadute?
Quali sono programmate oggi?
Quali sono in attesa?
```

Un responsabile deve poter capire:

```text
Cosa è scaduto?
Cosa sta per scadere?
Cosa non è ancora stato pianificato?
Quali OdL sono in ritardo?
Quali rapporti mancano?
Quali follow-up sono aperti?
```

Un amministratore deve poter configurare:

```text
Cosa
Dove
Quando
Chi
Con quale preavviso
Con quali documenti
```

senza dover ragionare in termini di regole tecniche o override.

---

# 72. Deliverable richiesto a Claude Code

Procedere direttamente sul repository con questo ordine:

1. analizzare implementazione attuale;
2. identificare impatto reale;
3. definire mapping old -> new;
4. implementare schema/modelli;
5. implementare migration;
6. implementare recurrence engine;
7. implementare occurrence generation;
8. integrare WorkOrder massivi;
9. aggiornare UI;
10. aggiornare permission;
11. migrare amministrative/legacy;
12. eliminare contatori dal nuovo flusso;
13. aggiungere test;
14. eseguire test;
15. correggere regressioni;
16. documentare brevemente le modifiche.

Prima di cancellare fisicamente dati o modelli legacy:
- verificare dipendenze;
- migrare i dati;
- mantenere rollback ragionevole.

Non limitarsi a proporre pseudocodice: implementare concretamente il refactoring nel codice esistente.

---

# 73. Decisioni già prese — NON chiedere nuovamente

Queste decisioni sono definitive per questa fase:

- solo manutenzioni basate sul tempo;
- niente ore/km/cicli;
- manutenzione ordinaria: nuova scadenza dalla data effettiva;
- amministrativa: nuova scadenza dalla scadenza teorica;
- macchina ferma: le manutenzioni continuano ad essere mostrate;
- anomalie: follow-up collegato all'OdL/occurrence;
- manutenzione esterna:
  - da programmare;
  - appuntamento;
  - eseguita;
  - rapporto;
- amministrative: allegato obbligatorio;
- supportare ricorrenze calendario evolute;
- utenti:
  - admin;
  - responsabile;
  - manutentore;
  - caporeparto;
- supportare Piano applicato a:
  - singolo asset;
  - gruppo/famiglia;
- periodicità e preavviso possono differire tra gruppi;
- supportare OdL massivi;
- asset escluso da OdL resta da fare;
- OdL distribuibile su più giorni;
- dashboard manutentore per:
  - piano;
  - famiglia;
  - asset;
- responsabile con quadro completo.

---

# 74. Nota finale per l'implementazione

La principale trasformazione concettuale è:

PRIMA:

```text
Rule -> Asset -> WorkOrder
```

DOPO:

```text
Plan
  -> Assignment
      -> Occurrence
          -> WorkOrder
```

L'`Occurrence` deve essere trattata come l'elemento che garantisce la continuità della scadenza.

Il WorkOrder è lo strumento operativo per organizzare il lavoro.

Questa distinzione deve guidare l'intero refactoring.
