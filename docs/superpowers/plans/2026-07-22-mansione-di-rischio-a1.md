# Mansione di rischio · A1 (modello + resolver) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estendere `EsposizioneRischio` con un target dipendente opzionale e aggiungere un resolver `requisiti_dipendente()` che unisce i requisiti di mansione, area e dipendente. Nessuna UI.

**Architecture:** Additivo. Nuovo campo nullable su `EsposizioneRischio` (terzo target accanto a mansione/area). Nuovo resolver in `services/mansionario.py` che riusa il resolver mansione esistente (`requisiti_per_nome_mansione`) e vi somma le esposizioni di area e dirette al dipendente, condividendo un helper fattori→requisiti (refactor DRY di `_resolve`).

**Tech Stack:** Django 5.2, SQLite in test (`config.settings.test_fast` per iterazione rapida), mssql-django in prod.

## Global Constraints

- Migrazioni **additive** e **SQL-Server-safe**: colonna nullable, `db_index=True`, nessun indice parziale né `UniqueConstraint` condizionale.
- Dipendente agganciato via `legacy_anagrafica_id` (IntegerField), **nessuna FK** al modello dipendente.
- Nessuna UI in A1 (form/scheda/DPI sono A2/A3).
- Test con: `& "C:/Dev/Portale Novicrom/.venv/Scripts/python.exe" "C:/Dev/pn-epica-a1/django_app/manage.py" test <label> --settings=config.settings.test_fast --keepdb` (creare `config/settings/test_fast.py` come in pn-quickwin: `from .test import *` + `DATABASES["default"]["TEST"]["NAME"]` fisso — **non committare**).
- Ogni task finisce con **commit**. CHANGELOG aggiornato nel task che tocca codice. README non toccato.

---

### Task 1: Modello — `EsposizioneRischio` target dipendente

**Files:**
- Modify: `django_app/anagrafica/models_rischi.py` (import ValidationError; campo `legacy_anagrafica_id`; `clean()`; `__str__`; index)
- Modify: `django_app/anagrafica/admin.py:385-389` (esporre il campo)
- Create: `django_app/anagrafica/migrations/00XX_esposizionerischio_legacy_anagrafica_id.py` (via `makemigrations`)
- Test: `django_app/anagrafica/tests_mansione_rischio_a1.py` (nuovo)

**Interfaces:**
- Produces: `EsposizioneRischio.legacy_anagrafica_id` (int|None); `EsposizioneRischio.clean()` che esige ≥1 target fra mansione/area/legacy_anagrafica_id.

- [ ] **Step 1: Write the failing test**

Creare `django_app/anagrafica/tests_mansione_rischio_a1.py`:

```python
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Mansione
from .models_rischi import EsposizioneRischio, FattoreRischio


class EsposizioneRischioTargetTests(TestCase):
    def setUp(self):
        self.fattore = FattoreRischio.objects.create(codice="RUM", nome="Rumore")

    def test_target_solo_dipendente_valido(self):
        esp = EsposizioneRischio(fattore=self.fattore, legacy_anagrafica_id=42)
        esp.full_clean()  # non deve sollevare
        esp.save()
        self.assertEqual(esp.legacy_anagrafica_id, 42)

    def test_nessun_target_non_valido(self):
        esp = EsposizioneRischio(fattore=self.fattore)
        with self.assertRaises(ValidationError):
            esp.full_clean()

    def test_target_mansione_resta_valido(self):
        m = Mansione.objects.create(nome="Tornitore-A1")
        EsposizioneRischio(fattore=self.fattore, mansione=m).full_clean()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:/Dev/Portale Novicrom/.venv/Scripts/python.exe" "C:/Dev/pn-epica-a1/django_app/manage.py" test anagrafica.tests_mansione_rischio_a1.EsposizioneRischioTargetTests --settings=config.settings.test_fast --keepdb`
Expected: FAIL — `test_target_solo_dipendente_valido` errore (campo `legacy_anagrafica_id` inesistente) e/o `test_nessun_target_non_valido` non solleva (nessun `clean`).

- [ ] **Step 3: Add field + clean + __str__**

In `models_rischi.py`, in cima (dopo `from django.db import models`):

```python
from django.core.exceptions import ValidationError
```

In `EsposizioneRischio`, dopo il campo `area = ...`:

```python
    legacy_anagrafica_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="Esposizione assegnata direttamente a un singolo dipendente (1.9).",
    )
```

Aggiungere in `Meta.indexes` (in coda alla lista):

```python
            models.Index(fields=["legacy_anagrafica_id", "is_active"]),
```

Aggiungere il metodo `clean` e sostituire `__str__`:

```python
    def clean(self):
        if not (self.mansione_id or self.area_id or self.legacy_anagrafica_id):
            raise ValidationError(
                "Specificare almeno un target: mansione, area o dipendente."
            )

    def __str__(self) -> str:
        if self.mansione_id:
            target = self.mansione
        elif self.area_id:
            target = self.area
        elif self.legacy_anagrafica_id:
            target = f"dip #{self.legacy_anagrafica_id}"
        else:
            target = "—"
        return f"{target} → {self.fattore.codice}"
```

- [ ] **Step 4: Generate migration**

Run: `& "C:/Dev/Portale Novicrom/.venv/Scripts/python.exe" "C:/Dev/pn-epica-a1/django_app/manage.py" makemigrations anagrafica --settings=config.settings.test_fast`
Expected: crea `anagrafica/migrations/00XX_esposizionerischio_legacy_anagrafica_id.py` (AddField + AddIndex). Verificare che sia additiva (nessun `RunPython` distruttivo).

- [ ] **Step 5: Run test to verify it passes**

Run: stesso comando dello Step 2.
Expected: PASS (3 test).

- [ ] **Step 6: Update admin**

In `admin.py`, `EsposizioneRischioAdmin`:

```python
    list_display = ("fattore", "mansione", "area", "legacy_anagrafica_id", "is_active", "created_at")
    list_filter = ("is_active", "fattore__categoria")
    search_fields = ("fattore__codice", "fattore__nome", "mansione__nome", "area__nome", "legacy_anagrafica_id")
    autocomplete_fields = ("fattore",)
    raw_id_fields = ("mansione", "area")
    readonly_fields = ("created_at",)
```

- [ ] **Step 7: Check + commit**

Run: `& "C:/Dev/Portale Novicrom/.venv/Scripts/python.exe" "C:/Dev/pn-epica-a1/django_app/manage.py" check --settings=config.settings.test`
Expected: `System check identified no issues`.

Aggiornare `django_app/CHANGELOG.md` (sotto `## [Unreleased]`, nuovo blocco):
```
### Epica A / A1 — mansione di rischio: modello + resolver
- **[feat/test] `anagrafica/models_rischi.py`, `anagrafica/admin.py`, `anagrafica/migrations/…`, `anagrafica/tests_mansione_rischio_a1.py`**: (1.9) `EsposizioneRischio` può ora puntare anche a un singolo dipendente (`legacy_anagrafica_id`), oltre a mansione/area; `clean()` esige almeno un target. Migrazione additiva.
```

```bash
git add django_app/anagrafica/models_rischi.py django_app/anagrafica/admin.py django_app/anagrafica/migrations/ django_app/anagrafica/tests_mansione_rischio_a1.py django_app/CHANGELOG.md
git commit -m "feat(anagrafica): EsposizioneRischio con target dipendente (A1, 1.9)"
```

---

### Task 2: Resolver — `requisiti_dipendente()`

**Files:**
- Modify: `django_app/anagrafica/services/mansionario.py` (helper `_requisiti_da_fattori`, `_corsi_per_categoria`; refactor `_resolve`/`_supplementi` per riuso; nuova `requisiti_dipendente`)
- Test: `django_app/anagrafica/tests_mansione_rischio_a1.py` (append)

**Interfaces:**
- Consumes: `EsposizioneRischio.legacy_anagrafica_id` (Task 1); `requisiti_per_nome_mansione(nome)`, `_dedup`, `requisiti_vuoti` (esistenti).
- Produces: `requisiti_dipendente(legacy_id: int, *, mansione_nome: str|None=None, area_id: int|None=None) -> dict[str, list]` con chiavi `{dpi, visite, corsi, piani, fattori}`.

- [ ] **Step 1: Write the failing tests**

Append a `tests_mansione_rischio_a1.py`:

```python
from datetime import date

from .models import AreaAziendale, DipendenteAnagraficaAziendale, Mansione, TipoVisitaMedica
from .models_rischi import CategoriaCorso, EsposizioneRischio, FattoreRischio
from .services.mansionario import requisiti_dipendente


class RequisitiDipendenteTests(TestCase):
    def setUp(self):
        from dpi.models import CategoriaDPI
        self.dpi_guanti = CategoriaDPI.objects.create(nome="Guanti")
        self.dpi_cuffie = CategoriaDPI.objects.create(nome="Cuffie")
        self.visita_audio = TipoVisitaMedica.objects.create(nome="Audiometria", durata_mesi=24)

        self.f_rumore = FattoreRischio.objects.create(codice="RUM", nome="Rumore")
        self.f_rumore.categorie_dpi.add(self.dpi_cuffie)
        self.f_rumore.tipi_visita.add(self.visita_audio)

        self.f_chimico = FattoreRischio.objects.create(codice="CHI", nome="Chimico")
        self.f_chimico.categorie_dpi.add(self.dpi_guanti)

        # Mansione lavorativa "Verniciatore" esposta al chimico
        self.mansione = Mansione.objects.create(nome="Verniciatore-A1")
        EsposizioneRischio.objects.create(fattore=self.f_chimico, mansione=self.mansione)

    def test_eredita_dalla_mansione(self):
        req = requisiti_dipendente(700, mansione_nome="Verniciatore-A1")
        self.assertIn(self.dpi_guanti, req["dpi"])

    def test_esposizione_diretta_aggiunge_fattore(self):
        EsposizioneRischio.objects.create(fattore=self.f_rumore, legacy_anagrafica_id=700)
        req = requisiti_dipendente(700, mansione_nome="Verniciatore-A1")
        self.assertIn(self.dpi_cuffie, req["dpi"])
        self.assertIn(self.visita_audio, req["visite"])

    def test_esposizione_di_area_aggiunge_fattore(self):
        area = AreaAziendale.objects.create(nome="IN1-A1")
        EsposizioneRischio.objects.create(fattore=self.f_rumore, area=area)
        req = requisiti_dipendente(701, mansione_nome="Verniciatore-A1", area_id=area.id)
        self.assertIn(self.dpi_cuffie, req["dpi"])

    def test_dedup_tra_fonti(self):
        # Stesso DPI dal chimico via mansione E via esposizione diretta.
        EsposizioneRischio.objects.create(fattore=self.f_chimico, legacy_anagrafica_id=700)
        req = requisiti_dipendente(700, mansione_nome="Verniciatore-A1")
        self.assertEqual([d for d in req["dpi"] if d == self.dpi_guanti], [self.dpi_guanti])

    def test_dipendente_nudo_requisiti_vuoti(self):
        req = requisiti_dipendente(999, mansione_nome="Inesistente", area_id=None)
        self.assertEqual(req, {"dpi": [], "visite": [], "corsi": [], "piani": [], "fattori": []})

    def test_area_risolta_da_db_se_non_passata(self):
        area = AreaAziendale.objects.create(nome="IN2-A1")
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=702, area_aziendale=area)
        EsposizioneRischio.objects.create(fattore=self.f_rumore, area=area)
        req = requisiti_dipendente(702, mansione_nome="")
        self.assertIn(self.dpi_cuffie, req["dpi"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "C:/Dev/Portale Novicrom/.venv/Scripts/python.exe" "C:/Dev/pn-epica-a1/django_app/manage.py" test anagrafica.tests_mansione_rischio_a1.RequisitiDipendenteTests --settings=config.settings.test_fast --keepdb`
Expected: FAIL — `ImportError`/`AttributeError` su `requisiti_dipendente` (non esiste).

- [ ] **Step 3: Refactor helper + implement resolver**

In `services/mansionario.py`:

(a) Aggiungere un helper condiviso fattori→requisiti (subito dopo `_dedup`):

```python
def _corsi_per_categoria(categoria_ids: set[int]) -> dict[int, list[TrainingCourse]]:
    out: dict[int, list[TrainingCourse]] = {}
    if categoria_ids:
        for corso in (
            TrainingCourse.objects
            .filter(categoria_id__in=categoria_ids, is_active=True)
            .select_related("piano")
        ):
            out.setdefault(corso.categoria_id, []).append(corso)
    return out


def _requisiti_da_fattori(fattori, corsi_per_categoria) -> dict[str, list]:
    """DPI/visite/corsi/fattori derivati da una lista di FattoreRischio attivi."""
    dpi, visite, corsi, out_fattori = [], [], [], []
    for fattore in fattori:
        if fattore is None or not fattore.is_active:
            continue
        out_fattori.append(fattore)
        visite.extend(fattore.tipi_visita.all())
        try:
            dpi.extend(fattore.categorie_dpi.all())
        except Exception:
            pass
        for categoria in fattore.categorie_corso.all():
            corsi.extend(corsi_per_categoria.get(categoria.pk, []))
    return {"dpi": dpi, "visite": visite, "corsi": corsi, "fattori": out_fattori}
```

(b) In `_resolve`, sostituire il blocco `# 2) requisiti ereditati dai fattori...` (il `for esp in mansione.esposizioni_rischio.all(): ...`) con:

```python
        # 2) requisiti ereditati dai fattori di rischio esposti (helper condiviso)
        fattori_esposti = [
            esp.fattore for esp in mansione.esposizioni_rischio.all()
            if esp.is_active and esp.fattore and esp.fattore.is_active
        ]
        parziale = _requisiti_da_fattori(fattori_esposti, corsi_per_categoria)
        dpi.extend(parziale["dpi"])
        visite.extend(parziale["visite"])
        corsi.extend(parziale["corsi"])
        fattori.extend(parziale["fattori"])
```

