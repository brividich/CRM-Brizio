# Home Portale "Bacheca" + Documenti & Collegamenti — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sostituire la home del portale con una "bacheca" info-hub (News + Documenti & Collegamenti gestibili da admin, Cose da fare, KPI/AI/launcher compatti) e aggiungere una sezione **Documenti & Collegamenti** con gestione admin (categorie, voci file/URL/interne, visibilità per ruolo).

**Architecture:** Modelli in `core` (`HubLinkCategory`, `HubLink`, `HubLinkRoleAccess`) + storage privato cifrato (`HubLinkStorage`). Logica di visibilità in un service puro `core/hub_bacheca.py`. Rendering nella app `dashboard` (home riscritta + pagina `/bacheca/` + download protetto). Gestione admin in `admin_portale`. Nessuna app nuova (evita il pitfall del Setup Wizard).

**Tech Stack:** Django 5.2 SSR + HTMX, `EncryptedStorageMixin` (Fernet/`DOCUMENT_ENCRYPTION_KEY`), token CSS di `theme.css`, test `config.settings.test` su SQLite.

## Global Constraints

- **Tema INTOCCABILE:** riusare SOLO i token esistenti di `core/static/core/css/theme.css` (`--primary #002b5c`, `--accent #ff6b00`, `--bg`, `--surface`, `--border`, `--text`, `--success #38a169`, `--warning #d69e2e`, `--danger #e53e3e`, `--radius 12px`, font **Outfit**) e il dark mode `body.theme-dark`. **Nessuna nuova palette, nessun nuovo font, nessun hardcode di colore.** Il nuovo CSS home migra ai token (cfr. debito dark-mode noto su `home_portale.css`).
- **File caricati fuori webroot:** SOLO via `HubLinkStorage` (cifrato) e serviti SOLO da `hub_link_download` (login + check ruolo + audit). Mai URL pubblico.
- **Modelli in `core`** (mai app nuova): il Setup Wizard fa migrate selettivo → app non registrate rompono la prod.
- **Rotte admin già escluse dal gate ACL** grazie a `@legacy_admin_required` (`LEGACY_ADMIN_BYPASS_ATTR`). Le rotte **pubbliche** `bacheca` e `hub_link_download` vanno aggiunte a `_ACL_SHARED_ROUTE_NAMES` in `core/middleware.py`, altrimenti `ACL_STRICT_CANONICAL` le nega ai non-superuser (i test con superuser NON scoprono il problema).
- **API protette → JSON 401/403**, mai redirect HTML.
- Branch di lavoro: `feature/skill-matrix-mod187` (gira in prod). Working tree condiviso: `git add` solo dei file del task, verifica `git diff --cached`, nessun file dati (.xlsx/.csv/.pdf) staged.
- Semantica ruoli (identica a `NavigationRoleAccess`): nessun record `HubLinkRoleAccess` per una voce ⇒ visibile a tutti; con record ⇒ solo ai `legacy_role_id` con `can_view=True`. `is_admin` bypassa il ruolo ma NON la `is_visible`.
- A fine feature: CHANGELOG.md + README.md + bump `APP_VERSION` (`1.2.1` → `1.3.0`).

## File Structure

| File | Responsabilità | Azione |
|---|---|---|
| `django_app/config/settings/base.py` | `HUB_BACHECA_PRIVATE_ROOT` | Modify |
| `django_app/core/hub_bacheca_storage.py` | Storage privato cifrato bacheca | Create |
| `django_app/core/models.py` | 3 modelli bacheca | Modify (append) |
| `django_app/core/migrations/00XX_hub_bacheca.py` | Migrazione tabelle | Create (makemigrations) |
| `django_app/core/hub_bacheca.py` | Service visibilità (puro) | Create |
| `django_app/core/middleware.py` | Rotte pubbliche condivise | Modify |
| `django_app/dashboard/views_home_portale.py` | Home builder + context snello | Modify |
| `django_app/dashboard/templates/dashboard/pages/home_portale.html` | Layout Bacheca | Modify (rewrite) |
| `django_app/core/static/core/css/home_portale.css` | CSS home (token-only) | Modify (rewrite) |
| `django_app/dashboard/views_bacheca.py` | Pagina `/bacheca/` + download | Create |
| `django_app/dashboard/templates/dashboard/pages/bacheca.html` | Pagina bacheca completa | Create |
| `django_app/dashboard/urls.py` | Rotte bacheca | Modify |
| `django_app/admin_portale/views_bacheca.py` | CRUD admin | Create |
| `django_app/admin_portale/urls.py` | Rotte admin bacheca | Modify |
| `django_app/admin_portale/templates/admin_portale/bacheca.html` | UI gestione | Create |
| `django_app/core/migrations/00YY_navitem_bacheca.py` | Voce subnav admin | Create |
| `django_app/core/tests/test_hub_bacheca*.py` | Test | Create |
| `django_app/dashboard/tests_bacheca.py` | Test home/download | Create |
| `django_app/admin_portale/tests_bacheca.py` | Test admin | Create |

Comando test ricorrente: `python django_app\manage.py test django_app.core django_app.dashboard django_app.admin_portale --settings=config.settings.test --keepdb`

---

### Task 1: Settings + storage privato

**Files:**
- Modify: `django_app/config/settings/base.py` (dopo `ANAGRAFICA_PRIVATE_ROOT`, ~riga 603)
- Create: `django_app/core/hub_bacheca_storage.py`
- Test: `django_app/core/tests/test_hub_bacheca_storage.py`

**Interfaces:**
- Produces: `core.hub_bacheca_storage.HubLinkStorage` (FileSystemStorage cifrato; `url()` solleva `NotImplementedError`); setting `HUB_BACHECA_PRIVATE_ROOT`.

- [ ] **Step 1: Aggiungi il setting**

In `django_app/config/settings/base.py`, subito dopo la riga `ANAGRAFICA_PRIVATE_ROOT = ...`:

```python
# Bacheca "Documenti & Collegamenti": documenti caricati (modulistica, SGI, organigramma).
# Storage privato cifrato FUORI webroot, servito SOLO da dashboard:hub_link_download (ACL + audit).
# Default persistente (fuori da `current`) come GESTIONE_SPECIFICHE_PRIVATE_ROOT: sopravvive ai deploy.
HUB_BACHECA_PRIVATE_ROOT = Path(env("HUB_BACHECA_PRIVATE_ROOT", str(MEDIA_ROOT.parent / "media_private")))
```

- [ ] **Step 2: Scrivi il test che fallisce**

Create `django_app/core/tests/test_hub_bacheca_storage.py`:

```python
from __future__ import annotations

import os
import tempfile

from django.test import TestCase, override_settings

from core.hub_bacheca_storage import HubLinkStorage


class HubLinkStorageTests(TestCase):
    def test_url_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            HubLinkStorage().url("hub_links/2026/07/x.pdf")

    def test_location_points_to_private_root(self):
        tmp = tempfile.mkdtemp()
        with override_settings(HUB_BACHECA_PRIVATE_ROOT=tmp):
            self.assertEqual(HubLinkStorage().location, os.path.abspath(tmp))
```

