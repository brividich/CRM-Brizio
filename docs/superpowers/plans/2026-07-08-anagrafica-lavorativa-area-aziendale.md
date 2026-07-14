# Collegamento anagrafica lavorativa ↔ AreaAziendale (Fase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dare al dipendente una FK vera verso `AreaAziendale` (sostituendo il CharField morto `area_aziendale_nome`), esposta in UI con un picker a cascata Reparto→Area, mantenuta coerente da un'unica funzione di sincronizzazione, e ripristinare il match (oggi silenzioso e rotto) delle regole di formazione obbligatoria scoped per area.

**Architecture:** Migration additiva su `DipendenteAnagraficaAziendale` (rimuove `area_aziendale_nome`, aggiunge FK `area_aziendale`). `_sync_aziendale_from_reparto` diventa l'unico punto che scrive/valida l'invariante "l'area assegnata appartiene al reparto assegnato", richiamato sia dal mini-form rapido "Cambia reparto" sia dal form completo "Modifica dati aziendali". Il cascading Reparto→Area in UI è client-side (blob JSON + JS, nessuna chiamata server aggiuntiva). `training_eligibility.py` passa dal match testuale al match per ID.

**Tech Stack:** Django 5.2 ModelForm/FBV, template Django + JS vanilla (nessun framework), SQLite in test (`config.settings.test`).

## Global Constraints

- Non introdurre validazione bloccante lato form per la coerenza reparto↔area: la correzione è sempre silenziosa, centralizzata in `_sync_aziendale_from_reparto` (deciso con l'utente in fase di brainstorming).
- Non richiedere `is_active=True` sull'Area aziendale nella validazione di appartenenza al reparto: un'assegnazione a un'area nel frattempo disattivata resta valida (coerenza con `area`/`ruolo_aziendale`, che preservano il valore corrente anche se fuori catalogo attivo).
- Nessun backfill/riassegnazione massiva dei dipendenti in questo piano (fuori scope, spec §"Non in scope").
- Ogni task termina con test verdi eseguiti con `python django_app\manage.py test django_app.anagrafica --settings=config.settings.test --keepdb` (usare `-v 0` se serve ridurre l'I/O, mai la suite completa del progetto).
- Aggiornare `CHANGELOG.md` a fine piano (Task 7), non prima — un'unica voce coerente sull'intera feature.

---

## File Structure

- **Modifica** `django_app/anagrafica/models.py` — campo `area_aziendale` (FK) al posto di `area_aziendale_nome` (CharField) su `DipendenteAnagraficaAziendale`.
- **Crea** `django_app/anagrafica/migrations/0082_dipendente_area_aziendale_fk.py` — migration dello schema sopra.
- **Modifica** `django_app/anagrafica/views.py` — `_sync_aziendale_from_reparto` (firma+logica estesa), `dipendente_reparto_set` (legge `area_aziendale` da POST), `dipendente_anagrafica_aziendale_save` (passa `obj.area_aziendale_id` alla sync), `dipendente_detail` (nuovo context `aree_by_reparto_json`).
- **Modifica** `django_app/anagrafica/forms.py` — `AnagraficaAziendaleForm` include ora `area_aziendale` come `ModelChoiceField` filtrato.
- **Modifica** `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html` — select "Area aziendale" nel mini-form rapido, rimozione dell'input readonly morto nel form completo, riquadro di sola lettura aggiornato alla FK, JS di cascading esteso.
- **Modifica** `django_app/anagrafica/services/training_eligibility.py` — match per `area_aziendale_id` invece che per nome.
- **Crea** `django_app/anagrafica/management/commands/report_regole_formazione_area.py` — report di sola lettura.
- **Crea** `django_app/anagrafica/tests_area_aziendale_dipendente.py` — tutti i test nuovi di questo piano, in un file dedicato (segue la convenzione già in uso nel modulo per feature auto-contenute: `tests_mpq_crud.py`, `tests_skillmatrix_*.py`), per non appesantire ulteriormente il già enorme `tests.py`.
- **Modifica** `CHANGELOG.md` — voce unica a fine piano (Task 7).

---

### Task 1: Migration — FK `area_aziendale` al posto di `area_aziendale_nome`

**Files:**
- Modify: `django_app/anagrafica/models.py:1004-1023` (classe `DipendenteAnagraficaAziendale`)
- Create: `django_app/anagrafica/migrations/0082_dipendente_area_aziendale_fk.py`
- Test: `django_app/anagrafica/tests_area_aziendale_dipendente.py` (nuovo file, creato in questo task)

**Interfaces:**
- Produce: `DipendenteAnagraficaAziendale.area_aziendale` — `ForeignKey(AreaAziendale, null=True, blank=True, on_delete=SET_NULL, related_name="dipendenti_assegnati")`. Task 2+ scrivono/leggono `az.area_aziendale_id`.

- [ ] **Step 1: Scrivi il file di test con le assert sul nuovo schema**

Crea `django_app/anagrafica/tests_area_aziendale_dipendente.py`:

```python
"""Collegamento anagrafica lavorativa <-> AreaAziendale (Fase 2 dell'inversione
gerarchia Reparto/AreaAziendale, spec 2026-07-08-anagrafica-lavorativa-area-aziendale).

Copre: la FK area_aziendale sul dipendente, la sincronizzazione centralizzata in
_sync_aziendale_from_reparto (invariante area<->reparto), le due viste che la
scrivono (mini-form rapido + form completo), il context/markup del cascading in
dipendente_detail, il match per ID in training_eligibility, e il report di sola
lettura sulle regole di formazione per area.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteAreaAziendaleFieldTests(TestCase):
    """Il dipendente si collega alla nuova AreaAziendale con una FK vera (non più
    il CharField area_aziendale_nome, rimosso con l'inversione gerarchia)."""

    def test_dipendente_ha_fk_area_aziendale_non_piu_charfield(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        az = DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=901, area="UT", area_aziendale=area,
        )
        self.assertFalse(hasattr(az, "area_aziendale_nome"))
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_area_aziendale_nullable(self):
        az = DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=902)
        self.assertIsNone(az.area_aziendale_id)

    def test_elimina_area_aziendale_azzera_riferimento_dipendente(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        az = DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=903, area_aziendale=area,
        )
        area.delete()
        az.refresh_from_db()
        self.assertIsNone(az.area_aziendale_id)
```

- [ ] **Step 2: Esegui i test per verificare che falliscano**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente --settings=config.settings.test -v 2`
Expected: FAIL — `DipendenteAnagraficaAziendale() got unexpected keyword arguments: 'area_aziendale'` (il campo non esiste ancora).

- [ ] **Step 3: Modifica il modello**

In `django_app/anagrafica/models.py`, sostituisci il blocco (righe 1008-1022):

```python
    area = models.CharField(max_length=100, blank=True, default="", verbose_name="Reparto")
    area_aziendale_nome = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Area aziendale",
        help_text="Compilato automaticamente dall'area aziendale del reparto assegnato.",
    )
    caporeparto_legacy_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Caporeparto",
        help_text="ID legacy del caporeparto, compilato automaticamente dal reparto assegnato.",
    )
