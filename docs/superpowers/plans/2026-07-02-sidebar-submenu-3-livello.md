# Sottomenu 3° livello nella sidebar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere un 3° livello (accordion) nella sidebar principale: un modulo (es. Anagrafica) si espande mostrando i propri sotto-moduli.

**Architecture:** Riuso di `core.NavigationItem` con `section='subnav'` + `parent_code`. Le voci subnav il cui `parent_code` coincide con il `code` di un modulo topbar diventano i suoi figli di 3° livello nella sidebar. L'aggancio avviene nel context processor (nuova mappa `parent_code → figli`), il render nella `sidebar.html`. Nessuna migration di schema; l'ACL sulle sotto-voci è già applicata da `_compiled_items_for_role(section='subnav')`.

**Tech Stack:** Django 5.2, template SSR + CSS custom + vanilla JS, SQLite in test / SQL Server in prod.

## Global Constraints

- Test SEMPRE scoping all'app: `python django_app\manage.py test django_app.<app> --settings=config.settings.test --keepdb`. MAI la suite completa.
- Migration di seed: usare SEMPRE `get_or_create(code=..., defaults={...})`, MAI `update_or_create` (non sovrascrivere le personalizzazioni NavBuilder). Cfr. docstring in `core/models.py:240`.
- La visibilità del menu NON è un confine di sicurezza: nessuna nuova route → nessuna modifica a `core/middleware.py` `API_ACL_GATE_PATHS`.
- Nessun dato sensibile nei seed/fixture (solo label + route pubbliche).
- Linkage: una subnav è figlia del modulo topbar **X** sse `subnav.parent_code == X.code`. Il codice topbar di Anagrafica è `"anagrafica"` (`core/module_registry.py:164-171`).
- Anagrafica sopravvive al reuse: le sue pagine sovrascrivono `{% block subnav %}` con il proprio componente, quindi le voci subnav seminate NON compaiono in-pagina (solo nella sidebar).
- Al termine: aggiornare `CHANGELOG.md` (obbligatorio) e `README.md` (se cambia funzionalità visibile). Valutare version-bump.

---

## File Structure

- `django_app/core/navigation_registry.py` — MODIFY: nuova funzione `get_sidebar_children_map()`.
- `django_app/core/context_processors.py` — MODIFY: campo `NavItem.children`, helper `_build_sidebar_children()`, aggancio in `_load_registry_nav_items()`.
- `django_app/core/templates/core/components/sidebar.html` — MODIFY: render 3° livello nel ciclo `grp.items`.
- `django_app/core/static/core/css/theme.css` — MODIFY: stile `.sb-module` / `.sb-mod-items` / `.sb-sub-item--l3`.
- `django_app/core/migrations/00XX_anagrafica_sidebar_subnav.py` — CREATE: seed iniziale sotto-voci Anagrafica.
- `django_app/admin_portale/views.py` — MODIFY (opzionale, Task 6): passare `topbar_modules` al NavBuilder.
- `django_app/admin_portale/templates/admin_portale/pages/navigation_builder.html` — MODIFY (opzionale, Task 6): dropdown "Modulo padre".
- `django_app/core/tests.py` — MODIFY: test unitari registry + helper.

---

## Task 1: Registry — mappa `parent_code → figli`

**Files:**
- Modify: `django_app/core/navigation_registry.py` (dopo `get_subnav_nodes`, ~riga 382)
- Test: `django_app/core/tests.py`

**Interfaces:**
- Produces: `get_sidebar_children_map(*, role_id: int|None, is_admin: bool, legacy_user_id: int|None=None) -> dict[str, list[NavigationNode]]` — chiave = `parent_code`, valore = lista di `NavigationNode` (con `active=False`, ordinati per `order_hint`, poi `label`). Riusa `_compiled_items_for_role(section="subnav")` e `_apply_user_nav_overrides` (stessa ACL/cache di `get_subnav_nodes`).

- [ ] **Step 1: Scrivere il test che fallisce**

In `django_app/core/tests.py` (aggiungere in fondo):

