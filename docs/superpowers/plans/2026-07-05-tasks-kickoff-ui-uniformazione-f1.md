# Uniformazione UI KICK-OFF — Fase 1 (Fondazione UI) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare la UI del modulo `tasks` (KICK-OFF) allo standard condiviso del portale — chrome (`hub-page-header` + subnav `NavigationItem`), token dark-aware, policy larghezza, responsività — **senza cambiare comportamento, route, permessi o dati**.

**Architecture:** Si ritira la shell custom `base_shell.html` (con `ts-hero`+`ts-tabs`) a favore di una `tasks/base.html` che estende `core/base.html`. La navigazione di modulo passa alla `subnav.html` condivisa (voci come `NavigationItem`); le tab per-commessa diventano un componente locale. Il dark-mode si risolve sostituendo gli hex hardcodati con i token core (che già flippano in `body.theme-dark`), mantenendo la ricchezza visiva (card cover, KPI) via varianti `body.theme-dark` mirate.

**Tech Stack:** Django 5.2 templates (SSR), CSS custom con token `--*`/`--hub-*`, HTMX (invariato). Nessun framework JS nuovo.

Spec di riferimento: `docs/superpowers/specs/2026-07-05-tasks-kickoff-ui-uniformazione-f1-design.md`

## Stato esecuzione (2026-07-05)

Eseguiti inline (utente assente, niente subagent) i task fondativi a basso rischio:

- ✅ **Task 2** — `tasks/base.html` + `_project_tabs.html` + stili `.tk-*` (commit `77eccdf`). Tutto dentro `tasks/`, **inerte** (nessuna pagina ancora ripointata).
- ✅ **Task 3** — migrazione `core/0061_tasks_subnav.py` (commit `01d0b45`). **NON applicata al DB dev**: va applicata **insieme** ai repoint (Task 4–10), altrimenti le pagine ancora su `base_shell` mostrano doppia navigazione (ts-tabs + subnav condivisa).
- ⏸️ **Task 1** — **NON eseguito**: l'edit a `core/base.html` è stato **negato dall'utente**. **Sostituzione:** l'opt-in larghezza si farà **senza toccare il core**, via il block `{% block body_class %}` già esposto da `core/base.html` (linea 37). Nel Gantt (Task 7): `{% block body_class %}{{ block.super }} tk-wide{% endblock %}` + regola in `tasks.css`: `body.tk-wide .content{width:100%;max-width:none}`. Ignorare gli Step su `core/base.html`+`theme.css` del Task 1 originale.
- ⏭️ **Task 4–12** — da fare al ritorno dell'utente (richiedono verifica visiva light/dark). Iniziare applicando la migrazione 0061 al dev (`migrate core --settings=config.settings.dev`) contestualmente al primo repoint.

Deviazione token confermata: `--ts-*` restano (già dark-aware); nessun rename a `--hub-*`.

## Global Constraints

- **Iso-funzionale:** NON modificare `tasks/views.py`, `tasks/urls.py`, `tasks/models.py`, `tasks/forms.py` nella logica. Route e permessi invariati. (Unica eccezione ammessa: lettura del codice nav top in migrazione dati.)
- **Non modificare il tema:** riusare i token esistenti (`--surface`, `--border`, `--text`, `--text-mid`, `--bg`, `--hub-*`, `--hub-status-*`). Nessuna nuova palette.
- **Subnav SOLO via `NavigationItem`** (`section="subnav"`), mai hardcodata nel template.
- **`--ts-*` restano** (deviazione motivata dalla spec): la verifica ha mostrato che in `tasks.css` `--ts-border/text/text-mid/surface` sono già alias di `--border/--text/--text-mid/--surface`, che flippano in `body.theme-dark` (theme.css:14). Il rename cosmetico a `--hub-*` è **YAGNI** e aggiunge churn: si mantiene `--ts-*`. Il debito dark-mode reale è **solo** negli hex hardcodati.
- **Branch:** lavorare su `feature/skill-matrix-mod187` (prod gira questo branch, non `main`). Le modifiche devono finire nel checkout locale `C:\Dev\Portale Novicrom`.
- **Fine sessione:** aggiornare `CHANGELOG.md` (sempre) e `README.md` (UI user-facing → sì) + bump versione (Task 12).
- **Test scoping:** `python django_app\manage.py test django_app.tasks --settings=config.settings.test --keepdb`. **MAI** la suite completa.
- **Shell:** PowerShell per i comandi (il tool Bash è rifiutato dai permessi in questo ambiente).
- **Recipe hex→token** (vale per OGNI task per-pagina, sezione 4..10):

  | Uso attuale (light hardcoded) | Sostituzione |
  |---|---|
  | `#fff` / `#ffffff` come **sfondo** superficie/card | `var(--surface)` |
  | `#fff` come **testo su fondo colorato** (cover, badge pieno) | **lasciare `#fff`** (intenzionale) |
  | grigi chiari di sfondo (`#f8fafc`,`#eef4fb`,`#f4f8fd`,`#f0f4f8`…) | `var(--bg)` oppure `color-mix(in srgb, var(--surface) 92%, var(--text) 8%)` per un raised sottile |
  | bordi chiari (`#e2e8f0`,`#dde8f2`,`#cbd5e1`,`#e5e7eb`) | `var(--border)` |
  | testo scuro primario (`#0f172a`,`#1e293b`,`#1a202c`,`#111`) | `var(--text)` |
  | testo secondario (`#475569`,`#64748b`,`#4a5568`) | `var(--text-mid)` |
  | testo tenue (`#94a3b8`,`#cbd5e1` come testo) | `var(--text-light)` |
  | colori di stato (blu `#1d4ed8`, verde `#166534`, ambra `#b45309`, rosso `#b91c1c`, viola `#7c3aed`) | token stato: `--hub-status-info`/`success`/`warning`/`danger`/`neutral` **oppure** lasciare per il light e aggiungere override `body.theme-dark` se il contrasto si rompe |
  | **gradienti decorativi** (cover portfolio, KPI) | mantenere per il light; aggiungere blocco `body.theme-dark { … }` con gradiente scuro equivalente |

  Regola d'oro: **non** fare find/replace cieco. Valutare ogni occorrenza (testo-su-colore va tenuto). In dubbio su un elemento decorativo, preferire un override `body.theme-dark` mirato al posto della sostituzione del valore light.

