# Suggestion Corner — Sessione 3: ACL v2 + viste protette (sola lettura + navigazione)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere il modulo `suggestion_corner` **navigabile e sicuro**: `urls.py` + viste di sola lettura (home/elenco con queryset filtrati per ruolo, dettaglio con storico), doppio livello di autorizzazione (ACL v2 canonico per l'accesso al modulo + Django Group `SMS_TEAM` per lo scope dei dati), voce di menu. Le azioni che pilotano la FSM (classifica, plan, completa, check, chiudi) sono **fuori scope** — sessione 3b.

**Architecture:** Due livelli di autorizzazione. (1) **ACL v2 canonico** (come `gestione_specifiche`): un permesso `suggestion_corner.segnalazione.view` con binding route→permesso, così `ACLMiddleware`/`ACL_STRICT_CANONICAL` (attivo in prod) lascia passare gli utenti autorizzati; `PERM_VIEW` è concesso a TUTTI i ruoli (il modulo è apribile da ogni utente autenticato, i dati sono poi ristretti per-utente). (2) **Django auth Group `SMS_TEAM`** (nome da `SuggestionCornerConfig.sms_team_group_name`): decide lo **scope dei dati** dentro le viste — chi è nel gruppo (o è superuser) vede tutte le segnalazioni e le code "da gestire"; gli altri vedono solo le proprie (`created_by`) + gli incarichi assegnati (`incaricato`/`controllore`). Le viste sono `@login_required`; il filtro object-level nel dettaglio dà 404 a chi non ha visibilità. Nessuna scrittura, nessun endpoint API JSON (le viste HTML sono gated dal route binding, non serve `API_ACL_GATE_PATHS`).

**Tech Stack:** Django 5.2, viste SSR che estendono `core/base.html`, ACL v2 (`core/acl_bootstrap_base.run_bootstrap` + `PermissionDefinition`/`RoutePermissionBinding`/`NavigationItem`/`RolePermissionGrant`), Django `Group`. Test runner Django.

## Global Constraints

- Solo **lettura** in questa sessione. Nessun form, nessuna transizione FSM guidata da view, nessun POST (a parte quello che Django/ACL già gestisce). Le azioni sono sessione 3b.
- Il route name del modulo è **`suggestion_corner:home`** (già dichiarato in `core/module_registry.py` in sessione 1). `urls.py` deve esporre `name="home"` all'URL radice.
- Registrazione in `config/urls.py`: `path("suggestion-corner/", include(("suggestion_corner.urls", "suggestion_corner"), namespace="suggestion_corner"))`.
- **SMS_TEAM = Django auth `Group`** cercato per nome via `SuggestionCornerConfig.load().sms_team_group_name` (default `"SMS_TEAM"`). NON un ruolo legacy. Superuser sempre incluso nello scope "vede tutto".
- **ACL v2**: `PERM_VIEW = "suggestion_corner.segnalazione.view"`, binding per `suggestion_corner:home` e `suggestion_corner:dettaglio`, concesso a TUTTI i ruoli legacy (`_ROLE_GRANTS` = tutti i ruoli → {PERM_VIEW}). Copia il pattern di `gestione_specifiche/acl_bootstrap.py`.
- Viste `@login_required`. Il dettaglio filtra a livello di oggetto: `get_object_or_404(visible_segnalazioni(request.user), pk=pk)`.
- Template estendono `core/base.html`.
- **Nessuna migration** (nessun campo nuovo): verifica `makemigrations suggestion_corner --check --dry-run` → "No changes detected".
- Test scoped, dalla root, col venv: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner --keepdb --settings=config.settings.test`.
- **Commit sicuro (indice condiviso):** `git add <file>` poi `git commit -m "<msg>" -- <file...>` (opzioni PRIMA del `--`). Dopo il commit `git show --stat --oneline HEAD` deve mostrare SOLO i tuoi file; se compare altro, STOP e segnala. MAI `git add .`/`-A`.
- CHANGELOG.md gestito dal controller (WIP concorrente nel file).
- Pattern di riferimento: `gestione_specifiche/{urls,views,acl_bootstrap,apps}.py` e `templates/gestione_specifiche/{lista,dettaglio}.html`.

---

### Task 1: `urls.py` + home view minimale + registrazione in config/urls

**Files:**
- Create: `django_app/suggestion_corner/urls.py`
- Create: `django_app/suggestion_corner/views.py`
- Modify: `django_app/config/urls.py`
- Create: `django_app/suggestion_corner/tests/test_views.py`

**Interfaces:**
- Produces: namespace `suggestion_corner`, route `suggestion_corner:home` (URL radice) e `suggestion_corner:dettaglio` (`<int:pk>/`); view `home` (elenco base, raffinata nel Task 3), view `dettaglio` (stub nel Task 1, raffinata nel Task 4).

- [ ] **Step 1: Scrivere il test che fallisce**

`django_app/suggestion_corner/tests/test_views.py`:
```python
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class SuggestionCornerUrlsTest(TestCase):
    def test_home_url_risolve(self):
        self.assertEqual(reverse("suggestion_corner:home"), "/suggestion-corner/")

    def test_home_richiede_login(self):
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertEqual(resp.status_code, 302)  # redirect al login
        self.assertIn("/login", resp.url.lower())

    def test_home_autenticato_200(self):
        User.objects.create_user(username="u1", password="x")
        self.client.login(username="u1", password="x")
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertEqual(resp.status_code, 200)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_views --settings=config.settings.test`
Expected: FAIL — `NoReverseMatch` (namespace/route inesistenti).

- [ ] **Step 3: Creare views.py**

`django_app/suggestion_corner/views.py`:
```python
"""Viste (sola lettura) del modulo Suggestion Corner.

Gating: `@login_required` + ACLMiddleware (binding canonico per rotta, vedi
acl_bootstrap.py). Lo scope dei dati è deciso da `permissions.visible_segnalazioni`.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Elenco segnalazioni (raffinato nel Task 3 con queryset filtrati)."""
    from .models import SuggestionCorner

    segnalazioni = SuggestionCorner.objects.all().order_by("-data_segnalazione", "-id")
    return render(request, "suggestion_corner/home.html", {"segnalazioni": segnalazioni})


