# KICK-OFF (`tasks`) — Fase 2: Indicatore di prontezza all'avvio (Readiness)

- **Data:** 2026-07-05
- **Modulo:** `django_app/tasks` (dominio: gestione KICK-OFF = avvio commesse)
- **Branch:** `feature/skill-matrix-mod187`
- **Stato:** Design approvato, in attesa di piano di implementazione
- **Prerequisito:** F1 (uniformazione UI) — chrome condiviso già in essere.

---

## 1. Contesto e obiettivo

Dopo l'uniformazione UI (F1), la Fase 2 introduce la prima **funzionalità** del modulo KICK-OFF,
scelta con l'utente tra le proposte: un **indicatore di prontezza all'avvio** ("readiness") per
commessa. È il tema #1 dei tool di portfolio/kickoff management emerso dal confronto web (vista di
salute/prontezza a colpo d'occhio).

**Significato scelto:** *prontezza all'avvio (gate)* — quanto una commessa è **correttamente
impostata per partire**. NON misura la salute in corso d'esecuzione (avanzamento/ritardi), che
resta fuori scope.

**Valore:** colpo d'occhio manageriale su quali commesse sono pronte e cosa manca a quelle che non
lo sono, con azioni dirette per colmare i gap. **Rischio basso:** solo lettura di dati già presenti,
nessun nuovo modello, nessuna migrazione.

---

## 2. Modello di calcolo

La readiness è **calcolata al volo** dai dati esistenti. **Nessun campo persistente, nessuna
migrazione, nessuno snapshot** (decisione approvata): il valore è sempre fresco e non va mantenuto
in sync.

Unità isolata e testabile — nuovo `django_app/tasks/readiness.py`:

```python
@dataclass(frozen=True)
class ReadinessCriterion:
    key: str          # "vrf" | "meeting" | "team" | "plan"
    label: str        # etichetta IT
    ok: bool
    action_url: str | None  # link per colmare il gap (None se non applicabile)

@dataclass(frozen=True)
class ReadinessResult:
    criteria: list[ReadinessCriterion]
    met: int          # criteri soddisfatti (0..4)
    total: int        # 4
    level: str        # "ready" | "partial" | "notready"
    label: str        # "Pronto" | "Quasi pronto" | "Non pronto"

def compute_project_readiness(project) -> ReadinessResult: ...
```

---

## 3. I 4 criteri (regole precise)

| Criterio | Chiave | Regola (True = ok) | Azione se mancante |
|---|---|---|---|
| **VRF a posto** | `vrf` | `project.vrf_status in {UPLOADED, NOT_REQUIRED}` (≠ `PENDING`/"Da caricare") | `tasks:project_vrf_upload` |
| **Incontro kickoff fatto** | `meeting` | esiste almeno un `KickoffMeeting` (`project.meetings.exists()` o annotazione `_has_meeting`) | `tasks:project_meeting_create` |
| **Team assegnato** | `team` | `project_manager_id` **e** `capo_commessa_id` **e** `programmer_id` valorizzati | *nessun link* (vedi §4) |
| **Piano attività definito** | `plan` | esiste almeno un'attività collegata **con scadenza** (`project.tasks.filter(due_date__isnull=False).exists()` o annotazione `_has_planned_task`) | `tasks:create` + `?project=<id>` |

Note:
- VRF: si usa lo **stato documento** (`vrf_status`). La valutazione rischi MOD.073
  (`project.vrf_assessment`, OneToOne) NON è richiesta dal gate (semplicità); resta una possibile
  variante più severa futura.
- `related_name` reali verificati: `project.tasks`, `project.meetings`, `project.vrf_assessment`.

---

## 4. Livelli, badge e checklist

**Livelli (soglie approvate, tarabili in un unico punto di `readiness.py`):**
- **4/4 → `ready` "Pronto"** (verde)
- **2–3 → `partial` "Quasi pronto"** (ambra)
- **0–1 → `notready` "Non pronto"** (rosso)

**Badge** (`tasks/_readiness_badge.html`): pallino colorato + testo "«label» «met»/4".
Colori dai **token stato** (`--hub-status-success` / `--hub-status-warning` / `--hub-status-danger`
+ i rispettivi `-bg`), quindi **dark-safe** senza hex hardcodati.

