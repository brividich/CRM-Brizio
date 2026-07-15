# Visite mediche — sessione "consona" e scadenze confermate — Piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** nella registrazione batch delle visite mediche il sistema propone solo dipendenti per cui il tipo di visita è davvero richiesto (ruoli operativi + processi MOD.128, cessati esclusi), e una volta registrata la visita la vecchia scadenza si rinnova in TUTTE le viste (dashboard, KPI, export, digest) perché "confermata".

**Architecture:** nessuna migrazione DB. Un helper di servizio (`ultime_visite_correnti_ids`) diventa la fonte unica della definizione "ultima visita per (dipendente, tipo)" — max `data_svolgimento`, spareggio `pk` — e viene riusato da dashboard, index, scadenzario, export Excel e digest AU45. Il builder dei candidati sessione viene riscritto attorno a un nuovo helper `_requisiti_tipo_visita` (ruoli + MOD.128 + flag `ha_vincoli`); il POST batch guadagna guardrail (anti-doppione, no date future, prescrizioni/note separate, referto per riga tramite l'helper condiviso `_salva_referto_visita`).

**Tech Stack:** Django 5.2, Python 3.11, template SSR con stili inline (pagina `visite_mediche_nuova_sessione.html`), test `django.test.TestCase` + `RequestFactory`. DB prod SQL Server (`mssql-django`): ORM SQL Server-safe, niente window function.

**Spec di riferimento:** `docs/superpowers/specs/2026-07-15-visite-mediche-sessione-design.md` (nel checkout `C:\Dev\Portale Novicrom`).

## Global Constraints

- **Worktree dedicato obbligatorio** (regola CLAUDE.md "Session Isolation"): mai lavorare né committare nel checkout condiviso `C:\Dev\Portale Novicrom`. Task 1 crea `C:\Dev\pn-visite-sessione` su branch `feature/anagrafica-visite-sessione`.
- **Mai `git add -A` / `git commit -a`**: staging sempre con percorsi espliciti.
- **Venv**: il worktree non ha `.venv`. Usare sempre il Python del checkout condiviso: `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"`.
- **Test COSTOSI**: `config.settings.test` usa un DB SQLite con nome per-PID (`suite_<pid>.sqlite3`), quindi OGNI invocazione rimigra l'intero progetto: **~6-8 minuti a run anche per un solo test** (verificato). Perciò: (a) una sola run "rossa" e una sola run "verde" per task, mai per singolo test; (b) timeout ≥ 600000 ms; (c) `--verbosity 1`. `--keepdb` è innocuo ma non aiuta tra run diverse.
- **Mai lanciare la suite completa** (`manage.py test` senza label).
- Tutti i test nuovi vanno in **`django_app/anagrafica/tests_visite_sessione.py`** (file nuovo). Label: `anagrafica.tests_visite_sessione`.
- Comando test standard (eseguito **dalla radice del worktree**):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_visite_sessione --settings=config.settings.test --keepdb --verbosity 1`
- **PowerShell** (non bash): path Windows, `&` per invocare exe quotati.
- Nel worktree manca `.env`: 3 test di `automazioni` fallirebbero per `DEFAULT_FROM_EMAIL` vuoto — noto, NON è una regressione, e comunque qui si lanciano solo label `anagrafica.*`.
- **Mai asserire su conteggi globali di `AuditLog`** (gli insert automatici della policy 2FA li rendono fragili); se serve, contare per azione specifica.
- Template Django: `{# #}` commenta UNA SOLA riga; mai commentare multi-riga con quello (i tag interni vengono eseguiti).
- ORM SQL Server-safe: niente `Window`/`distinct on`; il pattern "ultima riga per gruppo" è a 2 passaggi con `values().annotate(Max(...))`.
- Privacy: le visite mediche sono dato sanitario. Nessun esito/prescrizione nei log o nell'audit (solo conteggi); tutte le view restano gated da `_can_view_visite_mediche`.
- **CHANGELOG.md** va aggiornato (Task 9) con tutti i file toccati; **README.md** per il comportamento visibile. Obbligatori.
- Versione app corrente: 1.3.0. Il version bump segue la checklist `docs/ai/06_TESTING_AND_QUALITY_GATES.md` (Task 9). ATTENZIONE nota storica: il file `VERSION` va scritto **UTF-8 senza BOM** (un BOM ha già bloccato una release).

---

### Task 1: Setup worktree e branch

**Files:** nessun file di progetto; solo setup git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-visite-sessione` su branch `feature/anagrafica-visite-sessione` (base `origin/main`), usato da TUTTI i task successivi come cwd.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-visite-sessione -B feature/anagrafica-visite-sessione origin/main
Set-Location C:\Dev\pn-visite-sessione
git status
```

Atteso: `On branch feature/anagrafica-visite-sessione`, `nothing to commit, working tree clean`.

- [ ] **Step 2: Verifica che il venv condiviso risponda**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
```

Atteso: `Python 3.11.x` (o superiore).

---

### Task 2: Helper `ultime_visite_correnti_ids` (fonte unica "ultima visita")

**Files:**
- Modify: `django_app/anagrafica/services/visite.py`
- Test (nuovo): `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Produces: `anagrafica.services.visite.ultime_visite_correnti_ids(legacy_ids: Iterable[int] | None = None, tipo_ids: Iterable[int] | None = None) -> set[int]` — id delle `VisitaMedica` "correnti" (l'ultima per coppia `(legacy_anagrafica_id, tipo_id)`: max `data_svolgimento`, spareggio `pk` più alto). Consumata dai Task 3 e 4.

- [ ] **Step 1: Crea il file di test con la classe del helper**

Crea `django_app/anagrafica/tests_visite_sessione.py` con questo contenuto ESATTO:

```python
"""Test per la sessione visite mediche "consona" e la coerenza delle scadenze.

Spec:  docs/superpowers/specs/2026-07-15-visite-mediche-sessione-design.md
Piano: docs/superpowers/plans/2026-07-15-visite-mediche-sessione-scadenze.md
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    DocumentoDipendente,
    RuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)
from .services.visite import ultime_visite_correnti_ids

User = get_user_model()


class UltimeVisiteCorrentiIdsTests(TestCase):
    def setUp(self):
        self.tipo = TipoVisitaMedica.objects.create(nome="Periodica corrente", durata_mesi=12)
        self.tipo_b = TipoVisitaMedica.objects.create(nome="Audiometria corrente", durata_mesi=24)
        self.oggi = timezone.localdate()

    def test_ultima_per_coppia_dipendente_tipo(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        recente = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        altro_tipo = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo_b,
            data_svolgimento=self.oggi - timedelta(days=200),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {recente.pk, altro_tipo.pk})

    def test_retrodatata_inserita_dopo_non_diventa_corrente(self):
        recente = VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=5),
        )
        # Inserita DOPO (pk maggiore) ma con data più vecchia: non deve vincere.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=500),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {recente.pk})

    def test_spareggio_stessa_data_vince_pk_maggiore(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=3, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=30),
        )
        seconda = VisitaMedica.objects.create(
            legacy_anagrafica_id=3, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=30),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {seconda.pk})

    def test_filtri_legacy_ids_e_tipo_ids(self):
        v1 = VisitaMedica.objects.create(
            legacy_anagrafica_id=4, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        v2 = VisitaMedica.objects.create(
            legacy_anagrafica_id=5, tipo=self.tipo_b,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        self.assertEqual(ultime_visite_correnti_ids(legacy_ids=[4]), {v1.pk})
        self.assertEqual(ultime_visite_correnti_ids(tipo_ids=[self.tipo_b.pk]), {v2.pk})
```

- [ ] **Step 2: Run test → deve FALLIRE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_visite_sessione --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `ImportError: cannot import name 'ultime_visite_correnti_ids'` (fallimento all'import, tutti i test in errore). Durata ~6-8 min (migrazioni complete: normale).

- [ ] **Step 3: Implementa l'helper**

In `django_app/anagrafica/services/visite.py`:

(a) cambia la riga di import typing da:

```python
from typing import Any
```

a:

```python
from typing import Any, Iterable
```

(b) aggiungi in coda al file:

```python
def ultime_visite_correnti_ids(
    legacy_ids: Iterable[int] | None = None,
    tipo_ids: Iterable[int] | None = None,
) -> set[int]:
    """Id delle ``VisitaMedica`` **correnti**: l'ultima per coppia
    ``(legacy_anagrafica_id, tipo_id)``.

    Definizione canonica per tutto il portale: massima ``data_svolgimento``,
    a parità di data vince il ``pk`` più alto (stessa regola di
    ``ultime_visite_per_tipo``, qui in versione bulk). Le righe storiche
    superate NON sono "correnti": una scadenza superata da una visita più
    recente non deve più comparire come scaduta in nessuna vista.

    SQL Server-safe: niente window function, due query in tutto.
    """
    qs = VisitaMedica.objects.all()
    if legacy_ids is not None:
        qs = qs.filter(legacy_anagrafica_id__in=list(legacy_ids))
    if tipo_ids is not None:
        qs = qs.filter(tipo_id__in=list(tipo_ids))

    max_data = {
        (row["legacy_anagrafica_id"], row["tipo_id"]): row["max_data"]
        for row in (
            qs.order_by()
            .values("legacy_anagrafica_id", "tipo_id")
            .annotate(max_data=Max("data_svolgimento"))
        )
    }
    if not max_data:
        return set()

    correnti: dict[tuple[int, int], int] = {}
    for pk, lid, tid, data in qs.order_by().values_list(
        "id", "legacy_anagrafica_id", "tipo_id", "data_svolgimento"
    ):
        chiave = (lid, tid)
        if max_data.get(chiave) != data:
            continue
        prev = correnti.get(chiave)
        if prev is None or pk > prev:
            correnti[chiave] = pk
    return set(correnti.values())
```

- [ ] **Step 4: Run test → deve PASSARE**

Stesso comando dello Step 2. Atteso: `OK`, 4 test.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/services/visite.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): helper ultime_visite_correnti_ids, fonte unica ultima visita per (dipendente, tipo)"
```

---

### Task 3: Coerenza "scadenza confermata" — dashboard, index, scadenzario, export, digest

**Files:**
- Modify: `django_app/anagrafica/views.py` (view `visite_mediche_dashboard` ~riga 9702; view `index` blocco `n_visite_scadute` ~riga 536; view `scadenzario` sezione visite ~riga 7129; view `visite_mediche_export_scadenze` ~riga 10169; import dei servizi ~riga 132)
- Modify: `django_app/anagrafica/management/commands/send_visite_mediche_digest.py`
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `ultime_visite_correnti_ids()` dal Task 2.
- Produces: nessuna nuova interfaccia; comportamento (le righe superate spariscono da KPI/tabelle/export/digest).

- [ ] **Step 1: Scrivi i test (in coda a `tests_visite_sessione.py`)**

```python
class DashboardScadenzeConfermateTests(TestCase):
    """Dopo la registrazione di una nuova visita la vecchia scadenza è
    "confermata": non deve più comparire come scaduta nella dashboard."""

    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-visite-dash", email="su-visite-dash@test.local", password="x"
        )
        self.tipo = TipoVisitaMedica.objects.create(nome="Periodica coerenza", durata_mesi=12)
        self.oggi = timezone.localdate()

    def _dashboard_body(self) -> str:
        from .views import visite_mediche_dashboard
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_dashboard(request)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", errors="ignore")

    def test_scadenza_superata_sparisce_dopo_nuova_visita(self):
        # Visita del 10-03-2024 → scadenza 10-03-2025 (passata).
        VisitaMedica.objects.create(
            legacy_anagrafica_id=70, tipo=self.tipo,
            data_svolgimento=date(2024, 3, 10),
        )
        body = self._dashboard_body()
        # Da sola è la visita corrente: la scadenza vecchia compare sia nella
        # tabella "scadute o in scadenza" sia nel log "ultime registrazioni".
        self.assertGreaterEqual(body.count("10-03-2025"), 2)

        # Rinnovo: la vecchia riga resta SOLO nel log "ultime registrazioni"
        # (storico delle registrazioni), non più tra scadute/KPI/per-tipo.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=70, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=5),
        )
        body = self._dashboard_body()
        self.assertEqual(body.count("10-03-2025"), 1)


class DigestVisiteCorrentiTests(TestCase):
    def test_digest_esclude_righe_superate(self):
        from io import StringIO
        from django.core.management import call_command

        tipo = TipoVisitaMedica.objects.create(nome="Digest corrente", durata_mesi=12)
        oggi = timezone.localdate()
        # Riga vecchia: scadrebbe tra ~20 giorni (dentro la finestra 60gg)...
        VisitaMedica.objects.create(
            legacy_anagrafica_id=90, tipo=tipo,
            data_svolgimento=oggi - timedelta(days=345),
        )
        # ...ma è stata rinnovata ieri: la corrente scade tra ~1 anno.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=90, tipo=tipo,
            data_svolgimento=oggi - timedelta(days=1),
        )
        out = StringIO()
        call_command("send_visite_mediche_digest", "--dry-run", stdout=out)
        self.assertIn("Nessuna visita medica in scadenza", out.getvalue())