@login_required
def dettaglio(request, pk: int):
    """Dettaglio segnalazione (raffinato nel Task 4 con scope + storico)."""
    from django.shortcuts import get_object_or_404

    from .models import SuggestionCorner

    seg = get_object_or_404(SuggestionCorner, pk=pk)
    return render(request, "suggestion_corner/dettaglio.html", {"seg": seg})
```

- [ ] **Step 4: Creare urls.py**

`django_app/suggestion_corner/urls.py`:
```python
from django.urls import path

from . import views

app_name = "suggestion_corner"

urlpatterns = [
    path("", views.home, name="home"),
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
]
```

- [ ] **Step 5: Creare i template minimi**

`django_app/suggestion_corner/templates/suggestion_corner/home.html`:
```django
{% extends "core/base.html" %}
{% block content %}
<div class="content">
  <h1>Suggestion Corner</h1>
  <p>{{ segnalazioni|length }} segnalazioni.</p>
</div>
{% endblock %}
```

`django_app/suggestion_corner/templates/suggestion_corner/dettaglio.html`:
```django
{% extends "core/base.html" %}
{% block content %}
<div class="content">
  <h1>Segnalazione SC#{{ seg.pk }}</h1>
  <p>{{ seg.opportunity }}</p>
</div>
{% endblock %}
```

- [ ] **Step 6: Registrare in config/urls.py**

In `django_app/config/urls.py`, nella lista `urlpatterns`, dopo la riga di `gestione-specifiche` (riga ~45), aggiungere:
```python
    path("suggestion-corner/", include(("suggestion_corner.urls", "suggestion_corner"), namespace="suggestion_corner")),
```
(`include` è già importato in cima al file.)

- [ ] **Step 7: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_views --settings=config.settings.test`
Expected: PASS (3 test). NB: in `config.settings.test` `ACL_STRICT_CANONICAL` è normalmente disattivo, quindi l'utente autenticato senza grant ACL riceve comunque 200 (il gating stretto è verificato in prod dal binding del Task 5).

- [ ] **Step 8: Commit (metodo sicuro)**

