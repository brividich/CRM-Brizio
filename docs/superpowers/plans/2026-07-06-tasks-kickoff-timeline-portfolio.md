# KICK-OFF Timeline cross-commessa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Terza vista "Timeline" sul portfolio Kickoff: roadmap cross-commessa con una barra per commessa (span derivato dai task), colorata per readiness.

**Architecture:** Logica pura in `tasks/timeline.py` (`build_portfolio_timeline`, geometria a percentuali), ramo `view=timeline` in `project_list` che annota lo span (Min/Max sui task) e riusa `project.readiness`. Template SSR con barre absolute-positioned. Nessuna route/migrazione/ACL nuova.

**Tech Stack:** Django 5.2 (Min/Max/Coalesce), template SSR, CSS token.

Spec: `docs/superpowers/specs/2026-07-06-tasks-kickoff-timeline-portfolio-design.md`

## Global Constraints

- **Nessuna migrazione, nessuna route/ACL nuova** (riusa `project_list`, già bound). **Sola lettura.**
- **Span:** inizio = `Min(Coalesce(tasks.next_step_due, tasks.due_date))`, fine = `Max(tasks.due_date)`. Commesse senza span → niente barra, nota separata. `end < start` → clamp `end=start`.
- **Colore barre = readiness** (`ready`/`partial`/`notready`; `na` se assente).
- **Finestra auto-fit** al range dei dati, **incluso `today`**; scroll orizzontale.
- **Prefisso CSS `.ptl-*`** (NON `.tl-*`, già usato dalla tabella backlog in `list.html`).
- Import modelli/funzioni locali nelle view; attributi template senza underscore iniziale.
- **Test:** `.\.venv\Scripts\python.exe django_app\manage.py test tasks.<Class> --settings=config.settings.test --keepdb`. Mai suite completa.
- **Fixture:** `Task.objects.create(title=, created_by=user, project=p, next_step_due=<date>, due_date=<date>)` per dare uno span; `Project.objects.create(name=, created_by=user)` (name auto → verificare per id).

## File Structure

**Nuovi:** `tasks/timeline.py`, `tasks/templates/tasks/_timeline.html`.
**Modificati:** `tasks/views.py` (`project_list` ramo timeline), `tasks/templates/tasks/projects.html` (terzo toggle + branch), `tasks/static/tasks/css/tasks.css` (+`.ptl-*`), `tasks/tests.py`, `CHANGELOG.md`, `README.md`.

---

## Task 1: `timeline.py` — geometria roadmap pura

**Files:** Create `django_app/tasks/timeline.py`; Test `django_app/tasks/tests.py`.

**Interfaces:** `build_portfolio_timeline(items, today) -> dict` con `months` (`{label,left_pct,width_pct}`), `rows` (`{project,readiness,start,end,left_pct,width_pct}`), `today_pct`, `empty`, `window_start`, `window_end`. `items = [{project, start, end, readiness}]`.

- [ ] **Step 1: Test (fallisce)**

```python
class PortfolioTimelineTests(TestCase):
    def test_geometry_and_window(self):
        from datetime import date
        from tasks.timeline import build_portfolio_timeline
        items = [
            {"project": "A", "start": date(2026, 3, 1), "end": date(2026, 4, 30), "readiness": None},
            {"project": "B", "start": date(2026, 6, 1), "end": date(2026, 6, 15), "readiness": None},
        ]
        tl = build_portfolio_timeline(items, today=date(2026, 5, 10))
        assert tl["empty"] is False
        assert tl["window_start"] == date(2026, 3, 1)
        assert tl["window_end"] == date(2026, 6, 30)
        assert len(tl["months"]) == 4
        assert tl["rows"][0]["left_pct"] == 0.0
        assert 0 < tl["today_pct"] < 100

    def test_empty(self):
        from datetime import date
        from tasks.timeline import build_portfolio_timeline
        tl = build_portfolio_timeline([{"project": "X", "start": None, "end": None}], today=date(2026, 5, 1))
        assert tl["empty"] is True and tl["rows"] == []

    def test_clamp_end_before_start(self):
        from datetime import date
        from tasks.timeline import build_portfolio_timeline
        tl = build_portfolio_timeline(
            [{"project": "C", "start": date(2026, 5, 10), "end": date(2026, 5, 1)}],
            today=date(2026, 5, 5),
        )
        assert tl["rows"][0]["end"] == date(2026, 5, 10)
```

