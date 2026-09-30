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
- [x] 5.2 Gruppi decisi con l'utente (2026-09-25) → vedi «Round 2».

### Extra
- [x] Badge git di sviluppo spostato in basso a destra: in alto copriva il menu utente.

## Verifica
- [x] test `core.tests.TopnavUnifiedSearchTests`, `core.test_vendor_assets`, navigation registry/legacy/branding, sidebar footer (25 OK)
- [x] a video (Playwright, SQLite di worktree): light + dark, 1440 / 1180 / 1024 / 390 px; nessun errore JS; un solo overlay con Ctrl+K; tema persistito dopo reload; Recenti e tastiera verificati
- [x] CHANGELOG + README
- [x] merge main → release/prod (main `db3e10be`, release/prod `59b55825`)

---

# Round 2 — gruppi e sottocategorie (2026-09-25)

Branch `feature/core-topnav-gruppi` · worktree `C:\Dev\pn-navgruppi`

## Decisioni dell'utente (vincolanti)
- Segnalazioni **distinte**: niente «+ Segnala» unico. **Tickets resta un modulo unico** (IT + MAN), voce diretta.
- **Suggestion Corner** fuori da «Per me»: voce diretta.
- **Timbri** = registro HR (non le timbrature personali): solo in Persone.
- «Dashboard» esce dalla barra (ci porta il logo); resta in sidebar e Ctrl+K.

## Struttura
```
[logo] Per me ▾  Tickets  Produzione ▾  Persone ▾  Sicurezza e ambiente ▾  Qualità ▾  IT ▾  Suggestion Corner
```
| Gruppo | Sottocategoria → voci (route) |
|---|---|
| Per me | Da fare → Presa visione (`procedure_refresh:my_assignments`), KICK-OFF da gestire (`tasks:da_gestire`) · Richieste → Le mie assenze (`assenze_gestione`), Richiedi assenza (`assenze_richiesta`), Richiedi DPI (`dpi:nuova`) · Azienda → Notizie |
| Tickets | voce diretta (`tickets:dashboard`) |
| Produzione | Commesse e reparti → KICK-OFF, Carichi Macchina, Checklist Operativa · Manutenzione → Asset e manutenzione, Gestione Attrezzatura |
| Persone | Anagrafica, Assenze (gestione HR) (`assenze_impostazioni`, permesso esplicito `legacy.assenze.admin_assenze`: la route eredita `assenze.route.view` = tutti), Timbri, Campagne presa visione (`procedure_refresh:admin_dashboard`) |
| Sicurezza e ambiente | Sul campo → Diario preposto, Segnalazioni sicurezza, DPI · Prodotti e rifiuti → Schede di Sicurezza, Rentri |
| Qualità | Gestione Anomalie (legate agli ordini), Gestione Specifiche, Registro OFI |
| IT | Security Center, Contatori MFC, Accessi azienda |
| Suggestion Corner | voce diretta |

Scartati dopo verifica nel codice: «Il mio turno» (nascosto apposta da assets 0104); «I miei DPI» (stesso URL di DPI: `dpi:dashboard` è già personale per chi non è gestore).

## Checklist
- [x] R2.1 `_group_nav_items`: `sections` dalle sottocategorie (`NavigationItem.group`), `cols` se >6 voci; `is_home` per nascondere Dashboard in topnav
- [x] R2.2 Template tendina: intestazioni sottocategoria, colonne; «Altro» e hamburger con intestazioni; tendina tenuta dentro lo schermo
- [x] R2.3 Comando `riorganizza_topbar` (`--apply`, default dry-run), idempotente: categorie (rinomina le esistenti, crea «Per me»), sposta/etichetta voci per code con fallback route, crea le 4 voci nuove, report permessi e voci non toccate, bump cache registry
- [x] R2.4 Test: raggruppamento, comando (dry-run non scrive, apply, secondo apply senza modifiche)
- [x] R2.5 Verifica a video light/dark 1440/1180/1024/390
- [ ] R2.6 CHANGELOG, README, merge main → release/prod; al deploy: `riorganizza_topbar` poi `--apply`

## Emersi durante il lavoro
- [x] **Bootstrap che annullavano il menu**: 9 moduli (`dpi`, `timbri`, `procedure_refresh`, `tasks`, `attrezzature`, `gestione_carichi_macchina`, `gestione_specifiche`, `schede_sicurezza`, `suggestion_corner`) a ogni avvio riscrivevano etichetta/ordine/visibilità → `core.navigation_registry.ensure_navigation_item` (poi solo campi di codice).
- [x] **Branding batte l'etichetta**: le voci-modulo prendono il nome da `module_branding.<modulo>.menu_label`; il comando lo imposta solo se vuoto.
- [x] **Permesso troppo largo**: la route admin assenze ereditava `assenze.route.view` → permesso esplicito `legacy.assenze.admin_assenze` su `assenze_impostazioni` (`gestione_admin` è un redirect deprecato).
- [x] **Spazio**: a 1440px le voci non entravano (964px su 711) → niente icone al primo livello, nome utente nel menu dell'avatar sotto 1600px.
- [ ] Preesistente, NON legato a questo lavoro: `dpi.tests.DpiCatalogRequestTests` 2 test falliti anche su `origin/main` (il dettaglio richiesta non mostra il codice modello).