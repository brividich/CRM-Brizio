# GCM Gantt — Slittamento su conflitto + popup conferma — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correggere lo slittamento del drag-to-reschedule del Gantt carichi macchina in modo che spinga solo i lavori realmente in conflitto (del minimo necessario, in giorni lavorativi) e mostrare un popup di riepilogo con conferma prima di applicare.

**Architecture:** Un nuovo helper puro `_piano_slittamento()` in `views.py` calcola — senza toccare il DB — la lista ordinata dei movimenti (A + lavori spinti a catena solo sui conflitti reali, oppure A + tutta la coda se il flag "coda" è ON). `reschedule()` usa l'helper per rispondere con `reason:"slittamento"` + `piano` in fase di preview, e per applicare atomicamente il piano su conferma. Il frontend sostituisce il `window.confirm` con un modale che elenca i movimenti.

**Tech Stack:** Django 5.2 (SSR + HTMX), vanilla JS, test `django.test`. Riuso helper esistenti span-aware.

## Global Constraints

- Test scoped: `python django_app\manage.py test django_app.gestione_carichi_macchina --keepdb --settings=config.settings.test` (mai la suite completa).
- Ambiente: PowerShell + python del venv (`.\.venv\Scripts\python.exe`). Bash rifiutato dai permessi.
- Django vieta attributi template con `_` iniziale (non rilevante qui, ma non introdurre attrs helper con underscore iniziale nelle view).
- API/AJAX: risposte JSON, mai redirect HTML. Endpoint già protetto da `@login_required @require_POST`.
- Endpoint invariati: `reschedule` continua a esporre nella risposta `ok`, `spostati` (conteggio) e `macchina` (bool) per non rompere il frontend che ricarica quando `spostati > 1`.
- Slittamento in **giorni lavorativi** (weekend esclusi): usa `_giorni_lavorativi`, `_span_lavorativi`, `_fine_lavorativa_excl`, `_sovrapposizioni` già presenti.
- **MANDATORY a fine lavoro:** aggiornare `CHANGELOG.md` (tutti i file modificati) e `README.md` (comportamento visibile cambiato).

### Firme helper esistenti (da consumare, NON reimplementare)

```python
# tutte in gestione_carichi_macchina/views.py
_giorni_lavorativi(start: date, n: int) -> list[date]      # n giorni lun-ven da start
_span_lavorativi(ore, ore_giorno) -> int                   # ceil(ore/ore_giorno), min 1
_fine_lavorativa_excl(inizio: date, span_lav: int) -> date # fine esclusiva
_sovrapposizioni(macchina, turno, data, ore, escludi_id=None) -> list[Pianificazione]
# Macchina.ore_giorno_per_turno(turno) -> Decimal
# Pianificazione: campi .id .macchina_id .macchina .turno .data (date) .ore .stato
#   .testo_originale .famiglia_id .famiglia.nome .fonte  ; FONTE_MANUALE ; STATO_COMPLETATA
```

---

### Task 1: Helper `_piano_slittamento` — caso base (spingi solo i conflitti, minimo)

**Files:**
- Modify: `django_app/gestione_carichi_macchina/views.py` (nuovo helper, inserire subito dopo `_primo_slot_libero`, ~riga 178)
- Test: `django_app/gestione_carichi_macchina/tests_gantt.py`

**Interfaces:**
- Consumes: `_sovrapposizioni`, `_span_lavorativi`, `_fine_lavorativa_excl`, `_giorni_lavorativi`, `Macchina.ore_giorno_per_turno`.
- Produces:
  ```python
  def _piano_slittamento(macchina_eff, p, nuova_data, coda=False, orizzonte=60) -> list[dict]:
      # ritorna lista ordinata; ogni riga:
      # {"id": int, "etichetta": str, "macchina": str, "da": date, "a": date}
      # riga[0] è sempre p (il lavoro trascinato: da=p.data, a=nuova_data).
      # righe successive = lavori spinti. Nessuna scrittura sul DB.
  ```

- [ ] **Step 1: Scrivi il test che fallisce**

Aggiungi in `tests_gantt.py`, dentro `class GanttViewTest` (usa `self.m`, categoria 5_axis, `ore_giorno_per_turno('giorno')` default). Nota: senza `ore`, `_span_lavorativi` = 1 giorno lavorativo, quindi ogni lavoro occupa 1 giorno.