```

- [ ] **Step 2: Run test → i 2 nuovi devono FALLIRE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_visite_sessione --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: FAIL su `test_scadenza_superata_sparisce_dopo_nuova_visita` (count > 1) e su `test_digest_esclude_righe_superate` (il digest elenca la riga superata); i 4 test del Task 2 restano verdi.

- [ ] **Step 3: Estendi l'import dei servizi in `views.py`**

Alla riga ~132, cambia:

```python
from .services.visite import stato_visite, visite_storico
```

in:

```python
from .services.visite import stato_visite, ultime_visite_correnti_ids, visite_storico
```

- [ ] **Step 4: Dashboard — KPI, tabella scadenze, contatori per tipo, pannello sessioni**

In `visite_mediche_dashboard` (~riga 9702), subito dopo `nomi_map = _build_nomi_map()`, aggiungi:

```python
    # Fonte unica "visite correnti" (l'ultima per dipendente+tipo): le righe
    # storiche superate non contano più come scadute/in scadenza.
    correnti_qs = VisitaMedica.objects.filter(id__in=ultime_visite_correnti_ids())
```

Poi sostituisci le query così (stesse posizioni del codice attuale):

1. KPI:

```python
    kpi_scadute = correnti_qs.filter(
        data_scadenza__isnull=False, data_scadenza__lt=oggi
    ).count()
    kpi_in_scad = correnti_qs.filter(
        data_scadenza__isnull=False, data_scadenza__range=[oggi, soglia_avviso]
    ).count()
    kpi_visite_totali = VisitaMedica.objects.count()
