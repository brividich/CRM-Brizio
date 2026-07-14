# Report compliance SDS (`schede_sicurezza`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compliance report page to the existing `schede_sicurezza` Django app showing (1) chemical products with no current safety data sheet, and (2) per-department percentage of active employees who confirmed reading each current SDS, with CSV export for both.

**Architecture:** Two pure query functions in a new `schede_sicurezza/reports.py` service module, consumed by one gated view (`report_compliance`) that either renders an HTML page or streams a CSV depending on query params. No new models, no new permissions — reuses the existing `schede_sicurezza.prodotto.gestisci` ACL v2 permission and route-binding pattern already used by every other view in this app.

**Tech Stack:** Django 5.2, `config.settings.test` (SQLite) for tests, existing `anagrafica.Reparto`/`AreaAziendale`/`DipendenteAnagraficaAziendale` and `core.models.Profile` models for the department→user resolution (verified against real code, not assumed — see design spec).

## Global Constraints

- Run scoped tests only: `python django_app\manage.py test django_app.schede_sicurezza --settings=config.settings.test --keepdb` (never the full suite unless explicitly asked — CLAUDE.md).
- No new dependencies. No new ACL permission — reuse `schede_sicurezza.prodotto.gestisci` (`PERM_GESTISCI` in `schede_sicurezza/acl_bootstrap.py`).
- Reuse the existing `ss-*` CSS classes already defined in `schede_sicurezza/templates/schede_sicurezza/pages/prodotto_list.html` — no new color palette.
- "Dipendente attivo" = `DipendenteAnagraficaAziendale.data_cessazione__isnull=True`. There is no dedicated boolean field.
- A department with zero resolvable employees must report percentage as `None` (rendered "n/d"), never `0`.
- Update `CHANGELOG.md` and `README.md` as the final task, per CLAUDE.md's mandatory-after-every-change rule.
- Design spec: `docs/superpowers/specs/2026-07-09-schede-sicurezza-report-compliance-design.md`.

---

### Task 1: `prodotti_senza_scheda_corrente()` query function

**Files:**
- Create: `django_app/schede_sicurezza/reports.py`
- Create: `django_app/schede_sicurezza/tests_reports.py`

**Interfaces:**
- Produces: `prodotti_senza_scheda_corrente() -> QuerySet[ProdottoChimico]` — importable as `from schede_sicurezza.reports import prodotti_senza_scheda_corrente`. Each item in the queryset has `.nome`, `.reparto.nome`, `.fornitore` accessible without extra queries (uses `select_related("reparto")`).

- [ ] **Step 1: Write the failing test**

Create `django_app/schede_sicurezza/tests_reports.py`:

```python
from __future__ import annotations

from django.test import TestCase

from anagrafica.models import Reparto

from .models import ProdottoChimico, SchedaSicurezza
from .reports import prodotti_senza_scheda_corrente


def _pdf():
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n%finto\n", content_type="application/pdf")


class ProdottiSenzaSchedaCorrenteTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")

    def test_prodotto_senza_nessuna_scheda_e_incluso(self):
        p = ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        self.assertIn(p, prodotti_senza_scheda_corrente())

    def test_prodotto_con_scheda_non_corrente_e_incluso(self):
        p = ProdottoChimico.objects.create(nome="Solo scheda vecchia", reparto=self.reparto)
        SchedaSicurezza.objects.create(prodotto=p, pdf=_pdf(), versione="1", is_corrente=False)
        self.assertIn(p, prodotti_senza_scheda_corrente())

    def test_prodotto_con_scheda_corrente_e_escluso(self):
        p = ProdottoChimico.objects.create(nome="Con scheda corrente", reparto=self.reparto)
        SchedaSicurezza.objects.create(prodotto=p, pdf=_pdf(), versione="1", is_corrente=True)
        self.assertNotIn(p, prodotti_senza_scheda_corrente())

    def test_prodotto_non_attivo_e_escluso(self):
        p = ProdottoChimico.objects.create(nome="Disattivato", reparto=self.reparto, attivo=False)
        self.assertNotIn(p, prodotti_senza_scheda_corrente())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_reports --settings=config.settings.test -v 2`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'schede_sicurezza.reports'` (the module does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `django_app/schede_sicurezza/reports.py`:

```python
"""Query di sola lettura per il report di compliance SDS (nessun modello nuovo).

Funzioni pure: non toccano `request`, non hanno side effect. Consumate dalla
view `schede_sicurezza.views.report_compliance` sia per il rendering HTML sia
per l'export CSV.
"""
from __future__ import annotations