```python
def test_piano_slittamento_spinge_solo_conflitto_minimo(self):
    from datetime import date
    from .views import _piano_slittamento
    d = date(2026, 6, 22)  # lunedì
    p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
    b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
    c = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=4), turno="giorno", testo_originale="C", fonte=Pianificazione.FONTE_IMPORT)
    # Trascino A dal 22 al 23 (dove sta B, 1 giorno) -> B in conflitto, C no.
    piano = _piano_slittamento(self.m, p0, d + timedelta(days=1), coda=False)
    ids = [r["id"] for r in piano]
    self.assertEqual(ids[0], p0.id)          # A è la prima riga
    self.assertIn(b.id, ids)                 # B viene spinto
    self.assertNotIn(c.id, ids)              # C non viene toccato
    riga_b = next(r for r in piano if r["id"] == b.id)
    self.assertEqual(riga_b["a"], d + timedelta(days=2))  # B -> primo giorno lav. dopo A (24=merc)
```

- [ ] **Step 2: Esegui il test e verifica che fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_piano_slittamento_spinge_solo_conflitto_minimo --keepdb --settings=config.settings.test`
Expected: FAIL con `ImportError: cannot import name '_piano_slittamento'`.

- [ ] **Step 3: Implementa il caso base**

Inserisci in `views.py` dopo `_primo_slot_libero`:

```python
def _piano_slittamento(macchina_eff, p, nuova_data, coda=False, orizzonte=60):
    """Calcola (senza toccare il DB) i movimenti necessari per spostare `p` a
    `nuova_data` sulla macchina `macchina_eff`.

    Con coda=False: spinge in avanti SOLO i lavori realmente in conflitto, del
    minimo necessario (in giorni lavorativi), a catena finché nascono nuovi
    conflitti reali. I lavori non collidenti non vengono toccati.

    Ritorna lista ordinata di dict {id, etichetta, macchina, da, a}; la prima
    riga è sempre `p`.
    """
    def _etichetta(job):
        return (getattr(job, "testo_originale", "") or
                (job.famiglia.nome if getattr(job, "famiglia_id", None) else "") or
                "lavoro")

    def _fine(inizio, job):
        ore = float(job.ore) if job.ore else None
        span = _span_lavorativi(ore, macchina_eff.ore_giorno_per_turno(job.turno))
        return _fine_lavorativa_excl(inizio, span)

    def _primo_lav(da_data):
        # primo giorno lavorativo >= da_data
        return _giorni_lavorativi(da_data, 1)[0]

    piano = [{"id": p.id, "etichetta": _etichetta(p), "macchina": macchina_eff.codice,
              "da": p.data, "a": nuova_data}]
    # mappa id -> data corrente (di lavoro) durante la simulazione
    pos = {p.id: nuova_data}

    # Coda dei lavori appena (ri)posizionati di cui propagare i conflitti.
    frontiera = [(p, nuova_data)]
    visti = {p.id}
    passi = 0
    while frontiera and passi < 500:
        passi += 1
        job, job_data = frontiera.pop(0)
        ore = float(job.ore) if job.ore else None
        conflitti = _sovrapposizioni(macchina_eff, job.turno, job_data, ore, escludi_id=job.id)
        # ordina per data così la catena resta contigua e deterministica
        conflitti.sort(key=lambda o: (o.data, o.id))
        for o in conflitti:
            if o.id in visti:
                continue
            visti.add(o.id)
            nuova = _primo_lav(_fine(job_data, job))
            # non trascinare all'infinito: limita entro l'orizzonte lavorativo
            limite = _giorni_lavorativi(job_data, orizzonte)[-1]
            if nuova > limite:
                nuova = limite
            pos[o.id] = nuova
            piano.append({"id": o.id, "etichetta": _etichetta(o), "macchina": macchina_eff.codice,
                          "da": o.data, "a": nuova})
            frontiera.append((o, nuova))
    return piano
```

- [ ] **Step 4: Esegui il test e verifica che passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_piano_slittamento_spinge_solo_conflitto_minimo --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/gestione_carichi_macchina/views.py django_app/gestione_carichi_macchina/tests_gantt.py
git commit -m "feat(gcm): helper _piano_slittamento (spinge solo i conflitti, minimo)"
```

---

### Task 2: `_piano_slittamento` — catena solo-conflitti reali + skip weekend

**Files:**
- Test: `django_app/gestione_carichi_macchina/tests_gantt.py`

**Interfaces:**
- Consumes: `_piano_slittamento` (Task 1). Nessuna modifica di firma: i test verificano il comportamento a catena e il salto weekend già implementati.

- [ ] **Step 1: Scrivi i test che falliscono (o confermano il comportamento)**