```python
class SidebarChildrenMapTests(TestCase):
    def test_groups_subnav_by_parent_code_ordered(self):
        from core.models import NavigationItem
        from core.navigation_registry import get_sidebar_children_map

        NavigationItem.objects.create(code="topbar-x", label="X", section="topbar", url_path="/x/")
        NavigationItem.objects.create(
            code="x-sub-2", label="Due", section="subnav",
            parent_code="topbar-x", url_path="/x/due/", order=20,
        )
        NavigationItem.objects.create(
            code="x-sub-1", label="Uno", section="subnav",
            parent_code="topbar-x", url_path="/x/uno/", order=10,
        )
        # subnav senza parent → ignorata
        NavigationItem.objects.create(
            code="x-orphan", label="Orfana", section="subnav",
            parent_code="", url_path="/x/orfana/", order=5,
        )

        m = get_sidebar_children_map(role_id=None, is_admin=True, legacy_user_id=None)

        self.assertIn("topbar-x", m)
        self.assertEqual([n.label for n in m["topbar-x"]], ["Uno", "Due"])
        self.assertNotIn("", m)
```

- [ ] **Step 2: Eseguire il test e verificarne il fallimento**

Run: `python django_app\manage.py test django_app.core.tests.SidebarChildrenMapTests --settings=config.settings.test --keepdb`
Expected: FAIL con `ImportError`/`AttributeError` (`get_sidebar_children_map` non esiste).

- [ ] **Step 3: Implementare la funzione**

In `django_app/core/navigation_registry.py`, subito dopo la fine di `get_subnav_nodes` (dopo la riga `return nodes`, ~382):

```python
def get_sidebar_children_map(
    *,
    role_id: int | None,
    is_admin: bool,
    legacy_user_id: int | None = None,
) -> dict[str, list[NavigationNode]]:
    """Mappa parent_code -> voci subnav (ACL-filtrate) per il 3° livello sidebar.

    Riusa la stessa compilazione ACL-aware di get_subnav_nodes (section='subnav'),
    raggruppando per parent_code invece di filtrare su un singolo gruppo.
    Lo stato attivo è calcolato dal context processor (active=False qui).
    """
    compiled = _compiled_items_for_role(
        role_id=role_id,
        is_admin=is_admin,
        section="subnav",
        legacy_user_id=legacy_user_id,
    )
    if legacy_user_id is not None and not is_admin:
        compiled = _apply_user_nav_overrides(compiled, legacy_user_id, "subnav", is_admin)
    out: dict[str, list[NavigationNode]] = {}
    for row in compiled:
        parent = str(row.get("parent_code", "") or "")
        if not parent:
            continue
        out.setdefault(parent, []).append(
            NavigationNode(
                label=row["label"],
                href=row["href"],
                active=False,  # calcolato nel context processor
                order_hint=_safe_int(row["order"], 100),
                coming=bool(row["coming"]),
                legacy_url=row.get("route_name") or row.get("url_path") or "",
                modulo="navigation",
                codice=row["code"],
                icon=row.get("icon", ""),
                group=row.get("group", ""),
                active_patterns=row.get("active_patterns", ""),
            )
        )
    for parent in out:
        out[parent].sort(key=lambda n: (n.order_hint, n.label.lower()))
    return out
```

- [ ] **Step 4: Eseguire il test e verificarne il successo**

Run: `python django_app\manage.py test django_app.core.tests.SidebarChildrenMapTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/core/navigation_registry.py django_app/core/tests.py
git commit -m "feat(core/nav): mappa parent_code->figli per 3° livello sidebar"
```

---

## Task 2: Context processor — aggancio figli al modulo

**Files:**
- Modify: `django_app/core/context_processors.py` (import riga 3 e 23; dataclass `NavItem` ~181; `_load_registry_nav_items` ~413)
- Test: `django_app/core/tests.py`

**Interfaces:**
- Consumes: `get_sidebar_children_map(...)` (Task 1).
- Produces: `NavItem.children: list[NavItem]` popolato per i moduli topbar con figli; `NavItem.active` include lo stato attivo dei figli. Helper `_build_sidebar_children(child_nodes: list, request) -> tuple[list[NavItem], bool]`.

- [ ] **Step 1: Scrivere il test che fallisce**

In `django_app/core/tests.py` (in fondo):