```bash
git add django_app/suggestion_corner/urls.py django_app/suggestion_corner/views.py django_app/suggestion_corner/templates/suggestion_corner/home.html django_app/suggestion_corner/templates/suggestion_corner/dettaglio.html django_app/suggestion_corner/tests/test_views.py django_app/config/urls.py
git commit -m "feat(suggestion_corner): urls + viste lettura minime + registrazione config/urls" -- django_app/suggestion_corner/urls.py django_app/suggestion_corner/views.py django_app/suggestion_corner/templates/suggestion_corner/home.html django_app/suggestion_corner/templates/suggestion_corner/dettaglio.html django_app/suggestion_corner/tests/test_views.py django_app/config/urls.py
```
Verifica scope: `git show --stat --oneline HEAD` → solo 6 file.

---

### Task 2: Helper permessi — `is_sms_team` + `visible_segnalazioni`

**Files:**
- Create: `django_app/suggestion_corner/permissions.py`
- Create: `django_app/suggestion_corner/tests/test_permissions.py`

**Interfaces:**
- Produces: `is_sms_team(user) -> bool` (True se superuser o membro del Group `SuggestionCornerConfig.sms_team_group_name`); `visible_segnalazioni(user) -> QuerySet[SuggestionCorner]` (tutte se `is_sms_team`, altrimenti `created_by=user` OR `incaricato=user` OR `controllore=user`).

- [ ] **Step 1: Scrivere il test che fallisce**

`django_app/suggestion_corner/tests/test_permissions.py`:
```python
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig
from suggestion_corner.permissions import is_sms_team, visible_segnalazioni

User = get_user_model()


class PermissionsTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.membro = User.objects.create_user(username="team", password="x")
        self.estraneo = User.objects.create_user(username="ext", password="x")
        self.incaricato = User.objects.create_user(username="inc", password="x")
        cfg = SuggestionCornerConfig.load()
        self.group = Group.objects.create(name=cfg.sms_team_group_name)
        self.membro.groups.add(self.group)
        # una segnalazione dell'estraneo, una con incaricato
        self.sc_ext = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Ext.", created_by=self.estraneo,
        )
        self.sc_inc = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Inc.", incaricato=self.incaricato,
        )

    def test_is_sms_team_membro(self):
        self.assertTrue(is_sms_team(self.membro))

    def test_is_sms_team_superuser(self):
        su = User.objects.create_superuser(username="su", password="x")
        self.assertTrue(is_sms_team(su))

    def test_is_sms_team_estraneo_false(self):
        self.assertFalse(is_sms_team(self.estraneo))

    def test_team_vede_tutto(self):
        self.assertEqual(visible_segnalazioni(self.membro).count(), 2)

    def test_estraneo_vede_solo_le_proprie(self):
        vis = visible_segnalazioni(self.estraneo)
        self.assertEqual(list(vis), [self.sc_ext])

    def test_incaricato_vede_il_proprio_incarico(self):
        vis = visible_segnalazioni(self.incaricato)
        self.assertIn(self.sc_inc, vis)
        self.assertNotIn(self.sc_ext, vis)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_permissions --settings=config.settings.test`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` su `permissions`.

- [ ] **Step 3: Implementare permissions.py**

`django_app/suggestion_corner/permissions.py`:
```python
"""Autorizzazione dati del modulo Suggestion Corner.

L'accesso al modulo è gated da ACL v2 (PERM_VIEW, vedi acl_bootstrap.py).
Qui si decide lo *scope dei dati*: il team SMS (Django Group) vede tutto, gli
altri vedono solo le proprie segnalazioni e gli incarichi assegnati.
"""
from __future__ import annotations

from django.db.models import Q

from .models import SuggestionCorner, SuggestionCornerConfig