```python
def test_piano_slittamento_a_catena_solo_conflitti_reali(self):
    from datetime import date
    from .views import _piano_slittamento
    d = date(2026, 6, 22)  # lunedì
    p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
    b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
    c = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=2), turno="giorno", testo_originale="C", fonte=Pianificazione.FONTE_IMPORT)
    far = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=10), turno="giorno", testo_originale="Z", fonte=Pianificazione.FONTE_IMPORT)
    piano = _piano_slittamento(self.m, p0, d + timedelta(days=1), coda=False)
    ids = [r["id"] for r in piano]
    self.assertIn(b.id, ids)      # B spinto da A
    self.assertIn(c.id, ids)      # C spinto da B (catena)
    self.assertNotIn(far.id, ids) # Z lontano: non toccato

def test_piano_slittamento_salta_weekend(self):
    from datetime import date
    from .views import _piano_slittamento
    ven = date(2026, 6, 26)  # venerdì
    p0 = Pianificazione.objects.create(macchina=self.m, data=ven, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
    b = Pianificazione.objects.create(macchina=self.m, data=ven, turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
    piano = _piano_slittamento(self.m, p0, ven, coda=False)
    riga_b = next(r for r in piano if r["id"] == b.id)
    # A occupa venerdì -> B spinto al primo giorno lavorativo dopo = lunedì 29/06
    self.assertEqual(riga_b["a"], date(2026, 6, 29))
    self.assertLess(riga_b["a"].weekday(), 5)  # non è weekend
```

- [ ] **Step 2: Esegui i test**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_piano_slittamento_a_catena_solo_conflitti_reali django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_piano_slittamento_salta_weekend --keepdb --settings=config.settings.test`
Expected: PASS (il comportamento è già coperto dall'implementazione del Task 1; questi test lo blindano).

- [ ] **Step 3: Se un test fallisce, correggi `_piano_slittamento`**

Se `test_..._salta_weekend` fallisce perché due lavori partono lo stesso giorno e `_sovrapposizioni` non li considera in conflitto quando `data` coincide, verifica la condizione `o.data < fine and data < o_fine` in `_sovrapposizioni`: con span 1 e stessa data il conflitto c'è. Nessuna modifica prevista; se serve, l'aggiustamento è solo in `_piano_slittamento` (non toccare `_sovrapposizioni`).

- [ ] **Step 4: Commit**

```powershell
git add django_app/gestione_carichi_macchina/tests_gantt.py django_app/gestione_carichi_macchina/views.py
git commit -m "test(gcm): catena solo-conflitti + skip weekend nello slittamento"
```

---

### Task 3: `_piano_slittamento` — ramo `coda=True` (sposta tutta la coda, stesso delta)

**Files:**
- Modify: `django_app/gestione_carichi_macchina/views.py` (`_piano_slittamento`)
- Test: `django_app/gestione_carichi_macchina/tests_gantt.py`

**Interfaces:**
- Consumes/Produces: stessa firma di Task 1. Con `coda=True` il piano contiene p + tutti i successivi stesso turno spostati dello stesso delta.

- [ ] **Step 1: Scrivi il test che fallisce**

```python
def test_piano_slittamento_coda_sposta_tutta_la_coda(self):
    from datetime import date
    from .views import _piano_slittamento
    d = date(2026, 6, 22)  # lunedì
    p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
    b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
    c = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=2), turno="giorno", testo_originale="C", fonte=Pianificazione.FONTE_IMPORT)
    piano = _piano_slittamento(self.m, p0, d + timedelta(days=3), coda=True)
    ids = [r["id"] for r in piano]
    self.assertEqual(set(ids), {p0.id, b.id, c.id})   # tutta la coda
    riga_b = next(r for r in piano if r["id"] == b.id)
    riga_c = next(r for r in piano if r["id"] == c.id)
    self.assertEqual(riga_b["a"], b.data + timedelta(days=3))  # stesso delta calendario
    self.assertEqual(riga_c["a"], c.data + timedelta(days=3))