```python
class BuildSidebarChildrenTests(TestCase):
    def test_marks_active_child_by_path(self):
        from django.test import RequestFactory
        from core.context_processors import _build_sidebar_children
        from core.navigation_registry import NavigationNode

        nodes = [
            NavigationNode(label="Uno", href="/x/uno/", active=False, order_hint=10,
                           coming=False, legacy_url="", modulo="navigation", codice="x-sub-1"),
            NavigationNode(label="Due", href="/x/due/", active=False, order_hint=20,
                           coming=False, legacy_url="", modulo="navigation", codice="x-sub-2"),
        ]
        req = RequestFactory().get("/x/due/")
        children, any_active = _build_sidebar_children(nodes, req)

        self.assertEqual([c.label for c in children], ["Uno", "Due"])
        self.assertTrue(any_active)
        self.assertFalse(children[0].active)
        self.assertTrue(children[1].active)

    def test_empty_input(self):
        from django.test import RequestFactory
        from core.context_processors import _build_sidebar_children
        children, any_active = _build_sidebar_children([], RequestFactory().get("/"))
        self.assertEqual(children, [])
        self.assertFalse(any_active)
```

- [ ] **Step 2: Eseguire il test e verificarne il fallimento**

Run: `python django_app\manage.py test django_app.core.tests.BuildSidebarChildrenTests --settings=config.settings.test --keepdb`
Expected: FAIL (`_build_sidebar_children` non esiste; `NavItem` senza `children`).

- [ ] **Step 3: Modificare l'import dataclasses**

`django_app/core/context_processors.py` riga 3:

```python
from dataclasses import dataclass, field
```

- [ ] **Step 4: Aggiungere il campo `children` al dataclass `NavItem`**

In `django_app/core/context_processors.py`, dataclass `NavItem` (~181-197): aggiungere come ultimo campo, dopo `category_order: int = 0`:

```python
    children: list = field(default_factory=list)
```

- [ ] **Step 5: Aggiungere `get_sidebar_children_map` all'import del registry**

Riga 23:

```python
from core.navigation_registry import (
    get_admin_subnav_nodes,
    get_sidebar_children_map,
    get_subnav_nodes,
    get_topbar_nodes,
)
```

- [ ] **Step 6: Aggiungere l'helper `_build_sidebar_children`**

In `django_app/core/context_processors.py`, subito prima di `def _load_registry_nav_items` (~riga 413):

```python
def _build_sidebar_children(child_nodes: list, request) -> tuple[list[NavItem], bool]:
    """Costruisce le NavItem figlie (3° livello) con stato attivo calcolato dal path.

    Match ESATTO su path+query, con fallback al solo path (coerente con _load_subnav_items).
    Ritorna (figli, almeno_uno_attivo).
    """
    if not child_nodes:
        return [], False
    current_variants = _path_variants(request.path)
    try:
        current_full = request.get_full_path()
    except Exception:
        current_full = request.path
    has_exact = any(n.href == current_full for n in child_nodes)
    children: list[NavItem] = []
    any_active = False
    for n in child_nodes:
        if has_exact:
            active = (n.href == current_full)
        else:
            href_path = _normalize_path(urlsplit(n.href).path or "/")
            active = bool(current_variants.intersection({href_path}))
        any_active = any_active or active
        children.append(
            NavItem(
                label=n.label,
                legacy_url=n.legacy_url,
                href=n.href,
                active=active,
                coming=n.coming,
                modulo=n.modulo,
                codice=n.codice,
                icon=n.icon,
                group=n.group,
                order_hint=n.order_hint,
            )
        )
    return children, any_active
```

- [ ] **Step 7: Agganciare i figli in `_load_registry_nav_items`**

In `django_app/core/context_processors.py`, sostituire il blocco finale di `_load_registry_nav_items` (attuale `return [ NavItem(...) for node in nodes ]`, righe ~440-459) con:

```python
    child_map = get_sidebar_children_map(
        role_id=role_id,
        is_admin=is_admin,
        legacy_user_id=legacy_user_id_for_override,
    )
    items: list[NavItem] = []
    for node in nodes:
        children, child_active = _build_sidebar_children(child_map.get(node.codice, []), request)
        items.append(
            NavItem(
                label=node.label,
                legacy_url=node.legacy_url,
                href=node.href,
                active=bool(node.active or child_active),
                coming=node.coming,
                modulo=node.modulo,
                codice=node.codice,
                icon=node.icon,
                group=node.group,
                order_hint=node.order_hint,
                category_color=node.category_color,
                category_key=node.category_key,
                category_label=node.category_label,
                category_icon=node.category_icon,
                category_order=node.category_order,
                children=children,
            )
        )
    return items
```