from dataclasses import dataclass


def prodotti_senza_scheda_corrente():
    """QuerySet dei ProdottoChimico attivi senza nessuna SchedaSicurezza corrente."""
    from .models import ProdottoChimico

    return (
        ProdottoChimico.objects.filter(attivo=True)
        .exclude(schede__is_corrente=True)
        .select_related("reparto")
        .order_by("reparto__nome", "nome")
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_reports --settings=config.settings.test -v 2`
Expected: `Ran 4 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add django_app/schede_sicurezza/reports.py django_app/schede_sicurezza/tests_reports.py
git commit -m "feat(schede-sicurezza): query prodotti senza scheda corrente per report compliance"
```

---

### Task 2: `matrice_presa_visione()` query function

**Files:**
- Modify: `django_app/schede_sicurezza/reports.py`
- Modify: `django_app/schede_sicurezza/tests_reports.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (independent function in the same module).
- Produces:
  - `RigaMatricePresaVisione` dataclass with fields `prodotto_id: int`, `prodotto_nome: str`, `scheda_id: int`, `scheda_versione: str`, `totale_dipendenti: int`, `confermati: int`, `percentuale: int | None`
  - `RepartoMatricePresaVisione` dataclass with fields `reparto_id: int`, `reparto_nome: str`, `righe: list[RigaMatricePresaVisione]`
  - `matrice_presa_visione() -> list[RepartoMatricePresaVisione]` — importable as `from schede_sicurezza.reports import matrice_presa_visione, RepartoMatricePresaVisione, RigaMatricePresaVisione`. Later tasks (view, template, CSV export) consume this return type.

- [ ] **Step 1: Write the failing test**

Append to `django_app/schede_sicurezza/tests_reports.py`:

```python
from django.contrib.auth import get_user_model

from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale
from core.models import Profile

from .models import PresaVisioneScheda
from .reports import matrice_presa_visione

User = get_user_model()


def _crea_dipendente_attivo(legacy_id: int, area_aziendale, *, cessato=False) -> "User":
    from datetime import date

    DipendenteAnagraficaAziendale.objects.create(
        legacy_anagrafica_id=legacy_id,
        area_aziendale=area_aziendale,
        data_cessazione=date(2020, 1, 1) if cessato else None,
    )
    user = User.objects.create_user(username=f"dip{legacy_id}", password="x")
    Profile.objects.create(user=user, legacy_user_id=legacy_id)
    return user


class MatricePresaVisioneTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.area = AreaAziendale.objects.create(nome="Produzione - Linea 1", reparto=self.reparto)
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_pdf(), versione="1", is_corrente=True,
        )

    def test_percentuale_calcolata_su_dipendenti_attivi_mappati(self):
        u1 = _crea_dipendente_attivo(9001, self.area)
        _crea_dipendente_attivo(9002, self.area)  # non conferma
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=u1)

        matrice = matrice_presa_visione()
        self.assertEqual(len(matrice), 1)
        reparto_row = matrice[0]
        self.assertEqual(reparto_row.reparto_id, self.reparto.id)
        self.assertEqual(len(reparto_row.righe), 1)
        riga = reparto_row.righe[0]
        self.assertEqual(riga.totale_dipendenti, 2)
        self.assertEqual(riga.confermati, 1)
        self.assertEqual(riga.percentuale, 50)

    def test_dipendente_cessato_escluso_dal_denominatore(self):
        u1 = _crea_dipendente_attivo(9003, self.area)
        _crea_dipendente_attivo(9004, self.area, cessato=True)
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=u1)

        riga = matrice_presa_visione()[0].righe[0]
        self.assertEqual(riga.totale_dipendenti, 1)
        self.assertEqual(riga.confermati, 1)
        self.assertEqual(riga.percentuale, 100)

    def test_nessun_dipendente_mappato_da_percentuale_none(self):
        # nessun DipendenteAnagraficaAziendale collegato all'area del reparto
        riga = matrice_presa_visione()[0].righe[0]
        self.assertEqual(riga.totale_dipendenti, 0)
        self.assertIsNone(riga.percentuale)

    def test_prodotto_senza_scheda_corrente_non_appare_in_matrice(self):
        ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        _crea_dipendente_attivo(9005, self.area)
        nomi_prodotto = {r.prodotto_nome for r in matrice_presa_visione()[0].righe}
        self.assertNotIn("Senza scheda", nomi_prodotto)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_reports --settings=config.settings.test -v 2`
Expected: FAIL — `ImportError: cannot import name 'matrice_presa_visione'`.

- [ ] **Step 3: Write minimal implementation**

Append to `django_app/schede_sicurezza/reports.py`:

```python
@dataclass
class RigaMatricePresaVisione:
    prodotto_id: int
    prodotto_nome: str
    scheda_id: int
    scheda_versione: str
    totale_dipendenti: int
    confermati: int
    percentuale: int | None


@dataclass
class RepartoMatricePresaVisione:
    reparto_id: int
    reparto_nome: str
    righe: list[RigaMatricePresaVisione]


def _user_ids_attivi_per_reparto(reparto_id: int) -> set[int]:
    """Django User attivi collegati (via Profile) a dipendenti in forza del reparto.

    Percorso verificato: Reparto <- AreaAziendale.reparto <- DipendenteAnagraficaAziendale
    (legacy_anagrafica_id == Profile.legacy_user_id, stesso spazio ID) -> User.
    Limite noto: cattura solo i dipendenti con `area_aziendale` valorizzato, non
    quelli ancora sul solo campo testo legacy `area`.
    """
    from anagrafica.models import DipendenteAnagraficaAziendale
    from core.models import Profile

    legacy_ids = list(
        DipendenteAnagraficaAziendale.objects.filter(
            area_aziendale__reparto_id=reparto_id,
            data_cessazione__isnull=True,
        ).values_list("legacy_anagrafica_id", flat=True)
    )
    if not legacy_ids:
        return set()
    return set(
        Profile.objects.filter(legacy_user_id__in=legacy_ids, user__is_active=True)
        .values_list("user_id", flat=True)
    )


def matrice_presa_visione() -> list[RepartoMatricePresaVisione]:
    """Un elemento per ogni Reparto con almeno un prodotto attivo con scheda corrente."""
    from anagrafica.models import Reparto

    from .models import PresaVisioneScheda, ProdottoChimico

    risultato: list[RepartoMatricePresaVisione] = []
    reparti = (
        Reparto.objects.filter(
            prodotti_chimici__attivo=True,
            prodotti_chimici__schede__is_corrente=True,
        )
        .distinct()
        .order_by("nome")
    )
    for reparto in reparti:
        user_ids = _user_ids_attivi_per_reparto(reparto.id)
        prodotti = (
            ProdottoChimico.objects.filter(reparto=reparto, attivo=True, schede__is_corrente=True)
            .distinct()
            .order_by("nome")
        )
        righe: list[RigaMatricePresaVisione] = []
        for prodotto in prodotti:
            scheda = prodotto.scheda_corrente()
            if scheda is None:
                continue
            totale = len(user_ids)
            if totale == 0:
                confermati = 0
                percentuale = None
            else:
                confermati = PresaVisioneScheda.objects.filter(
                    scheda=scheda, operatore_id__in=user_ids
                ).count()
                percentuale = round((confermati / totale) * 100)
            righe.append(RigaMatricePresaVisione(
                prodotto_id=prodotto.id,
                prodotto_nome=prodotto.nome,
                scheda_id=scheda.id,
                scheda_versione=scheda.versione,
                totale_dipendenti=totale,
                confermati=confermati,
                percentuale=percentuale,
            ))
        if righe:
            risultato.append(RepartoMatricePresaVisione(
                reparto_id=reparto.id, reparto_nome=reparto.nome, righe=righe,
            ))
    return risultato
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_reports --settings=config.settings.test -v 2`
Expected: `Ran 8 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add django_app/schede_sicurezza/reports.py django_app/schede_sicurezza/tests_reports.py
git commit -m "feat(schede-sicurezza): query matrice presa visione per reparto"
```

---

### Task 3: `report_compliance` view (HTML only) + URL + ACL binding

**Files:**
- Modify: `django_app/schede_sicurezza/views.py`
- Modify: `django_app/schede_sicurezza/urls.py:11` (insert new path after `prodotto_nuovo`)
- Modify: `django_app/schede_sicurezza/acl_bootstrap.py` (`_ROUTE_BINDINGS` dict, `_BOOTSTRAP_CACHE_KEY`)
- Create: `django_app/schede_sicurezza/tests_report_view.py`

**Interfaces:**
- Consumes: `prodotti_senza_scheda_corrente()` and `matrice_presa_visione()` from Task 1/2 (`from .reports import ...`), `_can_gestire(request)` already defined in `views.py`.
- Produces: view function `report_compliance(request)`, URL name `schede_sicurezza:report_compliance` at path `/schede-sicurezza/report/`.

- [ ] **Step 1: Write the failing test**

Create `django_app/schede_sicurezza/tests_report_view.py`:

```python
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Reparto

from .models import ProdottoChimico

User = get_user_model()


def _pdf():
    return SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n%finto\n", content_type="application/pdf")


class ReportComplianceViewTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        self.admin = User.objects.create_user(username="admin_report", password="x", is_superuser=True, is_staff=True)

    def test_report_visibile_a_utente_con_permesso(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Senza scheda")

    def test_report_negato_a_utente_senza_permesso(self):
        utente = User.objects.create_user(username="senza_permesso_report", password="x")
        self.client.force_login(utente)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertNotEqual(resp.status_code, 200)

    def test_report_negato_senza_login(self):
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_report_view --settings=config.settings.test -v 2`
Expected: FAIL — `NoReverseMatch: Reverse for 'report_compliance' not found`.

- [ ] **Step 3: Write minimal implementation**

In `django_app/schede_sicurezza/views.py`, add near the top imports (alongside the existing `from .services.qr import genera_qr_png` line):

```python
from .reports import matrice_presa_visione, prodotti_senza_scheda_corrente
```

Then add this view function at the end of the file:

```python
@login_required
def report_compliance(request):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    return render(request, "schede_sicurezza/pages/report_compliance.html", {
        "gap": prodotti_senza_scheda_corrente(),
        "matrice": matrice_presa_visione(),
    })
```

In `django_app/schede_sicurezza/urls.py`, insert after line 11 (`path("nuovo/", ...)`):

```python
    path("report/", views.report_compliance, name="report_compliance"),
```

Full resulting `urlpatterns` order:

```python
urlpatterns = [
    path("", views.prodotto_list, name="prodotto_list"),
    path("nuovo/", views.prodotto_form, name="prodotto_nuovo"),
    path("report/", views.report_compliance, name="report_compliance"),
    path("<int:pk>/", views.prodotto_detail, name="prodotto_detail"),
    path("<int:pk>/modifica/", views.prodotto_form, name="prodotto_modifica"),
    path("<int:pk>/qr/", views.prodotto_qr, name="prodotto_qr"),
    path("s/<uuid:uuid>/", views.scheda_mobile, name="scheda_mobile"),
    path("scheda/<int:pk>/download/", views.scheda_download, name="scheda_download"),
    path("scheda/<int:scheda_pk>/presa-visione/", views.presa_visione_conferma, name="presa_visione_conferma"),
    path("scheda/<int:scheda_pk>/presa-visione/elenco/", views.presa_visione_list, name="presa_visione_list"),
]
```

Create a minimal placeholder template so the view doesn't 500 — `django_app/schede_sicurezza/templates/schede_sicurezza/pages/report_compliance.html`:

```html
{% extends "core/base.html" %}

{% block title %}Report compliance | Schede Sicurezza{% endblock %}

{% block content %}
<div>
  <h1>Report compliance SDS</h1>
  <ul>
    {% for prodotto in gap %}
      <li>{{ prodotto.nome }}</li>
    {% endfor %}
  </ul>
</div>
{% endblock %}
```

(This placeholder is replaced with the full styled template in Task 5.)

In `django_app/schede_sicurezza/acl_bootstrap.py`, update `_ROUTE_BINDINGS` to add the new route (insert after the `presa_visione_conferma` entry):

```python
_ROUTE_BINDINGS = {
    "schede_sicurezza:prodotto_list": PERM_VIEW,
    "schede_sicurezza:prodotto_detail": PERM_VIEW,
    "schede_sicurezza:prodotto_qr": PERM_VIEW,
    "schede_sicurezza:scheda_mobile": PERM_VIEW,
    "schede_sicurezza:scheda_download": PERM_VIEW,
    "schede_sicurezza:presa_visione_conferma": PERM_VIEW,
    "schede_sicurezza:prodotto_nuovo": PERM_GESTISCI,
    "schede_sicurezza:prodotto_modifica": PERM_GESTISCI,
    "schede_sicurezza:presa_visione_list": PERM_GESTISCI,
    "schede_sicurezza:report_compliance": PERM_GESTISCI,
}
```

And bump the cache key so the binding gets registered on environments where the module already bootstrapped once:

```python
_BOOTSTRAP_CACHE_KEY = "schede_sicurezza_acl_bootstrap_v2"
```

(replaces the existing `_BOOTSTRAP_CACHE_KEY = "schede_sicurezza_acl_bootstrap_v1"` line)

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_report_view --settings=config.settings.test -v 2`
Expected: `Ran 3 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add django_app/schede_sicurezza/views.py django_app/schede_sicurezza/urls.py django_app/schede_sicurezza/acl_bootstrap.py django_app/schede_sicurezza/tests_report_view.py django_app/schede_sicurezza/templates/schede_sicurezza/pages/report_compliance.html
git commit -m "feat(schede-sicurezza): view report_compliance gated ACL v2 + route binding"
```

---

### Task 4: CSV export for both report sections

**Files:**
- Modify: `django_app/schede_sicurezza/views.py`
- Modify: `django_app/schede_sicurezza/tests_report_view.py`

**Interfaces:**
- Consumes: `RepartoMatricePresaVisione`/`RigaMatricePresaVisione` field names from Task 2, `prodotti_senza_scheda_corrente()` from Task 1.
- Produces: `report_compliance` now also handles `?formato=csv&sezione=gap` and `?formato=csv&sezione=matrice` query params, returning `text/csv` responses. No new URL — same view.

- [ ] **Step 1: Write the failing test**

Append to `django_app/schede_sicurezza/tests_report_view.py`:

```python
import csv
import io

from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale
from core.models import Profile

from .models import PresaVisioneScheda, SchedaSicurezza


class ReportComplianceCsvExportTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.area = AreaAziendale.objects.create(nome="Produzione - Linea 1", reparto=self.reparto)
        self.senza_scheda = ProdottoChimico.objects.create(
            nome="Senza scheda", reparto=self.reparto, fornitore="ACME",
        )
        self.con_scheda = ProdottoChimico.objects.create(nome="Con scheda", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.con_scheda, pdf=_pdf(), versione="Rev.2", is_corrente=True,
        )
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=9101, area_aziendale=self.area)
        dip_user = User.objects.create_user(username="dip9101", password="x")
        Profile.objects.create(user=dip_user, legacy_user_id=9101)
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=dip_user)

        self.admin = User.objects.create_user(username="admin_csv", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_export_csv_gap(self):
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"), {"formato": "csv", "sezione": "gap"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        righe = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        self.assertEqual(righe[0], ["Prodotto", "Reparto", "Fornitore"])
        self.assertIn(["Senza scheda", "Produzione", "ACME"], righe)

    def test_export_csv_matrice(self):
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"), {"formato": "csv", "sezione": "matrice"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        righe = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        self.assertEqual(
            righe[0],
            ["Reparto", "Prodotto", "Versione scheda", "Dipendenti totali", "Confermati", "Percentuale"],
        )
        self.assertIn(["Produzione", "Con scheda", "Rev.2", "1", "1", "100%"], righe)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_report_view --settings=config.settings.test -v 2`
Expected: FAIL — the view ignores `formato`/`sezione` and returns the HTML page (`Content-Type` is `text/html`, assertion on `resp["Content-Type"] == "text/csv"` fails).

- [ ] **Step 3: Write minimal implementation**

In `django_app/schede_sicurezza/views.py`, add `import csv` near the top with the other stdlib imports, then replace the `report_compliance` view body with:

```python
@login_required
def report_compliance(request):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    formato = request.GET.get("formato", "").strip()
    sezione = request.GET.get("sezione", "").strip()

    if formato == "csv" and sezione == "gap":
        return _csv_gap_sds(prodotti_senza_scheda_corrente())
    if formato == "csv" and sezione == "matrice":
        return _csv_matrice_presa_visione(matrice_presa_visione())

    return render(request, "schede_sicurezza/pages/report_compliance.html", {
        "gap": prodotti_senza_scheda_corrente(),
        "matrice": matrice_presa_visione(),
    })


