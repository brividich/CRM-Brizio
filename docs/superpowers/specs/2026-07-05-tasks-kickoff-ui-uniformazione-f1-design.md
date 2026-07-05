# Uniformazione UI modulo KICK-OFF (`tasks`) — Fase 1: Fondazione UI

- **Data:** 2026-07-05
- **Modulo:** `django_app/tasks` (dominio: gestione **KICK-OFF** = avvio progetti/commesse; NON "cose da fare")
- **Branch di lavoro:** `feature/skill-matrix-mod187` (branch attivo in prod — vedi nota deploy)
- **Stato:** Design approvato, in attesa di piano di implementazione

---

## 1. Contesto e problema

Il modulo `tasks` (etichetta utente **KICK-OFF**) è l'unico modulo del portale che si
discosta dallo standard di UI condiviso. Gestisce l'avvio delle commesse: **Project =
kickoff** (con VRF/MOD.073, Gantt, Incontri, copia-con-VRF) e **Task = attività** dentro
la commessa (sottotask, allegati, stato, categorie, ruoli, attrezzature).

Debito attuale rilevato in ricognizione:

- **Chrome custom** invece dello standard: `tasks/templates/tasks/base_shell.html` usa una
  shell propria con `ts-hero` + `ts-tabs` come navigazione, invece di
  `core/components/page_header.html` (`hub-page-header`) + la `subnav.html` condivisa
  (pilotata da `NavigationItem`, come tutti gli altri moduli).
- **Design token paralleli**: usa `--ts-*` (`--ts-border`, `--ts-text-mid`,
  `--ts-radius-md`, …) invece del design-system `--hub-*` (definito in
  `core/static/core/css/tokens.css`, già con supporto light + `body.theme-dark`).
- **Override responsività**: `base_shell.html` forza `.content { width:100% !important;
  max-width:none !important }` — l'anti-pattern mappato nell'audit responsività del portale.
- **Debito dark-mode**: ogni template ha un blocco `<style>` con colori chiari hardcodati
  (`#fff`, gradienti `#dbeafe`, `#1d4ed8`, …) → in `body.theme-dark` molte parti restano
  chiare/illeggibili.
- **Duplicazione**: `tasks.css` (777 righe) + ~15 template, ognuno con stile proprio.

### Confronto web (prodotti simili)

Confronto orientato a tool di **project/portfolio kickoff management** (non todo personali):
Asana, ClickUp, Linear, Monday, Smartsheet, Wrike. Temi ricorrenti dei prodotti leader,
utili come roadmap (fonti in fondo):

- Viste multiple sullo stesso dato: List, **Board/Kanban**, **Timeline/Gantt**, **Calendar**.
- Vista d'insieme di portfolio con **indicatori di salute/readiness** per iniziativa.
- Densità e scansionabilità: righe compatte, gerarchia tipografica chiara, indicatori di
  stato a colpo d'occhio (tasks lo fa già con il bordo-stato di riga).
- Keyboard-first & azioni rapide (Linear); stati vuoti e onboarding curati; filtri/viste salvati.

Queste idee alimentano **F2/F3** (sotto), non F1.

---

## 2. Obiettivo e scomposizione in fasi