```

- [ ] **Step 2: Esegui il test e verifica che fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_piano_slittamento_coda_sposta_tutta_la_coda --keepdb --settings=config.settings.test`
Expected: FAIL (con `coda=True` l'attuale helper ignora il flag e non include B/C, oppure li include per conflitto ma con date diverse).

- [ ] **Step 3: Implementa il ramo `coda=True`**

In `_piano_slittamento`, subito dopo aver costruito la prima riga `piano = [...]` e prima del ciclo `while frontiera`, inserisci:

```python
    if coda:
        from .models import Pianificazione
        delta = (nuova_data - p.data).days
        successivi = (Pianificazione.objects
                      .filter(macchina=macchina_eff, turno=p.turno, data__gte=p.data)
                      .exclude(pk=p.pk)
                      .exclude(stato=Pianificazione.STATO_COMPLETATA)
                      .order_by("data", "id"))
        for o in successivi:
            piano.append({"id": o.id, "etichetta": _etichetta(o),
                          "macchina": macchina_eff.codice,
                          "da": o.data, "a": o.data + timedelta(days=delta)})
        return piano
```

- [ ] **Step 4: Esegui il test e verifica che passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_piano_slittamento_coda_sposta_tutta_la_coda --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/gestione_carichi_macchina/views.py django_app/gestione_carichi_macchina/tests_gantt.py
git commit -m "feat(gcm): ramo coda in _piano_slittamento (sposta tutta la coda)"
```

---

### Task 4: `reschedule()` — preview `reason:"slittamento"` + apply su conferma

**Files:**
- Modify: `django_app/gestione_carichi_macchina/views.py` (funzione `reschedule`, ~riga 898-990)
- Test: `django_app/gestione_carichi_macchina/tests_gantt.py`

**Interfaces:**
- Consumes: `_piano_slittamento` (Task 1-3).
- Produces (contratto HTTP di `reschedule`):
  - POST params: `pianificazione_id`, `giorni_delta`, `coda` (`1/0`, alias legge anche `cascata`), `macchina_dest?`, `forza?`, `conferma_slittamento?` (`1`).
  - Preview conflitto: `200` `{"ok": false, "reason": "slittamento", "piano": [{"etichetta","macchina","da":"dd/mm","a":"dd/mm"}...]}` (senza scrivere sul DB).
  - Apply: `200` `{"ok": true, "id", "spostati": N, "coda": bool, "macchina": bool}`.

- [ ] **Step 1: Scrivi i test che falliscono**

```python
def test_reschedule_conflitto_richiede_conferma_poi_applica(self):
    self.client.force_login(self.user)
    d = date(2026, 6, 22)  # lunedì
    p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
    b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
    # Preview: A -> 23 (dove sta B). Deve chiedere conferma, DB invariato.
    r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                         {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0"})
    self.assertEqual(r.status_code, 200)
    j = r.json()
    self.assertFalse(j["ok"])
    self.assertEqual(j["reason"], "slittamento")
    self.assertGreaterEqual(len(j["piano"]), 2)
    p0.refresh_from_db(); b.refresh_from_db()
    self.assertEqual(p0.data, d)                       # invariato
    self.assertEqual(b.data, d + timedelta(days=1))    # invariato
    # Apply: con conferma_slittamento=1 esegue.
    r2 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                          {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0", "conferma_slittamento": "1"})
    self.assertTrue(r2.json()["ok"])
    p0.refresh_from_db(); b.refresh_from_db()
    self.assertEqual(p0.data, d + timedelta(days=1))   # A spostato
    self.assertEqual(b.data, d + timedelta(days=2))    # B slittato del minimo

def test_reschedule_senza_conflitto_applica_diretto(self):
    self.client.force_login(self.user)
    d = date(2026, 6, 22)
    p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
    r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                         {"pianificazione_id": p0.id, "giorni_delta": "3", "coda": "0"})
    self.assertTrue(r.json()["ok"])   # nessun conflitto -> nessuna conferma
    p0.refresh_from_db()
    self.assertEqual(p0.data, d + timedelta(days=3))
```

- [ ] **Step 2: Esegui i test e verifica che falliscono**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_reschedule_conflitto_richiede_conferma_poi_applica django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_reschedule_senza_conflitto_applica_diretto --keepdb --settings=config.settings.test`
Expected: FAIL (oggi `reason` è `sovrapposizione`/assente e la logica cascata è diversa).

- [ ] **Step 3: Riscrivi il corpo di `reschedule` dopo il blocco "incompatibile"**

Sostituisci il blocco da `# Conferma su SOVRAPPOSIZIONE ...` (riga ~937) fino alla fine della funzione (prima di `@login_required` di `reschedule_undo`) con:

```python
    coda = (request.POST.get("coda") in ("1", "true", "on")
            or request.POST.get("cascata") in ("1", "true", "on"))  # alias legacy
    conferma = request.POST.get("conferma_slittamento") in ("1", "true", "on")
    macchina_eff = target or p.macchina
    nuova_data = p.data + timedelta(days=delta)

    piano = _piano_slittamento(macchina_eff, p, nuova_data, coda=coda)

    # C'è slittamento (piano oltre la sola p) e non ancora confermato -> preview.
    if len(piano) > 1 and not conferma and not forza:
        return JsonResponse({
            "ok": False, "reason": "slittamento",
            "piano": [{
                "etichetta": r["etichetta"], "macchina": r["macchina"],
                "da": r["da"].strftime("%d/%m"), "a": r["a"].strftime("%d/%m"),
            } for r in piano],
        }, status=200)

    with transaction.atomic():
        ids = [r["id"] for r in piano]
        blocco = {j.id: j for j in Pianificazione.objects.select_for_update().filter(pk__in=ids)}
        snap = [{"id": j.id, "macchina_id": j.macchina_id, "data": j.data.isoformat()}
                for j in blocco.values()]
        for r in piano:
            job = blocco.get(r["id"])
            if not job:
                continue
            job.data = r["a"]
            if sposta_macchina and job.pk == p.pk:
                job.macchina = target
            job.fonte = Pianificazione.FONTE_MANUALE
            job.save(update_fields=["data", "macchina", "fonte", "updated_at"])

    request.session["gcm_undo"] = {"snap": snap}
    request.session.modified = True
    macchina_log = target or p.macchina
    n_slittati = len(piano) - 1
    if sposta_macchina:
        descr = f"Spostato su {macchina_log.codice}" + (f", {delta:+d} giorni" if delta else "")
    else:
        descr = f"Spostato di {delta:+d} giorni"
    if n_slittati:
        descr += f" (+{n_slittati} slittati)"
    _log_azione(request, "sposta", macchina=macchina_log, pianificazione_id=p.id, descrizione=descr)
    return JsonResponse({
        "ok": True, "id": p.id, "spostati": len(piano),
        "coda": coda and not sposta_macchina, "macchina": sposta_macchina,
    })
```

Rimuovi le vecchie variabili non più usate del blocco sostituito (`altri`, `ore_f`, `etich`, `sug`, `msg`, il vecchio ciclo `cascata`/`successivi`/`affected`). Mantieni gli import in cima alla funzione (`from django.db import transaction`, `from .models import Macchina, Pianificazione`).

- [ ] **Step 4: Esegui i test e verifica che passano**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_reschedule_conflitto_richiede_conferma_poi_applica django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_reschedule_senza_conflitto_applica_diretto --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/gestione_carichi_macchina/views.py django_app/gestione_carichi_macchina/tests_gantt.py
git commit -m "feat(gcm): reschedule con preview slittamento + apply su conferma"
```

---

### Task 5: Adegua i test esistenti al nuovo contratto (`coda`, undo multiplo)

**Files:**
- Modify: `django_app/gestione_carichi_macchina/tests_gantt.py`

**Interfaces:**
- Consumes: `reschedule` (Task 4).

I test esistenti `test_reschedule_cascata_sposta_i_successivi`, `test_reschedule_senza_cascata_sposta_solo_uno`, `test_reschedule_undo_ripristina` usano il parametro `cascata` e assumono la vecchia semantica. Con dati **non contigui** (gap di 2 giorni) il nuovo caso base non trova conflitti; con `coda=1` invece la coda si sposta. Vanno aggiornati.

- [ ] **Step 1: Aggiorna i test esistenti**

Sostituisci `test_reschedule_cascata_sposta_i_successivi` con la versione che usa `coda`:

```python
def test_reschedule_coda_sposta_i_successivi(self):
    self.client.force_login(self.user)
    d0 = date(2026, 6, 22)  # lunedì (niente weekend nei +2/+4)
    p0 = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
    p1 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=2), turno="giorno", testo_originale="b", fonte=Pianificazione.FONTE_IMPORT)
    p2 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=4), turno="giorno", testo_originale="c", fonte=Pianificazione.FONTE_IMPORT)
    r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                         {"pianificazione_id": p0.id, "giorni_delta": "3", "coda": "1", "conferma_slittamento": "1"})
    self.assertEqual(r.status_code, 200)
    self.assertEqual(r.json()["spostati"], 3)
    p0.refresh_from_db(); p1.refresh_from_db(); p2.refresh_from_db()
    self.assertEqual(p0.data, d0 + timedelta(days=3))
    self.assertEqual(p1.data, d0 + timedelta(days=5))
    self.assertEqual(p2.data, d0 + timedelta(days=7))