```

con:

```python
    area = models.CharField(max_length=100, blank=True, default="", verbose_name="Reparto")
    area_aziendale = models.ForeignKey(
        AreaAziendale,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dipendenti_assegnati",
        verbose_name="Area aziendale",
    )
    caporeparto_legacy_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Caporeparto",
        help_text="ID legacy del caporeparto, compilato automaticamente dal reparto assegnato.",
    )
```

(`AreaAziendale` è già definita più sopra nello stesso file, riga 763 — nessun nuovo import necessario.)

- [ ] **Step 4: Crea la migration**

Crea `django_app/anagrafica/migrations/0082_dipendente_area_aziendale_fk.py`:

```python
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0081_subnav_reparti_persone"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="dipendenteanagraficaaziendale",
            name="area_aziendale_nome",
        ),
        migrations.AddField(
            model_name="dipendenteanagraficaaziendale",
            name="area_aziendale",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dipendenti_assegnati",
                to="anagrafica.areaaziendale",
                verbose_name="Area aziendale",
            ),
        ),
    ]
```

- [ ] **Step 5: Esegui i test e verifica che passino**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente --settings=config.settings.test -v 2`
Expected: PASS (3 test).

- [ ] **Step 6: Commit**

```bash
git add django_app/anagrafica/models.py django_app/anagrafica/migrations/0082_dipendente_area_aziendale_fk.py django_app/anagrafica/tests_area_aziendale_dipendente.py
git commit -m "feat(anagrafica): FK area_aziendale su DipendenteAnagraficaAziendale al posto del CharField morto"
```

---

### Task 2: `_sync_aziendale_from_reparto` esteso + mini-form "Cambia reparto"

**Files:**
- Modify: `django_app/anagrafica/views.py:5412-5432` (`_sync_aziendale_from_reparto`)
- Modify: `django_app/anagrafica/views.py:3192-3236` (`dipendente_reparto_set`)
- Test: `django_app/anagrafica/tests_area_aziendale_dipendente.py`

**Interfaces:**
- Consumes: `AreaAziendale`, `Reparto`, `DipendenteAnagraficaAziendale` (Task 1).
- Produces: `_sync_aziendale_from_reparto(legacy_id: int, reparto_nome: str, *, area_aziendale_id: int | None = None, saved_by) -> None`. Task 3 la richiama anch'essa con lo stesso `area_aziendale_id` kwarg.

- [ ] **Step 1: Scrivi i test per `_sync_aziendale_from_reparto` (falliscono: kwarg non esiste)**

Aggiungi a `tests_area_aziendale_dipendente.py`:

```python
@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SyncAziendaleFromRepartoTests(TestCase):
    """_sync_aziendale_from_reparto valida che l'Area aziendale assegnata
    appartenga sempre al Reparto risolto, azzerandola in caso contrario."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="sync_az_admin", email="sync_az_admin@x.local", password="x"
        )

    def test_area_appartenente_al_reparto_viene_salvata(self):
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT", caporeparto_legacy_id=401)
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        _sync_aziendale_from_reparto(910, "UT", area_aziendale_id=area.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=910)
        self.assertEqual(az.area_aziendale_id, area.pk)
        self.assertEqual(az.caporeparto_legacy_id, 401)

    def test_area_di_un_altro_reparto_viene_azzerata(self):
        from .views import _sync_aziendale_from_reparto
        Reparto.objects.create(nome="UT")
        rep_mag = Reparto.objects.create(nome="MAG")
        area_mag = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_mag)
        _sync_aziendale_from_reparto(911, "UT", area_aziendale_id=area_mag.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=911)
        self.assertIsNone(az.area_aziendale_id)

    def test_reparto_vuoto_azzera_anche_area(self):
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        _sync_aziendale_from_reparto(912, "", area_aziendale_id=area.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=912)
        self.assertIsNone(az.area_aziendale_id)
        self.assertEqual(az.area, "")

    def test_area_disattivata_ma_ancora_del_reparto_resta_valida(self):
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep, is_active=False)
        _sync_aziendale_from_reparto(913, "UT", area_aziendale_id=area.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=913)
        self.assertEqual(az.area_aziendale_id, area.pk)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente.SyncAziendaleFromRepartoTests --settings=config.settings.test -v 2`
Expected: FAIL — `TypeError: _sync_aziendale_from_reparto() got an unexpected keyword argument 'area_aziendale_id'`.

- [ ] **Step 3: Estendi `_sync_aziendale_from_reparto`**

In `django_app/anagrafica/views.py`, sostituisci (righe 5412-5432):

