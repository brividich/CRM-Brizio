# F1 — Menu di modulo Anagrafica: da hover-dropdown a click-accordion

**Data:** 2026-07-03
**Ambito:** `django_app/anagrafica` — solo il menu di modulo (sotto-nav). **Non** tocca la navbar globale del portale.
**Stato:** design approvato in brainstorming, pronto per il piano d'implementazione.
**Fase:** F1 di una roadmap più ampia (vedi *Roadmap*).

---

## 1. Contesto e problema

Il modulo Anagrafica ha una sotto-nav propria (non usa la `subnav` piatta condivisa dagli altri
moduli): una **barra orizzontale a pillole** con dropdown e un mega-menu, la "Proposta A" a 4 pilastri
(👥 Persone · 🎓 Competenze · 🛡 Compliance · 🪙 Amministrazione) più i link diretti Dashboard,
Scadenzario, Impostazioni. In totale **7 voci di primo livello / 30 sotto-link**.

I dropdown si aprono **all'hover** (`:hover` / `:focus-within` in CSS). Problema principale: l'hover è
**fragile su touch e tablet**, richiede timing di apertura/chiusura, e la chiusura "all'uscita del mouse"
è imprevedibile. È il difetto #1 emerso dalla valutazione delle strategie di navigazione.

**Obiettivo F1:** sostituire l'apertura a hover con l'apertura al **click**, mantenendo la barra
orizzontale e l'intera struttura dati esistente. Fix mirato, a basso rischio, che sblocca touch/tastiera
senza redesign del layout.

## 2. Decisioni bloccate (dal brainstorming)

| # | Decisione | Valore scelto |
|---|-----------|---------------|
| D1 | Superficie | **Menu di modulo** Anagrafica (la sotto-nav). NON la navbar globale. |
| D2 | Fonte di verità nav | **Tieni i modelli `SubnavCategoriaAnagrafica` / `SubnavLinkAnagrafica`** e ridisegna sopra. Nessuna migrazione dati; CRUD runtime da Impostazioni preservata. |
| D3 | Layout | **Barra orizzontale invariata**; i dropdown a hover diventano **pannelli che si aprono al click**. Niente rail verticale, niente shell a 2 colonne. |
| D4 | Costo | Minimo: si tocca **essenzialmente un solo file** (`subnav.html`). |

## 3. Stato attuale (file coinvolti)

- **Markup + CSS:** `django_app/anagrafica/templates/anagrafica/components/subnav.html` (~123 righe,
  `<style>` inline con le classi `.hrnav-*`, loop su `nav.items`, `<script>` inline finale).
- **Provider dati (template tag):** `django_app/anagrafica/templatetags/anagrafica_extras.py`,
  `subnav_anagrafica` (righe 168-306). Ritorna `{"items": [...]}` con item `type="link"` o
  `type="category"`; le category hanno `landing_url`, `links`, `groups` (colonne del mega-menu dal
  campo `gruppo`), `has_headers`, `active`.
- **Modelli:** `django_app/anagrafica/models.py` righe 1803-1896.
- **Inclusione:** ~60 pagine fanno `{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}`.

Meccanica hover attuale (da rimuovere):
```css
.hrnav-dd:hover .hrnav-dd-menu,
.hrnav-dd:focus-within .hrnav-dd-menu { display:block; }
.hrnav-dd:hover .hrnav-dd-menu.hrnav-dd-mega,
.hrnav-dd:focus-within .hrnav-dd-menu.hrnav-dd-mega { display:flex; }
```

Due forme di trigger nel markup (entrambe da conservare):
- **Split-pill** (categoria con `landing_url`): `<a class="hrnav-pill">` (link alla dashboard del
  sotto-modulo) + `<button class="hrnav-caret-btn">▾</button>` (apre il menu).
- **Dropdown semplice** (categoria senza landing): `<button class="hrnav-dd-btn">`.

## 4. Design della soluzione

Principio: **trasformare l'apertura da CSS-hover a click controllato da JS**, senza toccare dati,
template tag, modelli o le pagine. Il template tag continua a produrre la stessa struttura `nav.items`.

### 4.1 Markup (`subnav.html`)
Modifiche minime ai `<button>` trigger già presenti:
- Aggiungere a ogni trigger (`.hrnav-caret-btn` e `.hrnav-dd-btn`):
  `aria-expanded="false"`, `aria-haspopup="true"`, `aria-controls="<id-del-menu>"`.
- Dare al `.hrnav-dd-menu` un `id` univoco (es. `hrnav-menu-{{ item.id }}`) e `aria-label="{{ item.label }}"`.
- **Non** usare `role="menu"/menuitem`: introdurrebbe l'aspettativa di navigazione a frecce. I figli
  restano `<a>` normali (Tab li attraversa), pattern robusto tipo GOV.UK sub-navigation.
- Lo split-pill resta invariato: il **testo** (`<a class="hrnav-pill">`) naviga al landing; **solo il
  caret** apre il menu.

### 4.2 CSS (`subnav.html`)
- Rimuovere i trigger `:hover`/`:focus-within` che fanno `display:*`.
- Aprire via classe di stato:
  ```css
  .hrnav-dd-menu.open { display:block; }
  .hrnav-dd-menu.hrnav-dd-mega.open { display:flex; gap:2px; }
  ```
- Stato "aperto" sul trigger: caret ruotato (`[aria-expanded="true"] .hrnav-caret{transform:rotate(180deg)}`),
  wrappato in `@media (prefers-reduced-motion:reduce)` per la transizione.
- Il posizionamento resta quello attuale: `.hrnav-dd{position:relative}` + `.hrnav-dd-menu{position:absolute}`
  → nessun calcolo JS di posizione.