- [ ] **Step 8: Eseguire i test e verificarne il successo**

Run: `python django_app\manage.py test django_app.core.tests.BuildSidebarChildrenTests django_app.core.tests.SidebarChildrenMapTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add django_app/core/context_processors.py django_app/core/tests.py
git commit -m "feat(core/nav): aggancia i figli subnav ai moduli topbar (3° livello)"
```

---

## Task 3: Sidebar — render + CSS del 3° livello

**Files:**
- Modify: `django_app/core/templates/core/components/sidebar.html` (ciclo `grp.items`, righe 51-57; script in fondo ~184)
- Modify: `django_app/core/static/core/css/theme.css` (dopo la regola `.sb-sub-item.active`, ~riga 182)

**Interfaces:**
- Consumes: `item.children` (Task 2), classi CSS esistenti `.sb-item .sb-sub-item .sb-cat-arrow`.

- [ ] **Step 1: Aggiornare il markup del ciclo `grp.items`**

In `sidebar.html` sostituire il blocco `{% for item in grp.items %} ... {% endfor %}` (righe 51-57) con:

```django
{% for item in grp.items %}
  {% if item.children %}
    <div class="sb-module{% if item.active %} open active{% endif %}" data-key="{{ item.codice }}">
      <div class="sb-mod-head">
        <a class="sb-item sb-sub-item{% if item.active %} active{% endif %}" href="{{ item.href }}" title="{{ item.label }}"{% if item.active %} aria-current="page"{% endif %}>
          <span class="sb-icon" aria-hidden="true">{% render_icon item.icon item.label %}</span>
          <span class="sb-label">{{ item.label }}</span>
        </a>
        <button class="sb-mod-toggle" type="button" aria-expanded="{% if item.active %}true{% else %}false{% endif %}" aria-label="Espandi {{ item.label }}">
          <span class="sb-cat-arrow" aria-hidden="true">&#8250;</span>
        </button>
      </div>
      <div class="sb-mod-items">
        {% for child in item.children %}
          <a class="sb-item sb-sub-item sb-sub-item--l3{% if child.active %} active{% endif %}" href="{{ child.href }}" title="{{ child.label }}"{% if child.active %} aria-current="page"{% endif %}>
            <span class="sb-icon" aria-hidden="true">{% render_icon child.icon child.label %}</span>
            <span class="sb-label">{{ child.label }}</span>
            {% if child.coming %}<span class="sb-item-badge sb-item-badge-dot" aria-hidden="true"></span>{% endif %}
          </a>
        {% endfor %}
      </div>
    </div>
  {% else %}
    <a class="sb-item sb-sub-item{% if item.active %} active{% endif %}" href="{{ item.href }}" title="{{ item.label }}"{% if item.active %} aria-current="page"{% endif %}>
      <span class="sb-icon" aria-hidden="true">{% render_icon item.icon item.label %}</span>
      <span class="sb-label">{{ item.label }}</span>
      {% if item.coming %}<span class="sb-item-badge sb-item-badge-dot" aria-hidden="true"></span>{% endif %}
    </a>
  {% endif %}
{% endfor %}
```

- [ ] **Step 2: Aggiungere l'handler JS per l'accordion di modulo**

In `sidebar.html`, nello `<script>` in fondo, subito dopo il blocco `sidebar.querySelectorAll('.sb-cat-btn').forEach(...)` (dopo la riga 206, prima del `document.addEventListener('click', ...)`):

```javascript
  sidebar.querySelectorAll('.sb-mod-toggle').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var mod = btn.closest('.sb-module');
      if (!mod) return;
      var isOpen = mod.classList.toggle('open');
      btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      if (isOpen && body.classList.contains('sb-collapsed')) {
        body.classList.remove('sb-collapsed');
        syncToggleState();
        persistCollapsed(false);
      }
    });
  });
```