```python
def _sync_aziendale_from_reparto(legacy_id: int, reparto_nome: str, *, saved_by) -> None:
    """Aggiorna caporeparto_legacy_id su DipendenteAnagraficaAziendale in base
    al Reparto assegnato. Chiamato ogni volta che il reparto cambia.

    L'area aziendale non si autopopola più: con l'inversione della gerarchia
    un Reparto può avere più Aree aziendali figlie, quindi non è più
    derivabile in automatico da un singolo Reparto (Fase 2 nello spec).
    """
    capo_id = None
    if reparto_nome:
        rep = Reparto.objects.filter(nome__iexact=reparto_nome, is_active=True).first()
        if rep:
            capo_id = rep.caporeparto_legacy_id
    az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id,
        defaults={"updated_by": saved_by},
    )
    az.area = reparto_nome
    az.caporeparto_legacy_id = capo_id
    az.updated_by = saved_by
    az.save(update_fields=["area", "caporeparto_legacy_id", "updated_by", "updated_at"])
```

con:

```python
def _sync_aziendale_from_reparto(
    legacy_id: int, reparto_nome: str, *, area_aziendale_id: int | None = None, saved_by
) -> None:
    """Aggiorna caporeparto_legacy_id e area_aziendale su DipendenteAnagraficaAziendale
    in base al Reparto assegnato. Chiamato ogni volta che il reparto (o l'area) cambia.

    L'Area aziendale deve appartenere al Reparto risolto, altrimenti viene azzerata
    silenziosamente (reparto cambiato altrove, reparto non trovato/disattivato, o area
    di un altro reparto) invece di bloccare il salvataggio. Non si richiede che l'area
    sia attiva: un'assegnazione a un'area nel frattempo disattivata resta valida, come
    già avviene per area/ruolo_aziendale (forms.py preserva il valore corrente anche
    se non più nel catalogo "attive").
    """
    capo_id = None
    rep = None
    if reparto_nome:
        rep = Reparto.objects.filter(nome__iexact=reparto_nome, is_active=True).first()
        if rep:
            capo_id = rep.caporeparto_legacy_id

    area_id_valido = None
    if area_aziendale_id and rep is not None:
        area = AreaAziendale.objects.filter(pk=area_aziendale_id, reparto_id=rep.id).first()
        if area is not None:
            area_id_valido = area.id

    az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id,
        defaults={"updated_by": saved_by},
    )
    az.area = reparto_nome
    az.caporeparto_legacy_id = capo_id
    az.area_aziendale_id = area_id_valido
    az.updated_by = saved_by
    az.save(update_fields=["area", "caporeparto_legacy_id", "area_aziendale", "updated_by", "updated_at"])
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente.SyncAziendaleFromRepartoTests --settings=config.settings.test -v 2`
Expected: PASS (4 test).

- [ ] **Step 5: Scrivi i test per il mini-form `dipendente_reparto_set` (falliscono: POST area_aziendale ignorato)**

Aggiungi a `tests_area_aziendale_dipendente.py`:

```python
@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteRepartoSetAreaAziendaleTests(TestCase):
    """Il mini-form rapido 'Cambia reparto' può impostare anche l'Area aziendale."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="rep_set_admin", email="rep_set_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo) "
                "VALUES (%s, %s, %s, %s)",
                ["l.verdi", "Luca", "Verdi", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["l.verdi"])
            self.legacy_id = int(cursor.fetchone()[0])

    def test_post_con_area_del_reparto_selezionato_viene_salvata(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.post(
            reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id]),
            {"reparto": "UT", "area_aziendale": str(area.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_post_con_area_di_un_altro_reparto_viene_ignorata(self):
        Reparto.objects.create(nome="UT")
        rep_mag = Reparto.objects.create(nome="MAG")
        area_mag = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_mag)
        resp = self.client.post(
            reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id]),
            {"reparto": "UT", "area_aziendale": str(area_mag.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertIsNone(az.area_aziendale_id)

    def test_post_senza_area_non_genera_errore(self):
        Reparto.objects.create(nome="UT")
        resp = self.client.post(
            reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id]),
            {"reparto": "UT"},
        )
        self.assertEqual(resp.status_code, 302)
```

- [ ] **Step 6: Esegui i test e verifica che falliscano**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente.DipendenteRepartoSetAreaAziendaleTests --settings=config.settings.test -v 2`
Expected: FAIL su `test_post_con_area_del_reparto_selezionato_viene_salvata` — `area_aziendale_id` resta `None` perché la vista non legge ancora il POST.

- [ ] **Step 7: Aggiorna `dipendente_reparto_set`**

In `django_app/anagrafica/views.py`, nel corpo di `dipendente_reparto_set` (righe 3192-3236), subito dopo la riga:

```python
    reparto_nome = (request.POST.get("reparto") or "").strip()[:200]
```

aggiungi:

```python
    area_aziendale_raw = (request.POST.get("area_aziendale") or "").strip()
    area_aziendale_id = int(area_aziendale_raw) if area_aziendale_raw.isdigit() else None
```

e sostituisci la riga:

```python
        _sync_aziendale_from_reparto(legacy_id, reparto_nome, saved_by=request.user)
```

con:

```python
        _sync_aziendale_from_reparto(
            legacy_id, reparto_nome, area_aziendale_id=area_aziendale_id, saved_by=request.user
        )
```

- [ ] **Step 8: Esegui i test e verifica che passino**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente --settings=config.settings.test -v 2`
Expected: PASS (tutti i test finora, 10 totali).

- [ ] **Step 9: Commit**

```bash
git add django_app/anagrafica/views.py django_app/anagrafica/tests_area_aziendale_dipendente.py
git commit -m "feat(anagrafica): _sync_aziendale_from_reparto valida area<->reparto; mini-form Cambia reparto imposta l'area"
```

---

### Task 3: Form completo "Modifica dati aziendali" — `AnagraficaAziendaleForm` + `dipendente_anagrafica_aziendale_save`

**Files:**
- Modify: `django_app/anagrafica/forms.py:1-18` (import), `forms.py:140-184` (`AnagraficaAziendaleForm`)
- Modify: `django_app/anagrafica/views.py:4026-4062` (`dipendente_anagrafica_aziendale_save`)
- Test: `django_app/anagrafica/tests_area_aziendale_dipendente.py`

