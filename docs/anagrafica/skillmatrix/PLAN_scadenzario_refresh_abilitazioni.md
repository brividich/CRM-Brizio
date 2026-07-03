# Scadenzario abilitazioni macchina + avvio refresh HR→CAR — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere il refresh semestrale delle abilitazioni macchina (MOD.187) gestibile come una scadenza, con uno scadenzario per reparto dentro Skill Matrix da cui HR "dà il via" al refresh e il CAR viene avvisato (in-portale + email).

**Architecture:** Strato **additivo** su `anagrafica`. Riusa `AbilitazioneMacchina.prossima_revisione` (scadenza già esistente) e `CampagnaRefresh` (trigger). Nuove funzioni pure in `services/skillmatrix_refresh.py`, una view/pagina scadenzario, un binding ACL, una voce subnav, e una sezione "Cose da gestire" in `dashboard` che chiama un helper read-only di `anagrafica`. Skill Matrix resta read-only verso gli altri moduli.

**Tech Stack:** Django 5.2, Python 3.11+, template SSR HUB (`hr-shell`/`hr-pagehead`), test `django.test.TestCase` su SQLite.

## Global Constraints

- **SQL-Server-safe**: nessun indice parziale, nessun `UniqueConstraint` con `condition`, nessun campo `unique` nullable.
- **Dipendente sempre via `legacy_anagrafica_id`** (IntegerField), nessuna FK al modello dipendente.
- **`email` = login legacy** → per le notifiche usare **`email_notifica`** (`core.legacy_models.AnagraficaDipendente`).
- **Handoff fail-safe**: un errore di notifica/email **non** annulla l'apertura della campagna.
- **HR dà il via manualmente**: nessuno scheduler automatico.
- **Guardia permesso**: `from .acl_bootstrap import PERM_SKM_MANAGE` + `_check_skm_permission(request, PERM_SKM_MANAGE)`.
- **Ambiente comandi**: PowerShell; test con `--settings=config.settings.test --keepdb`.
- **MANDATORY**: a fine lavoro aggiornare `CHANGELOG.md` (e `README.md` per funzionalità visibile) — Task 9.
- Numeri migration liberi: **0075** (campo config), **0076** (subnav). Ultima esistente = `0074`.

## File Structure

Modificati:
- `django_app/anagrafica/models_skillmatrix.py` — nuovo campo `preavviso_refresh_giorni` su `SkillMatrixConfig`.
- `django_app/anagrafica/forms.py` — campo nel `SkillMatrixConfigForm`.
- `django_app/anagrafica/templates/anagrafica/pages/skill_matrix_impostazioni.html` — render campo.
- `django_app/anagrafica/services/skillmatrix_refresh.py` — `scadenzario_reparti`, `avvia_refresh`, `campagne_da_gestire`, `_risolvi_car`, `_notifica_car`, refactor `apri_campagna`.
- `django_app/anagrafica/views.py` — view `skm_scadenzario`.
- `django_app/anagrafica/urls.py` — route.
- `django_app/anagrafica/acl_bootstrap.py` — binding route + bump cache key.
- `django_app/dashboard/views_mie_attivita.py` — `_my_skm_refresh` + sezione.
- `CHANGELOG.md`, `README.md`, `docs/skill-matrix/BUILD_LOG.md`.

Creati:
- `django_app/anagrafica/migrations/0075_skillmatrixconfig_preavviso_refresh_giorni.py` (auto).
- `django_app/anagrafica/migrations/0076_subnav_skill_matrix_scadenzario.py` (manuale).
- `django_app/anagrafica/templates/anagrafica/pages/skm_scadenzario.html`.
- `django_app/anagrafica/tests_skillmatrix_scadenzario.py`.

---

### Task 1: Campo config `preavviso_refresh_giorni` (modello + migration + form + Impostazioni)