**Checklist** (`tasks/_readiness_checklist.html`): i 4 criteri con icona ok/mancante e, per i
mancanti con `action_url`, un link "Sistema" all'azione corrispondente.
- **Team senza link-azione** (decisione approvata): oggi non esiste una route di modifica commessa
  (`urls.py` ha `project_create`, non `project_edit`). La voce "Team assegnato" mancante è quindi
  **informativa** (nessun link). Se in futuro si vuole il link, va aggiunta una piccola vista di
  modifica commessa — **fuori scope F2**.

---

## 5. Dove appare

- **Card portfolio** (`tasks/projects.html`) e **riga lista backlog** (`tasks/list.html`, modalità
  globale, colonna o accanto al nome commessa): **badge**.
- **Header commessa** (`tasks/list.html`, modalità progetto, dentro `.pk-header`): **badge +
  checklist** azionabile.
- **Dashboard globale** (`tasks/list.html`, sezione admin `admin_console`): **riepilogo aggregato**
  "Pronte N · Quasi N · Non pronte N" (conteggio sui progetti in scope; non cliccabile in F2).

---

## 6. Performance (no N+1)

Per le viste di lista i queryset dei progetti vengono **annotati** una volta sola:
- `_has_meeting = Exists(KickoffMeeting.objects.filter(project=OuterRef("pk")))`
- `_has_planned_task = Exists(Task.objects.filter(project=OuterRef("pk"), due_date__isnull=False))`

`vrf_status` e le FK team sono già sulla riga del progetto. `compute_project_readiness` **preferisce
le annotazioni** se presenti sull'oggetto, altrimenti esegue le query puntuali (usato nell'header
del singolo progetto). Così il portfolio non fa query per-progetto.

---

## 7. File e isolamento

**Nuovi:**
- `django_app/tasks/readiness.py` — logica pura (fonte di verità unica del calcolo).
- `django_app/tasks/templates/tasks/_readiness_badge.html` — badge (input: `readiness`).
- `django_app/tasks/templates/tasks/_readiness_checklist.html` — checklist (input: `readiness`).

**Modificati (additivo, nessun cambio di logica esistente):**
- `django_app/tasks/views.py` — `project_list` e `task_list`: annotare il queryset progetti e
  passare `readiness` (per-progetto e/o aggregato) al contesto. Nessuna modifica alle regole
  ACL/scope esistenti.
- `django_app/tasks/templates/tasks/projects.html` — include badge nelle card.
- `django_app/tasks/templates/tasks/list.html` — badge in riga backlog; badge+checklist in
  `.pk-header`; riepilogo aggregato in `admin_console`.
- `django_app/tasks/static/tasks/css/tasks.css` — stili `.tk-readiness*` su token (dark-safe).
- `django_app/tasks/tests.py` — test unit + smoke.

**Vincolo import (memoria progetto):** in `views.py` i modelli esterni si importano **localmente
dentro la funzione**, mai globali.

---

## 8. Strategia di verifica

- **Unit** su `compute_project_readiness`: ogni criterio isolato (vrf pending/uploaded/not_required;
  meeting sì/no; team completo/parziale; plan con/ senza scadenza), le tre soglie di `level`, e
  l'aggregato (conteggio Pronte/Quasi/Non pronte). Funzione pura → TDD.
- **No N+1:** test con `assertNumQueries` sul `project_list` annotato (il conteggio query non cresce
  col numero di progetti).
- **Smoke render:** il badge compare nelle card portfolio e la checklist nell'header progetto
  (superuser + fixture Project con vari stati).
- `python django_app\manage.py test django_app.tasks --settings=config.settings.test --keepdb`;
  `manage.py check`. Mai la suite completa.

---

## 9. Confini (YAGNI)

**Dentro F2:** solo prontezza-gate calcolata al volo, badge + checklist + riepilogo aggregato.
**Fuori:** salute-in-corso (avanzamento/ritardi come indicatore); campo/snapshot persistente;
route di modifica commessa per il link team; board per fase / calendario / timeline (feature
successive); qualsiasi nuova route o modello.

---

## 10. Note operative

- Modifiche nel checkout locale `C:\Dev\Portale Novicrom`; prod gira `feature/skill-matrix-mod187`.
- A fine lavoro: `CHANGELOG.md` + `README.md` + eventuale bump versione.