---

## File Structure

**Nuovi file:**
- `django_app/tasks/templates/tasks/base.html` — base di modulo, `extends core/base.html`; espone blocchi page_header + `content_class` + `tasks_content` + `tasks_scripts`.
- `django_app/tasks/templates/tasks/_project_tabs.html` — tab contestuali di commessa (record-level), stile hub.
- `django_app/core/migrations/00NN_tasks_subnav.py` — seed `NavigationItem` subnav.

**Modificati:**
- `django_app/core/templates/core/base.html` — aggiunta `{% block content_class %}`.
- `django_app/core/static/core/css/theme.css` — aggiunta `.content--wide`; cleanup `.content>.ts-shell` (Task 11).
- `django_app/tasks/static/tasks/css/tasks.css` — stili `.tk-tabs`, dark-variant componenti, rimozione stili shell legacy (Task 11).
- `django_app/tasks/templates/tasks/*.html` (15 file) — repoint a `tasks/base.html`, `page_header`, hex→token, wrapper tabelle.
- `django_app/tasks/tests.py` — test statici + render-smoke.
- `CHANGELOG.md`, `README.md`.

**Eliminati (Task 11):**
- `django_app/tasks/templates/tasks/base_shell.html`.

**Ordine e stato transitorio noto:** dopo il Task 3 (seed subnav) e prima del completamento dei repoint, le pagine ancora su `base_shell` mostrano **sia** i vecchi `ts-tabs` **sia** la subnav condivisa. È uno stato intermedio accettato tra commit; si risolve completando i repoint (Task 4–10) e il cutover (Task 11).

---

## Task 1: Core — opt-in larghezza `content--wide`

**Files:**
- Modify: `django_app/core/templates/core/base.html:58`
- Modify: `django_app/core/static/core/css/theme.css:66` (aggiunta regola adiacente)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces: block Django `content_class` sul `<div class="content …">`; classe CSS `.content--wide`. Le pagine che vogliono larghezza piena aggiungono `{% block content_class %} content--wide{% endblock %}` (nota lo spazio iniziale).

- [ ] **Step 1: Scrivere il test statico (fallisce)**

In `django_app/tasks/tests.py` aggiungere in fondo:

```python
from django.template.loader import get_template


class CoreWidthOptInTests(TestCase):
    def test_base_html_exposes_content_class_block(self):
        src = Path(get_template("core/base.html").origin.name).read_text(encoding="utf-8")
        assert 'class="content{% block content_class %}{% endblock %}"' in src, (
            "core/base.html deve esporre il block content_class sul div .content"
        )

    def test_theme_css_defines_content_wide(self):
        from django.contrib.staticfiles import finders
        css = Path(finders.find("core/css/theme.css")).read_text(encoding="utf-8")
        assert ".content--wide" in css, "theme.css deve definire .content--wide"
```

- [ ] **Step 2: Eseguire il test → fallisce**

Run: `python django_app\manage.py test django_app.tasks.tests.CoreWidthOptInTests --settings=config.settings.test --keepdb`
Expected: FAIL (assertion su `content_class` e `.content--wide`).

- [ ] **Step 3: Modificare `core/base.html`**

Sostituire la riga 58:

```html
  <div class="content">
```

con:

```html
  <div class="content{% block content_class %}{% endblock %}">
```

- [ ] **Step 4: Aggiungere la regola in `theme.css`**

Subito dopo la regola `.content{…}` (riga 66) aggiungere:

```css
.content--wide{width:100%;max-width:none}
```

- [ ] **Step 5: Eseguire il test → passa**

Run: `python django_app\manage.py test django_app.tasks.tests.CoreWidthOptInTests --settings=config.settings.test --keepdb`
Expected: PASS (2 test).

- [ ] **Step 6: Verifica non-regressione layout globale**

Run: `python django_app\manage.py check --settings=config.settings.test`
Expected: `System check identified no issues`. (Il block è default-vuoto: nessuna pagina esistente cambia larghezza.)

- [ ] **Step 7: Commit**

```powershell
git add django_app/core/templates/core/base.html django_app/core/static/core/css/theme.css django_app/tasks/tests.py
git commit -m "feat(core): opt-in larghezza .content--wide (default-off) per pagine wide"
```

---

## Task 2: Base di modulo `tasks/base.html` + componente `_project_tabs.html`

