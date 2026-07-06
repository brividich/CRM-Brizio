# KICK-OFF Board per fase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vista Board (Kanban) per fase sul portfolio Kickoff, con campo `Project.phase` persistente e drag&drop per cambiare fase.

**Architecture:** Nuovo campo `Project.phase` (4 fasi) con backfill una-tantum in migrazione. Toggle `?view=board|cards` su `project_list`; template board (colonne per fase) con card che riusano il badge readiness (F2). Cambio fase via endpoint `project_set_phase` (POST JSON, edit-permission) con binding ACL; drag&drop + `<select>` di fallback.

**Tech Stack:** Django 5.2 (TextChoices, migration RunPython), template SSR, fetch + HTML5 drag&drop, token CSS.

Spec: `docs/superpowers/specs/2026-07-06-tasks-kickoff-board-fase-design.md`

## Global Constraints

- **4 fasi (ordine fisso):** `BOZZA` "Bozza" → `VRF` "VRF" → `EXEC` "In esecuzione" → `DONE` "Completata". Default `BOZZA`.
- **Backfill derivato (una-tantum):** ha attività e nessuna aperta → `DONE`; ha attività aperte → `EXEC`; nessuna attività ma `vrf_status = UPLOADED` → `VRF`; altrimenti `BOZZA`. Stati aperti = `("TODO","IN_PROGRESS")`.
- **Default vista = `cards`**; board via toggle. `project_list` resta iso-funzionale per `view=cards`.
- **Cambio fase:** `POST /tasks/projects/<id>/set-phase/`; valida `phase ∈ ProjectPhase.values` (→ **400 JSON**); permesso = `tasks_edit` **o** `_can_manage_project` (→ **403 JSON** altrimenti); risponde JSON `{ok, phase, phase_label}`. Endpoint JSON → **niente redirect HTML** (come da CLAUDE.md).
- **ACL:** binding `"tasks:project_set_phase": "tasks.kickoff.edit"` in `acl_bootstrap._ROUTE_BINDINGS` + bump `_BOOTSTRAP_CACHE_KEY` (`v5` → `v6`). `API_ACL_GATE_PATHS` **non** va toccato (contiene solo prefissi `/api/`; gli endpoint JSON di tasks seguono binding + check in-view — stesso pattern di `change_status`).
- **Non modificare il tema:** solo token; dark-safe. Attributi template senza underscore iniziale. Import modelli esterni locali nelle view.
- **Test:** `.\.venv\Scripts\python.exe django_app\manage.py test tasks.<Class> --settings=config.settings.test --keepdb`. Mai suite completa.
- **Fixture:** `Project.objects.create(name=, created_by=user)` (NB: `save()` sovrascrive `name` con "KICK-OFF N" per i nuovi senza `kickoff_number` → nei test verificare via id, non per nome); `Task.objects.create(title=, created_by=user, project=, status=, due_date=)`.

## File Structure

**Nuovi:**
- `django_app/tasks/phase.py` — `derive_initial_phase(total, open_count, vrf_status) -> str` (logica pura, testabile; rispecchiata dal backfill).
- `django_app/tasks/migrations/0032_project_phase.py` — AddField + RunPython backfill.
- `django_app/tasks/templates/tasks/_board.html` — colonne board + JS drag.
- `django_app/tasks/templates/tasks/_board_card.html` — card commessa (con badge readiness + select fase).

**Modificati:**
- `django_app/tasks/models.py` (+`ProjectPhase`, +campo `phase`).
- `django_app/tasks/views.py` (`project_list`: `view`/`board_columns`/`is_board_editor`; nuova `project_set_phase`).
- `django_app/tasks/urls.py` (+route).
- `django_app/tasks/acl_bootstrap.py` (+binding, bump cache).
- `django_app/tasks/templates/tasks/projects.html` (toggle in `.pf-toolbar` + ramo board).
- `django_app/tasks/static/tasks/css/tasks.css` (+`.kbf-*`).
- `django_app/tasks/tests.py`, `CHANGELOG.md`, `README.md`.

---

## Task 1: campo `phase` + helper derivazione + migrazione con backfill