def _csv_gap_sds(prodotti):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="schede_sicurezza_gap_sds.csv"'
    writer = csv.writer(response)
    writer.writerow(["Prodotto", "Reparto", "Fornitore"])
    for p in prodotti:
        writer.writerow([p.nome, p.reparto.nome, p.fornitore])
    return response


def _csv_matrice_presa_visione(reparti):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="schede_sicurezza_matrice_presa_visione.csv"'
    writer = csv.writer(response)
    writer.writerow(["Reparto", "Prodotto", "Versione scheda", "Dipendenti totali", "Confermati", "Percentuale"])
    for reparto in reparti:
        for riga in reparto.righe:
            percentuale = "n/d" if riga.percentuale is None else f"{riga.percentuale}%"
            writer.writerow([
                reparto.reparto_nome, riga.prodotto_nome, riga.scheda_versione,
                riga.totale_dipendenti, riga.confermati, percentuale,
            ])
    return response
```

`HttpResponse` is already imported in `views.py` (used by `prodotto_qr`); no new import needed for it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_report_view --settings=config.settings.test -v 2`
Expected: `Ran 5 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add django_app/schede_sicurezza/views.py django_app/schede_sicurezza/tests_report_view.py
git commit -m "feat(schede-sicurezza): export CSV gap SDS e matrice presa visione"
```