(L'auto-apertura del modulo attivo è già gestita dalla classe `open` aggiunta nel template quando `item.active`.)

- [ ] **Step 3: Aggiungere il CSS del 3° livello**

In `theme.css`, dopo la riga 182 (`.sb-sub-item.active{...}`):

```css
.sb-module{display:flex;flex-direction:column}
.sb-mod-head{display:flex;align-items:center;gap:2px}
.sb-mod-head>.sb-sub-item{flex:1 1 auto}
.sb-mod-toggle{flex:0 0 auto;border:none;background:transparent;cursor:pointer;color:rgba(255,255,255,.55);padding:0 8px;min-height:34px;border-radius:8px}
.sb-mod-toggle:hover{background:rgba(255,255,255,.12);color:#fff}
.sb-mod-toggle .sb-cat-arrow{margin-left:0;transition:transform .2s}
.sb-module.open>.sb-mod-head .sb-mod-toggle .sb-cat-arrow{transform:rotate(90deg)}
.sb-mod-items{display:none}
.sb-module.open>.sb-mod-items{display:block;margin:2px 0 4px 12px;padding:2px 0;border-left:1px solid rgba(255,255,255,.16)}
.sb-sub-item--l3{margin-left:6px;padding-left:12px;font-size:var(--fs-sm);color:rgba(255,255,255,.62)}
.sb-sub-item--l3::before{width:5px;height:5px;background:rgba(255,255,255,.28)}
body.sb-collapsed .sb-module.open>.sb-mod-items{margin-left:6px;border-left:none}
body.sb-collapsed .sb-mod-toggle{display:none}
```

- [ ] **Step 4: Verifica manuale (nessun unit test per template/CSS/JS)**

Prerequisito: aver eseguito il seed (Task 5) o creato a mano una `NavigationItem` topbar + una subnav figlia.
Run: `python django_app\manage.py runserver --settings=config.settings.dev`
Verificare nel browser:
1. Nella categoria che contiene Anagrafica, "Anagrafica" mostra una freccia di espansione.
2. Click sulla freccia → si aprono i sotto-moduli rientrati; click sul nome "Anagrafica" → naviga alla home del modulo.
3. Aprendo una sotto-pagina (es. Dipendenti), al reload il modulo Anagrafica risulta già aperto e la voce attiva evidenziata.
4. Con sidebar collassata, il click sul modulo la riespande (come per le categorie).
5. Regressione: i moduli SENZA figli restano link semplici, invariati.

- [ ] **Step 5: Commit**

```bash
git add django_app/core/templates/core/components/sidebar.html django_app/core/static/core/css/theme.css
git commit -m "feat(core/nav): sidebar 3° livello - render accordion, JS toggle e CSS"
```

---

## Task 4: Seed iniziale sotto-voci Anagrafica

**Files:**
- Create: `django_app/core/migrations/00XX_anagrafica_sidebar_subnav.py` (00XX = numero successivo all'ultima migration `core`; verificare con la lista sotto)
- Test: `django_app/core/tests.py`

**Interfaces:**
- Produces: 3 `NavigationItem` section='subnav', parent_code='anagrafica', codici `anagrafica-sub-dipendenti|-ex-dipendenti|-ruoli-operativi`.

- [ ] **Step 1: Determinare il numero di migration**

Run: `python django_app\manage.py showmigrations core --settings=config.settings.test`
Prendere l'ultima migration `core` applicata (al momento della stesura: `0047_admin_subnav_trigger_generator`) e usarla come dipendenza; nominare il file col numero successivo.

- [ ] **Step 2: Scrivere il test che fallisce**

In `django_app/core/tests.py`:

```python
class AnagraficaSidebarSeedTests(TestCase):
    def test_seed_creates_anagrafica_subnav_children(self):
        from core.models import NavigationItem
        codes = ["anagrafica-sub-dipendenti", "anagrafica-sub-ex-dipendenti", "anagrafica-sub-ruoli-operativi"]
        qs = NavigationItem.objects.filter(code__in=codes)
        self.assertEqual(qs.count(), 3)
        for it in qs:
            self.assertEqual(it.section, "subnav")
            self.assertEqual(it.parent_code, "anagrafica")
```

- [ ] **Step 3: Eseguire il test e verificarne il fallimento**

Run: `python django_app\manage.py test django_app.core.tests.AnagraficaSidebarSeedTests --settings=config.settings.test`
(NB: senza `--keepdb`, così le migration girano da zero.)
Expected: FAIL (`0 != 3`).

- [ ] **Step 4: Creare la migration di seed**

`django_app/core/migrations/00XX_anagrafica_sidebar_subnav.py` (sostituire `0047_admin_subnav_trigger_generator` con l'ultima reale se diversa):

```python
from django.db import migrations

SEED = [
    {"code": "anagrafica-sub-dipendenti", "label": "Dipendenti",
     "route_name": "anagrafica:dipendenti_list", "order": 10},
    {"code": "anagrafica-sub-ex-dipendenti", "label": "Ex dipendenti",
     "route_name": "anagrafica:ex_dipendenti_list", "order": 20},
    {"code": "anagrafica-sub-ruoli-operativi", "label": "Ruoli operativi",
     "route_name": "anagrafica:ruoli_operativi_list", "order": 30},
]


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    for row in SEED:
        NavigationItem.objects.get_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "section": "subnav",
                "parent_code": "anagrafica",
                "route_name": row["route_name"],
                "order": row["order"],
                "is_visible": True,
                "is_enabled": True,
            },
        )


def unseed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code__in=[r["code"] for r in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0047_admin_subnav_trigger_generator")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 5: Eseguire il test e verificarne il successo**

Run: `python django_app\manage.py test django_app.core.tests.AnagraficaSidebarSeedTests --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 6: Verifica non-regressione migrazioni**

Run: `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test`
Expected: "No changes detected" (nessuna migration mancante).

- [ ] **Step 7: Commit**

```bash
git add django_app/core/migrations/00XX_anagrafica_sidebar_subnav.py django_app/core/tests.py
git commit -m "feat(core/nav): seed sotto-voci Anagrafica per il 3° livello sidebar"
```

---

## Task 5: (Opzionale) NavBuilder — dropdown "Modulo padre"

Rende la gestione futura non-tecnica (scegliere il modulo padre da un menù invece di digitare `parent_code`). **Deferibile**: il layout + seed (Task 1-4) funzionano senza questa task. Farla solo se si vuole abilitare la gestione self-service.

**Files:**
- Modify: `django_app/admin_portale/views.py` (`navigation_builder`, ~riga 7806 contesto `render`)
- Modify: `django_app/admin_portale/templates/admin_portale/pages/navigation_builder.html` (campo create ~538, tabella edit ~804)
- Test: `django_app/admin_portale/tests.py`

**Interfaces:**
- Consumes: `NavigationItem` section='topbar'.
- Produces: context `topbar_modules: list[dict{code,label}]`; markup `<select name="parent_code">` popolato.

- [ ] **Step 1: Scrivere il test che fallisce**

In `django_app/admin_portale/tests.py` (adattare al setup admin già presente nel file — riusare il login admin usato dagli altri test di `navigation_builder`):

```python
class NavigationBuilderParentModulesTests(TestCase):
    def test_context_exposes_topbar_modules(self):
        from core.models import NavigationItem
        NavigationItem.objects.create(code="anagrafica", label="Anagrafica", section="topbar", url_path="/anagrafica/")
        self._login_admin()  # helper già usato negli altri test admin (o replicare il login)
        resp = self.client.get("/admin-portale/navigation-builder/")
        self.assertEqual(resp.status_code, 200)
        codes = [m["code"] for m in resp.context["topbar_modules"]]
        self.assertIn("anagrafica", codes)
```

> NB: verificare l'URL reale del NavBuilder in `admin_portale/urls.py` e il metodo di login admin usato dagli altri test dello stesso file; adeguare `_login_admin()`.

- [ ] **Step 2: Eseguire il test e verificarne il fallimento**

Run: `python django_app\manage.py test django_app.admin_portale.tests.NavigationBuilderParentModulesTests --settings=config.settings.test --keepdb`
Expected: FAIL (`KeyError: 'topbar_modules'`).

- [ ] **Step 3: Passare `topbar_modules` al template**

In `django_app/admin_portale/views.py`, dentro `navigation_builder`, prima del `return render(...)` (~7806) calcolare:

```python
    topbar_modules = [
        {"code": it.code, "label": it.label}
        for it in NavigationItem.objects.filter(section="topbar", is_visible=True).order_by("label", "code")
    ]
```

e aggiungerlo al dict di contesto del `render`:

```python
            "topbar_modules": topbar_modules,
```

- [ ] **Step 4: Sostituire il campo `parent_code` con un select nel form di creazione**

In `navigation_builder.html` riga ~538, sostituire l'`<input ... name="parent_code" ...>` con:

```django
<select class="input" name="parent_code">
  <option value="">— Nessuno (voce di 1° livello) —</option>
  {% for mod in topbar_modules %}
    <option value="{{ mod.code }}">{{ mod.label }} ({{ mod.code }})</option>
  {% endfor %}
</select>
```

- [ ] **Step 5: Sostituire il campo `parent_code` nella tabella di modifica**

In `navigation_builder.html` riga ~804, sostituire l'`<input ... data-name="parent_code" ...>` con un `<select data-name="parent_code">` analogo, preselezionando il valore corrente:

```django
<select class="input input-sm" data-name="parent_code" title="Modulo padre">
  <option value="">—</option>
  {% for mod in topbar_modules %}
    <option value="{{ mod.code }}"{% if row.parent_code == mod.code %} selected{% endif %}>{{ mod.label }} ({{ mod.code }})</option>
  {% endfor %}
</select>
```

> NB: la JS di save legge già `data-name="parent_code"` sia da input che da select (`.value`); verificare il selettore usato intorno alla riga 1871 e, se filtra per `input`, includere anche `select`.

- [ ] **Step 6: Eseguire il test e verificarne il successo**

Run: `python django_app\manage.py test django_app.admin_portale.tests.NavigationBuilderParentModulesTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 7: Verifica manuale**

Aprire il NavBuilder, creare una voce section='subnav' scegliendo "Anagrafica" dal menù "Modulo padre", salvare → deve comparire nella sidebar sotto Anagrafica.

- [ ] **Step 8: Commit**

```bash
git add django_app/admin_portale/views.py django_app/admin_portale/templates/admin_portale/pages/navigation_builder.html django_app/admin_portale/tests.py
git commit -m "feat(admin/nav): dropdown 'Modulo padre' per gestire il 3° livello sidebar"
```

---

## Task 6: Documentazione + version bump

**Files:**
- Modify: `CHANGELOG.md` (obbligatorio) e `django_app/CHANGELOG.md` se pertinente
- Modify: `README.md` (sezione navigazione/menu, se presente)
- Modify: `CLAUDE.md` (versione app) + eventuale `docs/ai/GUIDA_AI.html` NON pertinente (feature non-AI)
- Consultare `docs/ai/06_TESTING_AND_QUALITY_GATES.md` per il checklist version-bump

- [ ] **Step 1: Aggiornare `CHANGELOG.md`**

Sotto `[Unreleased]`, elencare i file modificati e la descrizione: "Sidebar: 3° livello (sotto-moduli) per i moduli con voci subnav; seed iniziale Anagrafica; dropdown Modulo padre nel NavBuilder."

- [ ] **Step 2: Aggiornare `README.md`**

Se il README documenta la navigazione/sidebar, aggiungere una riga sul 3° livello e su come gestirlo (NavBuilder → section subnav → Modulo padre).

- [ ] **Step 3: Version bump (se applicabile)**

Seguire il checklist in `docs/ai/06_TESTING_AND_QUALITY_GATES.md`. La funzionalità utente-visibile cambia → valutare bump di `CLAUDE.md` "Versione app corrente".

- [ ] **Step 4: Eseguire i test delle app toccate**

Run: `python django_app\manage.py test django_app.core django_app.admin_portale --settings=config.settings.test --keepdb --verbosity 0`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md CLAUDE.md django_app/CHANGELOG.md
git commit -m "docs(nav): changelog/readme per il 3° livello sidebar"
```

---

## Self-Review

- **Copertura spec**: linkage `parent_code==code` (Task 1-2), accordion 3° livello (Task 3), seed Anagrafica (Task 4), gestione facile via dropdown (Task 5, opzionale), ACL ereditata (Task 1 riusa `_compiled_items_for_role`), solo-sidebar (nessuna modifica a `topnav.html`), niente doppione in-pagina Anagrafica (block subnav sovrascritto). Docs/version-bump (Task 6). ✔
- **Placeholder**: `00XX` nel nome migration è risolto da Task 4 Step 1 (comando esplicito per determinare il numero). Nessun altro placeholder.
- **Coerenza tipi**: `get_sidebar_children_map` (dict[str, list[NavigationNode]]) → consumato da `_build_sidebar_children` (list → tuple[list[NavItem], bool]) → `NavItem.children`. `render_icon` invariato. ✔

## Execution Handoff

Vedi messaggio conversazionale per la scelta della modalità di esecuzione.
