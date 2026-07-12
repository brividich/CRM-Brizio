# Export PDF + Excel per le viste tabellari di anagrafica — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dare a ogni vista elenco del modulo `anagrafica` un'estrazione PDF e Excel coerente col branding HUB, con filtri della vista rispettati, gate ACL della vista e audit.

**Architecture:** Un registry di `ExportSpec` in `anagrafica/exports.py` alimenta un endpoint unico `/anagrafica/esporta/<key>/?format=xlsx|pdf&scope=filtered|full`. Il PDF riusa il template HUB (`core/pdf.py`) tramite un helper condiviso promosso da `assets/views.py` a `core/table_pdf.py`; l'Excel riusa `core/excel_export.py` esteso con un blocco intestazione documento (logo + titolo + data/autore + filtri). Un componente template `_export_menu.html` aggiunge il pulsante «Esporta ▾» alle pagine elenco.

**Tech Stack:** Django 5.2, reportlab (via `core/pdf.py`), openpyxl (via `core/excel_export.py`), template Django SSR + CSS `fmd-*`, ACL v2, `core.audit.log_action` → `core.models.AuditLog`.

**Spec:** `docs/superpowers/specs/2026-07-12-anagrafica-export-pdf-excel-design.md`

## Global Constraints

- Nessuna nuova dipendenza: `reportlab` e `openpyxl` sono già in `requirements.txt`.
- Retrocompatibilità obbligatoria: `core/excel_export.py::make_xlsx_response` e `build_xlsx_bytes` sono già usati (DPI, retribuzioni, skill matrix). Tutti i parametri nuovi sono **opzionali**, nessuna firma esistente cambia.
- `assets/views.py` continua a produrre gli stessi PDF: `_report_table_pdf` viene sostituito da un import da `core.table_pdf`, non riscritto.
- ACL: nessun permesso nuovo. La rotta di export deve essere registrata nel binding canonico di anagrafica (`anagrafica/acl_bootstrap.py`), altrimenti `ACL_STRICT_CANONICAL=True` (attivo in prod) la nega ai non-superuser.
- Audit obbligatorio su ogni export: `log_action(request, "export", "anagrafica", {...})`.
- Nessun dato reale nei test: solo fixture sintetiche.
- Comando test (PowerShell, dalla root del repo):
  `python django_app\manage.py test anagrafica.tests_exports --settings=config.settings.test --keepdb`
  (se il label non risolve, usare `django_app.anagrafica.tests_exports`).
- **A fine lavoro**: aggiornare `CHANGELOG.md` (sezione `[Unreleased]`, tutti i file toccati) e `README.md` (sezione anagrafica: nuova funzionalità di export).

---

## File Structure

**Creati:**
- `django_app/core/table_pdf.py` — helper condiviso «tabella → PDF template HUB».
- `django_app/anagrafica/exports.py` — dataclass `ExportSpec`, registry `EXPORT_SPECS`, costruzione risposta + audit.
- `django_app/anagrafica/templates/anagrafica/components/_export_menu.html` — pulsante «Esporta ▾».
- `django_app/anagrafica/tests_exports.py` — test dell'endpoint, ACL, audit, filtri.

**Modificati:**
- `django_app/core/excel_export.py` — intestazione documento (logo/titolo/sottotitolo/filtri).
- `django_app/core/test_excel_export.py` — test dell'intestazione + regressione firma esistente.
- `django_app/assets/views.py:13217` — `_report_table_pdf` diventa import da `core.table_pdf`.
- `django_app/anagrafica/views.py` — estrazione helper filtri per le liste non banali + view `export_view`.
- `django_app/anagrafica/urls.py` — rotta `esporta/<key>/`.
- `django_app/anagrafica/acl_bootstrap.py` — binding canonico della rotta di export.
- Template delle pagine elenco di anagrafica — include del menu export.

---

### Task 1: Helper PDF condiviso (`core/table_pdf.py`)

**Files:**
- Create: `django_app/core/table_pdf.py`
- Modify: `django_app/assets/views.py` (rimuovere `_report_table_pdf`, righe 13217-13258, e importarlo da `core.table_pdf`)
- Test: `django_app/core/tests_table_pdf.py`

**Interfaces:**
- Consumes: `core.pdf` (`PdfTheme`, `build_styles`, `make_document`, `data_table`, `header_footer_callback`).
- Produces: `core.table_pdf.render_table_pdf(*, title: str, headers: list[str], rows: list[list], subtitle: str = "") -> bytes`

- [ ] **Step 1: Scrivere il test che fallisce**

`django_app/core/tests_table_pdf.py`:

```python
from django.test import TestCase

from core.table_pdf import render_table_pdf


class RenderTablePdfTests(TestCase):
    def test_returns_pdf_bytes(self):
        data = render_table_pdf(
            title="Elenco di prova",
            headers=["Nome", "Reparto"],
            rows=[["Mario Bianchi", "Officina"], ["Anna Verdi", "Qualita"]],
            subtitle="Generato il 12-07-2026 · 2 righe",
        )
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 800)

    def test_empty_rows_still_produce_pdf(self):
        data = render_table_pdf(title="Vuoto", headers=["Nome"], rows=[])
        self.assertTrue(data.startswith(b"%PDF"))
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run: `python django_app\manage.py test core.tests_table_pdf --settings=config.settings.test --keepdb`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.table_pdf'`

- [ ] **Step 3: Implementare `core/table_pdf.py`**

Il corpo è quello di `assets/views.py::_report_table_pdf` (righe 13217-13258), con in più il parametro `subtitle`:

```python
"""Render di una tabella (headers + rows) in PDF col template HUB.

Promosso da ``assets/views.py::_report_table_pdf`` per essere riusato da tutti i
moduli (anagrafica, assets, ...). Le decisioni grafiche vengono dal branding via
``core.pdf.PdfTheme``.
"""
from __future__ import annotations

import io
from html import escape

from django.utils import timezone
from reportlab.platypus import Paragraph

from core.pdf import (
    PdfTheme,
    build_styles,
    data_table,
    header_footer_callback,
    make_document,
)


def render_table_pdf(*, title: str, headers: list, rows: list, subtitle: str = "") -> bytes:
    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = io.BytesIO()
    doc = make_document(buf, title=title, landscape=True)
    elements: list = []

    if not rows:
        elements.append(Paragraph("Nessun record.", styles["body"]))
    else:
        page_w = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
        col_w = page_w / max(len(headers), 1)
        table_rows = [
            [Paragraph(escape(str(header)), styles["table_header"]) for header in headers],
            *[
                [
                    Paragraph(escape("" if value is None else str(value)).replace("\n", "<br/>"), styles["cell"])
                    for value in row
                ]
                for row in rows
            ],
        ]
        elements.append(
            data_table(
                table_rows,
                theme,
                col_widths=[col_w] * len(headers),
                repeat_rows=1,
                extra_style=[
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ],
            )
        )

    if not subtitle:
        subtitle = f"Generato il {timezone.localdate().strftime('%d-%m-%Y')}"
    draw = header_footer_callback(theme, title=title.upper(), subtitle=subtitle)
    doc.build(elements, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run: `python django_app\manage.py test core.tests_table_pdf --settings=config.settings.test --keepdb`
Expected: PASS (2 test)

- [ ] **Step 5: Far usare l'helper condiviso ad assets**

In `django_app/assets/views.py`: cancellare la funzione `_report_table_pdf` (righe 13217-13258) e aggiungere accanto agli altri import da `core`:

```python
from core.table_pdf import render_table_pdf as _report_table_pdf
```

Le tre call-site (`asset_list_export`, `workorder_list_export`, `work_machine_export_pdf`) restano invariate: la firma posizionale `(title, headers, rows)` non è compatibile con `render_table_pdf` (keyword-only), quindi aggiornarle a keyword, es.:

```python
pdf_bytes = _report_table_pdf(title="Inventario asset", headers=_ASSET_EXPORT_HEADERS, rows=rows)
```

- [ ] **Step 6: Verificare la non-regressione di assets**

Run: `python django_app\manage.py test assets.tests.AssetExportTests --settings=config.settings.test --keepdb`
(se il nome della classe non esiste, eseguire l'intero `assets.tests` filtrando: `python django_app\manage.py test assets --settings=config.settings.test --keepdb`)
Expected: PASS — in particolare `test_asset_list_export_pdf_returns_shared_template_pdf`

- [ ] **Step 7: Commit**

```powershell
git add django_app/core/table_pdf.py django_app/core/tests_table_pdf.py django_app/assets/views.py
git commit -m "refactor(core): helper condiviso render_table_pdf (promosso da assets)"
```

---

### Task 2: Intestazione documento nell'Excel (`core/excel_export.py`)

**Files:**
- Modify: `django_app/core/excel_export.py`
- Test: `django_app/core/test_excel_export.py`

**Interfaces:**
- Consumes: `core.pdf.PdfTheme.from_branding()` (per `logo_path`, `primary`, nome portale).
- Produces:
  `build_xlsx_bytes(*, columns, rows, sheet_title="Dati", title=None, subtitle=None, filters_label=None, logo=True) -> bytes`
  `make_xlsx_response(*, filename, columns, rows, sheet_title="Dati", title=None, subtitle=None, filters_label=None, logo=True) -> HttpResponse`

Layout prodotto quando `title` è valorizzato:

```
A1  [logo]  NOVICROM HUB      ← riga brand (logo immagine se disponibile, altrimenti solo nome)
A3  Elenco dipendenti          ← title, bold 14, navy 0C2545
A4  Generato il 12-07-2026 da L. Bova   ← subtitle
A5  Filtri: Reparto = Officina · 37 righe ← filters_label
A7  | Nominativo | Reparto |    ← header navy (freeze + autofilter da qui)
```

Senza `title` il file resta come oggi (header in riga 1): retrocompatibilità.

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in `django_app/core/test_excel_export.py`:

```python
from io import BytesIO

from openpyxl import load_workbook

from core.excel_export import build_xlsx_bytes