**Files:**
- Create: `django_app/tasks/phase.py`
- Modify: `django_app/tasks/models.py`
- Create: `django_app/tasks/migrations/0032_project_phase.py`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces: `tasks.models.ProjectPhase` (TextChoices), `Project.phase`; `tasks.phase.derive_initial_phase(total, open_count, vrf_status) -> str`.

- [ ] **Step 1: Test dell'helper (fallisce)**

In `tests.py`:

```python
class ProjectPhaseDeriveTests(TestCase):
    def test_derivation(self):
        from tasks.phase import derive_initial_phase
        assert derive_initial_phase(3, 0, "PENDING") == "DONE"      # tutte chiuse
        assert derive_initial_phase(3, 2, "PENDING") == "EXEC"      # aperte
        assert derive_initial_phase(0, 0, "UPLOADED") == "VRF"      # vrf ok, no task
        assert derive_initial_phase(0, 0, "PENDING") == "BOZZA"     # nulla
        assert derive_initial_phase(0, 0, "NOT_REQUIRED") == "BOZZA"
```

- [ ] **Step 2: Eseguire → fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ProjectPhaseDeriveTests --settings=config.settings.test --keepdb`
Expected: FAIL (`ModuleNotFoundError: tasks.phase`).

- [ ] **Step 3: Creare `django_app/tasks/phase.py`**

```python
"""Derivazione della fase iniziale della commessa (backfill una-tantum)."""
from __future__ import annotations


def derive_initial_phase(total: int, open_count: int, vrf_status: str) -> str:
    if total > 0 and open_count == 0:
        return "DONE"
    if open_count > 0:
        return "EXEC"
    if vrf_status == "UPLOADED":
        return "VRF"
    return "BOZZA"
```

- [ ] **Step 4: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ProjectPhaseDeriveTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Aggiungere `ProjectPhase` + campo `phase` a `models.py`**

Sopra `class Project` (vicino a `VRFDocStatus`):

```python
class ProjectPhase(models.TextChoices):
    BOZZA = "BOZZA", "Bozza"
    VRF = "VRF", "VRF"
    EXEC = "EXEC", "In esecuzione"
    DONE = "DONE", "Completata"
```

Dentro `class Project`, accanto a `vrf_status`:

```python
    phase = models.CharField(
        max_length=10, choices=ProjectPhase.choices,
        default=ProjectPhase.BOZZA, db_index=True, verbose_name="Fase",
    )
```

- [ ] **Step 6: Generare la migrazione schema**

Run: `.\.venv\Scripts\python.exe django_app\manage.py makemigrations tasks --settings=config.settings.dev`
Expected: crea `django_app/tasks/migrations/0032_project_phase.py` con `AddField`.

- [ ] **Step 7: Aggiungere il backfill alla migrazione**

Editare `0032_project_phase.py`: aggiungere la funzione e l'operazione `RunPython` **dopo** l'`AddField`:

```python
def _backfill_phase(apps, schema_editor):
    Project = apps.get_model("tasks", "Project")
    Task = apps.get_model("tasks", "Task")
    open_statuses = ("TODO", "IN_PROGRESS")
    for p in Project.objects.all().iterator():
        total = Task.objects.filter(project=p).count()
        open_count = Task.objects.filter(project=p, status__in=open_statuses).count()
        # Mirror di tasks.phase.derive_initial_phase (inline per freeze-safety)
        if total > 0 and open_count == 0:
            phase = "DONE"
        elif open_count > 0:
            phase = "EXEC"
        elif p.vrf_status == "UPLOADED":
            phase = "VRF"
        else:
            phase = "BOZZA"
        if p.phase != phase:
            p.phase = phase
            p.save(update_fields=["phase"])


def _noop(apps, schema_editor):
    pass
```

e nella lista `operations`, dopo l'`AddField`:

```python
        migrations.RunPython(_backfill_phase, _noop),