- **Fallback senza JS:** conservare `:focus-within` come apertura di ripiego **solo quando il JS non è
  attivo**, per non litigare col controller. Pattern: il controller aggiunge `hrnav-js` alla radice; il
  CSS di fallback si applica con `:not(.hrnav-js)`:
  ```css
  html:not(.hrnav-js) .hrnav-dd:focus-within .hrnav-dd-menu { display:block; }
  html:not(.hrnav-js) .hrnav-dd:focus-within .hrnav-dd-menu.hrnav-dd-mega { display:flex; }
  ```
- Estendere le regole `body.theme-dark` ai nuovi stati open/expanded (il file gestisce già il dark).

### 4.3 Controller JS (~25 righe, vanilla, inline in `subnav.html`)
Coerente con lo `<script>` inline già presente e con lo stack "no framework". Comportamento:
1. All'avvio: `document.documentElement.classList.add('hrnav-js')` (disattiva il fallback CSS).
2. Per ogni `.hrnav-dd`: individua il/i trigger button e il `.hrnav-dd-menu` fratello.
3. **Click sul trigger** → toggle `.open` sul menu + `aria-expanded` sul button; **chiude gli altri**
   (uno alla volta).
4. **Click fuori** (`document`, con `closest('.hrnav-dd')` per escludere l'interno) → chiude tutti.
5. **`Esc`** → chiude tutti e riporta il focus al trigger aperto.
6. Il click sul **testo dello split-pill** (link landing) non è intercettato: naviga normalmente.

### 4.4 Stati: attivo ≠ aperto
- **Attivo** = pagina corrente, invariato: calcolato dal template tag via `active_view_names`
  (`aria-current="page"` da aggiungere sull'item attivo per correttezza a11y).
- **Aperto** = stato di UI transitorio del dropdown (`aria-expanded`). I due sono indipendenti e
  visivamente distinti (pill navy vs. caret ruotato).

## 5. Accessibilità
- `<button aria-expanded aria-haspopup aria-controls>` per ogni trigger; `aria-current="page"` sull'attivo.
- Tastiera: Tab raggiunge trigger e link; Invio/Spazio sul button apre; Esc chiude e ripristina il focus.
- Touch: nativo (nessun hover).
- Degrado senza JS: menu raggiungibili via `:focus-within` (gate `html:not(.hrnav-js)`).
- `prefers-reduced-motion`: nessuna animazione di rotazione/transizione.

## 6. Cosa NON cambia (non-goals)
- Nessuna modifica a `SubnavCategoria/Link`, ai dati, alla CRUD runtime di Impostazioni.
- Nessuna modifica al template tag `subnav_anagrafica` (salvo, eventuale e opzionale, l'emissione
  dell'`id` menu — fattibile anche interamente nel template con `{{ item.id }}`).
- Nessuna modifica alle ~60 pagine che includono la subnav (ereditano il nuovo comportamento).
- Nessun rail verticale, nessuna shell a 2 colonne, nessuna navbar globale.
- Il contenuto/raggruppamento del mega-menu Competenze resta identico (colonne dal campo `gruppo`).
- La sotto-nav Sicurezza di 2° livello (`_safety_subnav.html`) resta com'è, annidata in Compliance.

## 7. Piano di test e quality gate
- `python django_app\manage.py test django_app.anagrafica --settings=config.settings.test --keepdb`
  (verifica non-regressione del template tag / render subnav).
- `python django_app\manage.py check --settings=config.settings.test`.
- **Verifica manuale in browser** (light + dark): click apre/chiude; uno alla volta; Esc; click fuori;
  Tab da tastiera; touch/emulazione mobile; lo split-pill naviga al landing; le colonne del mega
  Competenze si renderizzano; stato attivo corretto; **con JS disattivato** i menu restano raggiungibili
  via focus (fallback).
- Aggiornare **CHANGELOG.md** (file toccati + descrizione sotto `[Unreleased]`) e **README.md** se cambia
  funzionalità visibile (obbligatorio da CLAUDE.md).

## 8. Rischi e mitigazioni
| Rischio | Mitigazione |
|---|---|
| Interferenza tra fallback `:focus-within` e JS | Gate `html:not(.hrnav-js)`: il fallback si spegne quando il JS è attivo. |
| La subnav è inclusa in ~60 pagine | Si cambia solo l'interno del partial: tutte le pagine ereditano; nessun override CSS delle classi `.hrnav-*` altrove (da verificare con una grep rapida in fase di piano). |
| Regressione del mega-menu (flex vs block) | Regole `.open` distinte per `.hrnav-dd-menu` e `.hrnav-dd-mega`, come oggi per l'hover. |
| Click-outside che ingoia altri click | Handler con `closest('.hrnav-dd')`, nessun `preventDefault` sui link. |

## 9. Roadmap (contesto, fuori ambito F1)
- **F1 (questo doc)** — barra orizzontale, apertura al click.
- **F2** — hub landing a card su `/anagrafica/` (scopribilità/onboarding).
- **F3** — profilo persona a tab HTMX, ACL-gated (spina dorsale "oggetto persona").
- **F4** — command palette ⌘K (opzionale, layer power-user).

Ogni fase ha il suo ciclo spec → piano → implementazione. F2-F4 non sono coperte qui.

## 10. Prova visiva
Prototipo interattivo del design F1 (barra orizzontale, pannelli al click, inventario reale):
artifact `anagrafica-hubnav-prototipo` — comportamento click/uno-alla-volta/Esc, split-pill, mega a
colonne, stato attivo, fallback.