- [ ] **Step 2: Eseguire → fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.PortfolioTimelineTests --settings=config.settings.test --keepdb`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Creare `django_app/tasks/timeline.py`**

```python
"""Roadmap portfolio: geometria della timeline cross-commessa (logica pura)."""
from __future__ import annotations

import calendar as _cal
from datetime import date

_MONTHS_ABBR = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _month_end(d: date) -> date:
    return date(d.year, d.month, _cal.monthrange(d.year, d.month)[1])


def _next_month(y: int, m: int):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def build_portfolio_timeline(items, today: date) -> dict:
    dated = [dict(it) for it in items if it.get("start") and it.get("end")]
    for it in dated:
        if it["end"] < it["start"]:
            it["end"] = it["start"]
    if not dated:
        return {"months": [], "rows": [], "today_pct": None, "empty": True,
                "window_start": None, "window_end": None}

    window_start = _month_start(min([it["start"] for it in dated] + [today]))
    window_end = _month_end(max([it["end"] for it in dated] + [today]))
    total_days = (window_end - window_start).days + 1

    def pct(d: date) -> float:
        return (d - window_start).days / total_days * 100

    months = []
    y, m = window_start.year, window_start.month
    while (y, m) <= (window_end.year, window_end.month):
        ms = date(y, m, 1)
        me = _month_end(ms)
        months.append({
            "label": f"{_MONTHS_ABBR[m]} {str(y)[2:]}",
            "left_pct": round(pct(ms), 4),
            "width_pct": round(((me - ms).days + 1) / total_days * 100, 4),
        })
        y, m = _next_month(y, m)

    rows = []
    for it in dated:
        width = max(((it["end"] - it["start"]).days + 1) / total_days * 100, 1.2)
        rows.append({
            "project": it["project"], "readiness": it.get("readiness"),
            "start": it["start"], "end": it["end"],
            "left_pct": round(pct(it["start"]), 4), "width_pct": round(width, 4),
        })

    today_pct = round(pct(today), 4) if window_start <= today <= window_end else None
    return {"months": months, "rows": rows, "today_pct": today_pct, "empty": False,
            "window_start": window_start, "window_end": window_end}
```

- [ ] **Step 4: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.PortfolioTimelineTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/timeline.py django_app/tasks/tests.py
git commit -m "feat(tasks): timeline.py — geometria roadmap portfolio (logica pura)"
```

---

## Task 2: ramo `view=timeline` + template + toggle + CSS

**Files:** Modify `tasks/views.py`, `tasks/templates/tasks/projects.html`, `tasks/static/tasks/css/tasks.css`; Create `tasks/templates/tasks/_timeline.html`; Test `tasks/tests.py`.

- [ ] **Step 1: `project_list` — accettare `timeline` e costruire i dati**

In `views.py`, `project_list`: cambiare la riga del view_mode (dal ramo Board di C):

```python
    _v = request.GET.get("view")
    view_mode = _v if _v in ("board", "timeline") else "cards"
```

Dopo il blocco `if view_mode == "board":` aggiungere:

```python
    timeline = None
    timeline_undated = []
    if view_mode == "timeline":
        from django.db.models import Max, Min
        from django.db.models.functions import Coalesce
        from tasks.timeline import build_portfolio_timeline
        spans = {
            r["id"]: (r["tl_start"], r["tl_end"])
            for r in Project.objects.filter(id__in=[p.id for p in projects]).annotate(
                tl_start=Min(Coalesce("tasks__next_step_due", "tasks__due_date")),
                tl_end=Max("tasks__due_date"),
            ).values("id", "tl_start", "tl_end")
        }
        items = []
        for p in projects:
            s, e = spans.get(p.id, (None, None))
            if s and e:
                items.append({"project": p, "start": s, "end": e, "readiness": getattr(p, "readiness", None)})
            else:
                timeline_undated.append(p)
        timeline = build_portfolio_timeline(items, timezone.localdate())
```

e nel dizionario di `render` aggiungere:

```python
            "timeline": timeline,
            "timeline_undated": timeline_undated,
```

- [ ] **Step 2: Template** `django_app/tasks/templates/tasks/_timeline.html`:

```html
{% if timeline.empty %}
  <p class="ptl-empty">Nessuna commessa con date pianificate.</p>
{% else %}
<div class="ptl-scroll">
  <div class="ptl-timeline">
    <div class="ptl-row ptl-row--head">
      <div class="ptl-row-label"></div>
      <div class="ptl-row-track ptl-head-track">
        {% for mo in timeline.months %}
          <div class="ptl-month" style="left:{{ mo.left_pct }}%;width:{{ mo.width_pct }}%;">{{ mo.label }}</div>
        {% endfor %}
      </div>
    </div>
    {% for row in timeline.rows %}
      <div class="ptl-row">
        <div class="ptl-row-label">
          <a href="{% url 'tasks:project_gantt' row.project.id %}">{{ row.project.name }}</a>
          {% if row.readiness %}{% include "tasks/_readiness_badge.html" with readiness=row.readiness %}{% endif %}
        </div>
        <div class="ptl-row-track">
          {% if timeline.today_pct is not None %}<div class="ptl-today" style="left:{{ timeline.today_pct }}%;"></div>{% endif %}
          <div class="ptl-bar ptl-bar--{{ row.readiness.level|default:'na' }}" style="left:{{ row.left_pct }}%;width:{{ row.width_pct }}%;" title="{{ row.start|date:'d/m/Y' }} – {{ row.end|date:'d/m/Y' }}"></div>
        </div>
      </div>
    {% endfor %}
  </div>
</div>
{% endif %}
{% if timeline_undated %}
  <p class="ptl-note">{{ timeline_undated|length }} commesse senza date pianificate (visibili nella vista Card).</p>
{% endif %}
```

- [ ] **Step 3: CSS** in `tasks.css` (in fondo):

```css
/* ── Timeline portfolio (roadmap) ────────────────────────────────── */
.ptl-scroll{overflow-x:auto}
.ptl-timeline{display:flex;flex-direction:column;gap:5px;min-width:820px}
.ptl-row{display:flex;gap:10px;align-items:center}
.ptl-row-label{width:210px;flex-shrink:0;display:flex;flex-direction:column;gap:3px;font-size:12px}
.ptl-row-label a{font-weight:800;color:var(--text);text-decoration:none}
.ptl-row-label a:hover{color:var(--accent)}
.ptl-row-track{position:relative;flex:1;height:26px;background:color-mix(in srgb,var(--surface) 92%,var(--text) 8%);border-radius:6px}
.ptl-head-track{height:18px;background:transparent}
.ptl-month{position:absolute;top:0;font-size:10px;font-weight:800;text-transform:uppercase;color:var(--text-mid);border-left:1px solid var(--border);padding-left:4px;box-sizing:border-box;overflow:hidden;white-space:nowrap}
.ptl-today{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--accent);z-index:2}
.ptl-bar{position:absolute;top:4px;height:18px;border-radius:5px;min-width:4px;background:var(--hub-status-neutral)}
.ptl-bar--ready{background:var(--hub-status-success)}
.ptl-bar--partial{background:var(--hub-status-warning)}
.ptl-bar--notready{background:var(--hub-status-danger)}
.ptl-empty,.ptl-note{color:var(--text-mid);font-size:13px;margin:8px 2px}
```