**Files:**
- Create: `django_app/tasks/templates/tasks/base.html`
- Create: `django_app/tasks/templates/tasks/_project_tabs.html`
- Modify: `django_app/tasks/static/tasks/css/tasks.css` (append stili `.tk-tabs`)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces:
  - `tasks/base.html` con blocchi: `page_eyebrow`, `page_title`, `page_subtitle`, `page_actions`, `content_class` (ripassa a core), `tasks_head`, `tasks_content`, `tasks_scripts`. Context atteso: nessuno obbligatorio (title default "KICK-OFF").
  - `tasks/_project_tabs.html`: include che consuma `project` (con `.id`) e `active` (stringa in `{"detail","gantt","meetings","vrf"}`). Rende link a `tasks:project_gantt`, `tasks:project_meetings`, `tasks:project_vrf_upload`.
- Consumes: `core/components/page_header.html` (arg `eyebrow/title/subtitle`), `core/base.html`.

- [ ] **Step 1: Scrivere il test (fallisce)**

In `tasks/tests.py`:

```python
from django.template.loader import render_to_string


class TasksBaseTemplateTests(TestCase):
    def test_base_extends_core(self):
        src = Path(get_template("tasks/base.html").origin.name).read_text(encoding="utf-8")
        assert 'extends "core/base.html"' in src
        assert "core/components/page_header.html" in src

    def test_project_tabs_render_active(self):
        html = render_to_string(
            "tasks/_project_tabs.html",
            {"project": type("P", (), {"id": 7})(), "active": "gantt"},
        )
        assert "/tasks/projects/7/gantt/" in html
        assert "tk-tab--active" in html
```

- [ ] **Step 2: Eseguire → fallisce**

Run: `python django_app\manage.py test django_app.tasks.tests.TasksBaseTemplateTests --settings=config.settings.test --keepdb`
Expected: FAIL (`TemplateDoesNotExist: tasks/base.html`).

- [ ] **Step 3: Creare `tasks/base.html`**

```html
{% extends "core/base.html" %}
{% load static %}

{% block title %}{{ page_title|default:"KICK-OFF" }} - NOVICROM HUB{% endblock %}

{% block content_class %}{% block tasks_content_class %}{% endblock %}{% endblock %}

{% block extra_head %}
<link rel="stylesheet" href="{% static 'tasks/css/tasks.css' %}">
{% block tasks_head %}{% endblock %}
{% endblock %}

{% block content %}
  {% include "core/components/page_header.html" with eyebrow=page_eyebrow|default:"Workflow operativo" title=page_title|default:"KICK-OFF" subtitle=page_subtitle only %}
  {% block page_actions %}{% endblock %}

  {% if messages %}
    <div class="tk-messages">
      {% for message in messages %}
        <div class="tk-message tk-message--{{ message.tags|default:'info' }}">{{ message }}</div>
      {% endfor %}
    </div>
  {% endif %}

  {% block tasks_content %}{% endblock %}
{% endblock %}

{% block extra_scripts %}{% block tasks_scripts %}{% endblock %}{% endblock %}
```

Nota: le tab di modulo (Dashboard/Kickoff/Impostazioni) NON sono qui — arrivano dalla `subnav.html` condivisa (Task 3). Le azioni primarie di pagina vanno nel block `page_actions`.

- [ ] **Step 4: Creare `tasks/_project_tabs.html`**

```html
{% load static %}
<nav class="tk-tabs" aria-label="Sezioni commessa">
  <a class="tk-tab{% if active == 'gantt' %} tk-tab--active{% endif %}" href="{% url 'tasks:project_gantt' project.id %}">Gantt</a>
  <a class="tk-tab{% if active == 'meetings' %} tk-tab--active{% endif %}" href="{% url 'tasks:project_meetings' project.id %}">Incontri</a>
  <a class="tk-tab{% if active == 'vrf' %} tk-tab--active{% endif %}" href="{% url 'tasks:project_vrf_upload' project.id %}">VRF</a>
</nav>
```

- [ ] **Step 5: Aggiungere gli stili `.tk-tabs` in `tasks.css`**

Append in fondo a `django_app/tasks/static/tasks/css/tasks.css`:

```css
/* ── Tab contestuali di commessa (record-level) ─────────────────── */
.tk-tabs{display:flex;gap:4px;flex-wrap:wrap;margin:0 0 var(--hub-space-4);border-bottom:1px solid var(--border);padding-bottom:0}
.tk-tab{padding:9px 14px;border-radius:var(--hub-radius-md) var(--hub-radius-md) 0 0;font-size:var(--hub-font-sm);font-weight:700;color:var(--text-mid);text-decoration:none;border:1px solid transparent;border-bottom:none;transition:background .12s,color .12s}
.tk-tab:hover{color:var(--text);background:color-mix(in srgb,var(--accent) 8%,transparent)}
.tk-tab--active{color:var(--accent);background:var(--surface);border-color:var(--border);position:relative;top:1px}
.tk-messages{display:flex;flex-direction:column;gap:8px;margin-bottom:var(--hub-space-4)}
.tk-message{padding:10px 14px;border-radius:var(--hub-radius-md);border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:var(--hub-font-sm)}
.tk-message--success{border-color:var(--hub-status-success);background:var(--hub-status-success-bg)}
.tk-message--error,.tk-message--danger{border-color:var(--hub-status-danger);background:var(--hub-status-danger-bg)}
.tk-message--warning{border-color:var(--hub-status-warning);background:var(--hub-status-warning-bg)}
```

- [ ] **Step 6: Eseguire → passa**

Run: `python django_app\manage.py test django_app.tasks.tests.TasksBaseTemplateTests --settings=config.settings.test --keepdb`
Expected: PASS (2 test).

- [ ] **Step 7: Commit**

