# Topnav — revisione UX (2026-09)

Branch: `feature/core-topnav-ux` · worktree `C:\Dev\pn-topnav`

File coinvolti: `core/templates/core/components/topnav.html`, `core/templates/core/base.html`,
`core/static/core/css/theme.css`, `core/static/core/js/command-palette.js`, `core/static/core/css/command-palette.css`,
`core/context_processors.py`, `core/templates/core/components/_dev_git_badge.html`.

## Checklist

### 1. Bug
- [x] 1.1 Ctrl+K gestito due volte (palette + ricerca globale in `base.html`). Ora un solo overlay (`#gs-overlay`) guidato da `command-palette.js`, con sezioni «Recenti», «Vai a…» e risultati dati.
- [x] 1.1b Con il Navigation Registry l'indice pagine era **vuoto**: il ramo registry di `navigation_context` faceva `return` prima di calcolarlo. Estratto `_build_command_palette_items`, chiamato su entrambi i rami (test `TopnavUnifiedSearchTests`).
- [x] 1.2 Dropdown con colori fissi (`#f1f5f9`, `#1a6fc4`, `#eff6ff`) → `color-mix` su `--text`/`--accent`, validi in chiaro e scuro; tolti gli override dark dedicati.
- [x] 1.3 Tendine e menu utente da tastiera: ↓/Invio/Spazio apre, frecce/Home/End, Esc chiude e riporta il focus.
- [x] 1.4 Hamburger mai visibile: `.nav-hamburger{display:none}` stava dopo le media query. Spostato prima.

### 2. Zona destra: 8 → 4 elementi
- [x] 2.1 Lente → barra «Cerca o vai a… Ctrl K».
- [x] 2.2 Menu utente (avatar ▾): Profilo, Preferenze, Tema chiaro/scuro (POST `ui_prefs_api_save`), Segnala un problema, Esci.
- [x] 2.3 Pillola ⚠ rossa → «N da approvare», ambra.
- [x] 2.4 «AI» testo → icona SVG + tooltip Alt+A.

### 3. Contenuto voci
- [x] 3.1 Emoji (🔍 🔔 ⚙ ⚠) → SVG inline.
- [x] 3.2 `title` = `legacy_url` rimosso.
- [x] 3.3 Pallino `coming` → etichetta «Presto».
- [x] 3.4 «Recenti»: ultime 6 pagine di navigazione visitate (localStorage `nhub.recent-pages`, per browser; tollerante a storage bloccato).

### 4. Layout / responsive
- [x] 4.1 Voce attiva: sottolineatura `--accent` (desktop), barretta laterale (hamburger/tendine).
- [x] 4.2 Overflow «Altro ▾» sopra 1100px (ricalcolo su resize, font caricati e `ResizeObserver` sulla zona destra); hamburger con etichette da ≤1100px.
- [x] 4.3 ≤640px: a destra solo ricerca (icona), notifiche, avatar (+ pillola compatta se presente).
- [x] 4.4 Separatori e margini dopo logo/prima della zona destra rimossi.

### 5. Raggruppamento
- [x] 5.1 I gruppi nascono da `category_key` del Navigation Registry (`_group_nav_items`) e si gestiscono da **Impostazioni → Navigation Builder**: è configurazione dati, non codice. L'overflow «Altro» elimina il problema di spazio anche senza riorganizzarli.
- [ ] 5.2 (decisione di contenuto, fuori codice) ridurre a 5–6 aree: Operatività, Persone, Sicurezza, Automazioni, Amministrazione.

### Extra
- [x] Badge git di sviluppo spostato in basso a destra: in alto copriva il menu utente.

## Verifica
- [x] test `core.tests.TopnavUnifiedSearchTests`, `core.test_vendor_assets`, navigation registry/legacy/branding, sidebar footer (25 OK)
- [x] a video (Playwright, SQLite di worktree): light + dark, 1440 / 1180 / 1024 / 390 px; nessun errore JS; un solo overlay con Ctrl+K; tema persistito dopo reload; Recenti e tastiera verificati
- [x] CHANGELOG + README
- [ ] merge main → release/prod
