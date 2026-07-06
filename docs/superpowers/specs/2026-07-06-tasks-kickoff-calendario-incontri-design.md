# KICK-OFF (`tasks`) — Calendario incontri (cross-commessa)

- **Data:** 2026-07-06
- **Modulo:** `django_app/tasks` (gestione KICK-OFF)
- **Branch:** `feature/skill-matrix-mod187`
- **Stato:** Design approvato, in attesa di piano
- **Prerequisiti:** F1 (UI condivisa).

---

## 1. Contesto e obiettivo

Feature "D" dal menu: una **vista calendario** cross-commessa degli incontri di kickoff
(`KickoffMeeting`), come nei tool di portfolio. Oggi gli incontri si vedono solo dentro la singola
commessa (`/tasks/projects/<id>/incontri/`, in lista). Questa pagina dà la vista d'insieme mensile
di **tutti** gli incontri nello scope di chi guarda.

**Valore:** pianificazione a colpo d'occhio del mese. **Rischio basso:** sola lettura, nessuna
modifica ai dati, rendering server-side.

`KickoffMeeting` ha già i campi necessari: `data` (DateField), `ora` (TimeField), `luogo`, `titolo`,
`numero`, `project`.

---

## 2. Unità isolata (logica calendario)

Nuovo `django_app/tasks/calendario.py` — logica pura, testabile, senza accesso DB:

```python
def build_meetings_calendar(meetings, year: int, month: int) -> dict:
    """meetings: iterable di KickoffMeeting (già filtrati per scope e mese).
    Ritorna {weeks, year, month, month_label, prev, next, today} dove weeks è una
    lista di settimane (Lun–Dom); ogni giorno = {date, in_month, is_today, meetings}."""
```

Usa `calendar` stdlib (`calendar.Calendar(firstweekday=0)` → settimane Lun–Dom). Mappa gli incontri
sul giorno di `data`. `prev`/`next` = stringhe `YYYY-MM` del mese precedente/successivo (gestendo il
cambio d'anno). `today` per evidenziare la cella.

---

## 3. Vista

`incontri_calendario(request)` (decoratore `@task_permissions_required("tasks_view")`):

- legge `?m=YYYY-MM`; se assente o non parsabile → mese corrente (`timezone.localdate()`);
- `meetings = KickoffMeeting.objects.filter(project__in=_scoped_projects_queryset(request),
  data__year=year, data__month=month).select_related("project").order_by("data", "ora")`;
- `data = build_meetings_calendar(meetings, year, month)`;
- `render("tasks/incontri_calendario.html", { **_tasks_shell_context(active="calendario"), page_title, "cal": data })`.

**Scope:** le commesse in scope (i non-admin già limitati). Nessun toggle "le mie" (YAGNI).

---

## 4. Template (griglia mensile SSR, niente librerie JS)

- Header: etichetta mese/anno + frecce **‹ / ›** (link `?m=<prev>` / `?m=<next>`) + link "Oggi".
- Griglia 7 colonne (Lun–Dom, intestazioni giorni). Ogni cella-giorno:
  - numero del giorno; **attenuata** se `in_month=False`; **evidenziata** se `is_today`;
  - gli incontri del giorno come **chip**: `ora · Commessa/titolo`, link al **verbale**
    (`tasks:project_meeting_detail project.id meeting.id`), `luogo` in `title`.
- Token/dark-safe (`--surface`, `--border`, `--text`, `--accent`, `--hub-*`). Responsive: su schermi
  stretti la griglia scrolla orizzontalmente nel contenitore (o le celle si comprimono).

---

## 5. Navigazione e ACL

- **Route:** `tasks:incontri_calendario` → `/tasks/incontri-calendario/`.
- **Subnav:** `NavigationItem` "Calendario" (`section="subnav"`, `parent_code="tasks"`,
  `required_permission_code="tasks.kickoff.view"`, order tra Kickoff e Impostazioni) — migrazione dati.
- **ACL:** binding `"tasks:incontri_calendario": "tasks.kickoff.view"` in `acl_bootstrap._ROUTE_BINDINGS`
  + bump `_BOOTSTRAP_CACHE_KEY` (`v6` → `v7`). Pagina (non `/api/`) → niente `API_ACL_GATE_PATHS`.

---

## 6. File

**Nuovi:** `tasks/calendario.py`, `tasks/templates/tasks/incontri_calendario.html`, migrazione core
`00NN_tasks_calendario_subnav.py`.
**Modificati:** `tasks/views.py` (+view), `tasks/urls.py` (+route), `tasks/acl_bootstrap.py`
(+binding, bump), `tasks/static/tasks/css/tasks.css` (+`.cal-*`), `tasks/tests.py`, `CHANGELOG.md`,
`README.md`.

**Regole progetto:** import modelli esterni locali nelle view; attributi template senza underscore
iniziale.

---

## 7. Verifica

- **`build_meetings_calendar`**: struttura settimane (ogni settimana 7 giorni, Lun–Dom); un incontro
  cade nel giorno corretto; `prev`/`next` gestiscono il cambio d'anno (gennaio → dicembre anno prec.,
  dicembre → gennaio anno succ.); giorni fuori mese marcati `in_month=False`.
- **Smoke render**: `/tasks/incontri-calendario/` → 200, griglia presente, un incontro del mese
  compare con link al verbale; `?m=YYYY-MM` naviga.
- **Subnav** seedata; **ACL** binding presente dopo bootstrap.
- `test tasks.<Class> --settings=config.settings.test --keepdb`; `check`. Mai suite completa.

---

## 8. Confini (YAGNI)

**Fuori:** vista settimana/giorno; creazione/modifica incontro dal calendario; drag; export ICS;
toggle "le mie"; integrazione Outlook lato calendario (l'incontro ha già il suo sync). Solo vista
mese in sola lettura.

---

## 9. Note operative

- Prod gira `feature/skill-matrix-mod187`; modifiche nel checkout locale; applicare migrazione +
  bootstrap ACL in dev. A fine lavoro `CHANGELOG.md` + `README.md` (attenzione al working tree
  condiviso: staging mirato).