- [ ] **Step 4: `projects.html` — terzo bottone toggle + branch**

Nel `.pf-view-toggle` sostituire i due bottoni con tre:

```html
      <div class="pf-view-toggle">
        <button type="submit" name="view" value="cards" class="pf-view-btn {% if view == 'cards' or not view %}active{% endif %}">Card</button>
        <button type="submit" name="view" value="board" class="pf-view-btn {% if view == 'board' %}active{% endif %}">Board</button>
        <button type="submit" name="view" value="timeline" class="pf-view-btn {% if view == 'timeline' %}active{% endif %}">Timeline</button>
      </div>
```

E nel body del pannello aggiungere il ramo timeline prima di `{% elif projects %}`:

```html
    {% if view == 'board' %}
      {% include "tasks/_board.html" %}
    {% elif view == 'timeline' %}
      {% include "tasks/_timeline.html" %}
    {% elif projects %}
```

- [ ] **Step 5: Smoke test**

```python
class PortfolioTimelineRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="tl_admin", email="t@x.local", password="x"
        )

    def setUp(self):
        from tasks.models import Project, Task
        self.client.force_login(self.admin)
        p = Project.objects.create(name="P", created_by=self.admin)
        Task.objects.create(
            title="t", created_by=self.admin, project=p,
            next_step_due=timezone.localdate(),
            due_date=timezone.localdate() + timedelta(days=20),
        )

    def test_timeline_view_renders_bar(self):
        r = self.client.get(reverse("tasks:project_list") + "?view=timeline")
        assert r.status_code == 200
        assert b"ptl-timeline" in r.content
        assert b"ptl-bar" in r.content

    def test_cards_still_default(self):
        r = self.client.get(reverse("tasks:project_list"))
        assert r.status_code == 200
        assert b"ptl-timeline" not in r.content
```

- [ ] **Step 6: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.PortfolioTimelineRenderTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add django_app/tasks/views.py django_app/tasks/templates/tasks/_timeline.html django_app/tasks/templates/tasks/projects.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/tests.py
git commit -m "feat(tasks): terza vista Timeline sul portfolio (roadmap per readiness)"
```

---

## Task 3: documentazione

- [ ] **Step 1: CHANGELOG** — `[Unreleased] / ### Added`: "KICK-OFF · Timeline cross-commessa: terza vista `?view=timeline` sul portfolio (roadmap, una barra per commessa con span derivato dai task, colore per readiness, marcatore oggi); `tasks/timeline.py`." **Staging mirato** se CHANGELOG ha WIP di altra sessione (`git add -p`).
- [ ] **Step 2: README** — sezione modulo `tasks`: aggiungere "Timeline cross-commessa (terza vista roadmap sul portfolio)".
- [ ] **Step 3: Verifica finale**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.PortfolioTimelineTests tasks.tests.PortfolioTimelineRenderTests --settings=config.settings.test --keepdb`
Run: `.\.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: PASS + no issues.

- [ ] **Step 4: Commit** (staging mirato)

```powershell
git add README.md
git commit -m "docs(tasks): CHANGELOG + README — timeline cross-commessa KICK-OFF"
```

---

## Self-Review (esito)

**Copertura spec:** §2 span (annotazioni) → Task 2 Step 1; §3 terza vista → Task 2 (view_mode + toggle); §4 unità pura → Task 1; §5 senza date → Task 2 (`timeline_undated` + nota); §6 UI → Task 2 (template/CSS); §7 file → coperti; §8 verifica → unit + smoke.

**Placeholder scan:** nessun TBD. **Coerenza tipi/nomi:** `build_portfolio_timeline(items, today)` → `months/rows/today_pct/empty/window_start/window_end`; contesto `timeline`/`timeline_undated`; classi `.ptl-*`; `view=timeline` — coerenti tra i task e con `project_list` (view_mode già introdotto da C, qui esteso).