**Interfaces:**
- Consumes: `_sync_aziendale_from_reparto(..., area_aziendale_id=..., saved_by=...)` (Task 2).
- Produces: `AnagraficaAziendaleForm` con campo `area_aziendale` (`ModelChoiceField`, id HTML `id_area_aziendale`, widget attr `data-current`). Task 4 (template) si aggancia a `id_area_aziendale` per il cascading JS.

- [ ] **Step 1: Scrivi i test (falliscono: campo assente / area non corretta)**

Aggiungi a `tests_area_aziendale_dipendente.py`:

```python
@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnagraficaAziendaleFormAreaAziendaleTests(TestCase):
    """Il form completo 'Modifica dati aziendali' include ora la FK area_aziendale,
    corretta/azzerata da _sync_aziendale_from_reparto se incoerente col reparto."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="az_form_admin", email="az_form_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_form_include_campo_area_aziendale_non_piu_nome(self):
        from .forms import AnagraficaAziendaleForm
        form = AnagraficaAziendaleForm()
        self.assertIn("area_aziendale", form.fields)
        self.assertNotIn("area_aziendale_nome", form.fields)

    def test_save_con_area_coerente_persiste_la_fk(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[920]),
            {"area": "UT", "area_aziendale": str(area.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=920)
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_save_con_area_incoerente_viene_azzerata(self):
        Reparto.objects.create(nome="UT")
        rep_mag = Reparto.objects.create(nome="MAG")
        area_mag = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_mag)
        resp = self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[921]),
            {"area": "UT", "area_aziendale": str(area_mag.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=921)
        self.assertIsNone(az.area_aziendale_id)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente.AnagraficaAziendaleFormAreaAziendaleTests --settings=config.settings.test -v 2`
Expected: FAIL — `assertIn("area_aziendale", form.fields)` fallisce (il campo è ancora escluso).

- [ ] **Step 3: Aggiorna l'import in `forms.py`**

In `django_app/anagrafica/forms.py`, dopo la riga 4 (`from django.utils import timezone`), aggiungi:

```python
from django.db.models import Q
```

- [ ] **Step 4: Aggiorna `AnagraficaAziendaleForm`**

Sostituisci il blocco `Meta.exclude` (righe 143-147):

```python
        exclude = [
            "legacy_anagrafica_id", "updated_by", "updated_at",
            "tipologia_contratto", "livello_inquadramento",
            "area_aziendale_nome", "caporeparto_legacy_id",
        ]
```

con:

```python
        exclude = [
            "legacy_anagrafica_id", "updated_by", "updated_at",
            "tipologia_contratto", "livello_inquadramento",
            "caporeparto_legacy_id",
        ]
```

Nel metodo `__init__` (dopo il blocco che tratta `self.fields["area"]`, righe 166-175, e prima del blocco "Ruolo aziendale" a riga 177), aggiungi:

```python
        # Area aziendale: dropdown filtrato via JS sul Reparto scelto (client-side,
        # vedi cascading in dipendente_detail.html). Il queryset include le aree
        # attive più quella eventualmente già assegnata (anche se nel frattempo
        # disattivata), stesso criterio già usato sopra per "area".
        area_aziendale_corrente_id = self.instance.area_aziendale_id if self.instance.pk else None
        self.fields["area_aziendale"].queryset = AreaAziendale.objects.filter(
            Q(is_active=True) | Q(pk=area_aziendale_corrente_id)
        ).order_by("nome")
        self.fields["area_aziendale"].label = "Area aziendale"
        self.fields["area_aziendale"].empty_label = "— Nessuna —"
        self.fields["area_aziendale"].widget.attrs.update({
            "class": "dp-input",
            "data-current": str(area_aziendale_corrente_id or ""),
        })
```

- [ ] **Step 5: Aggiorna `dipendente_anagrafica_aziendale_save`**

In `django_app/anagrafica/views.py`, sostituisci la riga (4044):

```python
        _sync_aziendale_from_reparto(legacy_id, obj.area or "", saved_by=request.user)
```

con:

```python
        _sync_aziendale_from_reparto(
            legacy_id, obj.area or "", area_aziendale_id=obj.area_aziendale_id, saved_by=request.user
        )
```

- [ ] **Step 6: Esegui i test e verifica che passino**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente --settings=config.settings.test -v 2`
Expected: PASS (tutti i test finora, 13 totali).

- [ ] **Step 7: Commit**

```bash
git add django_app/anagrafica/forms.py django_app/anagrafica/views.py django_app/anagrafica/tests_area_aziendale_dipendente.py
git commit -m "feat(anagrafica): AnagraficaAziendaleForm espone area_aziendale, sincronizzata alla stessa invariante"
```

---

### Task 4: `dipendente_detail` — context `aree_by_reparto_json` + template (cascading UI)

**Files:**
- Modify: `django_app/anagrafica/views.py:2004-2017` (blocco "Catalogo reparti"), `views.py:2041-2058` (context del `render`)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html:843-864` (mini-form), `:891-900` (riquadro sola lettura), `:955-959` (rimozione input morto), `:2698-2711` (JS)
- Test: `django_app/anagrafica/tests_area_aziendale_dipendente.py`

**Interfaces:**
- Consumes: `aziendale.area_aziendale_id` (Task 1), `id_area_aziendale` come id del campo form (Task 3).
- Produces: context `aree_by_reparto_json` (dict JSON `{nome_reparto: [{id, nome}, ...]}`), markup `id="mini-reparto-select"` / `id="mini-area-select"` nel mini-form.

- [ ] **Step 1: Scrivi il test UI (fallisce: markup assente)**

Aggiungi a `tests_area_aziendale_dipendente.py`:

```python
@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteDetailAreaAziendaleUITests(TestCase):
    """dipendente_detail espone il cascading Reparto->Area aziendale in pagina."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="dd_area_admin", email="dd_area_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["p.bianchi", "Paolo", "Bianchi", "UT", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["p.bianchi"])
            self.legacy_id = int(cursor.fetchone()[0])

    def test_pagina_espone_select_area_aziendale_e_blob_json(self):
        rep = Reparto.objects.create(nome="UT")
        AreaAziendale.objects.create(nome="IN1", reparto=rep)
        AreaAziendale.objects.create(nome="IN2", reparto=rep)
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('id="mini-area-select"', content)
        self.assertIn('id_area_aziendale', content)
        self.assertIn('"UT"', content)
        self.assertIn('"IN1"', content)
        self.assertIn('"IN2"', content)
        self.assertNotIn("az-area-autofill", content)
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente.DipendenteDetailAreaAziendaleUITests --settings=config.settings.test -v 2`
Expected: FAIL — `'id="mini-area-select"' not found` (markup non ancora presente).

- [ ] **Step 3: Aggiungi il context `aree_by_reparto_json` nella vista**

In `django_app/anagrafica/views.py`, subito dopo il blocco che costruisce `reparto_autofill_json` (righe 2012-2017):

```python
    reparto_autofill_json = json.dumps({
        r.nome: {
            "capo_label": _dip_picker_map_detail.get(r.caporeparto_legacy_id or 0, ""),
        }
        for r in reparti_catalog
    })
```

aggiungi:

```python
    _area_corrente_id = aziendale.area_aziendale_id if aziendale else None
    aree_by_reparto: dict[str, list[dict]] = {}
    for a in (
        AreaAziendale.objects.filter(Q(is_active=True) | Q(pk=_area_corrente_id))
        .select_related("reparto")
        .order_by("nome")
    ):
        if a.reparto_id is None:
            continue
        aree_by_reparto.setdefault(a.reparto.nome, []).append({"id": a.id, "nome": a.nome})
    aree_by_reparto_json = json.dumps(aree_by_reparto)
```

(`Q` e `AreaAziendale` sono già importati a livello di modulo, righe 17 e 62.)

Nel `return render(...)` (righe 2041-2058), subito dopo la riga:

```python
        "reparto_autofill_json": reparto_autofill_json,
```

aggiungi:

```python
        "aree_by_reparto_json": aree_by_reparto_json,
```

- [ ] **Step 4: Aggiorna il mini-form "Cambia reparto" nel template**

In `dipendente_detail.html`, sostituisci il blocco (righe 843-864):

```html
          <div class="dp-mansione-form" id="reparto-form">
            <form method="post" action="{% url 'anagrafica:dipendente_reparto_set' legacy_id %}" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              {% csrf_token %}
              <select name="reparto" class="dp-select" style="min-width:200px;">
                <option value="">— Nessun reparto —</option>
                {% for rep in reparti_catalog %}
                  <option value="{{ rep.nome }}" {% if rep.nome == dip.reparto %}selected{% endif %}>
                    {{ rep.nome }}
                  </option>
                {% endfor %}
                {% if dip.reparto and not reparto_in_catalog %}
                  <option value="{{ dip.reparto }}" selected>{{ dip.reparto }} (attuale – non in catalogo)</option>
                {% endif %}
              </select>
              <button type="submit" class="dp-btn dp-btn-primary dp-btn-xs">Salva</button>
              <button type="button" class="dp-btn dp-btn-ghost dp-btn-xs" onclick="toggleRepartoForm()">Annulla</button>
            </form>
            <div style="font-size:11px;color:#94a3b8;margin-top:2px;">
              Non trovi il reparto? <a href="{% url 'anagrafica:aree_list' %}" style="color:#1f87cd;">Gestisci il catalogo</a>.
            </div>
          </div>
```

con:

```html
          <div class="dp-mansione-form" id="reparto-form">
            <form method="post" action="{% url 'anagrafica:dipendente_reparto_set' legacy_id %}" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              {% csrf_token %}
              <select name="reparto" id="mini-reparto-select" class="dp-select" style="min-width:200px;">
                <option value="">— Nessun reparto —</option>
                {% for rep in reparti_catalog %}
                  <option value="{{ rep.nome }}" {% if rep.nome == dip.reparto %}selected{% endif %}>
                    {{ rep.nome }}
                  </option>
                {% endfor %}
                {% if dip.reparto and not reparto_in_catalog %}
                  <option value="{{ dip.reparto }}" selected>{{ dip.reparto }} (attuale – non in catalogo)</option>
                {% endif %}
              </select>
              <select name="area_aziendale" id="mini-area-select" class="dp-select" style="min-width:180px;" data-current="{{ aziendale.area_aziendale_id|default:'' }}">
                <option value="">— Nessuna area —</option>
              </select>
              <button type="submit" class="dp-btn dp-btn-primary dp-btn-xs">Salva</button>
              <button type="button" class="dp-btn dp-btn-ghost dp-btn-xs" onclick="toggleRepartoForm()">Annulla</button>
            </form>
            <div style="font-size:11px;color:#94a3b8;margin-top:2px;">
              Non trovi il reparto? <a href="{% url 'anagrafica:aree_list' %}" style="color:#1f87cd;">Gestisci il catalogo</a>.
            </div>
          </div>
```

- [ ] **Step 5: Aggiorna il riquadro di sola lettura "Area aziendale"**

Sostituisci il blocco (righe 891-900):

```html
        <div class="dp-info-item">
          <div class="dp-info-label">Area aziendale</div>
          <div class="dp-info-value">
            {% if aziendale.area_aziendale_nome %}
              {{ aziendale.area_aziendale_nome }}
            {% else %}
              <span style="color:#94a3b8;font-size:12px;">Non assegnata</span>
            {% endif %}
          </div>
        </div>
```

con:

```html
        <div class="dp-info-item">
          <div class="dp-info-label">Area aziendale</div>
          <div class="dp-info-value">
            {% if aziendale.area_aziendale %}
              {{ aziendale.area_aziendale.nome }}
            {% else %}
              <span style="color:#94a3b8;font-size:12px;">Non assegnata</span>
            {% endif %}
          </div>
        </div>
```

