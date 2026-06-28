# Piano — Fruibilità portale con tool open-source

Integrazioni open-source per migliorare la **fruibilità** (UX, form, dashboard,
onboarding) **e l'affidabilità** di NOVICROM HUB, **senza tradire lo stack**:
Django SSR + HTMX, niente SPA/build step, on-premise.

## Principi invariabili
- **Self-host** di ogni asset (JS/CSS/font) in `static/` — **niente CDN a runtime**
  (offline-safe, CSP-friendly, no supply-chain a runtime). Versione **pinnata**.
- **Drop-in**: librerie usabili con un solo `<script>`/`<link>`, **nessun build npm**.
- **Progressive enhancement**: la pagina funziona anche senza JS dove possibile;
  i widget degradano al controllo nativo.
- **Accessibilità** e coerenza col design system (navy/cyan/orange, font Outfit).
- Una voce alla volta, **un commit per voce**, con test/guardrail dove ha senso.

## Stato dello stack (ricognizione 2026-06-28)
- HTMX ovunque (ok). `django-htmx` per lo script. `openpyxl 3.1.5`, `reportlab`,
  `pymupdf`, `pillow`, `qrcode` **già installati**.
- **CDN a runtime da eliminare**: Chart.js 4.4.4 (`rilevazione_incidenti`),
  FullCalendar 6.1.11 (`assets`) e 6.1.17 + locales (`assenze`), frappe-gantt 0.6.1
  (`assets`), SortableJS 1.15.2 (`admin_portale`), html2canvas 1.4.1
  (`automazioni`, `core`), Google Fonts Outfit (`base.html` + template di stampa).
- React + Babel-in-browser in `anomalie` (fuori linea; ridurre, non ampliare).
- Asset globali → `django_app/core/static/core/` (qui `vendor/`).

---

## Ondata A — Igiene/affidabilità: self-host dei CDN (nessun cambio UX)
- [x] **A1. Vendor delle librerie JS/CSS già usate** ✅ (commit in corso) — vendorizzate in `core/static/core/vendor/` e repointate; guardrail `core/test_vendor_assets.py`. Fix latenti emersi: rimosso il `<link>` CSS FullCalendar 6 (404, FC6 inietta la CSS dal JS) e corretto `frappe-gantt.umd.js` → `frappe-gantt.min.js` (il file `.umd.js` non esiste nella 0.6.1: la gantt era rotta a runtime). in `core/static/core/vendor/`
  (versioni identiche a quelle attuali → zero cambi di comportamento) e repoint dei
  template a `{% static %}`: Chart.js 4.4.4, FullCalendar 6.1.11 (JS+CSS),
  FullCalendar 6.1.17 (JS) + locales-all, frappe-gantt 0.6.1 (JS+CSS),
  SortableJS 1.15.2, html2canvas 1.4.1. **Guardrail**: test che nessun template
  referenzi più `cdn.jsdelivr`/`unpkg`/`cdnjs` per gli script/style.
- [x] **A2. Self-host font Outfit** ✅ — CSS + 2 woff2 (Outfit è variable font → un
  solo file per latin/latin-ext copre tutti i pesi) in `core/static/core/vendor/outfit/`;
  repoint di `base.html` + 6 template di stampa. Guardrail esteso ai Google Fonts.

## Ondata B — Form & input (alto ROI sulla data-entry)
- [x] **B1. Tom Select** ✅ — vendorizzato; init globale `core/js/tomselect-init.js`
  su `select.js-searchable` (anche post-HTMX, fallback nativo, opt-in via classe).
  Piloti: report conformità DPI (dipendente + categoria), assegnazione ticket
  (tecnico + fornitore). Per abilitarlo su altri select basta aggiungere la classe
  `js-searchable` (+ opz. `data-placeholder`).
- [x] **B2. Flatpickr** ✅ — vendorizzato (JS+CSS+locale IT); init globale
  `core/js/flatpickr-init.js` su `input.js-datepicker` (e `js-daterange` per il
  range), valore inviato sempre ISO `Y-m-d` (compat Django), mostrato `d/m/Y`,
  anche post-HTMX, fallback a `<input type=date>` nativo. Pilota: filtro data di
  audit_log. Estendibile aggiungendo `js-datepicker` a qualsiasi input data.

## Ondata C — Visualizzazione dati
- [x] **C1. Chart.js riusabile** ✅ — helper di brand `core/js/chart-helper.js`
  (`NHUB.barChart/lineChart/chart`, palette navy/cyan/orange, lifecycle: ridisegnare
  distrugge l'istanza precedente). Pilota: **anomalie_statistiche** — distribuzione
  per mese ora anche come **grafico a barre** (oltre alla tabella), dai dati già
  fetchati. Riusabile su altre dashboard includendo Chart.js + helper e chiamando
  `NHUB.barChart(canvas, {labels, values, label})`.
- [x] **C2. Export Excel (openpyxl)** ✅ — util condivisa `core/excel_export.py`
  (`make_xlsx_response`/`build_xlsx_bytes`: intestazione navy, larghezze auto, riga
  bloccata, autofiltro). Pilota: **conformità DPI** — pulsante «Esporta Excel» che
  scarica la tabella stato-DPI del dipendente (ACL gestore, audit-light). Riusabile
  per saturazione carichi, asset, ecc. passando colonne+righe già calcolate.

## Ondata D — Interattività & onboarding
- [ ] **D1. Alpine.js** (vendor) — sprinkles dichiarativi complementari a HTMX;
  caso pilota di refactor del vanilla JS scritto a mano.
- [ ] **D2. driver.js** (vendor) — tour guidati per-modulo, agganciati all'onboarding.
- [ ] **D3. Lucide** (SVG) — set icone coerente (sostituzione progressiva di emoji/SVG sparsi).
- [x] **D4. Command palette `Ctrl+K`** ✅ — `core/js/command-palette.js` + CSS di
  brand. Overlay vanilla (Ctrl+K / Cmd+K) per saltare a qualsiasi pagina; indice
  **piatto e ACL-filtrato** costruito lato server (`command_palette_items` in
  `legacy_nav`, da `nav_items`/subnav, niente voci "in arrivo"). Filtro multi-termine,
  navigazione frecce/Invio/Esc, tema chiaro+scuro. Zero costo per anonimi (lista vuota).

---

## Come si esegue
Una voce alla volta, **un commit per voce** (CHANGELOG aggiornato). Per gli asset:
download della **versione pinnata dalla stessa fonte** già in uso, vendoring in
`core/static/core/vendor/<lib>/`, repoint dei template. Dove un'integrazione è
user-visibile, aggiornare README e (se AI) `docs/ai/GUIDA_AI.html`.

## Avanzamento
*(aggiornare i checkbox a ogni commit)*
