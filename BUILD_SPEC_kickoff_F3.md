# KICK-OFF (`tasks`) — F3: identità normalizzata · registro azioni · panoramica commessa

- **Data:** 2026-09-02
- **Modulo:** `django_app/tasks`
- **Branch suggerito:** `feature/kickoff-f3-fruibilita`
- **Stato:** design approvato, pronto per esecuzione
- **Prerequisiti:** F1 (uniformazione UI), F2 (readiness), `da_gestire` — tutti già in `main`

---

## 0. RECON — obbligatoria, prima di scrivere una riga

Questa spec cita firme e numeri di riga rilevati al momento della stesura. **Verificale sul codice
reale prima di modificare qualsiasi cosa** e, se divergono, adegua il piano e annota la divergenza
in `RECON.md` (file temporaneo, non committato). Non inventare: se un simbolo non esiste con quel
nome, cercalo, non ricrearlo.

Da verificare esplicitamente:

| Simbolo | File atteso | Perché serve |
|---|---|---|
| `Project.save()` con retry su `IntegrityError` per `kickoff_number` | `tasks/models.py` (~riga 130) | Fase A ci si innesta sopra senza toccarne la logica |
| `ProjectKickoffForm.clean()` con match `part_number__iexact` | `tasks/forms.py` (~riga 149) | Fase A cambia i dati su cui questo match opera |
| `_scoped_projects_queryset(request)` | `tasks/views.py` (~riga 1031) | ACL di tutte le nuove view |
| `_tasks_shell_context(request, *, active, task, project)` | `tasks/views.py` | Contratto delle nuove view |
| `_can_manage_project(request, project)` | `tasks/views.py` | Gating delle azioni in Panoramica |
| `compute_project_readiness(project)`, `annotate_readiness_qs(qs)` | `tasks/readiness.py` | Riuso in Panoramica |
| `build_kickoff_da_gestire(request, scope)` e la forma sezione/item | `tasks/da_gestire.py` | Modello di stile per `action_register.py` |
| Template `_project_tabs.html`, `_readiness_badge.html`, `_readiness_checklist.html` | `tasks/templates/tasks/` | Riuso obbligatorio |
| Pattern `<datalist>` sale riunioni | `tasks/templates/tasks/project_meeting_form.html` (~riga 68 e ~286) | Modello di stile per l'autocomplete |
| `normalize_part_number()` | `attrezzature/services/kickoff_integration.py` | Parità di comportamento (vedi A.1) |

---

## 1. Obiettivo

Tre interventi di fruibilità, indipendenti fra loro ma coerenti come blocco unico. Nessun modello
nuovo, una sola migration di soli dati.

**A — Identità normalizzata.** `client_name` e `part_number` sono `CharField` liberi senza
normalizzazione. Il match duplicati in `ProjectKickoffForm.clean()` usa `__iexact`, ma non regge
spazi doppi, spazi in coda o varianti di case interne. Di conseguenza il raggruppamento per cliente
e l'aggancio al P/N (attrezzature, commesse simili, famiglia pezzo) sono inaffidabili.

