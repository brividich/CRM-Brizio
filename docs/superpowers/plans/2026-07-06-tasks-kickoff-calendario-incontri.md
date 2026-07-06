# KICK-OFF Calendario incontri — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pagina calendario mensile cross-commessa di tutti gli incontri kickoff nello scope.

**Architecture:** Logica pura in `tasks/calendario.py` (`build_meetings_calendar`, usa `calendar` stdlib), view sottile che filtra i `KickoffMeeting` in scope per il mese, template griglia SSR (niente librerie JS). Nuova route + subnav + binding ACL.

**Tech Stack:** Django 5.2, `calendar` stdlib, template SSR, token CSS.

Spec: `docs/superpowers/specs/2026-07-06-tasks-kickoff-calendario-incontri-design.md`

## Global Constraints

- **Sola lettura**, niente librerie JS. Griglia settimane **Lun–Dom**.
- **Scope:** `KickoffMeeting.objects.filter(project__in=_scoped_projects_queryset(request), data__year=Y, data__month=M)`. Nessun toggle "le mie".
- **Route** `tasks:incontri_calendario` → `/tasks/incontri-calendario/`; `?m=YYYY-MM` (default mese corrente, `timezone.localdate()`).
- **ACL:** binding `"tasks:incontri_calendario": "tasks.kickoff.view"` + bump `_BOOTSTRAP_CACHE_KEY` (`v6` → `v7`). Pagina (non `/api/`) → niente `API_ACL_GATE_PATHS`.
- **Subnav:** `NavigationItem` "Calendario" (`section="subnav"`, `parent_code="tasks"`, `required_permission_code="tasks.kickoff.view"`, order 25).
- Import modelli esterni locali nelle view; attributi template senza underscore iniziale.
- **Test:** `.\.venv\Scripts\python.exe django_app\manage.py test tasks.<Class> --settings=config.settings.test --keepdb`. Mai suite completa.
- **Fixture:** `KickoffMeeting.objects.create(project=p, numero=1, titolo="x", data=<date>, created_by=user)`.

## File Structure

**Nuovi:** `tasks/calendario.py`, `tasks/templates/tasks/incontri_calendario.html`, `core/migrations/0063_tasks_calendario_subnav.py`.
**Modificati:** `tasks/views.py` (+view), `tasks/urls.py` (+route), `tasks/acl_bootstrap.py` (+binding, bump), `tasks/static/tasks/css/tasks.css` (+`.cal-*`), `tasks/tests.py`, `CHANGELOG.md`, `README.md`.

---

## Task 1: `calendario.py` — griglia mensile pura

**Files:** Create `django_app/tasks/calendario.py`; Test `django_app/tasks/tests.py`.

**Interfaces:** `build_meetings_calendar(meetings, year, month, today=None) -> dict` con `weeks` (lista di settimane; ogni giorno = `{date, in_month, is_today, meetings}`), `month_label`, `prev`, `next`, `year`, `month`, `today`.

- [ ] **Step 1: Test (fallisce)**

```python
class MeetingsCalendarTests(TestCase):
    def test_grid_and_placement(self):
        import types
        from datetime import date
        from tasks.calendario import build_meetings_calendar
        m = types.SimpleNamespace(data=date(2026, 7, 15))
        cal = build_meetings_calendar([m], 2026, 7, today=date(2026, 7, 6))
        assert cal["month_label"] == "Luglio 2026"
        assert cal["prev"] == "2026-06" and cal["next"] == "2026-08"
        assert all(len(w) == 7 for w in cal["weeks"])
        placed = [d for w in cal["weeks"] for d in w if d["date"] == date(2026, 7, 15)]
        assert placed and placed[0]["meetings"] == [m]
        todays = [d for w in cal["weeks"] for d in w if d["is_today"]]
        assert len(todays) == 1 and todays[0]["date"] == date(2026, 7, 6)

    def test_year_boundary(self):
        from tasks.calendario import build_meetings_calendar
        assert build_meetings_calendar([], 2026, 1)["prev"] == "2025-12"
        assert build_meetings_calendar([], 2026, 12)["next"] == "2027-01"
```