---

### Task 5: Styled template + navigation link

**Files:**
- Modify: `django_app/schede_sicurezza/templates/schede_sicurezza/pages/report_compliance.html` (replace Task 3 placeholder)
- Modify: `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_list.html:49-53`
- Modify: `django_app/schede_sicurezza/tests_report_view.py`

**Interfaces:**
- Consumes: `gap` (queryset from Task 1) and `matrice` (list of `RepartoMatricePresaVisione` from Task 2) template context variables, already passed by the view from Task 3/4.
- Produces: nothing consumed by later tasks — this is the last functional task.

- [ ] **Step 1: Write the failing test**

Append to `django_app/schede_sicurezza/tests_report_view.py` (reuses `ReportComplianceCsvExportTest.setUp` fixtures via a new test class with its own setup):

```python
class ReportComplianceTemplateTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.area = AreaAziendale.objects.create(nome="Produzione - Linea 1", reparto=self.reparto)
        self.prodotto = ProdottoChimico.objects.create(nome="Con scheda", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_pdf(), versione="Rev.2", is_corrente=True,
        )
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=9201, area_aziendale=self.area)
        dip_user = User.objects.create_user(username="dip9201", password="x")
        Profile.objects.create(user=dip_user, legacy_user_id=9201)
        self.admin = User.objects.create_user(username="admin_tpl", password="x", is_superuser=True, is_staff=True)

    def test_matrice_mostra_percentuale_e_badge(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertContains(resp, "Rev.2")
        self.assertContains(resp, "0%")  # nessuna presa visione ancora confermata

    def test_link_report_presente_in_lista_prodotti(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"))
        self.assertContains(resp, reverse("schede_sicurezza:report_compliance"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_report_view --settings=config.settings.test -v 2`