```powershell
git add django_app/tasks/templates/tasks/base.html django_app/tasks/templates/tasks/_project_tabs.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/tests.py
git commit -m "feat(tasks): base di modulo su core/base + componente tab commessa (chrome condiviso)"
```

---

## Task 3: Seed subnav `NavigationItem` (migrazione dati)

**Files:**
- Create: `django_app/core/migrations/00NN_tasks_subnav.py` (numero = successivo all'ultima migrazione core)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces: 3 `NavigationItem` con `section="subnav"`, `parent_code=<codice nav-top tasks>`: codici `tasks-sub-dashboard` → `tasks:list`, `tasks-sub-kickoff` → `tasks:project_list`, `tasks-sub-impostazioni` → `tasks:impostazioni` (con `required_permission_code="tasks.kickoff.admin"`).
- Il `parent_code` è **risolto a runtime** cercando la voce topbar di `tasks:list` (fallback `"tasks"`), per evitare disallineamenti col codice reale.

- [ ] **Step 1: Trovare il numero di migrazione core successivo**

Run: `python django_app\manage.py showmigrations core --settings=config.settings.test` → prendere l'ultima e usare `N+1` nel nome file (es. se l'ultima è `0060_…`, il file sarà `0061_tasks_subnav.py`).

- [ ] **Step 2: Scrivere il test (fallisce)**

In `tasks/tests.py`:

```python
class TasksSubnavSeedTests(TestCase):
    def test_subnav_items_seeded(self):
        from core.models import NavigationItem
        codes = set(
            NavigationItem.objects.filter(
                section="subnav", code__startswith="tasks-sub-"
            ).values_list("code", flat=True)
        )
        assert {"tasks-sub-dashboard", "tasks-sub-kickoff", "tasks-sub-impostazioni"} <= codes

    def test_impostazioni_is_admin_gated(self):
        from core.models import NavigationItem
        item = NavigationItem.objects.get(code="tasks-sub-impostazioni")
        assert item.required_permission_code == "tasks.kickoff.admin"
        assert item.route_name == "tasks:impostazioni"
```

- [ ] **Step 3: Eseguire → fallisce**

Run: `python django_app\manage.py test django_app.tasks.tests.TasksSubnavSeedTests --settings=config.settings.test --keepdb`
Expected: FAIL (`NavigationItem.DoesNotExist` / set vuoto).

- [ ] **Step 4: Creare la migrazione**

`django_app/core/migrations/00NN_tasks_subnav.py` (sostituire `00NN` e la dependency con i valori reali dallo Step 1):