```

(`kpi_visite_totali` resta volutamente sullo storico completo: è il totale registrazioni.)

2. Nei tre rami del filtro mese (`mese_corrente` / `prossimo_mese` / `tutti`), sostituisci ogni `scad_qs = VisitaMedica.objects.filter(` con `scad_qs = correnti_qs.filter(` (3 occorrenze, i filtri interni restano identici).

3. Contatori per tipo:

```python
    _valide_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in correnti_qs
        .filter(data_scadenza__gte=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }
    _scadute_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in correnti_qs
        .filter(data_scadenza__lt=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }
```

4. Nel loop `for t in tipi_attivi_qs:` sostituisci il calcolo di `legacy_ids_coperti`:

```python
        legacy_ids_coperti = set(
            correnti_qs
            .filter(tipo=t, data_scadenza__gte=oggi)
            .values_list("legacy_anagrafica_id", flat=True)
        )
```

5. Pannello "sessioni per tipo": sostituisci il blocco che calcola `_latest_ids_bulk` + `_latest_sessions_bulk` (il `values(...).annotate(max_id=Max("id"))` seguito dal fetch) con:

```python
        _latest_sessions_bulk = list(
            correnti_qs
            .filter(tipo_id__in=_all_tipo_ids)
            .select_related("tipo")
            .order_by("tipo_id", "legacy_anagrafica_id")
        )
```

(la variabile `_latest_ids_bulk` sparisce; il resto del blocco — loop su `_latest_sessions_bulk`, `_session_sort_key`, ecc. — resta identico).

- [ ] **Step 5: Index — `n_visite_scadute`**

Nella view `index` (~riga 536), sostituisci l'intero blocco `latest_ids = (...)` + `n_visite_scadute = VisitaMedica.objects.filter(id__in=latest_ids, ...)` con:

```python
    can_view_visite = _can_view_visite_mediche(request)
    n_visite_scadute = 0
    if can_view_visite:
        n_visite_scadute = VisitaMedica.objects.filter(
            id__in=ultime_visite_correnti_ids(), data_scadenza__lt=oggi
        ).count()
```

- [ ] **Step 6: Scadenzario — sezione visite**

Nella view `scadenzario` (~riga 7129), sostituisci il blocco `latest_ids = (...)` + `qs_v = VisitaMedica.objects.select_related("tipo").filter(id__in=latest_ids)` con:

```python
    if can_view_visite and filtro_tipo in ("", "visita"):
        qs_v = VisitaMedica.objects.select_related("tipo").filter(
            id__in=ultime_visite_correnti_ids(), data_scadenza__isnull=False
        )
```

(i filtri successivi su `filtro_stato` restano identici).

- [ ] **Step 7: Export Excel scadenze**

Nella view `visite_mediche_export_scadenze` (~riga 10169), subito dopo `filtro = request.GET.get("scad", "tutti").strip()` aggiungi:

```python
    correnti_ids = ultime_visite_correnti_ids()
```

e in ciascuno dei tre rami aggiungi il filtro correnti alla queryset, ad esempio il primo ramo diventa:

```python
        qs = VisitaMedica.objects.filter(
            id__in=correnti_ids,
            data_scadenza__isnull=False,
            data_scadenza__range=[oggi.replace(day=1), oggi.replace(day=ld)],
        )
```

(stessa aggiunta `id__in=correnti_ids` negli altri due rami `prossimo_mese` e default).

- [ ] **Step 8: Digest AU45**

In `django_app/anagrafica/management/commands/send_visite_mediche_digest.py`, cambia l'import dei modelli:

```python
from anagrafica.models import VisitaMedica
from anagrafica.services.visite import ultime_visite_correnti_ids
```

e la query:

```python
        in_scadenza = list(
            VisitaMedica.objects.filter(
                id__in=ultime_visite_correnti_ids(),
                data_scadenza__isnull=False,
                data_scadenza__gte=today,
                data_scadenza__lte=horizon,
            ).order_by("data_scadenza")
        )
```

- [ ] **Step 9: Run test → tutti verdi**

Stesso comando dello Step 2. Atteso: `OK` (6 test).

- [ ] **Step 10: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/management/commands/send_visite_mediche_digest.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "fix(anagrafica): scadenze visite 'confermate' - dashboard/index/scadenzario/export/digest solo su visite correnti"
```

---

### Task 4: Candidati sessione "consoni" (`_requisiti_tipo_visita` + riscrittura builder)

**Files:**
- Modify: `django_app/anagrafica/views.py` (helper `_build_candidati_sessione` ~riga 9917; nuovi helper subito sopra)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Produces:
  - `_cessati_legacy_ids() -> set[int]` (module-level in `views.py`);
  - `_requisiti_tipo_visita(tipo: TipoVisitaMedica) -> dict` con chiavi `da_ruoli: set[int]`, `da_processi: set[int]`, `ha_vincoli: bool` (`ha_vincoli` = il tipo HA ruoli o processi collegati in configurazione, anche senza persone assegnate) — consumata dai Task 5 e 6;
  - dict candidato con chiavi `legacy_id, nome, ultima_visita, data_scadenza, status, giorni_a_scadenza, origine` (`origine` ∈ `"ruolo" | "processo" | "storico"`) — consumato dal Task 7 (template).

- [ ] **Step 1: Scrivi i test (in coda a `tests_visite_sessione.py`)**

```python
class CandidatiSessioneTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Verniciatore")
        self.tipo = TipoVisitaMedica.objects.create(nome="Vernici", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)

    def _candidati(self, tipo=None):
        from .views import _build_candidati_sessione
        return _build_candidati_sessione(tipo or self.tipo, self.oggi)

    def _candidati_ids(self, tipo=None):
        return {c["legacy_id"] for c in self._candidati(tipo)}

    def test_mai_effettuata_proposta_per_ruolo(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=20, ruolo=self.ruolo)
        cand = self._candidati()
        self.assertEqual({c["legacy_id"] for c in cand}, {20})
        self.assertEqual(cand[0]["origine"], "ruolo")
        self.assertEqual(cand[0]["status"], "mai_effettuata")

    def test_cessato_escluso(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=21, ruolo=self.ruolo)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=21,
            data_cessazione=self.oggi - timedelta(days=30),
        )
        self.assertEqual(self._candidati_ids(), set())

    def test_abilitato_processo_mod128_incluso(self):
        from .models_mpq import (
            AbilitazioneProcesso, ClienteQualificante, ProcessoQualificato,
        )
        cliente = ClienteQualificante.objects.create(nome="Cliente MPQ test")
        proc = ProcessoQualificato.objects.create(nome="Saldatura speciale", cliente=cliente)
        proc.visite_richieste.add(self.tipo)
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=22, processo=proc)
        cand = [c for c in self._candidati() if c["legacy_id"] == 22]
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["origine"], "processo")

    def test_ruolo_configurato_senza_assegnatari_non_degrada_a_storico(self):
        # Il tipo HA un ruolo collegato ma nessuno lo possiede: chi ha solo
        # storico (senza ruolo) NON va proposto.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=33, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        self.assertEqual(self._candidati_ids(), set())

    def test_tipo_senza_vincoli_propone_solo_storico(self):
        tipo_libero = TipoVisitaMedica.objects.create(nome="Libera", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=40, tipo=tipo_libero,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        cand = self._candidati(tipo_libero)
        self.assertEqual({c["legacy_id"] for c in cand}, {40})
        self.assertEqual(cand[0]["origine"], "storico")
        self.assertEqual(cand[0]["data_scadenza"], cand[0]["ultima_visita"].data_scadenza)

    def test_visita_senza_scadenza_non_riproposta(self):
        tipo0 = TipoVisitaMedica.objects.create(nome="Una tantum", durata_mesi=0)
        tipo0.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=50, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=50, tipo=tipo0,
            data_svolgimento=self.oggi - timedelta(days=1000),
        )
        self.assertEqual(self._candidati_ids(tipo0), set())

    def test_visita_valida_oltre_soglia_non_proposta(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=51, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=51, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        self.assertEqual(self._candidati_ids(), set())
```

- [ ] **Step 2: Run test → i nuovi devono FALLIRE**

Stesso comando standard. Atteso: FAIL/ERROR sui test di `CandidatiSessioneTests` (`origine` KeyError, cessato incluso, MOD.128 assente, ecc.); i precedenti restano verdi.

- [ ] **Step 3: Aggiungi gli helper e riscrivi il builder**

In `django_app/anagrafica/views.py`, SOSTITUISCI integralmente la funzione `_build_candidati_sessione` (e aggiungi sopra di essa i due nuovi helper) con:

```python
def _cessati_legacy_ids() -> set[int]:
    """Id legacy dei dipendenti cessati (``data_cessazione`` valorizzata)."""
    return set(
        DipendenteAnagraficaAziendale.objects
        .filter(data_cessazione__isnull=False)
        .values_list("legacy_anagrafica_id", flat=True)
    )


def _requisiti_tipo_visita(tipo: TipoVisitaMedica) -> dict:
    """Chi è tenuto alla visita ``tipo`` e da dove nasce l'obbligo.

    Ritorna ``{"da_ruoli": set, "da_processi": set, "ha_vincoli": bool}``.
    ``ha_vincoli`` = il tipo ha ruoli operativi o processi MOD.128 COLLEGATI
    in configurazione (anche se nessuna persona li possiede): governa il
    fallback storico e la valutazione di pertinenza. Cessati NON filtrati qui.
    """
    ruolo_ids = list(tipo.ruoli_operativi.values_list("id", flat=True))
    da_ruoli: set[int] = set()
    if ruolo_ids:
        da_ruoli = set(
            DipendenteRuoloOperativo.objects
            .filter(ruolo_id__in=ruolo_ids)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    da_processi: set[int] = set()
    ha_processi = False
    try:
        from .models_mpq import AbilitazioneProcesso
        ha_processi = tipo.processi_richiedenti.exists()
        if ha_processi:
            da_processi = set(
                AbilitazioneProcesso.objects
                .filter(
                    stato=AbilitazioneProcesso.STATO_ATTIVA,
                    processo__visite_richieste=tipo,
                )
                .exclude(legacy_anagrafica_id=0)
                .values_list("legacy_anagrafica_id", flat=True)
            )
    except Exception:
        logger.warning(
            "Lookup requisiti MOD.128 per tipo visita %s fallito", tipo.pk, exc_info=True,
        )
    return {
        "da_ruoli": da_ruoli,
        "da_processi": da_processi,
        "ha_vincoli": bool(ruolo_ids) or ha_processi,
    }


def _build_candidati_sessione(tipo: TipoVisitaMedica, oggi) -> list[dict]:
    """Dipendenti candidati per una sessione di visita del tipo dato.

    Il tipo è "consono" quando è richiesto dai ruoli operativi del dipendente
    o da un processo MOD.128 a cui è abilitato; se il tipo non ha vincoli
    configurati si propone chi ha quel tipo nello storico (stato calcolato
    sull'ultima visita). Cessati sempre esclusi.

    Candidato = ultima visita del tipo scaduta, in scadenza entro 90 giorni,
    oppure mai effettuata (solo pool ruoli/processi). Un'ultima visita senza
    scadenza (durata 0) è valida per sempre: non viene riproposta.
    """
    soglia = oggi + _timedelta(days=90)
    cessati = _cessati_legacy_ids()
    req = _requisiti_tipo_visita(tipo)
    da_ruoli, da_processi = req["da_ruoli"], req["da_processi"]

    if req["ha_vincoli"]:
        pool_ids = (da_ruoli | da_processi) - cessati
    else:
        # Tipo non collegato a ruoli/processi: si propone chi ha quel tipo
        # nello storico, non tutta l'azienda.
        pool_ids = set(
            VisitaMedica.objects
            .filter(tipo=tipo)
            .values_list("legacy_anagrafica_id", flat=True)
        ) - cessati

    if not pool_ids:
        return []

    # Ultima visita del tipo per ogni candidato (spareggio: pk più alto).
    ultima_per_id: dict[int, VisitaMedica] = {}
    for v in (
        VisitaMedica.objects
        .filter(tipo=tipo, legacy_anagrafica_id__in=pool_ids)
        .select_related("tipo")
        .order_by("legacy_anagrafica_id", "-data_svolgimento", "-pk")
    ):
        if v.legacy_anagrafica_id not in ultima_per_id:
            ultima_per_id[v.legacy_anagrafica_id] = v

    nomi_map = _build_nomi_map()

    candidati = []
    for lid in pool_ids:
        ultima = ultima_per_id.get(lid)
        if ultima is None:
            status = "mai_effettuata"
            giorni = None
        elif ultima.data_scadenza is None:
            continue  # valida senza scadenza: non riproporre
        elif ultima.data_scadenza < oggi:
            status = "scaduta"
            giorni = (ultima.data_scadenza - oggi).days
        elif ultima.data_scadenza <= soglia:
            status = "in_scadenza"
            giorni = (ultima.data_scadenza - oggi).days
        else:
            continue  # ancora valida oltre la soglia dei 90 giorni

        if lid in da_ruoli:
            origine = "ruolo"
        elif lid in da_processi:
            origine = "processo"
        else:
            origine = "storico"

        candidati.append({
            "legacy_id": lid,
            "nome": nomi_map.get(lid, f"#{lid}"),
            "ultima_visita": ultima,
            "data_scadenza": ultima.data_scadenza if ultima else None,
            "status": status,
            "giorni_a_scadenza": giorni,
            "origine": origine,
        })

    # Ordine: in_scadenza → scaduta → mai_effettuata; poi alfabetico per nome
    _status_order = {"in_scadenza": 0, "scaduta": 1, "mai_effettuata": 2}
    candidati.sort(key=lambda c: (_status_order.get(c["status"], 9), c["nome"]))
    return candidati
```

Nota: `DipendenteAnagraficaAziendale`, `DipendenteRuoloOperativo`, `TipoVisitaMedica`, `VisitaMedica`, `logger`, `_timedelta` sono già importati/definiti in `views.py` — nessun nuovo import top-level.

- [ ] **Step 4: Run test → tutti verdi**

Comando standard. Atteso: `OK` (13 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): candidati sessione visite consoni - ruoli+MOD.128, cessati esclusi, fallback storico"
```

---

### Task 5: API ricerca dipendente — pertinenza e cessati esclusi

**Files:**
- Modify: `django_app/anagrafica/views.py` (view `visite_mediche_api_cerca_dipendente` ~riga 10130)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `_requisiti_tipo_visita`, `_cessati_legacy_ids` dal Task 4.
- Produces: JSON `{results: [{legacy_id, nome, pertinente}]}` — `pertinente` consumato dal JS del template (Task 7). Nuovo parametro GET `tipo_id`.

- [ ] **Step 1: Scrivi i test (in coda a `tests_visite_sessione.py`)**

```python
class ApiCercaDipendenteTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo)"
                " VALUES (%s, %s, %s, %s)",
                ["m.verdi", "Marco", "Verdi", 1],
            )
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s",
                ["m.verdi"],
            )
            self.legacy_id = int(cursor.fetchone()[0])
        self.user_super = User.objects.create_superuser(
            username="su-api-visite", email="su-api-visite@test.local", password="x"
        )
        self.ruolo = RuoloOperativo.objects.create(nome="Carrellista")
        self.tipo = TipoVisitaMedica.objects.create(nome="Carrelli", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)

    def _get(self, **params):
        from .views import visite_mediche_api_cerca_dipendente
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/api/cerca-dipendente/", params)
        request.user = self.user_super
        resp = visite_mediche_api_cerca_dipendente(request)
        return json.loads(resp.content)

    def test_flag_pertinente_false_se_tipo_non_richiesto(self):
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertEqual(len(data["results"]), 1)
        self.assertFalse(data["results"][0]["pertinente"])

    def test_flag_pertinente_true_se_ruolo_collegato(self):
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=self.legacy_id, ruolo=self.ruolo,
        )
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertTrue(data["results"][0]["pertinente"])

    def test_tipo_senza_vincoli_sempre_pertinente(self):
        tipo_libero = TipoVisitaMedica.objects.create(nome="Libera api", durata_mesi=12)
        data = self._get(q="verdi", tipo_id=str(tipo_libero.pk))
        self.assertTrue(data["results"][0]["pertinente"])

    def test_cessato_escluso_dalla_ricerca(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.legacy_id,
            data_cessazione=timezone.localdate() - timedelta(days=10),
        )
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertEqual(data["results"], [])
```

- [ ] **Step 2: Run test → i 4 nuovi devono FALLIRE**

Comando standard. Atteso: KeyError `pertinente` / cessato presente nei risultati.

- [ ] **Step 3: Riscrivi la view API**

Sostituisci integralmente `visite_mediche_api_cerca_dipendente` con:

```python
@login_required
def visite_mediche_api_cerca_dipendente(request):
    """Ricerca live dipendenti per il popup '+Aggiungi dipendente' nella sessione.

    GET ?q=QUERY&exclude=ID1,ID2,...&tipo_id=N
    Ritorna JSON {results: [{legacy_id, nome, pertinente}, ...]}.

    ``pertinente`` = il tipo è richiesto al dipendente da ruoli operativi o
    processi MOD.128; se il tipo non ha vincoli configurati la pertinenza non
    è valutabile e vale sempre ``true``. I cessati non compaiono mai.
    """
    if not _can_view_visite_mediche(request):
        return JsonResponse({"error": "Forbidden"}, status=403)

    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    exclude_ids: set[int] = set()
    for s in request.GET.get("exclude", "").split(","):
        try:
            exclude_ids.add(int(s.strip()))
        except (ValueError, TypeError):
            pass
    exclude_ids |= _cessati_legacy_ids()

    pertinenti: set[int] | None = None
    tipo_id_raw = request.GET.get("tipo_id", "").strip()
    if tipo_id_raw:
        try:
            tipo = TipoVisitaMedica.objects.get(pk=int(tipo_id_raw))
        except (TipoVisitaMedica.DoesNotExist, ValueError, TypeError):
            tipo = None
        if tipo is not None:
            req = _requisiti_tipo_visita(tipo)
            if req["ha_vincoli"]:
                pertinenti = req["da_ruoli"] | req["da_processi"]

    qs = (
        AnagraficaDipendente.objects
        .filter(Q(cognome__icontains=q) | Q(nome__icontains=q))
        .exclude(id__in=exclude_ids)
        .order_by("cognome", "nome")[:25]
    )
    results = []
    for d in qs:
        cog = (getattr(d, "cognome", "") or "").strip()
        nom = (getattr(d, "nome", "") or "").strip()
        results.append({
            "legacy_id": d.id,
            "nome": f"{cog} {nom}".strip() or f"#{d.id}",
            "pertinente": True if pertinenti is None else (d.id in pertinenti),
        })
    return JsonResponse({"results": results})
