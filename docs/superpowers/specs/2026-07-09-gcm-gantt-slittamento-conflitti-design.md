# GCM Gantt — Slittamento su conflitto + popup di conferma

**Data:** 2026-07-09
**Modulo:** `django_app/gestione_carichi_macchina`
**Tipo:** correzione comportamento + nuova UX (design)

## Problema

Nel drag-to-reschedule del Gantt carichi macchina, quando un lavoro viene
trascinato su uno slot già occupato lo "slittamento" produce risultati
sorprendenti: uno o entrambi i lavori finiscono in date non attese.

**Causa radice** (`views.py::reschedule`, funzione `cascata`): con il checkbox
"Cascata" attivo (default) il sistema sposta **tutti** i lavori successivi sulla
stessa macchina+turno (`data__gte=p.data`) dello **stesso delta** del
trascinamento, in modo incondizionato — anche quelli che non sono in conflitto.
Inoltre:

- Il conflitto reale è calcolato sullo **span in giorni lavorativi** (un lavoro
  da 16h su macchina a 8h occupa 2 giorni), mentre la cascata ragiona a "delta
  secco": i due modelli non coincidono, quindi restano conflitti o si aprono buchi.
- Con cascata ON il controllo di sovrapposizione (`if not forza and not cascata`)
  viene **saltato del tutto**: nessun riepilogo, nessuna vera risoluzione.
- Non esiste un riepilogo di cosa verrà spostato: solo un `window.confirm`
  generico.

## Obiettivo

1. Sostituire lo slittamento con un algoritmo **"inserisci e spingi"**
   span-aware: sposto il lavoro dove l'operatore l'ha lasciato e spingo in avanti
   **solo** i lavori realmente in conflitto, del **minimo necessario**, a catena
   finché nascono nuovi conflitti reali. I lavori più avanti che non collidono
   non si toccano mai.
2. Mostrare un **popup di riepilogo** con l'elenco di cosa verrà spostato
   (`Lavoro — da_data → a_data`) e chiedere conferma prima di applicare.

## Decisioni di design (confermate)

- **Slittamento in giorni lavorativi**: le nuove date cadono sempre sul primo
  giorno lavorativo libero, mai sabato/domenica (coerente con saturazione e
  `_sovrapposizioni`).
- **Drag senza conflitto**: applicato subito, senza conferma. Il popup compare
  **solo** quando c'è uno slittamento da confermare.
- **Checkbox "coda" nella pagina**: il checkbox oggi chiamato "Cascata" resta un
  flag in pagina, rinominato **"Sposta anche la coda (stesso delta)"**, gestito
  dall'operatore. **Default OFF**.
  - OFF (azione base): sposta solo A e slitta i **soli** conflitti, del minimo.
  - ON: sposta A e **tutta** la coda (stessa macchina+turno, `data >= A`) dello
    stesso delta — comportamento storico, ma ora con popup di conferma.

## Architettura

### Backend — `gestione_carichi_macchina/views.py`

Nuovo helper puro, testabile in isolamento:

```
def _piano_slittamento(macchina_eff, p, nuova_data, coda: bool) -> list[dict]:
    """Ritorna il piano di spostamento come lista ordinata di righe:
        [{"id", "etichetta", "macchina", "da": date, "a": date}, ...]
    La prima riga è sempre p (il lavoro trascinato). Le successive sono i
    lavori spinti. Non tocca il DB: calcola soltanto."""
```

- **Cosa fa (coda=False, default):**
  1. p va a `nuova_data` (già calcolata dal chiamante: `p.data + delta`,
     eventualmente con macchina di destinazione).
  2. Trova i conflitti di p con `_sovrapposizioni(macchina_eff, p.turno,
     nuova_data, ore_p, escludi_id=p.id)`.
  3. Per ogni conflitto, calcola la nuova data-inizio = primo giorno lavorativo
     `>= fine lavorativa di p` (usa `_fine_lavorativa_excl` / `_giorni_lavorativi`
     già esistenti). Aggiunge la riga al piano.
  4. Ripete la ricerca conflitti per ciascun lavoro spinto rispetto ai lavori
     **non ancora nel piano** (catena), spingendo solo quelli che collidono
     davvero. Ordina per data così la catena resta contigua.
  5. Termina quando nessun nuovo conflitto emerge. Nessun tocco ai lavori non
     collidenti.

- **Cosa fa (coda=True):** piano = p + tutti i `Pianificazione` con
  `macchina=macchina_eff, turno=p.turno, data >= p.data` (esclusa p), ciascuno
  spostato dello **stesso delta**. (Equivale al comportamento storico, reso
  esplicito e con riepilogo.)

`reschedule()` viene ristrutturata così:

1. Parse parametri (aggiungi `coda` = ex-`cascata`, e `conferma_slittamento`).
2. Gestione incompatibilità categoria macchina (invariata: `reason:"incompatibile"`).
3. Calcola `piano = _piano_slittamento(...)`.
4. Se `len(piano) > 1` (c'è slittamento) **e** non `conferma_slittamento` **e**
   non `forza` → risponde `200` con:
   ```json
   {"ok": false, "reason": "slittamento",
    "piano": [{"etichetta": "...", "macchina": "DM3", "da": "23/06", "a": "26/06"}, ...]}
   ```
5. Altrimenti applica il piano in `transaction.atomic()`:
   - `select_for_update()` su tutti gli id coinvolti.
   - aggiorna `data` (e `macchina` per la sola p in caso di cambio macchina),
     `fonte=FONTE_MANUALE`.
   - snapshot undo di **tutti** gli id coinvolti in `request.session["gcm_undo"]`.
6. Log azione con descrizione che include il numero di lavori slittati.

Il campo POST `cascata` viene rinominato in `coda`; per compatibilità si accetta
anche `cascata` come alias in lettura (nessun consumer esterno, ma il costo è
nullo). Nota: la risposta continua a esporre `spostati` (conteggio) per non
rompere il frontend che ricarica quando `spostati > 1`.

### Frontend — `templates/gestione_carichi_macchina/gantt.html`

- **Checkbox**: `#g_cascata` → rinominato label "Sposta anche la coda (stesso
  delta)", **senza** `checked` (default OFF). Il valore viene inviato come `coda`.
- **`postMove`**: quando la risposta ha `reason === "slittamento"`, invece del
  `window.confirm` apre un **modale** che elenca le righe di `data.piano`
  (`etichetta — da → a`) con intestazione *"Questo spostamento richiede di
  slittare N lavori:"* e bottoni **Conferma** / **Annulla**.
  - Conferma → ripete `postMove` con `params.conferma_slittamento = "1"`.
  - Annulla → `resetBar(d)`.
- `reason === "incompatibile"` resta con `window.confirm` (→ `forza=1`), invariato.
- **Drag senza conflitto**: si rimuove il `window.confirm` a monte del drag
  temporale (il modale ora copre il solo caso conflitto). Il cambio macchina
  mantiene la sua conferma esplicita (azione più impattante).
- Il modale riusa lo stile modale già presente nella pagina (nessuna nuova
  libreria): markup SSR nascosto + toggle via classe, coerente con il pattern
  "vanilla JS" del file.

### Dati / flusso

```
drag rilascio
  └─ POST reschedule {pianificazione_id, giorni_delta, coda, macchina_dest?}
       ├─ incompatibile categoria → reason:"incompatibile"  → confirm → forza=1
       ├─ piano vuoto/1 riga        → applica, ok
       └─ piano > 1 riga            → reason:"slittamento" + piano
                                          └─ modale conferma
                                               └─ POST reschedule {..., conferma_slittamento:1}
                                                     └─ applica atomico, ok
```

## Error handling

- `_piano_slittamento` è puro e non solleva su input validi; il chiamante gestisce
  gli id mancanti come oggi (`get_object_or_404`).
- Orizzonte di catena limitato (riuso l'orizzonte lavorativo esistente, es. 60
  giorni lavorativi) per evitare loop patologici; se un lavoro non trova slot
  entro l'orizzonte, viene comunque spostato alla fine dell'orizzonte e il piano
  lo segnala (nessun crash).
- Applicazione sempre in `transaction.atomic()` + `select_for_update()` per
  coerenza sotto concorrenza.
- L'undo ripristina **tutti** i lavori dello snapshot.

## Testing (`tests_gantt.py`)

Nuovi test:

- `test_slittamento_spinge_solo_conflitto_minimo`: A spinto su B → B scala del
  minimo, C (non in conflitto) invariato.
- `test_slittamento_a_catena_solo_conflitti_reali`: B spinto genera conflitto con
  C contiguo → C scala; D distante invariato.
- `test_slittamento_salta_weekend`: la nuova data non cade di sabato/domenica.
- `test_slittamento_richiede_conferma`: prima POST → `reason:"slittamento"` +
  `piano`; DB invariato. Seconda POST con `conferma_slittamento=1` → applica.
- `test_coda_flag_sposta_tutta_la_coda`: con `coda=1` tutta la coda scala dello
  stesso delta (aggiorna l'attuale `test_reschedule_cascata_*`).
- `test_undo_ripristina_tutti_gli_slittati`: undo riporta A e i lavori spinti.
- Adegua i test esistenti che usano `cascata` al nuovo nome `coda` (mantenendo un
  test di alias se si conserva la retro-compatibilità in lettura).

## Fuori scope (per modifiche successive)

L'utente ha anticipato ulteriori modifiche successive. Questo spec copre solo lo
slittamento su conflitto e il popup di conferma. Non tocca: import, previsioni,
saturazione, cambio-categoria pool, altre viste.

## File toccati

- `django_app/gestione_carichi_macchina/views.py` (helper + `reschedule`)
- `django_app/gestione_carichi_macchina/templates/gestione_carichi_macchina/gantt.html`
  (checkbox, `postMove`, modale)
- `django_app/gestione_carichi_macchina/tests_gantt.py` (test)
- `CHANGELOG.md`, `README.md` (dovuto per cambio comportamento visibile)