def is_sms_team(user) -> bool:
    """True se l'utente è superuser o membro del Group SMS_TEAM configurato."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    group_name = SuggestionCornerConfig.load().sms_team_group_name
    return user.groups.filter(name=group_name).exists()


def visible_segnalazioni(user):
    """QuerySet delle segnalazioni visibili all'utente.

    - team SMS / superuser: tutte;
    - altri: create da loro (created_by) o a loro assegnate (incaricato/controllore).
    """
    qs = SuggestionCorner.objects.all()
    if is_sms_team(user):
        return qs
    return qs.filter(
        Q(created_by=user) | Q(incaricato=user) | Q(controllore=user)
    ).distinct()
```

- [ ] **Step 4: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_permissions --settings=config.settings.test`
Expected: PASS (6 test).

- [ ] **Step 5: Commit (metodo sicuro)**

```bash
git add django_app/suggestion_corner/permissions.py django_app/suggestion_corner/tests/test_permissions.py
git commit -m "feat(suggestion_corner): helper scope dati (is_sms_team + visible_segnalazioni)" -- django_app/suggestion_corner/permissions.py django_app/suggestion_corner/tests/test_permissions.py
```
Verifica scope con `git show --stat`.

---

### Task 3: Home/elenco con queryset filtrati per ruolo

**Files:**
- Modify: `django_app/suggestion_corner/models.py` (property `stato_label`)
- Modify: `django_app/suggestion_corner/views.py`
- Modify: `django_app/suggestion_corner/templates/suggestion_corner/home.html`
- Modify: `django_app/suggestion_corner/tests/test_views.py`

**Interfaces:**
- Consumes: `permissions.visible_segnalazioni`, `permissions.is_sms_team`.
- Produces: `SuggestionCorner.stato_label` (property, etichetta leggibile dello stato via `Stato`); `home` che passa al template `segnalazioni` (scope-filtrate), `is_team` (bool), e `da_gestire` (per il team: quelle in stato `DA_CLASSIFICARE`; per gli altri: vuoto).

Nota: aggiungere anche una property `stato_label` al modello (Task 3 tocca quindi anche `models.py`), perché `stato` è un FSMField **senza** `choices` → `get_stato_display` NON esiste. In `models.py`, dopo la property `scaduto_check`, aggiungere:
```python
    @property
    def stato_label(self) -> str:
        """Etichetta leggibile dello stato (FSMField senza choices)."""
        try:
            return self.Stato(self.stato).label
        except ValueError:
            return self.stato
```
Questo NON genera migration (è una property). Verificare con `makemigrations --check`.

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `django_app/suggestion_corner/tests/test_views.py`:
```python
from django.contrib.auth.models import Group

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig


class HomeScopeTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="CNC")
        self.team = User.objects.create_user(username="team", password="x")
        self.estraneo = User.objects.create_user(username="ext", password="x")
        g = Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name)
        self.team.groups.add(g)
        SuggestionCorner.objects.create(reparto_provenienza=self.reparto, opportunity="A.", created_by=self.estraneo)
        SuggestionCorner.objects.create(reparto_provenienza=self.reparto, opportunity="B.", created_by=self.team)

    def test_team_vede_tutte_in_home(self):
        self.client.login(username="team", password="x")
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_team"])
        self.assertEqual(len(resp.context["segnalazioni"]), 2)

    def test_estraneo_vede_solo_le_proprie_in_home(self):
        self.client.login(username="ext", password="x")
        resp = self.client.get(reverse("suggestion_corner:home"))
        self.assertFalse(resp.context["is_team"])
        self.assertEqual(len(resp.context["segnalazioni"]), 1)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_views.HomeScopeTest --settings=config.settings.test`
Expected: FAIL — `KeyError` su `resp.context["is_team"]` / conteggi errati (la home stub mostra tutte).

- [ ] **Step 3a: Aggiungere la property `stato_label` al modello**

In `django_app/suggestion_corner/models.py`, dopo la property `scaduto_check` di `SuggestionCorner`, aggiungere:
```python
    @property
    def stato_label(self) -> str:
        """Etichetta leggibile dello stato (FSMField senza choices)."""
        try:
            return self.Stato(self.stato).label
        except ValueError:
            return self.stato
```
(È una property → nessuna migration.)

- [ ] **Step 3: Raffinare la view home**

In `django_app/suggestion_corner/views.py`, sostituire la funzione `home`:
```python
@login_required
def home(request):
    """Elenco segnalazioni con scope per-utente.

    - team SMS / superuser: tutte + coda 'da gestire' (DA_CLASSIFICARE);
    - altri: solo le proprie + incarichi assegnati.
    """
    from .models import SuggestionCorner
    from .permissions import is_sms_team, visible_segnalazioni

    team = is_sms_team(request.user)
    segnalazioni = visible_segnalazioni(request.user).select_related(
        "reparto_provenienza", "incaricato", "controllore",
    )
    da_gestire = (
        segnalazioni.filter(stato=SuggestionCorner.Stato.DA_CLASSIFICARE)
        if team else SuggestionCorner.objects.none()
    )
    return render(request, "suggestion_corner/home.html", {
        "segnalazioni": segnalazioni,
        "da_gestire": da_gestire,
        "is_team": team,
    })
```

- [ ] **Step 4: Raffinare il template home**

Sostituire `django_app/suggestion_corner/templates/suggestion_corner/home.html`:
```django
{% extends "core/base.html" %}
{% block content %}
<div class="content">
  <h1>Suggestion Corner</h1>

  {% if is_team and da_gestire %}
  <h2>Da gestire ({{ da_gestire|length }})</h2>
  <ul>
    {% for s in da_gestire %}
      <li><a href="{% url 'suggestion_corner:dettaglio' s.pk %}">SC#{{ s.pk }} — {{ s.opportunity|truncatechars:60 }}</a></li>
    {% endfor %}
  </ul>
  {% endif %}

  <h2>{% if is_team %}Tutte le segnalazioni{% else %}Le mie segnalazioni{% endif %} ({{ segnalazioni|length }})</h2>
  {% if segnalazioni %}
  <table class="hub-table">
    <thead>
      <tr><th>#</th><th>Data</th><th>Reparto</th><th>Stato</th><th>Opportunità</th></tr>
    </thead>
    <tbody>
      {% for s in segnalazioni %}
      <tr>
        <td><a href="{% url 'suggestion_corner:dettaglio' s.pk %}">SC#{{ s.pk }}</a></td>
        <td>{{ s.data_segnalazione|date:"d/m/Y" }}</td>
        <td>{{ s.reparto_provenienza.nome }}</td>
        <td>{{ s.stato_label }}</td>
        <td>{{ s.opportunity|truncatechars:80 }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p>Nessuna segnalazione da mostrare.</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_views --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 6: Commit (metodo sicuro)**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/views.py django_app/suggestion_corner/templates/suggestion_corner/home.html django_app/suggestion_corner/tests/test_views.py
git commit -m "feat(suggestion_corner): home con scope per-utente (team vede tutto + coda da gestire) + property stato_label" -- django_app/suggestion_corner/models.py django_app/suggestion_corner/views.py django_app/suggestion_corner/templates/suggestion_corner/home.html django_app/suggestion_corner/tests/test_views.py
```
Verifica scope.

---

### Task 4: Dettaglio con scope object-level + storico

**Files:**
- Modify: `django_app/suggestion_corner/views.py`
- Modify: `django_app/suggestion_corner/templates/suggestion_corner/dettaglio.html`
- Modify: `django_app/suggestion_corner/tests/test_views.py`

**Interfaces:**
- Consumes: `permissions.visible_segnalazioni`.
- Produces: `dettaglio` che dà 404 a chi non ha visibilità sull'oggetto e passa `seg` + `storico`.

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `django_app/suggestion_corner/tests/test_views.py`:
```python
class DettaglioScopeTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="PRESS")
        self.owner = User.objects.create_user(username="own", password="x")
        self.estraneo = User.objects.create_user(username="ext2", password="x")
        self.seg = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Riservata.", created_by=self.owner,
        )

    def test_owner_vede_dettaglio(self):
        self.client.login(username="own", password="x")
        resp = self.client.get(reverse("suggestion_corner:dettaglio", args=[self.seg.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["seg"], self.seg)

    def test_estraneo_riceve_404(self):
        self.client.login(username="ext2", password="x")
        resp = self.client.get(reverse("suggestion_corner:dettaglio", args=[self.seg.pk]))
        self.assertEqual(resp.status_code, 404)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_views.DettaglioScopeTest --settings=config.settings.test`
Expected: FAIL — l'estraneo riceve 200 (la stub del Task 1 non filtra).

- [ ] **Step 3: Raffinare la view dettaglio**

In `views.py`, sostituire la funzione `dettaglio`:
```python
@login_required
def dettaglio(request, pk: int):
    """Dettaglio in sola lettura; 404 se l'utente non ha visibilità sull'oggetto."""
    from django.shortcuts import get_object_or_404

    from .permissions import visible_segnalazioni

    seg = get_object_or_404(
        visible_segnalazioni(request.user).select_related(
            "reparto_provenienza", "reparto_destinazione", "incaricato", "controllore",
        ),
        pk=pk,
    )
    storico = seg.storico.select_related("autore").all()
    return render(request, "suggestion_corner/dettaglio.html", {"seg": seg, "storico": storico})
```

- [ ] **Step 4: Raffinare il template dettaglio**

Sostituire `django_app/suggestion_corner/templates/suggestion_corner/dettaglio.html`:
```django
{% extends "core/base.html" %}
{% block content %}
<div class="content">
  <p><a href="{% url 'suggestion_corner:home' %}">&larr; Suggestion Corner</a></p>
  <h1>Segnalazione SC#{{ seg.pk }}</h1>

  <dl class="hub-dl">
    <dt>Stato</dt><dd>{{ seg.stato_label }}</dd>
    <dt>Data</dt><dd>{{ seg.data_segnalazione|date:"d/m/Y" }}</dd>
    <dt>Reparto provenienza</dt><dd>{{ seg.reparto_provenienza.nome }}</dd>
    <dt>Processo</dt><dd>{{ seg.processo|default:seg.processo_libero|default:"—" }}</dd>
    <dt>Incaricato</dt><dd>{{ seg.incaricato|default:"—" }}</dd>
    <dt>Controllore</dt><dd>{{ seg.controllore|default:"—" }}</dd>
  </dl>

  <h2>Opportunità</h2>
  <p>{{ seg.opportunity|linebreaksbr }}</p>

  {% if seg.plan_testo %}<h2>Plan</h2><p>{{ seg.plan_testo|linebreaksbr }}</p>{% endif %}
  {% if seg.do_testo %}<h2>Do</h2><p>{{ seg.do_testo|linebreaksbr }}</p>{% endif %}
  {% if seg.check_testo %}<h2>Check</h2><p>{{ seg.check_testo|linebreaksbr }}</p>{% endif %}
  {% if seg.act_testo %}<h2>Act</h2><p>{{ seg.act_testo|linebreaksbr }}</p>{% endif %}

  <h2>Storico</h2>
  {% if storico %}
  <ul>
    {% for v in storico %}
      <li>{{ v.timestamp|date:"d/m/Y H:i" }} — {{ v.stato_precedente }} &rarr; {{ v.stato_nuovo }}{% if v.autore %} ({{ v.autore }}){% endif %}</li>
    {% endfor %}
  </ul>
  {% else %}
  <p>Nessuna voce di storico.</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_views --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 6: Commit (metodo sicuro)**

```bash
git add django_app/suggestion_corner/views.py django_app/suggestion_corner/templates/suggestion_corner/dettaglio.html django_app/suggestion_corner/tests/test_views.py
git commit -m "feat(suggestion_corner): dettaglio sola lettura con scope object-level + storico" -- django_app/suggestion_corner/views.py django_app/suggestion_corner/templates/suggestion_corner/dettaglio.html django_app/suggestion_corner/tests/test_views.py
```
Verifica scope.

---

### Task 5: ACL v2 bootstrap (PERM_VIEW + binding + nav + grants) + wiring apps.ready

**Files:**
- Create: `django_app/suggestion_corner/acl_bootstrap.py`
- Modify: `django_app/suggestion_corner/apps.py`
- Create: `django_app/suggestion_corner/tests/test_acl.py`

**Interfaces:**
- Consumes: `core.acl_bootstrap_base.run_bootstrap`, i modelli ACL v2 di `core.models`, `core.legacy_models.Ruolo`.
- Produces: `bootstrap_suggestion_corner_acl()`; permesso `suggestion_corner.segnalazione.view`; binding per `suggestion_corner:home`/`suggestion_corner:dettaglio`; `NavigationItem` `suggestion-corner`; grant `PERM_VIEW` a tutti i ruoli.

- [ ] **Step 1: Scrivere il test che fallisce**

`django_app/suggestion_corner/tests/test_acl.py`:
```python
from __future__ import annotations

from django.test import TestCase

from core.legacy_models import Ruolo
from core.models import NavigationItem, PermissionDefinition, RoutePermissionBinding
from suggestion_corner.acl_bootstrap import (
    PERM_VIEW, bootstrap_suggestion_corner_acl,
)


class SuggestionCornerAclTest(TestCase):
    def test_bootstrap_crea_permesso_binding_nav(self):
        Ruolo.objects.get_or_create(id=1, defaults={"nome": "admin"})
        bootstrap_suggestion_corner_acl(force=True)

        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_VIEW).exists())
        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="suggestion_corner:home", permission_id=PERM_VIEW
            ).exists()
        )
        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="suggestion_corner:dettaglio", permission_id=PERM_VIEW
            ).exists()
        )
        self.assertTrue(NavigationItem.objects.filter(code="suggestion-corner").exists())
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_acl --settings=config.settings.test`
Expected: FAIL — `ImportError` su `acl_bootstrap`.

- [ ] **Step 3: Creare acl_bootstrap.py**

`django_app/suggestion_corner/acl_bootstrap.py` (adattamento fedele di `gestione_specifiche/acl_bootstrap.py`, un solo permesso di view, grant a TUTTI i ruoli):
```python
"""Bootstrap ACL v2 canonico per Suggestion Corner (sola lettura, sessione 3).