class XlsxDocumentHeaderTests(TestCase):
    def test_header_block_contains_title_subtitle_and_filters(self):
        data = build_xlsx_bytes(
            columns=["Nominativo", "Reparto"],
            rows=[["Mario Bianchi", "Officina"]],
            title="Elenco dipendenti",
            subtitle="Generato il 12-07-2026 da Mario Rossi",
            filters_label="Filtri: Reparto = Officina · 1 righe",
        )
        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws["A3"].value, "Elenco dipendenti")
        self.assertEqual(ws["A4"].value, "Generato il 12-07-2026 da Mario Rossi")
        self.assertEqual(ws["A5"].value, "Filtri: Reparto = Officina · 1 righe")
        self.assertEqual(ws["A7"].value, "Nominativo")
        self.assertEqual(ws["A8"].value, "Mario Bianchi")
        self.assertEqual(ws.freeze_panes, "A8")

    def test_without_title_header_stays_on_first_row(self):
        data = build_xlsx_bytes(columns=["Nominativo"], rows=[["Mario Bianchi"]])
        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws["A1"].value, "Nominativo")
        self.assertEqual(ws["A2"].value, "Mario Bianchi")
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `python django_app\manage.py test core.test_excel_export --settings=config.settings.test --keepdb`
Expected: FAIL — `A3` è `None` (oggi il titolo va in A1 e l'header in riga 3)

- [ ] **Step 3: Implementare il blocco intestazione**

Riscrivere `build_xlsx_bytes` in `django_app/core/excel_export.py` (mantenendo il resto del file):

```python
def _brand_header(ws, *, title, subtitle, filters_label, logo):
    """Scrive il blocco intestazione (righe 1..5) e ritorna la riga di header tabella."""
    from openpyxl.styles import Font

    from core.pdf import PdfTheme

    theme = PdfTheme.from_branding()
    navy = "0C2545"

    ws.cell(row=1, column=2, value=getattr(theme, "portal_name", "") or "NOVICROM HUB").font = Font(
        bold=True, size=11, color=navy
    )
    if logo and getattr(theme, "logo_path", None):
        try:
            from openpyxl.drawing.image import Image as XlImage

            img = XlImage(theme.logo_path)
            img.height = 36
            img.width = int(img.width * (36 / max(img.height, 1))) if img.height else 90
            ws.add_image(img, "A1")
            ws.row_dimensions[1].height = 30
        except Exception:  # logo non disegnabile: si prosegue senza
            pass

    ws.cell(row=3, column=1, value=str(title)).font = Font(bold=True, size=14, color=navy)
    if subtitle:
        ws.cell(row=4, column=1, value=str(subtitle)).font = Font(size=10, color="5B6B7C")
    if filters_label:
        ws.cell(row=5, column=1, value=str(filters_label)).font = Font(size=10, color="5B6B7C")
    return 7


def build_xlsx_bytes(
    *,
    columns,
    rows,
    sheet_title: str = "Dati",
    title: str | None = None,
    subtitle: str | None = None,
    filters_label: str | None = None,
    logo: bool = True,
) -> bytes:
    """Costruisce il file .xlsx (bytes). `columns`: intestazioni; `rows`: iterabile di righe.

    Con `title` valorizzato scrive il blocco intestazione HUB (logo, titolo, sottotitolo,
    filtri) e la tabella parte dalla riga 7; senza `title` l'header resta in riga 1.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    columns = list(columns)
    rows = [list(r) for r in rows]

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title or "Dati")[:31]

    header_row = 1
    if title:
        header_row = _brand_header(
            ws, title=title, subtitle=subtitle, filters_label=filters_label, logo=logo
        )

    header_fill = PatternFill("solid", fgColor="0C2545")
    header_font = Font(bold=True, color="FFFFFF")
    for c, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=c, value=str(col))
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")

    r = header_row
    for row in rows:
        r += 1
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)

    for c, col in enumerate(columns, start=1):
        maxlen = len(str(col))
        for row in rows:
            if c - 1 < len(row) and row[c - 1] is not None:
                maxlen = max(maxlen, len(str(row[c - 1])))
        ws.column_dimensions[get_column_letter(c)].width = min(60, max(10, maxlen + 2))

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if rows and columns:
        last = get_column_letter(len(columns))
        ws.auto_filter.ref = f"A{header_row}:{last}{header_row + len(rows)}"
        ws.print_title_rows = f"{header_row}:{header_row}"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

E propagare i nuovi parametri in `make_xlsx_response`:

```python
def make_xlsx_response(
    *,
    filename: str,
    columns,
    rows,
    sheet_title: str = "Dati",
    title: str | None = None,
    subtitle: str | None = None,
    filters_label: str | None = None,
    logo: bool = True,
) -> HttpResponse:
    """Risposta HTTP di download .xlsx. La view resta responsabile di ACL/filtri."""
    data = build_xlsx_bytes(
        columns=columns,
        rows=rows,
        sheet_title=sheet_title,
        title=title,
        subtitle=subtitle,
        filters_label=filters_label,
        logo=logo,
    )
    safe_name = (filename or "export.xlsx").replace('"', "")
    response = HttpResponse(data, content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    response["Content-Length"] = str(len(data))
    return response
```

Nota: se `PdfTheme` non espone `portal_name`, usare l'attributo effettivo del branding (verificare `core/pdf.py` righe 101-155) — il fallback `"NOVICROM HUB"` copre il caso mancante.

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `python django_app\manage.py test core.test_excel_export --settings=config.settings.test --keepdb`
Expected: PASS (test nuovi + quelli preesistenti nel file)

- [ ] **Step 5: Verificare la non-regressione dei consumatori esistenti**

Run: `python django_app\manage.py test dpi --settings=config.settings.test --keepdb`
Expected: PASS (l'export conformità DPI usa `make_xlsx_response` senza i nuovi parametri)

- [ ] **Step 6: Commit**

```powershell
git add django_app/core/excel_export.py django_app/core/test_excel_export.py
git commit -m "feat(core): intestazione documento HUB (logo/titolo/filtri) negli export xlsx"
```

---

### Task 3: Registry `ExportSpec` + endpoint unico + audit (con lista pilota «mansioni»)

**Files:**
- Create: `django_app/anagrafica/exports.py`
- Create: `django_app/anagrafica/tests_exports.py`
- Modify: `django_app/anagrafica/views.py` (nuova view `export_view`)
- Modify: `django_app/anagrafica/urls.py`
- Modify: `django_app/anagrafica/acl_bootstrap.py`

**Interfaces:**
- Consumes: `core.table_pdf.render_table_pdf` (Task 1), `core.excel_export.make_xlsx_response` (Task 2), `core.audit.log_action`.
- Produces:
  - `anagrafica.exports.ExportSpec` (dataclass: `key`, `title`, `sheet_title`, `columns: list[tuple[str, str]]`, `dataset: Callable[[HttpRequest, str], list[dict]]`, `permission: Callable[[HttpRequest], bool]`, `filters_label: Callable[[HttpRequest], str]`)
  - `anagrafica.exports.EXPORT_SPECS: dict[str, ExportSpec]`
  - `anagrafica.exports.build_export_response(request, key: str, fmt: str, scope: str) -> HttpResponse`
  - URL name `anagrafica:export` → `/anagrafica/esporta/<key>/`

- [ ] **Step 1: Scrivere i test che falliscono**

`django_app/anagrafica/tests_exports.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Mansione
from core.models import AuditLog

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExportEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser("admin_export", "admin@example.invalid", "x")
        cls.plain = User.objects.create_user("utente_export", "u@example.invalid", "x")
        Mansione.objects.create(nome="Addetto verniciatura", livello_rischio="ALTO")
        Mansione.objects.create(nome="Impiegato ufficio", livello_rischio="BASSO")

    def _url(self, key, **params):
        url = reverse("anagrafica:export", args=[key])
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def test_xlsx_export_returns_spreadsheet(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="xlsx"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], XLSX_CT)
        self.assertIn("mansioni", resp["Content-Disposition"])

    def test_pdf_export_returns_pdf(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="pdf"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_filtered_scope_respects_querystring(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="xlsx", scope="filtered", q="verniciatura"))
        self.assertEqual(resp.status_code, 200)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 1)

    def test_full_scope_ignores_querystring(self):
        self.client.force_login(self.admin)
        self.client.get(self._url("mansioni", format="xlsx", scope="full", q="verniciatura"))
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 2)

    def test_audit_row_written(self):
        self.client.force_login(self.admin)
        self.client.get(self._url("mansioni", format="pdf"))
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.modulo, "anagrafica")
        self.assertEqual(log.dettaglio.get("lista"), "mansioni")
        self.assertEqual(log.dettaglio.get("formato"), "pdf")

    def test_unknown_key_is_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("non-esiste", format="xlsx"))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(self._url("mansioni", format="xlsx"))
        self.assertIn(resp.status_code, (302, 403))
