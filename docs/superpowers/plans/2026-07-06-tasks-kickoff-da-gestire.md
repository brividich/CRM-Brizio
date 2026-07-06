# KICK-OFF Centro "Da gestire" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pagina dedicata `/tasks/da-gestire/` che eleva i segnali KICK-OFF (readiness + KPI admin) a 4 sezioni azionabili con toggle Portfolio/Le mie, solo navigazione.

**Architecture:** Logica pura isolata in `tasks/da_gestire.py` (`build_kickoff_da_gestire(request, scope)`), che riusa `tasks/readiness.py` e gli helper di scope di `views.py`. Ogni sezione è un helper difensivo che ritorna dict `{key,label,tone,icon,items,all_url,empty}`. View sottile + template SSR con partial di sezione. Nuova route con binding ACL e voce subnav.

**Tech Stack:** Django 5.2 (ORM annotate/Count/Q), template SSR, componenti `ts-panel` + badge readiness esistenti.

Spec: `docs/superpowers/specs/2026-07-06-tasks-kickoff-da-gestire-design.md`

## Global Constraints

- **Solo lettura + navigazione:** nessun endpoint POST, nessuna mutazione inline, nessun nuovo modello.
- **Riuso:** `tasks/readiness.py` (`annotate_readiness_qs`, `compute_project_readiness`); helper scope `_scoped_projects_queryset(request)` / `_scoped_tasks_queryset(request)` e `_has_task_permission(request, "tasks_admin")` (in `views.py`), importati **localmente** (regola progetto).
- **Top 20** item per sezione; `all_url` verso l'elenco filtrato dove esiste, altrimenti `None`.
- **Default scope:** `portfolio` se scope-admin, altrimenti `mine`. Toggle via `?scope=portfolio|mine`.
- **Nuova route → ACL obbligatorio:** binding `tasks:da_gestire → tasks.kickoff.view` in `acl_bootstrap._ROUTE_BINDINGS` + bump `_BOOTSTRAP_CACHE_KEY` (`tasks_acl_bootstrap_v4` → `v5`). È una pagina (non `/api/`) → niente `API_ACL_GATE_PATHS`.
- **Non modificare il tema:** solo token; dark-safe.
- **Decoratore view:** `@task_permissions_required("tasks_view")` (come `task_list`/`project_list`).
- **Relazioni reali:** `MeetingIssue.source_meeting` (related_name `issues_created`); `MeetingIssueStatus.OPEN`; `VRFDocStatus.PENDING`; `project.project_manager/capo_commessa/programmer/created_by`.
- **Test:** `.\.venv\Scripts\python.exe django_app\manage.py test tasks.<Class> --settings=config.settings.test --keepdb` (label `tasks.`). Mai suite completa. Shell PowerShell.
- **Fixture:** `Project.objects.create(name=, created_by=user)`, `Task.objects.create(title=, created_by=user, project=, due_date=, status=, assigned_to=)`, `KickoffMeeting.objects.create(project=, titolo=, data=timezone.localdate(), created_by=)`, `MeetingIssue.objects.create(project=, source_meeting=, title=, status=)`.

## File Structure

**Nuovi:**
- `django_app/tasks/da_gestire.py` — logica (build + section helpers).
- `django_app/tasks/templates/tasks/da_gestire.html` — pagina.
- `django_app/tasks/templates/tasks/_da_gestire_section.html` — partial sezione (input: `section`).
- `django_app/core/migrations/00NN_tasks_da_gestire_subnav.py` — voce subnav.

**Modificati:**
- `django_app/tasks/urls.py` (+route), `django_app/tasks/views.py` (+view `da_gestire`),
  `django_app/tasks/acl_bootstrap.py` (+binding, bump cache),
  `django_app/tasks/templates/tasks/list.html` (link da dashboard),
  `django_app/tasks/static/tasks/css/tasks.css` (stili sezione), `django_app/tasks/tests.py`,
  `CHANGELOG.md`, `README.md`.

