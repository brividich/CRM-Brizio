# Export PDF + Excel per le viste tabellari di anagrafica

Data: 2026-07-12
Stato: design approvato, pronto per il piano di implementazione

## Obiettivo

Rendere disponibile un'estrazione **PDF** e **Excel** su tutte le viste elenco del
modulo `anagrafica` (~20 liste), con un impianto unico e riusabile invece di export
puntuali scritti a mano vista per vista.

## Contesto (cosa esiste già)

- **PDF**: `core/pdf.py` — `PdfTheme.from_branding()` (logo su disco, colore primario,
  nome portale), `build_styles`, `make_document`, `data_table`, `header_footer_callback`.
  L'helper tabellare `_report_table_pdf(title, headers, rows)` esiste in
  `assets/views.py:13217` ma non è condiviso.
- **Excel**: `core/excel_export.py` — `build_xlsx_bytes` / `make_xlsx_response`
  (header navy, larghezze auto, freeze panes, autofiltro; titolo opzionale in A1).
  `core/exporting.py` — `export_rows_response` + `ExportMixin` (CSV/XLSX generico).
- **Audit**: `core/audit.py::log_action(request, azione, modulo, dettaglio)` → modello
  `core.models.AuditLog` (DB Django), già usato dagli export di anomalie e assenze.
- In anagrafica esistono export puntuali (ratei, retribuzioni globali, visite mediche,
  skill matrix, attestati): **restano invariati**, non vengono migrati.
- Le liste di anagrafica filtrano **inline dentro la view**: non esistono helper di
  filtro riusabili.

## Approccio scelto (ibrido)

Registry di specifiche di export + endpoint unico parametrico. Le view non vengono
riscritte; il filtro viene estratto in un helper condiviso **solo** dove è non banale,
per evitare divergenza tra ciò che l'utente vede e ciò che esporta.

### Componenti

1. **`core/table_pdf.py` (nuovo)** — promozione di `_report_table_pdf` da `assets/views.py`
   a helper condiviso. `assets` lo importa; comportamento invariato. Aggiunta: il
   sottotitolo dell'header accoglie la riga filtri/conteggio.
2. **`core/excel_export.py` (esteso)** — blocco intestazione documento riusabile
   (vedi «Template Excel»). Nuovi parametri opzionali; le chiamate esistenti (DPI,
   retribuzioni, skill matrix) continuano a funzionare senza modifiche.
3. **`anagrafica/exports.py` (nuovo)** — registry `EXPORT_SPECS: dict[str, ExportSpec]`:

   ```python
   ExportSpec(
       key="dipendenti",
       title="Elenco dipendenti",
       permission=...,                       # stesso gate ACL della view
       columns=[("Nominativo", "nominativo"), ("Reparto", "reparto"), ...],
       dataset=lambda request, scope: ...,   # righe filtrate (scope="filtered") o complete ("full")
       filters_label=lambda request: ...,    # es. 'Reparto: Officina · Ricerca: "ross"'
   )
   ```

4. **Endpoint unico** `anagrafica:export` →
   `/anagrafica/esporta/<key>/?format=xlsx|pdf&scope=filtered|full`
   Risolve la spec, applica il gate ACL, costruisce le righe, scrive l'audit,
   restituisce il file.
5. **`anagrafica/components/_export_menu.html` (nuovo)** — pulsante «Esporta ▾» nel
   toolbar tabella, incluso nelle pagine elenco passando la chiave della lista.

### Anti-drift dei filtri

- Filtri **non banali** (dipendenti, ex-dipendenti, documenti, formazione corsi/sessioni,
  ratei): estratti dalla view in un helper condiviso chiamato **sia dalla view sia dalla
  spec**.
- Filtri **banali** (mansioni, aree, ruoli aziendali/operativi, qualifiche, sessioni
  qualifica, categorie corso, fattori/esposizioni rischio, istruttori, piani, onboarding,
  MPQ clienti): la spec li replica in poche righe.

### Liste non piatte

`aree_list` (reparti con aree annidate) e simili vengono **appiattite**: una riga per
area, con la colonna «Reparto» ripetuta.

## Contenuto dell'export

- **Colonne**: quelle della tabella a schermo (nessuna colonna extra non visibile).
- **Righe**: tutte quelle del risultato, non solo la pagina corrente.
- **Scope**: doppia scelta — `filtered` (querystring corrente propagata) e `full`.

## Template PDF

Riusa il template HUB esistente (`core/pdf.py`), identico a assets/anomalie:

- Header: logo (o monogramma di fallback) + titolo report.
- Sottotitolo: `Generato il GG-MM-AAAA · <filtri applicati> · N righe`.
- Corpo: `data_table` landscape, righe alternate, header di tabella ripetuto a ogni pagina.
- Footer: paginazione e branding.

## Template Excel

Intestazione documento riusabile, alimentata dallo stesso `PdfTheme.from_branding()`
(coerenza visiva tra i due formati):

```
A1  [logo]   NOVICROM HUB
A3           Elenco dipendenti                  ← titolo, bold 14, navy
A4           Generato il 12-07-2026 da L. Bova
A5           Filtri: Reparto = Officina · Ricerca "ross" · 37 righe
A7  | Nominativo | Reparto | ... |              ← header navy, freeze + autofilter
```

Restano larghezze auto, freeze panes e autofiltro già presenti; si aggiunge l'area di
stampa con riga di header ripetuta.

Firma estesa (parametri nuovi tutti opzionali):

```python
make_xlsx_response(*, filename, columns, rows, sheet_title="Dati", title=None,
                   subtitle=None, filters_label=None, logo=True)
```

## UI

`_export_menu.html`: pulsante «Esporta ▾» accanto alla ricerca nel toolbar tabella,
con quattro voci — Excel (filtrato), Excel (tutto), PDF (filtrato), PDF (tutto).
Il link «filtrato» propaga la querystring corrente della pagina.

## ACL e audit

- **ACL**: nessun permesso nuovo. L'endpoint riusa lo **stesso gate della view**
  corrispondente, dichiarato nella `ExportSpec`. La rotta va mappata in
  `API_ACL_GATE_PATHS` / binding canonico, altrimenti `ACL_STRICT_CANONICAL` la nega
  ai non-superuser.
- **Audit**: ogni export scrive una riga via `log_action()` →
  `core.models.AuditLog` (DB Django, consultabile dal pannello log di admin_portale):
  `azione="export"`, `modulo="anagrafica"`,
  `dettaglio={lista, formato, scope, n_righe, filtri}`.
- **Privacy**: i dati dei dipendenti sono dati personali; nessuna colonna sensibile
  aggiuntiva rispetto a quanto già visibile a schermo.

## Test (`anagrafica/tests_exports.py`)

1. Per ogni chiave del registry: `format=xlsx` e `format=pdf` → 200 con content-type corretto.
2. `scope=filtered` rispetta i filtri della querystring (numero di righe atteso).
3. Utente senza il permesso della vista → 403.
4. L'export scrive una riga di `AuditLog` con `n_righe` e filtri.
5. Regressione: gli export esistenti (DPI, retribuzioni, skill matrix) continuano a
   funzionare dopo l'estensione di `core/excel_export.py`.

## Fuori scope

- Export CSV (già coperto altrove dove serve).
- Migrazione degli export puntuali esistenti di anagrafica al nuovo registry.
- Export di viste non tabellari (dashboard, form, dettagli).