Expected: FAIL — `test_matrice_mostra_percentuale_e_badge` fails because the Task 3 placeholder template never renders `matrice`/percentages; `test_link_report_presente_in_lista_prodotti` fails because `prodotto_list.html` has no link yet.

- [ ] **Step 3: Write minimal implementation**

Replace the full contents of `django_app/schede_sicurezza/templates/schede_sicurezza/pages/report_compliance.html`:

```html
{% extends "core/base.html" %}

{% block title %}Report compliance | Schede Sicurezza{% endblock %}

{% block extra_head %}
<style>
.ss-report-section { background:#fff; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-bottom:20px; }
.ss-report-title { font-size:16px; font-weight:800; margin-bottom:10px; display:flex; align-items:center; justify-content:space-between; }
.ss-pct-badge { display:inline-block; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:700; }
.ss-pct-rosso { background:#fee2e2; color:#dc2626; }
.ss-pct-arancione { background:#fef3c7; color:#b45309; }
.ss-pct-verde { background:#dcfce7; color:#15803d; }
.ss-pct-nd { background:#f1f5f9; color:#64748b; }

body.theme-dark .ss-report-section { background:var(--surface); border-color:var(--border); }
body.theme-dark .ss-pct-rosso { background:rgba(220,38,38,.2); color:#fca5a5; }
body.theme-dark .ss-pct-arancione { background:rgba(180,83,9,.2); color:#fbbf24; }
body.theme-dark .ss-pct-verde { background:rgba(21,128,61,.2); color:#86efac; }
body.theme-dark .ss-pct-nd { background:var(--surface-alt); color:var(--text-light); }
</style>
{% endblock %}

{% block content %}
<div style="display:flex;flex-direction:column;gap:8px;">
  <div class="ss-header-row">
    <div class="ss-page-title">Report compliance SDS</div>
    <a href="{% url 'schede_sicurezza:prodotto_list' %}" class="ss-btn ss-btn-sm ss-btn-gray">← Torna all'elenco</a>
  </div>

  <div class="ss-report-section">
    <div class="ss-report-title">
      Prodotti senza scheda corrente ({{ gap|length }})
      <a href="?formato=csv&amp;sezione=gap" class="ss-btn ss-btn-sm ss-btn-gray">Export CSV</a>
    </div>
    {% if gap %}
      <table class="ss-table">
        <thead><tr><th>Prodotto</th><th>Reparto</th><th>Fornitore</th><th></th></tr></thead>
        <tbody>
          {% for prodotto in gap %}
            <tr>
              <td>{{ prodotto.nome }}</td>
              <td>{{ prodotto.reparto.nome }}</td>
              <td>{{ prodotto.fornitore|default:"—" }}</td>
              <td><a href="{% url 'schede_sicurezza:prodotto_detail' pk=prodotto.pk %}" class="ss-btn ss-btn-sm ss-btn-gray">Carica SDS</a></td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <div class="ss-empty">Tutti i prodotti attivi hanno una scheda corrente.</div>
    {% endif %}
  </div>

  <div class="ss-report-section">
    <div class="ss-report-title">
      Presa visione per reparto
      <a href="?formato=csv&amp;sezione=matrice" class="ss-btn ss-btn-sm ss-btn-gray">Export CSV</a>
    </div>
    {% if matrice %}
      <table class="ss-table">
        <thead><tr><th>Reparto</th><th>Prodotto</th><th>Versione</th><th>Confermati</th><th>Copertura</th></tr></thead>
        <tbody>
          {% for reparto_row in matrice %}
            {% for riga in reparto_row.righe %}
              <tr>
                <td>{{ reparto_row.reparto_nome }}</td>
                <td>{{ riga.prodotto_nome }}</td>
                <td>{{ riga.scheda_versione|default:"—" }}</td>
                <td>{{ riga.confermati }} / {{ riga.totale_dipendenti }}</td>
                <td>
                  {% if riga.percentuale is None %}
                    <span class="ss-pct-badge ss-pct-nd" title="Nessun dipendente collegato al reparto tramite area aziendale">n/d</span>
                  {% elif riga.percentuale >= 100 %}
                    <span class="ss-pct-badge ss-pct-verde">{{ riga.percentuale }}%</span>
                  {% elif riga.percentuale >= 50 %}
                    <span class="ss-pct-badge ss-pct-arancione">{{ riga.percentuale }}%</span>
                  {% else %}
                    <span class="ss-pct-badge ss-pct-rosso">{{ riga.percentuale }}%</span>
                  {% endif %}
                </td>
              </tr>
            {% endfor %}
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <div class="ss-empty">Nessun prodotto con scheda corrente da monitorare.</div>
    {% endif %}
  </div>
</div>
{% endblock %}
```