- [ ] **Step 2: Eseguire → fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.MeetingsCalendarTests --settings=config.settings.test --keepdb`
Expected: FAIL (`ModuleNotFoundError: tasks.calendario`).

- [ ] **Step 3: Creare `django_app/tasks/calendario.py`**

```python
"""Griglia calendario mensile degli incontri kickoff (logica pura)."""
from __future__ import annotations

import calendar as _cal

_MONTHS_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _prev_next(year: int, month: int):
    prev = (year - 1, 12) if month == 1 else (year, month - 1)
    nxt = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{prev[0]:04d}-{prev[1]:02d}", f"{nxt[0]:04d}-{nxt[1]:02d}"


def build_meetings_calendar(meetings, year: int, month: int, today=None) -> dict:
    by_day = {}
    for m in meetings:
        by_day.setdefault(m.data, []).append(m)
    grid = _cal.Calendar(firstweekday=0).monthdatescalendar(year, month)  # Lun–Dom
    weeks = []
    for week in grid:
        days = []
        for d in week:
            days.append({
                "date": d,
                "in_month": d.month == month,
                "is_today": today is not None and d == today,
                "meetings": by_day.get(d, []),
            })
        weeks.append(days)
    prev, nxt = _prev_next(year, month)
    return {
        "weeks": weeks, "year": year, "month": month,
        "month_label": f"{_MONTHS_IT[month]} {year}",
        "prev": prev, "next": nxt, "today": today,
    }
```

- [ ] **Step 4: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.MeetingsCalendarTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/calendario.py django_app/tasks/tests.py
git commit -m "feat(tasks): calendario.py — griglia mensile incontri (logica pura)"
```

---

## Task 2: view + route + template + CSS

**Files:** Modify `tasks/views.py`, `tasks/urls.py`, `tasks/static/tasks/css/tasks.css`; Create `tasks/templates/tasks/incontri_calendario.html`; Test `tasks/tests.py`.

- [ ] **Step 1: View** in `views.py` (vicino a `project_meetings`):

```python
@task_permissions_required("tasks_view")
def incontri_calendario(request):
    from tasks.models import KickoffMeeting
    from tasks.calendario import build_meetings_calendar

    today = timezone.localdate()
    year, month = today.year, today.month
    m_param = (request.GET.get("m") or "").strip()
    if m_param:
        try:
            y_str, mo_str = m_param.split("-")
            y, mo = int(y_str), int(mo_str)
            if 1 <= mo <= 12:
                year, month = y, mo
        except (ValueError, TypeError):
            pass
    meetings = (
        KickoffMeeting.objects
        .filter(project__in=_scoped_projects_queryset(request), data__year=year, data__month=month)
        .select_related("project")
        .order_by("data", "ora")
    )
    cal = build_meetings_calendar(list(meetings), year, month, today=today)
    return render(
        request,
        "tasks/incontri_calendario.html",
        {
            **_tasks_shell_context(request, active="calendario"),
            "page_title": "Calendario incontri",
            "cal": cal,
        },
    )
```

- [ ] **Step 2: Route** in `urls.py` (dopo `project_meetings` o vicino a `list`):

```python
    path("tasks/incontri-calendario/", views.incontri_calendario, name="incontri_calendario"),
```

- [ ] **Step 3: Template** `django_app/tasks/templates/tasks/incontri_calendario.html`:

```html
{% extends "tasks/base_shell.html" %}

{% block tasks_shell_eyebrow %}<span class="ts-eyebrow">KICK-OFF / Calendario</span>{% endblock %}
{% block tasks_shell_title %}Calendario incontri{% endblock %}
{% block tasks_shell_subtitle %}Gli incontri di kickoff del mese, tutte le commesse.{% endblock %}

{% block tasks_shell_actions %}
  <a class="ts-hero-action" href="?m={{ cal.prev }}" aria-label="Mese precedente">‹</a>
  <a class="ts-hero-action" href="{% url 'tasks:incontri_calendario' %}">Oggi</a>
  <a class="ts-hero-action" href="?m={{ cal.next }}" aria-label="Mese successivo">›</a>
{% endblock %}

{% block tasks_shell_content %}
<section class="ts-panel">
  <div class="ts-panel-head"><h2 class="ts-panel-title">{{ cal.month_label }}</h2></div>
  <div class="ts-panel-body">
    <div class="cal-scroll">
      <div class="cal-grid">
        <div class="cal-dow">Lun</div><div class="cal-dow">Mar</div><div class="cal-dow">Mer</div><div class="cal-dow">Gio</div><div class="cal-dow">Ven</div><div class="cal-dow">Sab</div><div class="cal-dow">Dom</div>
        {% for week in cal.weeks %}
          {% for day in week %}
            <div class="cal-day{% if not day.in_month %} cal-day--out{% endif %}{% if day.is_today %} cal-day--today{% endif %}">
              <div class="cal-day-num">{{ day.date.day }}</div>
              {% for mtg in day.meetings %}
                <a class="cal-mtg" href="{% url 'tasks:project_meeting_detail' mtg.project_id mtg.id %}" title="{{ mtg.luogo }}">
                  {% if mtg.ora %}{{ mtg.ora|time:"H:i" }} {% endif %}{{ mtg.project.name }}
                </a>
              {% endfor %}
            </div>
          {% endfor %}
        {% endfor %}
      </div>
    </div>
  </div>
</section>
{% endblock %}
```

- [ ] **Step 4: CSS** in `tasks.css` (in fondo):

```css
/* ── Calendario incontri ─────────────────────────────────────────── */
.cal-scroll{overflow-x:auto}
.cal-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;min-width:660px}
.cal-dow{font-size:11px;font-weight:800;text-transform:uppercase;color:var(--text-mid);text-align:center;padding:4px 0}
.cal-day{min-height:92px;border:1px solid var(--border);border-radius:var(--hub-radius-md);background:var(--surface);padding:5px;display:flex;flex-direction:column;gap:3px}
.cal-day--out{opacity:.45}
.cal-day--today{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.cal-day-num{font-size:11px;font-weight:800;color:var(--text-mid)}
.cal-mtg{font-size:11px;font-weight:700;color:var(--text);text-decoration:none;background:color-mix(in srgb,var(--accent) 12%,var(--surface));border-left:3px solid var(--accent);border-radius:4px;padding:2px 5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cal-mtg:hover{color:var(--accent)}
```

- [ ] **Step 5: Smoke test**

```python
class MeetingsCalendarRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="cal_admin", email="c@x.local", password="x"
        )

    def setUp(self):
        from tasks.models import Project, KickoffMeeting
        self.client.force_login(self.admin)
        p = Project.objects.create(name="P", created_by=self.admin)
        self.meeting = KickoffMeeting.objects.create(
            project=p, numero=1, titolo="Inc", data=timezone.localdate(), created_by=self.admin
        )

    def test_calendar_renders_current_month_with_meeting(self):
        r = self.client.get(reverse("tasks:incontri_calendario"))
        assert r.status_code == 200
        assert b"cal-grid" in r.content
        assert reverse("tasks:project_meeting_detail", args=[self.meeting.project_id, self.meeting.id]).encode() in r.content

    def test_month_param_navigates(self):
        r = self.client.get(reverse("tasks:incontri_calendario") + "?m=2026-01")
        assert r.status_code == 200
        assert b"Gennaio 2026" in r.content
```

- [ ] **Step 6: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.MeetingsCalendarRenderTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add django_app/tasks/views.py django_app/tasks/urls.py django_app/tasks/templates/tasks/incontri_calendario.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/tests.py
git commit -m "feat(tasks): pagina Calendario incontri (griglia mensile SSR)"
```

---

## Task 3: subnav + binding ACL

**Files:** Create `core/migrations/0063_tasks_calendario_subnav.py`; Modify `tasks/acl_bootstrap.py`; Test `tasks/tests.py`.

- [ ] **Step 1: Test (fallisce)**

```python
class MeetingsCalendarNavAclTests(TestCase):
    def test_subnav_seeded(self):
        from core.models import NavigationItem
        item = NavigationItem.objects.get(code="tasks-sub-calendario")
        assert item.section == "subnav" and item.parent_code == "tasks"
        assert item.route_name == "tasks:incontri_calendario"

    def test_route_bound(self):
        from core.models import RoutePermissionBinding
        from tasks.acl_bootstrap import bootstrap_tasks_acl_endpoints
        bootstrap_tasks_acl_endpoints(force=True)
        assert RoutePermissionBinding.objects.filter(
            route_name="tasks:incontri_calendario", permission_id="tasks.kickoff.view", is_active=True
        ).exists()
