# TODO — Restyle UI Anagrafica HR (da prototipo JSX) — COMPLETATO ✓

> File di avanzamento. Fasi A, A-bis, B e C completate.
> Tenere come riferimento storico; eventuali sviluppi futuri aprire un nuovo TODO.

## Contesto

- **Sorgente UI**: `django_app/anagrafica_hr_dashboard_novicrom.jsx` — prototipo grafico React,
  dati MOCKATI. Da trattare SOLO come reference visivo, NON come sorgente dati.
- **Obiettivo**: portare il look & feel del prototipo nel modulo `anagrafica` come
  **solo cambio UI/UX**, senza toccare business logic, ACL, modelli, migrazioni, routing.
- **Vincolo chiave emerso dall'analisi**: il portale NON usa React/Vite/Tailwind.
  È Django SSR + HTMX + CSS custom. → Il prototipo va **ricostruito come template Django**,
  non importato come componente React.

## Stato analisi

- [x] Analisi prototipo JSX
- [x] Verifica stack frontend (NO React/Vite/Tailwind in `django_app`)
- [x] Analisi modulo `anagrafica` (views/urls/models/templates)
- [x] Analisi sicurezza/navigazione (`core/middleware.py`, `acl.py`, `navigation_registry.py`)
- [x] Report tecnico di impact assessment consegnato in chat
- [ ] Decisione utente sull'approccio (Fase A da avviare?)

## Verdetto

**PORTABILE CON ADATTAMENTI** — rischio MEDIO.
Ricostruzione come template Django SSR (NO React). Il prototipo definisce solo lo stile.

## Decisioni utente (confermate)

- **Layout grafico del prototipo va mantenuto fedelmente**, al netto del framework:
  stessa impaginazione, palette, card, pill, tab, hero, dettaglio inline.
  Si riusa la **logica/i dati già presenti** nel portale (non i mock).
- **Tab "Formazione"**: va **prevista nel layout** come tab/sezione, ma resta un
  **placeholder** (stato vuoto / "in arrivo"). Sarà implementata successivamente.
  NON creare modelli/migrazioni/viste per la formazione ora.

## Fasi proposte

### Fase A — UI shell protetta (COMPLETATA)

- [x] Creare CSS dedicato per il restyle (palette `#12395f` / `#1f5c91`)
      → `anagrafica/templates/anagrafica/components/_hr_restyle.html` (classi `hr-`).
        NB: incluso inline via `{% include %}` in `extra_head`, NON file static.
        Motivo: l'`AppDirectoriesFinder` registra le cartelle static all'avvio
        del runserver → un file static nuovo dà 404 finché non si riavvia.
        Il pattern inline del modulo anagrafica evita il problema.
- [x] Ricostruire `index.html` anagrafica con hero + metric card nuovo stile
      → dati invariati (6 conteggi view `index`), logica widget personalizzazione preservata
- [x] Restyle `dipendenti_list.html` (tabella + ricerca)
      → colonne/contesto/paginazione/sortable-table invariati
- [x] Restyle `subnav.html` a pill-tab (DB-driven, nessun cambio dati/registry)
- [x] Restyle design-system di `dipendente_detail.html`
      → riscritto SOLO il blocco `<style>`: classi `dp-*` invariate, corpo HTML
        e logica (form, edit toggle, widget, ACL) NON toccati. Palette/forma del
        prototipo. Corretto bug CSS media query mobile preesistente.