- [ ] **Step 6: Rimuovi l'input readonly morto nel form completo**

Elimina il blocco (righe 955-958), lasciando che il ciclo `{% for field in form_aziendale %}` renda il campo `area_aziendale` normalmente:

```html
            <div class="dp-form-field">
              <label class="dp-form-label">Area aziendale</label>
              <input type="text" id="az-area-autofill" class="dp-input" readonly style="background:#f8fafc;color:#64748b;cursor:default;" value="{{ aziendale.area_aziendale_nome|default:'' }}">
              <span style="font-size:11px;color:#94a3b8;">Non assegnata automaticamente in questa fase</span>
            </div>
```

- [ ] **Step 7: Estendi il JS di cascading**

Sostituisci il blocco JS finale (righe 2698-2711):

```html
// Auto-fill caporeparto quando si seleziona il reparto (l'area aziendale non
// si autopopola più: un reparto può avere più aree aziendali figlie).
(function() {
  var repartiData = {{ reparto_autofill_json|safe }};
  var sel = document.getElementById('id_area');
  if (!sel) return;
  function fill() {
    var d = repartiData[sel.value] || {};
    var capoEl = document.getElementById('az-capo-autofill');
    if (capoEl) capoEl.value = d.capo_label || '';
  }
  sel.addEventListener('change', fill);
  fill();
})();
```

con:

```html
// Auto-fill caporeparto in sola lettura + cascading Reparto -> Area aziendale
// (client-side, nessuna chiamata al server). L'area aziendale è impostabile sia
// dal mini-form rapido "Cambia reparto" sia dal form completo "Modifica dati
// aziendali"; entrambi ricostruiscono le opzioni dallo stesso blob JSON.
(function() {
  var repartiData = {{ reparto_autofill_json|safe }};
  var areeByReparto = {{ aree_by_reparto_json|safe }};

  function syncAreaOptions(repartoSel, areaSel) {
    if (!repartoSel || !areaSel) return;
    var current = areaSel.dataset.current || '';
    var opzioni = areeByReparto[repartoSel.value] || [];
    areaSel.innerHTML = '';
    var optNone = document.createElement('option');
    optNone.value = '';
    optNone.textContent = '— Nessuna area —';
    areaSel.appendChild(optNone);
    opzioni.forEach(function(area) {
      var opt = document.createElement('option');
      opt.value = String(area.id);
      opt.textContent = area.nome;
      if (String(area.id) === current) opt.selected = true;
      areaSel.appendChild(opt);
    });
    areaSel.dataset.current = '';  // il preselect vale solo al primo render
  }

  function wireCascading(repartoSel, areaSel) {
    if (!repartoSel || !areaSel) return;
    syncAreaOptions(repartoSel, areaSel);
    repartoSel.addEventListener('change', function() { syncAreaOptions(repartoSel, areaSel); });
  }

  wireCascading(document.getElementById('mini-reparto-select'), document.getElementById('mini-area-select'));
  wireCascading(document.getElementById('id_area'), document.getElementById('id_area_aziendale'));

  var sel = document.getElementById('id_area');
  if (sel) {
    function fillCapo() {
      var d = repartiData[sel.value] || {};
      var capoEl = document.getElementById('az-capo-autofill');
      if (capoEl) capoEl.value = d.capo_label || '';
    }
    sel.addEventListener('change', fillCapo);
    fillCapo();
  }
})();
```