- [ ] **Step 3: Verifica che fallisca**

Run: `python django_app\manage.py test django_app.core.tests.test_hub_bacheca_storage --settings=config.settings.test`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.hub_bacheca_storage'`

- [ ] **Step 4: Implementa lo storage**

Create `django_app/core/hub_bacheca_storage.py`:

```python
from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage

from core.encrypted_storage import EncryptedStorageMixin


class HubLinkStorage(EncryptedStorageMixin, FileSystemStorage):
    """Storage privato cifrato per i documenti della Bacheca (Documenti & Collegamenti).

    I file sono salvati in ``settings.HUB_BACHECA_PRIVATE_ROOT`` (default
    ``media_private/``), fuori dalla webroot, cifrati at-rest via
    ``DOCUMENT_ENCRYPTION_KEY``. L'accesso passa SEMPRE per la view protetta
    ``dashboard:hub_link_download`` (ACL per-voce + audit).
    """

    @property
    def base_location(self):
        return str(settings.HUB_BACHECA_PRIVATE_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError(
            "I documenti della bacheca non sono serviti su URL pubblico. "
            "Usa {% url 'hub_link_download' link.id %}."
        )
```

- [ ] **Step 5: Verifica che passi**

Run: `python django_app\manage.py test django_app.core.tests.test_hub_bacheca_storage --settings=config.settings.test`
Expected: PASS (2 test)

- [ ] **Step 6: Commit**

```bash
git add django_app/config/settings/base.py django_app/core/hub_bacheca_storage.py django_app/core/tests/test_hub_bacheca_storage.py
git commit -m "feat(bacheca): storage privato cifrato per documenti Documenti & Collegamenti"
```

---

### Task 2: Modelli + migrazione

**Files:**
- Modify: `django_app/core/models.py` (append in fondo)
- Create: `django_app/core/migrations/00XX_hub_bacheca.py` (via makemigrations)
- Test: `django_app/core/tests/test_hub_bacheca_models.py`

**Interfaces:**
- Consumes: `HubLinkStorage` (Task 1).
- Produces:
  - `HubLinkCategory(name, slug, icon, description, order, is_visible, ...)`
  - `HubLink(category, kind∈{file,url,internal}, title, description, icon, url, route_name, route_kwargs, file, original_filename, file_size, content_type, open_in_new_tab, order, is_visible, ...)`; costanti `HubLink.KIND_FILE|KIND_URL|KIND_INTERNAL`; metodi `clean()`, `resolve_href()`.
  - `HubLinkRoleAccess(link, legacy_role_id, can_view)`.

- [ ] **Step 1: Scrivi i test che falliscono**

Create `django_app/core/tests/test_hub_bacheca_models.py`:

```python
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import HubLink, HubLinkCategory


class HubLinkModelTests(TestCase):
    def setUp(self):
        self.cat = HubLinkCategory.objects.create(name="Modulistica", slug="modulistica")

    def test_clean_url_requires_url(self):
        link = HubLink(category=self.cat, kind=HubLink.KIND_URL, title="Gestionale", url="")
        with self.assertRaises(ValidationError):
            link.clean()

    def test_clean_internal_requires_route_name(self):
        link = HubLink(category=self.cat, kind=HubLink.KIND_INTERNAL, title="Ferie", route_name="")
        with self.assertRaises(ValidationError):
            link.clean()

    def test_clean_url_ok(self):
        link = HubLink(category=self.cat, kind=HubLink.KIND_URL, title="Gestionale",
                       url="https://esempio.local")
        link.clean()  # non solleva

    def test_resolve_href_url(self):
        link = HubLink.objects.create(category=self.cat, kind=HubLink.KIND_URL,
                                      title="Gestionale", url="https://esempio.local")
        self.assertEqual(link.resolve_href(), "https://esempio.local")

    def test_resolve_href_internal_unknown_route_is_hash(self):
        link = HubLink.objects.create(category=self.cat, kind=HubLink.KIND_INTERNAL,
                                      title="X", route_name="rotta_inesistente_xyz")
        self.assertEqual(link.resolve_href(), "#")
```

- [ ] **Step 2: Verifica fallimento**

Run: `python django_app\manage.py test django_app.core.tests.test_hub_bacheca_models --settings=config.settings.test`
Expected: FAIL — `ImportError: cannot import name 'HubLink'`

- [ ] **Step 3: Aggiungi i modelli**

Append in fondo a `django_app/core/models.py` (in cima al file sono già importati `models` e `settings`; aggiungi in cima `from django.core.exceptions import ValidationError` e `from django.urls import NoReverseMatch, reverse` se non presenti):

```python
class HubLinkCategory(models.Model):
    """Categoria della bacheca 'Documenti & Collegamenti' (gestita da admin)."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    icon = models.CharField(max_length=500, blank=True, default="",
                            help_text="Emoji, alias SVG o URL immagine.")
    description = models.CharField(max_length=255, blank=True, default="")
    order = models.IntegerField(default=100)
    is_visible = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_categories_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_categories_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name", "id"]

    def __str__(self) -> str:
        return f"HubCat<{self.slug}>"


class HubLink(models.Model):
    """Voce della bacheca: documento caricato, collegamento esterno o scorciatoia interna."""

    KIND_FILE = "file"
    KIND_URL = "url"
    KIND_INTERNAL = "internal"
    KIND_CHOICES = [
        (KIND_FILE, "Documento"),
        (KIND_URL, "Collegamento esterno"),
        (KIND_INTERNAL, "Scorciatoia interna"),
    ]

    category = models.ForeignKey(HubLinkCategory, on_delete=models.CASCADE, related_name="links")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=300, blank=True, default="")
    icon = models.CharField(max_length=500, blank=True, default="")
    # target per kind:
    url = models.CharField(max_length=500, blank=True, default="")            # kind=url
    route_name = models.CharField(max_length=160, blank=True, default="")     # kind=internal
    route_kwargs = models.JSONField(default=dict, blank=True)                 # kind=internal (opzionale)
    file = models.FileField(storage=HubLinkStorage(), upload_to="hub_links/%Y/%m",
                            blank=True, null=True)                            # kind=file
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file_size = models.PositiveIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=120, blank=True, default="")
    open_in_new_tab = models.BooleanField(default=False)
    order = models.IntegerField(default=100)
    is_visible = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_links_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="hub_links_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title", "id"]

    def __str__(self) -> str:
        return f"HubLink<{self.kind}:{self.title}>"

    def clean(self):
        if self.kind == self.KIND_URL:
            if not (self.url or "").strip():
                raise ValidationError({"url": "URL obbligatorio per un collegamento esterno."})
        elif self.kind == self.KIND_INTERNAL:
            if not (self.route_name or "").strip():
                raise ValidationError({"route_name": "Nome route obbligatorio per una scorciatoia interna."})
        elif self.kind == self.KIND_FILE:
            if not self.file:
                raise ValidationError({"file": "File obbligatorio per un documento."})
        else:
            raise ValidationError({"kind": "Tipo non valido."})

    def resolve_href(self) -> str:
        if self.kind == self.KIND_URL:
            return self.url or "#"
        if self.kind == self.KIND_INTERNAL:
            try:
                return reverse(self.route_name, kwargs=self.route_kwargs or None)
            except NoReverseMatch:
                return "#"
        if self.kind == self.KIND_FILE:
            try:
                return reverse("hub_link_download", args=[self.pk])
            except NoReverseMatch:
                return "#"
        return "#"


class HubLinkRoleAccess(models.Model):
    """Visibilità per ruolo di una voce bacheca (come NavigationRoleAccess).

    Nessun record per una voce ⇒ visibile a TUTTI i ruoli.
    """

    link = models.ForeignKey(HubLink, on_delete=models.CASCADE, related_name="role_accesses")
    legacy_role_id = models.IntegerField(db_index=True)
    can_view = models.BooleanField(default=True)

    class Meta:
        unique_together = [("link", "legacy_role_id")]

    def __str__(self) -> str:
        return f"HubLinkAccess<link={self.link_id} role={self.legacy_role_id}>"
```