```

- [ ] **Step 4: Run test → tutti verdi**

Comando standard. Atteso: `OK` (17 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): API cerca dipendente sessione visite - flag pertinente per tipo, cessati esclusi"
```

---

### Task 6: Registrazione batch — guardrail e campi ricchi

**Files:**
- Modify: `django_app/anagrafica/views.py` (view `visite_mediche_nuova_sessione` ~riga 9993; nuovo helper `_salva_referto_visita` prima di `dipendente_visita_add` ~riga 8995; refactor di `dipendente_visita_add` e `dipendente_visita_edit`)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `_requisiti_tipo_visita` (Task 4).
- Produces:
  - `_salva_referto_visita(request, visita: VisitaMedica, referto_file) -> DocumentoDipendente` (module-level in `views.py`);
  - campi POST per riga: `esito_{id}`, `prescrizioni_{id}`, `note_{id}`, file `referto_{id}` — consumati dal template (Task 7);
  - context step 2: `oggi` (date), `nuova_scadenza_preview` (date|None), `tipo_senza_vincoli` (bool), `medici_precedenti` (list[str]) — consumati dal template (Task 7).

- [ ] **Step 1: Scrivi i test (in coda a `tests_visite_sessione.py`)**

```python
class SessioneBatchPostTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-batch-visite", email="su-batch-visite@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Molatore")
        self.tipo = TipoVisitaMedica.objects.create(nome="Molatura", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=60, ruolo=self.ruolo)

    def _post(self, data):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.post("/anagrafica/visite-mediche/nuova-sessione/", data)
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return visite_mediche_nuova_sessione(request)

    def _base_step2(self, **extra):
        data = {
            "step": "2",
            "tipo_id": str(self.tipo.pk),
            "data_svolgimento": (self.oggi - timedelta(days=1)).isoformat(),
            "medico_competente": "Dr. Test",
            "dipendenti_selezionati": ["60"],
            "esito_60": "IDONEO",
            "prescrizioni_60": "DPI UDITO",
            "note_60": "nota di prova",
        }
        data.update(extra)
        return data

    def test_creazione_con_prescrizioni_e_note_separate(self):
        resp = self._post(self._base_step2())
        self.assertEqual(resp.status_code, 302)
        v = VisitaMedica.objects.get(legacy_anagrafica_id=60)
        self.assertEqual(v.prescrizioni, "DPI UDITO")
        self.assertEqual(v.note, "nota di prova")
        self.assertEqual(v.medico_competente, "Dr. Test")

    def test_doppione_stessa_data_saltato(self):
        self._post(self._base_step2())
        self._post(self._base_step2())
        self.assertEqual(
            VisitaMedica.objects.filter(legacy_anagrafica_id=60).count(), 1,
        )

    def test_data_futura_respinta(self):
        self._post(self._base_step2(
            data_svolgimento=(self.oggi + timedelta(days=3)).isoformat(),
        ))
        self.assertEqual(VisitaMedica.objects.count(), 0)

    def test_referto_per_riga_creato_e_agganciato(self):
        pdf = SimpleUploadedFile(
            "referto.pdf", b"%PDF-1.4 stub", content_type="application/pdf",
        )
        self._post(self._base_step2(referto_60=pdf))
        v = VisitaMedica.objects.get(legacy_anagrafica_id=60)
        self.assertIsNotNone(v.referto_documento_id)
        self.assertEqual(
            v.referto_documento.tipo, DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
        )
        self.assertEqual(v.referto_documento.legacy_anagrafica_id, 60)
```