```python
from django.db import migrations

SEED = [
    {"code": "tasks-sub-dashboard", "label": "Dashboard",
     "route_name": "tasks:list", "order": 10, "perm": "tasks.kickoff.view"},
    {"code": "tasks-sub-kickoff", "label": "Kickoff",
     "route_name": "tasks:project_list", "order": 20, "perm": "tasks.kickoff.projects"},
    {"code": "tasks-sub-impostazioni", "label": "Impostazioni",
     "route_name": "tasks:impostazioni", "order": 30, "perm": "tasks.kickoff.admin"},
]


def _tasks_parent_code(NavigationItem):
    top = (
        NavigationItem.objects.filter(section="topbar", route_name="tasks:list")
        .order_by("id")
        .first()
    )
    return top.code if top else "tasks"


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    parent_code = _tasks_parent_code(NavigationItem)
    for row in SEED:
        NavigationItem.objects.get_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "section": "subnav",
                "parent_code": parent_code,
                "route_name": row["route_name"],
                "order": row["order"],
                "required_permission_code": row["perm"],
                "is_visible": True,
                "is_enabled": True,
            },
        )


def unseed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code__in=[r["code"] for r in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "00NN_PREVIOUS")]  # sostituire con l'ultima migrazione core reale
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 5: Applicare la migrazione e verificare validità**

Run: `python django_app\manage.py makemigrations --check --settings=config.settings.test` (Expected: no changes — la migrazione è a mano, nessun modello nuovo)
Run: `python django_app\manage.py migrate core --settings=config.settings.dev` (applica in dev per lo smoke manuale successivo)

- [ ] **Step 6: Eseguire → passa**

Run: `python django_app\manage.py test django_app.tasks.tests.TasksSubnavSeedTests --settings=config.settings.test --keepdb`
Expected: PASS (2 test).

- [ ] **Step 7: Commit**

```powershell
git add django_app/core/migrations/00NN_tasks_subnav.py django_app/tasks/tests.py
git commit -m "feat(tasks): subnav di modulo via NavigationItem (Dashboard/Kickoff/Impostazioni)"
```

---

## Task 4: Repoint pagina Dashboard (`list.html`)

**Files:**
- Modify: `django_app/tasks/templates/tasks/list.html`

**Interfaces:**
- Consumes: `tasks/base.html` (Task 2), subnav condivisa (Task 3). La view `tasks:list` NON cambia.

- [ ] **Step 1: Repoint del template**

Sostituire la testata:

```html
{% extends "tasks/base_shell.html" %}
{% block tasks_shell_head %}
```
→
```html
{% extends "tasks/base.html" %}
{% block tasks_head %}
```

Sostituire `{% block tasks_shell_content %}` → `{% block tasks_content %}` e i restanti blocchi `tasks_shell_*` con gli equivalenti `tasks_*` / `page_actions` (es. il pulsante "Nuova attività" va in `{% block page_actions %}`). Rimuovere ogni uso di `ts-hero`/`ts-tabs` locali se presenti (la nav è ora condivisa). Impostare, se la view fornisce un contesto per il titolo, `page_title`/`page_subtitle` via blocchi o context (nessuna modifica view: usare i blocchi `{% block page_title %}Dashboard{% endblock %}` se il titolo è statico — ma i blocchi page_* sono variabili nel base; in alternativa passare i valori come blocchi override: aggiungere in `tasks/base.html` `{% block page_title_ovr %}` — vedi nota).

  Nota implementativa: per titoli statici per-pagina, nel `page_header include` usare variabili. Poiché l'include legge `page_title`/`page_subtitle` dal context, e qui non modifichiamo la view, definire in `tasks/base.html` dei blocchi override che precedono l'include:

  ```html
  {% block content %}
    {% include "core/components/page_header.html" with eyebrow=page_eyebrow|default:"Workflow operativo" title=page_title|default:"KICK-OFF" subtitle=page_subtitle only %}
  ```

  Se la view `task_list` non passa `page_title`, la Dashboard mostrerà "KICK-OFF" (accettabile e coerente). Se si vuole "Dashboard", verificare se `task_list` già passa `page_title` (molte view del modulo lo fanno via `page_title`); NON aggiungere logica view in F1 — usare il default.

- [ ] **Step 2: Convertire gli hex del blocco `<style>`**

Applicare la **Recipe hex→token** (Global Constraints) a tutti gli hex del `<style>` di `list.html` (≈171). Esempi concreti presenti nel file:

```css
/* prima */
.tl-table-wrap { … background:#fff; }
.tl-table thead th { background:linear-gradient(180deg,#f4f8fd 0%,#eef4fb 100%); border-bottom:1px solid #dde8f2; color:#475569; }
.tl-table td { color:#1e293b; }
.tl-table tbody tr:hover td { background:#eef5ff; }
```
```css
/* dopo */
.tl-table-wrap { … background:var(--surface); }
.tl-table thead th { background:color-mix(in srgb,var(--surface) 92%,var(--text) 8%); border-bottom:1px solid var(--border); color:var(--text-mid); }
.tl-table td { color:var(--text); }
.tl-table tbody tr:hover td { background:color-mix(in srgb,var(--accent) 7%,var(--surface)); }
```

Per i KPI admin con gradienti (`.tl-admin-kpi.c-blue` ecc.): mantenere il gradiente light e aggiungere un blocco dark:

```css
body.theme-dark .tl-admin-kpi.c-blue   { background:color-mix(in srgb,var(--hub-status-info) 18%,var(--surface)); border-color:var(--border); }
body.theme-dark .tl-admin-kpi.c-amber  { background:color-mix(in srgb,var(--hub-status-warning) 18%,var(--surface)); border-color:var(--border); }
body.theme-dark .tl-admin-kpi.c-teal   { background:color-mix(in srgb,var(--hub-status-success) 16%,var(--surface)); border-color:var(--border); }
body.theme-dark .tl-admin-kpi.c-purple { background:color-mix(in srgb,var(--hub-status-neutral) 20%,var(--surface)); border-color:var(--border); }
body.theme-dark .tl-admin-kpi.c-red    { background:color-mix(in srgb,var(--hub-status-danger) 18%,var(--surface)); border-color:var(--border); }
```

I valori numerici KPI (`.tl-admin-kpi-val.blue` ecc., colori di testo) mantenerli: sono colori-stato leggibili su fondo tenue in entrambi i temi; se in dark il contrasto risulta basso, schiarirli con `color-mix(in srgb, <token stato> 60%, white)` nel blocco `body.theme-dark`.

- [ ] **Step 3: Wrapper tabella e responsività**

Assicurarsi che `.tl-table` sia dentro `.tl-table-wrap { overflow-x:auto }` (già presente). Verificare che le griglie `.tl-admin-kpis`/`.tl-filter-grid` usino `repeat(auto-fit,minmax(…))` o abbiano media query di collasso; se usano `repeat(5,1fr)` fisso, cambiare in `repeat(auto-fit,minmax(150px,1fr))`.

- [ ] **Step 4: Verifica render (dev, manuale)**

Run: `python django_app\manage.py runserver --settings=config.settings.dev` e aprire `/tasks/`.
Expected: pagina con `hub-page-header`, subnav condivisa con "Dashboard" attivo; in dark-mode (toggle tema) testi/tabelle leggibili; nessun blocco chiaro residuo.

- [ ] **Step 5: Check template**

Run: `python django_app\manage.py check --settings=config.settings.test`
Expected: no issues (nessun errore di sintassi template).

- [ ] **Step 6: Commit**

```powershell
git add django_app/tasks/templates/tasks/list.html
git commit -m "refactor(tasks): Dashboard su chrome condiviso + token dark-aware"
```

---

## Task 5: Repoint pagina Kickoff portfolio (`projects.html`)

**Files:**
- Modify: `django_app/tasks/templates/tasks/projects.html`

- [ ] **Step 1: Repoint** — come Task 4 Step 1: `extends "tasks/base.html"`, blocchi `tasks_head`/`tasks_content`/`page_actions` (pulsante "Nuovo kickoff" → `page_actions`). Rimuovere riferimenti a `ts-hero`/`ts-tabs`.

- [ ] **Step 2: Card cover dark-variant** — mantenere i gradienti light delle cover; aggiungere blocco dark:

```css
body.theme-dark .pf-card { background:var(--surface); border-color:var(--border); }
body.theme-dark .pf-card-cover.ok      { background:linear-gradient(135deg,#052e22 0%,#064534 40%,#065f46 100%); }
body.theme-dark .pf-card-cover.warn    { background:linear-gradient(135deg,#3a1c06 0%,#5c340a 40%,#7c4a12 100%); }
body.theme-dark .pf-card-cover.blocked { background:linear-gradient(135deg,#3a0d0d 0%,#5c1414 40%,#7f1d1d 100%); }
body.theme-dark .pf-card-cover.na      { background:linear-gradient(135deg,#0f172a 0%,#1e293b 40%,#334155 100%); }
body.theme-dark .pf-card-cover.pending { background:radial-gradient(ellipse at 80% -20%,rgba(249,115,22,.35) 0%,transparent 50%),linear-gradient(135deg,#0a1120 0%,#12275a 55%,#173a9e 100%); }
```

- [ ] **Step 3: Struttura hex→token** — corpo card (sfondo `#fff`→`var(--surface)`, testo→`var(--text)`/`var(--text-mid)`, bordi→`var(--border)`) secondo Recipe. Le griglie `.pf-grid` usano già `auto-fill,minmax(330px,1fr)` (ok responsive).

- [ ] **Step 4: Verifica render** — `/tasks/projects/` in light+dark: cover leggibili, testo su cover resta bianco, card scure in dark.

- [ ] **Step 5: Check** — `python django_app\manage.py check --settings=config.settings.test` → no issues.

- [ ] **Step 6: Commit**

```powershell
git add django_app/tasks/templates/tasks/projects.html
git commit -m "refactor(tasks): Kickoff portfolio su chrome condiviso + cover dark-variant"
```

---

## Task 6: Repoint dettaglio/form attività (`detail.html`, `form.html`, `project_create.html`)

**Files:**
- Modify: `django_app/tasks/templates/tasks/detail.html`
- Modify: `django_app/tasks/templates/tasks/form.html`
- Modify: `django_app/tasks/templates/tasks/project_create.html`

- [ ] **Step 1: Repoint dei tre template** a `tasks/base.html` (blocchi `tasks_head`/`tasks_content`/`page_actions`). `detail.html`: il vecchio tab "Dettaglio" (mostrato quando `tasks_shell_task`) non serve più come tab di sezione; il contesto è dato dal `page_header` (titolo = titolo attività). Nessun `_project_tabs` qui (le attività non sono commesse).

- [ ] **Step 2: hex→token** su ciascun `<style>` (detail ≈88, form ≈35, project_create ≈27) secondo Recipe. Riusare `.btn` condiviso per i pulsanti dove il template usa bottoni custom con hex.

- [ ] **Step 3: Wrapper** per eventuali tabelle sottotask/allegati (`overflow-x:auto`).

- [ ] **Step 4: Verifica render** — aprire un `/tasks/<id>/`, `/tasks/new/`, `/tasks/projects/new/` in light+dark.

- [ ] **Step 5: Check** — `python django_app\manage.py check --settings=config.settings.test` → no issues.

- [ ] **Step 6: Commit**

```powershell
git add django_app/tasks/templates/tasks/detail.html django_app/tasks/templates/tasks/form.html django_app/tasks/templates/tasks/project_create.html
git commit -m "refactor(tasks): dettaglio/form attività su chrome condiviso + token"
```

---

## Task 7: Repoint Gantt (`project_gantt.html`) — pagina wide + project tabs

**Files:**
- Modify: `django_app/tasks/templates/tasks/project_gantt.html`

- [ ] **Step 1: Repoint + wide** — `extends "tasks/base.html"`; attivare la larghezza piena:

```html
{% block tasks_content_class %} content--wide{% endblock %}
```

Includere le tab commessa in cima al contenuto:

```html
{% block tasks_content %}
  {% include "tasks/_project_tabs.html" with project=project active="gantt" %}
  … resto del Gantt …
{% endblock %}
```

(Verificare il nome reale della variabile di contesto del progetto nella view `project_gantt` — potrebbe essere `project`; se diverso, adeguare l'`include`.)

- [ ] **Step 2: hex→token** sui due `<style>` del Gantt (≈228, il file più pesante). Attenzione a barre/righe Gantt che usano colori-stato: mantenere i colori di stato semantici, ma sfondi/griglia/bordi → token; aggiungere override `body.theme-dark` per la griglia temporale se resta chiara.

- [ ] **Step 3: Verifica render** — `/tasks/projects/<id>/gantt/`: larghezza piena, tab "Gantt" attiva, griglia leggibile in dark.

- [ ] **Step 4: Check** — `python django_app\manage.py check --settings=config.settings.test` → no issues.

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/templates/tasks/project_gantt.html
git commit -m "refactor(tasks): Gantt su chrome condiviso, wide opt-in + tab commessa"
```

---

## Task 8: Repoint Incontri (`project_meetings.html`, `project_meeting_detail.html`, `project_meeting_form.html`)

**Files:**
- Modify: `django_app/tasks/templates/tasks/project_meetings.html`
- Modify: `django_app/tasks/templates/tasks/project_meeting_detail.html`
- Modify: `django_app/tasks/templates/tasks/project_meeting_form.html`

- [ ] **Step 1: Repoint** dei tre template a `tasks/base.html`. In cima al contenuto includere `{% include "tasks/_project_tabs.html" with project=project active="meetings" %}`.

- [ ] **Step 2: hex→token** su ciascun `<style>` (meeting_detail ≈167, meeting_form ≈171, meetings ≈40) secondo Recipe. Questi file hanno molti hex: procedere per sezioni del `<style>` (header, liste, badge, form) e riverificare dopo ogni sezione.

- [ ] **Step 3: Wrapper** tabelle/liste problemi-agenda con `overflow-x:auto` dove servono.

- [ ] **Step 4: Verifica render** — `/tasks/projects/<id>/incontri/`, un dettaglio incontro e il form, in light+dark; tab "Incontri" attiva.

- [ ] **Step 5: Check** — `python django_app\manage.py check --settings=config.settings.test` → no issues.

- [ ] **Step 6: Commit**

```powershell
git add django_app/tasks/templates/tasks/project_meetings.html django_app/tasks/templates/tasks/project_meeting_detail.html django_app/tasks/templates/tasks/project_meeting_form.html
git commit -m "refactor(tasks): Incontri su chrome condiviso + token + tab commessa"
```

---

## Task 9: Repoint VRF (`project_vrf_upload.html`, `project_vrf_compile.html`)

**Files:**
- Modify: `django_app/tasks/templates/tasks/project_vrf_upload.html`
- Modify: `django_app/tasks/templates/tasks/project_vrf_compile.html`

- [ ] **Step 1: Repoint** a `tasks/base.html` + `{% include "tasks/_project_tabs.html" with project=project active="vrf" %}`.

- [ ] **Step 2: hex→token** sui `<style>` (upload ≈62, compile ≈80) secondo Recipe.

- [ ] **Step 3: Verifica render** — `/tasks/projects/<id>/vrf/` e `/vrf/compile/` in light+dark; tab "VRF" attiva.

- [ ] **Step 4: Check** — `python django_app\manage.py check --settings=config.settings.test` → no issues.

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/templates/tasks/project_vrf_upload.html django_app/tasks/templates/tasks/project_vrf_compile.html
git commit -m "refactor(tasks): VRF su chrome condiviso + token + tab commessa"
```

---

## Task 10: Repoint area admin (`impostazioni.html`, `gestione_admin.html`, `import.html`)

**Files:**
- Modify: `django_app/tasks/templates/tasks/impostazioni.html`
- Modify: `django_app/tasks/templates/tasks/gestione_admin.html`
- Modify: `django_app/tasks/templates/tasks/import.html`

- [ ] **Step 1: Repoint** a `tasks/base.html`. Subnav "Impostazioni" risulterà attiva su queste route (gated admin). Nessun project-tab.

- [ ] **Step 2: hex→token** sui `<style>` (impostazioni ≈160, import ≈41, gestione_admin ≈14) secondo Recipe. `impostazioni.html` è pesante: procedere per sezioni.

- [ ] **Step 3: Wrapper** tabelle di configurazione con `overflow-x:auto`.

- [ ] **Step 4: Verifica render** — `/tasks/impostazioni/`, `/tasks/gestione/`, `/tasks/import/` in light+dark.

- [ ] **Step 5: Check** — `python django_app\manage.py check --settings=config.settings.test` → no issues.

- [ ] **Step 6: Commit**

```powershell
git add django_app/tasks/templates/tasks/impostazioni.html django_app/tasks/templates/tasks/gestione_admin.html django_app/tasks/templates/tasks/import.html
git commit -m "refactor(tasks): area admin (impostazioni/gestione/import) su chrome condiviso + token"
```

---

## Task 11: Cutover — rimozione `base_shell.html` + cleanup + render-smoke

**Files:**
- Delete: `django_app/tasks/templates/tasks/base_shell.html`
- Modify: `django_app/core/static/core/css/theme.css` (cleanup `.content>.ts-shell`)
- Modify: `django_app/tasks/static/tasks/css/tasks.css` (rimozione stili shell legacy `.ts-shell/.ts-hero/.ts-tabs/.ts-tab`)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: tutti i template repointati (Task 4–10).

- [ ] **Step 1: Test statico anti-regressione (fallisce se resta legacy)**

In `tasks/tests.py`:

```python
class TasksNoLegacyShellTests(TestCase):
    TASKS_TPL = Path(get_template("tasks/base.html").origin.name).parent

    def test_no_template_extends_base_shell(self):
        offenders = [
            p.name for p in self.TASKS_TPL.glob("*.html")
            if "tasks/base_shell.html" in p.read_text(encoding="utf-8")
        ]
        assert not offenders, f"Ancora su base_shell: {offenders}"

    def test_no_content_maxwidth_override_in_tasks(self):
        for p in self.TASKS_TPL.glob("*.html"):
            txt = p.read_text(encoding="utf-8").replace(" ", "")
            assert "max-width:none!important" not in txt, f"override .content in {p.name}"

    def test_base_shell_removed(self):
        assert not (self.TASKS_TPL / "base_shell.html").exists()
```

- [ ] **Step 2: Eseguire → fallisce** sul terzo test (il file esiste ancora).

Run: `python django_app\manage.py test django_app.tasks.tests.TasksNoLegacyShellTests --settings=config.settings.test --keepdb`
Expected: FAIL (`base_shell.html` esiste; e/o eventuali template non repointati emergono qui).

- [ ] **Step 3: Se emergono offenders** dai primi due test, tornare al task per-pagina corrispondente e completare il repoint. Procedere solo quando i primi due test passano.

- [ ] **Step 4: Eliminare `base_shell.html`**

```powershell
git rm django_app/tasks/templates/tasks/base_shell.html
```

- [ ] **Step 5: Cleanup CSS**

In `theme.css:68`, rimuovere `.content>.ts-shell` dall'elenco dei selettori full-height (lasciando gli altri: `.portal-fill`, `.as-shell`, `.abs-shell`, `.dash`, `#eb-root`). In `tasks.css`, rimuovere le regole ora inutilizzate di `.ts-shell`, `.ts-hero*`, `.ts-tabs`, `.ts-tab*` (NON toccare `--ts-*` né i componenti `pf-*`/`tl-*`/`tk-*`).

- [ ] **Step 6: Render-smoke autenticato (superuser)**

In `tasks/tests.py`:

```python
class TasksRenderSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="smoke_admin", email="s@x.local", password="x"
        )
        cls.project = Project.objects.create(name="Smoke KO")
        cls.task = Task.objects.create(title="Smoke task")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_module_pages_render(self):
        for name in ["tasks:list", "tasks:project_list", "tasks:impostazioni",
                     "tasks:gestione_admin", "tasks:import_excel", "tasks:create"]:
            r = self.client.get(reverse(name))
            assert r.status_code == 200, f"{name} -> {r.status_code}"

    def test_project_pages_render(self):
        pid = self.project.id
        for name in ["tasks:project_gantt", "tasks:project_meetings", "tasks:project_vrf_upload"]:
            r = self.client.get(reverse(name, args=[pid]))
            assert r.status_code == 200, f"{name} -> {r.status_code}"

    def test_task_detail_renders(self):
        r = self.client.get(reverse("tasks:detail", args=[self.task.id]))
        assert r.status_code == 200
```

Nota: verificare i campi minimi obbligatori reali di `Project`/`Task` (aprire `tasks/models.py`); se il costruttore richiede altri campi non-null, aggiungerli nel `setUpTestData`. Il superuser bypassa l'ACL (lo scopo è lo smoke di rendering, non l'ACL — invariata in F1).

- [ ] **Step 7: Eseguire l'intera suite del modulo**

Run: `python django_app\manage.py test django_app.tasks --settings=config.settings.test --keepdb`
Expected: PASS (tutti, inclusi i nuovi smoke). Correggere eventuali `TemplateSyntaxError`/`VariableDoesNotExist` emersi.

- [ ] **Step 8: Commit**

```powershell
git add -A django_app/tasks django_app/core/static/core/css/theme.css
git commit -m "refactor(tasks): cutover — rimozione base_shell legacy + render-smoke KICK-OFF"
```

---

## Task 12: Documentazione e bump versione

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: file di versione (seguire la checklist version-bump)

- [ ] **Step 1: CHANGELOG** — sotto `[Unreleased]` elencare tutti i file toccati e la descrizione: "Uniformazione UI modulo KICK-OFF (F1): chrome condiviso (page_header + subnav NavigationItem), tab commessa, token dark-aware, opt-in larghezza `.content--wide`, rimozione shell legacy."

- [ ] **Step 2: README** — nella tabella catalogo moduli / sezione `tasks` (KICK-OFF), aggiornare la nota UI (allineato al design-system condiviso, dark-mode, responsive).

- [ ] **Step 3: Bump versione** — seguire il checklist in `docs/ai/06_TESTING_AND_QUALITY_GATES.md` (comportamento user-facing cambiato → bump). Aggiornare `CLAUDE.md` "Versione app corrente" se previsto dal checklist.

- [ ] **Step 4: Verifica finale**

Run: `python django_app\manage.py test django_app.tasks --settings=config.settings.test --keepdb`
Run: `python django_app\manage.py check --settings=config.settings.test`
Expected: PASS + no issues.

- [ ] **Step 5: Commit**

```powershell
git add CHANGELOG.md README.md CLAUDE.md
git commit -m "docs(tasks): CHANGELOG + README + bump versione (uniformazione UI KICK-OFF F1)"
```

---

## Self-Review (esito)

**Copertura spec (§4 spec → task):**
- §4.1 chrome/nav (base, page_header, subnav, project tabs) → Task 2, 3, 4–10.
- §4.2 policy larghezza (content--wide, Gantt wide) → Task 1, 7.
- §4.3 token & CSS (hex→token, riuso componenti) → Recipe globale + Task 4–10; cleanup Task 11.
- §4.4 ricchezza preservata (cover/KPI dark-variant) → Task 4 (KPI), 5 (cover).
- §5 confini YAGNI → nessun task tocca view/route/model; readiness/board/calendar/timeline esclusi.
- §6 file impattati → coperti; §7 verifica → test statici (Task 1,2,3,11) + render-smoke (Task 11) + smoke manuale per-pagina.

**Deviazioni dalla spec (motivate):**
- Rename `--ts-*`→`--hub-*` **non** eseguito: `--ts-*` già alias di token dark-aware; rename cosmetico = YAGNI. Il requisito funzionale (dark-mode + coerenza) è comunque soddisfatto. Annotato in Global Constraints.

**Placeholder scan:** nessun "TBD/TODO"; le uniche note "verificare" sono controlli legittimi a runtime (numero migrazione core, nome variabile context progetto, campi obbligatori modelli) con procedura esplicita per risolverli.

**Coerenza tipi/nomi:** blocchi `tasks_content`/`tasks_head`/`tasks_scripts`/`page_actions`/`tasks_content_class` coerenti tra Task 2 e Task 4–10; classi `.tk-tab`/`.tk-tab--active` coerenti tra `_project_tabs.html` (Task 2) e il test (Task 2 Step 1); codici subnav coerenti tra migrazione e test (Task 3).
