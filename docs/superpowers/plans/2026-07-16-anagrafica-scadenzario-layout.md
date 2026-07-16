# Anagrafica — Scadenzario & Formazione-sessione: layout, viste e rinnovi — Piano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rendere lo **scadenzario HR** più operativo secondo la punch-list del capo:
visite mediche collassate di default, **formazione inline** (niente redirect alla pagina
dedicata come unico accesso), **toggle di vista** (Gruppi · Calendario · Affiancata),
**«↻ Rinnovo» per singola visita**, e sul lato **formazione** un «seleziona dipendenti →
sessione di rinnovo» che entra nel **flusso standard** già esistente più «scadenzario =
plan» (vista calendario). Nessun modello nuovo, **nessuna migrazione**.

**Architecture:** additiva e a riuso massimo. Le scadenze restano quelle di
`_build_scadenzario_voci`; si aggiungono `tipo_id` (voce/gruppo visita) e `corso_id`
(voce formazione). Il rinnovo formazione **riusa** `formazione_sessione_create` +
`TrainingEnrollment.get_or_create` (come `formazione_iscrizione_bulk`), passando i
dipendenti selezionati via `request.session`. La vista calendario riusa
`formazione_plan?view=calendario` e l'helper `_add_months`. Il ↻ Rinnovo visita usa il
deep-link `visite_mediche_nuova_sessione?tipo=<id>` del piano visite.

**Tech Stack:** Django 5.2, Python 3.11+, HTMX/SSR con stili inline e design-system
`fmd-`, test `django.test.TestCase` + `RequestFactory`/`Client`. DB prod SQL Server:
ORM SQL-Server-safe. **Nessuna migrazione in questo piano.**

**Spec:** `docs/superpowers/specs/2026-07-16-anagrafica-scadenzario-layout-design.md`
(nel checkout `C:\Dev\Portale Novicrom`).

## Global Constraints

- **Worktree dedicato** (Session Isolation CLAUDE.md): mai lavorare/committare nel checkout
  condiviso `C:\Dev\Portale Novicrom`. Task 1 crea `C:\Dev\pn-anag-scadenzario` su branch
  `feature/anagrafica-scadenzario-layout` da `origin/main`.
- **Mai `git add -A` / `git commit -a`**: staging con percorsi espliciti.
- **Venv**: usare sempre `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"` (il worktree
  non ha `.venv`).
- **Test DB**: `config.settings.test` usa SQLite per-PID sotto `.tmp_tests`. **Questo piano
  non crea migrazioni**, quindi si può usare `--keepdb` fin dalla prima run. (Se il DB
  `--keepdb` è stantio da un altro branch con migrazioni diverse, fare una run **senza
  `--keepdb`** una volta — ~6-8 min — poi tornare a `--keepdb`.)
- Comando test (dalla radice del worktree):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_scadenzario_layout --settings=config.settings.test --keepdb --verbosity 1`
- **Timeout test ≥ 600000 ms**. Non lanciare la suite intera se non nel task di regressione
  finale (label `anagrafica`).
- **PowerShell** (Windows): `&` per invocare l'exe quotato; `Set-Location` alla radice del worktree.
- Nuovi test in **`django_app/anagrafica/tests_scadenzario_layout.py`** (nuovo file).
- **Template Django**: `{# #}` commenta UNA riga (multi-riga i `{% %}` interni vengono
  ESEGUITI); mai chiavi/variabili con `_` iniziale.
- **HTMX / progressive enhancement**: toggle vista e calendario funzionano via `?layout=`
  server-side (no JS). Le checkbox di selezione dipendenti sono in un `<form>` classico.
- **Privacy**: gating invariato (dentro `_build_scadenzario_voci`); l'endpoint rinnovo
  formazione è gated `_can_edit_formazione`. Nessun esito sanitario esposto.
- **SQL-Server-safe**: niente window function.
- **CHANGELOG.md** + **README.md** obbligatori (Task finale). **Niente version bump.**
- Riuso obbligatorio (non riscrivere): `_build_scadenzario_voci`,
  `_raggruppa_scadenze_per_tipo`, `formazione_sessione_create`,
  `formazione_iscrizione_bulk` (logica `get_or_create`), `formazione_plan` (calendario),
  `_add_months`, `_build_nomi_map`, `_dipendenti_picker_rows`.

## Coordinamento con il piano «Giornata visite» (VINCOLANTE)

Il piano `docs/superpowers/plans/2026-07-16-visite-giornata-sessioni.md` (**Task 9**)
tocca gli stessi punti:

- aggiunge `"tipo_id": v.tipo_id` alla **voce visita** in `_build_scadenzario_voci`;
- aggiunge `"tipo_id"` al **gruppo** in `_raggruppa_scadenze_per_tipo`;
- aggiunge in `scadenzario.html` il **↻ Rinnovo per GRUPPO** (summary + lista piatta),
  deep-link `visite_mediche_nuova_sessione?tipo=<id>`.

Questo piano aggiunge il **↻ Rinnovo per SINGOLA visita** (che dipende dallo stesso
`tipo_id`) e riscrive altre porzioni di `scadenzario.html` (collapse, formazione inline,
toggle vista). Regole di convivenza:

1. **Preferenza: eseguire prima il piano visite.** Poi questo stream si innesta.
2. **Se questo stream parte prima/in parallelo**: il **Task 2 qui aggiunge da sé
   `tipo_id` (voce + gruppo) in modo IDEMPOTENTE** (`if "tipo_id" not in dict` /
   `.setdefault`), così i due piani non si sovrascrivono. Se il piano visite è già
   atterrato, il Task 2 verifica che `tipo_id` esista e **salta** l'aggiunta duplicata.
3. Le CTA nel template stanno in **regioni diverse** (visite: `<summary>` del gruppo e cella
   «Descrizione» della lista piatta; qui: flag `open` del `<details>`, pannello formazione,
   header con toggle). In caso di rebase, **conservare ENTRAMBE** le CTA ↻ Rinnovo (per
   gruppo e per singola), mai rimuovere quella dell'altro piano.

## Ordine di esecuzione e dipendenze (VINCOLANTE)

Le route del rinnovo formazione si referenziano a runtime (`redirect(name)`),
quindi la view + la `path()` vanno nello **stesso commit**. Ordine consigliato:

1 → 2 (voci: `tipo_id`/`corso_id`) → 3 (view: `layout` + strutture) → 4 (template:
toggle + collapse + ↻ singola) → 5 (endpoint rinnovo + sezione formazione inline) → 6
(`formazione_sessione_create` consuma i selezionati) → 7 (layout affiancata + calendario)
→ 8 (formazione scadenzario dedicato: calendario + seleziona dipendenti) → 9 (regressione,
CHANGELOG, README, push).

**Nota dipendenza Task 6 ↔ 5:** il Task 5 fa `redirect("anagrafica:formazione_sessione_create")`
(route già esistente: nessun `NoReverseMatch`). Il consumo dei selezionati (Task 6)
avviene nella view esistente: i due task sono committabili separatamente.

---

### Task 1: Setup worktree

**Files:** solo git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-anag-scadenzario` su `feature/anagrafica-scadenzario-layout`
  (base `origin/main`), cwd di tutti i task.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-anag-scadenzario -B feature/anagrafica-scadenzario-layout origin/main
Set-Location C:\Dev\pn-anag-scadenzario
git status
```

Atteso: `On branch feature/anagrafica-scadenzario-layout`, tree clean.

- [ ] **Step 2: Verifica venv**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
```

Atteso: `Python 3.11+`.

---

### Task 2: Voci scadenzario — `tipo_id` sulla visita, `corso_id` sulla formazione, `tipo_id` sul gruppo (idempotente)

**Files:**
- Modify: `django_app/anagrafica/views.py` (`_build_scadenzario_voci` ~riga 7141 — voce
  visita ~7230, voce formazione ~7265; `_raggruppa_scadenze_per_tipo` ~riga 7346)
- Create: `django_app/anagrafica/tests_scadenzario_layout.py`

**Interfaces:**
- Produces: voce `visita` con `tipo_id`, voce `formazione` con `corso_id`, gruppo con
  `tipo_id`. Consumati da Task 4/5/7.

- [ ] **Step 1: Scrivi il test (nuovo file `tests_scadenzario_layout.py`)**

```python
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from .models import TipoVisitaMedica, VisitaMedica
from .models_formazione import TrainingCourse, TrainingDeadline

User = get_user_model()


class VociScadenzarioIdsTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-voci", "su-voci@test.local", "x")
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="VociT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=201, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),  # scaduta
        )
        self.corso = TrainingCourse.objects.create(codice="C-VOCI", titolo="Corso Voci", is_active=True)
        TrainingDeadline.objects.create(
            legacy_anagrafica_id=201, corso=self.corso, is_required=True,
            data_scadenza=self.oggi + timedelta(days=10), stato_scadenza="IN_SCADENZA_30",
        )

    def _voci(self, **kw):
        from .views import _build_scadenzario_voci
        rf = RequestFactory()
        request = rf.get("/anagrafica/scadenzario/")
        request.user = self.su
        return _build_scadenzario_voci(request, **kw)

    def test_voce_visita_ha_tipo_id(self):
        v = next(x for x in self._voci(filtro_tipo="visita") if x["kind"] == "visita")
        self.assertEqual(v["tipo_id"], self.tipo.pk)

    def test_voce_formazione_ha_corso_id(self):
        f = next(x for x in self._voci(filtro_tipo="formazione") if x["kind"] == "formazione")
        self.assertEqual(f["corso_id"], self.corso.pk)

    def test_gruppo_visita_ha_tipo_id(self):
        from .views import _raggruppa_scadenze_per_tipo
        gruppi = _raggruppa_scadenze_per_tipo(self._voci(filtro_tipo="visita"))
        g = next(x for x in gruppi if x["kind"] == "visita")
        self.assertEqual(g["tipo_id"], self.tipo.pk)
```

- [ ] **Step 2: Run test → FALLISCE** (KeyError `tipo_id`/`corso_id`).

- [ ] **Step 3: Implementa (idempotente)**

(a) Voce visita — nel dict `~7230-7242`, dopo `"tipo_nome": v.tipo.nome,` aggiungere (se
non già presente per via del piano visite):

```python
                "tipo_id":      v.tipo_id,
```

(b) Voce formazione — nel dict `~7265-7277`, dopo `"tipo_nome": d.corso.titolo,` aggiungere:

```python
                "corso_id":     d.corso_id,
```

(c) Gruppo — in `_raggruppa_scadenze_per_tipo`, nel dict del gruppo (dopo
`"tipo_nome": tipo_nome,`) aggiungere:

```python
            "tipo_id": gv[0].get("tipo_id"),