In `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_list.html`, replace lines 49-53:

```html
  <div class="ss-header-row">
    <div class="ss-page-title">Schede di Sicurezza (SDS)</div>
    {% if can_gestire %}
      <a href="{% url 'schede_sicurezza:prodotto_nuovo' %}" class="ss-btn">+ Nuovo prodotto</a>
    {% endif %}
```

with:

```html
  <div class="ss-header-row">
    <div class="ss-page-title">Schede di Sicurezza (SDS)</div>
    <div style="display:flex;gap:8px;">
      {% if can_gestire %}
        <a href="{% url 'schede_sicurezza:report_compliance' %}" class="ss-btn ss-btn-gray">Report compliance</a>
        <a href="{% url 'schede_sicurezza:prodotto_nuovo' %}" class="ss-btn">+ Nuovo prodotto</a>
      {% endif %}
    </div>
```

(the existing `{% endif %}` two lines below already closes this block — no other change needed there)

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_report_view --settings=config.settings.test -v 2`
Expected: `Ran 7 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add django_app/schede_sicurezza/templates/schede_sicurezza/pages/report_compliance.html django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_list.html django_app/schede_sicurezza/tests_report_view.py
git commit -m "feat(schede-sicurezza): template report compliance con badge percentuale + link da lista prodotti"
```

---

### Task 6: ACL bootstrap regression test, full suite, CHANGELOG/README

**Files:**
- Modify: `django_app/schede_sicurezza/tests_acl.py`
- Modify: `CHANGELOG.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `PERM_GESTISCI` from `schede_sicurezza/acl_bootstrap.py` (already imported in `tests_acl.py`).
- Produces: nothing (terminal task).