```

Nota per l'implementatore: verificare i nomi dei campi di `core.models.AuditLog` (`azione`, `modulo`, `dettaglio`) e di `Mansione` (`nome`, `livello_rischio`) prima di eseguire; adeguare le fixture se i campi obbligatori sono altri.

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `python django_app\manage.py test anagrafica.tests_exports --settings=config.settings.test --keepdb`
Expected: FAIL — `NoReverseMatch: 'export' is not a valid view function or pattern name`

- [ ] **Step 3: Implementare `anagrafica/exports.py`**

```python
"""Registry degli export tabellari di anagrafica (PDF + Excel).

Ogni vista elenco dichiara una ``ExportSpec``; l'endpoint unico
``anagrafica:export`` risolve la chiave, applica il gate ACL della vista,
costruisce le righe, scrive l'audit e restituisce il file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.http import Http404, HttpRequest, HttpResponse
from django.utils import timezone

from core.audit import log_action
from core.excel_export import make_xlsx_response
from core.table_pdf import render_table_pdf


@dataclass(frozen=True)
class ExportSpec:
    key: str
    title: str
    columns: list[tuple[str, str]]          # (etichetta, chiave nel dict riga)
    dataset: Callable[[HttpRequest, str], list[dict]]   # (request, scope) -> righe
    permission: Callable[[HttpRequest], bool] = lambda request: True
    filters_label: Callable[[HttpRequest], str] = lambda request: ""
    sheet_title: str = "Dati"


EXPORT_SPECS: dict[str, ExportSpec] = {}


def register(spec: ExportSpec) -> ExportSpec:
    EXPORT_SPECS[spec.key] = spec
    return spec


def _actor_name(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    return (getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "") or "").strip()


def build_export_response(request: HttpRequest, key: str, fmt: str, scope: str) -> HttpResponse:
    spec = EXPORT_SPECS.get(key)
    if spec is None:
        raise Http404("Export non disponibile.")

    fmt = (fmt or "xlsx").strip().lower()
    if fmt not in ("xlsx", "pdf"):
        fmt = "xlsx"
    scope = (scope or "filtered").strip().lower()
    if scope not in ("filtered", "full"):
        scope = "filtered"

    rows_data = list(spec.dataset(request, scope))
    headers = [label for label, _accessor in spec.columns]
    rows = [[row.get(accessor, "") for _label, accessor in spec.columns] for row in rows_data]

    filters = spec.filters_label(request) if scope == "filtered" else "Tutti i record"
    today = timezone.localdate().strftime("%d-%m-%Y")
    stamp = timezone.localdate().strftime("%Y%m%d")
    subtitle = f"Generato il {today} da {_actor_name(request)}".strip()
    filters_label = f"{filters} · {len(rows)} righe" if filters else f"{len(rows)} righe"

    log_action(request, "export", "anagrafica", {
        "lista": spec.key,
        "formato": fmt,
        "scope": scope,
        "n_righe": len(rows),
        "filtri": filters,
    })

    if fmt == "pdf":
        pdf_bytes = render_table_pdf(
            title=spec.title,
            headers=headers,
            rows=rows,
            subtitle=f"{subtitle} · {filters_label}",
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{spec.key}_{stamp}.pdf"'
        return response

    return make_xlsx_response(
        filename=f"{spec.key}_{stamp}.xlsx",
        columns=headers,
        rows=rows,
        sheet_title=spec.sheet_title or spec.title[:31],
        title=spec.title,
        subtitle=subtitle,
        filters_label=filters_label,
    )
```

In coda allo stesso file, la **spec pilota «mansioni»** (filtro banale, replicato qui — vedi `views.py::mansioni_list` righe 5167-5183):

```python
def _mansioni_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import Mansione

    qs = Mansione.objects.all().order_by("nome")
    if scope == "filtered":
        q_text = (request.GET.get("q") or "").strip()
        filtro_rischio = (request.GET.get("rischio") or "").strip().upper()
        solo_rischio = request.GET.get("solo_rischio") == "1"
        if q_text:
            qs = qs.filter(nome__icontains=q_text)
        if filtro_rischio in dict(Mansione.LIVELLO_RISCHIO_CHOICES):
            qs = qs.filter(livello_rischio=filtro_rischio)
        if solo_rischio:
            qs = qs.exclude(livello_rischio="")
    return [
        {
            "nome": m.nome or "",
            "categoria": m.get_categoria_display() if hasattr(m, "get_categoria_display") else "",
            "livello_rischio": m.get_livello_rischio_display() if m.livello_rischio else "",
            "descrizione": m.descrizione or "",
            "attiva": "Si" if getattr(m, "is_active", True) else "No",
        }
        for m in qs
    ]


def _mansioni_filters(request: HttpRequest) -> str:
    parts = []
    if (request.GET.get("q") or "").strip():
        parts.append(f'Ricerca: "{request.GET["q"].strip()}"')
    if (request.GET.get("rischio") or "").strip():
        parts.append(f'Rischio: {request.GET["rischio"].strip()}')
    if request.GET.get("solo_rischio") == "1":
        parts.append("Solo mansioni di rischio")
    return " · ".join(parts)


register(ExportSpec(
    key="mansioni",
    title="Catalogo mansioni",
    sheet_title="Mansioni",
    columns=[
        ("Mansione", "nome"),
        ("Categoria", "categoria"),
        ("Livello di rischio", "livello_rischio"),
        ("Descrizione", "descrizione"),
        ("Attiva", "attiva"),
    ],
    dataset=_mansioni_rows,
    filters_label=_mansioni_filters,
))
```

- [ ] **Step 4: Aggiungere la view e la rotta**

In `django_app/anagrafica/views.py`, accanto alle altre view (import in cima al file, insieme agli altri import di modulo):

```python
from anagrafica.exports import build_export_response


@login_required
def export_view(request, key: str):
    """Endpoint unico di export delle liste di anagrafica (PDF/Excel)."""
    from anagrafica.exports import EXPORT_SPECS

    spec = EXPORT_SPECS.get(key)
    if spec is None:
        raise Http404("Export non disponibile.")
    if not spec.permission(request):
        return HttpResponseForbidden("Permessi insufficienti.")
    return build_export_response(
        request,
        key,
        request.GET.get("format", "xlsx"),
        request.GET.get("scope", "filtered"),
    )
```

(verificare che `Http404` e `HttpResponseForbidden` siano già importati in `views.py`; in caso contrario aggiungerli agli import di `django.http`.)

In `django_app/anagrafica/urls.py`, dopo la rotta `index`:

```python
    # Export tabellari (PDF/Excel) — endpoint unico parametrico
    path("esporta/<str:key>/", views.export_view, name="export"),
```

- [ ] **Step 5: Registrare il binding ACL canonico**

In `django_app/anagrafica/acl_bootstrap.py`, aggiungere la rotta `anagrafica:export` alla mappa dei binding canonici di anagrafica (funzione `_bootstrap_anagrafica_canonical`, riga 198), associandola al permesso di lettura di anagrafica già usato dalle liste (stesso `permission_id` delle rotte `*_list`). Senza questo binding, con `ACL_STRICT_CANONICAL=True` la rotta risponde 403 a tutti i non-superuser.

- [ ] **Step 6: Eseguire i test e verificare che passino**

Run: `python django_app\manage.py test anagrafica.tests_exports --settings=config.settings.test --keepdb`
Expected: PASS (7 test)

- [ ] **Step 7: Commit**

```powershell
git add django_app/anagrafica/exports.py django_app/anagrafica/tests_exports.py django_app/anagrafica/views.py django_app/anagrafica/urls.py django_app/anagrafica/acl_bootstrap.py
git commit -m "feat(anagrafica): registry ExportSpec + endpoint unico export PDF/Excel (pilota mansioni)"
```

---

### Task 4: Componente UI «Esporta ▾»

**Files:**
- Create: `django_app/anagrafica/templates/anagrafica/components/_export_menu.html`
- Modify: `django_app/anagrafica/templates/anagrafica/pages/mansioni_list.html` (toolbar, riga ~74)
- Test: `django_app/anagrafica/tests_exports.py` (aggiungere `ExportMenuTemplateTests`)

**Interfaces:**
- Consumes: URL name `anagrafica:export` (Task 3).
- Produces: componente includibile con `{% include "anagrafica/components/_export_menu.html" with export_key="mansioni" %}`.

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `django_app/anagrafica/tests_exports.py`:

```python
class ExportMenuTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser("admin_menu", "admin2@example.invalid", "x")

    def test_mansioni_list_shows_export_links(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:mansioni_list") + "?q=vernic")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Esporta", html)
        self.assertIn("/anagrafica/esporta/mansioni/?format=xlsx&amp;scope=full", html)
        self.assertIn("format=pdf", html)
        self.assertIn("scope=filtered", html)
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run: `python django_app\manage.py test anagrafica.tests_exports.ExportMenuTemplateTests --settings=config.settings.test --keepdb`
Expected: FAIL — "Esporta" non presente nell'HTML

- [ ] **Step 3: Creare il componente**

`django_app/anagrafica/templates/anagrafica/components/_export_menu.html`:

```django
{# Menu di export per le liste di anagrafica.
   Uso: {% include "anagrafica/components/_export_menu.html" with export_key="mansioni" %}
   Il link "filtrato" propaga la querystring corrente della pagina. #}
{% with base_url="/anagrafica/esporta/"|add:export_key|add:"/" %}
<details class="fmd-export">
  <summary class="fmd-btn fmd-btn-ghost" title="Esporta la lista">
    <svg class="fmd-ico"><use href="#i-download"/></svg>Esporta
  </summary>
  <div class="fmd-export-menu" role="menu">
    <a role="menuitem" href="{{ base_url }}?format=xlsx&amp;scope=filtered{% if request.GET.urlencode %}&amp;{{ request.GET.urlencode }}{% endif %}">Excel — risultati filtrati</a>
    <a role="menuitem" href="{{ base_url }}?format=xlsx&amp;scope=full">Excel — tutto</a>
    <a role="menuitem" href="{{ base_url }}?format=pdf&amp;scope=filtered{% if request.GET.urlencode %}&amp;{{ request.GET.urlencode }}{% endif %}">PDF — risultati filtrati</a>
    <a role="menuitem" href="{{ base_url }}?format=pdf&amp;scope=full">PDF — tutto</a>
  </div>
</details>
{% endwith %}
```

Stile: aggiungere in `django_app/core/static/core/css/fm-table-enhanced.css` (in coda), usando solo token del tema esistenti — nessuna palette nuova:

```css
/* Menu export delle liste (componente _export_menu.html) */
.fmd-export { position: relative; display: inline-block; }
.fmd-export > summary { list-style: none; cursor: pointer; }
.fmd-export > summary::-webkit-details-marker { display: none; }
.fmd-export-menu {
  position: absolute; right: 0; top: calc(100% + 6px); z-index: 30;
  min-width: 220px; padding: 6px;
  background: var(--surface, #fff); color: var(--text, #0c2545);
  border: 1px solid var(--border, #dfe5ec); border-radius: 10px;
  box-shadow: 0 10px 24px rgba(12, 37, 69, .14);
}
.fmd-export-menu a { display: block; padding: 8px 10px; border-radius: 8px; text-decoration: none; color: inherit; font-size: 13px; }
.fmd-export-menu a:hover { background: var(--surface-2, #f1f5f9); }
```

Se l'icona `#i-download` non esiste in `anagrafica/components/_fm_icons.html`, usare un'icona già presente (es. `#i-clipboard`) invece di aggiungerne una nuova.

- [ ] **Step 4: Includere il componente nella pagina mansioni**

In `django_app/anagrafica/templates/anagrafica/pages/mansioni_list.html`, dentro la toolbar, subito prima di `<span class="fmd-spacer"></span>` (riga 74):

```django
      {% include "anagrafica/components/_export_menu.html" with export_key="mansioni" %}
```

- [ ] **Step 5: Eseguire i test e verificare che passino**

Run: `python django_app\manage.py test anagrafica.tests_exports --settings=config.settings.test --keepdb`
Expected: PASS (8 test)

- [ ] **Step 6: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/components/_export_menu.html django_app/anagrafica/templates/anagrafica/pages/mansioni_list.html django_app/core/static/core/css/fm-table-enhanced.css django_app/anagrafica/tests_exports.py
git commit -m "feat(anagrafica): menu Esporta (Excel/PDF, filtrato o tutto) nel toolbar liste"
```

---

### Task 5: Lista «dipendenti» con estrazione del filtro dalla view (anti-drift)

**Files:**
- Modify: `django_app/anagrafica/views.py:516-587` (`dipendenti_list`)
- Modify: `django_app/anagrafica/exports.py`
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendenti_list.html`
- Test: `django_app/anagrafica/tests_exports.py`

**Interfaces:**
- Produces: `anagrafica.views.build_dipendenti_rows(request, *, apply_filters: bool = True) -> list[dict]` — righe già filtrate e ordinate, con le stesse chiavi usate oggi dal template (`id`, `nome`, `cognome`, `matricola`, `reparto`, `aliasusername`, `ruolo`/`mansione`, `attivo`).
- Consumes: `ExportSpec`/`register` (Task 3).

Questa è la lista dove il filtro **non** va replicato: la view fa fetch legacy, esclusione cessati, fallback reparto da `DipendenteAnagraficaAziendale.area`, ricerca su nome/cognome/alias/matricola, filtri reparto/area/tipologia_contratto e ordinamento. Duplicarlo garantirebbe drift.

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `django_app/anagrafica/tests_exports.py`. L'anagrafica legge dal DB legacy: in test l'elenco può essere vuoto, quindi il secondo test verifica la **coerenza** tra view ed export, non un conteggio assoluto.

```python
from django.test import RequestFactory


class DipendentiExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser("admin_dip", "admin3@example.invalid", "x")

    def test_dipendenti_export_xlsx_ok_and_audited(self):
        self.client.force_login(self.admin)
        url = reverse("anagrafica:export", args=["dipendenti"]) + "?format=xlsx&scope=filtered&reparto=Officina"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], XLSX_CT)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("lista"), "dipendenti")
        self.assertIn("Officina", log.dettaglio.get("filtri", ""))

    def test_export_dataset_matches_view_helper(self):
        from anagrafica.exports import EXPORT_SPECS
        from anagrafica.views import build_dipendenti_rows

        request = RequestFactory().get("/anagrafica/dipendenti/?q=ross")
        request.user = self.admin
        view_rows = build_dipendenti_rows(request, apply_filters=True)
        export_rows = EXPORT_SPECS["dipendenti"].dataset(request, "filtered")
        self.assertEqual(len(view_rows), len(export_rows))
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `python django_app\manage.py test anagrafica.tests_exports.DipendentiExportTests --settings=config.settings.test --keepdb`
Expected: FAIL — `ImportError: cannot import name 'build_dipendenti_rows'` / chiave `dipendenti` assente dal registry

- [ ] **Step 3: Estrarre l'helper dalla view**

In `django_app/anagrafica/views.py`, spostare il blocco righe 517-587 di `dipendenti_list` in una funzione modulo:

```python
def build_dipendenti_rows(request, *, apply_filters: bool = True) -> list[dict]:
    """Righe dell'elenco dipendenti (legacy + fallback reparto), filtrate e ordinate.

    Fonte unica condivisa tra la view `dipendenti_list` e l'export
    (`anagrafica.exports`): il filtro non va duplicato altrove.
    """
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(deduplicate=True)
    cessati_ids = _cessati_legacy_ids()
    rows = [row for row in rows if int(row.get("id") or 0) not in cessati_ids]

    _ids_no_reparto = [int(r.get("id") or 0) for r in rows if not str(r.get("reparto") or "").strip()]
    if _ids_no_reparto:
        _az_area_map = dict(
            DipendenteAnagraficaAziendale.objects
            .filter(legacy_anagrafica_id__in=_ids_no_reparto)
            .exclude(area="")
            .values_list("legacy_anagrafica_id", "area")
        )
        for row in rows:
            if not str(row.get("reparto") or "").strip():
                lid = int(row.get("id") or 0)
                if lid in _az_area_map:
                    row["reparto"] = _az_area_map[lid]

    if apply_filters:
        q = request.GET.get("q", "").strip()
        reparto = request.GET.get("reparto", "").strip()
        area_filter = request.GET.get("area", "").strip()
        contratto_filter = request.GET.get("tipologia_contratto", "").strip()

        if q:
            q_norm = q.casefold()
            rows = [
                row for row in rows
                if any(
                    q_norm in value.casefold()
                    for value in [
                        str(row.get("nome") or "").strip(),
                        str(row.get("cognome") or "").strip(),
                        str(row.get("aliasusername") or "").strip(),
                        str(row.get("matricola") or "").strip(),
                    ] if value
                )
            ]
        if reparto:
            rows = [row for row in rows if str(row.get("reparto") or "").strip().casefold() == reparto.casefold()]
        if area_filter or contratto_filter:
            az_qs = DipendenteAnagraficaAziendale.objects.all()
            if area_filter:
                az_qs = az_qs.filter(area__iexact=area_filter)
            if contratto_filter:
                az_qs = az_qs.filter(tipologia_contratto=contratto_filter)
            allowed_ids = set(az_qs.values_list("legacy_anagrafica_id", flat=True))
            rows = [row for row in rows if int(row.get("id") or 0) in allowed_ids]

    rows.sort(key=lambda row: (
        str(row.get("cognome") or "").strip().casefold(),
        str(row.get("nome") or "").strip().casefold(),
        str(row.get("aliasusername") or "").strip().casefold(),
        int(row.get("id") or 0),
    ))
    return rows
```

E in `dipendenti_list` sostituire il blocco estratto con:

```python
@login_required
def dipendenti_list(request):
    q = request.GET.get("q", "").strip()
    reparto = request.GET.get("reparto", "").strip()
    area_filter = request.GET.get("area", "").strip()
    contratto_filter = request.GET.get("tipologia_contratto", "").strip()

    rows_all = build_dipendenti_rows(request, apply_filters=False)
    reparti_list = sorted({str(r.get("reparto") or "").strip() for r in rows_all if str(r.get("reparto") or "").strip()})
    n_totale = len(rows_all)
    rows = build_dipendenti_rows(request, apply_filters=True)
    # ... da qui in poi il resto della view resta invariato (aree_list, user_map,
    #     arricchimento righe, Paginator, foto, timbri, render)
```

**Attenzione:** `n_totale` e `reparti_list` erano calcolati sulle righe **pre-filtro**; la sostituzione sopra preserva quel comportamento. Non cambiare il context passato al template.

- [ ] **Step 4: Registrare la spec `dipendenti`**

In coda a `django_app/anagrafica/exports.py`:

```python
def _dipendenti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.views import build_dipendenti_rows

    rows = build_dipendenti_rows(request, apply_filters=(scope == "filtered"))
    return [
        {
            "cognome": str(r.get("cognome") or "").strip(),
            "nome": str(r.get("nome") or "").strip(),
            "matricola": str(r.get("matricola") or "").strip(),
            "reparto": str(r.get("reparto") or "").strip(),
            "ruolo": str(r.get("ruolo") or r.get("mansione") or "").strip(),
            "username": str(r.get("aliasusername") or "").strip(),
            "attivo": "Si" if (r.get("attivo") is None or bool(r.get("attivo"))) else "No",
        }
        for r in rows
    ]


def _dipendenti_filters(request: HttpRequest) -> str:
    parts = []
    for param, label in (("q", "Ricerca"), ("reparto", "Reparto"), ("area", "Area"), ("tipologia_contratto", "Contratto")):
        value = (request.GET.get(param) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return " · ".join(parts)


register(ExportSpec(
    key="dipendenti",
    title="Elenco dipendenti",
    sheet_title="Dipendenti",
    columns=[
        ("Cognome", "cognome"),
        ("Nome", "nome"),
        ("Matricola", "matricola"),
        ("Reparto", "reparto"),
        ("Ruolo / mansione", "ruolo"),
        ("Username", "username"),
        ("Attivo", "attivo"),
    ],
    dataset=_dipendenti_rows,
    filters_label=_dipendenti_filters,
))
```

L'import di `build_dipendenti_rows` è **locale alla funzione** per evitare import circolari `views ↔ exports` (stesso pattern già usato in `tickets/views.py` per i modelli esterni).

- [ ] **Step 5: Aggiungere il menu export alla pagina**

In `django_app/anagrafica/templates/anagrafica/pages/dipendenti_list.html`, nella toolbar dei filtri (stessa posizione del pattern di Task 4):

```django
      {% include "anagrafica/components/_export_menu.html" with export_key="dipendenti" %}
```

- [ ] **Step 6: Eseguire i test e verificare che passino**

Run: `python django_app\manage.py test anagrafica.tests_exports --settings=config.settings.test --keepdb`
Expected: PASS

Run (non-regressione della lista): `python django_app\manage.py test anagrafica.tests --settings=config.settings.test --keepdb`
Expected: PASS (nessuna regressione su `dipendenti_list`)

- [ ] **Step 7: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/exports.py django_app/anagrafica/tests_exports.py django_app/anagrafica/templates/anagrafica/pages/dipendenti_list.html
git commit -m "feat(anagrafica): export dipendenti (helper filtri condiviso view/export)"
```

---

### Task 6-9: Rollout sulle liste restanti

Ogni task segue **la stessa ricetta** (non è un rimando: la ricetta è qui, per esteso):

1. Aprire la view della lista in `django_app/anagrafica/views.py` (o `views_mpq.py`) e leggere: parametri `request.GET` usati, queryset/ordinamento, gate ACL (`_check_hr_permission`, `is_legacy_admin`, `_can_view_formazione`, …).
2. Aprire il template della pagina e prendere **le colonne mostrate a schermo** come colonne dell'export.
3. In `anagrafica/exports.py` aggiungere `_<lista>_rows(request, scope)`, `_<lista>_filters(request)` e la `register(ExportSpec(...))`, con `permission=` uguale al gate della view (es. `permission=lambda request: _check_hr_permission(request)` importato localmente).
   - Se il filtro della view è **non banale** (più di ~3 parametri o logica su fonti multiple), estrarlo prima dalla view in `build_<lista>_rows(request, *, apply_filters=True)` come in Task 5, e richiamarlo dalla spec.
   - Liste annidate (es. `aree_list`: reparti → aree): appiattire, ripetendo la colonna «Reparto» su ogni riga area.
4. Includere `{% include "anagrafica/components/_export_menu.html" with export_key="<key>" %}` nella toolbar del template.
5. Aggiungere in `tests_exports.py` un test parametrico per la chiave: `format=xlsx` → 200 + content-type xlsx; `format=pdf` → 200 + `%PDF`; utente senza permesso → 403.
6. Eseguire `python django_app\manage.py test anagrafica.tests_exports --settings=config.settings.test --keepdb` e committare.

**Task 6 — Anagrafiche di supporto** (filtri banali):
`aree` (`aree_list`, appiattita reparto→area), `ruoli_aziendali` (`ruoli_aziendali_list`), `ruoli_operativi` (`ruoli_operativi_list`), `qualifiche` (`qualifiche_list`), `qualifica_sessioni` (`qualifica_sessioni_list`).
Commit: `feat(anagrafica): export liste anagrafiche di supporto (aree, ruoli, qualifiche)`

**Task 7 — Formazione**:
`formazione_piani`, `formazione_corsi`, `formazione_istruttori`, `formazione_sessioni`, `fattori_rischio`, `categorie_corso`, `esposizioni_rischio`.
`formazione_corsi` e `formazione_sessioni` hanno filtri non banali: estrarre `build_formazione_corsi_rows` / `build_formazione_sessioni_rows` come in Task 5. Gate ACL: `_can_view_formazione`.
Commit: `feat(anagrafica): export liste formazione (piani, corsi, istruttori, sessioni, rischi)`

**Task 8 — HR e documenti**:
`ex_dipendenti` (riusa `build_dipendenti_rows`? no: `ex_dipendenti_list` ha una sua fonte — estrarre `build_ex_dipendenti_rows`), `documenti` (gate `is_admin or _check_hr_permission`, filtri cartella/dipendente; escludere sempre le cartelle `solo_admin` per i non-superuser, **come fa la view**), `onboarding`, `ratei`.
Attenzione privacy: nessuna colonna oltre a quelle già visibili a schermo.
Commit: `feat(anagrafica): export liste HR (ex dipendenti, documenti, onboarding, ratei)`

**Task 9 — MPQ (MOD.128)**:
`mpq_clienti` (`views_mpq.mpq_cliente_list`) ed eventuali altre liste MPQ presenti in `anagrafica/urls.py` sotto `mod128/`. Gate ACL: quello già usato in `views_mpq`.
Commit: `feat(anagrafica): export liste MPQ (MOD.128)`

---

### Task 10: Documentazione e chiusura

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 1: Aggiornare `CHANGELOG.md`**

Sotto `[Unreleased]`, elencare tutti i file creati/modificati e descrivere: export PDF+Excel su tutte le liste di anagrafica, helper condiviso `core/table_pdf.py`, intestazione documento negli xlsx, endpoint unico `/anagrafica/esporta/<key>/`, audit su `AuditLog`.

- [ ] **Step 2: Aggiornare `README.md`**

Nella sezione/`<details>` di anagrafica: nuova funzionalità «Esporta» sulle liste (Excel/PDF, risultati filtrati o elenco completo), con nota che ogni export è tracciato in audit.

- [ ] **Step 3: Verifica finale**

Run: `python django_app\manage.py test anagrafica --settings=config.settings.test --keepdb`
Expected: PASS

Run: `python django_app\manage.py check --settings=config.settings.test`
Expected: `System check identified no issues`

- [ ] **Step 4: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs: export PDF/Excel liste anagrafica (CHANGELOG + README)"
```

---

## Note per chi implementa

- Le liste di anagrafica **non sono tutte tabelle HTML**: alcune sono griglie di card (es. mansioni). L'export le tratta comunque come tabella piatta del dataset sottostante — è voluto.
- `ACL_STRICT_CANONICAL=True` è attivo in produzione: se il binding di Task 3 Step 5 manca, l'export funziona solo per i superuser. È l'errore più probabile di questo lavoro.
- Non toccare gli export già esistenti di anagrafica (ratei, retribuzioni globali, visite mediche, skill matrix, attestati): restano dove sono.