Registra: permesso canonico view, binding route->permesso (necessari con
ACL_STRICT_CANONICAL in prod), voce di menu e grant di default a TUTTI i ruoli
(il modulo è apribile da ogni utente autenticato; lo scope dei dati è deciso in
permissions.visible_segnalazioni via Group SMS_TEAM). Chiamato da apps.ready().
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "suggestion_corner"
_BOOTSTRAP_CACHE_KEY = "suggestion_corner_acl_bootstrap_v1"

PERM_VIEW = "suggestion_corner.segnalazione.view"

_CANONICAL = {
    PERM_VIEW: {
        "label": "Suggestion Corner - Visualizza",
        "description": "Accesso a elenco e dettaglio segnalazioni (scope per-utente via Group SMS_TEAM).",
    },
}

_ROUTE_BINDINGS = {
    "suggestion_corner:home": PERM_VIEW,
    "suggestion_corner:dettaglio": PERM_VIEW,
}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "sc_view", "label": "Suggestion Corner",
     "url": "/suggestion-corner/", "visible_topbar": True, "ui_order": 95},
]


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Ruolo
    from core.models import (
        NavigationItem, NavigationRoleAccess, PermissionDefinition,
        RolePermissionGrant, RoutePermissionBinding,
    )
    from core.navigation_registry import bump_navigation_registry_version

    changed = False
    with transaction.atomic():
        # 1) permesso canonico
        for code, payload in _CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        # 2) binding route -> permesso
        for route_name, code in _ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[SC_BOOTSTRAP] binding Suggestion Corner",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        # 3) voce di menu
        nav, created = NavigationItem.objects.update_or_create(
            code="suggestion-corner",
            defaults={"label": "Suggestion Corner",
                      "route_name": "suggestion_corner:home",
                      "url_path": "", "section": "topbar",
                      "required_permission_code": PERM_VIEW, "order": 95,
                      "is_visible": True, "is_enabled": True, "icon": "message-square",
                      "description": "Segnalazioni di miglioramento (SMS)."},
        )
        changed = changed or created

        # 4) grant PERM_VIEW a TUTTI i ruoli (modulo apribile da ogni utente;
        #    lo scope dati è filtrato in view). CREATE-ONLY, non clobbera l'admin.
        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        existing_nav = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=nav)}
        for rid in roles:
            _, created = RolePermissionGrant.objects.get_or_create(
                legacy_role_id=rid, permission_id=PERM_VIEW,
                defaults={"enabled": True, "note": "[SC_BOOTSTRAP] default view"},
            )
            changed = changed or created
            row = existing_nav.get(rid)
            if row is None:
                NavigationRoleAccess.objects.create(item=nav, legacy_role_id=rid, can_view=True)
                changed = True
            elif not row.can_view:
                row.can_view = True
                row.save(update_fields=["can_view"])
                changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_suggestion_corner_acl(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="message-square",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
```

- [ ] **Step 4: Agganciare in apps.ready()**

In `django_app/suggestion_corner/apps.py`, estendere `ready()` (mantenendo l'import di `state_machine` della sessione 2):
```python
    def ready(self):
        """Collega il signal post_transition (audit FSM) e fa il bootstrap ACL v2.
        Entrambi fail-safe."""
        try:
            from . import state_machine  # noqa: F401  (registra il signal audit)
        except Exception:
            pass
        try:
            from .acl_bootstrap import bootstrap_suggestion_corner_acl

            bootstrap_suggestion_corner_acl()
        except Exception:
            return
```

- [ ] **Step 5: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_acl --settings=config.settings.test`
Expected: PASS. Se il modello `RolePermissionGrant`/`RoutePermissionBinding` ha nomi campo diversi da quelli usati (verificare contro `gestione_specifiche/acl_bootstrap.py`, che è la fonte di verità copiata), allinearli — il pattern è identico.

- [ ] **Step 6: Commit (metodo sicuro)**

```bash
git add django_app/suggestion_corner/acl_bootstrap.py django_app/suggestion_corner/apps.py django_app/suggestion_corner/tests/test_acl.py
git commit -m "feat(suggestion_corner): ACL v2 bootstrap (PERM_VIEW + binding + nav + grants) + wiring apps.ready" -- django_app/suggestion_corner/acl_bootstrap.py django_app/suggestion_corner/apps.py django_app/suggestion_corner/tests/test_acl.py
```
Verifica scope.

---

### Task 6: Verifica finale + no-migration + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md` (gestito dal controller, non da subagent)

- [ ] **Step 1: Suite completa del modulo**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner --keepdb --settings=config.settings.test`
Expected: tutti verdi (models + admin + fsm + views + permissions + acl).

- [ ] **Step 2: no-migration + check**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --check --dry-run --settings=config.settings.test`
Expected: "No changes detected".
Run: `.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: no issues.

- [ ] **Step 3: CHANGELOG (controller)**

Il controller aggiunge sotto `[Unreleased] > ### Added` la voce sessione 3 (urls + viste lettura + doppio livello ACL/Group + nav) e committa SOLO la propria voce con la tecnica salva-patch/revert/edit/commit/riapplica.

---

## Self-Review (fatto in fase di stesura)

- **Copertura design §4:** SMS_TEAM (Group) vede tutto ✔ (Task 2/3); utenti normali vedono le proprie + incarichi ✔ (Task 2); pubblico POST-only = sessione 4 (fuori scope, dichiarato). Viste "da gestire"/"riguarda SMS" come queryset filtrati ✔ (Task 3, `da_gestire`). ✔
- **Doppio livello autorizzazione:** ACL v2 PERM_VIEW+binding (accesso modulo, prod ACL_STRICT) + Group SMS_TEAM (scope dati). Coerente con le memorie `acl_middleware_api_gate_paths` (nessun endpoint API JSON qui → nessun `API_ACL_GATE_PATHS`) e `acl_canonical_overrides_legacy`. ✔
- **route_name:** `suggestion_corner:home` combacia con `module_registry` (sessione 1). ✔
- **No-migration:** nessun campo nuovo; verifica in Task 6. ✔
- **Fuori scope (sessione 3b+):** azioni FSM da UI (classifica/plan/completa/check/chiudi), form pubblico (sess. 4), email (sess. 5), dashboard KPI (sess. 10). ✔
- **Rischio noto:** i nomi dei campi dei modelli ACL v2 (`RolePermissionGrant.legacy_role_id`, `RoutePermissionBinding.permission_id`/`match_strategy`/`path_pattern`) sono copiati 1:1 da `gestione_specifiche/acl_bootstrap.py` (fonte di verità funzionante). Se un test fallisse su un nome campo, allineare a quel file. In `config.settings.test` `ACL_STRICT_CANONICAL` è off, quindi i test view non dipendono dai grant; il binding è verificato strutturalmente in `test_acl`. ✔
- **Placeholder scan:** nessun TBD; ogni step ha codice/comando concreto. ✔