Obiettivo complessivo (deciso con l'utente): **uniformare la UI di `tasks` come gli altri
moduli** e, a seguire, **valutare/introdurre migliorie** emerse dal confronto. Scopo ibrido:
uniformazione + migliorie leggere + alcune viste nuove.

Poiché l'insieme è grande (~15 template + 777 righe CSS + 4 viste nuove richieste), si
scompone in fasi indipendenti, ognuna con il proprio ciclo spec → piano → implementazione.
Sequenza scelta: **Fondazione prima (F1 → F2 → F3)**.

| Fase | Contenuto | Rischio |
|------|-----------|---------|
| **F1 — Fondazione UI** *(questa spec)* | Chrome condiviso (`page_header` + subnav), rimozione override `.content`, migrazione token `--ts-*` → `--hub-*`, dark-mode, responsività. **Nessun cambio funzionale.** | Medio (tocca tutti i template, ma iso-funzionale) |
| **F2 — Migliorie leggere** | Indicatore **salute/readiness** commessa (VRF ok? incontro fatto? task in ritardo?); stati vuoti, densità, filtri. | Basso |
| **F3 — Viste nuove** | **Board** per stato/fase, **Calendario** incontri, **Timeline cross-commessa**. Nuove route → nuovi binding ACL + `API_ACL_GATE_PATHS`. | Alto |

Le viste nuove (F3) vanno costruite **sopra** il design-system condiviso: farle prima
dell'uniformazione significherebbe scriverle in stile `ts-` legacy e rimigrarle.

---

## 3. Scelte di design approvate

1. **Target visivo:** *sistema coerente, ricchezza preservata*. Si adottano chrome condiviso
   e token `--hub-*` (coerenza, dark-mode e responsività automatiche), **mantenendo** i
   componenti più ricchi di tasks (card portfolio con cover, KPI colorati) ribasati sui token.
   Nessun impoverimento visivo.
2. **Larghezza pagine:** *cap standard + opt-in `wide`*. Le pagine tornano al cap standard del
   portale; solo quelle che lo richiedono (Gantt ora; Board/Timeline in F3) attivano una
   classe `wide` esplicita.
3. **Tab di commessa** (per-record) come **componente locale**, non subnav di sezione.
4. **`tasks.css`** resta come **foglio di modulo** (ribasato sui token), non spalmato in `hub.css`.
5. **Opt-in larghezza** implementato con micro-modifica al core (`core/base.html` + `theme.css`),
   default-off, così diventa il meccanismo sanzionato che sostituisce gli override inline sparsi.

Vincolo permanente: **non modificare il tema** — riusare i token/palette esistenti, nessuna
nuova palette.

---

## 4. Architettura F1

### 4.1 Navigazione & chrome

- **Ritiro della shell custom.** `base_shell.html` (con `ts-hero` + `ts-tabs`) viene
  sostituito da un nuovo `tasks/base.html` che `extends core/base.html` (come gli altri
  moduli). Espone blocchi per gli argomenti del page_header e per la classe di larghezza.
- **Titolo di pagina** via `core/components/page_header.html` (`hub-page-header`), passando
  `eyebrow` / `title` / `subtitle` / eventuale `status_label`. Le azioni primarie (es. "Nuova
  attività", "Nuovo kickoff") vanno in un blocco azioni accanto al titolo, con `.btn` condiviso.
- **Subnav di modulo** (livello sezione): voci **Dashboard** (attività, `tasks:list`) ·
  **Kickoff** (progetti, `tasks:project_list`) · **Impostazioni** (`tasks:impostazioni`,
  gated su `tasks.kickoff.admin`). Implementate come `NavigationItem`
  (`section="subnav"`, `parent_code=<codice nav top del modulo>`, `route_name`, `order`,
  `is_visible`/`is_enabled`, `required_permission_code` dove serve), seed via **migrazione
  dati** (pattern `core/migrations/0058_anagrafica_sidebar_subnav.py`). Rese automaticamente
  dalla `subnav.html` condivisa, con active-state e filtro ACL.
  - **Check di implementazione:** allineare `parent_code` al codice reale della
    `NavigationItem` top di tasks. In `tasks/acl_bootstrap.py` il nav top è creato con
    `code = existing_nav_item.code if existing_nav_item else "tasks"`; verificare il valore
    effettivo in DB prima di fissare `parent_code` (atteso `"tasks"`).
- **Tab contestuali di commessa** (livello record): **Dettaglio · Gantt · Incontri · VRF**,
  dipendenti dal singolo `project_id`, non possono stare nella subnav di sezione. Nuovo
  partial `tasks/templates/tasks/_project_tabs.html` in stile hub (usa token `--hub-*`),
  incluso nelle pagine progetto con `active` passato dal contesto. Le stesse voci contestuali
  oggi presenti nei `ts-tabs` condizionali (`tasks_shell_project` / `tasks_shell_task`)
  vengono ricreate qui, iso-funzionali.

### 4.2 Policy larghezza

- Rimuovere l'override `.content { max-width:none }` da `base_shell.html`.
- **Opt-in sanzionato** (micro-modifica core, default-off):
  - `core/templates/core/base.html`: il div contenitore diventa
    `<div class="content{% block content_class %}{% endblock %}">`. Default vuoto ⇒ nessun
    cambiamento per tutte le pagine esistenti.
  - `core/static/core/css/theme.css`: aggiungere `.content--wide { width:100%; max-width:none }`.
- Pagine tasks:
  - Liste (Dashboard, Kickoff), dettaglio task, form, impostazioni, incontri → **cap standard**
    (nessuna classe).
  - **Gantt** (`project_gantt.html`) → `{% block content_class %} content--wide{% endblock %}`.
- Nota: `theme.css:68` già cita `.content > .ts-shell` per il full-height; al ritiro della
  shell, ripulire/riadeguare quella regola (senza rompere gli altri selettori elencati sulla
  stessa riga: `.portal-fill`, `.as-shell`, `.abs-shell`, `.dash`, `#eb-root`).

### 4.3 Token & CSS

- **Mappa `--ts-*` → `--hub-*`** (già light + dark in `tokens.css`):
  - `--ts-border` → `--hub-color-border`
  - `--ts-text` → `--hub-color-text`
  - `--ts-text-mid` → `--hub-color-text-muted`
  - `--ts-text-soft`/light → `--hub-color-text-soft`
  - `--ts-surface`/`#fff` → `--hub-color-surface` / `--hub-color-surface-raised`
  - `--ts-radius-*` → `--hub-radius-sm|md|lg|xl`
  - spaziature → `--hub-space-*`; ombre → `--hub-shadow-*`; stati → `--hub-status-*`
- **Riscrivere `tasks.css`** sui token core; mantenere un namespace `ts-`/`tk-` **solo** per
  componenti realmente specifici del modulo (card portfolio `pf-*`, KPI `tl-admin-kpi`,
  tabella attività `tl-table`), ribasati su token e con `body.theme-dark` corretto.
- **Assorbire i blocchi `<style>` per-template** dentro `tasks.css` dove il pattern è
  condiviso; eliminare gli hex chiari hardcodati (`#fff`, `#dbeafe`, `#1d4ed8`, gradienti)
  sostituendoli con token e/o varianti `body.theme-dark`.
- **Riusare i componenti condivisi** dove esistono: `.btn` (con `.btn-loading` già gestito da
  base.html), `core/components/status_badge.html`, `page_header.html`.

### 4.4 Ricchezza preservata

- **Card portfolio con cover** (`pf-card` / `pf-card-cover` colorata per stato VRF): concept
  mantenuto; i gradienti `ok`/`warn`/`blocked`/`na`/`pending` diventano token-driven con
  varianti `body.theme-dark` invece degli hex fissi.
- **KPI colorati** (`tl-admin-kpi c-blue|amber|teal|purple|red`): mantenuti, ribasati su
  `--hub-status-*` (success/warning/info/neutral/danger) con background/foreground coerenti in
  entrambi i temi.

---

## 5. Confini (YAGNI)

**Dentro F1:** solo chrome + token + dark-mode + responsività + policy larghezza. Comportamento,
route, permessi e dati **invariati**.

**Fuori da F1 (rimandato):**
- Indicatore readiness/salute commessa → **F2**.
- Board per stato/fase, Calendario incontri, Timeline cross-commessa → **F3** (con nuove route
  e relativi binding ACL + `API_ACL_GATE_PATHS`).
- Qualsiasi nuova route o vista, refactor di view/model, modifiche a VRF/Gantt logic.

---

## 6. File impattati (previsti)

- `django_app/tasks/templates/tasks/base_shell.html` → sostituito da `tasks/base.html`
  (extends `core/base.html`), + aggiornamento di tutti i template che estendono la shell.
- `django_app/tasks/templates/tasks/*.html` (~15): passaggio a `page_header`, rimozione
  `<style>` chiari, uso token, wrapper tabelle. Nuovo `tasks/_project_tabs.html`.
- `django_app/tasks/static/tasks/css/tasks.css`: riscrittura su token `--hub-*`.
- `django_app/core/templates/core/base.html`: aggiunta block `content_class` (default vuoto).
- `django_app/core/static/core/css/theme.css`: aggiunta `.content--wide`; adeguamento regola
  `.content > .ts-shell`.
- Nuova **migrazione dati** in `core/migrations/` per i `NavigationItem` di subnav tasks.
- `CHANGELOG.md` (obbligatorio) + `README.md` (catalogo moduli / sezione tasks) + bump versione
  se cambia UI user-facing.

---

## 7. Strategia di verifica

- **Iso-funzionalità:** nessuna modifica a `views.py`, `urls.py`, `models.py`, `acl_bootstrap`
  (salvo eventuale allineamento `parent_code` nav). Route e permessi invariati.
- **Smoke manuale** (runserver, `config.settings.dev`) di ogni pagina in **light + dark**:
  Dashboard, Kickoff (portfolio), Dettaglio task, Form, Gantt (wide), Incontri, Dettaglio
  incontro, Impostazioni, Import. Verifica: subnav con active-state corretto; tab-commessa
  corrette; nessun testo illeggibile in dark; tabelle scrollabili; griglie responsive.
- **Test app:** `python django_app\manage.py test django_app.tasks --settings=config.settings.test --keepdb`.
- **Blast radius core:** `core/base.html` + `theme.css` sono globali. Mitigazione: block
  `content_class` default-vuoto (nessun impatto sulle pagine esistenti) e `.content--wide`
  puramente opt-in. Verifica di controllo su 2–3 pagine non-tasks (es. dashboard, una lista
  anagrafica) che il layout resti invariato.
- Nessuna esecuzione della suite completa (vincolo risorse del progetto).

## 8. Note operative

- **Modifiche sempre nel checkout locale** dell'utente (`C:\Dev\Portale Novicrom`), non solo su
  git/origin. Se si lavora in worktree isolato, chiudere con merge/FF nel tree principale.
- **Prod gira `feature/skill-matrix-mod187`**, non `main`.
- Rispettare la regola subnav: voci **sempre** via `NavigationItem`, mai hardcodate nel template.

---

## Fonti confronto web

- List UI design examples & tips — Eleken: https://www.eleken.co/blog-posts/list-ui-design
- Task management dashboard patterns — Nicelydone: https://nicelydone.club/tags/task-management-dashboard
- Linear vs ClickUp — Guru: https://www.getguru.com/reference/linear-vs-clickup
- Dashboard UI/UX principles 2025 — Medium: https://medium.com/@allclonescript/20-best-dashboard-ui-ux-design-principles-you-need-in-2025-30b661f2f795
- Project portfolio dashboard guide — Teamhood: https://teamhood.com/project-management/project-portfolio-dashboard/
- Portfolio dashboards & health — Wrike: https://www.wrike.com/blog/project-portfolio-dashboard/
- Portfolio dashboard types — Smartsheet: https://www.smartsheet.com/content/project-portfolio-dashboards