- [ ] **Step 4: Genera la migrazione**

Run: `python django_app\manage.py makemigrations core --settings=config.settings.test`
Expected: crea `core/migrations/00XX_hub_bacheca.py` con `HubLinkCategory`, `HubLink`, `HubLinkRoleAccess`. Verifica che NON tocchi altri modelli.

- [ ] **Step 5: Verifica che i test passino**

Run: `python django_app\manage.py test django_app.core.tests.test_hub_bacheca_models --settings=config.settings.test`
Expected: PASS (5 test)

- [ ] **Step 6: Commit**

```bash
git add django_app/core/models.py django_app/core/migrations/00XX_hub_bacheca.py django_app/core/tests/test_hub_bacheca_models.py
git commit -m "feat(bacheca): modelli HubLinkCategory/HubLink/HubLinkRoleAccess + migrazione"
```

---

### Task 3: Service visibilità (`core/hub_bacheca.py`)

**Files:**
- Create: `django_app/core/hub_bacheca.py`
- Test: `django_app/core/tests/test_hub_bacheca_service.py`

**Interfaces:**
- Consumes: modelli Task 2.
- Produces:
  - `link_visible_to_role(link, legacy_role_id: int | None, is_admin: bool) -> bool`
  - `visible_bacheca(legacy_role_id: int | None, is_admin: bool = False, preview_limit: int | None = None) -> list[dict]` dove ogni dict è `{"category": HubLinkCategory, "items": list[HubLink], "total": int, "more": int}`.

- [ ] **Step 1: Scrivi i test che falliscono**

Create `django_app/core/tests/test_hub_bacheca_service.py`:

```python
from __future__ import annotations

from django.test import TestCase

from core.hub_bacheca import link_visible_to_role, visible_bacheca
from core.models import HubLink, HubLinkCategory, HubLinkRoleAccess


def _url_link(cat, title, order=100, visible=True):
    return HubLink.objects.create(category=cat, kind=HubLink.KIND_URL, title=title,
                                  url="https://esempio.local", order=order, is_visible=visible)


class HubBachecaServiceTests(TestCase):
    def setUp(self):
        self.cat = HubLinkCategory.objects.create(name="Collegamenti", slug="coll", order=10)

    def test_no_access_rows_visible_to_all(self):
        link = _url_link(self.cat, "Aperto")
        self.assertTrue(link_visible_to_role(link, legacy_role_id=None, is_admin=False))
        self.assertTrue(link_visible_to_role(link, legacy_role_id=7, is_admin=False))

    def test_access_rows_restrict(self):
        link = _url_link(self.cat, "Riservato")
        HubLinkRoleAccess.objects.create(link=link, legacy_role_id=5, can_view=True)
        self.assertTrue(link_visible_to_role(link, legacy_role_id=5, is_admin=False))
        self.assertFalse(link_visible_to_role(link, legacy_role_id=9, is_admin=False))
        self.assertFalse(link_visible_to_role(link, legacy_role_id=None, is_admin=False))

    def test_admin_bypasses_role_but_not_hidden(self):
        link = _url_link(self.cat, "Riservato")
        HubLinkRoleAccess.objects.create(link=link, legacy_role_id=5, can_view=True)
        self.assertTrue(link_visible_to_role(link, legacy_role_id=None, is_admin=True))
        hidden = _url_link(self.cat, "Nascosto", visible=False)
        self.assertFalse(link_visible_to_role(hidden, legacy_role_id=None, is_admin=True))

    def test_visible_bacheca_hidden_category_excluded(self):
        HubLinkCategory.objects.create(name="Nascosta", slug="nasc", is_visible=False)
        cat2 = HubLinkCategory.objects.get(slug="nasc")
        _url_link(cat2, "X")
        _url_link(self.cat, "Y")
        groups = visible_bacheca(legacy_role_id=None, is_admin=False)
        slugs = [g["category"].slug for g in groups]
        self.assertIn("coll", slugs)
        self.assertNotIn("nasc", slugs)

    def test_visible_bacheca_empty_category_excluded(self):
        HubLinkCategory.objects.create(name="Vuota", slug="vuota")
        groups = visible_bacheca(legacy_role_id=None, is_admin=False)
        self.assertEqual([g["category"].slug for g in groups], ["coll"] if False else [])
        # nessun link → nessun gruppo
        self.assertEqual(groups, [])

    def test_preview_limit_and_more(self):
        for i in range(6):
            _url_link(self.cat, f"L{i}", order=i)
        groups = visible_bacheca(legacy_role_id=None, is_admin=False, preview_limit=4)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["items"]), 4)
        self.assertEqual(groups[0]["total"], 6)
        self.assertEqual(groups[0]["more"], 2)
```

- [ ] **Step 2: Verifica fallimento**

Run: `python django_app\manage.py test django_app.core.tests.test_hub_bacheca_service --settings=config.settings.test`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.hub_bacheca'`

- [ ] **Step 3: Implementa il service**

Create `django_app/core/hub_bacheca.py`:

```python
"""Service di lettura della bacheca 'Documenti & Collegamenti'.

Funzioni pure che filtrano categorie/voci per ruolo legacy dell'utente.
Usato da: home (dashboard), pagina /bacheca/, download protetto.
"""
from __future__ import annotations

from core.models import HubLinkCategory


def link_visible_to_role(link, legacy_role_id, is_admin: bool) -> bool:
    """True se la voce è visibile all'utente con quel ruolo legacy.

    - is_visible=False ⇒ mai visibile (nemmeno all'admin, sulla bacheca pubblica).
    - is_admin ⇒ bypassa la restrizione di ruolo.
    - nessun HubLinkRoleAccess ⇒ visibile a tutti.
    - con record ⇒ visibile solo ai legacy_role_id con can_view=True.
    """
    if not link.is_visible:
        return False
    if is_admin:
        return True
    accesses = list(link.role_accesses.all())
    if not accesses:
        return True
    if legacy_role_id is None:
        return False
    return any(a.legacy_role_id == legacy_role_id and a.can_view for a in accesses)


def visible_bacheca(legacy_role_id, is_admin: bool = False, preview_limit=None) -> list[dict]:
    """Categorie visibili con le rispettive voci filtrate per ruolo.

    Ritorna: [{"category": HubLinkCategory, "items": [HubLink], "total": int, "more": int}]
    Le categorie senza voci visibili sono escluse.
    """
    categories = (
        HubLinkCategory.objects.filter(is_visible=True)
        .prefetch_related("links__role_accesses")
        .order_by("order", "name", "id")
    )
    result: list[dict] = []
    for cat in categories:
        items = [
            link for link in cat.links.all()
            if link_visible_to_role(link, legacy_role_id, is_admin)
        ]
        if not items:
            continue
        shown = items[:preview_limit] if preview_limit else items
        result.append({
            "category": cat,
            "items": shown,
            "total": len(items),
            "more": max(0, len(items) - len(shown)),
        })
    return result
```

- [ ] **Step 4: Verifica che i test passino**

Run: `python django_app\manage.py test django_app.core.tests.test_hub_bacheca_service --settings=config.settings.test`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add django_app/core/hub_bacheca.py django_app/core/tests/test_hub_bacheca_service.py
git commit -m "feat(bacheca): service di visibilità per ruolo (visible_bacheca)"
```

---

### Task 4: Home data layer (builder + context snello)

**Files:**
- Modify: `django_app/dashboard/views_home_portale.py`
- Test: `django_app/dashboard/tests_bacheca.py`

**Interfaces:**
- Consumes: `core.hub_bacheca.visible_bacheca` (Task 3).
- Produces: `_documenti_collegamenti(request, preview=True) -> list[dict]` con item mappati per il template (`{name, icon, slug, items:[{title, description, kind, kind_label, icon, href, open_in_new_tab}], more}`); costante `BACHECA_PREVIEW_PER_CATEGORY = 4`. Rimuove dal context: `calendar_week`, `safety_kpis`, `system_status`. Aggiunge `bacheca_groups`. Aggiunge `module_launcher` (lista piatta di card home-modulo).

- [ ] **Step 1: Scrivi il test che fallisce**

Create `django_app/dashboard/tests_bacheca.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from django.test import TestCase

from core.models import HubLink, HubLinkCategory
from dashboard import views_home_portale as hp


class DocumentiCollegamentiHelperTests(TestCase):
    def setUp(self):
        self.cat = HubLinkCategory.objects.create(name="Modulistica", slug="modulistica", order=1)
        HubLink.objects.create(category=self.cat, kind=HubLink.KIND_URL,
                               title="Gestionale", url="https://esempio.local")

    def _admin_request(self):
        # is_superuser=True ⇒ is_admin True ⇒ nessuna dipendenza da tabelle legacy
        return SimpleNamespace(
            user=SimpleNamespace(is_superuser=True, get_username=lambda: "admin",
                                 first_name="", email=""),
            legacy_user=SimpleNamespace(id=1, ruolo="AMMINISTRAZIONE", ruolo_id=1, nome="Admin"),
        )

    def test_documenti_collegamenti_shape(self):
        groups = hp._documenti_collegamenti(self._admin_request())
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g["name"], "Modulistica")
        self.assertEqual(g["items"][0]["title"], "Gestionale")
        self.assertEqual(g["items"][0]["kind_label"], "Link")
        self.assertEqual(g["items"][0]["href"], "https://esempio.local")
        self.assertTrue(g["items"][0]["open_in_new_tab"])
```

- [ ] **Step 2: Verifica fallimento**

Run: `python django_app\manage.py test django_app.dashboard.tests_bacheca --settings=config.settings.test`
Expected: FAIL — `AttributeError: module ... has no attribute '_documenti_collegamenti'`

- [ ] **Step 3: Implementa il builder e aggiorna il context**

In `django_app/dashboard/views_home_portale.py`:

(a) aggiungi import in cima (accanto agli altri):
```python
from core.hub_bacheca import visible_bacheca
from core.models import HubLink
```

(b) aggiungi la costante e il builder (prima di `home_portale`):
```python
BACHECA_PREVIEW_PER_CATEGORY = 4

_KIND_LABEL = {HubLink.KIND_FILE: "File", HubLink.KIND_URL: "Link", HubLink.KIND_INTERNAL: "Interna"}