```

- [ ] **Step 8: Applicare la migrazione (test + dev)**

Run: `.\.venv\Scripts\python.exe django_app\manage.py migrate tasks --settings=config.settings.dev`
Run: `.\.venv\Scripts\python.exe django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` (Expected: No changes detected)

- [ ] **Step 9: Commit**

```powershell
git add django_app/tasks/phase.py django_app/tasks/models.py django_app/tasks/migrations/0032_project_phase.py django_app/tasks/tests.py
git commit -m "feat(tasks): Project.phase (4 fasi) + backfill derivato dallo stato"
```

---

## Task 2: endpoint `project_set_phase` + route + ACL

**Files:**
- Modify: `django_app/tasks/views.py` (nuova view, vicino a `project_list`)
- Modify: `django_app/tasks/urls.py`
- Modify: `django_app/tasks/acl_bootstrap.py`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces: route `tasks:project_set_phase` (POST) → JSON `{ok, phase, phase_label}`.

- [ ] **Step 1: Test (fallisce)**

```python
class ProjectSetPhaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="ph_admin", email="p@x.local", password="x"
        )
        cls.outsider = User.objects.create_user(username="ph_out", password="x")

    def _make_project(self):
        from tasks.models import Project
        return Project.objects.create(name="P", created_by=self.admin)

    def test_editor_can_set_phase(self):
        p = self._make_project()
        self.client.force_login(self.admin)
        r = self.client.post(reverse("tasks:project_set_phase", args=[p.id]), {"phase": "EXEC"})
        assert r.status_code == 200
        assert r.json()["phase"] == "EXEC"
        p.refresh_from_db()
        assert p.phase == "EXEC"

    def test_invalid_phase_400(self):
        p = self._make_project()
        self.client.force_login(self.admin)
        r = self.client.post(reverse("tasks:project_set_phase", args=[p.id]), {"phase": "NOPE"})
        assert r.status_code == 400

    def test_non_editor_403(self):
        p = self._make_project()
        self.client.force_login(self.outsider)
        r = self.client.post(reverse("tasks:project_set_phase", args=[p.id]), {"phase": "EXEC"})
        assert r.status_code == 403
        p.refresh_from_db()
        assert p.phase == "BOZZA"
```

- [ ] **Step 2: Eseguire → fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ProjectSetPhaseTests --settings=config.settings.test --keepdb`
Expected: FAIL (`NoReverseMatch: tasks:project_set_phase`).

- [ ] **Step 3: Aggiungere la view** in `views.py` (subito dopo `project_list`):

```python
@require_POST
@task_permissions_required("tasks_view")
def project_set_phase(request, project_id: int):
    from tasks.models import ProjectPhase

    project = get_object_or_404(_scoped_projects_queryset(request), pk=project_id)
    if not (_has_task_permission(request, "tasks_edit") or _can_manage_project(request, project)):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    phase = (request.POST.get("phase") or "").strip()
    if phase not in ProjectPhase.values:
        return JsonResponse({"ok": False, "error": "Fase non valida."}, status=400)
    if project.phase != phase:
        project.phase = phase
        project.save(update_fields=["phase", "updated_at"])
    return JsonResponse({"ok": True, "phase": phase, "phase_label": ProjectPhase(phase).label})
```

(Verificare che `require_POST`, `JsonResponse`, `get_object_or_404` siano già importati in `views.py`; sono usati altrove nel file.)

- [ ] **Step 4: Registrare la route** in `urls.py` (dopo `project_gantt`/`copy` o vicino alle route progetto):

```python
    path("tasks/projects/<int:project_id>/set-phase/", views.project_set_phase, name="project_set_phase"),
```

- [ ] **Step 5: Binding ACL + bump cache** in `acl_bootstrap.py`:

In `_ROUTE_BINDINGS`, nel gruppo "Modifica attività e Gantt" (vicino a `"tasks:change_status": "tasks.kickoff.edit",`):

```python
    "tasks:project_set_phase": "tasks.kickoff.edit",
```

Cambiare `_BOOTSTRAP_CACHE_KEY = "tasks_acl_bootstrap_v5"` → `"tasks_acl_bootstrap_v6"`.

