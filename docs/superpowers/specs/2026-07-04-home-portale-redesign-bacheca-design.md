# Redesign Home Portale — "Bacheca" (info-hub) + Documenti & Collegamenti

**Data:** 2026-07-04
**Stato:** Design approvato (impianto), in attesa di piano di implementazione
**App coinvolte:** `dashboard` (home + pagina bacheca), `core` (modelli + storage), `admin_portale` (gestione)
**Branch di lavoro atteso:** `feature/skill-matrix-mod187` (branch che gira in prod — vedi nota deploy)

---

## 1. Contesto e obiettivo

La home attuale (`dashboard/views_home_portale.py` + `templates/dashboard/pages/home_portale.html`) è
densa: hero, 4 KPI, brief AI, cockpit "Le mie attività", moduli raggruppati in 5 categorie con mini-KPI,
presenze settimana, news+attività, KPI sicurezza, stato sistema — tutto a sezioni comprimibili. Troppa
densità = poca gerarchia.

**Obiettivo:** una home **diretta, semplice, chiara**, ripensata come **bacheca aziendale (info-hub)**:
News e una nuova sezione **Documenti & Collegamenti** (gestita dall'amministrazione) come protagonisti,
mantenendo sempre una sezione **Cose da fare**. Redesign radicale (sostituzione della home attuale), non
evoluzione.

### Criteri di successo
- L'utente capisce in 3 secondi "cosa c'è di nuovo / cosa mi serve" senza scroll infinito.
- L'admin gestisce Documenti & Collegamenti in autonomia (categorie, voci, ordine, visibilità per ruolo).
- I file caricati restano fuori dalla webroot e passano da ACL + audit.
- **Il tema del portale non cambia** (nessuna nuova palette).

---

## 2. Decisioni bloccate (dalle domande di brainstorming)

| Tema | Decisione |
|---|---|
| Ambito | **Redesign radicale**: si sostituisce l'attuale `home_portale`. |
| Scopo primario (3 sec) | **Info-hub**: News + Documenti/Collegamenti protagonisti, moduli secondari. |
| Sezione sempre presente | **Cose da fare** (riuso `build_cose_da_gestire()`). |
| Tipi di voce Documenti & Coll. | **File caricati**, **Link esterni (URL)**, **Scorciatoie interne** (route Django). NO share UNC. |
| Gestione admin | **Categorie + visibilità per ruolo** (modello leggero tipo `NavigationRoleAccess`). |
| Elementi tenuti (compatti/secondari) | 4 KPI prioritari, Brief AI, launcher moduli **solo home dei moduli**. |
| Elementi eliminati | Presenze settimana, KPI sicurezza, stato sistema, gruppi-moduli con mini-KPI, comprimibili ridondanti. |
| Layout | **Approccio A "Bacheca"** a 2 colonne (vedi §4), come da mockup approvato. |

Mockup interattivo approvato: Artifact "Nuova Home NOVICROM HUB — Approccio A" (light/dark + toggle Utente/Admin).

---

## 3. Vincoli

### 3.1 Tema (HARD)
Riusare i token esistenti di `core/static/core/css/theme.css` (`--primary #002b5c`, `--accent #ff6b00`,
`--bg`, `--surface`, `--border`, `--text`, `--success/--warning/--danger`, `--radius`, font **Outfit**) e il
dark mode esistente (`body.theme-dark`). **Nessuna nuova palette, nessun nuovo font, nessuna ridefinizione di
token di tema.** (I token `--nx-*` del mockup Artifact esistevano solo perché l'Artifact è isolato.)
Il nuovo CSS home può vivere in `core/static/core/css/home_portale.css` (riscritto) o file affiancato.

### 3.2 Sicurezza (HARD)
- **File caricati fuori webroot**: nuovo storage `HubLinkStorage(EncryptedStorageMixin, FileSystemStorage)`
  in una private root (es. `settings.HUB_BACHECA_PRIVATE_ROOT`, default `media_private/hub_links/`), cifratura
  at-rest via `DOCUMENT_ENCRYPTION_KEY` — stesso pattern di `anagrafica/storage.py`. `url()` solleva
  `NotImplementedError`: i file si servono SOLO dalla view protetta.
- **Download protetto + audit**: view `dashboard:hub_link_download(pk)` con `@login_required`, che verifica la
  **visibilità per ruolo** dell'utente sulla voce prima di restituire il file (`FileResponse`), e logga
  l'accesso.
- **ACL gate paths** (CRITICO, cfr. `acl_middleware_api_gate_paths`): ogni nuova rotta API/AJAX (salvataggio
  ordine, toggle, upload) va mappata in `core/middleware.py` `API_ACL_GATE_PATHS` verso una risorsa ACL bound,
  altrimenti `ACL_STRICT_CANONICAL` la nega ai non-superuser (403). Le rotte admin sono comunque admin-only; la
  rotta di download è per tutti gli autenticati ma con check di ruolo interno.
- **API protette → JSON 401/403**, non redirect HTML.
- **GDPR**: la sezione è pensata per documenti aziendali (modulistica, organigramma, SGI), non dati personali.
  Resta la barriera ACL/fuori-webroot; non caricare qui documenti con dati personali di dipendenti (quelli
  restano in `anagrafica`).

### 3.3 Deploy (HARD)
- **Modelli in `core`, NON in una nuova app.** Il Setup Wizard fa `migrate` **selettivo** dal
  `MODULE_REGISTRY` e salta le app non elencate → 500 in prod per tabelle mancanti (cfr.
  `setup_wizard_selective_migrate_pitfall`). `core` è sempre migrata: si evita il rischio alla radice.
- Prod gira il branch `feature/skill-matrix-mod187` (non `main`): sviluppare qui.

---

## 4. Approccio A — Layout / Information Architecture

Ordine verticale (News+Documenti in alto = scelta info-hub):

```
┌─────────────────────────────────────────────────────────┐
│ TOPBAR portale (invariata)                               │
├─────────────────────────────────────────────────────────┤
│ Saluto snello: "Buongiorno, {nome}"  · data/ora · [ruolo]│  greeting bar
├─────────────────────────────────────────────────────────┤
│ [KPI ⚠ anomalie][KPI 🎫 ticket][KPI ✔ task][KPI ✓ appr.] │  KPI strip (4)
├───────────────────────────┬─────────────────────────────┤
│ 📰 NEWS AZIENDALI          │ 📎 DOCUMENTI & COLLEGAMENTI  │  BACHECA 2 col
│  (ultime 4-5)             │  categorie → voci (file/url/  │
│                           │  interna), anteprima N per   │
│                           │  categoria + "Apri tutti →"  │
├───────────────────────────┴─────────────────────────────┤
│ ✅ COSE DA FARE (anomalie / ticket / approvazioni …)     │  card larga
├─────────────────────────────────────────────────────────┤
│ 🤖 Brief AI del giorno (compatto)                        │
├─────────────────────────────────────────────────────────┤
│ 🧩 MODULI (launcher, solo home moduli, badge conteggio)  │  griglia
├─────────────────────────────────────────────────────────┤
│ Footer: versione · ACL v2 attivo                         │
└─────────────────────────────────────────────────────────┘
```

**Responsive:** sotto ~900px la bacheca collassa a colonna singola (News poi Documenti), i KPI passano a 2×2,
il launcher riduce le colonne. Coerente con le fondamenta responsive del portale (`theme.css .content` cap
1680; cfr. `responsive_audit_portale`) — usare wrapper/`min-width:0`, nessun `overflow:hidden` che tagli.

**Dettaglio Documenti & Collegamenti (colonna dx):**
- Raggruppato per **categoria** (header: icona + nome + contatore).
- Ogni voce: icona per tipo, titolo, descrizione breve, **badge tipo** (File / Link / Interna).
- Distinzione tipo con colore semantico dei token: File = `--danger`, Link = `--info`/`--primary-mid`,
  Interna = `--accent`.
- Anteprima: prime **N (default 4)** voci visibili per categoria + "Apri tutti →" verso la pagina `/bacheca/`.

---

## 5. Modello dati (`core/models.py`)

Tre modelli, coerenti con lo stile di `NavigationItem`/`NavigationRoleAccess`.

### 5.1 `HubLinkCategory`
```
name              CharField(120)
slug              SlugField(unique)
icon              CharField(500, blank)   # emoji/alias SVG/URL, come NavigationItem.icon
description       CharField(255, blank)
order             IntegerField(default=100)
is_visible        BooleanField(default=True)      # on/off globale categoria
created_by/updated_by  FK user (SET_NULL, null)
created_at/updated_at  auto
Meta.ordering = ["order", "name", "id"]
```

### 5.2 `HubLink`
```
KIND = [("file","Documento"),("url","Collegamento esterno"),("internal","Scorciatoia interna")]
category          FK HubLinkCategory (related_name="links", on_delete=CASCADE)
kind              CharField(choices=KIND)
title             CharField(160)
description       CharField(300, blank)
icon              CharField(500, blank)
# target per kind:
url               CharField(500, blank)   # kind=url  (http/https)
route_name        CharField(160, blank)   # kind=internal (nome URL Django, con namespace)
route_kwargs      JSONField(default=dict, blank)   # kwargs opzionali per reverse()
file              FileField(storage=HubLinkStorage, upload_to="…", blank, null)  # kind=file
original_filename CharField(255, blank)   # metadato display
file_size         PositiveIntegerField(null, blank)
content_type      CharField(120, blank)
open_in_new_tab   BooleanField(default=False)      # tipicamente True per kind=url
order             IntegerField(default=100)
is_visible        BooleanField(default=True)
created_by/updated_by  FK user (SET_NULL, null)
created_at/updated_at  auto
Meta.ordering = ["order", "title", "id"]

clean(): valida che sia presente ESATTAMENTE il target del kind
         (kind=url→url, kind=internal→route_name, kind=file→file) e che gli altri siano vuoti.
def resolve_href(): ritorna URL finale (url, reverse(route_name, **route_kwargs), o download view).
```

### 5.3 `HubLinkRoleAccess`  (rispecchia `NavigationRoleAccess`)
```
link            FK HubLink (related_name="role_accesses", on_delete=CASCADE)
legacy_role_id  IntegerField(db_index=True)
can_view        BooleanField(default=True)
Meta.unique_together = [("link","legacy_role_id")]
```
**Semantica visibilità (identica a NavigationRoleAccess):**
- **Nessun record** per una voce ⇒ **visibile a tutti** i ruoli (chip "Tutti").
- Con record ⇒ visibile solo ai `legacy_role_id` con `can_view=True`.
- La **categoria** è mostrata sulla home/pagina se `is_visible=True` **e** contiene ≥1 voce visibile
  all'utente. (Nessun role-access a livello categoria in v1 — vedi §12 YAGNI.)

**Storage:** nuovo `core/hub_bacheca_storage.py` (o dentro `core/storage.py`):
```python
class HubLinkStorage(EncryptedStorageMixin, FileSystemStorage):
    # base_location = settings.HUB_BACHECA_PRIVATE_ROOT  (default media_private/hub_links/)
    # url() -> NotImplementedError
```
Settings: `HUB_BACHECA_PRIVATE_ROOT` in `config/settings/base.py` (default sotto una private root già
esistente), fuori webroot.

---

## 6. Rendering (view + template)

### 6.1 Home (`dashboard/views_home_portale.py`)
- Riscrittura snella di `home_portale()` e del template `home_portale.html`.
- **Riuso** helper esistenti: `_priority_kpis` / `_tile_kpi_counts` (per i 4 KPI), `build_cose_da_gestire()`
  (Cose da fare), `_news_items()` (News), brief AI (`ai_assistant/partials/daily_brief_widget.html`),
  `_module_groups()` **ridotto a launcher** (una card per modulo = home modulo, niente sotto-pulsanti né
  mini-KPI; si può derivare da `_MODULE_CATALOG`).
- **Nuovo builder** `_documenti_collegamenti(request, preview=True)`:
  - carica categorie visibili con le loro voci visibili filtrate per ruolo dell'utente
    (`legacy_role_id` dell'utente vs `HubLinkRoleAccess`),
  - ordina per `order`,
  - in modalità preview limita a N voci per categoria,
  - ritorna struttura `[{category, items:[{title, kind, href, description, icon, badge, open_in_new_tab}]}]`.
- Rimuove dal context/tempate: presenze settimana, safety_kpis, system_status, gruppi-moduli densi.

### 6.2 Pagina dedicata `/bacheca/` (`dashboard/views_bacheca.py` — nuovo file)
- `bacheca(request)`: tutte le categorie/voci visibili all'utente (no limite N), con eventuale ricerca
  testuale semplice (opzionale, vedi §12).
- `hub_link_download(request, pk)`: download protetto file (login + check ruolo + audit + `FileResponse`).

### 6.3 Admin (`admin_portale/views_bacheca.py` — nuovo file) + template
- CRUD categorie e voci (SSR + HTMX, coerente con lo stile admin_portale esistente).
- Upload file (validazione estensioni/size), scelta kind, target per kind, **multi-select ruoli** (visibilità),
  toggle `is_visible`, `order`.
- Riordino: campo `order` con controlli su/giù o drag-drop leggero (vedi §12).
- Voce di navigazione admin via **`NavigationItem`** (section subnav admin) — mai hardcodata nel template
  (cfr. `feedback_admin_subnav`).

---

## 7. Rotte

`dashboard/urls.py` (nuove):
```
path("bacheca/", views_bacheca.bacheca, name="bacheca")
path("bacheca/doc/<int:pk>/", views_bacheca.hub_link_download, name="hub_link_download")
```
`admin_portale/urls.py` (nuove, prefix /admin-portale/bacheca/…):
```
gestione lista + create/edit/delete categoria e voce + endpoint riordino/toggle (POST JSON)
```
**ACL gate:** mappare gli endpoint POST/AJAX admin e il download in `core/middleware.py`
`API_ACL_GATE_PATHS` verso risorsa ACL bound (admin per la gestione; risorsa "home/bacheca" per il download).
Il download effettua comunque il proprio check di ruolo per-voce.

---

## 8. Migrazione
- **1 migrazione in `core`** che crea `HubLinkCategory`, `HubLink`, `HubLinkRoleAccess`.
- Nessun seed di contenuti (l'admin li crea da UI). Opzionale: seed di 2-3 **categorie vuote di esempio** via
  `get_or_create(slug=…)` (mai `update_or_create`), disattivabili.
- `core` è migrata ovunque → nessun rischio Setup Wizard selective-migrate.

---

## 9. Testing (scoped, `--settings=config.settings.test`)
- `HubLink.clean()`: target coerente col kind (errore se mancante o se target incrociato).
- Visibilità per ruolo: nessun record ⇒ visibile a tutti; con record ⇒ solo ruoli abilitati; categoria nascosta
  se nessuna voce visibile.
- `_documenti_collegamenti()`: filtra correttamente per ruolo utente e rispetta `order` + limite N.
- Download: kind≠file ⇒ 404/400; utente senza ruolo ⇒ 403; utente con ruolo ⇒ 200 + `FileResponse`; file servito
  fuori webroot (mai URL pubblico).
- Admin CRUD: non-admin ⇒ 403 (verificare con utente NON superuser per scoprire eventuali gap ACL gate —
  cfr. `acl_middleware_api_gate_paths`).
- Home: il context non contiene più le sezioni rimosse; render OK con e senza voci bacheca.
- Comando: `python django_app\manage.py test django_app.dashboard django_app.core --settings=config.settings.test --keepdb`

---

## 10. Impatti documentazione / versione
- **CHANGELOG.md** `[Unreleased]`: elencare tutti i file modificati/aggiunti (obbligatorio).
- **README.md**: catalogo moduli / sezione dashboard aggiornata (nuova sezione Documenti & Collegamenti + pagina
  /bacheca/ + gestione admin).
- Cambio funzionalità user-facing ⇒ **bump versione** (da `1.2.1`) seguendo la checklist in
  `docs/ai/06_TESTING_AND_QUALITY_GATES.md` (nuova feature ⇒ minor: proposta `1.3.0`).
- Aggiornare `docs/gestione_carichi_macchina/…`? No. Se cambia la home in modo visibile, valutare screenshot doc.

---

## 11. Rischi e mitigazioni
| Rischio | Mitigazione |
|---|---|
| Blast-radius CSS sul tema condiviso | Non toccare `theme.css`; nuovo CSS usa solo variabili esistenti. |
| ACL 403 su nuove rotte per non-admin | Mappare in `API_ACL_GATE_PATHS`; testare con utente non-superuser. |
| File sensibili caricati in bacheca | Storage cifrato fuori webroot + download con check ruolo + audit; nota GDPR nei testi UI. |
| Nuova app romperebbe prod (Setup Wizard) | Modelli in `core`. |
| Working tree condiviso tra sessioni | `git add` selettivo, verifica `git diff --cached`, nessun file dati staged (cfr. `shared_worktree_staging_hazard`). |
| Perdita di funzioni utili rimosse | Presenze/safety/system restano raggiungibili dai rispettivi moduli; la home non è una security boundary. |

---

## 12. Fuori scope / YAGNI (v1)
- Role-access a livello **categoria** (in v1 solo a livello voce; categoria = contenitore on/off).
- **Ricerca/filtri** avanzati nella pagina `/bacheca/` (v1: elenco per categoria; ricerca semplice opzionale).
- Anteprime/thumbnail dei documenti, versioning dei file, analytics di click.
- Personalizzazione per-utente della bacheca (è una bacheca aziendale, gestione centralizzata).
- Drag-drop sofisticato: v1 può usare `order` con pulsanti su/giù; il drag-drop è un plus, non un requisito.

---

## 13. Deliverable dell'implementazione (sintesi)
1. `core`: modelli + storage + migrazione + settings private root.
2. `dashboard`: home riscritta (view + template + CSS) usando i token esistenti; pagina `/bacheca/`; download view.
3. `admin_portale`: gestione CRUD (view + template + urls) + voce `NavigationItem`.
4. `core/middleware.py`: mapping `API_ACL_GATE_PATHS`.
5. Test scoped; CHANGELOG/README; bump versione.