**B — Registro azioni unico.** Le azioni di una commessa vivono in tre posti scollegati:
`MeetingIssue` (raggiungibile solo entrando nell'incontro giusto), `Task`, `SubTask`. Manca una
vista che risponda alla domanda "cosa è aperto su questa commessa e chi ce l'ha".

**C — Panoramica commessa.** Aprendo una commessa si atterra sul Gantt. `_project_tabs.html`
espone tre tab (Gantt · Incontri · VRF), tutte specialistiche. Manca la landing che dice come sta
la commessa.

**Valore:** nessuna nuova procedura da far adottare a nessuno, nessun dato nuovo da inserire.
Solo dati già presenti, esposti dove servono.

---

## 2. Vincoli non negoziabili

1. **Zero invenzione.** Ogni riferimento a un simbolo deve corrispondere a codice reale verificato
   in RECON.
2. **Nessun modello nuovo, nessun campo nuovo.** L'unica migration è una data migration (A.2).
3. **Nessuna dipendenza nuova.** SSR Django + HTMX + CSS esistente. Nessuna libreria JS, nessun
   componente frontend importato.
4. **`Project.save()` non si riscrive.** La normalizzazione si innesta come primo blocco del metodo.
   La logica di generazione `kickoff_number` con retry su `IntegrityError` resta identica, carattere
   per carattere.
5. **`vrf_catalog.py` non si tocca.** Fuori scope.
6. **Le nuove view sono read-only.** Nessun endpoint di mutazione in F3: ogni riga del registro
   azioni linka agli endpoint di mutazione già esistenti.
7. **ACL:** ogni nuova view parte da `_scoped_projects_queryset(request)` e usa gli stessi
   decoratori delle view sorelle. Nessuna permission nuova, nessuna voce ACL nuova.
8. **Endpoint JSON:** in caso di utente non autorizzato devono rispondere `401`/`403` JSON, mai
   redirect HTML (regola `CLAUDE.md`).
9. **Lingua UI: italiano.** Stile coerente con le classi già in uso (`ts-*`, `pf-*`, `input`,
   `btn btn-secondary btn-sm`) e con la palette navy/cyan/orange. Non introdurre un nuovo design
   system dentro `tasks`.
10. **Sessioni sequenziali.** Un subagente alla volta (vincolo RAM documentato in `CLAUDE.md`).

---

## 3. Fase A — identità normalizzata

### A.1 — Modulo puro `tasks/identity.py`

Nuovo file, logica pura, zero import Django tranne quelli strettamente necessari.

```python
def normalize_part_number(value: str | None) -> str:
    """Upper + strip + collasso spazi interni. '  4a-77 821 ' -> '4A-77 821'."""

def normalize_client_name(value: str | None) -> str:
    """Strip + collasso spazi interni. NON upper: e' una ragione sociale."""
```

`normalize_part_number` deve produrre lo **stesso identico output** di
`attrezzature.services.kickoff_integration.normalize_part_number`, perché è la funzione che governa
l'aggancio attrezzatura↔P/N.

**Non importare da `attrezzature`**: introdurrebbe una dipendenza inversa fra app operative.
Duplica la funzione e scrivi un test di parità che importa entrambe e verifica l'uguaglianza su un
set di casi (spazi doppi, tab, case misto, `None`, stringa vuota, caratteri accentati).

### A.2 — Normalizzazione in `Project.save()`

Innesta come **primo blocco** del metodo, prima di qualunque logica esistente:

```python
def save(self, *args, **kwargs):
    self.part_number = normalize_part_number(self.part_number)
    self.client_name = normalize_client_name(self.client_name)
    # ... logica kickoff_number esistente, invariata ...
```

Verifica che il percorso `if not self._state.adding:` e il retry su `IntegrityError` restino
funzionalmente identici. I test esistenti su `kickoff_number` devono passare senza modifiche: se
uno fallisce, hai toccato qualcosa che non dovevi.

### A.3 — Data migration

Migration in `tasks/migrations/`, `RunPython(forward, migrations.RunPython.noop)`.

`forward` deve:

- iterare i `Project` con `.iterator()` e aggiornare in bulk a blocchi (evita di caricare tutto in
  memoria e di scatenare `save()` per riga — usa `queryset.update()` o `bulk_update`, **non**
  `instance.save()`, per non rigenerare `kickoff_number`);
- essere **idempotente**: rieseguirla non deve cambiare nulla;
- stampare a fine esecuzione quanti record sono stati modificati;
- **rilevare e segnalare le collisioni** senza risolverle. Dopo la normalizzazione può emergere che
  due `Project` storici condividono la stessa terna `(part_number, revisione, versione)`. La
  migration **non deve fondere, cancellare o rinominare nulla**: stampa l'elenco delle terne
  duplicate con gli id coinvolti, per revisione manuale successiva. Una fusione automatica di
  commesse è fuori discussione.

### A.4 — Endpoint di suggerimento

Nuova view `identity_suggest`, URL `tasks/projects/identity-suggest/`, nome
`tasks:identity_suggest`.

- Query param `field` ∈ `{client, part_number}` e `q` (prefisso, minimo 1 carattere).
- Base: `_scoped_projects_queryset(request)` — l'autocomplete non deve mai rivelare clienti o P/N
  di commesse fuori dallo scope ACL dell'utente.
- Ritorna `{"values": [...]}`, `values_list(...).distinct()`, ordinato alfabeticamente, **massimo
  20 elementi**.
- `401`/`403` JSON per non autorizzati.
- Nessun `log_action`: è una lettura ad alta frequenza, loggarla inquinerebbe l'audit trail.

### A.5 — Aggancio nel form di creazione

In `project_create.html`, aggancia due `<datalist>` ai campi `client_name` e `part_number`
replicando **esattamente** il pattern già usato per le sale riunioni in
`project_meeting_form.html`: fetch al primo focus, popolamento del `<datalist>`, `setAttribute('list', …)`.
Nessuna libreria, nessun debounce elaborato — un `input` con soglia di 1 carattere e fetch su
`change` è sufficiente per il volume reale.

`ProjectKickoffForm` non cambia. Il suo `clean()` continua a fare match `__iexact`, che dopo la
normalizzazione diventa affidabile invece che approssimativo.

---

## 4. Fase B — registro azioni unico

### B.1 — Modulo puro `tasks/action_register.py`

Stesso stile di `readiness.py` e `da_gestire.py`: logica pura, dataclass frozen, testabile senza
request.

```python
@dataclass(frozen=True)
class ActionRow:
    origin: str        # "issue" | "task" | "subtask"
    obj_id: int
    title: str
    owner_label: str   # display utente, "" se non assegnato
    due_date: date | None
    is_open: bool
    is_overdue: bool
    source_label: str  # "Incontro 3" | "Attivita" | "Sotto-attivita di «...»"
    url: str


def build_project_actions(project, *, include_closed: bool = False) -> list[ActionRow]:
    ...
```

**Sorgenti e mappatura:**

| Origine | Queryset | Aperto quando | `url` |
|---|---|---|---|
| `issue` | `project.meeting_issues.select_related("assigned_to", "source_meeting")` | `status == MeetingIssueStatus.OPEN` | `tasks:project_meeting_detail` dell'incontro di origine, ancora `#issue-<id>` |
| `task` | `project.tasks.select_related("assigned_to")` | `status not in {DONE, CANCELED}` | `tasks:detail` |
| `subtask` | `SubTask.objects.filter(task__project=project).select_related("assigned_to", "task")` | `status not in {DONE, CANCELED}` | `tasks:detail` del task padre |

**`is_overdue`** deve avere una semantica unica su tutte e tre le origini: `due_date` valorizzata,
`due_date < timezone.localdate()`, e riga ancora aperta. Per i task riusa la property
`Task.is_overdue` invece di riscrivere la condizione.

**Ordinamento** (unico, deterministico):

1. aperte e scadute, per `due_date` crescente;
2. aperte con scadenza futura, per `due_date` crescente;
3. aperte senza scadenza, per titolo;
4. chiuse in fondo (solo se `include_closed=True`).

Tie-break finale su `(origin, obj_id)` per stabilità dell'ordine fra chiamate.

**Performance:** massimo una query per sorgente, tutte con `select_related`. Nessun accesso a
`.task.title` o `.source_meeting.numero` fuori dalle relazioni precaricate. La `source_label` di un
issue senza `source_meeting` è `"Senza incontro"`, non un crash.

**Difensività:** come in `da_gestire.py`, ogni sorgente è raccolta in un helper separato avvolto in
`try/except`; il fallimento di una sorgente non deve svuotare la pagina.

### B.2 — View, URL, template

- `project_actions(request, project_id)` in `tasks/views_projects.py` (vedi §6).
- URL: `tasks/projects/<int:project_id>/azioni/`, nome `tasks:project_actions`.
- Template `project_actions.html`: tabella con colonne Azione · Origine · Responsabile · Scadenza ·
  Stato. Le righe scadute prendono il tono `danger` già usato in `da_gestire`. Filtro a due stati
  via query param `?closed=1` (mostra anche le chiuse), niente JS.
- `_tasks_shell_context(request, active="actions", project=project)`.
- Contatore in cima: "N aperte, M scadute".
- Empty state: "Nessuna azione aperta su questa commessa." + link a creazione attività. Non
  scrivere "Niente qui".

---

## 5. Fase C — panoramica commessa

### C.1 — View `project_overview`

- URL: `tasks/projects/<int:project_id>/`, nome `tasks:project_overview`. **Diventa la landing
  della commessa.**
- Attenzione al conflitto di routing: `tasks/projects/new/` è già registrato. Verifica l'ordine in
  `urls.py` — le rotte letterali devono precedere quella con `<int:project_id>`; con un converter
  `int` non c'è ambiguità, ma controllalo comunque.

**Contesto da produrre** (tutto da dati esistenti, nessuna query nuova pesante):

| Blocco | Fonte |
|---|---|
| Intestazione: nome, P/N + revisione, cliente, team a 3 ruoli, fase | campi `Project` |
| Badge readiness | `compute_project_readiness(project)` + `_readiness_badge.html` |
| Metrica "azioni aperte" | `build_project_actions(project)` — conteggio, riusa la stessa chiamata |
| Metrica "prossimo incontro" | primo `project.meetings` con `stato=PIANIFICATO` e `data >= oggi` |
| Metrica "attività a piano" | `project.tasks.filter(due_date__isnull=False).count()` su `project.tasks.count()` |
| Top 5 azioni in scadenza | primi 5 di `build_project_actions(project)` |
| Ultimi 3 incontri | `project.meetings.order_by("-numero")[:3]` con stato |
| Checklist readiness | `_readiness_checklist.html` riusata così com'è |

Le CTA presenti nella checklist readiness restano quelle già calcolate da `readiness.py`: non
duplicare la logica delle URL di azione nella view.

`_can_manage_project(request, project)` governa la visibilità dei pulsanti di modifica; la pagina
resta leggibile per chi ha solo lettura.

### C.2 — Tab

Estendi `_project_tabs.html` a cinque voci, in quest'ordine fisso:

`Panoramica` · `Azioni` · `Incontri` · `Piano` · `VRF`

dove `Piano` punta a `tasks:project_gantt` (rinominata: "Gantt" è il come, non il cosa). Slug
`active`: `overview`, `actions`, `meetings`, `gantt`, `vrf`. Aggiorna `active="..."` in **tutte** le
view che già rendono il tab bar, non solo nelle nuove.

La tab `Azioni` mostra il conteggio delle aperte come suffisso quando > 0.

### C.3 — Ridirezione dei punti d'ingresso

In `projects.html`, i link che oggi puntano a `tasks:project_gantt` come apertura della commessa
devono puntare a `tasks:project_overview`:

- il link sul nome (`pf-name-link`, ~riga 412);
- il pulsante di apertura scheda nella card (~riga 495 — **valuta**: se il pulsante si chiama
  "Gantt" ed è affiancato da "Attività" e "Incontri", lascialo puntare al Gantt e rendi cliccabile
  la card verso la Panoramica. Decidi una sola convenzione e applicala ovunque).

Cerca in tutto il repo (`templates/`, `views.py`, `da_gestire.py`) altri `reverse("tasks:project_gantt")`
usati con il significato di "apri la commessa" e adeguali.

---

## 6. Dove va il codice nuovo

`tasks/views.py` è a ~6.800 righe. **Non fare lo split integrale in questo intervento** — sarebbe un
diff enorme mescolato a modifiche funzionali, impossibile da revisionare.

Fai invece la mossa a basso rischio:

1. Crea `tasks/views_projects.py` contenente **solo le view nuove**: `project_overview`,
   `project_actions`, `identity_suggest`.
2. Importa in cima da `views.py` gli helper condivisi (`_scoped_projects_queryset`,
   `_tasks_shell_context`, `_can_manage_project`, decoratori). Se questo crea un import circolare,
   estrai prima quegli helper in `tasks/view_helpers.py` e fai importare entrambi da lì — questa
   estrazione sì, è in scope, purché sia un puro spostamento senza cambi di comportamento.
3. In `urls.py` importa `from . import views_projects` e registra le tre rotte da lì.

Non re-esportare le nuove view da `views.py`: le rotte le importano direttamente dal modulo nuovo.

---

## 7. Cosa NON fare in questo intervento

- **Non toccare il criterio readiness "VRF a posto"** in `readiness.py`. Resta a F4. Conseguenza
  nota e accettata: nella nuova Panoramica il badge readiness resterà pessimista sulle commesse
  senza VRF.
  Le **copertine colorate** di `projects.html` guidate da `vrf_status` sono invece un'altra cosa e
  spariscono nella Passata 2 di §10, sostituite da pill di stato. Non è un'anticipazione di F4: è
  la rimozione di un elemento grafico, non un cambio della logica di readiness.
- Non introdurre `DeliverableKickoff`, il cruscotto risorse, o qualsiasi aggancio a
  `gestione_carichi_macchina` / `anagrafica.AbilitazioneMacchina`. Sono F5 e F6.
- Non cambiare `ProjectPhase` né aggiungere una FSM.
- Non aggiungere endpoint di mutazione al registro azioni.
- Non fondere né deduplicare record esistenti nella data migration.

---

## 8. Definition of done

Il lavoro è finito quando **tutti** questi punti sono verdi.

**Test nuovi** (in file separati, non dentro `tests.py` che è già a 3.605 righe):

- `tests_identity.py`
  - parità `normalize_part_number` vs quella di `attrezzature` su ≥ 8 casi limite;
  - `Project.save()` normalizza in creazione e in aggiornamento;
  - la generazione `kickoff_number` è invariata (creazione concorrente simulata, retry su
    `IntegrityError` ancora raggiunto);
  - `identity_suggest` rispetta lo scope ACL: un utente con visibilità parziale non riceve clienti
    di commesse fuori scope;
  - `identity_suggest` risponde JSON `403` (non redirect HTML) all'utente non autorizzato;
  - la data migration è idempotente (eseguita due volte → stesso stato) e non altera
    `kickoff_number`.
- `tests_action_register.py`
  - le tre origini compaiono tutte, con `source_label` corretta;
  - ordinamento: scadute prima, poi future, poi senza data, chiuse in fondo;
  - `is_overdue` coerente con `Task.is_overdue` su un task DONE con `due_date` passata (deve
    risultare **non** in ritardo);
  - issue senza `source_meeting` non fa crashare;
  - `assertNumQueries` fissa il budget query della view (dichiara il numero atteso nel test).
- `tests_project_overview.py`
  - la view rende 200 per un utente in scope, 404 per uno fuori scope;
  - le cinque tab compaiono con `active` corretto;
  - le metriche corrispondono ai dati di fixture;
  - un utente senza `_can_manage_project` non vede le CTA di modifica.

**Test esistenti:** `python django_app\manage.py test tasks` verde, senza modifiche ai test già
presenti. Se un test esistente va cambiato, fermati e spiega perché prima di toccarlo.

**Check di piattaforma:**

```powershell
python django_app\manage.py check --settings=config.settings.test
python django_app\manage.py makemigrations --check --dry-run
python django_app\manage.py secret_hygiene_check
```

**Verifica manuale:**

- creare una commessa scrivendo `"  4a-778 21 "` come P/N → salvata come `4A-778 21`;
- riaprire il form: il datalist propone clienti e P/N esistenti;
- aprire una commessa dalla lista → si atterra sulla Panoramica;
- una `MeetingIssue` aperta con scadenza passata compare in cima al registro azioni e nel blocco
  "azioni in scadenza" della Panoramica.

---

## 9. Ordine di esecuzione

Una sessione per fase, sequenziali, commit separato per fase.

| Sessione | Contenuto | Esce con |
|---|---|---|
| 1 | RECON: verifica tutti i simboli di §0, scrivi `RECON.md` | elenco divergenze, o "nessuna" |
| 2 | Fase A completa (identity.py, save, migration, endpoint, datalist) + `tests_identity.py` | test A verdi |
| 3 | `view_helpers.py` se serve + `views_projects.py` vuoto + rotte registrate | `check` verde |
| 4 | Fase B (`action_register.py`, view, template) + `tests_action_register.py` | test B verdi |
| 5 | Fase C (view, template, tab, ridirezione ingressi) + `tests_project_overview.py` | test C verdi |
| 6 | Passata finale: `test tasks` completo, `check`, `makemigrations --check`, aggiornamento `CHANGELOG.md` | tutto verde |

Se una sessione supera il budget di contesto, interrompi al confine di fase e riprendi: le fasi
sono indipendenti per costruzione.

Le sessioni 7–9 sono descritte in §10 e vanno eseguite **dopo** la 6: il restyle si applica a
pagine che a quel punto esistono già e hanno test verdi, così un test che si rompe durante la
Passata 1 o 2 segnala un problema di markup e non di logica.

---

## 10. Restyle UI del modulo (direzione approvata: media, perimetro `tasks`)

### 10.0 Principio

Il portale **ha già** un token layer: `core/static/core/css/tokens.css`, caricato globalmente da
`core/templates/core/base.html`, con scala spazi (`--hub-space-1..8`), raggi (`--hub-radius-sm..xl`),
ombre (`--hub-shadow-sm/md`) e colori di stato con background dedicati (`--hub-status-*`).
`tasks.css` oggi lo bypassa e ricrea una propria scala di raggi (`--ts-radius-sm/md/lg` = 10/14/18)
in conflitto con quella del core (`--radius` = 12) e con quella di `tokens.css`.

**Il lavoro è adozione e sottrazione, non invenzione.** Non si crea un design system nuovo, non si
modifica `tokens.css`, non si tocca `theme.css`, non si tocca il CSS di altri moduli.

### 10.1 Regole visive (valgono per tutto ciò che si tocca da qui in poi)

| Regola | Dettaglio |
|---|---|
| Token | Solo `--hub-*`. Se manca un valore, usarne uno esistente della scala — non aggiungerne di nuovi a `tokens.css` |
| Raggi | `--hub-radius-lg` (10px) per le card, `--hub-radius-md` (8px) per controlli e pill. La scala `--ts-radius-*` viene rimossa |
| Ombre | `--hub-shadow-sm` come default. `--hub-shadow-md` solo per elementi flottanti (dropdown, popover). Nient'altro |
| Gradienti | Zero. Nessun `linear-gradient`, nessun `radial-gradient`, nessun overlay noise |
| Pesi tipografici | Massimo 600. Nessun 700, 800, 900 |
| Uppercase | Solo per sigle già maiuscole nel dato (P/N, VRF, MOD.073). Mai come effetto tipografico su etichette |
| Colore | Usato solo quando codifica uno stato. Superfici e bordi restano neutri |
| Hover | Cambio di `background` o `border-color`. Nessun `transform: translateY()`, nessuna scala |
| Dark theme | `body.theme-dark` esiste già in `theme.css`: ogni regola nuova deve reggere entrambi i temi. Nessun colore hardcoded in esadecimale |

### 10.2 Passata 0 — le pagine nuove nascono già giuste

`project_overview.html` e `project_actions.html` (Fasi B e C) si scrivono **direttamente** con le
regole di §10.1 e **senza un solo blocco `<style>` inline**: tutto il loro CSS va in una sezione
dedicata di `tasks.css`. Nessuna eccezione, nemmeno "una regola sola".

Questo non è una passata separata: è un vincolo da applicare nelle sessioni 4 e 5.

### 10.3 Passata 1 — intestazione piatta

Interviene su `base_shell.html` e sul blocco `Hero` di `tasks.css`. Effetto su ~20 pagine con un
diff contenuto.

- `.ts-hero` perde i tre gradienti sovrapposti, l'ombra a 48px di blur e l'`inset` bianco.
  Diventa: `background: var(--hub-color-surface)`, hairline `border-bottom: 1px solid var(--hub-color-border)`,
  nessun `border-radius`, padding dalla scala `--hub-space-*`.
- Il testo passa da bianco su fondo colorato a `--hub-color-text` su superficie.
- `.ts-eyebrow` perde pill, `font-weight: 900`, uppercase e `letter-spacing`: diventa una riga di
  testo `--hub-color-text-muted` a 13px sopra il titolo.
- `.ts-hero-action.primary` resta l'unica azione accentata della pagina; le altre diventano
  secondarie con bordo hairline.
- **Verifica obbligatoria:** aprire almeno `projects.html`, `list.html`, `project_gantt.html`,
  `project_meetings.html`, `impostazioni.html` e controllare che nessuna di queste dipendesse dal
  fondo scuro dell'hero per la leggibilità di un elemento (chip, badge, link). Dove succede,
  correggere il colore di quell'elemento, non ripristinare l'hero.

### 10.4 Passata 2 — card della lista commesse

Interviene su `projects.html` (61 blocchi di regole inline, ~riga 28 in poi) e sulla sezione
portfolio di `tasks.css`.

- `.pf-card-cover` e le sue cinque varianti (`ok`, `warn`, `blocked`, `na`, `pending`) vengono
  **eliminate**, insieme all'overlay noise in `::before`.
- `.pf-card:hover` perde `transform: translateY(-3px)` e l'ombra a 36px; resta un cambio di
  `border-color` verso `--hub-color-steel-2`.
- Nuova struttura della card, in quest'ordine: nome commessa + giorni alla consegna sulla stessa
  riga (giorni in `--hub-status-danger` se negativi, altrimenti `--hub-color-text-muted`) · riga
  cliente + P/N + revisione · riga di pill · separatore hairline · riga team.
- Pill previste: **fase** (neutra), **azioni scadute** (`--hub-status-danger` + `-bg`, solo se > 0),
  **readiness** quando il livello non è `ready` (`--hub-status-warning` per `partial`, `danger` per
  `notready`). Il conteggio azioni arriva da `build_project_actions` (Fase B): riusa la stessa
  funzione, non riscrivere il conteggio.
- **Attenzione N+1:** la lista rende N card. `build_project_actions` per riga farebbe esplodere le
  query. Aggiungi in `action_register.py` una funzione di aggregazione
  `annotate_open_action_counts(projects_qs)` che calcola i conteggi con annotazioni sul queryset,
  e usa quella nella lista. Il test deve fissare il budget query con `assertNumQueries` su una
  lista da almeno 10 commesse.
- La sezione VRF della card (i chip `Bloccato` / `Ngg` / `Da caricare`, ~righe 483–487) **resta**
  dov'è come chip informativo: sparisce solo il colore della copertina, non l'informazione.

### 10.5 Passata 3 — rientro del CSS inline

Solo dopo che 1 e 2 sono in `main` e stabili.

Sposta i blocchi `<style>` dei template in `tasks.css`, organizzati **per componente e non per
pagina**, nell'ordine seguente (dal più contenuto al più grosso, così si impara sul piccolo):
`project_meetings.html` (30) → `project_vrf_upload.html` (27) → `projects.html` (61, già toccato
dalla Passata 2) → `detail.html` (84) → `form.html` (90) → `project_meeting_detail.html` (117) →
`list.html` (137) → `project_gantt.html` (231).

Regole: un componente per volta, un commit per file, nessun cambio di resa visiva. Se durante lo
spostamento una regola risulta morta (selettore inesistente nel template), cancellala e annotalo
nel messaggio di commit. `_meeting_form_styles.html` (370 righe, 137 blocchi) è già un parziale
dedicato: valutane lo spostamento in `tasks.css` solo se non è incluso condizionalmente.

**Non iniziare la Passata 3 nella stessa sessione della 1 o della 2.**

### 10.6 Definition of done UI

- `grep -rn "linear-gradient\|radial-gradient" django_app/tasks/` → **0 occorrenze**
  (baseline attuale: 72).
- `grep -rn "font-weight: *[789]00\|font-weight:[789]00" django_app/tasks/` → **0 occorrenze**
  (baseline attuale: 125).
- `grep -rn "text-transform: *uppercase" django_app/tasks/` → solo occorrenze giustificate da sigle,
  ognuna con commento inline che spiega perché (baseline attuale: 103).
- `grep -rn -- "--ts-radius" django_app/tasks/` → 0 occorrenze.
- Nessun colore esadecimale nuovo introdotto in `tasks.css` o nei template di `tasks`.
- Le pagine elencate in 10.3 rese e verificate **in tema chiaro e in tema scuro**.
- `python django_app\manage.py test tasks` verde: i test di template che asseriscono su classi CSS
  vanno aggiornati se e solo se la classe è stata rinominata, mai per far passare il test.
- Nessun file modificato fuori da `django_app/tasks/`.

### 10.7 Sessioni aggiuntive

| Sessione | Contenuto | Esce con |
|---|---|---|
| 7 | Passata 1 — hero piatta + rimozione scala `--ts-radius-*` | 5 pagine verificate nei due temi |
| 8 | Passata 2 — card portfolio + `annotate_open_action_counts` + test query budget | test verdi, grep gradienti a 0 su `projects.html` |
| 9 | Passata 3 — rientro CSS inline, un commit per file | grep di §10.6 tutti a 0 |
