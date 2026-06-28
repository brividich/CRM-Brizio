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
- [ ] **B1. Tom Select** (vendor) — select ricercabili/typeahead accessibili,
  init globale su `select.js-searchable` (+ data-attr), fallback al `<select>`
  nativo. Applicazione progressiva: report DPI (dipendente/mansione), assegnazione
  ticket, filtri con liste lunghe.
- [ ] **B2. Flatpickr** (vendor, locale IT) — date/range picker coerente nei filtri
  e nei report; degrada a `<input type=date>`.

## Ondata C — Visualizzazione dati
- [ ] **C1. Chart.js riusabile** — dopo il self-host (A1), un piccolo helper +
  pattern per portare grafici veri dove oggi ci sono **barre CSS** (KPI gestione
  specifiche, analytics ticket, saturazione carichi). Una dashboard pilota.
- [ ] **C2. Export Excel (openpyxl, già installato)** — util condivisa per
  esportare i "report a tabella" (saturazione, asset, conformità DPI) in `.xlsx`,
  ACL-gated, audit-light. Eventuale formato `xlsx` anche per il report AI.

## Ondata D — Interattività & onboarding
- [ ] **D1. Alpine.js** (vendor) — sprinkles dichiarativi complementari a HTMX;
  caso pilota di refactor del vanilla JS scritto a mano.
- [ ] **D2. driver.js** (vendor) — tour guidati per-modulo, agganciati all'onboarding.
- [ ] **D3. Lucide** (SVG) — set icone coerente (sostituzione progressiva di emoji/SVG sparsi).
- [ ] **D4. Command palette `Ctrl+K`** (vanilla) — navigazione rapida cross-modulo (~27 moduli).

---

## Come si esegue
Una voce alla volta, **un commit per voce** (CHANGELOG aggiornato). Per gli asset:
download della **versione pinnata dalla stessa fonte** già in uso, vendoring in
`core/static/core/vendor/<lib>/`, repoint dei template. Dove un'integrazione è
user-visibile, aggiornare README e (se AI) `docs/ai/GUIDA_AI.html`.

## Avanzamento
*(aggiornare i checkbox a ogni commit)*
