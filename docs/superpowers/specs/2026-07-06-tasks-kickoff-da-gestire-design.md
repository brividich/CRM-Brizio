# KICK-OFF (`tasks`) — Centro "Da gestire" (portfolio/PM)

- **Data:** 2026-07-06
- **Modulo:** `django_app/tasks` (gestione KICK-OFF)
- **Branch:** `feature/skill-matrix-mod187`
- **Stato:** Design approvato, in attesa di piano
- **Prerequisiti:** F1 (uniformazione UI) + F2 (readiness) — riusa `tasks/readiness.py`.

---

## 1. Contesto e obiettivo

Terza tappa funzionale del modulo KICK-OFF (feature "B" dal menu). Un **Centro "Da gestire"**
orientato a chi gestisce le commesse (PM/portfolio): eleva i segnali già calcolati — readiness (F2)
e i KPI admin (`unassigned`/`without_due_date`/`stale_in_progress`) — da **conteggi** a **liste
azionabili** con link mirati al punto in cui intervenire.

**Non duplica** l'aggregatore personale cross-modulo esistente `dashboard.views_mie_attivita.
build_cose_da_gestire` (anomalie/ticket/approvazioni/DPI/formazione/procedure/sicurezza), che **non**
tocca KICK-OFF. Questo è specifico del modulo e portfolio-oriented, complementare.

**Valore:** un PM apre una pagina e vede subito cosa richiede intervento sulle commesse, con un clic
per andarci. **Rischio contenuto:** solo lettura + navigazione, nessun endpoint di mutazione.

---

## 2. Unità isolata

Nuovo `django_app/tasks/da_gestire.py` — logica pura, isolata e testabile:

```python
def build_kickoff_da_gestire(request, scope: str) -> dict:
    """scope ∈ {"portfolio", "mine"}. Ritorna {"sections": [...], "total": int}."""
```

Segue la **stessa forma di sezione** dell'aggregatore esistente per coerenza:
`{"key", "label", "tone", "icon", "items", "all_url", "empty"}`, dove ogni `item` è
`{"label", "url", "meta"}` (`meta` = chip/motivo opzionale). Ogni sezione è calcolata da un helper
piccolo e **difensivo** (try/except: un errore in una sezione non rompe la pagina), come
`build_cose_da_gestire`.

Riusa `tasks/readiness.py` (`annotate_readiness_qs`, `compute_project_readiness`) per la sezione
"Commesse non pronte".

---

## 3. Le 4 sezioni (tutte da dati esistenti)

| Sezione | Query | Item → link | all_url |
|---|---|---|---|
| **VRF da caricare** | progetti `vrf_status = PENDING` | commessa → `tasks:project_vrf_upload` | `tasks:project_list?vrf_status=pending` |
| **Commesse non pronte** | progetti con readiness `notready`/`partial` (gate F2) | commessa → dashboard progetto `tasks:list?project=<id>`; `meta` = criteri mancanti | `tasks:project_list` |
| **Attività critiche** | attività aperte con: scaduta (`due_date < oggi`) · non assegnata · senza data fine · ferma in corso `>7gg` | attività → `tasks:detail`; `meta` = motivo | `tasks:list?mine=0` |
| **Incontri da chiudere** | incontri con `MeetingIssue` `status=OPEN` | incontro → verbale `tasks:project_meeting_detail`; `meta` = n° problemi aperti | *None* (nessun elenco cross-commessa) |

- **Top 20** item per sezione (ordinati per urgenza dove sensato: scadenza, poi aggiornamento); se
  ci sono più elementi, `all_url` porta all'elenco filtrato completo (dove esiste).
- `all_url` è `None` quando non esiste un elenco corrispondente (Incontri).

---

## 4. Scope toggle (Portfolio / Le mie)

Parametro GET `?scope=portfolio|mine`.

- **Portfolio**: `_scoped_projects_queryset(request)` / `_scoped_tasks_queryset(request)` (l'intero
  scope di chi guarda — già limitato da ACL/scope per i non-admin).
- **Le mie**: filtro all'utente corrente —
  - commesse: `project_manager` **o** `capo_commessa` **o** `programmer` **o** `created_by` = utente;
  - attività: `created_by` **o** `assigned_to` **o** `subscribers` = utente (come `task_list`).
- **Default**: `portfolio` se scope-admin (`_has_task_permission(request, "tasks_admin")`), altrimenti
  `mine`. Toggle visibile per cambiare.

---

## 5. Pagina, navigazione e ACL

- **Route**: `tasks:da_gestire` → `/tasks/da-gestire/`, view `da_gestire(request)`.
- **Template**: `tasks/templates/tasks/da_gestire.html` (usa la shell del modulo + componenti
  `ts-panel` + badge readiness) e partial riusabile `tasks/templates/tasks/_da_gestire_section.html`.
- **Subnav**: nuova `NavigationItem` "Da gestire" (`section="subnav"`, `parent_code="tasks"`, gated
  `required_permission_code="tasks.kickoff.view"`, order tra Dashboard e Kickoff) — migrazione dati.
- **ACL (obbligatorio)**: aggiungere il binding `"tasks:da_gestire": "tasks.kickoff.view"` in
  `tasks/acl_bootstrap.py` `_ROUTE_BINDINGS` e **bump della cache-key** bootstrap (`_BOOTSTRAP_CACHE_KEY`
  `v4→v5`), altrimenti `ACL_STRICT_CANONICAL` nega la route ai non-superuser (403). È una pagina
  (non `/api/`), quindi **non** serve `API_ACL_GATE_PATHS`.
- **Link da dashboard**: nella sezione admin di `list.html`, mantenere i KPI come sintesi e
  aggiungere un link "Vai a «Da gestire»" → `tasks:da_gestire`.

---

## 6. Confini (YAGNI)

**Dentro:** pagina dedicata con 4 sezioni azionabili (link), toggle scope, link da dashboard.
**Fuori:** azioni/mutazioni inline (assegna/imposta data) e relativi endpoint POST; nuovi modelli;
paginazione per sezione (solo top-20 + link); aggregazione cross-modulo (resta separata dal
`build_cose_da_gestire` personale); notifiche/badge di conteggio nella navbar.

---

## 7. Verifica

- **Unit** su `build_kickoff_da_gestire`: ogni sezione popolata dal segnale giusto (VRF pending;
  readiness notready/partial; attività per ciascun motivo; incontri con issue OPEN); scope
  `portfolio` vs `mine` filtra correttamente; sezione vuota → `items=[]` + `empty`; `total` = somma;
  difensività (una sezione che solleva non rompe il resto).
- **Smoke render** della pagina (superuser + fixture): HTTP 200, sezioni presenti, toggle presente.
- **ACL**: test che la route `tasks:da_gestire` è **bound** a `tasks.kickoff.view` dopo bootstrap
  (un utente con permesso vede la pagina; il binding esiste).
- `python django_app\manage.py test tasks.<Class> --settings=config.settings.test --keepdb`;
  `manage.py check`. Mai la suite completa.

---

## 8. Note operative

- Import modelli esterni **locali** nelle funzioni di view/logica (regola progetto).
- Attributi template senza underscore iniziale.
- Nuova route → ricordarsi binding ACL + bump cache bootstrap (§5); in dev rilanciare il bootstrap
  (o `migrate`/restart) perché il binding entri in vigore.
- A fine lavoro: `CHANGELOG.md` + `README.md`. Modifiche nel checkout locale; prod gira
  `feature/skill-matrix-mod187`.