---

## Task 1: `da_gestire.py` — logica delle 4 sezioni

**Files:**
- Create: `django_app/tasks/da_gestire.py`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces: `build_kickoff_da_gestire(request, scope) -> {"sections": list, "total": int, "scope": str}`. Sezioni con `key ∈ {vrf, not_ready, critical, meetings}`, ognuna `{key,label,tone,icon,items,all_url,empty}`; `item = {label, url, meta}`.

- [ ] **Step 1: Scrivere i test (falliscono)**

In `django_app/tasks/tests.py` (in fondo):

```python
class KickoffDaGestireTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="dg_admin", email="dg@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def _req(self):
        # Request reale processato dal middleware (ha legacy_user, ecc.):
        # gli helper _scoped_* chiamano _has_task_permission che tocca attributi
        # settati dal middleware, quindi NON usare RequestFactory.
        return self.client.get(reverse("tasks:list")).wsgi_request

    def _sections(self, data):
        return {s["key"]: s for s in data["sections"]}

    def test_vrf_pending_section(self):
        from tasks.models import Project, VRFDocStatus
        from tasks.da_gestire import build_kickoff_da_gestire
        Project.objects.create(name="DaCaricare", created_by=self.admin)  # PENDING default
        Project.objects.create(
            name="Ok", created_by=self.admin, vrf_status=VRFDocStatus.UPLOADED
        )
        secs = self._sections(build_kickoff_da_gestire(self._req(), "portfolio"))
        labels = [i["label"] for i in secs["vrf"]["items"]]
        assert "DaCaricare" in labels and "Ok" not in labels

    def test_not_ready_section(self):
        from tasks.models import Project
        from tasks.da_gestire import build_kickoff_da_gestire
        Project.objects.create(name="Vuota", created_by=self.admin)  # 0/4 -> notready
        secs = self._sections(build_kickoff_da_gestire(self._req(), "portfolio"))
        labels = [i["label"] for i in secs["not_ready"]["items"]]
        assert "Vuota" in labels

    def test_critical_tasks_section_reasons(self):
        from tasks.models import Project, Task, TaskStatus
        from tasks.da_gestire import build_kickoff_da_gestire
        p = Project.objects.create(name="C", created_by=self.admin)
        Task.objects.create(
            title="Scaduta", created_by=self.admin, project=p,
            due_date=timezone.localdate() - timedelta(days=2),
            status=TaskStatus.TODO, assigned_to=self.admin,
        )
        Task.objects.create(
            title="NonAssegnata", created_by=self.admin, project=p,
            due_date=timezone.localdate() + timedelta(days=5), status=TaskStatus.TODO,
        )
        secs = self._sections(build_kickoff_da_gestire(self._req(), "portfolio"))
        titles = [i["label"] for i in secs["critical"]["items"]]
        assert "Scaduta" in titles and "NonAssegnata" in titles

    def test_meetings_open_issues_section(self):
        from tasks.models import Project, KickoffMeeting, MeetingIssue, MeetingIssueStatus
        from tasks.da_gestire import build_kickoff_da_gestire
        p = Project.objects.create(name="M", created_by=self.admin)
        m = KickoffMeeting.objects.create(
            project=p, titolo="Inc1", data=timezone.localdate(), created_by=self.admin
        )
        MeetingIssue.objects.create(
            project=p, source_meeting=m, title="Problema", status=MeetingIssueStatus.OPEN
        )
        secs = self._sections(build_kickoff_da_gestire(self._req(), "portfolio"))
        assert len(secs["meetings"]["items"]) == 1
        assert f"/tasks/projects/{p.id}/incontri/{m.id}/" in secs["meetings"]["items"][0]["url"]

    def test_total_and_scope_normalized(self):
        from tasks.da_gestire import build_kickoff_da_gestire
        data = build_kickoff_da_gestire(self._req(), "garbage")
        assert data["scope"] == "portfolio"
        assert data["total"] == sum(len(s["items"]) for s in data["sections"])
```