```

Sostituisci `test_reschedule_senza_cascata_sposta_solo_uno` con:

```python
def test_reschedule_senza_coda_non_tocca_i_non_conflitti(self):
    self.client.force_login(self.user)
    d0 = date(2026, 6, 22)
    p0 = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
    p1 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=2), turno="giorno", testo_originale="b", fonte=Pianificazione.FONTE_IMPORT)
    # +1 giorno: A finisce sul 23, p1 è sul 24 -> nessun conflitto, applica diretto.
    r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                         {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0"})
    self.assertEqual(r.json()["spostati"], 1)
    p1.refresh_from_db()
    self.assertEqual(p1.data, d0 + timedelta(days=2))  # invariato
```

Aggiorna `test_reschedule_undo_ripristina` per usare `coda` invece di `cascata` (parametro `"cascata": "0"` → `"coda": "0"`; resta un solo lavoro, nessun conflitto). Aggiungi inoltre il test undo multiplo:

```python
def test_undo_ripristina_tutti_gli_slittati(self):
    self.client.force_login(self.user)
    d = date(2026, 6, 22)
    p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
    b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
    self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                     {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0", "conferma_slittamento": "1"})
    r = self.client.post(reverse("gestione_carichi_macchina:reschedule_undo"))
    self.assertTrue(r.json()["ok"])
    p0.refresh_from_db(); b.refresh_from_db()
    self.assertEqual(p0.data, d)                     # A ripristinato
    self.assertEqual(b.data, d + timedelta(days=1))  # B ripristinato
```

- [ ] **Step 2: Esegui tutta la classe Gantt**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt --keepdb --settings=config.settings.test`
Expected: PASS (tutti). Se `test_cambio_macchina_compatibile` fallisce per via del nuovo flusso, verifica: con `giorni_delta=0` e cambio macchina senza conflitti, `piano` ha 1 riga → applica diretto (comportamento invariato).

- [ ] **Step 3: Commit**

```powershell
git add django_app/gestione_carichi_macchina/tests_gantt.py
git commit -m "test(gcm): adegua i test reschedule al parametro coda + undo multiplo"
```

---

### Task 6: Frontend — checkbox "coda" + modale di riepilogo slittamento

**Files:**
- Modify: `django_app/gestione_carichi_macchina/templates/gestione_carichi_macchina/gantt.html`

**Interfaces:**
- Consumes: risposta `reschedule` con `reason:"slittamento"` + `piano` (Task 4).

- [ ] **Step 1: Rinomina il checkbox e portalo a default OFF**

Sostituisci (riga ~468-470):

```html
    <label class="gflag" title="Sposta anche i lavori successivi sulla stessa macchina e turno">
      <input type="checkbox" id="g_cascata" checked> Cascata
    </label>
```

con:

```html
    <label class="gflag" title="Se attivo, il trascinamento sposta anche tutta la coda dei lavori successivi dello stesso numero di giorni. Se spento, sposta solo il lavoro e slitta i soli conflitti.">
      <input type="checkbox" id="g_cascata"> Sposta anche la coda
    </label>
```

- [ ] **Step 2: Aggiungi il markup del modale di riepilogo**

Subito dopo il modale `#gcm-add-ov` (dopo riga ~702, `</div>` di chiusura), inserisci:

```html
{# ── Modale: riepilogo slittamento (conferma spostamenti a catena) ── #}
<div class="gcm-ov" id="gcm-slit-ov">
  <div class="gcm-modal">
    <h3>Conferma spostamento <button type="button" data-close aria-label="Chiudi">&times;</button></h3>
    <div class="body">
      <p id="gcm-slit-intro" style="margin:0;font-size:.9rem;"></p>
      <div id="gcm-slit-list" style="display:grid;gap:6px;max-height:46vh;overflow:auto;"></div>
      <div class="actions">
        <button type="button" data-close>Annulla</button>
        <button type="button" class="primary" id="gcm-slit-ok">Conferma spostamento</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Sostituisci la gestione conflitto in `postMove` + rimuovi il confirm del drag temporale**

In `postMove` (riga ~832-834), sostituisci:

```javascript
      if (data && (data.reason === 'incompatibile' || data.reason === 'sovrapposizione')) {
        if (window.confirm(data.error || 'Spostare comunque?')) { params.forza = '1'; return postMove(d, params); }
        resetBar(d); return;
      }
```

con:

```javascript
      if (data && data.reason === 'incompatibile') {
        if (window.confirm(data.error || 'Spostare comunque?')) { params.forza = '1'; return postMove(d, params); }
        resetBar(d); return;
      }
      if (data && data.reason === 'slittamento') {
        gcmMostraSlittamento(data.piano || [], function () {
          params.conferma_slittamento = '1'; postMove(d, params);
        }, function () { resetBar(d); });
        return;
      }
```

Aggiungi la funzione modale (vicino a `postMove`, dentro la stessa IIFE):

```javascript
  function gcmMostraSlittamento(piano, onOk, onCancel) {
    var ov = document.getElementById('gcm-slit-ov');
    var intro = document.getElementById('gcm-slit-intro');
    var list = document.getElementById('gcm-slit-list');
    var ok = document.getElementById('gcm-slit-ok');
    if (!ov || !ok) { if (window.confirm('Questo spostamento sposta ' + piano.length + ' lavori. Confermare?')) { onOk(); } else { onCancel(); } return; }
    var n = Math.max(0, piano.length - 1);
    intro.textContent = n ? ('Questo spostamento richiede di slittare ' + n + (n === 1 ? ' lavoro:' : ' lavori:')) : 'Confermi lo spostamento?';
    list.innerHTML = piano.map(function (r, i) {
      var tag = i === 0 ? '<b>' + esc(r.etichetta) + '</b>' : esc(r.etichetta);
      return '<div style="display:flex;justify-content:space-between;gap:10px;font-size:.85rem;border-bottom:1px solid var(--g-border);padding-bottom:4px;">'
        + '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + tag + '</span>'
        + '<span style="white-space:nowrap;color:var(--g-light);">' + esc(r.da) + ' &rarr; ' + esc(r.a) + '</span></div>';
    }).join('');
    // handler one-shot: clono il bottone per azzerare listener precedenti
    var ok2 = ok.cloneNode(true); ok.parentNode.replaceChild(ok2, ok);
    ok2.addEventListener('click', function () { ov.classList.remove('open'); onOk(); });
    var cancelled = { done: false };
    function closer(e) {
      if (e.target === ov || (e.target.closest && e.target.closest('[data-close]'))) {
        ov.removeEventListener('click', closer);
        if (!cancelled.done) { cancelled.done = true; onCancel(); }
      }
    }
    ov.addEventListener('click', closer);
    openOv('gcm-slit-ov');
  }
```

Nota: `openOv` e `esc` sono già definiti nella stessa IIFE. Se `gcmMostraSlittamento` è collocata **prima** della definizione di `openOv`, va bene comunque (function declaration hoisted; `openOv` è anch'essa una function declaration nella stessa scope).

Poi, nel handler `mouseup` (righe ~869-875), **rimuovi il `window.confirm`** dello spostamento temporale semplice. Sostituisci:

```javascript
    var cascEl = document.getElementById('g_cascata');
    var casc = !!(cascEl && cascEl.checked);
    var verso = deltaDays > 0 ? 'avanti' : 'indietro';
    var m2 = 'Spostare la pianificazione di ' + Math.abs(deltaDays) + ' giorni ' + verso + '?';
    if (casc) m2 += '\n(Cascata attiva: sposto anche i lavori successivi sulla stessa macchina e turno)';
    if (!window.confirm(m2)) { resetBar(d); return; }
    postMove(d, { pianificazione_id: d.bar.getAttribute('data-id'), giorni_delta: deltaDays, cascata: casc ? '1' : '0' });
```

con:

```javascript
    var cascEl = document.getElementById('g_cascata');
    var casc = !!(cascEl && cascEl.checked);
    // Nessun conflitto -> il backend applica diretto; se c'è slittamento risponde
    // reason:"slittamento" e postMove apre il modale di riepilogo.
    postMove(d, { pianificazione_id: d.bar.getAttribute('data-id'), giorni_delta: deltaDays, coda: casc ? '1' : '0' });
```

- [ ] **Step 4: Verifica manuale nel browser**

Avvia il server e verifica il flusso end-to-end (vedi Task 8). Qui basta un controllo sintattico: apri la pagina Gantt, la console non deve mostrare errori JS al load.

Run: `.\.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: `System check identified no issues`.

- [ ] **Step 5: Commit**

```powershell
git add django_app/gestione_carichi_macchina/templates/gestione_carichi_macchina/gantt.html
git commit -m "feat(gcm): checkbox coda + modale riepilogo slittamento nel Gantt"
```

---

### Task 7: Aggiorna la legenda/hint del Gantt

**Files:**
- Modify: `django_app/gestione_carichi_macchina/templates/gestione_carichi_macchina/gantt.html`

- [ ] **Step 1: Aggiorna la stringa di hint**

Sostituisci (riga ~589):

```html
    <span>Trascina una barra per spostarla (snap al giorno, con conferma) · <b>Cascata</b> sposta anche i successivi · &#9888; = conflitto di capacità</span>
```

con:

```html
    <span>Trascina una barra per spostarla · in caso di conflitto i soli lavori sovrapposti slittano (con riepilogo e conferma) · <b>Sposta anche la coda</b> sposta tutti i successivi dello stesso delta · &#9888; = conflitto di capacità</span>
```

- [ ] **Step 2: Verifica render**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina.tests_gantt.GanttViewTest.test_gantt_page --keepdb --settings=config.settings.test`
Expected: PASS (la pagina renderizza).

- [ ] **Step 3: Commit**

```powershell
git add django_app/gestione_carichi_macchina/templates/gestione_carichi_macchina/gantt.html
git commit -m "docs(gcm): aggiorna hint Gantt per nuovo slittamento"
```

---

### Task 8: Verifica end-to-end nel browser + CHANGELOG/README

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: Avvia il server e prova il flusso**

Run (in background): `.\.venv\Scripts\python.exe django_app\manage.py runserver --settings=config.settings.dev`
Poi apri il Gantt (`/gestione-carichi-macchina/gantt/` o voce di menu), con almeno due lavori contigui sulla stessa macchina+turno. Verifica:
  1. Trascino su slot libero → salva senza popup.
  2. Trascino su slot occupato → compare il modale con l'elenco `A 22/06 → 23/06`, `B 23/06 → 24/06`; **Conferma** applica, **Annulla** ripristina la barra.
  3. Checkbox "Sposta anche la coda" attivo → il modale elenca tutta la coda.
  4. Undo ripristina tutti i lavori toccati.

- [ ] **Step 2: Esegui l'intera app di test del modulo**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test django_app.gestione_carichi_macchina --keepdb --settings=config.settings.test`
Expected: tutti PASS.

- [ ] **Step 3: Aggiorna CHANGELOG.md**

Sotto `## [Unreleased]`, aggiungi:

```markdown
### Fixed
- **Gestione carichi macchina / Gantt**: corretto lo slittamento nel drag-to-reschedule. Ora quando un lavoro viene spostato su uno slot occupato vengono spinti in avanti **solo** i lavori realmente in conflitto, del minimo necessario e in giorni lavorativi (prima l'intera coda si spostava dello stesso delta, con esiti sorprendenti). File: `django_app/gestione_carichi_macchina/views.py`, `.../templates/gestione_carichi_macchina/gantt.html`, `.../tests_gantt.py`.

### Changed
- **Gantt carichi macchina**: nuovo popup di riepilogo che elenca i lavori da spostare (da → a) e chiede conferma prima di applicare uno slittamento. Il checkbox "Cascata" è stato rinominato "Sposta anche la coda" (default OFF) e resta come strumento esplicito per spostare tutti i successivi dello stesso delta. Gli spostamenti senza conflitto vengono applicati diretti, senza conferma.
```

- [ ] **Step 4: Aggiorna README.md**

Nella sezione del modulo `gestione_carichi_macchina` (cerca "carichi macchina" nel `<details>` corrispondente), aggiorna la descrizione del Gantt per menzionare: "slittamento su conflitto con riepilogo e conferma; opzione «Sposta anche la coda»". Se non esiste una riga dedicata, aggiungi una frase nella descrizione del modulo nel catalogo.

- [ ] **Step 5: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(gcm): changelog e readme per slittamento su conflitto + popup"
```

---

## Self-Review

**Spec coverage:**
- Slittamento "spingi solo conflitti, minimo, giorni lavorativi" → Task 1, 2.
- Ramo coda (sposta tutta la coda) → Task 3.
- Preview `reason:"slittamento"` + apply su conferma + undo multiplo → Task 4, 5.
- Popup di riepilogo + checkbox rinominato default OFF + no-confirm senza conflitto → Task 6.
- Hint/legenda → Task 7.
- Verifica e2e + CHANGELOG/README → Task 8.
- Cambio macchina con conflitto sulla destinazione → coperto: `macchina_eff = target or p.macchina` passato a `_piano_slittamento` (Task 4).

**Placeholder scan:** nessun TBD/TODO; ogni step ha codice o comando concreto.

**Type consistency:** `_piano_slittamento(macchina_eff, p, nuova_data, coda=False, orizzonte=60)` usato coerentemente; righe piano con chiavi `id/etichetta/macchina/da/a` (date nell'helper, formattate `dd/mm` solo nella risposta HTTP di Task 4); parametro POST `coda` coerente tra backend (Task 4) e frontend (Task 6); risposta con `spostati` (int) e `coda` (bool) coerente con il frontend che ricarica se `spostati > 1` (riga esistente `data.macchina || data.spostati > 1`).

**Nota compatibilità:** il frontend esistente ricarica la pagina quando `data.spostati > 1` (riga ~838), quindi dopo uno slittamento multiplo la pagina si ricarica mostrando lo stato aggiornato — coerente col nuovo flusso.