- [ ] **Step 6: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ProjectSetPhaseTests --settings=config.settings.test --keepdb`
Expected: PASS (3 test). Se `test_non_editor_403` desse 200, verificare che `_can_manage_project` non conceda all'`outsider` (non è creatore né PM/CC) e che `tasks_edit` sia False per lui.

- [ ] **Step 7: Applicare bootstrap ACL in dev**

Run: `.\.venv\Scripts\python.exe django_app\manage.py shell --settings=config.settings.dev -c "from tasks.acl_bootstrap import bootstrap_tasks_acl_endpoints as b; b(force=True)"`

- [ ] **Step 8: Commit**

```powershell
git add django_app/tasks/views.py django_app/tasks/urls.py django_app/tasks/acl_bootstrap.py django_app/tasks/tests.py
git commit -m "feat(tasks): endpoint project_set_phase (POST JSON, edit) + binding ACL"
```

---

## Task 3: board UI (toggle + colonne + card + drag)

**Files:**
- Modify: `django_app/tasks/views.py` (`project_list`)
- Create: `django_app/tasks/templates/tasks/_board.html`, `_board_card.html`
- Modify: `django_app/tasks/templates/tasks/projects.html`
- Modify: `django_app/tasks/static/tasks/css/tasks.css`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: `Project.phase`, `ProjectPhase`, `project.readiness` (già presente da F2), route `tasks:project_set_phase`.
- Produces: contesto `view`, `board_columns` (lista di `{key,label,projects}`), `is_board_editor`.

- [ ] **Step 1: `project_list` — ramo board** — subito prima del `return render(...)` di `project_list`, aggiungere:

```python
    from tasks.models import ProjectPhase
    view_mode = "board" if request.GET.get("view") == "board" else "cards"
    board_columns = None
    is_board_editor = _has_task_permission(request, "tasks_edit")
    if view_mode == "board":
        by_phase = {key: [] for key, _ in ProjectPhase.choices}
        for p in projects:
            by_phase.get(getattr(p, "phase", ProjectPhase.BOZZA), by_phase[ProjectPhase.BOZZA]).append(p)
        board_columns = [
            {"key": key, "label": label, "projects": by_phase[key]}
            for key, label in ProjectPhase.choices
        ]
```

e nel dizionario di contesto del `render` aggiungere:

```python
            "view": view_mode,
            "board_columns": board_columns,
            "is_board_editor": is_board_editor,
            "phase_choices": ProjectPhase.choices,