**Files:**
- Modify: `django_app/anagrafica/models_skillmatrix.py` (classe `SkillMatrixConfig`, dopo `periodicita_refresh_mesi`)
- Modify: `django_app/anagrafica/forms.py` (`SkillMatrixConfigForm.Meta.fields` + `widgets`)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/skill_matrix_impostazioni.html` (card "Continuità & refresh")
- Create: `django_app/anagrafica/migrations/0075_skillmatrixconfig_preavviso_refresh_giorni.py` (via makemigrations)
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Produces: `SkillMatrixConfig.preavviso_refresh_giorni: int` (default 60), esposto nel form e nella pagina Impostazioni.

- [ ] **Step 1: Write the failing test**

Crea `django_app/anagrafica/tests_skillmatrix_scadenzario.py`:

```python
"""F10 — scadenzario abilitazioni macchina + avvio refresh HR->CAR."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import (
    AbilitazioneMacchina, CampagnaRefresh, CompetenzaSkm, LivelloSkm,
    Reparto, SkillMatrixConfig, SubnavLinkAnagrafica,
)

User = get_user_model()
OGGI = date(2026, 7, 3)


class ConfigPreavvisoTests(TestCase):
    def test_default_preavviso_refresh_giorni(self):
        cfg = SkillMatrixConfig.get_instance()
        self.assertEqual(cfg.preavviso_refresh_giorni, 60)

    def test_form_salva_preavviso(self):
        from .forms import SkillMatrixConfigForm
        cfg = SkillMatrixConfig.get_instance()
        data = {
            "soglia_operativa": "U", "regola_multivoce": "MIN", "soglia_uomo_solo": 2,
            "finestra_continuita_mesi": 12, "preavviso_continuita_mesi": 9,
            "periodicita_refresh_mesi": 6, "preavviso_refresh_giorni": 45,
            "etichetta_i": "I", "etichetta_l": "L", "etichetta_u": "U", "etichetta_o": "O",
        }
        form = SkillMatrixConfigForm(data, instance=cfg)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        cfg.refresh_from_db()
        self.assertEqual(cfg.preavviso_refresh_giorni, 45)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ConfigPreavvisoTests --settings=config.settings.test`
Expected: FAIL (`AttributeError`/campo mancante o migration assente).

- [ ] **Step 3: Add the model field**

In `models_skillmatrix.py`, dentro `SkillMatrixConfig`, subito dopo `periodicita_refresh_mesi = ...`:

```python
    preavviso_refresh_giorni = models.PositiveSmallIntegerField(
        default=60,
        help_text="Giorni prima di prossima_revisione entro cui un reparto è "
                  "«in arrivo» nello scadenzario abilitazioni.",
    )
```

- [ ] **Step 4: Add to the form**

In `forms.py`, `SkillMatrixConfigForm.Meta.fields`, aggiungi `"preavviso_refresh_giorni"` subito dopo `"periodicita_refresh_mesi"`. In `widgets` aggiungi:

```python
            "preavviso_refresh_giorni": forms.NumberInput(attrs={"class": "ana-input", "min": 0}),
```

- [ ] **Step 5: Render in Impostazioni template**

In `skill_matrix_impostazioni.html`, nella card "Continuità & refresh", subito dopo il blocco `periodicita_refresh_mesi`:

```html
        <div class="skc-field">
          <label for="{{ form.preavviso_refresh_giorni.id_for_label }}">Preavviso refresh (giorni)</label>
          {{ form.preavviso_refresh_giorni }}
          {{ form.preavviso_refresh_giorni.errors }}
        </div>
```

- [ ] **Step 6: Generate the migration**

Run: `python django_app\manage.py makemigrations anagrafica --settings=config.settings.test`
Expected: crea `0075_skillmatrixconfig_preavviso_refresh_giorni.py` con `AddField`.
Verifica: `python django_app\manage.py makemigrations anagrafica --check --settings=config.settings.test` → `No changes detected`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ConfigPreavvisoTests --settings=config.settings.test`
Expected: PASS (2 test).

- [ ] **Step 8: Commit**

```powershell
git add django_app/anagrafica/models_skillmatrix.py django_app/anagrafica/forms.py `
  django_app/anagrafica/templates/anagrafica/pages/skill_matrix_impostazioni.html `
  django_app/anagrafica/migrations/0075_skillmatrixconfig_preavviso_refresh_giorni.py `
  django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(skill-matrix): campo config preavviso_refresh_giorni (F10)"
```

---

### Task 2: Servizio — `scadenzario_reparti`

**Files:**
- Modify: `django_app/anagrafica/services/skillmatrix_refresh.py` (import + nuova funzione)
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Consumes: `SkillMatrixConfig.preavviso_refresh_giorni` (Task 1).
- Produces: `scadenzario_reparti(oggi=None, config=None) -> list[dict]` con chiavi
  `reparto, prossima_revisione, n_totali, n_scadute, n_in_arrivo, stato
  ('scaduto'|'in_arrivo'|'ok'), campagna_aperta, campagna_id, campagna_periodo_inizio`.
  Ordinamento: scadute→in_arrivo→ok, poi `-n_scadute`, poi `prossima_revisione` asc, poi reparto.

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests_skillmatrix_scadenzario.py`:

```python
class ScadenzarioRepartiTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.R = R
        self.a1 = Asset.objects.create(asset_tag="CNC-A-1", name="Alfa", asset_type="CNC", reparto="Officina")
        self.a2 = Asset.objects.create(asset_tag="CNC-B-1", name="Beta", asset_type="CNC", reparto="Montaggio")
        CompetenzaSkm.objects.create(competenza_key="A1", display="A1", tipo="macchina", asset=self.a1)
        CompetenzaSkm.objects.create(competenza_key="B1", display="B1", tipo="macchina", asset=self.a2)

    def test_reparto_scaduto_in_arrivo_ok(self):
        # Officina: una revisione scaduta -> stato scaduto
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.a1, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI - timedelta(days=5))
        # Montaggio: revisione tra 10 giorni, preavviso default 60 -> in_arrivo
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=2, asset=self.a2, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI + timedelta(days=10))
        rows = self.R.scadenzario_reparti(oggi=OGGI)
        by = {r["reparto"]: r for r in rows}
        self.assertEqual(by["Officina"]["stato"], "scaduto")
        self.assertEqual(by["Officina"]["n_scadute"], 1)
        self.assertEqual(by["Montaggio"]["stato"], "in_arrivo")
        self.assertEqual(by["Montaggio"]["n_in_arrivo"], 1)
        # ordinamento: scaduto prima di in_arrivo
        self.assertEqual(rows[0]["reparto"], "Officina")

    def test_reparto_ok_e_non_in_lista_escluso(self):
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=3, asset=self.a1, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI + timedelta(days=200))
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=4, asset=self.a2, livello=LivelloSkm.AUTONOMO,
            in_lista=False, prossima_revisione=OGGI - timedelta(days=5))
        by = {r["reparto"]: r for r in self.R.scadenzario_reparti(oggi=OGGI)}
        self.assertEqual(by["Officina"]["stato"], "ok")
        # Montaggio ha solo un'abilitazione non in lista -> nessuna riga
        self.assertNotIn("Montaggio", by)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ScadenzarioRepartiTests --settings=config.settings.test --keepdb`
Expected: FAIL (`AttributeError: module ... has no attribute 'scadenzario_reparti'`).

- [ ] **Step 3: Update imports**

In `services/skillmatrix_refresh.py`, riga `from datetime import timedelta` →

```python
from datetime import date, timedelta
```

- [ ] **Step 4: Implement `scadenzario_reparti`**

Aggiungi in fondo a `services/skillmatrix_refresh.py`:

```python
def scadenzario_reparti(oggi=None, config: SkillMatrixConfig | None = None) -> list[dict]:
    """Stato del refresh per reparto (derivato da prossima_revisione, in_lista).

    Un dict per reparto con almeno un'abilitazione in lista su una macchina catalogata.
    Stati: 'scaduto' (>=1 revisione < oggi), 'in_arrivo' (min non-scaduta <= oggi+preavviso),
    'ok' altrimenti. Ordinati per urgenza.
    """
    oggi = oggi or timezone.localdate()
    config = config or SkillMatrixConfig.get_instance()
    soglia = oggi + timedelta(days=int(config.preavviso_refresh_giorni))

    reparto_per_asset = {}
    for c in (CompetenzaSkm.objects
              .filter(tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False)
              .select_related("asset")):
        rep = (c.asset.reparto or "").strip()
        if rep:
            reparto_per_asset[c.asset_id] = rep
    if not reparto_per_asset:
        return []

    agg: dict[str, dict] = {}
    for a in (AbilitazioneMacchina.objects
              .filter(in_lista=True, asset_id__in=list(reparto_per_asset.keys()))):
        rep = reparto_per_asset.get(a.asset_id)
        if not rep:
            continue
        d = agg.setdefault(rep, {"n_totali": 0, "n_scadute": 0, "n_in_arrivo": 0,
                                 "prossima_revisione": None})
        d["n_totali"] += 1
        pr = a.prossima_revisione
        if pr is not None and pr < oggi:
            d["n_scadute"] += 1
        elif pr is not None and pr <= soglia:
            d["n_in_arrivo"] += 1
        if pr is not None and (d["prossima_revisione"] is None or pr < d["prossima_revisione"]):
            d["prossima_revisione"] = pr

    aperte = {c.reparto: c for c in
              CampagnaRefresh.objects.filter(stato=CampagnaRefresh.STATO_APERTA)}

    out = []
    for rep, d in agg.items():
        stato = "scaduto" if d["n_scadute"] else ("in_arrivo" if d["n_in_arrivo"] else "ok")
        camp = aperte.get(rep)
        out.append({
            "reparto": rep,
            "prossima_revisione": d["prossima_revisione"],
            "n_totali": d["n_totali"],
            "n_scadute": d["n_scadute"],
            "n_in_arrivo": d["n_in_arrivo"],
            "stato": stato,
            "campagna_aperta": camp is not None,
            "campagna_id": camp.id if camp else None,
            "campagna_periodo_inizio": camp.periodo_inizio if camp else None,
        })

    rank = {"scaduto": 0, "in_arrivo": 1, "ok": 2}
    out.sort(key=lambda r: (rank[r["stato"]], -r["n_scadute"],
                            r["prossima_revisione"] or date.max, r["reparto"]))
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ScadenzarioRepartiTests --settings=config.settings.test --keepdb`
Expected: PASS (2 test).

- [ ] **Step 6: Commit**

```powershell
git add django_app/anagrafica/services/skillmatrix_refresh.py django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(skill-matrix): scadenzario_reparti (stato refresh per reparto)"
```

---

### Task 3: Servizio — `avvia_refresh` + risoluzione/notifica CAR

**Files:**
- Modify: `django_app/anagrafica/services/skillmatrix_refresh.py`
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Consumes: `abilitazioni_reparto(reparto)` (esistente), `core.notifiche.invia_notifica`, `core.email_utils.send_hub_mail`, `Reparto.caporeparto_legacy_id`, `AnagraficaDipendente.email_notifica`.
- Produces:
  - `apri_campagna(reparto, *, periodo_inizio=None, avviatore_ruolo="", scadenza=None) -> CampagnaRefresh` (retro-compatibile).
  - `avvia_refresh(*, reparto, avviatore_ruolo="", avviatore_legacy_id=None, oggi=None) -> tuple[CampagnaRefresh, bool]` — `(campagna, created)`; se `created` notifica il CAR (in-app + email best-effort).
  - `_risolvi_car(reparto) -> tuple[int | None, str]` — `(car_legacy_id, email_notifica)`.

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests_skillmatrix_scadenzario.py`:

```python
class AvviaRefreshTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.R = R
        self.asset = Asset.objects.create(asset_tag="CNC-C-1", name="Gamma", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="C1", display="C1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=99)

    def _notifiche_car(self):
        from core.models import Notifica
        return Notifica.objects.filter(legacy_user_id=99, tipo="skm_refresh")

    def test_avvia_apre_campagna_e_notifica_una_volta(self):
        camp, created = self.R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")
        self.assertTrue(created)
        self.assertEqual(camp.stato, CampagnaRefresh.STATO_APERTA)
        self.assertEqual(self._notifiche_car().count(), 1)
        # seconda chiamata idempotente: nessuna nuova campagna, nessuna nuova notifica
        camp2, created2 = self.R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")
        self.assertFalse(created2)
        self.assertEqual(camp2.id, camp.id)
        self.assertEqual(self._notifiche_car().count(), 1)

    def test_apri_campagna_retrocompatibile(self):
        c = self.R.apri_campagna("Officina")
        self.assertEqual(c.reparto, "Officina")

    def test_risolvi_car(self):
        car_id, email = self.R._risolvi_car("Officina")
        self.assertEqual(car_id, 99)  # email vuota in test (AnagraficaDipendente legacy assente): ok
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.AvviaRefreshTests --settings=config.settings.test --keepdb`
Expected: FAIL (`avvia_refresh` / `_risolvi_car` inesistenti).

- [ ] **Step 3: Update imports**

In `services/skillmatrix_refresh.py`, in cima aggiungi:

```python
import logging
from urllib.parse import urlencode

from django.urls import reverse

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Refactor `apri_campagna` + implement CAR helpers e `avvia_refresh`**

Sostituisci la funzione `apri_campagna` esistente con:

```python
def _get_or_crea_campagna(reparto: str, *, periodo_inizio=None, avviatore_ruolo: str = "",
                          scadenza=None) -> tuple[CampagnaRefresh, bool]:
    periodo_inizio = periodo_inizio or timezone.localdate()
    return CampagnaRefresh.objects.get_or_create(
        reparto=reparto, stato=CampagnaRefresh.STATO_APERTA,
        defaults={"periodo_inizio": periodo_inizio, "avviatore_ruolo": avviatore_ruolo,
                  "scadenza": scadenza},
    )


def apri_campagna(reparto: str, *, periodo_inizio=None, avviatore_ruolo: str = "",
                  scadenza=None) -> CampagnaRefresh:
    """Apre (o riusa) la campagna aperta del reparto. Idempotente."""
    camp, _ = _get_or_crea_campagna(reparto, periodo_inizio=periodo_inizio,
                                    avviatore_ruolo=avviatore_ruolo, scadenza=scadenza)
    return camp
```

Aggiungi in fondo al file:

```python
def _risolvi_car(reparto: str) -> tuple[int | None, str]:
    """(caporeparto_legacy_id, email_notifica) del CAR del reparto, o (None, "")."""
    from ..models import Reparto
    rep = Reparto.objects.filter(nome__iexact=(reparto or "").strip()).first()
    if not rep or not rep.caporeparto_legacy_id:
        return (None, "")
    car_id = int(rep.caporeparto_legacy_id)
    email = ""
    try:
        from core.legacy_models import AnagraficaDipendente
        email = (AnagraficaDipendente.objects
                 .filter(id=car_id).values_list("email_notifica", flat=True).first()) or ""
    except Exception:
        logger.debug("Email CAR non risolta per reparto=%s", reparto, exc_info=True)
    return (car_id, str(email).strip())


def _notifica_car(reparto: str) -> None:
    """In-app + email best-effort al CAR. Nessun errore propagato."""
    car_id, car_email = _risolvi_car(reparto)
    n_da = abilitazioni_reparto(reparto).count()
    url = reverse("anagrafica:skm_refresh") + "?" + urlencode({"reparto": reparto})
    if car_id:
        try:
            from core.notifiche import invia_notifica
            invia_notifica(
                car_id, "skm_refresh",
                f"Refresh abilitazioni macchina avviato per il reparto «{reparto}»: "
                f"{n_da} abilitazioni da rivalutare.", url)
        except Exception:
            logger.warning("Notifica in-app CAR fallita reparto=%s", reparto, exc_info=True)
    if car_email:
        try:
            from core.email_utils import send_hub_mail
            send_hub_mail(
                f"Refresh abilitazioni macchina — reparto {reparto}",
                f"È stato avviato il refresh semestrale delle abilitazioni macchina del "
                f"reparto «{reparto}».\n\nAbilitazioni da rivalutare: {n_da}.\n\n"
                f"Apri la pagina di rivalutazione dal portale NOVICROM HUB.",
                [car_email], email_type="Anagrafica HR",
                section_label="Refresh abilitazioni macchina", fail_silently=True)
        except Exception:
            logger.warning("Email CAR fallita reparto=%s", reparto, exc_info=True)


def avvia_refresh(*, reparto: str, avviatore_ruolo: str = "", avviatore_legacy_id=None,
                  oggi=None) -> tuple[CampagnaRefresh, bool]:
    """HR "dà il via": apre la campagna del reparto (idempotente) e, solo se appena
    creata, notifica il CAR. L'apertura non è mai annullata da un errore di notifica."""
    reparto = (reparto or "").strip()
    if not reparto:
        raise ValueError("reparto obbligatorio")
    camp, created = _get_or_crea_campagna(reparto, periodo_inizio=oggi,
                                          avviatore_ruolo=avviatore_ruolo)
    if created:
        _notifica_car(reparto)
    return camp, created
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.AvviaRefreshTests django_app.anagrafica.tests_skillmatrix_refresh --settings=config.settings.test --keepdb`
Expected: PASS (nuovi test + regressione refresh esistente verde, incluso `test_apri_campagna_idempotente`).

- [ ] **Step 6: Commit**

```powershell
git add django_app/anagrafica/services/skillmatrix_refresh.py django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(skill-matrix): avvia_refresh + notifica CAR (in-app + email best-effort)"
```

---

### Task 4: Servizio — `campagne_da_gestire`

**Files:**
- Modify: `django_app/anagrafica/services/skillmatrix_refresh.py`
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Produces: `campagne_da_gestire(car_legacy_id) -> list[dict]` con chiavi `reparto, campagna_id, n_da_rivalutare, url`. Solo campagne **aperte** dei reparti di cui `car_legacy_id` è caporeparto.

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests_skillmatrix_scadenzario.py`:

```python
class CampagneDaGestireTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.R = R
        self.asset = Asset.objects.create(asset_tag="CNC-D-1", name="Delta", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="D1", display="D1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=99)

    def test_solo_campagne_aperte_del_car(self):
        self.assertEqual(self.R.campagne_da_gestire(99), [])  # nessuna campagna aperta
        self.R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")
        items = self.R.campagne_da_gestire(99)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reparto"], "Officina")
        self.assertEqual(items[0]["n_da_rivalutare"], 1)
        # un altro CAR non vede nulla
        self.assertEqual(self.R.campagne_da_gestire(100), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.CampagneDaGestireTests --settings=config.settings.test --keepdb`
Expected: FAIL (`campagne_da_gestire` inesistente).

- [ ] **Step 3: Implement `campagne_da_gestire`**

Aggiungi in fondo a `services/skillmatrix_refresh.py`:

```python
def campagne_da_gestire(car_legacy_id) -> list[dict]:
    """Campagne di refresh APERTE dei reparti di cui il legacy_id è caporeparto (CAR).
    Read-only, per la home 'Cose da gestire'."""
    if not car_legacy_id:
        return []
    from ..models import Reparto
    reparti = list(Reparto.objects
                   .filter(caporeparto_legacy_id=int(car_legacy_id))
                   .values_list("nome", flat=True))
    if not reparti:
        return []
    out = []
    for c in CampagnaRefresh.objects.filter(stato=CampagnaRefresh.STATO_APERTA,
                                            reparto__in=reparti):
        out.append({
            "reparto": c.reparto,
            "campagna_id": c.id,
            "n_da_rivalutare": abilitazioni_reparto(c.reparto).count(),
            "url": reverse("anagrafica:skm_refresh") + "?" + urlencode({"reparto": c.reparto}),
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.CampagneDaGestireTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/services/skillmatrix_refresh.py django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(skill-matrix): campagne_da_gestire per la home Cose da gestire"
```