- [ ] **Step 1: Write the failing test**

In `django_app/schede_sicurezza/tests_acl.py`, add a new test method to the existing `AclBootstrapTest` class:

```python
    def test_binding_report_compliance(self):
        from core.models import RoutePermissionBinding

        _bootstrap_canonical()
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="schede_sicurezza:report_compliance", permission_id=PERM_GESTISCI
        ).exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_acl --settings=config.settings.test -v 2`
Expected: FAIL if Task 3's `acl_bootstrap.py` edit was somehow skipped (`AssertionError: False is not true`). If Task 3 was completed correctly this will already PASS — in that case skip to Step 4 directly (no code change needed here, this step is a regression guard for the change already made in Task 3).

- [ ] **Step 3: Write minimal implementation**

No implementation change expected here — `_ROUTE_BINDINGS` was already updated in Task 3. If Step 2 failed, go back and verify `django_app/schede_sicurezza/acl_bootstrap.py` contains the `"schede_sicurezza:report_compliance": PERM_GESTISCI,` entry added in Task 3 Step 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza --settings=config.settings.test --keepdb -v 2`
Expected: full app suite green, no failures (existing Fase 1 tests + all new tests from Tasks 1-6).

- [ ] **Step 5: Update CHANGELOG.md and README.md, then commit**

Add a new bullet under `### Added` in `CHANGELOG.md` (top of `## [Unreleased]`, following the existing entry style for this app):