- [x] **Restyle strutturale `dipendente_detail.html` con tab interne** — FATTO
      → approccio additivo: tab bar `.dp-tabs` dopo l'hero; ogni card porta
        `data-tab="..."`; JS show/hide dei pannelli + `sessionStorage`.
        Tab senza card visibili per l'utente vengono nascoste automaticamente.
        Card NON riscritte, form/edit/widget/ACL invariati. Tab "Formazione"
        con placeholder `.dp-soon-card` + qualifiche/ruoli operativi.
        Bug CSS media query mobile corretto.

      **Mappa card → tab** (righe sorgente al momento del rilevamento):
      - HERO (l.301) → fuori dai tab, sempre visibile
      - Tab "Riepilogo"      → ANAGRAFICA AZIENDALE (l.329) + STATISTICHE (l.1569)
      - Tab "Anagrafica"     → ANAGRAFICA CIVILE (l.422)
      - Tab "Contratto & riservati" → DATI RISERVATI HR (l.477) + VOCI RETRIBUTIVE (l.533)
                               + CONTRATTO & INQUADRAMENTO (l.653) + STORICO CAMBIAMENTI (l.823)
      - Tab "Ferie"          → RATEI FERIE/ROL/EX-FEST (l.878)
      - Tab "Corsi"          → RUOLI OPERATIVI (l.947) + QUALIFICHE PROFESSIONALI (l.990)
      - Tab "DPI"            → DPI (l.1091)
      - Tab "Visite mediche" → VISITE MEDICHE (l.1195)
      - Tab "Documenti"      → DOCUMENTI DIPENDENTE (l.1342) + LICENZE SOFTWARE (l.1435)
      - Tab "Asset"          → ASSET (l.1483)

      Attenzione: card racchiuse in `{% if is_admin %}` / `{% if can_hr %}` —
      il wrapper `.dp-tab-panel` deve stare DENTRO o gestire bene gli `{% if %}`
      così una tab senza contenuto visibile resti comunque selezionabile (o
      nasconderla se l'utente non ha permessi: scelta da fare in fase di lavoro).
      "Formazione": aggiungere come tab placeholder (`.hr-soon`).
- [x] Ripuliti i colori inline `#1d4ed8` → `#1f5c91` nel corpo di
      `dipendente_detail.html` (link/accenti coerenti con la palette).
- [x] Nessun dato mock: usato SOLO context già forniti dalle view esistenti
- [x] Aggiornare `CHANGELOG.md` (voce sotto `[Unreleased] → Added`)
- [x] Verificato `python manage.py check` (0 issues) + compilazione template OK

**Tab 6 sezioni come subnav**: la subnav è DB-driven (`SubnavLinkAnagrafica`).
Le voci Dashboard/Persone/Assenze/Formazione/Documenti/Sicurezza vanno eventualmente
configurate come record subnav dal pannello Impostazioni → Navigazione (operazione
DATI, non codice — non farla via migrazione/hardcode). "Formazione" resta placeholder
finché non esiste una URL di destinazione.

### Fase A-bis — Restyle pagine secondarie del modulo anagrafica (COMPLETATA)

> HANDOFF: questa sezione è pensata per essere proseguita da un altro agente.
> Obiettivo: portare TUTTE le pagine del modulo `anagrafica` al nuovo stile,
> solo presentazione, zero modifiche a view/url/modelli/ACL/logica.

**Come si fa il restyle di una pagina (pattern consolidato):**

1. In `{% block extra_head %}` aggiungere come PRIMA riga:
   `{% include "anagrafica/components/_hr_restyle.html" %}`
   (NON usare file CSS static: l'`AppDirectoriesFinder` non li vede senza
   riavvio del runserver. Il partial inline è il pattern corretto.)
2. Assicurarsi che ci sia `{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}`.
3. Header pagina → `<div class="hr-pagehead">` con `hr-pagehead-eyebrow` /
   `hr-pagehead-title` / `hr-pagehead-desc` + eventuali `hr-btn`.
4. KPI/contatori → `hr-metric-grid` + `hr-metric` (icone `.blue/.green/.amber/.red/.navy`).
5. Contenitori → `hr-card` / `hr-card-head` / `hr-card-pad`; tabelle → `hr-table`;
   badge di stato → `hr-pill` (`.ok/.warning/.danger/.blue/.neutral`);
   bottoni → `hr-btn` (`-primary/-outline/-ghost`, `-sm`); vuoti → `hr-empty`.
6. Palette: navy `#12395f`, accento `#1f5c91`. Niente `#1d4ed8` inline nuovo.
7. NON toccare form, `name=` dei campi, action delle form, JS funzionale,
   context, `{% if is_admin/can_hr/... %}`. Solo markup/classi/CSS.
8. Verifica: compilare il template con `get_template(...)` e
   `python manage.py check --settings=config.settings.test`.
9. Aggiornare `CHANGELOG.md` e questo TODO.

**Classi disponibili in `_hr_restyle.html`**: `hr-shell, hr-hero(+stats),
hr-metric-grid/hr-metric(+ico), hr-card(+head/pad/title/desc), hr-grid(-2),
hr-pagehead(+eyebrow/title/desc), hr-pill(+toni), hr-progress, hr-btn(+varianti),
hr-tabs/hr-tab, hr-table, hr-search, hr-infocell, hr-empty, hr-soon(+badge)`.

**Stato pagine del modulo `anagrafica/templates/anagrafica/pages/`:**

- [x] `index.html` — dashboard
- [x] `dipendenti_list.html` — elenco dipendenti
- [x] `dipendente_detail.html` — scheda (design-system + tab interne)
- [x] `documenti_list.html` — archivio documenti (raccolta a cartelle)
- [x] `visite_mediche_dashboard.html` — dashboard visite mediche
- [x] `ratei_list.html` — ratei ferie/permessi
- [x] `impostazioni.html` — pannello impostazioni (cataloghi + permessi + navigazione)
      → ripalettatura `<style>` mantenendo classi `imp-*`; palette `#12395f`/`#1f5c91`
- [x] `mansioni_list.html` — catalogo mansioni
- [x] `aree_list.html` — catalogo aree aziendali
- [x] `ruoli_aziendali_list.html` — catalogo ruoli aziendali
- [x] `qualifiche_list.html` — catalogo tipi qualifica
      → link inline dipendente aggiornato a `#1f5c91`
- [x] `ruoli_operativi.html` — catalogo ruoli operativi
- [x] `dipendenti_report.html` — report dipendenti + export CSV
- [x] `dipendente_create.html` — form nuovo dipendente
      → include `dc-area-title::before` e `accent-color` checkbox
- [x] `dipendente_retribuzioni.html` — storico retributivo dipendente
- [x] `retribuzioni_import.html` — import CSV retribuzioni
      → upload zone drag-over color via JS aggiornato
- [x] `contratti_import.html` — import CSV contratti
      → upload zone drag-over color via JS aggiornato
- [x] `widget_permissions.html` — permessi widget statistiche
- [x] `visite_mediche_nuova_sessione.html` — registrazione sessione visite
      → aggiunto `{% block extra_head %}` con include; `#6366f1` e `#1d4ed8` → `#1f5c91`
- [x] componenti: `page_header.html`, `_retr_voce_row.html`, `partials/_dpi_iniziali_righe.html`
      → NESSUN RESTYLE NECESSARIO:
      · `page_header.html`: classi generiche del base template, nessun colore palette-specifico
      · `_retr_voce_row.html`: usa classi `dr-*` già ripalettate in `dipendente_retribuzioni.html`, nessun colore inline
      · `_dpi_iniziali_righe.html`: usa classi `dc-*` già aggiornate, solo colori neutri inline

> Suggerimento priorità per il prossimo agente: `impostazioni.html` (molto usata),
> poi i 4 cataloghi (mansioni/aree/ruoli aziendali/qualifiche) che hanno struttura
> simile fra loro, poi `dipendenti_report.html` e i form. `impostazioni.html` è
> grande e ha tab interne proprie: trattarla come `dipendente_detail` (ripaletta
> il blocco `<style>` mantenendo le classi, non riscrivere il corpo).

### Fase B — Collegamento dati read-only (COMPLETATA)

Audit completato. Risultati:

- [x] Verificare che ogni sezione del prototipo abbia una fonte dati reale
      → Dashboard, Persone, DPI, Documenti, Visite mediche: ✓ dati reali
      → Tab "Formazione": placeholder previsto — OK per design
      → Tab "Assenze" in `dipendente_detail`: **MANCANTE** (vedi Gap #1+#2 sotto)
- [x] NON creare nuove API se i context template bastano
- [x] Mascheramento server-side dei dati riservati (retribuzione/IBAN/CF)
      → `_check_hr_permission()` gating per dati riservati ✓
      → `iban_mascherato` property a livello modello ✓
      → `_can_view_visite_mediche()` per visite ✓
- [x] **Gap #5** (template): form upload visite già gated da `{% if is_admin and tipi_visita_attivi %}` dentro `{% if can_view_visite %}` — nessuna modifica necessaria
- [x] **Gap #4** (view+template): KPI qualifiche split — `n_qualifiche_scadute` (già scadute) + `n_qualifiche_scadenza` (prossimi 60gg, con lower bound corretto). Due metric card separate in `index.html`.

**Gap aperti — decisione utente richiesta:**

- [x] **Gap #1+#2 — Tab "Assenze" in `dipendente_detail.html`** (opzione B scelta dall'utente):
      Implementato `_query_assenze_dipendente(utente_id)` in `views.py`:
      query read-only su `assenze JOIN dipendenti` via `utente_id`, ultimi 2 anni.
      Template: KPI card (giorni approvati per tipo, anno corrente) + tabella storico
      con stato a pill. Fallback se dipendente non ha account portale.
      Zero nuovi modelli, zero nuovi URL, zero migrazioni.

### Fase C — Azioni operative (COMPLETATA)

- [x] Collegare pulsanti (Nuovo/Download/Permessi) a route esistenti o disabilitarli
      → Audit completo: tutti i bottoni nei template `anagrafica` sono collegati a route reali.
      → Unico stub rimasto: `href="#" onclick="alert(...)"` in `dipendente_detail.html`
        per "Import cedolini" → sostituito con `<details>` inline che mostra il comando CLI.
- [x] Nessuna azione mutativa nuova

### Miglioramenti fruibilità (post Fase C — su proposta agente, accettati dall'utente)

- [x] **Scadenzario unificato** (`anagrafica/views.py`, `urls.py`, `pages/scadenzario.html`):
      Vista `/anagrafica/scadenzario/` — qualifiche + visite mediche scadute/in scadenza.
      Filtri: tipo, stato (scaduta/30/60gg), reparto. Export CSV. Paginazione 50.
      ACL: visite gated da `_can_view_visite_mediche`. Ogni riga → link scheda dipendente.
- [x] **Alert banner dashboard** (`index.html`, `views.py`):
      Banner arancione se scadenze urgenti (`n_qualifiche_scadute > 0` o `n_visite_scadute > 0`).
      Link diretto allo scadenzario. Metric card con link contestuali.
- [x] **Foto dipendente hero**: già implementata in Fase A (`.dp-avatar` + `.dp-avatar-fallback`).

**Sviluppi futuri suggeriti:**
- Tab "Formazione" nella scheda dipendente (da implementare quando esiste il modulo corsi)
- Storico assenze più ricco (se si aggiunge FK Django nel modulo assenze)
- Notifiche email/Teams automatiche per scadenze prossime (`visite_expiry_reminders` esiste già)

## Cose da NON toccare (vincoli assoluti)

- `core/middleware.py` (ACLMiddleware), `core/acl.py`, `core/acl_v2.py`
- `_check_hr_permission` / `_can_view_visite_mediche` / `_can_view_stats` in `anagrafica/views.py`
- Modelli, migrazioni `anagrafica/migrations/*`
- `core/navigation_registry.py` e subnav `SubnavLinkAnagrafica`
- Workflow assenze / documenti / asset / retribuzioni / visite mediche
- Route in `anagrafica/urls.py`

## Note per chi prosegue

- Il prototipo ha 6 tab (Dashboard/Persone/Assenze/Formazione/Documenti/Sicurezza).
  Tutte e 6 vanno previste nel layout per fedeltà grafica.
  - Assenze: modulo separato → la tab mostra dati reali da `assenze`/legacy o linka al modulo.
  - Formazione: **placeholder** voluto dall'utente, implementazione futura.
  - Documenti/Sicurezza/Persone/Dashboard: popolati con logica/dati esistenti.
- I dati mock del JSX (people, absences, training, documents) NON vanno copiati.
- `anagrafica_hr_dashboard_novicrom.jsx` resta nel repo come reference; valutare se
  spostarlo in `docs/ai/` o rimuoverlo a fine lavori (decisione utente).