```

- [ ] **Step 2: Card board** `django_app/tasks/templates/tasks/_board_card.html`:

```html
<div class="kbf-card" draggable="{{ is_board_editor|yesno:'true,false' }}" data-project-id="{{ project.id }}">
  <a class="kbf-card-name" href="{% url 'tasks:project_gantt' project.id %}">{{ project.name }}</a>
  {% if project.client_name %}<div class="kbf-card-client">{{ project.client_name }}</div>{% endif %}
  {% if project.readiness %}<div class="kbf-card-badge">{% include "tasks/_readiness_badge.html" with readiness=project.readiness %}</div>{% endif %}
  <div class="kbf-card-meta">
    <span>{{ project.task_open }} aperte</span><span>·</span><span>{{ project.task_total }} tot</span>
  </div>
  {% if is_board_editor %}
    <select class="kbf-card-move js-phase-select" data-project-id="{{ project.id }}" aria-label="Sposta fase">
      {% for key, label in phase_choices %}
        <option value="{{ key }}" {% if key == project.phase %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  {% endif %}
</div>
```

Nota: `phase_choices` arriva dal contesto — aggiungere `"phase_choices": ProjectPhase.choices` al dizionario di `render` in Step 1 (accanto a `view`/`board_columns`/`is_board_editor`).

- [ ] **Step 3: Colonne board + JS** `django_app/tasks/templates/tasks/_board.html`:

```html
<div class="kbf-board" data-set-phase-url="{% url 'tasks:project_list' %}">
  {% for col in board_columns %}
    <div class="kbf-col" data-phase="{{ col.key }}">
      <div class="kbf-col-head">
        <span class="kbf-col-label">{{ col.label }}</span>
        <span class="kbf-col-count">{{ col.projects|length }}</span>
      </div>
      <div class="kbf-col-body">
        {% for project in col.projects %}
          {% include "tasks/_board_card.html" with project=project is_board_editor=is_board_editor phase_choices=phase_choices %}
        {% empty %}
          <p class="kbf-col-empty">—</p>
        {% endfor %}
      </div>
    </div>
  {% endfor %}
</div>

{% if is_board_editor %}
<script>
(function () {
  var csrf = document.querySelector("meta[name='csrf-token']");
  csrf = csrf ? csrf.getAttribute("content") : "";
  function setPhase(projectId, phase, onOk, onErr) {
    fetch("/tasks/projects/" + projectId + "/set-phase/", {
      method: "POST",
      headers: {"X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest"},
      body: "phase=" + encodeURIComponent(phase)
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(function (d) { if (d && d.ok) onOk(); else onErr(); })
      .catch(function () { onErr(); });
  }
  var dragged = null;
  document.querySelectorAll(".kbf-card[draggable='true']").forEach(function (card) {
    card.addEventListener("dragstart", function () { dragged = card; card.classList.add("is-dragging"); });
    card.addEventListener("dragend", function () { card.classList.remove("is-dragging"); dragged = null; });
  });
  document.querySelectorAll(".kbf-col").forEach(function (col) {
    col.addEventListener("dragover", function (e) { e.preventDefault(); col.classList.add("is-over"); });
    col.addEventListener("dragleave", function () { col.classList.remove("is-over"); });
    col.addEventListener("drop", function (e) {
      e.preventDefault(); col.classList.remove("is-over");
      if (!dragged) return;
      var pid = dragged.getAttribute("data-project-id");
      var phase = col.getAttribute("data-phase");
      var body = col.querySelector(".kbf-col-body");
      var prev = dragged.parentNode;
      body.appendChild(dragged);  // ottimistico
      setPhase(pid, phase, function () {
        var sel = dragged && dragged.querySelector(".js-phase-select"); if (sel) sel.value = phase;
      }, function () { prev.appendChild(dragged); alert("Cambio fase non riuscito."); });
    });
  });
  document.querySelectorAll(".js-phase-select").forEach(function (sel) {
    sel.addEventListener("change", function () {
      var pid = sel.getAttribute("data-project-id");
      setPhase(pid, sel.value, function () { window.location.reload(); }, function () { alert("Cambio fase non riuscito."); });
    });
  });
})();
</script>
{% endif %}
```

- [ ] **Step 4: `projects.html` — toggle + ramo board** — nella `.pf-toolbar` (form GET, ~riga 362) aggiungere in coda ai campi, prima di `</form>`, i due bottoni (preservano i filtri):

```html
      <div class="ts-field">
        <label>Vista</label>
        <div class="pf-view-toggle">
          <button type="submit" name="view" value="cards" class="pf-view-btn {% if view != 'board' %}active{% endif %}">Card</button>
          <button type="submit" name="view" value="board" class="pf-view-btn {% if view == 'board' %}active{% endif %}">Board</button>
        </div>
      </div>
```

e avvolgere la griglia card esistente `.pf-grid` con il ramo:

```html
{% if view == 'board' %}
  {% include "tasks/_board.html" %}
{% else %}
  ... blocco esistente con <div class="pf-grid"> ... {% endfor %} ...
{% endif %}
```

(Individuare l'inizio `<div class="pf-grid">` e la sua chiusura per avvolgere solo quel blocco.)

- [ ] **Step 5: CSS** in `tasks.css` (in fondo):

```css
/* ── Board per fase ──────────────────────────────────────────────── */
.pf-view-toggle{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.pf-view-btn{border:none;background:var(--surface);color:var(--text-mid);font-size:12px;font-weight:700;padding:6px 12px;cursor:pointer}
.pf-view-btn.active{background:var(--accent);color:#fff}
.kbf-board{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;align-items:start;overflow-x:auto}
.kbf-col{background:color-mix(in srgb,var(--surface) 92%,var(--text) 8%);border:1px solid var(--border);border-radius:var(--hub-radius-lg);display:flex;flex-direction:column;min-height:120px}
.kbf-col.is-over{border-color:var(--accent);box-shadow:var(--hub-shadow-focus)}
.kbf-col-head{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid var(--border);font-weight:800;font-size:12px;color:var(--text)}
.kbf-col-count{background:var(--hub-status-neutral-bg);color:var(--text-mid);border-radius:999px;padding:1px 8px;font-size:11px}
.kbf-col-body{padding:8px;display:flex;flex-direction:column;gap:8px;flex:1}
.kbf-col-empty{color:var(--text-light);text-align:center;margin:8px 0}
.kbf-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--hub-radius-md);padding:10px;display:flex;flex-direction:column;gap:5px;box-shadow:var(--hub-shadow-sm)}
.kbf-card[draggable='true']{cursor:grab}
.kbf-card.is-dragging{opacity:.5}
.kbf-card-name{font-weight:800;color:var(--text);text-decoration:none;font-size:13px}
.kbf-card-name:hover{color:var(--accent)}
.kbf-card-client{font-size:11px;color:var(--text-mid)}
.kbf-card-meta{display:flex;gap:6px;font-size:11px;color:var(--text-light)}
.kbf-card-move{margin-top:4px;font-size:11px;padding:3px 6px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text)}
@media (max-width:900px){.kbf-board{grid-template-columns:repeat(2,minmax(200px,1fr))}}
```

- [ ] **Step 6: Smoke test**

```python
class ProjectBoardRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="brd_admin", email="b@x.local", password="x"
        )

    def setUp(self):
        from tasks.models import Project
        self.client.force_login(self.admin)
        Project.objects.create(name="P1", created_by=self.admin)

    def test_board_view_renders_columns(self):
        r = self.client.get(reverse("tasks:project_list") + "?view=board")
        assert r.status_code == 200
        assert b"kbf-board" in r.content
        assert b"In esecuzione" in r.content  # etichetta colonna
        assert b"data-set-phase-url" in r.content

    def test_cards_view_default(self):
        r = self.client.get(reverse("tasks:project_list"))
        assert r.status_code == 200
        assert b"pf-grid" in r.content
        assert b"kbf-board" not in r.content
```

- [ ] **Step 7: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ProjectBoardRenderTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add django_app/tasks/views.py django_app/tasks/templates/tasks/_board.html django_app/tasks/templates/tasks/_board_card.html django_app/tasks/templates/tasks/projects.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/tests.py
git commit -m "feat(tasks): board per fase sul portfolio (toggle Card/Board + drag&drop)"
```

---

## Task 4: documentazione

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: CHANGELOG** — `[Unreleased] / ### Added`: "KICK-OFF · Board per fase (Kanban): campo `Project.phase` (Bozza/VRF/In esecuzione/Completata, backfill derivato), toggle Card/Board sul portfolio, drag&drop + `<select>` fallback, endpoint `project_set_phase` (edit, JSON) con binding ACL." Elencare i file. **Attenzione al working tree condiviso**: se `CHANGELOG.md` risulta modificato da altra sessione, stageare solo il proprio hunk (`git add -p`).

- [ ] **Step 2: README** — sezione modulo `tasks`: aggiungere "Board per fase (vista Kanban trascinabile sul portfolio)".

- [ ] **Step 3: Verifica finale**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ProjectPhaseDeriveTests tasks.tests.ProjectSetPhaseTests tasks.tests.ProjectBoardRenderTests --settings=config.settings.test --keepdb`
Run: `.\.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: PASS + no issues.

- [ ] **Step 4: Commit** (staging mirato se CHANGELOG ha WIP altrui)

```powershell
git add README.md
git commit -m "docs(tasks): CHANGELOG + README — board per fase KICK-OFF"
```

---

## Self-Review (esito)

**Copertura spec:** §2 campo/backfill → Task 1 (helper testato + migrazione); §3 toggle → Task 3 (Step 1/4); §4 UI board → Task 3 (colonne/card/CSS); §5 endpoint/ACL → Task 2 (view/route/binding/bump); §6 file → coperti; §7 verifica → helper unit + endpoint (200/400/403) + render board; §8 YAGNI → nessun WIP-limit/storico/pagina dedicata.

**Placeholder scan:** in Task 3 Step 2 c'è una **correzione esplicita** (rimuovere `{% load %}`, passare `phase_choices` dal contesto) — applicarla; nessun altro TBD. `00NN`→`0032` risolto.

**Coerenza tipi/nomi:** `ProjectPhase` (BOZZA/VRF/EXEC/DONE); `Project.phase`; `derive_initial_phase(total, open_count, vrf_status)`; route `tasks:project_set_phase`; contesto `view`/`board_columns`/`is_board_editor`/`phase_choices`; classi `.kbf-*`/`.pf-view-*`; binding `tasks.kickoff.edit` — coerenti tra i task.