- [ ] **Step 2: Run test → i 4 nuovi devono FALLIRE**

Comando standard. Atteso: FAIL su note separate (oggi il campo unico finisce in `prescrizioni` e `note` resta vuota), doppione (2 righe), data futura (riga creata), referto (assente).

- [ ] **Step 3: Estrai l'helper `_salva_referto_visita` e riusalo nelle view singole**

(a) In `views.py`, subito PRIMA di `dipendente_visita_add` (~riga 8995), aggiungi:

```python
def _salva_referto_visita(request, visita: VisitaMedica, referto_file) -> DocumentoDipendente:
    """Crea il ``DocumentoDipendente`` VISITA_MEDICA_REFERTO (storage privato)
    e lo aggancia a ``visita.referto_documento``. Percorso unico per form
    singolo e sessione batch."""
    doc = DocumentoDipendente(
        legacy_anagrafica_id=visita.legacy_anagrafica_id,
        tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
        nome_originale=getattr(referto_file, "name", "") or "referto",
        tipo_mime=getattr(referto_file, "content_type", "") or "",
        dimensione_bytes=getattr(referto_file, "size", 0) or 0,
        descrizione=f"Referto visita {visita.tipo.nome} del {visita.data_svolgimento}",
        oggetto_riferimento_tipo="anagrafica.visitamedica",
        oggetto_riferimento_id=visita.pk,
        created_by=request.user,
        created_by_display=request.user.get_full_name() or request.user.username,
    )
    doc.file.save(referto_file.name, referto_file, save=True)
    visita.referto_documento = doc
    visita.save(update_fields=["referto_documento", "updated_at"])
    return doc
```

(b) In `dipendente_visita_add`, sostituisci il blocco `if referto_file:` (creazione `DocumentoDipendente` + `doc.file.save` + aggancio) con:

```python
    referto_file = form.cleaned_data.get("referto_file")
    if referto_file:
        _salva_referto_visita(request, visita, referto_file)
```

(c) In `dipendente_visita_edit`, sostituisci lo stesso blocco di creazione/aggancio MA conservando la rimozione del referto precedente:

```python
    referto_file = form.cleaned_data.get("referto_file")
    if referto_file:
        # Se esisteva un referto, lo sostituiamo con uno nuovo
        if visita.referto_documento_id:
            try:
                visita.referto_documento.delete()
            except Exception:
                logger.warning(
                    "Impossibile rimuovere referto precedente di visita %s", v_id, exc_info=True,
                )
            visita.referto_documento = None
        _salva_referto_visita(request, visita, referto_file)
```

- [ ] **Step 4: Riscrivi il ramo POST step=2 di `visite_mediche_nuova_sessione`**

Sostituisci l'intero blocco `if request.method == "POST" and request.POST.get("step") == "2":` con:

