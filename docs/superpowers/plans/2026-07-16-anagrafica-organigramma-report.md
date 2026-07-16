# Anagrafica — Organigramma ad albero & Report dipendenti canonico — Piano (Stream 2)

> **For agentic workers:** REQUIRED SUB-SKILL: usa superpowers:subagent-driven-development (consigliato) o superpowers:executing-plans per eseguire questo piano task-per-task. Gli step usano checkbox (`- [ ]`) per il tracking.

**Goal:** chiudere tre voci della punch-list `docs/ANAGRAFICA - PERSONE.md` (Organigramma / Report): (1) organigramma **ad albero** per gerarchia di RUOLI + per singola **certificazione** (copertura); (2) **rimuovere il reparto legacy** dal report dipendenti a favore della catena canonica; (3) **caporeparto = responsabile dell'area aziendale** quando differisce dal capo del reparto.

**Architecture:** logica nuova in service dedicati (`services/organigramma_albero.py`, estensioni additive a `services/reparto_canonico.py`) + **una** view/route/template nuovi per l'albero; su `views.py`/`urls.py` solo hunk piccoli e localizzati. La gerarchia è **tra RUOLI** (`RuoloOperativo.riporta_a`), mai tra persone: le persone sono foglie titolari. Riuso massimo: `reparto_canonico.enrich_rows_reparto_canonico/build_area_canonica_map`, `core/operational_roles.get_anagrafica_ids_for_role`, `fetch_anagrafica_rows`, `DipendenteQualifica`.

**Tech Stack:** Django 5.2, Python 3.11+, SSR + HTMX (miglioria, non obbligatorio), test `TestCase` + `RequestFactory`/`Client`. ORM SQL-Server-safe (niente window function).

**Spec:** `docs/superpowers/specs/2026-07-16-anagrafica-organigramma-report-design.md`.

## Global Constraints