(`timedelta` è già importato in `tests.py` alla riga 4: `from datetime import datetime, timedelta`.)

- [ ] **Step 2: Eseguire → falliscono**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.KickoffDaGestireTests --settings=config.settings.test --keepdb`
Expected: FAIL (`ModuleNotFoundError: tasks.da_gestire`).

- [ ] **Step 3: Creare `django_app/tasks/da_gestire.py`**

```python
"""Centro 'Da gestire' KICK-OFF (portfolio/PM): aggrega segnali azionabili.

Solo lettura + navigazione. Ogni sezione e' difensiva (un errore non rompe
il resto). Riusa tasks/readiness.py.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

_TOP = 20


def _url(name, *args):
    try:
        return reverse(name, args=args) if args else reverse(name)
    except Exception:
        return ""


def _projects_qs(request, scope):
    from .views import _scoped_projects_queryset

    qs = _scoped_projects_queryset(request)
    if scope == "mine":
        u = request.user
        qs = qs.filter(
            Q(project_manager=u) | Q(capo_commessa=u) | Q(programmer=u) | Q(created_by=u)
        )
    return qs


def _tasks_qs(request, scope):
    from .views import _scoped_tasks_queryset

    qs = _scoped_tasks_queryset(request)
    if scope == "mine":
        u = request.user
        qs = qs.filter(
            Q(created_by=u) | Q(assigned_to=u) | Q(subscribers=u)
        ).distinct()
    return qs


def _sec_vrf_pending(request, scope):
    from .models import VRFDocStatus

    qs = _projects_qs(request, scope).filter(vrf_status=VRFDocStatus.PENDING).order_by("-updated_at")
    items = [
        {"label": p.name, "url": _url("tasks:project_vrf_upload", p.id), "meta": "VRF da caricare"}
        for p in qs[:_TOP]
    ]
    return {
        "key": "vrf", "label": "VRF da caricare", "tone": "warning", "icon": "\U0001F4C4",
        "items": items, "all_url": _url("tasks:project_list") + "?vrf_status=pending",
        "empty": "Nessun VRF da caricare.",
    }


def _sec_not_ready(request, scope):
    from .readiness import annotate_readiness_qs, compute_project_readiness

    items = []
    for p in annotate_readiness_qs(_projects_qs(request, scope)).order_by("name"):
        r = compute_project_readiness(p)
        if r.level in ("notready", "partial"):
            missing = ", ".join(c.label for c in r.criteria if not c.ok)
            items.append({
                "label": p.name,
                "url": _url("tasks:list") + f"?project={p.id}",
                "meta": f"{r.label} — manca: {missing}",
            })
        if len(items) >= _TOP:
            break
    return {
        "key": "not_ready", "label": "Commesse non pronte", "tone": "danger", "icon": "\U0001F6A6",
        "items": items, "all_url": _url("tasks:project_list"),
        "empty": "Tutte le commesse sono pronte.",
    }


def _sec_critical_tasks(request, scope):
    from .models import TaskStatus

    today = timezone.localdate()
    now = timezone.now()
    open_statuses = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
    base = _tasks_qs(request, scope).filter(status__in=open_statuses)

    items, seen = [], set()

    def add(qs, reason):
        for t in qs[:_TOP]:
            if t.id in seen:
                continue
            seen.add(t.id)
            items.append({"label": t.title, "url": _url("tasks:detail", t.id), "meta": reason})

    add(base.filter(due_date__lt=today).order_by("due_date"), "Scaduta")
    add(base.filter(assigned_to__isnull=True).order_by("-updated_at"), "Non assegnata")
    add(base.filter(due_date__isnull=True).order_by("-updated_at"), "Senza data fine")
    add(
        base.filter(status=TaskStatus.IN_PROGRESS, updated_at__lt=now - timedelta(days=7)).order_by("updated_at"),
        "Ferma >7gg",
    )
    return {
        "key": "critical", "label": "Attività critiche", "tone": "warning", "icon": "⏰",
        "items": items[:_TOP], "all_url": _url("tasks:list"),
        "empty": "Nessuna attività critica.",
    }


def _sec_meetings_open_issues(request, scope):
    from .models import KickoffMeeting, MeetingIssueStatus

    project_ids = _projects_qs(request, scope).values_list("id", flat=True)
    qs = (
        KickoffMeeting.objects.filter(project_id__in=project_ids)
        .annotate(
            open_issues=Count(
                "issues_created", filter=Q(issues_created__status=MeetingIssueStatus.OPEN)
            )
        )
        .filter(open_issues__gt=0)
        .order_by("-data")
    )
    items = [
        {
            "label": m.titolo,
            "url": _url("tasks:project_meeting_detail", m.project_id, m.id),
            "meta": f"{m.open_issues} problemi aperti",
        }
        for m in qs[:_TOP]
    ]
    return {
        "key": "meetings", "label": "Incontri da chiudere", "tone": "info", "icon": "\U0001F4CC",
        "items": items, "all_url": None,
        "empty": "Nessun incontro con problemi aperti.",
    }


def build_kickoff_da_gestire(request, scope: str) -> dict:
    scope = "mine" if scope == "mine" else "portfolio"
    builders = (_sec_vrf_pending, _sec_not_ready, _sec_critical_tasks, _sec_meetings_open_issues)
    sections = []
    for b in builders:
        try:
            sections.append(b(request, scope))
        except Exception:
            continue
    total = sum(len(s["items"]) for s in sections)
    return {"sections": sections, "total": total, "scope": scope}
```

- [ ] **Step 4: Eseguire → passano**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.KickoffDaGestireTests --settings=config.settings.test --keepdb`
Expected: PASS (5 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/da_gestire.py django_app/tasks/tests.py
git commit -m "feat(tasks): da_gestire.py — 4 sezioni azionabili KICK-OFF (portfolio/mine)"
```

---

## Task 2: view + route + template + partial

**Files:**
- Modify: `django_app/tasks/views.py` (nuova view `da_gestire`, vicino a `task_list`)
- Modify: `django_app/tasks/urls.py`
- Create: `django_app/tasks/templates/tasks/da_gestire.html`
- Create: `django_app/tasks/templates/tasks/_da_gestire_section.html`
- Modify: `django_app/tasks/static/tasks/css/tasks.css`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: `build_kickoff_da_gestire` (Task 1), `_has_task_permission`, `_tasks_shell_context`.

- [ ] **Step 1: Aggiungere la view** in `django_app/tasks/views.py` (subito dopo `task_list`, prima di `task_detail`):

```python
@task_permissions_required("tasks_view")
def da_gestire(request):
    from tasks.da_gestire import build_kickoff_da_gestire

    is_admin = _has_task_permission(request, "tasks_admin")
    scope = request.GET.get("scope") or ("portfolio" if is_admin else "mine")
    if scope not in ("portfolio", "mine"):
        scope = "portfolio" if is_admin else "mine"
    data = build_kickoff_da_gestire(request, scope)
    return render(
        request,
        "tasks/da_gestire.html",
        {
            **_tasks_shell_context(request, active="da_gestire"),
            "page_title": "Da gestire",
            "da_gestire_data": data,
            "scope": scope,
            "is_scope_admin": is_admin,
        },
    )
```

- [ ] **Step 2: Registrare la route** in `django_app/tasks/urls.py` (dopo la riga `path("tasks/", views.task_list, name="list"),`):

```python
    path("tasks/da-gestire/", views.da_gestire, name="da_gestire"),
```

- [ ] **Step 3: Creare il partial di sezione** `django_app/tasks/templates/tasks/_da_gestire_section.html`:

```html
<section class="ts-panel dg-section">
  <div class="ts-panel-head">
    <div class="ts-panel-title-wrap">
      <h2 class="ts-panel-title">{{ section.icon }} {{ section.label }}</h2>
      <p class="ts-panel-subtitle">{{ section.items|length }} da gestire</p>
    </div>
    {% if section.all_url %}<a class="ts-chip soft" style="text-decoration:none;" href="{{ section.all_url }}">Vedi tutti</a>{% endif %}
  </div>
  <div class="ts-panel-body">
    {% if section.items %}
      <ul class="dg-list">
        {% for item in section.items %}
          <li class="dg-item dg-item--{{ section.tone }}">
            <a class="dg-item-link" href="{{ item.url }}">{{ item.label }}</a>
            {% if item.meta %}<span class="dg-item-meta">{{ item.meta }}</span>{% endif %}
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="dg-empty">{{ section.empty }}</p>
    {% endif %}
  </div>
</section>
```

- [ ] **Step 4: Creare la pagina** `django_app/tasks/templates/tasks/da_gestire.html`:

```html
{% extends "tasks/base_shell.html" %}

{% block tasks_shell_eyebrow %}<span class="ts-eyebrow">KICK-OFF / Da gestire</span>{% endblock %}
{% block tasks_shell_title %}Da gestire{% endblock %}
{% block tasks_shell_subtitle %}Cosa richiede intervento sulle commesse kickoff.{% endblock %}

{% block tasks_shell_actions %}
  <a class="ts-hero-action {% if scope == 'portfolio' %}primary{% endif %}" href="{% url 'tasks:da_gestire' %}?scope=portfolio">Portfolio</a>
  <a class="ts-hero-action {% if scope == 'mine' %}primary{% endif %}" href="{% url 'tasks:da_gestire' %}?scope=mine">Le mie</a>
{% endblock %}

{% block tasks_shell_content %}
<div class="ts-stack">
  {% for section in da_gestire_data.sections %}
    {% include "tasks/_da_gestire_section.html" with section=section %}
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Stili** in `django_app/tasks/static/tasks/css/tasks.css` (in fondo):

```css
/* ── Centro "Da gestire" ─────────────────────────────────────────── */
.dg-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
.dg-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:var(--hub-radius-md);border-left:3px solid var(--border);transition:background .1s ease}
.dg-item:hover{background:color-mix(in srgb,var(--accent) 6%,transparent)}
.dg-item--danger{border-left-color:var(--hub-status-danger)}
.dg-item--warning{border-left-color:var(--hub-status-warning)}
.dg-item--info{border-left-color:var(--hub-status-info)}
.dg-item-link{font-weight:700;color:var(--text);text-decoration:none;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dg-item-link:hover{color:var(--accent)}
.dg-item-meta{font-size:var(--hub-font-xs);font-weight:700;color:var(--text-mid);white-space:nowrap;flex-shrink:0}
.dg-empty{color:var(--text-mid);font-size:var(--hub-font-sm);margin:0;padding:6px 2px}
```

- [ ] **Step 6: Smoke test**

```python
class KickoffDaGestireRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="dg_render", email="r@x.local", password="x"
        )

    def setUp(self):
        from tasks.models import Project
        self.client.force_login(self.admin)
        Project.objects.create(name="Vuota", created_by=self.admin)

    def test_page_renders_with_sections_and_toggle(self):
        r = self.client.get(reverse("tasks:da_gestire"))
        assert r.status_code == 200
        assert b"dg-section" in r.content
        assert b"Commesse non pronte" in r.content
        assert b"?scope=mine" in r.content

    def test_scope_mine_renders(self):
        r = self.client.get(reverse("tasks:da_gestire") + "?scope=mine")
        assert r.status_code == 200
```

- [ ] **Step 7: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.KickoffDaGestireRenderTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add django_app/tasks/views.py django_app/tasks/urls.py django_app/tasks/templates/tasks/da_gestire.html django_app/tasks/templates/tasks/_da_gestire_section.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/tests.py
git commit -m "feat(tasks): pagina /tasks/da-gestire/ con sezioni azionabili + toggle scope"
```

---

## Task 3: voce subnav "Da gestire"

**Files:**
- Create: `django_app/core/migrations/00NN_tasks_da_gestire_subnav.py`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces: `NavigationItem` `code="tasks-sub-da-gestire"`, `section="subnav"`, `parent_code="tasks"`, `route_name="tasks:da_gestire"`, order 15, `required_permission_code="tasks.kickoff.view"`.

- [ ] **Step 1: Numero migrazione** — `.\.venv\Scripts\python.exe django_app\manage.py showmigrations core --settings=config.settings.test` → usare l'ultima +1 (dopo `0061_tasks_subnav` → `0062_...`; verificare non ce ne siano di più recenti).

- [ ] **Step 2: Test (fallisce)**

```python
class KickoffDaGestireSubnavTests(TestCase):
    def test_subnav_item_seeded(self):
        from core.models import NavigationItem
        item = NavigationItem.objects.get(code="tasks-sub-da-gestire")
        assert item.section == "subnav" and item.parent_code == "tasks"
        assert item.route_name == "tasks:da_gestire"
        assert item.required_permission_code == "tasks.kickoff.view"
```

- [ ] **Step 3: Eseguire → fallisce**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.KickoffDaGestireSubnavTests --settings=config.settings.test --keepdb`
Expected: FAIL (`DoesNotExist`).

- [ ] **Step 4: Creare la migrazione** `django_app/core/migrations/00NN_tasks_da_gestire_subnav.py` (sostituire `00NN` e dependency reali):

```python
from django.db import migrations

ROW = {
    "code": "tasks-sub-da-gestire",
    "label": "Da gestire",
    "route_name": "tasks:da_gestire",
    "order": 15,
    "perm": "tasks.kickoff.view",
}


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=ROW["code"],
        defaults={
            "label": ROW["label"],
            "section": "subnav",
            "parent_code": "tasks",
            "route_name": ROW["route_name"],
            "order": ROW["order"],
            "required_permission_code": ROW["perm"],
            "is_visible": True,
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code=ROW["code"]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0061_tasks_subnav")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 5: Applicare in dev + test**

Run: `.\.venv\Scripts\python.exe django_app\manage.py migrate core --settings=config.settings.dev`
Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.KickoffDaGestireSubnavTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add django_app/core/migrations/00NN_tasks_da_gestire_subnav.py django_app/tasks/tests.py
git commit -m "feat(tasks): voce subnav 'Da gestire'"
```

---

## Task 4: binding ACL della route

**Files:**
- Modify: `django_app/tasks/acl_bootstrap.py` (`_ROUTE_BINDINGS`, `_BOOTSTRAP_CACHE_KEY`)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces: `RoutePermissionBinding` per `tasks:da_gestire → tasks.kickoff.view`.

- [ ] **Step 1: Aggiungere il binding** in `_ROUTE_BINDINGS` (vicino a `"tasks:list": "tasks.kickoff.view",`):

```python
    "tasks:da_gestire": "tasks.kickoff.view",
```

- [ ] **Step 2: Bump cache-key** — cambiare `_BOOTSTRAP_CACHE_KEY = "tasks_acl_bootstrap_v4"` in `"tasks_acl_bootstrap_v5"`.

- [ ] **Step 3: Test (rieseguendo il bootstrap forzato)**

```python
class KickoffDaGestireAclTests(TestCase):
    def test_route_is_bound(self):
        from core.models import RoutePermissionBinding
        from tasks.acl_bootstrap import bootstrap_tasks_acl_endpoints
        bootstrap_tasks_acl_endpoints(force=True)
        assert RoutePermissionBinding.objects.filter(
            route_name="tasks:da_gestire", permission_id="tasks.kickoff.view", is_active=True
        ).exists()
```

- [ ] **Step 4: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.KickoffDaGestireAclTests --settings=config.settings.test --keepdb`
Expected: PASS. (Se `bootstrap_tasks_acl_endpoints` richiede argomenti diversi, adattare alla firma reale in `acl_bootstrap.py`.)

- [ ] **Step 5: Applicare il bootstrap in dev**

Run: `.\.venv\Scripts\python.exe django_app\manage.py shell --settings=config.settings.dev -c "from tasks.acl_bootstrap import bootstrap_tasks_acl_endpoints as b; b(force=True)"`
(così il binding entra in vigore nel dev dell'utente.)

- [ ] **Step 6: Commit**

```powershell
git add django_app/tasks/acl_bootstrap.py django_app/tasks/tests.py
git commit -m "feat(tasks): binding ACL route da_gestire (tasks.kickoff.view) + bump cache v5"
```

---

## Task 5: link dalla dashboard

**Files:**
- Modify: `django_app/tasks/templates/tasks/list.html` (sezione admin `admin_console`)

- [ ] **Step 1: Aggiungere il link** — nella sezione `{% if is_scope_admin and admin_console %}`, nell'header del pannello "Alert operativi" (accanto allo `<span class="ts-chip info">Admin</span>`), aggiungere:

```html
<a class="ts-chip soft" style="text-decoration:none;" href="{% url 'tasks:da_gestire' %}">Vai a «Da gestire»</a>
```

- [ ] **Step 2: Verifica render**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessDashboardAggregateTests --settings=config.settings.test --keepdb`
Expected: PASS (la dashboard admin renderizza ancora; il link è presente).

- [ ] **Step 3: Commit**

```powershell
git add django_app/tasks/templates/tasks/list.html
git commit -m "feat(tasks): link 'Da gestire' dalla dashboard KICK-OFF"
```

---

## Task 6: documentazione

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: CHANGELOG** — sotto `[Unreleased] / ### Added`: "KICK-OFF · Centro «Da gestire» (portfolio/PM): pagina `/tasks/da-gestire/` con 4 sezioni azionabili (VRF da caricare, commesse non pronte, attività critiche, incontri da chiudere), toggle Portfolio/Le mie, solo navigazione; subnav + binding ACL; `tasks/da_gestire.py`." Elencare i file.

- [ ] **Step 2: README** — sezione modulo `tasks`: aggiungere il Centro «Da gestire» e la route.

- [ ] **Step 3: Verifica finale**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.KickoffDaGestireTests tasks.tests.KickoffDaGestireRenderTests tasks.tests.KickoffDaGestireSubnavTests tasks.tests.KickoffDaGestireAclTests --settings=config.settings.test --keepdb`
Run: `.\.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: PASS + no issues.

- [ ] **Step 4: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(tasks): CHANGELOG + README — Centro Da gestire KICK-OFF"
```

---

## Self-Review (esito)

**Copertura spec:** §2 unità isolata → Task 1; §3 le 4 sezioni → Task 1 (helper + test per ciascuna); §4 scope toggle → Task 1 (`_projects_qs`/`_tasks_qs`) + Task 2 (default in view + toggle template); §5 pagina/nav/ACL → Task 2 (route/template), Task 3 (subnav), Task 4 (binding+bump), Task 5 (link dashboard); §6 YAGNI → nessun POST/modello; §7 verifica → unit (Task 1) + smoke (Task 2) + subnav (Task 3) + ACL (Task 4).

**Placeholder scan:** `00NN` in Task 3 è un valore da risolvere a runtime con procedura esplicita (Step 1); nessun altro TBD. Nota sul `timedelta` nei test corretta inline.

**Coerenza tipi/nomi:** `build_kickoff_da_gestire(request, scope)`; sezioni `key ∈ {vrf,not_ready,critical,meetings}`; item `{label,url,meta}`; contesto `da_gestire_data`/`scope`; classi `.dg-*`; route `tasks:da_gestire`; subnav `tasks-sub-da-gestire`; binding `tasks.kickoff.view` — coerenti tra i task.