- [ ] **Step 8: Esegui il test e verifica che passi**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente --settings=config.settings.test -v 2`
Expected: PASS (tutti i test finora, 14 totali).

- [ ] **Step 9: Verifica manuale nel browser (dev)**

Avvia `python django_app\manage.py runserver --settings=config.settings.dev`, apri la scheda di un dipendente in `/anagrafica/dipendenti/<id>/`, tab Anagrafica:
- click "✏ Cambia reparto" → cambiare il Reparto deve ripopolare subito la select Area aziendale con solo le aree di quel reparto.
- "✏ Modifica" (form completo) → stesso comportamento sulla select "Area aziendale" del form, il campo readonly morto non c'è più.

- [ ] **Step 10: Commit**

```bash
git add django_app/anagrafica/views.py django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html django_app/anagrafica/tests_area_aziendale_dipendente.py
git commit -m "feat(anagrafica): cascading Reparto->Area aziendale in dipendente_detail (mini-form + form completo)"
```

---

### Task 5: `training_eligibility.py` — match per FK invece che per nome

**Files:**
- Modify: `django_app/anagrafica/services/training_eligibility.py:120-132`
- Test: `django_app/anagrafica/tests_area_aziendale_dipendente.py`

**Interfaces:**
- Consumes: `DipendenteAnagraficaAziendale.area_aziendale_id` (Task 1), `TrainingRequirementRule.area_id` (esistente, invariato).

- [ ] **Step 1: Scrivi il test (fallisce: nessun match, la regola resta "dormiente")**

Aggiungi a `tests_area_aziendale_dipendente.py`:

```python
@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TrainingEligibilityAreaAziendaleFkTests(TestCase):
    """Le regole di formazione obbligatoria per Area aziendale matchano per FK,
    non più per nome sul CharField rimosso."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, attivo) VALUES "
                "(931, 'Anna', 'Verdi', 1), (932, 'Bruno', 'Neri', 1)"
            )

    def test_pertinenza_per_area_aziendale_match_per_fk(self):
        from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule
        from .services.training_eligibility import candidati_corso
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=931, area_aziendale=area)
        # 932 resta senza area assegnata: non deve risultare pertinente.
        piano = TrainingPlan.objects.create(codice="PSIC", nome="Piano sicurezza")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="CS1", titolo="Corso sicurezza area", durata_ore_teorica=4,
        )
        TrainingRequirementRule.objects.create(
            corso=corso, area=area, is_active=True, is_mandatory=True,
        )
        res = candidati_corso(corso)
        ids = {c["legacy_id"] for c in res["idonei"]} | {c["legacy_id"] for c in res["non_idonei"]}
        self.assertIn(931, ids)
        self.assertNotIn(932, ids)
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente.TrainingEligibilityAreaAziendaleFkTests --settings=config.settings.test -v 2`
Expected: FAIL — `931 not in ids` (il match cerca ancora `area_aziendale_nome`, sempre vuoto).

- [ ] **Step 3: Aggiorna il match**

In `django_app/anagrafica/services/training_eligibility.py`, sostituisci il blocco (righe 120-132):

```python
    # 3) regole per area aziendale (match per nome su area_aziendale_nome denormalizzato)
    area_nomi = {
        r.area.nome.strip().casefold()
        for r in rules if r.area_id and r.area is not None
    }
    if area_nomi:
        for lid, area_nome in (
            DipendenteAnagraficaAziendale.objects
            .exclude(area_aziendale_nome="")
            .values_list("legacy_anagrafica_id", "area_aziendale_nome")
        ):
            if (area_nome or "").strip().casefold() in area_nomi:
                ids.add(int(lid))
```

con:

```python
    # 3) regole per area aziendale (match per FK area_aziendale, non più per nome)
    area_ids = {r.area_id for r in rules if r.area_id}
    if area_ids:
        ids.update(
            int(lid) for lid in DipendenteAnagraficaAziendale.objects
            .filter(area_aziendale_id__in=area_ids)
            .values_list("legacy_anagrafica_id", flat=True)
        )
```

- [ ] **Step 4: Esegui il test e verifica che passi**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente --settings=config.settings.test -v 2`
Expected: PASS (tutti i test finora, 15 totali).

- [ ] **Step 5: Commit**

```bash
git add django_app/anagrafica/services/training_eligibility.py django_app/anagrafica/tests_area_aziendale_dipendente.py
git commit -m "fix(anagrafica): training_eligibility matcha le regole per area aziendale via FK invece che per nome"
```

---

### Task 6: Management command di sola lettura `report_regole_formazione_area`

**Files:**
- Create: `django_app/anagrafica/management/commands/report_regole_formazione_area.py`
- Test: `django_app/anagrafica/tests_area_aziendale_dipendente.py`

**Interfaces:**
- Consumes: `TrainingRequirementRule` (`models_formazione.py`), `DipendenteAnagraficaAziendale.area_aziendale_id` (Task 1).

- [ ] **Step 1: Scrivi il test (fallisce: comando inesistente)**

Aggiungi a `tests_area_aziendale_dipendente.py`:

```python
@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReportRegoleFormazioneAreaCommandTests(TestCase):
    """Comando di sola lettura: elenca le TrainingRequirementRule per area con
    il conteggio dei dipendenti oggi assegnati (via FK)."""

    def test_elenca_regole_area_con_conteggio_dipendenti(self):
        from io import StringIO
        from django.core.management import call_command
        from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule

        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        piano = TrainingPlan.objects.create(codice="PF", nome="Piano F")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="C1", titolo="Corso sicurezza", durata_ore_teorica=8,
        )
        TrainingRequirementRule.objects.create(corso=corso, area=area, is_active=True, is_mandatory=True)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=940, area_aziendale=area)

        out = StringIO()
        call_command("report_regole_formazione_area", stdout=out)
        output = out.getvalue()
        self.assertIn("IN1", output)
        self.assertIn("UT", output)
        self.assertIn("Corso sicurezza", output)

    def test_nessuna_regola_stampa_messaggio(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("report_regole_formazione_area", stdout=out)
        self.assertIn("Nessuna regola", out.getvalue())
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente.ReportRegoleFormazioneAreaCommandTests --settings=config.settings.test -v 2`
Expected: FAIL — `Unknown command: 'report_regole_formazione_area'`.

- [ ] **Step 3: Crea il comando**

Crea `django_app/anagrafica/management/commands/report_regole_formazione_area.py`:

```python
"""Report di sola lettura delle TrainingRequirementRule scoped per Area aziendale.

Con l'inversione gerarchia Reparto/AreaAziendale (0080) e il collegamento del
dipendente alla nuova AreaAziendale (0082), le regole di obbligo formativo per
area tornano operative ma ripartono da zero: nessun dipendente ha ancora
un'Area aziendale assegnata finché non viene riassegnata da UI. Questo comando
elenca le regole attive scoped per area e quanti dipendenti risultano oggi
assegnati a quell'area, per dare visibilità su cosa aspetta una riassegnazione.

Esempio:
    python manage.py report_regole_formazione_area
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anagrafica.models import DipendenteAnagraficaAziendale
from anagrafica.models_formazione import TrainingRequirementRule


class Command(BaseCommand):
    help = "Sola lettura: elenca le TrainingRequirementRule per Area aziendale e i dipendenti oggi assegnati."

    def handle(self, *args, **options):
        regole = (
            TrainingRequirementRule.objects
            .filter(is_active=True, area__isnull=False)
            .select_related("area", "area__reparto", "corso", "piano")
            .order_by("area__nome")
        )
        if not regole.exists():
            self.stdout.write("Nessuna regola di formazione con target 'area aziendale' attiva.")
            return

        self.stdout.write(f"{'Area':<20} {'Reparto':<20} {'Corso/Piano':<40} {'Dipendenti assegnati':>22}")
        self.stdout.write("-" * 104)
        for regola in regole:
            oggetto = regola.corso.titolo if regola.corso_id else (regola.piano.nome if regola.piano_id else "—")
            n_dipendenti = DipendenteAnagraficaAziendale.objects.filter(area_aziendale_id=regola.area_id).count()
            reparto_nome = regola.area.reparto.nome if regola.area.reparto_id else "—"
            self.stdout.write(
                f"{regola.area.nome:<20} {reparto_nome:<20} {oggetto:<40} {n_dipendenti:>22}"
            )