---

### Task 5: View + URL + template `skm_scadenzario`

**Files:**
- Modify: `django_app/anagrafica/views.py` (nuova view, vicino a `skm_refresh`)
- Modify: `django_app/anagrafica/urls.py` (route)
- Create: `django_app/anagrafica/templates/anagrafica/pages/skm_scadenzario.html`
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Consumes: `scadenzario_reparti`, `avvia_refresh` (Task 2-3); `PERM_SKM_MANAGE`, `_check_skm_permission`.
- Produces: route `anagrafica:skm_scadenzario` (`/anagrafica/skill-matrix/scadenzario/`).

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests_skillmatrix_scadenzario.py`:

```python
@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class ScadenzarioViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("scadm", "sc@example.com", "pass12345")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skm_scadenzario")
        self.asset = Asset.objects.create(asset_tag="CNC-E-1", name="Epsilon", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="E1", display="E1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI - timedelta(days=3))
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=99)

    def test_get_render(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Officina")

    def test_export_csv(self):
        resp = self.client.get(self.url, {"format": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn(b"Officina", resp.content)

    def test_post_avvia_apre_campagna(self):
        resp = self.client.post(self.url, {"azione": "avvia", "reparto": "Officina"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CampagnaRefresh.objects.filter(
            reparto="Officina", stato=CampagnaRefresh.STATO_APERTA).exists())

    def test_accesso_negato(self):
        self.client.logout()
        nobody = User.objects.create_user("nob10", "nob10@example.com", "pass12345")
        self.client.force_login(nobody)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ScadenzarioViewTests --settings=config.settings.test --keepdb`
Expected: FAIL (`NoReverseMatch: 'skm_scadenzario'`).

- [ ] **Step 3: Add the URL**

In `urls.py`, dopo la riga `skm_refresh`:

```python
    path("skill-matrix/scadenzario/", views.skm_scadenzario, name="skm_scadenzario"),
```

- [ ] **Step 4: Implement the view**

In `views.py`, subito dopo la view `skm_refresh` (prima di `skm_impostazioni`), aggiungi:

```python
@login_required
def skm_scadenzario(request):
    """Scadenzario abilitazioni macchina per reparto (MOD.187).

    Mostra, per reparto, la prossima revisione, gli arretrati (non bloccanti) e lo
    stato campagna. HR "dà il via" al refresh (apre la campagna e avvisa il CAR: in-app
    + email); il merito della rivalutazione resta al CAR (pagina Refresh).
    Accesso: ``anagrafica.skillmatrix.manage``.
    """
    from .acl_bootstrap import PERM_SKM_MANAGE
    if not _check_skm_permission(request, PERM_SKM_MANAGE):
        messages.error(request, "Non hai i permessi per lo scadenzario Skill Matrix.")
        return redirect("anagrafica:index")

    from django.utils import timezone
    from .services import skillmatrix_refresh as refresh

    if request.method == "POST" and request.POST.get("azione") == "avvia":
        reparto = (request.POST.get("reparto") or "").strip()
        if reparto:
            legacy_user = get_legacy_user(request.user)
            _, created = refresh.avvia_refresh(
                reparto=reparto, avviatore_ruolo="HR",
                avviatore_legacy_id=int(legacy_user.id) if legacy_user else None)
            if created:
                messages.success(request, f"Refresh avviato per «{reparto}»: il CAR è stato avvisato.")
            else:
                messages.info(request, f"Il reparto «{reparto}» ha già una campagna di refresh aperta.")
        return redirect("anagrafica:skm_scadenzario")

    oggi = timezone.localdate()
    tutte = refresh.scadenzario_reparti(oggi=oggi)
    kpi = {
        "reparti_scaduti": sum(1 for r in tutte if r["stato"] == "scaduto"),
        "abil_scadute": sum(r["n_scadute"] for r in tutte),
        "campagne_aperte": sum(1 for r in tutte if r["campagna_aperta"]),
    }

    filtro_stato = (request.GET.get("stato") or "").strip()
    righe = [r for r in tutte if r["stato"] == filtro_stato] if filtro_stato in ("scaduto", "in_arrivo") else tutte

    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        resp["Content-Disposition"] = 'attachment; filename="scadenzario_abilitazioni.csv"'
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Reparto", "Prossima revisione", "Totali", "Scadute", "In arrivo", "Stato", "Campagna aperta"])
        for r in righe:
            w.writerow([
                r["reparto"],
                r["prossima_revisione"].strftime("%d/%m/%Y") if r["prossima_revisione"] else "",
                r["n_totali"], r["n_scadute"], r["n_in_arrivo"], r["stato"],
                "Sì" if r["campagna_aperta"] else "No",
            ])
        return resp

    return render(request, "anagrafica/pages/skm_scadenzario.html", {
        "oggi": oggi, "righe": righe, "kpi": kpi, "filtro_stato": filtro_stato,
        "totale": len(righe),
    })
```

- [ ] **Step 5: Create the template**

Crea `django_app/anagrafica/templates/anagrafica/pages/skm_scadenzario.html`:

```html
{% extends "core/base.html" %}
{% load static %}

{% block title %}Scadenzario abilitazioni — Skill Matrix MOD.187{% endblock %}

{% block extra_head %}
{% include "anagrafica/components/_hr_restyle.html" %}
{% include "anagrafica/components/_fm_style.html" %}
<style>
.sc-toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:6px 0 16px; }
.sc-kpis { display:flex; flex-wrap:wrap; gap:10px; margin:0 0 16px; }
.sc-chip { border:1px solid #e2e8f0; border-radius:999px; padding:6px 12px; font-size:12.5px; font-weight:700; color:#475569; background:#fff; }
.sc-chip b { color:#0c2545; }
.sc-chip.warn { border-color:#fcd34d; background:#fef9c3; color:#854d0e; }
.sc-chip.bad { border-color:#fca5a5; background:#fee2e2; color:#991b1b; }
.sc-table { border-collapse:collapse; width:100%; font-size:13px; }
.sc-table th, .sc-table td { border-bottom:1px solid #eef2f7; padding:7px 9px; text-align:left; vertical-align:middle; }
.sc-table thead th { background:#0c2545; color:#fff; font-size:11px; text-transform:uppercase; letter-spacing:.03em; }
.sc-table tbody tr:hover { background:#f8fafc; }
.sc-badge { display:inline-block; font-size:10.5px; font-weight:800; border-radius:5px; padding:2px 7px; }
.sc-badge.scaduto { color:#991b1b; background:#fee2e2; }
.sc-badge.in_arrivo { color:#854d0e; background:#fef9c3; }
.sc-badge.ok { color:#166534; background:#dcfce7; }
.sc-empty { text-align:center; padding:40px 16px; color:#475569; }
</style>
{% endblock %}

{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}

{% block content %}
<div class="hr-shell">

  <div class="hr-pagehead">
    <div>
      <div class="hr-pagehead-eyebrow">
        <a href="{% url 'anagrafica:index' %}" class="fm-crumb">Anagrafica</a>
        <span class="fm-crumb-sep">›</span> Skill Matrix MOD.187
      </div>
      <h2 class="hr-pagehead-title">📅 Scadenzario abilitazioni macchina</h2>
      <p class="hr-pagehead-desc">Prossime revisioni per reparto. HR avvia il refresh (il CAR viene avvisato); la rivalutazione resta al CAR.</p>
    </div>
    <a href="{% url 'anagrafica:skill_matrix_macchina' %}" class="hr-btn hr-btn-outline">↩ Torna alla matrice</a>
  </div>

  <div class="sc-kpis">
    <span class="sc-chip {% if kpi.reparti_scaduti %}bad{% endif %}">Reparti con arretrati <b>{{ kpi.reparti_scaduti }}</b></span>
    <span class="sc-chip {% if kpi.abil_scadute %}warn{% endif %}">Abilitazioni scadute <b>{{ kpi.abil_scadute }}</b></span>
    <span class="sc-chip">Campagne aperte <b>{{ kpi.campagne_aperte }}</b></span>
  </div>

  <form method="get" class="sc-toolbar">
    <label style="font-size:12px;color:#64748b;font-weight:700;">Stato</label>
    <select name="stato" onchange="this.form.submit()">
      <option value="" {% if not filtro_stato %}selected{% endif %}>Tutti</option>
      <option value="scaduto" {% if filtro_stato == 'scaduto' %}selected{% endif %}>Scaduti</option>
      <option value="in_arrivo" {% if filtro_stato == 'in_arrivo' %}selected{% endif %}>In arrivo</option>
    </select>
    <a class="hr-btn hr-btn-outline" href="?{% if filtro_stato %}stato={{ filtro_stato }}&amp;{% endif %}format=csv">⬇ CSV</a>
  </form>

  {% if righe %}
  <table class="sc-table">
    <thead>
      <tr><th>Reparto</th><th>Prossima revisione</th><th>In lista</th><th>Scadute</th><th>In arrivo</th><th>Stato</th><th>Campagna</th><th></th></tr>
    </thead>
    <tbody>
      {% for r in righe %}
      <tr>
        <td><a href="{% url 'anagrafica:skm_refresh' %}?reparto={{ r.reparto|urlencode }}">{{ r.reparto }}</a></td>
        <td>{{ r.prossima_revisione|date:"d/m/Y"|default:"—" }}</td>
        <td>{{ r.n_totali }}</td>
        <td>{{ r.n_scadute }}</td>
        <td>{{ r.n_in_arrivo }}</td>
        <td><span class="sc-badge {{ r.stato }}">{{ r.stato }}</span></td>
        <td>{% if r.campagna_aperta %}aperta dal {{ r.campagna_periodo_inizio|date:"d/m/Y" }}{% else %}—{% endif %}</td>
        <td>
          {% if not r.campagna_aperta %}
          <form method="post" style="margin:0;">
            {% csrf_token %}
            <input type="hidden" name="azione" value="avvia">
            <input type="hidden" name="reparto" value="{{ r.reparto }}">
            <button type="submit" class="hr-btn hr-btn-primary" style="padding:4px 10px;font-size:12px;">▶ Avvia refresh</button>
          </form>
          {% else %}
          <a class="hr-btn hr-btn-outline" style="padding:4px 10px;font-size:12px;" href="{% url 'anagrafica:skm_refresh' %}?reparto={{ r.reparto|urlencode }}">Rivaluta</a>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
    <div class="sc-empty">Nessun reparto da mostrare (la baseline abilitazioni non è ancora stata importata, oppure non ci sono scadenze per il filtro scelto).</div>
  {% endif %}

</div>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ScadenzarioViewTests --settings=config.settings.test --keepdb`
Expected: PASS (4 test).

- [ ] **Step 7: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/urls.py `
  django_app/anagrafica/templates/anagrafica/pages/skm_scadenzario.html `
  django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(skill-matrix): view+pagina scadenzario abilitazioni con avvio refresh HR"
```

---

### Task 6: Binding ACL della route

**Files:**
- Modify: `django_app/anagrafica/acl_bootstrap.py`
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Produces: `RoutePermissionBinding` per `anagrafica:skm_scadenzario` → `PERM_SKM_MANAGE`. Senza questo binding, in `ACL_STRICT_CANONICAL` la route sarebbe solo-superuser (vedi nota `acl_middleware_api_gate_paths`).

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests_skillmatrix_scadenzario.py`:

```python
class AclBindingTests(TestCase):
    def test_binding_scadenzario_manage(self):
        from .acl_bootstrap import _bootstrap_skillmatrix_canonical, PERM_SKM_MANAGE
        from core.models import RoutePermissionBinding
        _bootstrap_skillmatrix_canonical()
        b = RoutePermissionBinding.objects.filter(route_name="anagrafica:skm_scadenzario").first()
        self.assertIsNotNone(b)
        self.assertEqual(b.permission_id, PERM_SKM_MANAGE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.AclBindingTests --settings=config.settings.test --keepdb`
Expected: FAIL (`b is None`).

- [ ] **Step 3: Add the binding + bump cache key**

In `acl_bootstrap.py`:
- in `_SKM_ROUTE_BINDINGS`, aggiungi la riga:

```python
    "anagrafica:skm_scadenzario": PERM_SKM_MANAGE,
```

- aggiorna `_BOOTSTRAP_CACHE_KEY` da `"anagrafica_acl_bootstrap_v4"` a `"anagrafica_acl_bootstrap_v5"`, con commento:

```python
# Bump alla v5: aggiunge il binding route dello Scadenzario abilitazioni (F10)
# (anagrafica:skm_scadenzario → manage), così si ri-registra negli ambienti già a v4.
_BOOTSTRAP_CACHE_KEY = "anagrafica_acl_bootstrap_v5"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.AclBindingTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/acl_bootstrap.py django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(skill-matrix): binding ACL route skm_scadenzario -> manage (v5)"
```

---

### Task 7: Voce subnav "Scadenzario abilitazioni" (migration 0076)

**Files:**
- Create: `django_app/anagrafica/migrations/0076_subnav_skill_matrix_scadenzario.py`
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Produces: `SubnavLinkAnagrafica(url_value="anagrafica:skm_scadenzario", gruppo="Skill Matrix")`.

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests_skillmatrix_scadenzario.py`:

```python
class ScadenzarioNavTests(TestCase):
    def test_voce_menu_scadenzario(self):
        link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:skm_scadenzario").first()
        self.assertIsNotNone(link)
        self.assertEqual(link.gruppo, "Skill Matrix")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ScadenzarioNavTests --settings=config.settings.test`
Expected: FAIL (`link is None`).

- [ ] **Step 3: Create the migration**

Crea `django_app/anagrafica/migrations/0076_subnav_skill_matrix_scadenzario.py` (ricalca `0074`):

```python
from django.db import migrations

# Voce subnav "Scadenzario abilitazioni" nel gruppo Skill Matrix (pilastro Competenze).
# Stesso idioma di 0074: idempotente per url_value, voce non di sistema.

CATEGORIA = "Competenze"
GRUPPO = "Skill Matrix"
LINK = ("anagrafica:skm_scadenzario", "Scadenzario abilitazioni", 285)


def apply_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat = Cat.objects.filter(nome=CATEGORIA).order_by("id").first()
    if cat is None:
        cat = Cat.objects.create(nome=CATEGORIA, icona="🎓", ordine=200, is_active=True,
                                 landing_url_type="named",
                                 landing_url_value="anagrafica:formazione_dashboard")
    url_value, etichetta, ordine = LINK
    link = Link.objects.filter(url_value=url_value).order_by("id").first()
    if link is None:
        Link.objects.create(
            url_value=url_value, url_type="named", etichetta=etichetta,
            icona="", gruppo=GRUPPO, categoria=cat, ordine=ordine,
            active_view_names=url_value, is_active=True, is_sistema=False,
        )
    else:
        link.categoria = cat
        link.gruppo = GRUPPO
        link.etichetta = etichetta
        link.ordine = ordine
        link.is_active = True
        if not link.active_view_names:
            link.active_view_names = url_value
        link.save()


def reverse_subnav(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value=LINK[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0075_skillmatrixconfig_preavviso_refresh_giorni"),
    ]

    operations = [
        migrations.RunPython(apply_subnav, reverse_subnav),
    ]
```

> Nota: se il nome reale della migration di Task 1 differisse, allineare la dependency.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.ScadenzarioNavTests --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/migrations/0076_subnav_skill_matrix_scadenzario.py django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(skill-matrix): voce subnav Scadenzario abilitazioni (0076)"
```

---

### Task 8: Sezione "Cose da gestire" nel dashboard

**Files:**
- Modify: `django_app/dashboard/views_mie_attivita.py` (`_my_skm_refresh` + sezione in `build_cose_da_gestire`)
- Test: `django_app/anagrafica/tests_skillmatrix_scadenzario.py`

**Interfaces:**
- Consumes: `anagrafica.services.skillmatrix_refresh.campagne_da_gestire` (Task 4).
- Produces: `_my_skm_refresh(legacy_user_id) -> list[dict]` con item `{code, title, meta, status, url}`; sezione `key="skm_refresh"` in `build_cose_da_gestire`.

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests_skillmatrix_scadenzario.py`:

```python
class CoseDaGestireHelperTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.asset = Asset.objects.create(asset_tag="CNC-F-1", name="Zeta", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="F1", display="F1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=77)
        R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")

    def test_helper_mappa_item(self):
        from dashboard.views_mie_attivita import _my_skm_refresh
        items = _my_skm_refresh(77)
        self.assertEqual(len(items), 1)
        self.assertIn("Officina", items[0]["title"])
        self.assertIn("url", items[0])
        self.assertEqual(_my_skm_refresh(0), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.CoseDaGestireHelperTests --settings=config.settings.test --keepdb`
Expected: FAIL (`ImportError: cannot import name '_my_skm_refresh'`).

- [ ] **Step 3: Implement the helper**

In `dashboard/views_mie_attivita.py`, dopo `_my_elearning` (o accanto agli altri `_my_*`):

```python
def _my_skm_refresh(legacy_user_id) -> list[dict]:
    """Refresh abilitazioni macchina da gestire per il CAR (campagne aperte del suo reparto)."""
    if not legacy_user_id:
        return []
    try:
        from anagrafica.services.skillmatrix_refresh import campagne_da_gestire
        raw = campagne_da_gestire(legacy_user_id)
    except Exception:
        return []
    out = []
    for c in raw:
        out.append({
            "code": f"REP-{c['campagna_id']}",
            "title": f"Refresh reparto {c['reparto']}",
            "meta": f"{c['n_da_rivalutare']} abilitazioni da rivalutare",
            "status": "Da rivalutare",
            "url": c["url"],
        })
    return out
```

- [ ] **Step 4: Add the section**

In `build_cose_da_gestire`, dentro la lista `sections`, dopo il blocco `"key": "elearning"`:

```python
        {
            "key": "skm_refresh",
            "label": "Refresh abilitazioni macchina",
            "tone": "warning",
            "icon": "🔧",
            "items": _my_skm_refresh(legacy_user_id),
            "all_url": _safe_url("anagrafica:skm_scadenzario"),
            "empty": "Nessun refresh abilitazioni da gestire.",
        },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario.CoseDaGestireHelperTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add django_app/dashboard/views_mie_attivita.py django_app/anagrafica/tests_skillmatrix_scadenzario.py
git commit -m "feat(dashboard): sezione 'Refresh abilitazioni macchina' in Cose da gestire"
```

---

### Task 9: Suite completa + docs (BUILD_LOG, CHANGELOG, README)

**Files:**
- Modify: `docs/skill-matrix/BUILD_LOG.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/anagrafica/skillmatrix/SPEC_scadenzario_refresh_abilitazioni.md` (spunta stato, opzionale)

- [ ] **Step 1: Run the full skill-matrix suite + checks**

Run:
```
python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario django_app.anagrafica.tests_skillmatrix_refresh --settings=config.settings.test --keepdb
python django_app\manage.py makemigrations anagrafica --check --settings=config.settings.test
python django_app\manage.py check --settings=config.settings.test
```
Expected: tutti i test verdi; `No changes detected`; `0 issues`.

- [ ] **Step 2: Update BUILD_LOG**

In `docs/skill-matrix/BUILD_LOG.md`, aggiungi una sezione **F10** (dopo F9) che descrive: scadenzario per reparto, `avvia_refresh` con handoff CAR (in-app + email + Cose da gestire), campo config `preavviso_refresh_giorni`, binding ACL v5, subnav 0076; e aggiorna la lista "Stato fasi".

- [ ] **Step 3: Update CHANGELOG**

In `CHANGELOG.md`, sotto `[Unreleased]`, elenca i file toccati e la descrizione (nuovo scadenzario abilitazioni, avvio refresh HR→CAR con notifica+email, campo config, sezione Cose da gestire, ACL v5, subnav 0076).

- [ ] **Step 4: Update README**

In `README.md` (tabella catalogo moduli / sezione `anagrafica`), aggiungi la pagina **Scadenzario abilitazioni** (`/anagrafica/skill-matrix/scadenzario/`) tra le pagine Skill Matrix.

- [ ] **Step 5: Commit**

```powershell
git add docs/skill-matrix/BUILD_LOG.md CHANGELOG.md README.md docs/anagrafica/skillmatrix/SPEC_scadenzario_refresh_abilitazioni.md
git commit -m "docs(skill-matrix): F10 scadenzario abilitazioni + refresh HR->CAR (BUILD_LOG/CHANGELOG/README)"
```

---

## Self-Review

**Spec coverage** (spec §→task):
- §3 campo config → Task 1. §4 `scadenzario_reparti` → Task 2; `avvia_refresh`+CAR → Task 3; `campagne_da_gestire` → Task 4. §5 view/template/URL → Task 5. §6 Cose da gestire → Task 8. §7 ACL → Task 6; subnav → Task 7. §8 test → distribuiti + Task 9. §9 YAGNI → rispettato (nessun TrainingCourse/scheduler/continuità). §10 file → coperti. §11 deploy → note in Task 9/BUILD_LOG.

**Type/name consistency**: `scadenzario_reparti`, `avvia_refresh`, `campagne_da_gestire`, `_risolvi_car`, `_notifica_car`, `_my_skm_refresh`, `preavviso_refresh_giorni`, route `anagrafica:skm_scadenzario`, `PERM_SKM_MANAGE`, cache key `v5`, migration `0075`/`0076` — usati in modo coerente tra i task.

**Note operative**: i test usano SQLite (managed models); `AnagraficaDipendente` (legacy) può mancare in test → `_risolvi_car` è fail-safe e restituisce email vuota, per questo i test verificano la notifica in-app (via `Reparto.caporeparto_legacy_id`, managed) e non l'email.