```python
    if request.method == "POST" and request.POST.get("step") == "2":
        tipo_id = request.POST.get("tipo_id", "").strip()
        data_str = request.POST.get("data_svolgimento", "").strip()
        medico = request.POST.get("medico_competente", "").strip()

        try:
            tipo = TipoVisitaMedica.objects.get(pk=tipo_id, is_active=True)
        except (TipoVisitaMedica.DoesNotExist, ValueError):
            messages.error(request, "Tipo visita non valido.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        try:
            data_svolgimento = date.fromisoformat(data_str)
        except (ValueError, TypeError):
            messages.error(request, "Data non valida.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        if data_svolgimento > oggi:
            messages.error(request, "La data di svolgimento non può essere nel futuro.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        selected_ids = request.POST.getlist("dipendenti_selezionati")
        if not selected_ids:
            messages.warning(request, "Nessun dipendente selezionato.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        req = _requisiti_tipo_visita(tipo)
        pertinenti = (req["da_ruoli"] | req["da_processi"]) if req["ha_vincoli"] else None

        creati = 0
        doppioni = 0
        fuori_requisito = 0
        retrodatate = 0
        errori = []
        for legacy_id_str in selected_ids:
            try:
                legacy_id = int(legacy_id_str)
            except (ValueError, TypeError):
                continue
            esito = request.POST.get(f"esito_{legacy_id}", VisitaMedica.Esito.IDONEO)
            if esito not in VisitaMedica.Esito.values:
                esito = VisitaMedica.Esito.IDONEO
            prescrizioni = request.POST.get(f"prescrizioni_{legacy_id}", "").strip()
            note = request.POST.get(f"note_{legacy_id}", "").strip()
            try:
                # Anti-doppione: stessa persona, stesso tipo, stessa data.
                if VisitaMedica.objects.filter(
                    legacy_anagrafica_id=legacy_id, tipo=tipo,
                    data_svolgimento=data_svolgimento,
                ).exists():
                    doppioni += 1
                    continue
                visita = VisitaMedica.objects.create(
                    legacy_anagrafica_id=legacy_id,
                    tipo=tipo,
                    data_svolgimento=data_svolgimento,
                    esito=esito,
                    prescrizioni=prescrizioni,
                    note=note,
                    medico_competente=medico,
                    created_by=request.user,
                    updated_by=request.user,
                )
                referto_file = request.FILES.get(f"referto_{legacy_id}")
                if referto_file:
                    _salva_referto_visita(request, visita, referto_file)
                if pertinenti is not None and legacy_id not in pertinenti:
                    fuori_requisito += 1
                # Retro-registrazione: esiste già una visita più recente del
                # tipo — la riga è valida (storico) ma non diventa la corrente.
                if VisitaMedica.objects.filter(
                    legacy_anagrafica_id=legacy_id, tipo=tipo,
                    data_svolgimento__gt=data_svolgimento,
                ).exists():
                    retrodatate += 1
                creati += 1
            except Exception:
                logger.exception("Errore creazione VisitaMedica per legacy_id=%s", legacy_id)
                errori.append(legacy_id_str)

        try:
            from core.audit import log_action
            log_action(
                request,
                "VISITA_MEDICA_BATCH_CREATA",
                "anagrafica",
                f"Sessione {tipo.nome} del {data_svolgimento}: {creati} visite registrate, "
                f"{doppioni} doppioni saltati, {fuori_requisito} fuori requisito, "
                f"{retrodatate} retrodatate.",
            )
        except Exception:
            logger.warning("Audit VISITA_MEDICA_BATCH_CREATA fallito", exc_info=True)

        if errori:
            messages.warning(request, f"{creati} visite registrate. Errori per: {', '.join(errori)}.")
        else:
            msg = f"{creati} visite registrate per {tipo.nome} del {data_svolgimento.strftime('%d-%m-%Y')}."
            if doppioni:
                msg += f" {doppioni} già registrate in pari data: saltate."
            if fuori_requisito:
                msg += f" {fuori_requisito} fuori requisito (tipo non richiesto per il dipendente)."
            if retrodatate:
                msg += (
                    f" {retrodatate} retrodatate: esiste già una visita più recente,"
                    " le scadenze correnti non cambiano."
                )
            messages.success(request, msg)
        return redirect("anagrafica:visite_mediche_dashboard")
```

- [ ] **Step 5: Estendi il ramo step=1 e il context**

(a) Nel ramo `if request.method == "POST" and request.POST.get("step") == "1":`, dentro l'`else` che oggi chiama `_build_candidati_sessione`, aggiungi il controllo data futura PRIMA della chiamata:

```python
            else:
                if data_svolgimento_parsed > oggi:
                    messages.error(request, "La data di svolgimento non può essere nel futuro.")
                    step = 1
                else:
                    candidati = _build_candidati_sessione(tipo_selezionato, oggi)
                    if not candidati:
                        messages.info(
                            request,
                            f"Nessun dipendente risulta in scadenza per '{tipo_selezionato.nome}' "
                            f"nei prossimi 90 giorni.",
                        )
```

(b) PRIMA del `return render(...)` finale della view, aggiungi:

```python
    nuova_scadenza_preview = None
    tipo_senza_vincoli = False
    if step == 2 and tipo_selezionato and data_svolgimento_str:
        try:
            _data_sessione = date.fromisoformat(data_svolgimento_str)
        except (TypeError, ValueError):
            _data_sessione = None
        if _data_sessione and (tipo_selezionato.durata_mesi or 0) > 0:
            from .models import _add_months
            nuova_scadenza_preview = _add_months(_data_sessione, tipo_selezionato.durata_mesi)
        tipo_senza_vincoli = not _requisiti_tipo_visita(tipo_selezionato)["ha_vincoli"]

    medici_precedenti = list(
        VisitaMedica.objects
        .exclude(medico_competente="")
        .order_by("medico_competente")
        .values_list("medico_competente", flat=True)
        .distinct()[:20]
    )
```

(c) nel dict del `return render(...)` aggiungi le chiavi:

```python
        "oggi": oggi,
        "nuova_scadenza_preview": nuova_scadenza_preview,
        "tipo_senza_vincoli": tipo_senza_vincoli,
        "medici_precedenti": medici_precedenti,
```

- [ ] **Step 6: Run test → tutti verdi**

Comando standard. Atteso: `OK` (21 test).

- [ ] **Step 7: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): sessione visite - anti-doppione, no date future, prescrizioni/note separate, referto per riga"
```

---

### Task 7: Template sessione — colonne, badge origine, anteprima scadenza, referto, datalist

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html`
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: context del Task 6 (`oggi`, `nuova_scadenza_preview`, `tipo_senza_vincoli`, `medici_precedenti`), dict candidato del Task 4 (`origine`, `data_scadenza`), campi POST del Task 6, JSON `pertinente` del Task 5.

- [ ] **Step 1: Scrivi il test di rendering (in coda a `tests_visite_sessione.py`)**

```python
class SessioneStep2RenderTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-render-visite", email="su-render-visite@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Fonditore")
        self.tipo = TipoVisitaMedica.objects.create(nome="Fonderia", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=80, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=80, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def test_step2_mostra_nuove_colonne_e_campi(self):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.post("/anagrafica/visite-mediche/nuova-sessione/", {
            "step": "1",
            "tipo_id": str(self.tipo.pk),
            "data_svolgimento": self.oggi.isoformat(),
            "medico_competente": "",
        })
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_nuova_sessione(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", errors="ignore")
        self.assertIn("Scadenza attuale", body)
        self.assertIn('name="prescrizioni_80"', body)
        self.assertIn('name="note_80"', body)
        self.assertIn('name="referto_80"', body)
        self.assertIn('enctype="multipart/form-data"', body)
        self.assertIn("Nuova scadenza", body)
        self.assertIn("Ruolo", body)  # badge origine
```

- [ ] **Step 2: Run test → il nuovo deve FALLIRE**

Comando standard. Atteso: FAIL su `Scadenza attuale` / `prescrizioni_80`.

- [ ] **Step 3: Modifica il template**

In `visite_mediche_nuova_sessione.html`, applica queste modifiche puntuali (gli stili inline ricalcano quelli già presenti nel file):

(1) **Step 1 — input data con limite a oggi** (riga ~54):

```html
            <input type="date" name="data_svolgimento" value="{{ data_svolgimento_str }}" required max="{{ oggi|date:'Y-m-d' }}"
              style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;color:#1e293b;background:#fff;box-sizing:border-box;">
```

(2) **Step 1 — medico competente con suggerimenti** (riga ~59): sostituisci l'`<input type="text" name="medico_competente" ...>` con:

```html
            <input type="text" name="medico_competente" value="{{ medico_competente }}" placeholder="es. Dr. Rossi" list="medici-precedenti"
              style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;color:#1e293b;background:#fff;box-sizing:border-box;">
            <datalist id="medici-precedenti">
              {% for m in medici_precedenti %}<option value="{{ m }}"></option>{% endfor %}
            </datalist>
```