```

- [ ] **Step 4: Esegui il test e verifica che passi**

Run: `python django_app\manage.py test django_app.anagrafica.tests_area_aziendale_dipendente --settings=config.settings.test -v 2`
Expected: PASS (tutti i test del piano, 17 totali).

- [ ] **Step 5: Commit**

```bash
git add django_app/anagrafica/management/commands/report_regole_formazione_area.py django_app/anagrafica/tests_area_aziendale_dipendente.py
git commit -m "feat(anagrafica): report di sola lettura sulle regole di formazione per area aziendale"
```

---

### Task 7: Suite completa, CHANGELOG, chiusura

**Files:**
- Modify: `CHANGELOG.md` (voce `[Unreleased]`)

- [ ] **Step 1: Esegui l'intera suite `anagrafica` (non l'intero progetto)**

Run: `python django_app\manage.py test django_app.anagrafica --settings=config.settings.test --keepdb -v 1`
Expected: PASS, nessuna nuova failure. Le uniche failure attese sono quelle pre-esistenti e non correlate già note (vedi memoria di sessione: `AnagraficaDipendentiViewTests` avatar/foto, `FormazioneFlussoTests.test_corso_form_categoria_e_qualifica` su `quiz_punteggio_minimo`, `SkillMatrixImpostazioniViewTests.test_post_salva`, `test_upload_validation` `FornitoreDocumentoForm`). Se emergono failure diverse da queste, fermarsi e indagare prima di proseguire.

- [ ] **Step 2: `manage.py check`**

Run: `python django_app\manage.py check --settings=config.settings.test`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Aggiorna CHANGELOG.md**

Apri `CHANGELOG.md`, sotto `## [Unreleased]` → `### Added`, aggiungi una voce (segui lo stile delle voci esistenti — file coinvolti tra parentesi, poi la spiegazione):

```markdown
- **Anagrafica · Collegamento anagrafica lavorativa alla nuova AreaAziendale (Fase 2 dell'inversione gerarchia)** (`django_app/anagrafica/models.py` [`DipendenteAnagraficaAziendale.area_aziendale`: FK a `AreaAziendale`, `SET_NULL`, al posto del CharField morto `area_aziendale_nome`], `anagrafica/migrations/0082_dipendente_area_aziendale_fk.py` [nuova], `anagrafica/views.py` [`_sync_aziendale_from_reparto` valida ora che l'Area aziendale appartenga al Reparto risolto, azzerandola silenziosamente altrimenti — invariante centralizzata, richiamata sia da `dipendente_reparto_set` (mini-form rapido) sia da `dipendente_anagrafica_aziendale_save` (form completo); `dipendente_detail` espone `aree_by_reparto_json`], `anagrafica/forms.py` [`AnagraficaAziendaleForm` include ora `area_aziendale` come dropdown filtrato], `templates/anagrafica/pages/dipendente_detail.html` [select "Area aziendale" nel mini-form "Cambia reparto" e nel form "Modifica dati aziendali", cascading Reparto→Area client-side via JS, rimosso l'input readonly ormai morto], `anagrafica/services/training_eligibility.py` [le regole di formazione obbligatoria per area matchano ora per FK invece che per nome sul campo rimosso — **fix**: erano silenziosamente inefficaci dall'inversione gerarchia in poi], `anagrafica/management/commands/report_regole_formazione_area.py` [nuovo, sola lettura], `anagrafica/tests_area_aziendale_dipendente.py` [nuovo, 17 test]): completa la Fase 2 rimandata in `0080_reparto_area_aziendale_inversione` — il dipendente può ora essere assegnato a un'Area aziendale specifica, coerente col Reparto scelto (nessuna validazione bloccante: la coerenza è sempre corretta in automatico, non richiesta l'attivazione dell'area per preservare assegnazioni storiche). Nessun backfill automatico dei dipendenti esistenti (restano `area_aziendale = NULL` finché non riassegnati da UI); il nuovo comando dà visibilità su quali regole di formazione per area aspettano una riassegnazione. Spec: `docs/superpowers/specs/2026-07-08-anagrafica-lavorativa-area-aziendale-design.md`. Piano: `docs/superpowers/plans/2026-07-08-anagrafica-lavorativa-area-aziendale.md`.
```

- [ ] **Step 4: Verifica `git status` e stage solo i file di questo piano**

Run: `git status --short`
Verifica che non ci siano altre modifiche non correlate (worktree condiviso con altre sessioni). Stage **solo**:

```bash
git add django_app/anagrafica/models.py \
        django_app/anagrafica/migrations/0082_dipendente_area_aziendale_fk.py \
        django_app/anagrafica/views.py \
        django_app/anagrafica/forms.py \
        django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html \
        django_app/anagrafica/services/training_eligibility.py \
        django_app/anagrafica/management/commands/report_regole_formazione_area.py \
        django_app/anagrafica/tests_area_aziendale_dipendente.py \
        CHANGELOG.md
```

(Se i Task 1-6 sono già stati committati singolarmente, questo passo copre solo la voce CHANGELOG residua: `git add CHANGELOG.md`.)

- [ ] **Step 5: Commit finale**

```bash
git commit -m "docs(anagrafica): CHANGELOG collegamento anagrafica lavorativa <-> AreaAziendale"
```

---

## Note per chi esegue

- Le viste che leggono la tabella legacy `anagrafica_dipendenti` (`dipendente_reparto_set`, `dipendente_detail`) richiedono `_ensure_anagrafica_table()` nel `setUp`/`setUpTestData` dei test — vedi convenzione già in uso in `tests.py`. `dipendente_anagrafica_aziendale_save` invece **non** tocca la tabella legacy (lavora solo su `DipendenteAnagraficaAziendale`), quindi i suoi test non ne hanno bisogno.
- Non toccare `RepartoAreaAziendaleModelTests`/`AreeRepartiCrudTests`/`OrganigrammaTests` in `tests.py`: restano fuori scope, il piano lavora solo sul lato "dipendente" della gerarchia.
- Se in dev il DB ha ancora lo schema pre-`0082` (drift da un'altra sessione), rilanciare `python django_app\manage.py migrate --settings=config.settings.dev` prima di verificare manualmente in browser.
