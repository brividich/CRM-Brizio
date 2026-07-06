# KICK-OFF (`tasks`) — Board per fase (Kanban trascinabile)

- **Data:** 2026-07-06
- **Modulo:** `django_app/tasks` (gestione KICK-OFF)
- **Branch:** `feature/skill-matrix-mod187`
- **Stato:** Design approvato, in attesa di piano
- **Prerequisiti:** F1 (UI) + F2 (readiness) — riusa il badge readiness.

---

## 1. Contesto e obiettivo

Feature "C" dal menu: una **vista Board (Kanban) per fase** delle commesse kickoff, come nei
portfolio dei tool PM. A differenza di readiness/da-gestire (derivati, sola lettura), qui l'utente
**decide la fase** e la sposta via drag&drop → serve un **campo fase persistente**.

**Valore:** vista d'insieme del portfolio per stato del ciclo di avvio, con spostamento diretto.
**Rischio:** medio (migrazione + endpoint di scrittura + drag).

---

## 2. Campo fase (migrazione + backfill)

Nuovo su `Project`:

```python
class ProjectPhase(models.TextChoices):
    BOZZA = "BOZZA", "Bozza"
    VRF = "VRF", "VRF"
    EXEC = "EXEC", "In esecuzione"
    DONE = "DONE", "Completata"

phase = models.CharField(max_length=10, choices=ProjectPhase.choices,
                         default=ProjectPhase.BOZZA, db_index=True)
```

**Backfill una-tantum** in migrazione (`RunPython`), derivato dallo stato attuale così le commesse
esistenti non finiscono tutte in "Bozza":

- ha attività **e** nessuna aperta (tutte done/canceled) → **DONE**
- ha attività aperte → **EXEC**
- nessuna attività ma `vrf_status = UPLOADED` → **VRF**
- altrimenti → **BOZZA**

Dopo il backfill, la fase è **manuale** (drag). Nessuna transizione automatica successiva.

Ordine colonne (fisso): BOZZA → VRF → EXEC → DONE.

---

## 3. Toggle vista sul portfolio

`project_list` accetta `?view=board|cards` (**default `cards`**). Interruttore **Card ⇄ Board**
nell'header del portfolio. Stessi filtri/scope/ordinamento e stesse annotazioni (incluso readiness,
già presente da F2). In modalità board le commesse sono raggruppate per `phase`.

---

## 4. UI board

- 4 colonne (le fasi) con intestazione + **conteggio**. Ogni colonna scrolla in verticale.
- Card commessa compatta: nome/KO number, cliente, **badge readiness** (F2), mini-KPI attività.
- Draggable; drop su un'altra colonna → cambio fase.
- Token/dark-safe; responsive (colonne che collassano su schermi stretti — scroll orizzontale del
  contenitore board).

---

## 5. Cambio fase (endpoint + permessi + ACL)

- Nuova route `tasks:project_set_phase` → `POST /tasks/projects/<id>/set-phase/`, view
  `project_set_phase(request, project_id)`:
  - valida `phase` ∈ `ProjectPhase.values` (altrimenti **JSON 400**);
  - **permessi**: solo chi ha `tasks.kickoff.edit` **o** gestisce la commessa
    (`_can_manage_project`) può spostare; altrimenti **JSON 403** (non redirect HTML);
  - aggiorna `project.phase` (`save(update_fields=["phase", "updated_at"])`), risponde **JSON**
    `{ok: true, phase, phase_label}`.
- **Drag&drop**: `fetch` POST con CSRF; UI **ottimistica** (sposta subito, rollback su errore).
- **Fallback accessibile**: ogni card ha un `<select>` fase che posta al medesimo endpoint (funziona
  senza drag). I non-editor vedono la board in **sola lettura** (niente drag, niente select).
- **ACL (obbligatorio):**
  - binding `"tasks:project_set_phase": "tasks.kickoff.edit"` in `acl_bootstrap._ROUTE_BINDINGS` +
    bump `_BOOTSTRAP_CACHE_KEY` (`v5` → `v6`);
  - **verificare** se il path `/tasks/projects/<id>/set-phase/` va aggiunto a
    `core/middleware.py` `API_ACL_GATE_PATHS` come gli altri endpoint JSON POST di tasks (es.
    `change_status`, `project_gantt_update_task`), così `ACL_STRICT_CANONICAL` restituisca **403
    JSON** e non un redirect HTML ai non autorizzati. Allinearsi al trattamento di quegli endpoint.

---

## 6. File e isolamento

**Modificati:**
- `tasks/models.py` (+`ProjectPhase`, +campo `phase`).
- Nuova migrazione `tasks/migrations/00NN_project_phase.py` (add field + backfill).
- `tasks/views.py` (`project_list` ramo board: raggruppa per fase; nuova view `project_set_phase`).
- `tasks/urls.py` (+route).
- `tasks/acl_bootstrap.py` (+binding, bump cache); `core/middleware.py` (se necessario, §5).
- `tasks/templates/tasks/projects.html` (toggle + include board).
- `tasks/static/tasks/css/tasks.css` (+`.kbf-*`).

**Nuovi:**
- `tasks/templates/tasks/_board.html` (colonne + JS drag inline) + `_board_card.html` (card).

**Regole progetto:** import modelli esterni locali nelle view; attributi template senza underscore
iniziale; JSON `401/403` per endpoint protetti (no redirect HTML).

---

## 7. Verifica

- **Migrazione/backfill**: derivazione corretta (DONE/EXEC/VRF/BOZZA) su fixture rappresentative.
- **`project_set_phase`**: aggiorna la fase; `phase` invalida → 400; editor → 200; non-editor → 403
  JSON; commessa fuori scope → 404/403.
- **Render board**: `?view=board` mostra 4 colonne, card con badge readiness, toggle presente; le
  card cadono nella colonna della loro fase.
- **ACL**: binding `tasks:project_set_phase → tasks.kickoff.edit` presente dopo bootstrap; (se
  aggiunto) path in `API_ACL_GATE_PATHS`.
- `test tasks.<Class> --settings=config.settings.test --keepdb`; `check`. Mai suite completa.

---

## 8. Confini (YAGNI)

**Fuori:** WIP-limit per colonna; storico/log delle transizioni di fase; transizioni automatiche
(oltre il backfill una-tantum); riordino manuale dentro la colonna; board su una pagina dedicata
(si usa il toggle sul portfolio). Nessun cambiamento alla logica esistente del portfolio (solo un
ramo `view=board` aggiuntivo).

---

## 9. Note operative

- Prod gira `feature/skill-matrix-mod187`; modifiche nel checkout locale. Applicare migrazione +
  bootstrap ACL in dev per rendere la feature attiva.
- A fine lavoro: `CHANGELOG.md` + `README.md`. Attenzione al working tree condiviso (staging mirato).