```

- [ ] **Step 2: Eseguire → fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.MeetingsCalendarNavAclTests --settings=config.settings.test --keepdb`
Expected: FAIL.

- [ ] **Step 3: Migrazione subnav** `django_app/core/migrations/0063_tasks_calendario_subnav.py`:

```python
from django.db import migrations

ROW = {"code": "tasks-sub-calendario", "label": "Calendario",
       "route_name": "tasks:incontri_calendario", "order": 25, "perm": "tasks.kickoff.view"}


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=ROW["code"],
        defaults={
            "label": ROW["label"], "section": "subnav", "parent_code": "tasks",
            "route_name": ROW["route_name"], "order": ROW["order"],
            "required_permission_code": ROW["perm"], "is_visible": True, "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code=ROW["code"]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0062_tasks_da_gestire_subnav")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 4: Binding ACL + bump** in `acl_bootstrap.py`: in `_ROUTE_BINDINGS` (vicino a `"tasks:list": "tasks.kickoff.view",`) aggiungere `"tasks:incontri_calendario": "tasks.kickoff.view",`; cambiare `_BOOTSTRAP_CACHE_KEY = "tasks_acl_bootstrap_v6"` → `"tasks_acl_bootstrap_v7"`.

- [ ] **Step 5: Applicare in dev + test**

Run: `.\.venv\Scripts\python.exe django_app\manage.py migrate core --settings=config.settings.dev`
Run: `.\.venv\Scripts\python.exe django_app\manage.py shell --settings=config.settings.dev -c "from tasks.acl_bootstrap import bootstrap_tasks_acl_endpoints as b; b(force=True)"`
Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.MeetingsCalendarNavAclTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add django_app/core/migrations/0063_tasks_calendario_subnav.py django_app/tasks/acl_bootstrap.py django_app/tasks/tests.py
git commit -m "feat(tasks): subnav 'Calendario' + binding ACL route incontri_calendario"
```

---

## Task 4: documentazione

- [ ] **Step 1: CHANGELOG** — `[Unreleased] / ### Added`: "KICK-OFF · Calendario incontri (cross-commessa): pagina `/tasks/incontri-calendario/` (subnav «Calendario») con griglia mensile SSR di tutti gli incontri in scope, navigazione mese, chip con ora+commessa linkati al verbale. `tasks/calendario.py`; binding ACL." **Staging mirato** se CHANGELOG ha WIP di altra sessione (`git add -p`).
- [ ] **Step 2: README** — sezione modulo `tasks`: aggiungere "Calendario incontri (vista mensile cross-commessa)".
- [ ] **Step 3: Verifica finale**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.MeetingsCalendarTests tasks.tests.MeetingsCalendarRenderTests tasks.tests.MeetingsCalendarNavAclTests --settings=config.settings.test --keepdb`
Run: `.\.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: PASS + no issues.

- [ ] **Step 4: Commit** (staging mirato)

```powershell
git add README.md
git commit -m "docs(tasks): CHANGELOG + README — calendario incontri KICK-OFF"
```

---

## Self-Review (esito)

**Copertura spec:** §2 unità isolata → Task 1 (testata, incl. bordo d'anno); §3 view/scope → Task 2; §4 template griglia → Task 2; §5 nav/ACL → Task 3; §6 file → coperti; §7 verifica → unit + smoke + subnav + ACL; §8 YAGNI → solo vista mese.

**Placeholder scan:** nessun TBD; migrazione `0063` con dependency reale `0062`.

**Coerenza tipi/nomi:** `build_meetings_calendar(meetings, year, month, today=None)` → `weeks/month_label/prev/next`; route `tasks:incontri_calendario`; contesto `cal`; subnav `tasks-sub-calendario`; classi `.cal-*`; binding `tasks.kickoff.view` — coerenti tra i task.