```

> Se il piano visite ha già aggiunto `tipo_id` (voce/gruppo), NON duplicare: verificare la
> presenza prima di editare. Le tre aggiunte sono comunque additive e sicure da rebasare.

- [ ] **Step 4: Run test → PASSA** (3 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_scadenzario_layout.py
git commit -m "feat(anagrafica): scadenzario - tipo_id sulla voce/gruppo visita e corso_id sulla voce formazione"
```

---

### Task 3: View scadenzario — parametro `layout` + strutture affiancata/calendario

**Files:**
- Modify: `django_app/anagrafica/views.py` (`scadenzario` ~riga 7377; context finale ~7451)
- Test: `django_app/anagrafica/tests_scadenzario_layout.py`

**Interfaces:**
- Produces: context `layout` ∈ `{gruppi, calendario, affiancata}`, più `voci_visite`,
  `voci_formazione` (per affiancata) e `cal_settimane`, `cal_label`, `cal_prev`, `cal_next`
  (per calendario). Consumato da Task 4/7.

- [ ] **Step 1: Scrivi il test**

```python
class LayoutContextTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-lay", "su-lay@test.local", "x")
        self.client.force_login(self.su)

    def test_layout_default_gruppi(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"))
        self.assertEqual(resp.context["layout"], "gruppi")

    def test_layout_ignora_valore_ignoto(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "pippo"})
        self.assertEqual(resp.context["layout"], "gruppi")

    def test_layout_affiancata_espone_colonne(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "affiancata"})
        self.assertEqual(resp.context["layout"], "affiancata")
        self.assertIn("voci_visite", resp.context)
        self.assertIn("voci_formazione", resp.context)

    def test_layout_calendario_espone_griglia(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "calendario"})
        self.assertEqual(resp.context["layout"], "calendario")
        self.assertIn("cal_settimane", resp.context)
```

- [ ] **Step 2: Run test → FALLISCE** (KeyError `layout`).

- [ ] **Step 3: Implementa**

In `scadenzario`, dopo il calcolo di `gruppi` e prima del `return render(...)`:

```python
    layout = request.GET.get("layout", "gruppi")
    if layout not in ("gruppi", "calendario", "affiancata"):
        layout = "gruppi"

    voci_visite = [v for v in voci if v["kind"] == "visita"]
    voci_formazione = [v for v in voci if v["kind"] == "formazione"]

    cal_settimane = cal_label = cal_prev = cal_next = None
    if layout == "calendario":
        import calendar as _cal
        try:
            cal_anno = int(request.GET.get("anno") or oggi.year)
            cal_mese = int(request.GET.get("mese") or oggi.month)
        except (TypeError, ValueError):
            cal_anno, cal_mese = oggi.year, oggi.month
        if not 1 <= cal_mese <= 12:
            cal_mese = oggi.month
        primo = date(cal_anno, cal_mese, 1)
        per_giorno: dict = {}
        for v in voci:
            if v["data_scadenza"] and v["data_scadenza"].year == cal_anno and v["data_scadenza"].month == cal_mese:
                per_giorno.setdefault(v["data_scadenza"].day, []).append(v)
        settimane = []
        for week in _cal.Calendar(firstweekday=0).monthdatcalendar(cal_anno, cal_mese):
            giorni = []
            for gg in week:
                in_mese = (gg.month == cal_mese)
                giorni.append({
                    "data": gg, "in_mese": in_mese,
                    "voci": per_giorno.get(gg.day, []) if in_mese else [],
                    "is_oggi": gg == oggi,
                })
            settimane.append(giorni)
        cal_settimane = settimane
        cal_label = primo.strftime("%B %Y").capitalize()
        cal_prev = _add_months(primo, -1)
        cal_next = _add_months(primo, 1)
```

Aggiungere al dict del `render`:

```python
        "layout": layout,
        "voci_visite": voci_visite,
        "voci_formazione": voci_formazione,
        "cal_settimane": cal_settimane,
        "cal_label": cal_label,
        "cal_prev": cal_prev,
        "cal_next": cal_next,
```

(`date` e `_add_months` sono già importati/definiti nel modulo — verificare l'import di
`date` in cima al file; è usato altrove.)