def _documenti_collegamenti(request, preview: bool = True) -> list[dict]:
    """Sezione Documenti & Collegamenti per la home / pagina bacheca."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    role_id = getattr(legacy_user, "ruolo_id", None)
    limit = BACHECA_PREVIEW_PER_CATEGORY if preview else None
    groups = visible_bacheca(role_id, is_admin=is_admin, preview_limit=limit)
    out: list[dict] = []
    for g in groups:
        cat = g["category"]
        out.append({
            "name": cat.name,
            "icon": cat.icon,
            "slug": cat.slug,
            "more": g["more"],
            "items": [{
                "title": l.title,
                "description": l.description,
                "kind": l.kind,
                "kind_label": _KIND_LABEL.get(l.kind, ""),
                "icon": l.icon,
                "href": l.resolve_href(),
                "open_in_new_tab": bool(l.open_in_new_tab or l.kind == HubLink.KIND_URL),
            } for l in g["items"]],
        })
    return out


def _module_launcher(groups: list[dict]) -> list[dict]:
    """Appiattisce i module_groups in un'unica lista di card 'home modulo' (dedup)."""
    seen: set[str] = set()
    flat: list[dict] = []
    for grp in groups:
        for mod in grp.get("modules", []):
            key = str(mod.get("id") or mod.get("label") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            flat.append(mod)
    return flat
```

(c) in `home_portale()`, nel dict `context`:
- **rimuovi** le chiavi `"calendar_week"`, `"safety_kpis"`, `"system_status"` (e le rispettive righe che le calcolano: `_calendar_week`, `_safety_kpis`, `_system_status` — lascia le funzioni definite, ma non chiamarle nel context; oppure rimuovile se non usate altrove);
- **aggiungi**:
```python
        "bacheca_groups":     _documenti_collegamenti(request),
        "module_launcher":    _module_launcher(groups),
```

- [ ] **Step 4: Verifica che il test passi**

Run: `python django_app\manage.py test django_app.dashboard.tests_bacheca --settings=config.settings.test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add django_app/dashboard/views_home_portale.py django_app/dashboard/tests_bacheca.py
git commit -m "feat(bacheca): home builder Documenti & Collegamenti + launcher moduli snello"
```

---

### Task 5: Home template + CSS (layout Bacheca)

**Files:**
- Modify: `django_app/dashboard/templates/dashboard/pages/home_portale.html`
- Modify: `django_app/core/static/core/css/home_portale.css`

**Interfaces:**
- Consumes: context Task 4 (`bacheca_groups`, `module_launcher`, `priority_kpis`, `news_items`, `cose_da_gestire`, `ai_daily_brief_enabled`, `greeting*`).

> Nota: la parte presentazionale si verifica con un render/GET reale in dev; qui il "test" è manuale (runserver) + il test helper del Task 4 già verde. Non introdurre nuovi colori: usare i token di `theme.css`.

- [ ] **Step 1: Riscrivi il template nell'ordine Bacheca**

In `home_portale.html` sostituisci il body `{% block content %}` con l'ordine: saluto → KPI → **bacheca (2 col: news | documenti)** → cose da fare → brief AI → launcher moduli → footer. Rimuovi le sezioni `hp-board` (presenze), `hp-bottom` (safety/system) e i `module_groups` densi. La colonna Documenti itera `bacheca_groups`:

```django
<section class="hp-bacheca">
  <div class="hp-card hp-news-card">
    <header class="hp-card-h">
      <h3 class="hp-card-t">News aziendali</h3>
      <a href="{% url 'notizie_lista' %}" class="hp-card-link">Vedi tutte →</a>
    </header>
    <ul class="hp-news">
      {% for n in news_items %}
        <li><a href="{{ n.url }}"><span class="hp-news-mark"></span>
          <span class="hp-news-body"><span class="hp-news-t">{{ n.title }}</span>
          <span class="hp-news-m">{{ n.source }}</span></span>
          <span class="hp-news-time">{{ n.ago }}</span></a></li>
      {% empty %}<li class="hp-empty">Nessuna notizia recente.</li>{% endfor %}
    </ul>
  </div>

  <div class="hp-card hp-docs-card">
    <header class="hp-card-h">
      <h3 class="hp-card-t">Documenti &amp; Collegamenti</h3>
      <a href="{% url 'bacheca' %}" class="hp-card-link">Apri tutti →</a>
    </header>
    <div class="hp-docs">
      {% for cat in bacheca_groups %}
        <div class="hp-docs-cat">
          <div class="hp-docs-cat-h">
            <span class="hp-docs-cat-nm">{{ cat.name }}</span>
            <span class="hp-docs-cat-ct">{{ cat.items|length }}</span>
          </div>
          {% for it in cat.items %}
            <a class="hp-doc k-{{ it.kind }}" href="{{ it.href }}"
               {% if it.open_in_new_tab %}target="_blank" rel="noopener"{% endif %}>
              <span class="hp-doc-ic" aria-hidden="true"></span>
              <span class="hp-doc-bd"><span class="hp-doc-t">{{ it.title }}</span>
                <span class="hp-doc-d">{{ it.description }}</span></span>
              <span class="hp-doc-kind">{{ it.kind_label }}</span>
            </a>
          {% endfor %}
          {% if cat.more %}<a class="hp-doc-more" href="{% url 'bacheca' %}#{{ cat.slug }}">+{{ cat.more }} altri →</a>{% endif %}
        </div>
      {% empty %}
        <p class="hp-empty">Nessun documento o collegamento pubblicato.</p>
      {% endfor %}
    </div>
  </div>
</section>
```

Il launcher moduli itera `module_launcher` (riusa `core/components/_home_module_tile.html` o una card semplice).

- [ ] **Step 2: Aggiorna il CSS (solo token)**

In `home_portale.css` aggiungi/riscrivi le classi `hp-bacheca`, `hp-docs*`, `hp-doc*` usando SOLO variabili di `theme.css`. Esempio guida:

```css
.hp-bacheca{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
.hp-doc{display:flex;align-items:center;gap:11px;padding:9px;border-radius:10px;text-decoration:none;color:var(--text)}
.hp-doc:hover{background:var(--bg)}
.hp-doc .hp-doc-ic{width:32px;height:32px;border-radius:8px;border:1px solid var(--border);background:var(--surface)}
.hp-doc.k-file .hp-doc-ic{color:var(--danger)}
.hp-doc.k-url .hp-doc-ic{color:var(--primary-mid)}
.hp-doc.k-internal .hp-doc-ic{color:var(--accent)}
.hp-doc-kind{font-size:var(--fs-2xs);font-weight:700;text-transform:uppercase;padding:2px 7px;border-radius:6px}
.hp-doc.k-file .hp-doc-kind{background:var(--danger-bg);color:var(--danger)}
.hp-doc.k-url .hp-doc-kind{background:var(--accent-light);color:var(--primary-mid)}
.hp-doc.k-internal .hp-doc-kind{background:var(--accent-light);color:var(--accent)}
@media (max-width:900px){.hp-bacheca{grid-template-columns:1fr}}
```
Aggiungi gli override `body.theme-dark` se una classe introduce uno sfondo chiaro esplicito (preferisci i token, che il dark già ridefinisce).

- [ ] **Step 3: Verifica manuale**

Run: `python django_app\manage.py runserver --settings=config.settings.dev` → apri `/` → verifica layout Bacheca, tema chiaro **e** scuro (toggle tema), responsive < 900px. Con 0 voci: messaggio "Nessun documento…".

- [ ] **Step 4: Verifica non-regressione test dashboard**

Run: `python django_app\manage.py test django_app.dashboard --settings=config.settings.test --keepdb`
Expected: PASS (inclusi i test esistenti).

- [ ] **Step 5: Commit**

```bash
git add django_app/dashboard/templates/dashboard/pages/home_portale.html django_app/core/static/core/css/home_portale.css
git commit -m "feat(bacheca): home layout 'Bacheca' (News + Documenti & Collegamenti), token-only"
```

---

### Task 6: Pagina `/bacheca/` + download protetto + rotte pubbliche

**Files:**
- Create: `django_app/dashboard/views_bacheca.py`
- Create: `django_app/dashboard/templates/dashboard/pages/bacheca.html`
- Modify: `django_app/dashboard/urls.py`
- Modify: `django_app/core/middleware.py` (`_ACL_SHARED_ROUTE_NAMES`)
- Test: append a `django_app/dashboard/tests_bacheca.py`

**Interfaces:**
- Consumes: `core.hub_bacheca` (Task 3), `HubLink`.
- Produces: view `bacheca` (name `bacheca`), view `hub_link_download` (name `hub_link_download`).

- [ ] **Step 1: Scrivi i test che falliscono**

Append a `django_app/dashboard/tests_bacheca.py`:

```python
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from core.models import HubLinkRoleAccess


class HubLinkDownloadTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(username="mario", password="x")
        self.cat = HubLinkCategory.objects.create(name="Modulistica", slug="modulistica")
        self.tmp = tempfile.mkdtemp()

    def _file_link(self, title="Doc", roles=None):
        from core.models import HubLink
        link = HubLink.objects.create(
            category=self.cat, kind=HubLink.KIND_FILE, title=title,
            file=SimpleUploadedFile("m187.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
            original_filename="m187.pdf",
        )
        for rid in (roles or []):
            HubLinkRoleAccess.objects.create(link=link, legacy_role_id=rid)
        return link

    def test_public_file_download_ok(self):
        with override_settings(HUB_BACHECA_PRIVATE_ROOT=self.tmp):
            link = self._file_link()
            self.client.force_login(self.user)
            r = self.client.get(reverse("hub_link_download", args=[link.pk]))
            self.assertEqual(r.status_code, 200)

    def test_restricted_file_denied_for_user_without_role(self):
        with override_settings(HUB_BACHECA_PRIVATE_ROOT=self.tmp):
            link = self._file_link(roles=[5])   # utente test non ha ruolo legacy → None
            self.client.force_login(self.user)
            r = self.client.get(reverse("hub_link_download", args=[link.pk]))
            self.assertEqual(r.status_code, 404)

    def test_download_requires_login(self):
        link = self._file_link()
        r = self.client.get(reverse("hub_link_download", args=[link.pk]))
        self.assertIn(r.status_code, (302, 401, 403))
```

- [ ] **Step 2: Verifica fallimento**

Run: `python django_app\manage.py test django_app.dashboard.tests_bacheca --settings=config.settings.test`
Expected: FAIL — `NoReverseMatch: 'hub_link_download'`

- [ ] **Step 3: Implementa le view**

Create `django_app/dashboard/views_bacheca.py`:

```python
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from core.audit import log_action
from core.hub_bacheca import link_visible_to_role, visible_bacheca
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.models import HubLink


def _identity(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    role_id = getattr(legacy_user, "ruolo_id", None)
    return legacy_user, is_admin, role_id


@login_required
def bacheca(request):
    _, is_admin, role_id = _identity(request)
    groups = visible_bacheca(role_id, is_admin=is_admin, preview_limit=None)
    from dashboard.views_home_portale import _KIND_LABEL
    view_groups = [{
        "name": g["category"].name,
        "slug": g["category"].slug,
        "icon": g["category"].icon,
        "items": [{
            "title": l.title, "description": l.description, "kind": l.kind,
            "kind_label": _KIND_LABEL.get(l.kind, ""), "href": l.resolve_href(),
            "open_in_new_tab": bool(l.open_in_new_tab or l.kind == HubLink.KIND_URL),
        } for l in g["items"]],
    } for g in groups]
    return render(request, "dashboard/pages/bacheca.html", {
        "page_title": "Documenti & Collegamenti",
        "bacheca_groups": view_groups,
    })


@login_required
def hub_link_download(request, pk: int):
    link = get_object_or_404(HubLink, pk=pk, kind=HubLink.KIND_FILE)
    _, is_admin, role_id = _identity(request)
    if not link_visible_to_role(link, role_id, is_admin) or not link.file:
        raise Http404()
    log_action(request, "download", "bacheca", {"link_id": link.pk, "title": link.title})
    filename = link.original_filename or link.file.name.rsplit("/", 1)[-1]
    return FileResponse(link.file.open("rb"), as_attachment=True, filename=filename)
```

- [ ] **Step 4: Crea il template pagina**

Create `django_app/dashboard/templates/dashboard/pages/bacheca.html` estendendo `core/base.html`, iterando `bacheca_groups` con ancore `id="{{ g.slug }}"`. Riusa le classi `hp-docs*`/`hp-doc*` del Task 5. Struttura minima:

```django
{% extends "core/base.html" %}
{% block title %}Documenti & Collegamenti · NOVICROM HUB{% endblock %}
{% block content %}
<div class="hp-wrap">
  <div class="page-header"><div class="page-header-main">
    <h1 class="page-h">Documenti &amp; Collegamenti</h1>
    <p class="page-sub">Risorse utili, gestite dall'amministrazione.</p>
  </div></div>
  {% for g in bacheca_groups %}
    <section class="hp-card hp-docs-card" id="{{ g.slug }}">
      <header class="hp-card-h"><h3 class="hp-card-t">{{ g.name }}</h3></header>
      <div class="hp-docs">
        {% for it in g.items %}
          <a class="hp-doc k-{{ it.kind }}" href="{{ it.href }}"
             {% if it.open_in_new_tab %}target="_blank" rel="noopener"{% endif %}>
            <span class="hp-doc-ic" aria-hidden="true"></span>
            <span class="hp-doc-bd"><span class="hp-doc-t">{{ it.title }}</span>
              <span class="hp-doc-d">{{ it.description }}</span></span>
            <span class="hp-doc-kind">{{ it.kind_label }}</span>
          </a>
        {% endfor %}
      </div>
    </section>
  {% empty %}
    <p class="hp-empty">Nessun documento o collegamento disponibile.</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Registra le rotte**

In `django_app/dashboard/urls.py`: aggiungi l'import `from . import views_bacheca` e le due path (dentro `urlpatterns`):

```python
    path("bacheca/", views_bacheca.bacheca, name="bacheca"),
    path("bacheca/doc/<int:pk>/", views_bacheca.hub_link_download, name="hub_link_download"),
```

- [ ] **Step 6: Esponi le rotte pubbliche all'ACL**

In `django_app/core/middleware.py`, aggiungi `"bacheca"` e `"hub_link_download"` alla tupla `_ACL_SHARED_ROUTE_NAMES` (accanto a `"root"`, `"profilo"`, …), così sono accessibili a tutti gli autenticati (il download fa il proprio check di ruolo per-voce).

- [ ] **Step 7: Verifica che i test passino**

Run: `python django_app\manage.py test django_app.dashboard.tests_bacheca --settings=config.settings.test`
Expected: PASS (helper + 3 download test)

- [ ] **Step 8: Verifica manuale ACL non-admin**

Con un utente NON-admin (non superuser) in dev: `/bacheca/` risponde 200 e un download consentito funziona; un download riservato dà 404. (I test con superuser non coprono il gate ACL.)

- [ ] **Step 9: Commit**

```bash
git add django_app/dashboard/views_bacheca.py django_app/dashboard/templates/dashboard/pages/bacheca.html django_app/dashboard/urls.py django_app/core/middleware.py django_app/dashboard/tests_bacheca.py
git commit -m "feat(bacheca): pagina /bacheca/ + download protetto + rotte pubbliche ACL"
```

---

### Task 7: Gestione admin (CRUD)

**Files:**
- Create: `django_app/admin_portale/views_bacheca.py`
- Modify: `django_app/admin_portale/urls.py`
- Create: `django_app/admin_portale/templates/admin_portale/bacheca.html`
- Create: `django_app/core/migrations/00YY_navitem_bacheca.py` (voce subnav)
- Test: `django_app/admin_portale/tests_bacheca.py`

**Interfaces:**
- Consumes: modelli Task 2, `Ruolo` (`core.legacy_models`), `@legacy_admin_required`.
- Produces: pagina `admin_portale:bacheca` + API JSON category/link/role/reorder/toggle.

- [ ] **Step 1: Scrivi i test che falliscono**

Create `django_app/admin_portale/tests_bacheca.py`:

```python
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import HubLink, HubLinkCategory, HubLinkRoleAccess


class AdminBachecaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="admin", password="x", email="a@a.it")
        self.user = User.objects.create_user(username="mario", password="x")

    def test_page_forbidden_for_non_admin(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("admin_portale:bacheca"))
        self.assertEqual(r.status_code, 403)

    def test_admin_creates_category(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("admin_portale:api_hub_category_create"),
                             data=json.dumps({"name": "Modulistica"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(HubLinkCategory.objects.filter(name="Modulistica").exists())

    def test_admin_creates_url_link_with_roles(self):
        cat = HubLinkCategory.objects.create(name="Coll", slug="coll")
        self.client.force_login(self.admin)
        r = self.client.post(reverse("admin_portale:api_hub_link_create"),
                             data=json.dumps({
                                 "category_id": cat.id, "kind": "url", "title": "Gestionale",
                                 "url": "https://esempio.local", "role_ids": [5, 7],
                             }), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        link = HubLink.objects.get(title="Gestionale")
        self.assertEqual(set(HubLinkRoleAccess.objects.filter(link=link)
                             .values_list("legacy_role_id", flat=True)), {5, 7})
```

- [ ] **Step 2: Verifica fallimento**

Run: `python django_app\manage.py test django_app.admin_portale.tests_bacheca --settings=config.settings.test`
Expected: FAIL — `NoReverseMatch: 'admin_portale:bacheca'`

- [ ] **Step 3: Implementa le view admin**

Create `django_app/admin_portale/views_bacheca.py`:

```python
from __future__ import annotations

import json

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action
from core.legacy_models import Ruolo
from core.models import HubLink, HubLinkCategory, HubLinkRoleAccess
from .decorators import legacy_admin_required

ALLOWED_UPLOAD_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _json_body(request) -> dict:
    try:
        return json.loads(request.body or "{}")
    except (ValueError, AttributeError):
        return {}


def _unique_slug(name: str) -> str:
    base = slugify(name) or "categoria"
    slug, i = base, 2
    while HubLinkCategory.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"; i += 1
    return slug


@legacy_admin_required
@require_GET
def bacheca(request):
    categories = (HubLinkCategory.objects.prefetch_related("links__role_accesses")
                  .order_by("order", "name", "id"))
    ruoli = list(Ruolo.objects.all().order_by("nome"))
    return render(request, "admin_portale/bacheca.html", {
        "categories": categories, "ruoli": ruoli, "kinds": HubLink.KIND_CHOICES,
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_category_create(request):
    data = _json_body(request)
    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "Nome obbligatorio."}, status=400)
    cat = HubLinkCategory.objects.create(
        name=name, slug=_unique_slug(name), icon=(data.get("icon") or "").strip(),
        description=(data.get("description") or "").strip(),
        order=int(data.get("order") or 100), created_by=request.user, updated_by=request.user,
    )
    log_action(request, "create", "bacheca", {"category_id": cat.id, "name": name})
    return JsonResponse({"ok": True, "id": cat.id, "slug": cat.slug})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_category_update(request):
    data = _json_body(request)
    try:
        cat = HubLinkCategory.objects.get(pk=int(data.get("id")))
    except (HubLinkCategory.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Categoria non trovata."}, status=404)
    for f in ("name", "icon", "description"):
        if f in data:
            setattr(cat, f, (data.get(f) or "").strip())
    if "is_visible" in data:
        cat.is_visible = bool(data.get("is_visible"))
    if "order" in data:
        cat.order = int(data.get("order") or 100)
    cat.updated_by = request.user
    cat.save()
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_category_delete(request):
    data = _json_body(request)
    HubLinkCategory.objects.filter(pk=data.get("id")).delete()
    return JsonResponse({"ok": True})


def _set_roles(link, role_ids):
    HubLinkRoleAccess.objects.filter(link=link).delete()
    for rid in {int(r) for r in (role_ids or []) if str(r).strip().isdigit()}:
        HubLinkRoleAccess.objects.create(link=link, legacy_role_id=rid, can_view=True)


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_link_create(request):
    # Supporta sia JSON (url/internal) sia multipart (file upload).
    if request.content_type and request.content_type.startswith("multipart/"):
        data = request.POST
        role_ids = request.POST.getlist("role_ids")
        upload = request.FILES.get("file")
    else:
        data = _json_body(request)
        role_ids = data.get("role_ids") or []
        upload = None
    try:
        cat = HubLinkCategory.objects.get(pk=int(data.get("category_id")))
    except (HubLinkCategory.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Categoria non valida."}, status=400)
    kind = (data.get("kind") or "").strip()
    title = (data.get("title") or "").strip()
    if not title:
        return JsonResponse({"ok": False, "error": "Titolo obbligatorio."}, status=400)

    link = HubLink(category=cat, kind=kind, title=title,
                   description=(data.get("description") or "").strip(),
                   icon=(data.get("icon") or "").strip(),
                   open_in_new_tab=bool(data.get("open_in_new_tab")) or kind == HubLink.KIND_URL,
                   order=int(data.get("order") or 100),
                   created_by=request.user, updated_by=request.user)
    if kind == HubLink.KIND_URL:
        link.url = (data.get("url") or "").strip()
    elif kind == HubLink.KIND_INTERNAL:
        link.route_name = (data.get("route_name") or "").strip()
    elif kind == HubLink.KIND_FILE:
        if not upload:
            return JsonResponse({"ok": False, "error": "File obbligatorio."}, status=400)
        import os
        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXT:
            return JsonResponse({"ok": False, "error": f"Estensione {ext} non ammessa."}, status=400)
        if upload.size > MAX_UPLOAD_BYTES:
            return JsonResponse({"ok": False, "error": "File troppo grande (max 25 MB)."}, status=400)
        link.file = upload
        link.original_filename = upload.name
        link.file_size = upload.size
        link.content_type = upload.content_type or ""
    else:
        return JsonResponse({"ok": False, "error": "Tipo non valido."}, status=400)

    try:
        link.full_clean(exclude=["file"] if kind != HubLink.KIND_FILE else None)
    except Exception as exc:  # ValidationError
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    with transaction.atomic():
        link.save()
        _set_roles(link, role_ids)
    log_action(request, "create", "bacheca", {"link_id": link.id, "kind": kind, "title": title})
    return JsonResponse({"ok": True, "id": link.id})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_link_delete(request):
    data = _json_body(request)
    HubLink.objects.filter(pk=data.get("id")).delete()
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_link_toggle(request):
    data = _json_body(request)
    try:
        link = HubLink.objects.get(pk=int(data.get("id")))
    except (HubLink.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Voce non trovata."}, status=404)
    link.is_visible = bool(data.get("is_visible"))
    link.updated_by = request.user
    link.save(update_fields=["is_visible", "updated_by", "updated_at"])
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_reorder(request):
    """Payload: {"links": [id,...]} oppure {"categories": [id,...]} → riscrive order."""
    data = _json_body(request)
    for model, key in ((HubLink, "links"), (HubLinkCategory, "categories")):
        ids = data.get(key)
        if isinstance(ids, list):
            for i, pk in enumerate(ids):
                model.objects.filter(pk=pk).update(order=i * 10)
    return JsonResponse({"ok": True})
```

> Nota: `full_clean(exclude=[...])` è usato per validare `clean()`; per il file l'obbligatorietà è già verificata sopra. Se `full_clean` dà noia con `route_kwargs`, validare a mano richiamando `link.clean()`.

- [ ] **Step 4: Registra le rotte admin**

In `django_app/admin_portale/urls.py`: `from . import views_bacheca` e dentro `urlpatterns`:

```python
    path("bacheca/", views_bacheca.bacheca, name="bacheca"),
    path("api/bacheca/category/create", views_bacheca.api_hub_category_create, name="api_hub_category_create"),
    path("api/bacheca/category/update", views_bacheca.api_hub_category_update, name="api_hub_category_update"),
    path("api/bacheca/category/delete", views_bacheca.api_hub_category_delete, name="api_hub_category_delete"),
    path("api/bacheca/link/create", views_bacheca.api_hub_link_create, name="api_hub_link_create"),
    path("api/bacheca/link/delete", views_bacheca.api_hub_link_delete, name="api_hub_link_delete"),
    path("api/bacheca/link/toggle", views_bacheca.api_hub_link_toggle, name="api_hub_link_toggle"),
    path("api/bacheca/reorder", views_bacheca.api_hub_reorder, name="api_hub_reorder"),
```

- [ ] **Step 5: Crea il template di gestione**

Create `django_app/admin_portale/templates/admin_portale/bacheca.html` estendendo il base admin usato dalle altre pagine admin_portale (guarda `admin_portale/templates/admin_portale/pulsanti.html` o simile per la chrome/subnav). Deve elencare le categorie con le voci, un form modale "Aggiungi voce" (select kind → mostra campo url / route_name / file), un multi-select dei `ruoli` (id→nome) per la visibilità, toggle `is_visible`, e chiamate `fetch()` POST JSON/multipart agli endpoint dello Step 4 con header `X-CSRFToken`. Usa SOLO classi di `theme.css` (`.card`, `.btn-primary`, `.btn-secondary`, `.stat`, `.badge`). Nessun nuovo colore.

- [ ] **Step 6: Aggiungi la voce subnav admin (NavigationItem)**

Create `django_app/core/migrations/00YY_navitem_bacheca.py` (numero coerente col grafo) con una data-migration idempotente:

```python
from django.db import migrations


def add_navitem(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code="admin_bacheca",
        defaults=dict(
            label="Documenti & Collegamenti", section="admin_subnav", parent_code="",
            route_name="admin_portale:bacheca", order=180, icon="folder",
            group="hub", is_visible=True, is_enabled=True,
        ),
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("core", "00XX_hub_bacheca")]  # <-- sostituisci con la migrazione del Task 2
    operations = [migrations.RunPython(add_navitem, noop)]
```

> Regola: la subnav admin NON va hardcodata nel template — sempre via `NavigationItem` (section admin_subnav).

- [ ] **Step 7: Verifica che i test passino**

Run: `python django_app\manage.py test django_app.admin_portale.tests_bacheca --settings=config.settings.test`
Expected: PASS (3 test)

- [ ] **Step 8: Verifica manuale**

Run runserver, vai in `/admin-portale/bacheca/` da admin: crea categoria, aggiungi voce URL, voce interna (es. route `assenze_richiesta`), carica un file, imposta visibilità per ruolo, verifica che appaia in home/`/bacheca/` per un utente del ruolo giusto e sparisca per gli altri.

- [ ] **Step 9: Commit**

```bash
git add django_app/admin_portale/views_bacheca.py django_app/admin_portale/urls.py django_app/admin_portale/templates/admin_portale/bacheca.html django_app/core/migrations/00YY_navitem_bacheca.py django_app/admin_portale/tests_bacheca.py
git commit -m "feat(bacheca): gestione admin Documenti & Collegamenti (CRUD + visibilità ruolo + subnav)"
```

---

### Task 8: Documentazione + bump versione

**Files:**
- Modify: `CHANGELOG.md`, `README.md`
- Modify: `django_app/config/settings/base.py` (o dove vive `APP_VERSION`), `CLAUDE.md` (riga versione)

- [ ] **Step 1: CHANGELOG**

In `CHANGELOG.md` sotto `[Unreleased]` elenca TUTTI i file aggiunti/modificati con descrizione (nuova home Bacheca, sezione Documenti & Collegamenti, gestione admin, storage privato, rotte, migrazioni).

- [ ] **Step 2: README**

In `README.md` aggiorna la tabella moduli / sezione dashboard: nuova home "Bacheca", sezione Documenti & Collegamenti, pagina `/bacheca/`, gestione in `/admin-portale/bacheca/`, setting `HUB_BACHECA_PRIVATE_ROOT`.

- [ ] **Step 3: Bump versione**

Segui la checklist in `docs/ai/06_TESTING_AND_QUALITY_GATES.md`: `APP_VERSION` `1.2.1` → `1.3.0`; aggiorna la riga "Versione app corrente" in `CLAUDE.md`.

- [ ] **Step 4: Suite scoped finale**

Run: `python django_app\manage.py test django_app.core django_app.dashboard django_app.admin_portale --settings=config.settings.test --keepdb`
Expected: PASS.
Poi: `python django_app\manage.py check --settings=config.settings.test` → nessun errore.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md CLAUDE.md django_app/config/settings/base.py
git commit -m "docs(bacheca): CHANGELOG/README + bump versione 1.3.0"
```

---

## Self-Review

**Spec coverage:**
- §4 layout → Task 5. §5 modelli → Task 2. Storage → Task 1. §6 rendering → Task 4/5/6. Pagina + download → Task 6. §7 rotte + ACL gate → Task 6 (shared routes) + Task 7 (admin bypass). §8 migrazione → Task 2/7. §9 test → ogni task. §10 docs/versione → Task 8. Visibilità ruolo → Task 3. Tutte le sezioni dello spec hanno un task.
- Nota deliberata: role-access a livello **categoria** e ricerca su `/bacheca/` sono YAGNI (spec §12), non pianificati.

**Type consistency:** `HubLink.KIND_FILE/KIND_URL/KIND_INTERNAL`, `resolve_href()`, `link_visible_to_role(link, legacy_role_id, is_admin)`, `visible_bacheca(legacy_role_id, is_admin, preview_limit)`, `_documenti_collegamenti(request, preview)`, `_KIND_LABEL` usati in modo coerente tra Task 2→3→4→6.

**Placeholder scan:** i punti UI (template Task 5/7) rimandano a template esistenti per la sola *chrome*, ma logica, endpoint, payload e classi sono espliciti. Numeri di migrazione `00XX/00YY` da rimpiazzare col numero reale generato da `makemigrations` (indicato nei rispettivi step).
