# UI/UX Fase 1 (`schede_sicurezza`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four UI polish features to the existing `schede_sicurezza` app: department/family/status filters on the product list, an "outdated SDS" badge (36 months since upload), inline editing of the PyMuPDF-extracted curated fields, and a helpful link when no department exists yet.

**Architecture:** A new `scaduta` property on `SchedaSicurezza` is the single source of truth for "outdated," reused by both the list-filter query and the badge template. The product-list view gains three optional GET filters composed onto its existing queryset. The product-detail view gains a second POST branch (disambiguated by a hidden `form_type` field) for editing the current sheet's curated fields, alongside the existing SDS-upload POST branch. The product-form template gets a conditional CTA linking to the already-existing `anagrafica:aree_list` page — no new department-management code.

**Tech Stack:** Django 5.2, `config.settings.test` (SQLite) for tests, no new dependencies, no new models, no new ACL permissions.

## Global Constraints

- Run scoped tests only: `python django_app\manage.py test django_app.schede_sicurezza.<module> --settings=config.settings.test --keepdb` (never the full suite unless explicitly asked — CLAUDE.md). When cwd is already `django_app/`, drop the `django_app.` prefix.
- No new dependencies, no new ACL permission, no new model, no migrations expected (property is Python-only).
- Reuse `ss-*` CSS classes already defined in `prodotto_list.html` — no new color palette.
- `SCADENZA_SDS_GIORNI = 1095` (~36 months) is the single threshold constant; both the `scaduta` property and the `da_rivedere` list filter must derive from it, never a second hardcoded number.
- Reuse `schede_sicurezza.reports.prodotti_senza_scheda_corrente()` for the `stato=senza_scheda` filter — do not reimplement that condition.
- No new department-management UI — link to the existing `anagrafica:aree_list` route only.
- Update `CHANGELOG.md` and `README.md` as the final task, per CLAUDE.md's mandatory-after-every-change rule.
- Design spec: `docs/superpowers/specs/2026-07-10-schede-sicurezza-ui-ux-fase1-design.md`.

---

### Task 1: `SchedaSicurezza.scaduta` property

**Files:**
- Modify: `django_app/schede_sicurezza/models.py:79-101` (add module-level constant before the class, add property inside the class)
- Modify: `django_app/schede_sicurezza/tests.py` (append test class)

**Interfaces:**
- Produces: module-level constant `schede_sicurezza.models.SCADENZA_SDS_GIORNI = 1095`; `SchedaSicurezza.scaduta` (property, `bool`) — importable/accessible as `scheda.scaduta` on any `SchedaSicurezza` instance. Later tasks (list filter, badge template, detail template) consume this.

- [ ] **Step 1: Write the failing test**

Append to `django_app/schede_sicurezza/tests.py`:

```python
from datetime import timedelta

from django.utils import timezone

from .models import SCADENZA_SDS_GIORNI


class SchedaSicurezzaScadutaTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)

    def test_scheda_recente_non_scaduta(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1",
        )
        self.assertFalse(scheda.scaduta)

    def test_scheda_vecchia_e_scaduta(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1",
        )
        vecchia_data = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI + 10)
        SchedaSicurezza.objects.filter(pk=scheda.pk).update(data_caricamento=vecchia_data)
        scheda.refresh_from_db()
        self.assertTrue(scheda.scaduta)

    def test_scheda_esattamente_alla_soglia_non_e_scaduta(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1",
        )
        soglia_data = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI - 1)
        SchedaSicurezza.objects.filter(pk=scheda.pk).update(data_caricamento=soglia_data)
        scheda.refresh_from_db()
        self.assertFalse(scheda.scaduta)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests.SchedaSicurezzaScadutaTest --settings=config.settings.test -v 2`