(3) **Step 2 — banner tipo senza vincoli**: subito dopo `{% if step == 2 %}` (riga ~73) aggiungi:

```html
  {% if tipo_senza_vincoli %}
  <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:12px 16px;font-size:13px;color:#9a3412;">
    ⚠️ <strong>{{ tipo_selezionato.nome }}</strong> non è collegato a ruoli operativi né a processi MOD.128:
    i candidati sono proposti dallo storico delle visite di questo tipo. Collega i ruoli dal catalogo tipologie per una proposta completa.
  </div>
  {% endif %}
```

(4) **Step 2 — anteprima nuova scadenza nella testata** (riga ~80, dentro il `<div style="font-size:12px;color:#64748b;...">`): dopo lo span `label-candidati-iniziali` e la data, aggiungi:

```html
          · Nuova scadenza: <strong>{% if nuova_scadenza_preview %}{{ nuova_scadenza_preview|date:"d-m-Y" }}{% else %}— (tipo senza periodicità){% endif %}</strong>
```

(5) **Step 2 — form multipart** (riga ~93):

```html
    <form method="post" id="form-step2" enctype="multipart/form-data">
```

(6) **Step 2 — intestazioni tabella** (righe ~104-109): sostituisci le `<th>` con:

```html
              <th style="text-align:center;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;width:44px;">Sel.</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;">Dipendente</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;">Ultima visita</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;">Scadenza attuale</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;">Stato</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;min-width:180px;">Esito</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;min-width:160px;">Prescrizioni</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;min-width:140px;">Note</th>
              <th style="text-align:left;padding:9px 10px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;">Referto</th>
```

(7) **Step 2 — riga candidato**: nella cella Dipendente, dopo il link col nome, aggiungi il badge origine:

```html
                {% if c.origine == "ruolo" %}<span style="display:inline-block;margin-left:6px;padding:1px 7px;background:#eff6ff;color:#1d4ed8;border-radius:999px;font-size:10px;font-weight:700;">Ruolo</span>
                {% elif c.origine == "processo" %}<span style="display:inline-block;margin-left:6px;padding:1px 7px;background:#ede9fe;color:#5b21b6;border-radius:999px;font-size:10px;font-weight:700;">MOD.128</span>
                {% else %}<span style="display:inline-block;margin-left:6px;padding:1px 7px;background:#f1f5f9;color:#64748b;border-radius:999px;font-size:10px;font-weight:700;">Storico</span>{% endif %}
```

Dopo la cella "Ultima visita" inserisci la nuova cella "Scadenza attuale":

```html
              <td style="padding:8px 10px;color:#475569;">
                {% if c.data_scadenza %}{{ c.data_scadenza|date:"d-m-Y" }}{% else %}<span style="color:#94a3b8;">—</span>{% endif %}
              </td>
```

Sostituisci la vecchia cella unica "Note / Prescrizioni" con le TRE celle:

```html
              <td style="padding:8px 10px;">
                <input type="text" name="prescrizioni_{{ c.legacy_id }}" placeholder="es. D.P.I. UDITO"
                  class="row-input-{{ c.legacy_id }}"
                  style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;background:#fff;color:#1e293b;box-sizing:border-box;">
              </td>
              <td style="padding:8px 10px;">
                <input type="text" name="note_{{ c.legacy_id }}" placeholder="note interne"
                  class="row-input-{{ c.legacy_id }}"
                  style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;background:#fff;color:#1e293b;box-sizing:border-box;">
              </td>
              <td style="padding:8px 10px;">
                <input type="file" name="referto_{{ c.legacy_id }}" accept=".pdf,image/*"
                  class="row-input-{{ c.legacy_id }}"
                  style="width:150px;font-size:11px;color:#475569;">
              </td>
```

(8) **JS — passa `tipo_id` alla ricerca** (funzione `cercaDipendente`, riga ~298): sostituisci la costruzione dell'URL con:

```javascript
    var url = '{% url "anagrafica:visite_mediche_api_cerca_dipendente" %}?q=' + encodeURIComponent(q)
      + '&exclude=' + encodeURIComponent(exclude)
      + '&tipo_id={{ tipo_selezionato.pk }}';
```

(9) **JS — click risultato passa l'intero item** (dentro `cercaDipendente`, riga ~315):

```javascript
            div.addEventListener('click', function() { aggiungiDipendente(item); });
```

(10) **JS — `aggiungiDipendente` con badge pertinenza e nuove celle**: sostituisci integralmente la funzione `aggiungiDipendente(legacyId, nome)` con:

```javascript
function aggiungiDipendente(item) {
  closeAggiungiModal();
  var legacyId = item.legacy_id;
  var nome = item.nome;
  if (document.getElementById('row-' + legacyId)) return; // già presente

  var tbody = document.getElementById('tbody-candidati');
  var tr = document.createElement('tr');
  tr.id = 'row-' + legacyId;
  tr.style.cssText = 'border-bottom:1px solid #f1f5f9;background:#f0fdf4;';

  // Checkbox
  var tdCb = document.createElement('td');
  tdCb.style.cssText = 'padding:8px 10px;text-align:center;';
  var cb = document.createElement('input');
  cb.type = 'checkbox'; cb.name = 'dipendenti_selezionati'; cb.value = legacyId;
  cb.className = 'candidato-check'; cb.checked = true;
  cb.style.cssText = 'width:16px;height:16px;cursor:pointer;';
  cb.addEventListener('change', function() { toggleRow(legacyId, this.checked); });
  tdCb.appendChild(cb);

  // Nome (+ avviso pertinenza)
  var tdNome = document.createElement('td');
  tdNome.style.cssText = 'padding:8px 10px;font-weight:600;color:#1e293b;';
  tdNome.textContent = nome;
  if (item.pertinente === false) {
    var warn = document.createElement('span');
    warn.style.cssText = 'display:inline-block;margin-left:6px;padding:1px 7px;background:#fef2f2;color:#b91c1c;border-radius:999px;font-size:10px;font-weight:700;';
    warn.textContent = '⚠ tipo non richiesto';
    warn.title = 'Questo tipo di visita non è richiesto dai ruoli/processi del dipendente.';
    tdNome.appendChild(warn);
  }

  // Ultima visita
  var tdUlt = document.createElement('td');
  tdUlt.style.cssText = 'padding:8px 10px;color:#94a3b8;font-style:italic;font-size:12px;';
  tdUlt.textContent = 'Aggiunto manualmente';

  // Scadenza attuale
  var tdScad = document.createElement('td');
  tdScad.style.cssText = 'padding:8px 10px;color:#94a3b8;';
  tdScad.textContent = '—';

  // Stato
  var tdStato = document.createElement('td');
  tdStato.style.cssText = 'padding:8px 10px;';
  var span = document.createElement('span');
  span.style.cssText = 'display:inline-block;padding:2px 9px;background:#f0fdf4;color:#166534;border-radius:999px;font-size:11px;font-weight:700;';
  span.textContent = 'Aggiunto';
  tdStato.appendChild(span);

  // Esito select
  var tdEsito = document.createElement('td');
  tdEsito.style.cssText = 'padding:8px 10px;';
  tdEsito.appendChild(_buildEsitoSelect(legacyId));

  // Prescrizioni
  var tdPrescr = document.createElement('td');
  tdPrescr.style.cssText = 'padding:8px 10px;';
  var inpP = document.createElement('input');
  inpP.type = 'text'; inpP.name = 'prescrizioni_' + legacyId;
  inpP.placeholder = 'es. D.P.I. UDITO';
  inpP.className = 'row-input-' + legacyId;
  inpP.style.cssText = 'width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;background:#fff;color:#1e293b;box-sizing:border-box;';
  tdPrescr.appendChild(inpP);

  // Note
  var tdNote = document.createElement('td');
  tdNote.style.cssText = 'padding:8px 10px;';
  var inpN = document.createElement('input');
  inpN.type = 'text'; inpN.name = 'note_' + legacyId;
  inpN.placeholder = 'note interne';
  inpN.className = 'row-input-' + legacyId;
  inpN.style.cssText = 'width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;background:#fff;color:#1e293b;box-sizing:border-box;';
  tdNote.appendChild(inpN);

  // Referto
  var tdRef = document.createElement('td');
  tdRef.style.cssText = 'padding:8px 10px;';
  var inpF = document.createElement('input');
  inpF.type = 'file'; inpF.name = 'referto_' + legacyId;
  inpF.accept = '.pdf,image/*';
  inpF.className = 'row-input-' + legacyId;
  inpF.style.cssText = 'width:150px;font-size:11px;color:#475569;';
  tdRef.appendChild(inpF);

  tr.appendChild(tdCb); tr.appendChild(tdNome); tr.appendChild(tdUlt);
  tr.appendChild(tdScad); tr.appendChild(tdStato); tr.appendChild(tdEsito);
  tr.appendChild(tdPrescr); tr.appendChild(tdNote); tr.appendChild(tdRef);
  tbody.appendChild(tr);
  updateCount();
}
```