(c) Aggiungere in fondo al file:

```python
def requisiti_dipendente(
    legacy_id: int, *, mansione_nome: str | None = None, area_id: int | None = None
) -> dict[str, list]:
    """Requisiti effettivi di un dipendente: unione di (1) mansione lavorativa,
    (2) esposizioni di area, (3) esposizioni dirette al dipendente. Dedup fra fonti.

    ``mansione_nome`` / ``area_id`` opzionali: se assenti sono risolti dal DB
    (``DipendenteAnagraficaAziendale`` per l'area; riga legacy anagrafica per la
    mansione). Passarli evita il fetch quando il chiamante li ha già.
    """
    from ..models_rischi import EsposizioneRischio

    # Risoluzione DB dei parametri mancanti.
    if area_id is None or mansione_nome is None:
        from ..models import DipendenteAnagraficaAziendale
        az = DipendenteAnagraficaAziendale.objects.filter(
            legacy_anagrafica_id=legacy_id
        ).first()
        if area_id is None and az is not None:
            area_id = az.area_aziendale_id
        if mansione_nome is None:
            mansione_nome = _mansione_nome_legacy(legacy_id)

    # Fonte 1: mansione lavorativa (resolver esistente).
    base = (
        requisiti_per_nome_mansione(mansione_nome) if mansione_nome else requisiti_vuoti()
    )

    # Fonti 2+3: esposizioni di area + dirette al dipendente.
    esposizioni = EsposizioneRischio.objects.filter(is_active=True).select_related(
        "fattore"
    ).prefetch_related(
        "fattore__tipi_visita", "fattore__categorie_dpi", "fattore__categorie_corso"
    )
    q_area = esposizioni.filter(area_id=area_id) if area_id else esposizioni.none()
    q_dir = esposizioni.filter(legacy_anagrafica_id=legacy_id)
    fattori = [e.fattore for e in list(q_area) + list(q_dir)]

    categoria_ids = {
        c.pk for f in fattori if f and f.is_active for c in f.categorie_corso.all()
    }
    extra = _requisiti_da_fattori(fattori, _corsi_per_categoria(categoria_ids))

    return {
        "dpi": _dedup(base["dpi"] + extra["dpi"]),
        "visite": _dedup(base["visite"] + extra["visite"]),
        "corsi": _dedup(base["corsi"] + extra["corsi"]),
        "piani": _dedup(base["piani"]),
        "fattori": _dedup(base["fattori"] + extra["fattori"]),
    }


def _mansione_nome_legacy(legacy_id: int) -> str:
    """Nome mansione dalla riga legacy anagrafica (stringa `mansione`)."""
    try:
        from core.legacy_anagrafica import fetch_anagrafica_rows
        for row in fetch_anagrafica_rows(deduplicate=True):
            if int(row.get("id") or 0) == int(legacy_id):
                return str(row.get("mansione") or "").strip()
    except Exception:
        pass
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: comando dello Step 2 + anche `EsposizioneRischioTargetTests` (regressione Task 1) e i test esistenti del resolver:
`... test anagrafica.tests_mansione_rischio_a1 --settings=config.settings.test_fast --keepdb`
Expected: PASS (tutti). Poi girare i test mansionario esistenti: `... test anagrafica.tests --settings=config.settings.test_fast --keepdb` → nessuna regressione su `requisiti_mansione`/`requisiti_per_nome`.

- [ ] **Step 5: Commit**

Aggiornare `CHANGELOG.md` (stesso blocco A1, aggiungere la riga resolver):
```
- **[feat/test] `anagrafica/services/mansionario.py`**: nuova `requisiti_dipendente(legacy_id)` — unione requisiti mansione + esposizioni di area + dirette al dipendente (fonte unica per A2/A3). Refactor DRY del derivatore fattori→requisiti.
```

```bash
git add django_app/anagrafica/services/mansionario.py django_app/anagrafica/tests_mansione_rischio_a1.py django_app/CHANGELOG.md
git commit -m "feat(anagrafica): resolver requisiti_dipendente (A1, 1.9/2.1 foundation)"
```

---

## Self-Review

- **Spec coverage:** modello (Task 1) ✓; resolver con 3 fonti + dedup + fallback DB (Task 2) ✓; test modello+resolver ✓; nota cessati (nessun filtro nel resolver) ✓; migrazione additiva ✓; no UI ✓.
- **Placeholder scan:** nessun TBD; codice completo in ogni step.
- **Type consistency:** `requisiti_dipendente(legacy_id, *, mansione_nome, area_id)` e chiavi `{dpi,visite,corsi,piani,fattori}` coerenti fra spec, test e implementazione; `_requisiti_da_fattori`/`_corsi_per_categoria` usati sia da `_resolve` sia dal nuovo resolver.