Expected: FAIL — `ImportError: cannot import name 'SCADENZA_SDS_GIORNI'` (the constant doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

In `django_app/schede_sicurezza/models.py`, immediately before the `class EstrazioneStato(models.TextChoices):` block (currently around line 72), add:

```python
SCADENZA_SDS_GIORNI = 1095  # ~36 mesi: soglia oltre la quale una scheda è segnalata "da rivedere"
```

Inside the `SchedaSicurezza` class, immediately after the `save()` method (currently ending around line 135, right before the `PresaVisioneScheda` section comment), add:

```python
    @property
    def scaduta(self) -> bool:
        """True se la scheda non viene aggiornata da più di SCADENZA_SDS_GIORNI giorni."""
        if not self.data_caricamento:
            return False
        soglia = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI)
        return self.data_caricamento < soglia
```

At the top of `django_app/schede_sicurezza/models.py`, the existing imports are:

```python
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
```

Change this to add the two new imports needed by the property:

```python
from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests.SchedaSicurezzaScadutaTest --settings=config.settings.test -v 2`
Expected: `Ran 3 tests ... OK`

- [ ] **Step 5: Run the full model test file to confirm no regression, then commit**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests --settings=config.settings.test --keepdb -v 2`
Expected: all tests OK (existing model tests + 3 new ones).

```bash
git add django_app/schede_sicurezza/models.py django_app/schede_sicurezza/tests.py
git commit -m "feat(schede-sicurezza): property SchedaSicurezza.scaduta (soglia 36 mesi)"
```

---

### Task 2: Filtri lista prodotti + badge scadenza

**Files:**
- Modify: `django_app/schede_sicurezza/views.py:70-92` (the `prodotto_list` function)
- Modify: `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_list.html`
- Modify: `django_app/schede_sicurezza/tests_views.py` (append test class — this file already covers `prodotto_list`-adjacent behavior from Fase 1)

**Interfaces:**
- Consumes: `SchedaSicurezza.scaduta` (Task 1), `schede_sicurezza.reports.prodotti_senza_scheda_corrente()` (already exists from the Report Compliance sub-project).
- Produces: `prodotto_list` now reads GET params `reparto`, `famiglia`, `stato` (values `""`/`con_scheda`/`senza_scheda`/`da_rivedere`) and passes `reparti_options` and `famiglie_options` to the template context, alongside the existing `prodotti`/`query`/`can_gestire`.

- [ ] **Step 1: Write the failing test**

Append to `django_app/schede_sicurezza/tests_views.py`:

```python
class ProdottoListFiltriTest(TestCase):
    def setUp(self):
        self.reparto_a = Reparto.objects.create(nome="Produzione")
        self.reparto_b = Reparto.objects.create(nome="Verniciatura")
        self.admin = User.objects.create_user(username="admin_filtri", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

        self.senza_scheda = ProdottoChimico.objects.create(
            nome="Senza scheda", reparto=self.reparto_a, famiglia="Solventi",
        )
        self.con_scheda_recente = ProdottoChimico.objects.create(
            nome="Con scheda recente", reparto=self.reparto_a, famiglia="Acidi",
        )
        SchedaSicurezza.objects.create(
            prodotto=self.con_scheda_recente, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        self.con_scheda_vecchia = ProdottoChimico.objects.create(
            nome="Con scheda vecchia", reparto=self.reparto_b, famiglia="Solventi",
        )
        scheda_vecchia = SchedaSicurezza.objects.create(
            prodotto=self.con_scheda_vecchia, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        from datetime import timedelta

        from django.utils import timezone

        from .models import SCADENZA_SDS_GIORNI

        vecchia_data = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI + 10)
        SchedaSicurezza.objects.filter(pk=scheda_vecchia.pk).update(data_caricamento=vecchia_data)

    def test_filtro_reparto(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"reparto": self.reparto_b.pk})
        self.assertContains(resp, "Con scheda vecchia")
        self.assertNotContains(resp, "Senza scheda")
        self.assertNotContains(resp, "Con scheda recente")

    def test_filtro_famiglia(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"famiglia": "Acidi"})
        self.assertContains(resp, "Con scheda recente")
        self.assertNotContains(resp, "Senza scheda")

    def test_filtro_stato_senza_scheda(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"stato": "senza_scheda"})
        self.assertContains(resp, "Senza scheda")
        self.assertNotContains(resp, "Con scheda recente")
        self.assertNotContains(resp, "Con scheda vecchia")

    def test_filtro_stato_con_scheda(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"stato": "con_scheda"})
        self.assertContains(resp, "Con scheda recente")
        self.assertContains(resp, "Con scheda vecchia")
        self.assertNotContains(resp, "Senza scheda")

    def test_filtro_stato_da_rivedere(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"stato": "da_rivedere"})
        self.assertContains(resp, "Con scheda vecchia")
        self.assertNotContains(resp, "Con scheda recente")
        self.assertNotContains(resp, "Senza scheda")

    def test_badge_da_rivedere_visibile_in_lista(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"))
        self.assertContains(resp, "Da rivedere")
```

This test file's existing imports already include `TestCase`, `reverse`, `User`, `Reparto`, and a `_valid_pdf_upload()` helper (used by other Fase-1 test classes in the same file) — reuse those, do not redefine them.

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views.ProdottoListFiltriTest --settings=config.settings.test -v 2`
Expected: FAIL on `test_filtro_reparto` and the others — the view ignores the `reparto`/`famiglia`/`stato` GET params today, so all products appear regardless of filter (assertions on absence fail).

- [ ] **Step 3: Write minimal implementation**

Replace the `prodotto_list` function body in `django_app/schede_sicurezza/views.py` (currently lines 70-92):

```python
@login_required
def prodotto_list(request):
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    from anagrafica.models import Reparto

    query = request.GET.get("q", "").strip()
    reparto_id = request.GET.get("reparto", "").strip()
    famiglia = request.GET.get("famiglia", "").strip()
    stato = request.GET.get("stato", "").strip()

    qs = (
        ProdottoChimico.objects.filter(attivo=True)
        .select_related("reparto")
        .order_by("nome")
    )
    if query:
        qs = qs.filter(
            Q(nome__icontains=query)
            | Q(fornitore__icontains=query)
            | Q(codice_prodotto__icontains=query)
        )
    if reparto_id:
        qs = qs.filter(reparto_id=reparto_id)
    if famiglia:
        qs = qs.filter(famiglia=famiglia)
    if stato == "senza_scheda":
        qs = qs.filter(pk__in=prodotti_senza_scheda_corrente())
    elif stato == "con_scheda":
        qs = qs.filter(schede__is_corrente=True).distinct()
    elif stato == "da_rivedere":
        soglia = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI)
        qs = qs.filter(schede__is_corrente=True, schede__data_caricamento__lt=soglia).distinct()

    return render(request, "schede_sicurezza/pages/prodotto_list.html", {
        "prodotti": qs,
        "query": query,
        "reparto_selezionato": reparto_id,
        "famiglia_selezionata": famiglia,
        "stato_selezionato": stato,
        "reparti_options": Reparto.objects.filter(is_active=True).order_by("nome"),
        "famiglie_options": (
            ProdottoChimico.objects.exclude(famiglia="")
            .values_list("famiglia", flat=True).distinct().order_by("famiglia")
        ),
        "can_gestire": _can_gestire(request),
    })
```

At the top of `django_app/schede_sicurezza/views.py`, the current imports are:

```python
from __future__ import annotations

import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from .models import PresaVisioneScheda, ProdottoChimico, SchedaSicurezza
from .reports import matrice_presa_visione, prodotti_senza_scheda_corrente
from .services.ingestion import estrai_sds
from .services.qr import genera_qr_png
```

Add `timedelta` and `timezone`, and the `SCADENZA_SDS_GIORNI` constant:

```python
from __future__ import annotations

import csv
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from .models import SCADENZA_SDS_GIORNI, PresaVisioneScheda, ProdottoChimico, SchedaSicurezza
from .reports import matrice_presa_visione, prodotti_senza_scheda_corrente
from .services.ingestion import estrai_sds
from .services.qr import genera_qr_png
```

In `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_list.html`, replace the search form (currently lines 59-63):

```html
  <form method="get" style="display:flex;gap:6px;align-items:center;">
    <input type="text" name="q" value="{{ query }}" placeholder="Cerca nome, fornitore, codice..."
           style="padding:7px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;min-width:240px;">
    <button type="submit" class="ss-btn ss-btn-sm">Cerca</button>
  </form>
```

with:

```html
  <form method="get" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
    <input type="text" name="q" value="{{ query }}" placeholder="Cerca nome, fornitore, codice..."
           style="padding:7px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;min-width:220px;">
    <select name="reparto" style="padding:7px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;">
      <option value="">Tutti i reparti</option>
      {% for r in reparti_options %}
        <option value="{{ r.pk }}" {% if reparto_selezionato == r.pk|stringformat:"s" %}selected{% endif %}>{{ r.nome }}</option>
      {% endfor %}
    </select>
    <select name="famiglia" style="padding:7px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;">
      <option value="">Tutte le famiglie</option>
      {% for f in famiglie_options %}
        <option value="{{ f }}" {% if famiglia_selezionata == f %}selected{% endif %}>{{ f }}</option>
      {% endfor %}
    </select>
    <select name="stato" style="padding:7px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;">
      <option value="">Tutti gli stati</option>
      <option value="con_scheda" {% if stato_selezionato == "con_scheda" %}selected{% endif %}>Con scheda</option>
      <option value="senza_scheda" {% if stato_selezionato == "senza_scheda" %}selected{% endif %}>Senza scheda</option>
      <option value="da_rivedere" {% if stato_selezionato == "da_rivedere" %}selected{% endif %}>Da rivedere</option>
    </select>
    <button type="submit" class="ss-btn ss-btn-sm">Filtra</button>
  </form>
```

In the same template, replace the "Scheda corrente" table cell (currently lines 83-89):

```html
              <td>
                {% if prodotto.scheda_corrente %}
                  <span class="ss-badge ss-badge-current">v.{{ prodotto.scheda_corrente.versione|default:"?" }}</span>
                {% else %}
                  <span class="ss-badge ss-badge-missing">Nessuna scheda</span>
                {% endif %}
              </td>
```

with:

```html
              <td>
                {% if prodotto.scheda_corrente %}
                  <span class="ss-badge ss-badge-current">v.{{ prodotto.scheda_corrente.versione|default:"?" }}</span>
                  {% if prodotto.scheda_corrente.scaduta %}
                    <span class="ss-badge ss-badge-missing" title="Nessun aggiornamento da oltre 36 mesi">Da rivedere</span>
                  {% endif %}
                {% else %}
                  <span class="ss-badge ss-badge-missing">Nessuna scheda</span>
                {% endif %}
              </td>
```

Note: `prodotto.scheda_corrente` in the template calls the `scheda_corrente()` method twice per row (once for the version badge, once for `.scaduta`) — this is an existing Django template behavior (method calls aren't cached across `{% if %}` blocks) and matches the pre-existing pattern already in this template; not a new inefficiency introduced by this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views.ProdottoListFiltriTest --settings=config.settings.test -v 2`
Expected: `Ran 6 tests ... OK`

- [ ] **Step 5: Run the full tests_views.py file to confirm no regression, then commit**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views --settings=config.settings.test --keepdb -v 2`
Expected: all tests OK (existing Fase-1 view tests + 6 new ones).

```bash
git add django_app/schede_sicurezza/views.py django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_list.html django_app/schede_sicurezza/tests_views.py
git commit -m "feat(schede-sicurezza): filtri reparto/famiglia/stato + badge scadenza in lista prodotti"
```

---

### Task 3: Editing manuale campi estratti

**Files:**
- Modify: `django_app/schede_sicurezza/views.py:154-204` (the `prodotto_detail` function)
- Modify: `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_detail.html`
- Modify: `django_app/schede_sicurezza/tests_views.py` (append test class)

**Interfaces:**
- Consumes: nothing new from earlier tasks in this plan (independent of Task 1/2).
- Produces: `prodotto_detail` POST now branches on `request.POST.get("form_type")`; no new URL, no new interface consumed by later tasks.

- [ ] **Step 1: Write the failing test**

Append to `django_app/schede_sicurezza/tests_views.py`:

```python
class ModificaCampiEstrattiTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        self.admin = User.objects.create_user(username="admin_edit_campi", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_modifica_campi_estratti_aggiorna_scheda_corrente(self):
        url = reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk])
        resp = self.client.post(url, {
            "form_type": "modifica_campi_estratti",
            "pittogrammi": "GHS02, GHS07",
            "frasi_h": "H225,  H319",
            "frasi_p": "P210",
            "classificazione_clp": "Liquido infiammabile categoria 2.",
            "dpi_testo": "Guanti e occhiali protettivi.",
            "primo_soccorso": "Sciacquare abbondantemente con acqua.",
            "incompatibilita": "Incompatibile con ossidanti forti.",
        })
        self.assertEqual(resp.status_code, 302)
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, ["GHS02", "GHS07"])
        self.assertEqual(self.scheda.frasi_h, ["H225", "H319"])
        self.assertEqual(self.scheda.frasi_p, ["P210"])
        self.assertEqual(self.scheda.classificazione_clp, "Liquido infiammabile categoria 2.")
        self.assertEqual(self.scheda.dpi_testo, "Guanti e occhiali protettivi.")
        self.assertEqual(self.scheda.primo_soccorso, "Sciacquare abbondantemente con acqua.")
        self.assertEqual(self.scheda.incompatibilita, "Incompatibile con ossidanti forti.")

    def test_modifica_campi_estratti_ignora_virgole_vuote(self):
        url = reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk])
        self.client.post(url, {
            "form_type": "modifica_campi_estratti",
            "pittogrammi": "GHS02,, ,GHS07,",
            "frasi_h": "", "frasi_p": "",
            "classificazione_clp": "", "dpi_testo": "", "primo_soccorso": "", "incompatibilita": "",
        })
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, ["GHS02", "GHS07"])
        self.assertEqual(self.scheda.frasi_h, [])

    def test_modifica_campi_estratti_richiede_permesso_gestisci(self):
        utente = User.objects.create_user(username="senza_permesso_edit", password="x")
        self.client.force_login(utente)
        url = reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk])
        resp = self.client.post(url, {"form_type": "modifica_campi_estratti", "pittogrammi": "GHS02"})
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, [])

    def test_sezione_modifica_campi_presente_nel_dettaglio_con_scheda(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk]))
        self.assertContains(resp, "Modifica campi estratti")

    def test_sezione_modifica_campi_assente_senza_scheda_corrente(self):
        prodotto_senza = ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        resp = self.client.get(reverse("schede_sicurezza:prodotto_detail", args=[prodotto_senza.pk]))
        self.assertNotContains(resp, "Modifica campi estratti")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views.ModificaCampiEstrattiTest --settings=config.settings.test -v 2`
Expected: FAIL — the POST with `form_type=modifica_campi_estratti` today falls through to the existing upload branch, which requires `pdf` and errors with "Seleziona un file PDF." (redirects without touching `scheda.pittogrammi`), so the field assertions fail.

- [ ] **Step 3: Write minimal implementation**

In `django_app/schede_sicurezza/views.py`, the `prodotto_detail` function's POST handling currently starts like this (lines 162-166):

```python
    if request.method == "POST":
        if not _can_gestire(request):
            messages.error(request, "Accesso non autorizzato.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        pdf_file = request.FILES.get("pdf")
```

Replace it with (inserting the new branch before the existing upload logic, both still under the shared `_can_gestire` guard):

```python
    if request.method == "POST":
        if not _can_gestire(request):
            messages.error(request, "Accesso non autorizzato.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        if request.POST.get("form_type") == "modifica_campi_estratti":
            scheda_corrente = prodotto.scheda_corrente()
            if scheda_corrente is None:
                messages.error(request, "Nessuna scheda corrente da modificare.")
                return redirect("schede_sicurezza:prodotto_detail", pk=pk)

            def _parse_lista(valore: str) -> list[str]:
                return [v.strip() for v in valore.split(",") if v.strip()]

            scheda_corrente.pittogrammi = _parse_lista(request.POST.get("pittogrammi", ""))
            scheda_corrente.frasi_h = _parse_lista(request.POST.get("frasi_h", ""))
            scheda_corrente.frasi_p = _parse_lista(request.POST.get("frasi_p", ""))
            scheda_corrente.classificazione_clp = request.POST.get("classificazione_clp", "").strip()
            scheda_corrente.dpi_testo = request.POST.get("dpi_testo", "").strip()
            scheda_corrente.primo_soccorso = request.POST.get("primo_soccorso", "").strip()
            scheda_corrente.incompatibilita = request.POST.get("incompatibilita", "").strip()
            scheda_corrente.save(update_fields=[
                "pittogrammi", "frasi_h", "frasi_p", "classificazione_clp",
                "dpi_testo", "primo_soccorso", "incompatibilita",
            ])
            messages.success(request, "Campi estratti aggiornati.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        pdf_file = request.FILES.get("pdf")
```

The rest of the existing POST branch (upload logic) is unchanged.

In `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_detail.html`, add a new section immediately after the "Carica nuova versione SDS" block (currently ending at line 63, right before the "Storico versioni" block):

```html
  {% if can_gestire and scheda_corrente %}
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px;">
      <div style="font-weight:700;margin-bottom:10px;">Modifica campi estratti</div>
      <form method="post" style="display:flex;flex-direction:column;gap:10px;">
        {% csrf_token %}
        <input type="hidden" name="form_type" value="modifica_campi_estratti">

        <label>Pittogrammi (separati da virgola)
          <input type="text" name="pittogrammi" value="{{ scheda_corrente.pittogrammi|join:', ' }}"
                 style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">
        </label>
        <div style="display:flex;gap:12px;">
          <label style="flex:1;">Frasi H (separate da virgola)
            <input type="text" name="frasi_h" value="{{ scheda_corrente.frasi_h|join:', ' }}"
                   style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">
          </label>
          <label style="flex:1;">Frasi P (separate da virgola)
            <input type="text" name="frasi_p" value="{{ scheda_corrente.frasi_p|join:', ' }}"
                   style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">
          </label>
        </div>
        <label>Classificazione CLP
          <textarea name="classificazione_clp" rows="2"
                    style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">{{ scheda_corrente.classificazione_clp }}</textarea>
        </label>
        <label>DPI (testo)
          <textarea name="dpi_testo" rows="2"
                    style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">{{ scheda_corrente.dpi_testo }}</textarea>
        </label>
        <label>Primo soccorso
          <textarea name="primo_soccorso" rows="2"
                    style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">{{ scheda_corrente.primo_soccorso }}</textarea>
        </label>
        <label>Incompatibilità
          <textarea name="incompatibilita" rows="2"
                    style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">{{ scheda_corrente.incompatibilita }}</textarea>
        </label>
        <div>
          <button type="submit" style="padding:9px 18px;background:#1d4ed8;color:#fff;border:none;border-radius:10px;font-weight:700;cursor:pointer;">Salva campi</button>
        </div>
      </form>
    </div>
  {% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views.ModificaCampiEstrattiTest --settings=config.settings.test -v 2`
Expected: `Ran 5 tests ... OK`

- [ ] **Step 5: Run the full tests_views.py file to confirm no regression, then commit**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views --settings=config.settings.test --keepdb -v 2`
Expected: all tests OK.

```bash
git add django_app/schede_sicurezza/views.py django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_detail.html django_app/schede_sicurezza/tests_views.py
git commit -m "feat(schede-sicurezza): editing manuale campi estratti nel dettaglio prodotto"
```

---

### Task 4: CTA reparto mancante

**Files:**
- Modify: `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_form.html:23-30`
- Modify: `django_app/schede_sicurezza/tests_views.py` (append test class)

**Interfaces:**
- Consumes: the existing `reparti` context variable already passed by `prodotto_form` view (no view change needed — the queryset is already there).
- Produces: nothing consumed by later tasks (final UI task).

- [ ] **Step 1: Write the failing test**

Append to `django_app/schede_sicurezza/tests_views.py`:

```python
class RepartoMancanteCtaTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_reparto_cta", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_link_aree_list_presente_senza_reparti(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_nuovo"))
        self.assertContains(resp, reverse("anagrafica:aree_list"))

    def test_select_normale_con_almeno_un_reparto(self):
        Reparto.objects.create(nome="Produzione")
        resp = self.client.get(reverse("schede_sicurezza:prodotto_nuovo"))
        self.assertNotContains(resp, reverse("anagrafica:aree_list"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views.RepartoMancanteCtaTest --settings=config.settings.test -v 2`
Expected: FAIL on `test_link_aree_list_presente_senza_reparti` — the template today renders only an empty `<select>`, no link to `anagrafica:aree_list`.

- [ ] **Step 3: Write minimal implementation**

In `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_form.html`, replace the "Reparto *" label block (currently lines 23-30):

```html
    <label>Reparto *
      <select name="reparto" required style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">
        <option value="">Seleziona…</option>
        {% for r in reparti %}
          <option value="{{ r.pk }}" {% if prodotto.reparto_id == r.pk %}selected{% endif %}>{{ r.nome }}</option>
        {% endfor %}
      </select>
    </label>
```

with:

```html
    <label>Reparto *
      {% if reparti %}
        <select name="reparto" required style="width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:8px;">
          <option value="">Seleziona…</option>
          {% for r in reparti %}
            <option value="{{ r.pk }}" {% if prodotto.reparto_id == r.pk %}selected{% endif %}>{{ r.nome }}</option>
          {% endfor %}
        </select>
      {% else %}
        <div style="padding:10px;border:1px solid #fde68a;background:#fffbeb;border-radius:8px;font-size:13px;color:#92400e;">
          Nessun reparto disponibile. <a href="{% url 'anagrafica:aree_list' %}" style="color:#1d4ed8;font-weight:700;">Vai a Reparti &amp; Aree</a> per crearne uno.
        </div>
      {% endif %}
    </label>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views.RepartoMancanteCtaTest --settings=config.settings.test -v 2`
Expected: `Ran 2 tests ... OK`

- [ ] **Step 5: Run the full tests_views.py file to confirm no regression, then commit**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views --settings=config.settings.test --keepdb -v 2`
Expected: all tests OK.

```bash
git add django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_form.html django_app/schede_sicurezza/tests_views.py
git commit -m "feat(schede-sicurezza): CTA verso Reparti & Aree quando la select reparto e' vuota"
```

---

### Task 5: Suite completa, CHANGELOG, README

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing (terminal task).

- [ ] **Step 1: Run the full `schede_sicurezza` suite**

Run: `python django_app\manage.py test django_app.schede_sicurezza --settings=config.settings.test --keepdb -v 2`
Expected: all tests green (Fase 1 + Report Compliance + this plan's new tests: 3 model + 6 filtri + 5 editing + 2 CTA = 16 new tests on top of the 43 already passing before this plan).

- [ ] **Step 2: Confirm no pending migrations**

Run: `python django_app\manage.py makemigrations schede_sicurezza --check --dry-run --settings=config.settings.test`
Expected: `No changes detected in app 'schede_sicurezza'` (the `scaduta` property is Python-only, no DB field added).

- [ ] **Step 3: Update CHANGELOG.md**

Add a new bullet under `### Added` in `CHANGELOG.md`, in the `## [Unreleased]` section, immediately after the existing "Report compliance" bullet for this app:

```markdown
- **`schede_sicurezza` · UI/UX Fase 1 (filtri lista, badge scadenze, editing campi, CTA reparto)** (`django_app/schede_sicurezza/models.py` [+`SCADENZA_SDS_GIORNI`, +`SchedaSicurezza.scaduta`], `views.py` [`prodotto_list` +filtri reparto/famiglia/stato, `prodotto_detail` +branch editing campi estratti], `templates/schede_sicurezza/pages/prodotto_list.html` [+filtri, +badge "Da rivedere"], `templates/schede_sicurezza/pages/prodotto_detail.html` [+sezione "Modifica campi estratti"], `templates/schede_sicurezza/pages/prodotto_form.html` [+CTA verso `anagrafica:aree_list` se nessun reparto], `tests.py`/`tests_views.py` [+16 test]): terzo sotto-progetto della "Fase 2". Soglia scadenza SDS 36 mesi (`SCADENZA_SDS_GIORNI`, unica fonte di verità per badge e filtro `stato=da_rivedere`); filtro `stato=senza_scheda` riusa `reports.prodotti_senza_scheda_corrente()`. Editing manuale di pittogrammi/frasi H-P/classificazione CLP/DPI testo/primo soccorso/incompatibilità sulla scheda corrente, per correggere estrazioni PyMuPDF parziali. Nessuna nuova gestione reparti: si linka la pagina `anagrafica:aree_list` già esistente. Nessuna migrazione, nessun nuovo permesso ACL. Spec `docs/superpowers/specs/2026-07-10-schede-sicurezza-ui-ux-fase1-design.md`.
```

- [ ] **Step 4: Update README.md**

In the `<details>` block for module 22 (`schede_sicurezza`) in `README.md`, append a new bullet after the existing "Report compliance" line:

```markdown
- **Filtri lista** (reparto/famiglia/stato scheda) e **badge "Da rivedere"** (SDS non aggiornata da oltre 36 mesi, soglia unica riusata anche nel filtro); **editing manuale** dei campi curati (pittogrammi/frasi H-P/CLP/DPI/primo soccorso/incompatibilità) nel dettaglio prodotto, per correggere estrazioni PyMuPDF parziali; CTA verso `anagrafica:aree_list` quando non esiste ancora nessun reparto
```

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(schede-sicurezza): changelog + readme per UI/UX Fase 1"
```

## Post-plan verification

```bash
python django_app\manage.py test django_app.schede_sicurezza --settings=config.settings.test --keepdb -v 2
python django_app\manage.py makemigrations schede_sicurezza --check --dry-run --settings=config.settings.test
```

Expected: all tests green, `No changes detected in app 'schede_sicurezza'`.
