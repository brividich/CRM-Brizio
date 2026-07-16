# GCM Gantt — Lo spostamento conta sabato e domenica (bugfix) — Design

**Data:** 2026-07-16
**Modulo:** `django_app/gestione_carichi_macchina`
**Stream:** 6 — "GCM: bug spostamento Gantt weekend"
**Tipo:** bugfix mirato (correzione di comportamento)

## Problema (segnalazione capo)

Punch-list `docs/ANAGRAFICA - PERSONE.md`, sezione CARICHI MACCHINA:

> "Nello spostare gli elementi nel Gantt vengono considerati anche il sabato e la
> domenica, anche se non vengono visualizzati."

Trascinando una barra nel Gantt, lo spostamento **conteggia i giorni di weekend**
che invece non dovrebbero contare: il Gantt mostra **solo** giorni lavorativi
(lun-ven), quindi il conteggio dello spostamento deve essere in **giorni
lavorativi**, non di calendario.

## Causa radice

Il Gantt renderizza **solo giorni lavorativi**: la finestra è costruita da
`_finestra()` con `_giorni_lavorativi(start, giorni_n)` (weekend esclusi,
`views.py:372`). Ogni colonna visibile = **un giorno lavorativo**.

Il frontend calcola il delta del drag **in colonne visibili**:

```js
// templates/.../gantt.html:936
var deltaDays = Math.round((e.clientX - d.startX) / d.w);
```

`d.w` è la larghezza di **una colonna** (un giorno lavorativo). Quindi
`deltaDays` = numero di **giorni lavorativi** attraversati dal trascinamento, e
viene inviato come `giorni_delta` a `reschedule`.

Il backend però lo applica come **giorni di calendario**:

```python
# views.py:1143  (funzione reschedule)
nuova_data = p.data + timedelta(days=delta)
```

`timedelta(days=delta)` somma giorni **di calendario**: quando l'intervallo
attraversa un weekend, i due modelli divergono. Esempio (giugno 2026):

- barra su **giovedì 25/06**, drag di **2 colonne** (gio→ven→lun): `deltaDays=2`.
- atteso: **lunedì 29/06** (2 giorni lavorativi dopo giovedì).
- prodotto: `25/06 + 2 = sabato 27/06` → data di **sabato**, che il Gantt non
  mostra affatto: la barra "sparisce" o riappare in posizione errata.

Il difetto sta **solo** nel calcolo di `nuova_data` in `reschedule`. Tutto il
resto della pipeline è già "giorni-lavorativi-aware":

- `_piano_slittamento` fa atterrare gli slittati su giorni lavorativi
  (`_giorni_lavorativi`, `_fine_lavorativa_excl`);
- il ramo `coda=True` ricalcola il delta con `_delta_giorni_lavorativi(p.data,
  nuova_data)` e sposta la coda con `_sposta_giorni_lavorativi` — ma parte da una
  `nuova_data` **già sbagliata** (di calendario), quindi eredita l'errore e può
  perfino atterrare di sabato.

Esiste già l'helper corretto, non usato in `reschedule`:

```python
# views.py:363
def _sposta_giorni_lavorativi(d: date, n: int) -> date:
    """Sposta `d` di `n` giorni LAVORATIVI (n può essere negativo), saltando i weekend."""
```

## Obiettivo / fix

In `reschedule`, sostituire il computo di calendario con lo spostamento in
**giorni lavorativi**, riusando l'helper esistente:

```python
# PRIMA
nuova_data = p.data + timedelta(days=delta)
# DOPO
nuova_data = _sposta_giorni_lavorativi(p.data, delta)
```

`p.data` è sempre un giorno lavorativo (nel Gantt i lavori non cadono mai di
weekend), quindi `_sposta_giorni_lavorativi` (che salta sabato/domenica in
entrambe le direzioni) produce sempre una data lavorativa e conta i passi
correttamente. Il segno negativo (drag all'indietro) è già gestito.

Ricadute automatiche (nessun'altra modifica necessaria):

- il ramo `coda=True` ora parte da una `nuova_data` lavorativa: `_delta_giorni_
  lavorativi(p.data, nuova_data)` restituisce esattamente `delta` e la coda scala
  del delta lavorativo giusto, senza atterrare di weekend;
- il ramo `coda=False` passa a `_piano_slittamento` una `nuova_data` lavorativa
  coerente con le colonne viste dall'operatore.

## Comportamento atteso (preciso)

- Lo spostamento di N colonne = N **giorni lavorativi**: la data risultante è la
  data ottenuta scorrendo N giorni lavorativi da `p.data`, **saltando** sabato e
  domenica sia nel conteggio sia nell'atterraggio.
- La `nuova_data` di un lavoro trascinato non cade **mai** di sabato/domenica.
- Drag all'indietro (delta negativo): simmetrico, salta i weekend.

## Non-obiettivi (fuori scope)

- **Festività infrasettimanali** (es. 25/04, 1/05, 15/08): tutto il modulo GCM
  modella i giorni non lavorativi **solo** come weekend (`weekday() < 5`), senza
  alcun calendario festività. Restiamo coerenti: il fix tratta **solo**
  sabato/domenica. Un eventuale calendario festività è un lavoro separato.
- Nessuna modifica a import, previsioni, saturazione, cambio-categoria, undo, o
  al frontend: il frontend invia già il delta in colonne (giorni lavorativi); il
  difetto e la correzione sono interamente lato server in `reschedule`.
- Nessun cambio di API/contratto: `giorni_delta` resta il numero di colonne;
  cambia solo la sua **interpretazione** (lavorativi, non calendario).

## Compatibilità con i test esistenti

- `test_reschedule_sposta_data`: p su **martedì 23/06**, `giorni_delta=3`, attende
  **venerdì 26/06**. `_sposta_giorni_lavorativi(mar, 3)` = mer→gio→ven = 26/06.
  **Invariato** (nessun weekend attraversato).
- `test_reschedule_slittamento_e2e_giorni_lavorativi`: p0 su **lunedì 22/06**,
  `giorni_delta=3` → giovedì 25/06; nessun weekend attraversato: invariato.
- I test che chiamano `_piano_slittamento` con `nuova_data` esplicita non passano
  da `reschedule` e non sono toccati.

## Testing (`tests_gantt.py`)

**Test RED (riproduce il bug prima del fix):** in `GanttViewTest`, `p` su
**giovedì 25/06/2026**, POST `reschedule` con `giorni_delta=2` (niente coda).

- Comportamento buggato (attuale): `p.data == 27/06` (sabato) → `weekday()==5`.
- Atteso (dopo fix): `p.data == 29/06` (lunedì), `weekday() < 5`.

Asserzioni: `p.data == date(2026, 6, 29)` **e** `p.data.weekday() < 5`. Il test
fallisce prima del fix (ottiene sabato 27/06) e passa dopo.

Opzionale (irrobustimento): drag all'indietro attraverso il weekend (p su lunedì,
`giorni_delta=-2` → giovedì precedente, non domenica).

## File toccati

- `django_app/gestione_carichi_macchina/views.py` (una riga in `reschedule`)
- `django_app/gestione_carichi_macchina/tests_gantt.py` (test RED→GREEN)
- `CHANGELOG.md`, `README.md` (comportamento visibile corretto)

## Isolamento dagli altri stream

Il fix tocca **solo** `gestione_carichi_macchina/{views.py,tests_gantt.py}`,
modulo distinto da anagrafica/visite (stream paralleli): **nessun conflitto** di
file. CHANGELOG/README si aggiornano sotto `[Unreleased]` (append, niente version
bump).