```markdown
- **`schede_sicurezza` · Report compliance (gap SDS + matrice presa visione per reparto)** (`django_app/schede_sicurezza/reports.py` [nuovo], `views.py` [+`report_compliance`, +export CSV], `urls.py` [+`/schede-sicurezza/report/`], `acl_bootstrap.py` [+binding `report_compliance`→`PERM_GESTISCI`, cache key v1→v2], `templates/schede_sicurezza/pages/report_compliance.html` [nuovo], `templates/schede_sicurezza/pages/prodotto_list.html` [+link], `tests_reports.py`/`tests_report_view.py` [nuovi], `tests_acl.py` [+1 test]): primo sotto-progetto della "Fase 2" (decomposta in brainstorming — report/compliance, UI/UX, verifica consegna DPI, alert revisioni). Due sezioni: prodotti attivi senza scheda corrente, e per ogni reparto la % di dipendenti attivi che hanno confermato la lettura di ciascuna scheda corrente (denominatore risolto via `Reparto→AreaAziendale→DipendenteAnagraficaAziendale→Profile→User`, percentuale `None`/"n/d" quando nessun dipendente è mappato tramite `area_aziendale`). Export CSV per entrambe le sezioni. Nessun nuovo permesso ACL, nessun nuovo modello. Spec `docs/superpowers/specs/2026-07-09-schede-sicurezza-report-compliance-design.md`.
```

Update the `schede_sicurezza` row in the module catalog table in `README.md` (find the row containing `schede_sicurezza`) and its `<details>` section: append to the existing bullet list in the `<details>` block for `schede_sicurezza` a new line:

```markdown
- **Report compliance** (`/schede-sicurezza/report/`): prodotti attivi senza scheda corrente + matrice per reparto della % di dipendenti attivi che hanno confermato la presa visione (denominatore = `anagrafica.DipendenteAnagraficaAziendale` attivi collegati via `area_aziendale`), export CSV per entrambe le sezioni
```

Then commit everything:

```bash
git add django_app/schede_sicurezza/tests_acl.py CHANGELOG.md README.md
git commit -m "test(schede-sicurezza): binding ACL report_compliance + docs report compliance"
```

---

## Post-plan verification

After Task 6, run the full scoped suite one more time and confirm no pending migrations were introduced (this plan adds no models, so `makemigrations --check` should report no changes):

```bash
python django_app\manage.py test django_app.schede_sicurezza --settings=config.settings.test --keepdb -v 2
python django_app\manage.py makemigrations schede_sicurezza --check --dry-run --settings=config.settings.test
```

Expected: all tests green, `No changes detected in app 'schede_sicurezza'`.
