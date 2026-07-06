# KICK-OFF (`tasks`) — Timeline cross-commessa (portfolio roadmap)

- **Data:** 2026-07-06
- **Modulo:** `django_app/tasks` (gestione KICK-OFF)
- **Branch:** `feature/skill-matrix-mod187`
- **Stato:** Design approvato, in attesa di piano
- **Prerequisiti:** F2 (readiness, per il colore delle barre), C (toggle vista sul portfolio).

---

## 1. Contesto e obiettivo

Feature "E" (ultima del menu): una **timeline/roadmap cross-commessa** che mostra tutte le commesse
kickoff in scope su un'unica linea temporale, **una barra per commessa**, colorata per **readiness**
(F2). È la vista d'insieme direzionale del portfolio.

**Terza vista sul portfolio**: sul toggle esistente Card ⇄ Board si aggiunge **Timeline**
(`?view=timeline`). Nessuna nuova route/subnav (riusa `project_list`, già bound), **nessuna
migrazione** (lo span si deriva dai dati task esistenti).

---

## 2. Derivazione dello span (annotazioni, no migrazione)

Le attività usano `next_step_due` come **inizio** e `due_date` come **fine** (vincolo nel modello
`Task.clean`; stessa semantica del Gantt per-progetto). Per ogni commessa in scope si annota:

```python
from django.db.models import Min, Max
from django.db.models.functions import Coalesce
qs.annotate(
    tl_start=Min(Coalesce("tasks__next_step_due", "tasks__due_date")),
    tl_end=Max("tasks__due_date"),
)
```

- **inizio** = `tl_start` (prima data pianificata tra i task); **fine** = `tl_end` (ultima scadenza).
- Commesse con `tl_start` o `tl_end` nulli (nessun task datato) → **niente barra** (§5).
- Se `tl_end < tl_start` (dato incoerente), clamp `end = start` (barra minima).

---

## 3. Terza vista sul portfolio

`project_list` accetta ora `view ∈ {cards, board, timeline}` (default `cards`). In `view=timeline`:
materializza i progetti (già annotati con readiness da F2 e con `tl_start`/`tl_end`), costruisce gli
`items` con span+readiness e chiama `build_portfolio_timeline`. Stessi filtri/scope/ordinamento.

Toggle nel `.pf-toolbar`: tre bottoni submit `name="view"` → `cards` · `board` · `timeline`.

---

## 4. Unità pura testabile

Nuovo `django_app/tasks/timeline.py`:

```python
def build_portfolio_timeline(items, today) -> dict:
    """items: lista di {project, start: date, end: date, readiness}.
    Ritorna {months, rows, today_pct, empty, window_start, window_end}."""
```

- **Finestra**: `window_start` = inizio del mese di `min(min(start_i), today)`; `window_end` = fine del
  mese di `max(max(end_i), today)` (così il marcatore "oggi" è sempre nella finestra). Auto-fit al
  range dei dati.
- **months**: lista dei mesi della finestra con `label` (Mmm YY) e `width_pct` (proporzionale ai
  giorni del mese nella finestra) e `left_pct`.
- **rows**: per ogni item `{project, readiness, left_pct, width_pct, start, end}` — geometria a livello
  **giorno** sulla finestra (`left_pct = (start - window_start).days / total_days * 100`,
  `width_pct = ((end - start).days + 1) / total_days * 100`, con una `width` minima visibile).
- **today_pct**: posizione del marcatore "oggi".
- **empty**: `True` se nessun item con date. Nessun accesso DB → test deterministici (`today` iniettato).

---

## 5. Commesse senza date

Le commesse senza span (nessun task datato) **non** producono barre; sotto la timeline una nota
"**N commesse senza date pianificate**" (con link al portfolio Card per vederle). Passate al template
come conteggio/lista separata.

---

## 6. Timeline UI (server-side, niente librerie JS)

- Header mesi (celle con `width_pct`, label Mmm YY).
- Una **riga per commessa**: a sinistra nome + **badge readiness**; a destra la **track** con la
  **barra** posizionata (`left`/`width` in %), colorata per readiness
  (`--hub-status-success/warning/danger`), con tooltip `inizio – fine`.
- **Marcatore "oggi"**: linea verticale a `today_pct`.
- **Scroll orizzontale** se la finestra è larga (contenitore `overflow-x:auto`, `min-width`).
- Token/dark-safe. Prefisso classi **`.ptl-*`** (portfolio-timeline) per **non collidere** con le
  `.tl-*` della tabella backlog in `list.html`.

---

## 7. File

**Nuovi:** `tasks/timeline.py`, `tasks/templates/tasks/_timeline.html`.
**Modificati:** `tasks/views.py` (`project_list` ramo timeline), `tasks/templates/tasks/projects.html`
(terzo bottone toggle + branch include), `tasks/static/tasks/css/tasks.css` (+`.ptl-*`),
`tasks/tests.py`, `CHANGELOG.md`, `README.md`.

**Regole progetto:** import modelli/funzioni locali nelle view; attributi template senza underscore
iniziale.

---

## 8. Verifica

- **`build_portfolio_timeline`**: finestra auto-fit (include `today`), mesi corretti (numero/label),
  geometria barra (una commessa a inizio finestra → `left≈0`; a fine → `left+width≈100`),
  `today_pct` nel range, `empty=True` senza item; item con `end<start` → clamp.
- **Smoke render** `?view=timeline`: 200, contenitore `ptl-timeline`, una barra per commessa datata,
  nota per le non datate; `view=cards`/`board` invariati.
- `test tasks.<Class> --settings=config.settings.test --keepdb`; `check`. Mai suite completa.

---

## 9. Confini (YAGNI)

**Fuori:** barre a livello task (è il Gantt per-progetto esistente); drag/resize/dipendenze sulla
timeline; zoom settimana/giorno; finestra navigabile prev/next (si usa l'auto-fit); milestone;
export. Solo roadmap read-only, una barra per commessa.

---

## 10. Note operative

Prod gira `feature/skill-matrix-mod187`; modifiche nel checkout locale. Nessuna migrazione/bootstrap
da applicare (riusa route/annotazioni). A fine lavoro `CHANGELOG.md` + `README.md` (staging mirato se
working tree condiviso).