- **Worktree dedicato** (Session Isolation CLAUDE.md): mai lavorare/committare nel checkout condiviso `C:\Dev\Portale Novicrom`. Task 1 crea `C:\Dev\pn-anag-organigramma` su branch `feature/anagrafica-organigramma-report` da `origin/main`.
- **Mai `git add -A` / `git commit -a`**: staging con percorsi espliciti (i file `views.py`/`urls.py` sono condivisi con gli stream 1 e 3).
- **Venv assoluto** (il worktree non ha `.venv`): `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"`.
- **Comando test** (dalla radice del worktree):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.<test_module> --settings=config.settings.test --keepdb --verbosity 1`
- **Timeout test ≥ 600000 ms.** Nessuna migrazione in questo stream → **prima run già con `--keepdb`**; se per qualsiasi motivo il DB `.tmp_tests` non esiste, la prima run senza `--keepdb` rimigra (~6-8 min). Non lanciare la suite intera se non nel task di regressione finale (label `anagrafica`).
- **PowerShell** (Windows): `&` per invocare l'exe quotato; `Set-Location` alla radice del worktree.
- **Template Django**: `{# #}` commenta UNA riga; mai chiavi/variabili con `_` iniziale.
- **ACL** come le viste esistenti dell'anagrafica: `organigramma_albero` gated come `organigramma` (`@login_required` + gate ACL della route in `urls.py`/middleware); il report resta admin-only come oggi.
- **CHANGELOG.md** + **README.md** obbligatori (Task finale). **Niente version bump.**
- **Coordinamento**: preferire file/template nuovi e funzioni separate; su `views.py`/`urls.py` hunk minimi. In caso di conflitto in fase di merge, ricomporre a mano preservando gli hunk degli altri stream.
- **Riuso obbligatorio** (non riscrivere): `enrich_rows_reparto_canonico`, `build_area_canonica_map`, `build_reparto_canonico_map`, `resolve_reparto_for_row`, `core.operational_roles.get_anagrafica_ids_for_role`, `fetch_anagrafica_rows`.

## Ordine di esecuzione e dipendenze (VINCOLANTE)

1. La view `organigramma_albero` (Task 6) usa i builder dei Task 5a/5b: implementarli **prima**.
2. Ogni `path()` aggiunto in `urls.py` deve avere la **view definita nello stesso commit** (l'import di `urls.py` altrimenti rompe tutto).
3. Il link di toggle nel template `organigramma.html` (Task 6) referenzia `{% url 'anagrafica:organigramma_albero' %}` → la route deve esistere nello stesso commit.
4. **Ordine consigliato:** 1 → 2 (responsabile effettivo, base) → 3 (wiring `_sync`/onboarding) → 4 (report) → 5a → 5b → 6 (view+route+template albero, con toggle) → 7 (overlay certificazione) → 8 (organigramma griglia usa responsabile effettivo) → 9 (CHANGELOG/README).

---

### Task 1: Setup worktree

**Files:** solo git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-anag-organigramma` su `feature/anagrafica-organigramma-report` (base `origin/main`), cwd di tutti i task.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-anag-organigramma -B feature/anagrafica-organigramma-report origin/main
Set-Location C:\Dev\pn-anag-organigramma
git status
```

Atteso: `On branch feature/anagrafica-organigramma-report`, tree clean.

- [ ] **Step 2: Verifica venv**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
```

Atteso: `Python 3.11+`.

---

### Task 2: Responsabile effettivo — fonte unica (`reparto_canonico`)

**Files:**
- Modify: `django_app/anagrafica/services/reparto_canonico.py` (aggiunte additive in coda)
- Test: `django_app/anagrafica/tests_responsabile_effettivo.py` (nuovo)

**Interfaces:**
- Consumes: `build_area_canonica_map` (esistente), `AreaAziendale`, `Reparto`.
- Produces:
  - `resolve_responsabile_effettivo(*, area, reparto) -> int | None` — `area.responsabile_legacy_id` se valorizzato, altrimenti `reparto.caporeparto_legacy_id`, altrimenti `None`.
  - `build_responsabile_effettivo_map(legacy_ids) -> dict[int, int]` — per-dipendente via `build_area_canonica_map` (area già `select_related("reparto")`).

- [ ] **Step 1: Scrivi il test**

```python
from django.test import TestCase
from anagrafica.models import (
    AreaAziendale, DipendenteAnagraficaAziendale, Reparto,
)
from anagrafica.services.reparto_canonico import (
    resolve_responsabile_effettivo, build_responsabile_effettivo_map,
)


class ResponsabileEffettivoTests(TestCase):
    def setUp(self):
        self.rep = Reparto.objects.create(nome="Produzione", caporeparto_legacy_id=10)
        self.area_con_resp = AreaAziendale.objects.create(
            nome="Qualità", reparto=self.rep, responsabile_legacy_id=20,
        )
        self.area_senza_resp = AreaAziendale.objects.create(
            nome="Linea 1", reparto=self.rep,
        )

    def test_area_vince_sul_reparto_quando_differisce(self):
        self.assertEqual(
            resolve_responsabile_effettivo(area=self.area_con_resp, reparto=self.rep), 20
        )

    def test_fallback_al_caporeparto_se_area_senza_responsabile(self):
        self.assertEqual(
            resolve_responsabile_effettivo(area=self.area_senza_resp, reparto=self.rep), 10
        )

    def test_none_se_nessuno(self):
        rep2 = Reparto.objects.create(nome="Vuoto")
        area2 = AreaAziendale.objects.create(nome="A2", reparto=rep2)
        self.assertIsNone(resolve_responsabile_effettivo(area=area2, reparto=rep2))

    def test_map_per_dipendente(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=100, area_aziendale=self.area_con_resp,
        )
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=101, area_aziendale=self.area_senza_resp,
        )
        m = build_responsabile_effettivo_map([100, 101])
        self.assertEqual(m, {100: 20, 101: 10})
```

- [ ] **Step 2: Run test → FALLISCE**

Comando standard su `anagrafica.tests_responsabile_effettivo`. Atteso: `ImportError` su `resolve_responsabile_effettivo`.

- [ ] **Step 3: Implementa (in coda a `reparto_canonico.py`)**

```python
def resolve_responsabile_effettivo(*, area, reparto) -> int | None:
    """Responsabile effettivo di un dipendente: il responsabile dell'AREA
    AZIENDALE vince sul caporeparto del REPARTO quando differisce; il capo
    reparto è il fallback. ``None`` se nessuno dei due è valorizzato."""
    if area is not None and area.responsabile_legacy_id:
        return int(area.responsabile_legacy_id)
    if reparto is not None and reparto.caporeparto_legacy_id:
        return int(reparto.caporeparto_legacy_id)
    return None


def build_responsabile_effettivo_map(legacy_ids: list[int] | None = None) -> dict[int, int]:
    """``legacy_anagrafica_id`` → id legacy del responsabile effettivo."""
    result: dict[int, int] = {}
    for legacy_id, area in build_area_canonica_map(legacy_ids).items():
        rep = area.reparto if area.reparto_id else None
        resp = resolve_responsabile_effettivo(area=area, reparto=rep)
        if resp is not None:
            result[legacy_id] = resp
    return result
```

- [ ] **Step 4: Run test → PASSA** (`OK`, 4 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/services/reparto_canonico.py django_app/anagrafica/tests_responsabile_effettivo.py
git commit -m "feat(anagrafica): responsabile effettivo (area vince sul reparto) - fonte unica in reparto_canonico"
```

---

### Task 3: Wiring responsabile effettivo in `_sync_aziendale_from_reparto` + notifiche

**Files:**
- Modify: `django_app/anagrafica/views.py` (`_sync_aziendale_from_reparto` ~riga 5635)
- Modify: `django_app/anagrafica/services/onboarding.py` (`_caporeparto_emails` ~riga 243)
- Test: `django_app/anagrafica/tests_responsabile_effettivo.py` (estende)

**Interfaces:**
- Consumes: `resolve_responsabile_effettivo` (Task 2).
- Produces: il denormalizzato `DipendenteAnagraficaAziendale.caporeparto_legacy_id` è il **responsabile effettivo**; `_caporeparto_emails` risolve l'email dello stesso.

- [ ] **Step 1: Scrivi il test** (nel modulo del Task 2)

```python
class SyncResponsabileEffettivoTests(TestCase):
    def setUp(self):
        self.rep = Reparto.objects.create(nome="RepX", caporeparto_legacy_id=10)
        self.area = AreaAziendale.objects.create(
            nome="AreaX", reparto=self.rep, responsabile_legacy_id=20,
        )

    def test_sync_scrive_responsabile_area_non_capo_reparto(self):
        from anagrafica.views import _sync_aziendale_from_reparto
        _sync_aziendale_from_reparto(
            legacy_id=100, reparto_nome="RepX",
            area_aziendale_id=self.area.id, saved_by=None,
        )
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=100)
        self.assertEqual(az.caporeparto_legacy_id, 20)  # area vince

    def test_sync_fallback_capo_reparto_se_area_senza_responsabile(self):
        area2 = AreaAziendale.objects.create(nome="AreaY", reparto=self.rep)
        from anagrafica.views import _sync_aziendale_from_reparto
        _sync_aziendale_from_reparto(
            legacy_id=101, reparto_nome="RepX",
            area_aziendale_id=area2.id, saved_by=None,
        )
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=101)
        self.assertEqual(az.caporeparto_legacy_id, 10)
```

- [ ] **Step 2: Run test → FALLISCE** (oggi scrive sempre `rep.caporeparto_legacy_id` → il primo test fallisce con `10 != 20`).

- [ ] **Step 3: Implementa (hunk minimo in `_sync_aziendale_from_reparto`)**

Sostituire il calcolo di `capo_id` (righe ~5648-5659) così che, risolta l'area valida, il responsabile effettivo sia `resolve_responsabile_effettivo(area=area, reparto=rep)`; se l'area non è valida/assente resta il fallback `rep.caporeparto_legacy_id`. Import in cima al modulo o inline:
`from anagrafica.services.reparto_canonico import resolve_responsabile_effettivo`.

In `onboarding._caporeparto_emails`: dopo aver risolto il `Reparto`, se è passato/ricavabile anche l'area usare il responsabile effettivo; per non allargare la firma, in questa iterazione basta risolvere dal reparto **ma** documentare che il denormalizzato del dipendente (già corretto dal `_sync`) è la fonte preferenziale a valle. *(Se `_caporeparto_emails` riceve solo il nome reparto, il fix del denormalizzato del Task 3-Step 3 copre già i consumatori che leggono `az.caporeparto_legacy_id`.)*

- [ ] **Step 4: Run test → PASSA** (`OK`, 2 test). Regressione mirata: `anagrafica.tests_responsabile_effettivo`.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/services/onboarding.py django_app/anagrafica/tests_responsabile_effettivo.py
git commit -m "fix(anagrafica): caporeparto denormalizzato = responsabile area aziendale quando differisce"
```

---

### Task 4: Report dipendenti — reparto/area canonici (rimozione reparto legacy)

**Files:**
- Modify: `django_app/anagrafica/views.py` (`dipendenti_report` ~riga 5197: filtro, enrich, `reparti_list`, colonne CSV)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendenti_report.html` (rimozione colonna "Reparto (legacy)")
- Test: `django_app/anagrafica/tests_dipendenti_report_canonico.py` (nuovo)

**Interfaces:**
- Consumes: `reparto_canonico.enrich_rows_reparto_canonico` (già esistente), catalogo `Reparto`.
- Produces: report con **un solo** reparto (canonico) + area aziendale canonica; filtro reparto dal catalogo; CSV senza colonna legacy.

- [ ] **Step 1: Scrivi il test**

```python
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from anagrafica.models import (
    AreaAziendale, DipendenteAnagraficaAziendale, Reparto,
)

User = get_user_model()


class DipendentiReportCanonicoTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-rep", "su-rep@test.local", "x")
        self.rep = Reparto.objects.create(nome="Produzione Canonica")
        self.area = AreaAziendale.objects.create(nome="Linea A", reparto=self.rep)

    def _get(self, **params):
        from anagrafica.views import dipendenti_report
        rf = RequestFactory()
        request = rf.get("/anagrafica/dipendenti/report/", params)
        request.user = self.su
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return dipendenti_report(request)

    def test_pagina_non_ha_colonna_reparto_legacy(self):
        resp = self._get()
        body = resp.content.decode()
        self.assertNotIn("Reparto (legacy)", body)
        self.assertIn("Reparto", body)  # colonna canonica

    def test_csv_header_senza_reparto_legacy_con_area(self):
        resp = self._get(format="csv")
        header = resp.content.decode(errors="ignore").splitlines()[0]
        self.assertIn("Reparto", header)
        self.assertIn("Area aziendale", header)
```

*(Se il rendering completo richiede righe legacy, i test possono verificare header/colonne su dataset vuoto: la struttura tabellare è indipendente dai dati.)*

- [ ] **Step 2: Run test → FALLISCE** (il template contiene ancora "Reparto (legacy)").

- [ ] **Step 3: Implementa**

(a) In `dipendenti_report`: dopo aver costruito `all_rows` e arricchito con `az`/`civ`, chiamare `enrich_rows_reparto_canonico(all_rows)`; sostituire il filtro reparto (righe 5226-5230) con un match sul `row["reparto"]` **canonico**; alimentare `reparti_list` dai nomi del catalogo `Reparto.objects.filter(is_active=True)`; nel CSV sostituire la colonna legacy con reparto canonico e aggiungere/rinominare "Area aziendale" da `row["area_aziendale_nome"]`.

(b) Nel template: rimuovere `<th>Reparto (legacy)</th>` (riga 153) e la relativa `<td>` (riga 174); rinominare "Reparto (catalogo)" in "Reparto" e sorgente `{{ row.reparto }}`; aggiungere colonna "Area aziendale" `{{ row.area_aziendale_nome|default:"—" }}`. Il filtro "Reparto (catalogo)" (righe 98-102) resta ma popolato dal catalogo.

- [ ] **Step 4: Run test → PASSA** (`OK`, 2 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/templates/anagrafica/pages/dipendenti_report.html django_app/anagrafica/tests_dipendenti_report_canonico.py
git commit -m "feat(anagrafica): report dipendenti su reparto/area canonici - rimosso reparto legacy testo libero"
```

---

### Task 5a: Builder albero dei RUOLI (`build_ruolo_albero`)

**Files:**
- Create: `django_app/anagrafica/services/organigramma_albero.py`
- Test: `django_app/anagrafica/tests_organigramma_albero.py` (nuovo)

**Interfaces:**
- Consumes: `RuoloOperativo` (`riporta_a`), `core.operational_roles.get_anagrafica_ids_for_role`, `fetch_anagrafica_rows` (per i nomi).
- Produces: `build_ruolo_albero() -> list[dict]` — nodi `{ "ruolo": RuoloOperativo, "titolari": [{"legacy_id", "nome"}], "figli": [nodo...] }`. Radici = `riporta_a IS NULL`. Difesa anti-ciclo.

- [ ] **Step 1: Scrivi il test**

```python
from django.test import TestCase
from anagrafica.models import RuoloOperativo, DipendenteRuoloOperativo
from anagrafica.services.organigramma_albero import build_ruolo_albero


class RuoloAlberoTests(TestCase):
    def setUp(self):
        self.capo = RuoloOperativo.objects.create(nome="Coordinatore")
        self.sub = RuoloOperativo.objects.create(nome="Caporeparto", riporta_a=self.capo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=self.sub)

    def test_radici_sono_ruoli_senza_riporta_a(self):
        albero = build_ruolo_albero()
        nomi_radici = {n["ruolo"].nome for n in albero}
        self.assertIn("Coordinatore", nomi_radici)
        self.assertNotIn("Caporeparto", nomi_radici)  # è figlio

    def test_gerarchia_ruolo_e_titolari_come_foglie(self):
        albero = build_ruolo_albero()
        coord = next(n for n in albero if n["ruolo"].nome == "Coordinatore")
        figlio = coord["figli"][0]
        self.assertEqual(figlio["ruolo"].nome, "Caporeparto")
        self.assertEqual({t["legacy_id"] for t in figlio["titolari"]}, {1})
        # i titolari non hanno "figli": sono foglie, mai gerarchia tra persone
        self.assertNotIn("figli", figlio["titolari"][0])
```

- [ ] **Step 2: Run test → FALLISCE** (`ImportError`).

- [ ] **Step 3: Implementa** `build_ruolo_albero` in `organigramma_albero.py`: carica i `RuoloOperativo` attivi, indicizza per `riporta_a_id`, costruisce ricorsivamente da `riporta_a IS NULL` con `set` dei visitati (anti-ciclo), risolve i nomi dei titolari da `fetch_anagrafica_rows` (mappa `id→"Cognome Nome"`) sugli id di `get_anagrafica_ids_for_role`.

- [ ] **Step 4: Run test → PASSA** (`OK`, 2 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/services/organigramma_albero.py django_app/anagrafica/tests_organigramma_albero.py
git commit -m "feat(anagrafica): build_ruolo_albero - albero gerarchico tra RUOLI (riporta_a), persone come foglie"
```

---

### Task 5b: Overlay copertura certificazione (`build_certificazione_copertura`)

**Files:**
- Modify: `django_app/anagrafica/services/organigramma_albero.py`
- Test: `django_app/anagrafica/tests_organigramma_albero.py` (estende)

**Interfaces:**
- Consumes: `build_ruolo_albero`, `DipendenteQualifica` (filtro `tipo_id`, `data_scadenza`), `TipoQualifica`.
- Produces: `build_certificazione_copertura(tipo_qualifica_id, oggi=None) -> list[dict]` — stesso albero con, per ogni titolare, `stato ∈ {"posseduta_valida","scaduta","mancante"}`; per nodo `n_copertura`/`n_totale`.

- [ ] **Step 1: Scrivi il test**

```python
from datetime import timedelta
from django.utils import timezone
from anagrafica.models import TipoQualifica, DipendenteQualifica
from anagrafica.services.organigramma_albero import build_certificazione_copertura


class CertificazioneCoperturaTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=2, ruolo=self.ruolo)
        self.cert = TipoQualifica.objects.create(nome="Patentino saldatura")
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=1, tipo=self.cert,
            data_scadenza=self.oggi + timedelta(days=100),
        )

    def test_copertura_valida_scaduta_mancante(self):
        albero = build_certificazione_copertura(self.cert.pk)
        nodo = next(n for n in albero if n["ruolo"].nome == "Saldatore")
        stati = {t["legacy_id"]: t["stato"] for t in nodo["titolari"]}
        self.assertEqual(stati[1], "posseduta_valida")
        self.assertEqual(stati[2], "mancante")
        self.assertEqual(nodo["n_totale"], 2)
        self.assertEqual(nodo["n_copertura"], 1)
```

- [ ] **Step 2: Run test → FALLISCE** (`ImportError`).

- [ ] **Step 3: Implementa** riusando `build_ruolo_albero`: precalcola per il `tipo_id` la mappa `legacy_id → stato` (valida se `data_scadenza` assente o ≥ oggi; scaduta se < oggi; mancante altrimenti), poi annota ricorsivamente i titolari e aggrega `n_copertura`/`n_totale` per nodo (inclusi i figli o solo il nodo — decidere nel test; qui per-nodo diretto).

- [ ] **Step 4: Run test → PASSA** (`OK`, 1 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/services/organigramma_albero.py django_app/anagrafica/tests_organigramma_albero.py
git commit -m "feat(anagrafica): build_certificazione_copertura - copertura ad albero per singola certificazione"
```

---

### Task 6: View + route + template albero ruoli (+ toggle)

**Files:**
- Modify: `django_app/anagrafica/views.py` (nuova view `organigramma_albero`, **una** funzione)
- Modify: `django_app/anagrafica/urls.py` (**una** riga, dopo `organigramma/` riga 238)
- Create: `django_app/anagrafica/templates/anagrafica/pages/organigramma_albero.html`
- Modify: `django_app/anagrafica/templates/anagrafica/pages/organigramma.html` (link toggle nell'header)
- Test: `django_app/anagrafica/tests_organigramma_albero.py` (estende)

**Interfaces:**
- Consumes: `build_ruolo_albero`, `build_certificazione_copertura` (per il `?certificazione=`), `TipoQualifica` (selettore).
- Produces: view `organigramma_albero` + route name `organigramma_albero` (`organigramma/albero/`); template ricorsivo (partial per il nodo, `{% include %}` auto-ricorsivo con `only`).

- [ ] **Step 1: Scrivi il test**

```python
from django.test import RequestFactory
from django.contrib.auth import get_user_model
User = get_user_model()


class OrganigrammaAlberoViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-org", "su-org@test.local", "x")
        self.capo = RuoloOperativo.objects.create(nome="CoordView")
        self.sub = RuoloOperativo.objects.create(nome="CaporepView", riporta_a=self.capo)

    def _get(self, **params):
        from anagrafica.views import organigramma_albero
        rf = RequestFactory()
        request = rf.get("/anagrafica/organigramma/albero/", params)
        request.user = self.su
        return organigramma_albero(request)

    def test_render_albero_ruoli(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("CoordView", body)
        self.assertIn("CaporepView", body)
```

- [ ] **Step 2: Run test → FALLISCE** (`ImportError` su `organigramma_albero`).

- [ ] **Step 3: Implementa view + route + template**

(a) `views.py`, dopo `organigramma` (dopo riga 13409):

```python
@login_required
def organigramma_albero(request):
    """Organigramma ad albero: gerarchia dei RUOLI (RuoloOperativo.riporta_a),
    persone come foglie titolari. Con ?certificazione=<TipoQualifica.pk> mostra
    la copertura ad albero della certificazione (chi la possiede). La gerarchia
    è SEMPRE tra ruoli, mai tra persone."""
    from anagrafica.services.organigramma_albero import (
        build_ruolo_albero, build_certificazione_copertura,
    )
    raw = (request.GET.get("certificazione") or "").strip()
    cert_id = int(raw) if raw.isdigit() else None
    albero = build_certificazione_copertura(cert_id) if cert_id else build_ruolo_albero()
    return render(request, "anagrafica/pages/organigramma_albero.html", {
        "albero": albero,
        "cert_id": cert_id,
        "certificazioni": TipoQualifica.objects.filter(is_active=True).order_by("nome"),
    })
```

(b) `urls.py`, subito dopo la riga `organigramma/` (238):

```python
    path("organigramma/albero/", views.organigramma_albero, name="organigramma_albero"),
```

(c) Template `organigramma_albero.html`: header con selettore `certificazione` (GET) e link toggle a `{% url 'anagrafica:organigramma' %}`; il corpo include un partial ricorsivo del nodo (`_org_nodo.html`) che rende `ruolo.nome`, i titolari come lista foglia, e `{% include %}` di sé stesso sui `figli` con `only`. Nessuna variabile con `_` iniziale; `{# #}` solo monoriga.

(d) `organigramma.html`: nell'header (accanto ai bottoni, ~riga 104) aggiungere `<a class="hr-btn hr-btn-outline" href="{% url 'anagrafica:organigramma_albero' %}">🌳 Vista albero</a>`.

- [ ] **Step 4: Run test → PASSA** (`OK`, 1 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/urls.py django_app/anagrafica/templates/anagrafica/pages/organigramma_albero.html django_app/anagrafica/templates/anagrafica/pages/organigramma.html django_app/anagrafica/tests_organigramma_albero.py
git commit -m "feat(anagrafica): vista organigramma ad albero (gerarchia ruoli) + toggle dalla griglia"
```

---

### Task 7: Overlay certificazione nel template albero

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/organigramma_albero.html` (+ partial nodo)
- Test: `django_app/anagrafica/tests_organigramma_albero.py` (estende)

**Interfaces:**
- Consumes: `build_certificazione_copertura` (già cablata nella view al Task 6).
- Produces: rendering della copertura (badge posseduta/scaduta/mancante + `n_copertura/n_totale`) quando `?certificazione=` è attivo.

- [ ] **Step 1: Scrivi il test**

```python
class OrganigrammaAlberoCoperturaViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-cov", "su-cov@test.local", "x")
        self.ruolo = RuoloOperativo.objects.create(nome="SaldView")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=self.ruolo)
        self.cert = TipoQualifica.objects.create(nome="CertView")

    def test_render_copertura_certificazione(self):
        from anagrafica.views import organigramma_albero
        rf = RequestFactory()
        request = rf.get("/anagrafica/organigramma/albero/", {"certificazione": str(self.cert.pk)})
        request.user = self.su
        resp = organigramma_albero(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("CertView", body)   # selettore selezionato
        self.assertIn("SaldView", body)
```

- [ ] **Step 2: Run test → FALLISCE** (se il template non rende ancora l'overlay/selezione).

- [ ] **Step 3: Implementa** nel partial nodo: se il titolare ha la chiave `stato`, mostrare un badge (verde valida / rosso scaduta / grigio mancante) e, a livello nodo, `{{ nodo.n_copertura }}/{{ nodo.n_totale }}`; nel selettore marcare `selected` la certificazione attiva (`cert_id`).

- [ ] **Step 4: Run test → PASSA**.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/organigramma_albero.html django_app/anagrafica/tests_organigramma_albero.py
git commit -m "feat(anagrafica): overlay copertura certificazione nell'organigramma ad albero"
```

---

### Task 8: Organigramma a griglia — responsabile effettivo nel capo mostrato

**Files:**
- Modify: `django_app/anagrafica/views.py` (`organigramma._blocco_reparto` ~riga 13379)
- Test: `django_app/anagrafica/tests_organigramma_albero.py` (o `tests_responsabile_effettivo.py`)

**Interfaces:**
- Consumes: `build_responsabile_effettivo_map` (Task 2).
- Produces: nella griglia, il "Capo" del blocco riflette il responsabile effettivo dei membri quando l'area ha un responsabile diverso dal capo reparto. *(Hunk minimo; se il costo/rischio di conflitto è alto, questo task è opzionale e può essere rimandato: la correttezza a valle è già garantita dal denormalizzato del Task 3.)*

- [ ] **Step 1: Scrivi il test** — verifica che, dato un reparto con area a responsabile diverso, il blocco esponga il responsabile effettivo (via context della view `organigramma`).

- [ ] **Step 2: Run test → FALLISCE**.

- [ ] **Step 3: Implementa** hunk minimo in `_blocco_reparto`/costruzione blocchi: usare la mappa responsabile effettivo per i membri dell'area; mantenere `rep.caporeparto_legacy_id` come fallback del blocco reparto.

- [ ] **Step 4: Run test → PASSA**.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_organigramma_albero.py
git commit -m "feat(anagrafica): organigramma griglia usa il responsabile effettivo dell'area"
```

---

### Task 9: CHANGELOG + README + regressione

**Files:**
- Modify: `CHANGELOG.md` (sezione `[Unreleased]`: tutti i file toccati + descrizione)
- Modify: `README.md` (catalogo moduli / `<details>` anagrafica: vista organigramma albero + certificazione; report canonico)

**Interfaces:** documentazione. Niente version bump.

- [ ] **Step 1: Aggiorna CHANGELOG.md** elencando i file modificati/creati e la descrizione dei tre interventi.
- [ ] **Step 2: Aggiorna README.md** (rotte `organigramma/albero/`, vista albero per ruolo/certificazione, report dipendenti canonico).
- [ ] **Step 3: Regressione mirata** (label app, timeout ≥ 600000):

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_responsabile_effettivo anagrafica.tests_dipendenti_report_canonico anagrafica.tests_organigramma_albero --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: tutti verdi.

- [ ] **Step 4: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(anagrafica): CHANGELOG/README - organigramma albero + certificazione, report canonico, responsabile effettivo"
```

- [ ] **Step 5: Push**

```powershell
git push -u origin feature/anagrafica-organigramma-report
```

---

## Chiusura

- Verifica finale `git status` pulito nel worktree; nessun file dati staged.
- Rimozione worktree quando il ramo è integrato: `git worktree remove C:\Dev\pn-anag-organigramma` (o `cmd /c rmdir /s /q ...` + `git worktree prune` se il path è troppo lungo).