- [ ] **Step 4: Run test → PASSA** (4 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_scadenzario_layout.py
git commit -m "feat(anagrafica): scadenzario - parametro layout (gruppi/calendario/affiancata) e strutture di supporto"
```

---

### Task 4: Template scadenzario — toggle vista, visite collassate, ↻ Rinnovo per singola visita

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html`
  (header ~riga 21-31; `<details>` ~riga 73; cella descrizione lista piatta ~riga 141-146)
- Test: `django_app/anagrafica/tests_scadenzario_layout.py`

**Interfaces:**
- Consumes: `layout`, `can_view_visite`, gruppi/voci con `tipo_id` (Task 2/3), deep-link
  `visite_mediche_nuova_sessione` (piano visite / esistente).

- [ ] **Step 1: Scrivi il test**

```python
class ScadenzarioTemplateTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-tpl", "su-tpl@test.local", "x")
        self.client.force_login(self.su)
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="TplT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=301, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def test_toggle_layout_presente(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"))
        body = resp.content.decode()
        self.assertIn("layout=calendario", body)
        self.assertIn("layout=affiancata", body)

    def test_rinnovo_singola_visita_deeplink(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "visita"})
        body = resp.content.decode()
        self.assertIn(f"nuova-sessione/?tipo={self.tipo.pk}", body)

    def test_gruppo_visita_non_auto_aperto(self):
        # i gruppi visita NON devono avere l'attributo open anche se scaduti
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "visita"})
        body = resp.content.decode()
        # marcatore semplice: il summary Visita medica esiste ma senza <details ... open>
        self.assertIn("Visita medica", body)
```

- [ ] **Step 2: Run test → FALLISCE** (nessun toggle, nessun deep-link visite).

- [ ] **Step 3: Implementa**

(a) Header pagina (`fmd-pagehead-actions`, ~riga 27): aggiungere un toggle che preserva i
filtri correnti:

```django
        <div class="fmd-viewtoggle" style="display:inline-flex;gap:4px;">
          {% for lo, lbl in "gruppi,Gruppi;calendario,Calendario;affiancata,Affiancata"|cut:" "|default:"" %}{% endfor %}
        </div>
```

> Nota Django: il costrutto sopra è solo indicativo. Renderlo con 3 link espliciti (più
> semplice e leggibile), riusando `request.GET` per conservare `tipo`/`stato`/`reparto`:

```django
        <a class="fmd-btn fmd-btn-ghost{% if layout == 'gruppi' %} fmd-btn-primary{% endif %}"
           href="?{% for k,v in request.GET.items %}{% if k != 'layout' and k != 'page' %}{{ k }}={{ v }}&{% endif %}{% endfor %}layout=gruppi">Gruppi</a>
        <a class="fmd-btn fmd-btn-ghost{% if layout == 'calendario' %} fmd-btn-primary{% endif %}"
           href="?{% for k,v in request.GET.items %}{% if k != 'layout' and k != 'page' %}{{ k }}={{ v }}&{% endif %}{% endfor %}layout=calendario">Calendario</a>
        <a class="fmd-btn fmd-btn-ghost{% if layout == 'affiancata' %} fmd-btn-primary{% endif %}"
           href="?{% for k,v in request.GET.items %}{% if k != 'layout' and k != 'page' %}{{ k }}={{ v }}&{% endif %}{% endfor %}layout=affiancata">Affiancata</a>
```

(b) Wrappare la vista a gruppi + lista piatta esistente in `{% if layout == "gruppi" %}...{% endif %}`
(le viste calendario/affiancata arrivano in Task 7; per ora, se `layout != "gruppi"`,
mostrare un placeholder «Vista in arrivo» così il test del toggle passa senza rompere).

(c) `<details>` (riga 73): visite collassate anche se scadute —

```django
        <details class="scad-group"{% if g.has_scadute and g.kind != "visita" %} open{% endif %} ...>
```

(d) ↻ Rinnovo per SINGOLA visita — nella vista gruppi, dentro `{% for v in g.voci %}` (dopo
la cella nome/persona) e nella lista piatta, nella cella «Descrizione» (~riga 141, accanto
al ramo qualifica già presente del piano visite):

```django
                {% if v.kind == "visita" and can_view_visite and v.tipo_id %}
                  <a href="{% url 'anagrafica:visite_mediche_nuova_sessione' %}?tipo={{ v.tipo_id }}" title="Crea una giornata di rinnovo per questa visita" style="margin-left:8px;font-size:11px;font-weight:700;color:#059669;text-decoration:none;white-space:nowrap;">↻ Rinnovo</a>
                {% endif %}
```

> **Coordinamento:** se il piano visite ha già aggiunto il ↻ Rinnovo **per gruppo** nel
> `<summary>`, lasciarlo. Questo è il ↻ per **singola** riga: convivono.

- [ ] **Step 4: Run test → PASSA** (3 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/scadenzario.html django_app/anagrafica/tests_scadenzario_layout.py
git commit -m "feat(anagrafica): scadenzario - toggle vista, visite collassate di default, Rinnovo per singola visita"
```

---

### Task 5: Endpoint «rinnovo formazione dai selezionati» + sezione formazione INLINE

**Files:**
- Modify: `django_app/anagrafica/views.py` (nuova view `formazione_rinnovo_da_scadenzario`)
- Modify: `django_app/anagrafica/urls.py` (~riga 374, vicino a `formazione/scadenzario/`)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html`
  (pannello formazione ~righe 181-195: sostituire «solo KPI + link» con sezione inline
  + checkbox per corso + form)
- Test: `django_app/anagrafica/tests_scadenzario_layout.py`

**Interfaces:**
- Consumes: `TrainingCourse`, voci formazione con `corso_id` (Task 2).
- Produces: route `formazione_rinnovo_da_scadenzario`
  (`formazione/rinnovo-da-scadenzario/`); stash `request.session["rinnovo_preselect"]`.
  Consumato da Task 6.

- [ ] **Step 1: Scrivi il test**

```python
class RinnovoFormazioneEndpointTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-rin", "su-rin@test.local", "x")
        self.plain = User.objects.create_user("plain-rin", "plain-rin@test.local", "x")
        self.corso = TrainingCourse.objects.create(codice="C-RIN", titolo="Corso Rin", is_active=True)

    def test_post_stasha_e_redirige_a_create(self):
        self.client.force_login(self.su)
        resp = self.client.post(
            reverse("anagrafica:formazione_rinnovo_da_scadenzario"),
            {"corso_id": str(self.corso.pk), "dipendenti_selezionati": ["10", "11", "10"]},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"?corso={self.corso.pk}", resp["Location"])
        stash = self.client.session["rinnovo_preselect"]
        self.assertEqual(stash["corso"], self.corso.pk)
        self.assertEqual(sorted(stash["ids"]), [10, 11])  # dedup

    def test_nessun_selezionato_warning(self):
        self.client.force_login(self.su)
        resp = self.client.post(
            reverse("anagrafica:formazione_rinnovo_da_scadenzario"),
            {"corso_id": str(self.corso.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("rinnovo_preselect", self.client.session)

    def test_403_senza_permesso_editor(self):
        self.client.force_login(self.plain)
        resp = self.client.post(
            reverse("anagrafica:formazione_rinnovo_da_scadenzario"),
            {"corso_id": str(self.corso.pk), "dipendenti_selezionati": ["10"]},
        )
        # _can_edit_formazione nega → redirect (no stash)
        self.assertNotIn("rinnovo_preselect", self.client.session)
```

- [ ] **Step 2: Run test → FALLISCE** (route/vista assenti).

- [ ] **Step 3: Implementa view + route + sezione inline**

(a) `views.py` — vicino agli altri helper formazione:

```python
@login_required
@require_POST
def formazione_rinnovo_da_scadenzario(request):
    """Punto d'ingresso «seleziona dipendenti → sessione di rinnovo»: raccoglie i
    dipendenti selezionati per un corso e li porta nel FLUSSO STANDARD di creazione
    sessione (``formazione_sessione_create``). Gli id restano in ``request.session``
    e vengono iscritti in blocco al salvataggio della sessione."""
    if not _can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per creare sessioni di rinnovo.")
        return redirect("anagrafica:formazione_scadenzario")
    try:
        corso = TrainingCourse.objects.get(pk=request.POST.get("corso_id"), is_active=True)
    except (TrainingCourse.DoesNotExist, ValueError, TypeError):
        messages.error(request, "Corso non valido.")
        return redirect("anagrafica:formazione_scadenzario")
    ids, seen = [], set()
    for raw in request.POST.getlist("dipendenti_selezionati"):
        s = str(raw).strip()
        if s.isdigit():
            lid = int(s)
            if lid > 0 and lid not in seen:
                seen.add(lid)
                ids.append(lid)
    if not ids:
        messages.warning(request, "Nessun dipendente selezionato.")
        return redirect(request.POST.get("back") or "anagrafica:scadenzario")
    request.session["rinnovo_preselect"] = {"corso": corso.pk, "ids": ids}
    messages.info(request, f"{len(ids)} dipendenti pronti per il rinnovo: compila la sessione.")
    return redirect(f"{reverse('anagrafica:formazione_sessione_create')}?corso={corso.pk}")
```

(`reverse` è già importato nel modulo; verificarlo.)

(b) `urls.py` (dopo `formazione/scadenzario/`):

```python
    path("formazione/rinnovo-da-scadenzario/", views.formazione_rinnovo_da_scadenzario, name="formazione_rinnovo_da_scadenzario"),
```

(c) `scadenzario.html` — sostituire il pannello «Scadenzario formazione» (righe 181-195)
con una sezione INLINE che elenca le voci formazione raggruppate per corso e permette la
selezione. Struttura minima (gated `can_view_formazione`):

```django
    {% if can_view_formazione %}
    <section class="fmd-panel fmd-block">
      <div class="fmd-block-head">
        <div class="fmd-block-title"><svg class="fmd-ico"><use href="#i-cap"/></svg>Scadenzario formazione</div>
        <div style="display:flex;gap:8px;">
          <a href="{% url 'anagrafica:formazione_plan' %}?view=calendario" class="fmd-btn fmd-btn-ghost">Vista calendario (plan)</a>
          <a href="{% url 'anagrafica:formazione_scadenzario' %}" class="fmd-mtr-link">Apri pagina dedicata <svg class="fmd-ico"><use href="#i-arrow-right"/></svg></a>
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
        <span class="fmd-pill fmd-pill-red"><span class="fmd-pn">{{ fm_n_scaduti }}</span> Scaduti</span>
        <span class="fmd-pill fmd-pill-orange"><span class="fmd-pn">{{ fm_n_30gg }}</span> Entro 30gg</span>
        <span class="fmd-pill fmd-pill-amber"><span class="fmd-pn">{{ fm_n_90gg }}</span> Entro 90gg</span>
      </div>
      {% regroup voci_formazione by tipo_nome as corsi_group %}
      {% for cg in corsi_group %}
      <form method="post" action="{% url 'anagrafica:formazione_rinnovo_da_scadenzario' %}" style="border:1px solid #e6ecf3;border-radius:10px;margin-bottom:10px;padding:10px 14px;">
        {% csrf_token %}
        <input type="hidden" name="corso_id" value="{{ cg.list.0.corso_id }}">
        <input type="hidden" name="back" value="anagrafica:scadenzario">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
          <strong>{{ cg.grouper }}</strong>
          <button type="submit" class="fmd-btn fmd-btn-primary" style="font-size:12px;"><svg class="fmd-ico"><use href="#i-refresh"/></svg>Crea sessione di rinnovo con i selezionati</button>
        </div>
        <div style="overflow-x:auto;margin-top:8px;">
          <table class="fmd-table" style="margin:0;">
            <tbody>
              {% for v in cg.list %}
              <tr>
                <td style="width:36px;text-align:center;"><input type="checkbox" name="dipendenti_selezionati" value="{{ v.legacy_id }}"{% if v.scaduta %} checked{% endif %}></td>
                <td>{{ v.cognome }} {{ v.nome }}</td>
                <td class="fmd-nowrap fmd-num">{{ v.data_scadenza|date:"d-m-Y" }}</td>
                <td>{% if v.scaduta %}<span class="fmd-badge fmd-b-red">Scaduta</span>{% else %}<span class="fmd-badge fmd-b-amber">{{ v.giorni }}gg</span>{% endif %}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </form>
      {% empty %}
      <div class="fmd-muted">Nessuna scadenza formazione con i filtri correnti.</div>
      {% endfor %}
    </section>
    {% endif %}
```

- [ ] **Step 4: Run test → PASSA** (3 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/urls.py django_app/anagrafica/templates/anagrafica/pages/scadenzario.html django_app/anagrafica/tests_scadenzario_layout.py
git commit -m "feat(anagrafica): scadenzario - formazione inline con seleziona dipendenti -> sessione di rinnovo (flusso standard)"
```

---

### Task 6: `formazione_sessione_create` consuma i dipendenti pre-selezionati (iscrizione in blocco)

**Files:**
- Modify: `django_app/anagrafica/views.py` (`formazione_sessione_create` ~riga 11600, ramo
  POST dopo `sessione.save()`)
- Test: `django_app/anagrafica/tests_scadenzario_layout.py`

**Interfaces:**
- Consumes: `request.session["rinnovo_preselect"]` (Task 5), `TrainingEnrollment.get_or_create`
  (pattern di `formazione_iscrizione_bulk` ~riga 12287).
- Produces: al salvataggio, iscrive gli id e redirige a `formazione_sessione_iscritti`.

- [ ] **Step 1: Scrivi il test**

```python
class SessioneCreateConsumaPreselectTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-cre", "su-cre@test.local", "x")
        self.client.force_login(self.su)
        self.corso = TrainingCourse.objects.create(codice="C-CRE", titolo="Corso Cre", is_active=True)

    def test_salvataggio_iscrive_i_preselezionati(self):
        from .models_formazione import TrainingSession, TrainingEnrollment
        s = self.client.session
        s["rinnovo_preselect"] = {"corso": self.corso.pk, "ids": [51, 52]}
        s.save()
        oggi = timezone.localdate().isoformat()
        resp = self.client.post(reverse("anagrafica:formazione_sessione_create"), {
            "corso": str(self.corso.pk), "codice_sessione": "SESS-CRE-1",
            "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": oggi, "data_fine": oggi,
        })
        self.assertEqual(resp.status_code, 302)
        sess = TrainingSession.objects.get(codice_sessione="SESS-CRE-1")
        self.assertEqual(
            set(TrainingEnrollment.objects.filter(sessione=sess).values_list("legacy_anagrafica_id", flat=True)),
            {51, 52},
        )
        self.assertNotIn("rinnovo_preselect", self.client.session)  # pulito
        self.assertIn(f"/formazione/sessioni/{sess.pk}/iscritti/", resp["Location"])
```

- [ ] **Step 2: Run test → FALLISCE** (nessuna iscrizione; redirect va al detail, non a iscritti).

- [ ] **Step 3: Implementa**

In `formazione_sessione_create`, nel ramo POST, DOPO `sessione.save()` e PRIMA del
`return redirect(...)`:

```python
            pre = request.session.get("rinnovo_preselect")
            if pre and pre.get("corso") == sessione.corso_id and pre.get("ids"):
                n_new = 0
                for lid in pre["ids"]:
                    _, created = TrainingEnrollment.objects.get_or_create(
                        sessione=sessione, legacy_anagrafica_id=lid,
                        defaults={"stato": "ISCRITTO", "iscritto_da": request.user},
                    )
                    if created:
                        n_new += 1
                request.session.pop("rinnovo_preselect", None)
                messages.success(request, f'Sessione "{sessione.codice_sessione}" creata; {n_new} dipendenti iscritti per il rinnovo.')
                return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione.pk)
            messages.success(request, f'Sessione "{sessione.codice_sessione}" creata.')
            return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione.pk)
```

(Sostituisce il singolo `messages.success(...) + return redirect(detail)` esistente:
mantiene il comportamento normale quando non c'è preselezione.)

- [ ] **Step 4: Run test → PASSA** (1 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_scadenzario_layout.py
git commit -m "feat(anagrafica): formazione_sessione_create - iscrive in blocco i dipendenti pre-selezionati dallo scadenzario"
```

---

### Task 7: Layout «Affiancata» e «Calendario» nel template scadenzario

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html`
  (rami `{% elif layout == "affiancata" %}` / `{% elif layout == "calendario" %}` che
  sostituiscono il placeholder del Task 4)
- Test: `django_app/anagrafica/tests_scadenzario_layout.py`

**Interfaces:**
- Consumes: `voci_visite`, `voci_formazione`, `cal_settimane`, `cal_label`, `cal_prev`,
  `cal_next` (Task 3).

- [ ] **Step 1: Scrivi il test**

```python
class LayoutRenderTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-lr", "su-lr@test.local", "x")
        self.client.force_login(self.su)
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="LrT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=401, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def test_affiancata_due_colonne(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "affiancata"})
        body = resp.content.decode()
        self.assertIn("col-visite", body)
        self.assertIn("col-formazione", body)

    def test_calendario_intestazione_mese(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "calendario"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("cal-grid", resp.content.decode())
```

- [ ] **Step 2: Run test → FALLISCE** (placeholder, niente `col-visite`/`cal-grid`).

- [ ] **Step 3: Implementa i due rami**

Sostituire il placeholder «Vista in arrivo» con:

```django
    {% elif layout == "affiancata" %}
    <section class="fmd-panel">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <div class="col-visite">
          <h3 style="font-size:14px;font-weight:800;color:var(--fmd-navy);">Visite mediche</h3>
          {% if can_view_visite %}
          <table class="fmd-table"><tbody>
            {% for v in voci_visite %}
            <tr>
              <td>{{ v.cognome }} {{ v.nome }}</td>
              <td>{{ v.tipo_nome }}</td>
              <td class="fmd-nowrap fmd-num">{{ v.data_scadenza|date:"d-m-Y" }}</td>
              <td>{% if v.tipo_id %}<a href="{% url 'anagrafica:visite_mediche_nuova_sessione' %}?tipo={{ v.tipo_id }}" style="color:#059669;font-weight:700;font-size:11px;">↻ Rinnovo</a>{% endif %}</td>
            </tr>
            {% empty %}<tr><td colspan="4" class="fmd-muted">Nessuna visita in scadenza.</td></tr>{% endfor %}
          </tbody></table>
          {% else %}<div class="fmd-muted">Visite mediche non visibili col tuo accesso.</div>{% endif %}
        </div>
        <div class="col-formazione">
          <h3 style="font-size:14px;font-weight:800;color:var(--fmd-navy);">Formazione</h3>
          {% if can_view_formazione %}
          <table class="fmd-table"><tbody>
            {% for v in voci_formazione %}
            <tr>
              <td>{{ v.cognome }} {{ v.nome }}</td>
              <td>{{ v.tipo_nome }}</td>
              <td class="fmd-nowrap fmd-num">{{ v.data_scadenza|date:"d-m-Y" }}</td>
            </tr>
            {% empty %}<tr><td colspan="3" class="fmd-muted">Nessuna scadenza formazione.</td></tr>{% endfor %}
          </tbody></table>
          {% else %}<div class="fmd-muted">Formazione non visibile col tuo accesso.</div>{% endif %}
        </div>
      </div>
    </section>
    {% elif layout == "calendario" %}
    <section class="fmd-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <a class="fmd-btn fmd-btn-ghost" href="?layout=calendario&anno={{ cal_prev|date:'Y' }}&mese={{ cal_prev|date:'n' }}">‹ Mese prec.</a>
        <strong>{{ cal_label }}</strong>
        <a class="fmd-btn fmd-btn-ghost" href="?layout=calendario&anno={{ cal_next|date:'Y' }}&mese={{ cal_next|date:'n' }}">Mese succ. ›</a>
      </div>
      <table class="cal-grid" style="width:100%;border-collapse:collapse;table-layout:fixed;">
        <thead><tr>{% for d in "LMMGVSD"|make_list %}<th style="padding:4px;font-size:11px;color:var(--fmd-muted);">{{ d }}</th>{% endfor %}</tr></thead>
        <tbody>
          {% for settimana in cal_settimane %}
          <tr>
            {% for giorno in settimana %}
            <td style="border:1px solid #eef2f7;vertical-align:top;height:80px;padding:3px;{% if not giorno.in_mese %}background:#f8fafc;{% endif %}{% if giorno.is_oggi %}outline:2px solid var(--fmd-cyan);{% endif %}">
              <div style="font-size:11px;color:var(--fmd-muted);">{{ giorno.data|date:"j" }}</div>
              {% for v in giorno.voci %}
              <div style="font-size:10px;margin-top:2px;padding:1px 4px;border-radius:4px;{% if v.scaduta %}background:#fee2e2;color:#b91c1c;{% else %}background:#fff7ed;color:#9a3412;{% endif %}" title="{{ v.cognome }} {{ v.nome }} — {{ v.tipo_nome }}">{{ v.kind_label|slice:":3" }} · {{ v.cognome }}</div>
              {% endfor %}
            </td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </section>
    {% endif %}
```

- [ ] **Step 4: Run test → PASSA** (2 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/scadenzario.html django_app/anagrafica/tests_scadenzario_layout.py
git commit -m "feat(anagrafica): scadenzario - viste Affiancata (visite|formazione) e Calendario (griglia mensile)"
```

---

### Task 8: Formazione scadenzario dedicato — «= plan» (calendario) + seleziona dipendenti

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/formazione_scadenzario.html`
  (header ~righe 19-34; tabella ~righe 95-142)
- Test: `django_app/anagrafica/tests_scadenzario_layout.py`

**Interfaces:**
- Consumes: route `formazione_plan` (calendario) e `formazione_rinnovo_da_scadenzario`
  (Task 5). Il template ha già `page_obj.object_list` con `sc.corso`, `sc.legacy_anagrafica_id`.

- [ ] **Step 1: Scrivi il test**

```python
class FormazioneScadenzarioPlanTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-fsp", "su-fsp@test.local", "x")
        self.client.force_login(self.su)
        self.corso = TrainingCourse.objects.create(codice="C-FSP", titolo="Corso Fsp", is_active=True)
        TrainingDeadline.objects.create(
            legacy_anagrafica_id=61, corso=self.corso, is_required=True,
            data_scadenza=timezone.localdate() - timedelta(days=5), stato_scadenza="SCADUTO",
        )

    def test_toggle_calendario_plan_presente(self):
        resp = self.client.get(reverse("anagrafica:formazione_scadenzario"))
        self.assertIn("view=calendario", resp.content.decode())

    def test_seleziona_dipendenti_form_presente(self):
        resp = self.client.get(reverse("anagrafica:formazione_scadenzario"))
        body = resp.content.decode()
        self.assertIn('name="dipendenti_selezionati"', body)
        self.assertIn("formazione/rinnovo-da-scadenzario", body)
```

- [ ] **Step 2: Run test → FALLISCE** (nessun toggle plan; nessun form selezione).

- [ ] **Step 3: Implementa**

(a) Header (`fmd-pagehead-actions`, ~riga 25): aggiungere il toggle vista calendario:

```django
        <a href="{% url 'anagrafica:formazione_plan' %}?view=calendario" class="fmd-btn fmd-btn-ghost" title="Vista calendario (plan)"><svg class="fmd-ico"><use href="#i-calendar"/></svg>Calendario (plan)</a>
```

(b) Avvolgere la tabella scadenze in un `<form method="post"
action="{% url 'anagrafica:formazione_rinnovo_da_scadenzario' %}">` con `{% csrf_token %}`,
aggiungere una colonna checkbox `dipendenti_selezionati=<sc.legacy_anagrafica_id>`, un
`<input type="hidden" name="corso_id" value="{{ filtro_corso }}">` (attivo solo quando è
filtrato un corso — altrimenti la selezione multi-corso non è ammessa: mostrare le checkbox
solo se `filtro_corso`), e un pulsante «Crea sessione di rinnovo con i selezionati»
(`{% if is_editor and filtro_corso %}`).

> Vincolo: `TrainingSession` è per-corso, quindi la selezione batch qui richiede il filtro
> su un corso. Quando `filtro_corso` è vuoto, tenere solo il bottone esistente «Pianifica
> edizione di rinnovo» e nascondere le checkbox (evita batch cross-corso ambigui).

- [ ] **Step 4: Run test → PASSA** (2 test). Nota: il secondo test filtra implicitamente
  senza corso; adattare il test a passare `{"corso": self.corso.pk}` se le checkbox sono
  condizionate a `filtro_corso` (allineare test e implementazione).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/formazione_scadenzario.html django_app/anagrafica/tests_scadenzario_layout.py
git commit -m "feat(anagrafica): formazione scadenzario - toggle vista calendario (plan) + seleziona dipendenti per rinnovo"
```

---

### Task 9: Regressione, CHANGELOG, README, push

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: Regressione app anagrafica**

```powershell
Set-Location C:\Dev\pn-anag-scadenzario
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica --settings=config.settings.test --keepdb --verbosity 1 2>&1 | Select-Object -Last 25
```

Atteso: `OK` (a parte l'eventuale test cosmetico pre-esistente
`ScadenzarioEstesoTests.test_prova_futura_inclusa_prova_passata_esclusa`, non toccato da
questo lavoro — se ancora rosso, verificare che sia l'UNICO fallimento e che sia
pre-esistente).

- [ ] **Step 2: CHANGELOG** — sotto `## [Unreleased]` → `### Added`:

```markdown
- **Anagrafica · Scadenzario — layout, viste e rinnovi** (`django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html`, `.../formazione_scadenzario.html`, `django_app/anagrafica/tests_scadenzario_layout.py` [nuovo]). Lo scadenzario HR guadagna un **toggle di vista** (Gruppi · Calendario · Affiancata): «Calendario» è una griglia mensile delle scadenze, «Affiancata» due colonne Visite│Formazione. Le **visite mediche sono collassate di default**; la **formazione è ora inline** (tabella per corso con selezione dipendenti) invece del solo link alla pagina dedicata. Nuovo pulsante **«↻ Rinnovo» per singola visita** (deep-link alla Giornata visite). Sul lato **formazione**, «**seleziona dipendenti → sessione di rinnovo**»: dallo scadenzario si scelgono i dipendenti e si entra nel **flusso standard** di creazione sessione (`formazione_sessione_create`), che al salvataggio li iscrive in blocco; più «**scadenzario = plan**» (toggle vista calendario riusando `formazione_plan?view=calendario`). Nessuna migrazione; gating e privacy invariati. Verifica: suite `anagrafica` verde.
```

- [ ] **Step 3: README** — nel bullet «Scadenzario»/«Formazione» della sezione anagrafica,
  aggiungere una frase su toggle vista (Gruppi/Calendario/Affiancata), visite collassate,
  formazione inline, ↻ Rinnovo per singola visita e «seleziona dipendenti → sessione di
  rinnovo» nel flusso standard.

- [ ] **Step 4: Commit e push**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(anagrafica): changelog e readme per scadenzario layout/viste e rinnovo formazione da selezione"
git push -u origin feature/anagrafica-scadenzario-layout
```

- [ ] **Step 5: Riepilogo finale** all'utente: branch, commit, esito test, file toccati;
  ricordare la sezione «Coordinamento con il piano visite» (conservare entrambe le CTA ↻
  Rinnovo) e che il worktree `C:\Dev\pn-anag-scadenzario` è rimovibile dopo il merge.

---

## Idee future (fuori scope)
Estrarre un helper condiviso per la griglia calendario (oggi duplicata tra scadenzario e
`formazione_plan`); ↻ Rinnovo per singola qualifica/formazione; export della vista
calendario; ricordare i filtri scelti per vista tra i due scadenzari.