Nota: il vecchio link `<a href="#">` sul nome degli aggiunti manuali era rotto per costruzione — nella nuova versione è testo semplice, va bene così.

- [ ] **Step 4: Run test → tutti verdi**

Comando standard. Atteso: `OK` (22 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): UI sessione visite - scadenza attuale, badge origine/pertinenza, anteprima nuova scadenza, referto e datalist medico"
```

---

### Task 8: Verifica di regressione sui test esistenti delle visite

**Files:** nessuna modifica prevista (solo run; fix eventuali regressioni).

**Interfaces:** nessuna.

- [ ] **Step 1: Lancia i test esistenti correlati + i nuovi in un'unica run**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_visite_sessione anagrafica.tests.VisitaMedicaScadenzaTests anagrafica.tests.StatoVisiteServiceTests anagrafica.tests.VisiteMedicheDashboardTests anagrafica.tests.VisiteMedichePermissionTests anagrafica.test_reminder_emails --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `OK` (i nomi delle classi sono verificati sul codice attuale; `anagrafica.test_reminder_emails` copre la regressione di `send_visite_expiry_reminders`, che NON deve cambiare comportamento). Se una label non risolvesse, verificare il nome reale in `django_app/anagrafica/` e correggerla — NON saltare la run.

- [ ] **Step 2: Se qualcosa è rosso**: la causa più probabile è un'asserzione del vecchio comportamento (es. dashboard che contava le righe storiche). Correggere il TEST solo se asseriva il comportamento sbagliato ora corretto dalla spec; correggere il CODICE se la regressione è reale. In caso di dubbio, rileggere la spec.

- [ ] **Step 3: Commit (solo se ci sono state correzioni)**

```powershell
git add -u django_app/anagrafica
git commit -m "test(anagrafica): allineamento test esistenti alla coerenza scadenze visite"
```

---

### Task 9: CHANGELOG, README, version bump e push

**Files:**
- Modify: `CHANGELOG.md` (sezione `[Unreleased]`)
- Modify: `README.md` (bullet "Visite mediche", ~riga 372)
- Modify (se richiesto dalla checklist): `VERSION`, `CLAUDE.md` (riga versione)
- Read: `docs/ai/06_TESTING_AND_QUALITY_GATES.md`

**Interfaces:** nessuna.

- [ ] **Step 1: CHANGELOG**

In `CHANGELOG.md`, sotto `## [Unreleased]`, nella sezione `### Changed` (creala in testa se assente), aggiungi questo blocco:

```markdown
- **Visite mediche · sessione "consona" e scadenze confermate** (`django_app/anagrafica/services/visite.py`, `django_app/anagrafica/views.py`, `django_app/anagrafica/management/commands/send_visite_mediche_digest.py`, `django_app/anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html`, `django_app/anagrafica/tests_visite_sessione.py` [nuovo]). Due difetti collegati: (1) la **registrazione sessione** proponeva candidati non pertinenti — includeva i cessati, ignorava le visite richieste dai processi MOD.128 e, per i tipi senza ruoli collegati, proponeva l'intera azienda; (2) registrata la nuova visita, la **vecchia scadenza restava "scaduta"** nella dashboard visite (KPI, tabella scadenze, contatori per tipologia), nell'export Excel e nel digest AU45, perché quelle viste contavano tutte le righe storiche anziché l'ultima per (dipendente, tipo). Nuovo helper `ultime_visite_correnti_ids()` come **fonte unica** della definizione "ultima visita" (max data svolgimento, spareggio pk — corregge anche il vecchio criterio `Max(id)` che sbagliava sugli inserimenti retrodatati), riusato da dashboard, index, scadenzario, export e digest: la scadenza superata ora "scade in quanto confermata" ovunque. Candidati sessione riscritti su `_requisiti_tipo_visita` (ruoli operativi + processi MOD.128 con abilitazione attiva, cessati esclusi, fallback storico solo per tipi senza vincoli, visite senza scadenza non riproposte) con **badge origine** (Ruolo/MOD.128/Storico) e colonna **scadenza attuale**; guardrail alla registrazione: **anti-doppione** (stessa persona/tipo/data saltata), **date future vietate** (allineato al form singolo), **prescrizioni e note separate** (prima il campo unico finiva solo in `prescrizioni`), **referto opzionale per riga** (helper condiviso `_salva_referto_visita`, stesso percorso del form singolo), audit arricchito con conteggi doppioni/fuori-requisito; aggiunta manuale con avviso di pertinenza (l'API di ricerca espone `pertinente` e nasconde i cessati) e **anteprima della nuova scadenza** in testata; medico competente con suggerimenti dai valori già usati. Test: `anagrafica.tests_visite_sessione` (22) + regressione classi visite esistenti.
```

- [ ] **Step 2: README**

In `README.md`, bullet **Visite mediche** (~riga 372): dopo la frase su `send_visite_expiry_reminders`, PRIMA di "Default permesso:", inserisci:

```markdown
**Sessione di registrazione batch** (`/anagrafica/visite-mediche/nuova-sessione/`): propone solo i dipendenti per cui il tipo è richiesto (ruoli operativi + processi MOD.128, cessati esclusi; per i tipi senza vincoli, solo chi ha quel tipo nello storico) con badge dell'origine della proposta, scadenza attuale e anteprima della nuova scadenza; guardrail anti-doppione e date future vietate; per riga esito, prescrizioni, note e referto opzionale; aggiunta manuale con avviso se il tipo non è pertinente. **Scadenze "confermate"**: tutte le viste (dashboard, scadenzario, export, digest AU45) contano solo l'ultima visita per dipendente+tipo — registrata la nuova visita, la vecchia scadenza sparisce ovunque.
```

- [ ] **Step 3: Version bump secondo checklist**

Leggere `docs/ai/06_TESTING_AND_QUALITY_GATES.md` e applicare la checklist di version bump per una modifica di comportamento user-facing (versione corrente 1.3.0). ATTENZIONE: se si tocca `VERSION`, scriverlo **UTF-8 senza BOM** (in PowerShell: `[System.IO.File]::WriteAllText("VERSION", "1.4.0`n", (New-Object System.Text.UTF8Encoding($false)))` — adattare il numero a quanto chiede la checklist). Aggiornare anche la riga versione in cima a `CLAUDE.md` se la checklist lo prevede.

- [ ] **Step 4: Commit e push**

```powershell
git add CHANGELOG.md README.md
git add VERSION CLAUDE.md  # solo se toccati dalla checklist
git commit -m "docs(anagrafica): changelog e readme per sessione visite consona e scadenze confermate"
git push -u origin feature/anagrafica-visite-sessione
```

Atteso: push riuscito. NON fare merge in `main` né toccare `release/prod`: la decisione di integrazione spetta all'utente.

- [ ] **Step 5: Riepilogo finale**

Riportare all'utente: branch pushato, elenco commit, esito test (numero verdi), file toccati, e ricordare che il worktree `C:\Dev\pn-visite-sessione` può essere rimosso dopo il merge (`git worktree remove C:\Dev\pn-visite-sessione`).

---

## Idee future (fuori scope, NON implementare)

Registrate nella spec come non-obiettivi; da proporre all'utente separatamente:
stato "programmata/convocazione" con conferma esiti post-visita; flusso
dipendente-first multi-tipo; anagrafica strutturata dei medici competenti;
PDF "registro sessione" sul template `core/pdf`; notifica al dipendente alla
registrazione della visita.
